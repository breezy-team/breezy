# (C) 2005, 2006 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for bzrdir implementations - tests a bzrdir format."""

import os
from stat import *
import sys

import bzrlib.branch
import bzrlib.bzrdir as bzrdir
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.check import check
from bzrlib.commit import commit
import bzrlib.errors as errors
from bzrlib.errors import (FileExists,
                           NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
import bzrlib.repository as repository
from bzrlib.tests import (
                          ChrootedTestCase,
                          TestCase,
                          TestCaseWithTransport,
                          TestSkipped,
                          )
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
import bzrlib.transport as transport
from bzrlib.transport import get_transport
import bzrlib.ui as ui
from bzrlib.upgrade import upgrade
import bzrlib.workingtree as workingtree


class TestCaseWithBzrDir(TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithBzrDir, self).setUp()
        self.bzrdir = None

    def get_bzrdir(self):
        if self.bzrdir is None:
            self.bzrdir = self.make_bzrdir(None)
        return self.bzrdir

    def make_bzrdir(self, relpath):
        try:
            url = self.get_url(relpath)
            segments = url.split('/')
            if segments and segments[-1] not in ('', '.'):
                parent = '/'.join(segments[:-1])
                t = get_transport(parent)
                try:
                    t.mkdir(segments[-1])
                except FileExists:
                    pass
            return self.bzrdir_format.initialize(url)
        except UninitializableFormat:
            raise TestSkipped("Format %s is not initializable.")


class TestBzrDir(TestCaseWithBzrDir):
    # Many of these tests test for disk equality rather than checking
    # for semantic equivalence. This works well for some tests but
    # is not good at handling changes in representation or the addition
    # or removal of control data. It would be nice to for instance:
    # sprout a new branch, check that the nickname has been reset by hand
    # and then set the nickname to match the source branch, at which point
    # a semantic equivalence should pass

    def assertDirectoriesEqual(self, source, target, ignore_list=[]):
        """Assert that the content of source and target are identical.

        paths in ignore list will be completely ignored.
        """
        files = []
        directories = ['.']
        while directories:
            dir = directories.pop()
            for path in source.list_dir(dir):
                path = dir + '/' + path
                if path in ignore_list:
                    continue
                stat = source.stat(path)
                if S_ISDIR(stat.st_mode):
                    self.assertTrue(S_ISDIR(target.stat(path).st_mode))
                    directories.append(path)
                else:
                    self.assertEqualDiff(source.get(path).read(),
                                         target.get(path).read(),
                                         "text for file %r differs:\n" % path)

    def test_clone_bzrdir_empty(self):
        dir = self.make_bzrdir('source')
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)
    
    def test_clone_bzrdir_empty_force_new_ignored(self):
        # the force_new_repo parameter should have no effect on an empty
        # bzrdir's clone logic
        dir = self.make_bzrdir('source')
        target = dir.clone(self.get_url('target'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)
    
    def test_clone_bzrdir_repository(self):
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        # add some content to differentiate from an empty repository.
        repo.control_weaves.add_text('inventory',
                                     "A",
                                     [],
                                     [],
                                     repo.get_transaction())
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_clone_bzrdir_repository_under_shared(self):
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        # add some content to differentiate from an empty repository.
        repo.control_weaves.add_text('inventory',
                                     "A",
                                     [],
                                     [],
                                     repo.get_transaction())
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.clone(self.get_url('target/child'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertRaises(errors.NoRepositoryPresent, target.open_repository)
        
    def test_clone_bzrdir_repository_under_shared_force_new_repo(self):
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        # add some content to differentiate from an empty repository.
        repo.control_weaves.add_text('inventory',
                                     "A",
                                     [],
                                     [],
                                     repo.get_transaction())
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.clone(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_clone_bzrdir_repository_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a repository with some revisions,
        # and clone it with a revision limit.
        # 
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_last_revision(None)
        tree.commit('revision 2', rev_id='2')
        source = self.make_repository('source')
        tree.bzrdir.open_repository().copy_content_into(source)
        dir = source.bzrdir
        target = dir.clone(self.get_url('target'), revision_id='2')
        raise TestSkipped('revision limiting not strict yet')

    def test_clone_bzrdir_branch_and_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.bzrdir.open_repository().copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache', './.bzr/checkout/stat-cache'])

    def test_clone_bzrdir_branch_and_repo_into_shared_repo(self):
        # by default cloning into a shared repo uses the shared repo.
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.bzrdir.open_repository().copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        dir = source.bzrdir
        target = dir.clone(self.get_url('target/child'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertRaises(errors.NoRepositoryPresent, target.open_repository)
        self.assertEqual(source.revision_history(),
                         target.open_branch().revision_history())

    def test_clone_bzrdir_branch_and_repo_into_shared_repo_force_new_repo(self):
        # by default cloning into a shared repo uses the shared repo.
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.bzrdir.open_repository().copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        dir = source.bzrdir
        target = dir.clone(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        target.open_repository()
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_clone_bzrdir_branch_reference(self):
        # cloning should preserve the reference status of the branch in a bzrdir
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_clone_bzrdir_branch_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a branch with some revisions,
        # and clone it with a revision limit.
        # 
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        source = self.make_branch('source')
        tree.bzrdir.open_repository().copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        target = dir.clone(self.get_url('target'), revision_id='1')
        self.assertEqual('1', target.open_branch().last_revision())
        
    def test_clone_bzrdir_tree_branch_repo(self):
        tree = self.make_branch_and_tree('sourcce')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1')
        dir = tree.bzrdir
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache', './.bzr/checkout/stat-cache'])

    def test_clone_bzrdir_tree_branch_reference(self):
        # a tree with a branch reference (aka a checkout) 
        # should stay a checkout on clone.
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        dir.create_workingtree()
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache', './.bzr/checkout/stat-cache'])

    def test_clone_bzrdir_tree_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a tree with a revision with a last-revision
        # and clone it with a revision limit.
        # This smoke test just checks the revision-id is right. Tree specific
        # tests will check corner cases.
        tree = self.make_branch_and_tree('source')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        dir = tree.bzrdir
        target = dir.clone(self.get_url('target'), revision_id='1')
        self.assertEqual('1', target.open_workingtree().last_revision())

    def test_clone_bzrdir_incomplete_source_with_basis(self):
        # ensure that basis really does grab from the basis by having incomplete source
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_branch_and_tree('source')
        # this gives us an incomplete repository
        tree.bzrdir.open_repository().copy_content_into(source.branch.repository)
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        tree.bzrdir.open_branch().copy_content_into(source.branch)
        tree.copy_content_into(source)
        self.assertFalse(source.branch.repository.has_revision('2'))
        dir = source.bzrdir
        target = dir.clone(self.get_url('target'), basis=tree.bzrdir)
        self.assertEqual('2', target.open_branch().last_revision())
        self.assertEqual('2', target.open_workingtree().last_revision())
        self.assertTrue(target.open_branch().repository.has_revision('2'))

    def test_sprout_bzrdir_empty(self):
        dir = self.make_bzrdir('source')
        target = dir.sprout(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # creates a new repository branch and tree
        target.open_repository()
        target.open_branch()
        target.open_workingtree()

    def test_sprout_bzrdir_empty_under_shared_repo(self):
        # sprouting an empty dir into a repo uses the repo
        dir = self.make_bzrdir('source')
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.sprout(self.get_url('target/child'))
        self.assertRaises(errors.NoRepositoryPresent, target.open_repository)
        target.open_branch()
        target.open_workingtree()

    def test_sprout_bzrdir_empty_under_shared_repo(self):
        # the force_new_repo parameter should force use of a new repo in an empty
        # bzrdir's sprout logic
        dir = self.make_bzrdir('source')
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.sprout(self.get_url('target/child'), force_new_repo=True)
        target.open_repository()
        target.open_branch()
        target.open_workingtree()
    
    def test_sprout_bzrdir_repository(self):
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        # add some content to differentiate from an empty repository.
        repo.control_weaves.add_text('inventory',
                                     "A",
                                     [],
                                     [],
                                     repo.get_transaction())
        target = dir.sprout(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_sprout_bzrdir_repository_under_shared(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_last_revision(None)
        tree.commit('revision 2', rev_id='2')
        source = self.make_repository('source')
        tree.bzrdir.open_repository().copy_content_into(source)
        dir = source.bzrdir
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.sprout(self.get_url('target/child'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertTrue(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_repository_under_shared_force_new_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_last_revision(None)
        tree.commit('revision 2', rev_id='2')
        source = self.make_repository('source')
        tree.bzrdir.open_repository().copy_content_into(source)
        dir = source.bzrdir
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.sprout(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertFalse(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_repository_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a repository with some revisions,
        # and sprout it with a revision limit.
        # 
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_last_revision(None)
        tree.commit('revision 2', rev_id='2')
        source = self.make_repository('source')
        tree.bzrdir.open_repository().copy_content_into(source)
        dir = source.bzrdir
        target = dir.sprout(self.get_url('target'), revision_id='2')
        raise TestSkipped('revision limiting not strict yet')

    def test_sprout_bzrdir_branch_and_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.bzrdir.open_repository().copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        target = dir.sprout(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_sprout_bzrdir_branch_and_repo_shared(self):
        # sprouting a branch with a repo into a shared repo uses the shared
        # repo
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_branch('source')
        tree.bzrdir.open_repository().copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.sprout(self.get_url('target/child'))
        self.assertTrue(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_branch_and_repo_shared_force_new_repo(self):
        # sprouting a branch with a repo into a shared repo uses the shared
        # repo
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_branch('source')
        tree.bzrdir.open_repository().copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.sprout(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertFalse(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_branch_reference(self):
        # sprouting should create a repository if needed and a sprouted branch.
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        target = dir.sprout(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and as we dont support repositories being detached yet, a repo in 
        # place
        target.open_repository()

    def test_sprout_bzrdir_branch_reference_shared(self):
        # sprouting should create a repository if needed and a sprouted branch.
        referenced_tree = self.make_branch_and_tree('referenced')
        referenced_tree.commit('1', rev_id='1', allow_pointless=True)
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_tree.branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.sprout(self.get_url('target/child'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and we want no repository as the target is shared
        self.assertRaises(errors.NoRepositoryPresent, 
                          target.open_repository)
        # and we want revision '1' in the shared repo
        self.assertTrue(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_branch_reference_shared_force_new_repo(self):
        # sprouting should create a repository if needed and a sprouted branch.
        referenced_tree = self.make_branch_and_tree('referenced')
        referenced_tree.commit('1', rev_id='1', allow_pointless=True)
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_tree.branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.sprout(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and we want revision '1' in the new repo
        self.assertTrue(target.open_repository().has_revision('1'))
        # but not the shared one
        self.assertFalse(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_branch_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a repository with some revisions,
        # and sprout it with a revision limit.
        # 
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        source = self.make_branch('source')
        tree.bzrdir.open_repository().copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        target = dir.sprout(self.get_url('target'), revision_id='1')
        self.assertEqual('1', target.open_branch().last_revision())
        
    def test_sprout_bzrdir_tree_branch_repo(self):
        tree = self.make_branch_and_tree('sourcce')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1')
        dir = tree.bzrdir
        target = dir.sprout(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache', './.bzr/checkout/stat-cache'])

    def test_sprout_bzrdir_tree_branch_reference(self):
        # sprouting should create a repository if needed and a sprouted branch.
        # the tree state should be copied.
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        dir.create_workingtree()
        target = dir.sprout(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and as we dont support repositories being detached yet, a repo in 
        # place
        target.open_repository()
        # we trust that the working tree sprouting works via the other tests.
        target.open_workingtree()

    def test_sprout_bzrdir_tree_branch_reference_revision(self):
        # sprouting should create a repository if needed and a sprouted branch.
        # the tree state should be copied but the revision changed,
        # and the likewise the new branch should be truncated too
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        tree = dir.create_workingtree()
        self.build_tree(['foo'], transport=dir.root_transport)
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        target = dir.sprout(self.get_url('target'), revision_id='1')
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and as we dont support repositories being detached yet, a repo in 
        # place
        target.open_repository()
        # we trust that the working tree sprouting works via the other tests.
        self.assertEqual('1', target.open_workingtree().last_revision())
        self.assertEqual('1', target.open_branch().last_revision())

    def test_sprout_bzrdir_tree_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a tree with a revision with a last-revision
        # and sprout it with a revision limit.
        # This smoke test just checks the revision-id is right. Tree specific
        # tests will check corner cases.
        tree = self.make_branch_and_tree('source')
        self.build_tree(['foo'], transport=tree.bzrdir.root_transport)
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        dir = tree.bzrdir
        target = dir.sprout(self.get_url('target'), revision_id='1')
        self.assertEqual('1', target.open_workingtree().last_revision())

    def test_sprout_bzrdir_incomplete_source_with_basis(self):
        # ensure that basis really does grab from the basis by having incomplete source
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.root_transport)
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_branch_and_tree('source')
        # this gives us an incomplete repository
        tree.bzrdir.open_repository().copy_content_into(source.branch.repository)
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        tree.bzrdir.open_branch().copy_content_into(source.branch)
        tree.copy_content_into(source)
        self.assertFalse(source.branch.repository.has_revision('2'))
        dir = source.bzrdir
        target = dir.sprout(self.get_url('target'), basis=tree.bzrdir)
        self.assertEqual('2', target.open_branch().last_revision())
        self.assertEqual('2', target.open_workingtree().last_revision())
        self.assertTrue(target.open_branch().repository.has_revision('2'))

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        t = get_transport(self.get_url())
        readonly_t = get_transport(self.get_readonly_url())
        made_control = self.bzrdir_format.initialize(t.base)
        self.failUnless(isinstance(made_control, bzrdir.BzrDir))
        self.assertEqual(self.bzrdir_format,
                         bzrdir.BzrDirFormat.find_format(readonly_t))
        direct_opened_dir = self.bzrdir_format.open(readonly_t)
        opened_dir = bzrdir.BzrDir.open(t.base)
        self.assertEqual(made_control._format,
                         opened_dir._format)
        self.assertEqual(direct_opened_dir._format,
                         opened_dir._format)
        self.failUnless(isinstance(opened_dir, bzrdir.BzrDir))

    def test_open_not_bzrdir(self):
        # test the formats specific behaviour for no-content or similar dirs.
        self.assertRaises(NotBranchError,
                          self.bzrdir_format.open,
                          get_transport(self.get_readonly_url()))

    def test_create_branch(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        made_branch = made_control.create_branch()
        self.failUnless(isinstance(made_branch, bzrlib.branch.Branch))
        self.assertEqual(made_control, made_branch.bzrdir)
        
    def test_open_branch(self):
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        made_branch = made_control.create_branch()
        opened_branch = made_control.open_branch()
        self.assertEqual(made_control, opened_branch.bzrdir)
        self.failUnless(isinstance(opened_branch, made_branch.__class__))
        self.failUnless(isinstance(opened_branch._format, made_branch._format.__class__))

    def test_create_repository(self):
        # a bzrdir can construct a repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        self.failUnless(isinstance(made_repo, repository.Repository))
        self.assertEqual(made_control, made_repo.bzrdir)
        
    def test_open_repository(self):
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        opened_repo = made_control.open_repository()
        self.assertEqual(made_control, opened_repo.bzrdir)
        self.failUnless(isinstance(opened_repo, made_repo.__class__))
        self.failUnless(isinstance(opened_repo._format, made_repo._format.__class__))

    def test_create_workingtree(self):
        # a bzrdir can construct a working tree for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # this has to be tested with local access as we still support creating 
        # format 6 bzrdirs
        t = get_transport('.')
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        made_branch = made_control.create_branch()
        made_tree = made_control.create_workingtree()
        self.failUnless(isinstance(made_tree, workingtree.WorkingTree))
        self.assertEqual(made_control, made_tree.bzrdir)
        
    def test_create_workingtree_revision(self):
        # a bzrdir can construct a working tree for itself @ a specific revision.
        source = self.make_branch_and_tree('source')
        source.commit('a', rev_id='a', allow_pointless=True)
        source.commit('b', rev_id='b', allow_pointless=True)
        self.build_tree(['new/'])
        made_control = self.bzrdir_format.initialize('new')
        source.branch.repository.clone(made_control)
        source.branch.clone(made_control)
        made_tree = made_control.create_workingtree(revision_id='a')
        self.assertEqual('a', made_tree.last_revision())
        
    def test_open_workingtree(self):
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # this has to be tested with local access as we still support creating 
        # format 6 bzrdirs
        t = get_transport('.')
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        made_branch = made_control.create_branch()
        made_tree = made_control.create_workingtree()
        opened_tree = made_control.open_workingtree()
        self.assertEqual(made_control, opened_tree.bzrdir)
        self.failUnless(isinstance(opened_tree, made_tree.__class__))
        self.failUnless(isinstance(opened_tree._format, made_tree._format.__class__))

    def test_get_branch_transport(self):
        dir = self.make_bzrdir('.')
        # without a format, get_branch_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(isinstance(dir.get_branch_transport(None),
                                   transport.Transport))
        # with a given format, either the bzr dir supports identifiable
        # branches, or it supports anonymous  branch formats, but not both.
        anonymous_format = bzrlib.branch.BzrBranchFormat4()
        identifiable_format = bzrlib.branch.BzrBranchFormat5()
        try:
            found_transport = dir.get_branch_transport(anonymous_format)
            self.assertRaises(errors.IncompatibleFormat,
                              dir.get_branch_transport,
                              identifiable_format)
        except errors.IncompatibleFormat:
            found_transport = dir.get_branch_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must be statable.
        found_transport.stat('.')

    def test_get_repository_transport(self):
        dir = self.make_bzrdir('.')
        # without a format, get_repository_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(isinstance(dir.get_repository_transport(None),
                                   transport.Transport))
        # with a given format, either the bzr dir supports identifiable
        # repositoryes, or it supports anonymous  repository formats, but not both.
        anonymous_format = repository.RepositoryFormat6()
        identifiable_format = repository.RepositoryFormat7()
        try:
            found_transport = dir.get_repository_transport(anonymous_format)
            self.assertRaises(errors.IncompatibleFormat,
                              dir.get_repository_transport,
                              identifiable_format)
        except errors.IncompatibleFormat:
            found_transport = dir.get_repository_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must be statable.
        found_transport.stat('.')

    def test_get_workingtree_transport(self):
        dir = self.make_bzrdir('.')
        # without a format, get_workingtree_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(isinstance(dir.get_workingtree_transport(None),
                                   transport.Transport))
        # with a given format, either the bzr dir supports identifiable
        # trees, or it supports anonymous tree formats, but not both.
        anonymous_format = workingtree.WorkingTreeFormat2()
        identifiable_format = workingtree.WorkingTreeFormat3()
        try:
            found_transport = dir.get_workingtree_transport(anonymous_format)
            self.assertRaises(errors.IncompatibleFormat,
                              dir.get_workingtree_transport,
                              identifiable_format)
        except errors.IncompatibleFormat:
            found_transport = dir.get_workingtree_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must be statable.
        found_transport.stat('.')

    def test_root_transport(self):
        dir = self.make_bzrdir('.')
        self.assertEqual(dir.root_transport.base,
                         get_transport(self.get_url('.')).base)

    def test_find_repository_no_repo_under_standalone_branch(self):
        # finding a repo stops at standalone branches even if there is a
        # higher repository available.
        try:
            repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        url = self.get_url('intermediate')
        get_transport(self.get_url()).mkdir('intermediate')
        get_transport(self.get_url()).mkdir('intermediate/child')
        made_control = self.bzrdir_format.initialize(url)
        made_control.create_repository()
        innermost_control = self.bzrdir_format.initialize(
            self.get_url('intermediate/child'))
        try:
            child_repo = innermost_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        self.assertRaises(errors.NoRepositoryPresent,
                          innermost_control.find_repository)

    def test_find_repository_containing_shared_repository(self):
        # find repo inside a shared repo with an empty control dir
        # returns the shared repo.
        try:
            repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        url = self.get_url('childbzrdir')
        get_transport(self.get_url()).mkdir('childbzrdir')
        made_control = self.bzrdir_format.initialize(url)
        try:
            child_repo = made_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        found_repo = made_control.find_repository()
        self.assertEqual(repo.bzrdir.root_transport.base,
                         found_repo.bzrdir.root_transport.base)
        
    def test_find_repository_standalone_with_containing_shared_repository(self):
        # find repo inside a standalone repo inside a shared repo finds the standalone repo
        try:
            containing_repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        child_repo = self.make_repository('childrepo')
        opened_control = bzrdir.BzrDir.open(self.get_url('childrepo'))
        found_repo = opened_control.find_repository()
        self.assertEqual(child_repo.bzrdir.root_transport.base,
                         found_repo.bzrdir.root_transport.base)

    def test_find_repository_shared_within_shared_repository(self):
        # find repo at a shared repo inside a shared repo finds the inner repo
        try:
            containing_repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        url = self.get_url('childrepo')
        get_transport(self.get_url()).mkdir('childrepo')
        child_control = self.bzrdir_format.initialize(url)
        child_repo = child_control.create_repository(shared=True)
        opened_control = bzrdir.BzrDir.open(self.get_url('childrepo'))
        found_repo = opened_control.find_repository()
        self.assertEqual(child_repo.bzrdir.root_transport.base,
                         found_repo.bzrdir.root_transport.base)
        self.assertNotEqual(child_repo.bzrdir.root_transport.base,
                            containing_repo.bzrdir.root_transport.base)

    def test_find_repository_with_nested_dirs_works(self):
        # find repo inside a bzrdir inside a bzrdir inside a shared repo 
        # finds the outer shared repo.
        try:
            repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        url = self.get_url('intermediate')
        get_transport(self.get_url()).mkdir('intermediate')
        get_transport(self.get_url()).mkdir('intermediate/child')
        made_control = self.bzrdir_format.initialize(url)
        try:
            child_repo = made_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        innermost_control = self.bzrdir_format.initialize(
            self.get_url('intermediate/child'))
        try:
            child_repo = innermost_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        found_repo = innermost_control.find_repository()
        self.assertEqual(repo.bzrdir.root_transport.base,
                         found_repo.bzrdir.root_transport.base)
        
    def test_can_and_needs_format_conversion(self):
        # check that we can ask an instance if its upgradable
        dir = self.make_bzrdir('.')
        if dir.can_convert_format():
            # if its updatable there must be an updater
            self.assertTrue(isinstance(dir._format.get_converter(),
                                       bzrdir.Converter))
        dir.needs_format_conversion(None)

    def test_upgrade_new_instance(self):
        """Does an available updater work ?."""
        dir = self.make_bzrdir('.')
        if dir.can_convert_format():
            dir._format.get_converter(None).convert(dir, ui.ui_factory.progress_bar())
            # and it should pass 'check' now.
            check(bzrdir.BzrDir.open(self.get_url('.')).open_branch(), False)


class ChrootedBzrDirTests(ChrootedTestCase):

    def test_find_repository_no_repository(self):
        # loopback test to check the current format fails to find a 
        # share repository correctly.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        url = self.get_url('subdir')
        get_transport(self.get_url()).mkdir('subdir')
        made_control = self.bzrdir_format.initialize(url)
        try:
            repo = made_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        opened_control = bzrdir.BzrDir.open(self.get_readonly_url('subdir'))
        self.assertRaises(errors.NoRepositoryPresent,
                          opened_control.find_repository)

