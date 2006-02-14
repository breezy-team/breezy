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
import sys

import bzrlib.bzrdir as bzrdir
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.commit import commit
import bzrlib.errors as errors
from bzrlib.errors import (FileExists,
                           NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
import bzrlib.repository as repository
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from bzrlib.transport import get_transport
from bzrlib.upgrade import upgrade
from bzrlib.workingtree import WorkingTree


class TestCaseWithRepository(TestCaseWithBzrDir):

    def setUp(self):
        super(TestCaseWithRepository, self).setUp()

    def make_branch(self, relpath):
        repo = self.make_repository(relpath)
        return repo.bzrdir.create_branch()

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

    def make_repository(self, relpath):
        made_control = self.make_bzrdir(relpath)
        return self.repository_format.initialize(made_control)


class TestRepository(TestCaseWithRepository):

    def test_clone_to_default_format(self):
        #TODO: Test that cloning a repository preserves all the information
        # such as signatures[not tested yet] etc etc.
        # when changing to the current default format.
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        bzrdirb = self.make_bzrdir('b')
        repo_b = tree_a.branch.repository.clone(bzrdirb)
        tree_b = repo_b.revision_tree('rev1')
        tree_b.get_file_text('file1')
        rev1 = repo_b.get_revision('rev1')

    def test_clone_specific_format(self):
        """todo"""

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.repository_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        t = get_transport(self.get_url())
        readonly_t = get_transport(self.get_readonly_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = self.repository_format.initialize(made_control)
        self.failUnless(isinstance(made_repo, repository.Repository))
        self.assertEqual(made_control, made_repo.bzrdir)

        # find it via bzrdir opening:
        opened_control = bzrdir.BzrDir.open(readonly_t.base)
        direct_opened_repo = opened_control.open_repository()
        self.assertEqual(direct_opened_repo.__class__, made_repo.__class__)
        self.assertEqual(opened_control, direct_opened_repo.bzrdir)

        self.failUnless(isinstance(direct_opened_repo._format,
                        self.repository_format.__class__))
        # find it via Repository.open
        opened_repo = repository.Repository.open(readonly_t.base)
        self.failUnless(isinstance(opened_repo, made_repo.__class__))
        self.assertEqual(made_repo._format.__class__,
                         opened_repo._format.__class__)
        # if it has a unique id string, can we probe for it ?
        try:
            self.repository_format.get_format_string()
        except NotImplementedError:
            return
        self.assertEqual(self.repository_format,
                         repository.RepositoryFormat.find_format(opened_control))

    def test_create_repository(self):
        # a repository can be constructedzrdir can construct a repository for itself.
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

    def test_revision_tree(self):
        wt = self.make_branch_and_tree('.')
        wt.commit('lala!', rev_id='revision-1', allow_pointless=True)
        tree = wt.branch.repository.revision_tree('revision-1')
        self.assertEqual(list(tree.list_files()), [])
        tree = wt.branch.repository.revision_tree(None)
        self.assertEqual(len(tree.list_files()), 0)
        tree = wt.branch.repository.revision_tree(NULL_REVISION)
        self.assertEqual(len(tree.list_files()), 0)

    def test_fetch(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        def check_push_rev1(repo):
            # ensure the revision is missing.
            self.assertRaises(NoSuchRevision, repo.get_revision, 'rev1')
            # fetch with a limit of NULL_REVISION
            repo.fetch(tree_a.branch.repository, NULL_REVISION)
            # nothing should have been pushed
            self.assertFalse(repo.has_revision('rev1'))
            # fetch with a default limit (grab everything)
            repo.fetch(tree_a.branch.repository)
            # check that b now has all the data from a's first commit.
            rev = repo.get_revision('rev1')
            tree = repo.revision_tree('rev1')
            tree.get_file_text('file1')
            for file_id in tree:
                if tree.inventory[file_id].kind == "file":
                    tree.get_file(file_id).read()

        # makes a latest-version repo 
        repo_b = bzrdir.BzrDir.create_repository(self.get_url('b'))
        check_push_rev1(repo_b)

        # makes a this-version repo:
        repo_c = self.make_repository('c')
        check_push_rev1(repo_c)

    def test_clone_bzrdir_repository_revision(self):
        # make a repository with some revisions,
        # and clone it, this should not have unreferenced revisions.
        # also: test cloning with a revision id of NULL_REVISION -> empty repo.
        raise TestSkipped('revision limiting is not implemented yet.')

    def test_clone_repository_basis_revision(self):
        raise TestSkipped('the use of a basis should not add noise data to the result.')

    def test_clone_repository_incomplete_source_with_basis(self):
        # ensure that basis really does grab from the basis by having incomplete source
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_repository('source')
        # this gives us an incomplete repository
        tree.bzrdir.open_repository().copy_content_into(source)
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        self.assertFalse(source.has_revision('2'))
        target = source.bzrdir.clone(self.get_url('target'), basis=tree.bzrdir)
        self.assertTrue(target.open_repository().has_revision('2'))


class TestCaseWithComplexRepository(TestCaseWithRepository):

    def setUp(self):
        super(TestCaseWithComplexRepository, self).setUp()
        tree_a = self.make_branch_and_tree('a')
        self.bzrdir = tree_a.branch.bzrdir
        # add a corrupt inventory 'orphan'
        tree_a.branch.repository.control_weaves.add_text(
            'inventory', 'orphan', [], [],
            tree_a.branch.repository.get_transaction())
        # add a real revision 'rev1'
        tree_a.commit('rev1', rev_id='rev1', allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        tree_a.commit('rev2', rev_id='rev2', allow_pointless=True)

    def test_all_revision_ids(self):
        # all_revision_ids -> all revisions
        self.assertEqual(['rev1', 'rev2'],
                         self.bzrdir.open_repository().all_revision_ids())

    def test_missing_revision_ids(self):
        # revision ids in repository A but not B are returned, fake ones
        # are stripped. (fake meaning no revision object, but an inventory 
        # as some formats keyed off inventory data in the past.
        # make a repository to compare against that claims to have rev1
        tree_b = self.make_branch_and_tree('rev1_only')
        # add a real revision 'rev1'
        tree_b.commit('rev1', rev_id='rev1', allow_pointless=True)
        repo_a = self.bzrdir.open_repository()
        repo_b = tree_b.branch.repository
        self.assertEqual(['rev2'],
                         repo_b.missing_revision_ids(repo_a))

    def test_missing_revision_ids_default_format(self):
        # revision ids in repository A but not B are returned, fake ones
        # are stripped. (fake meaning no revision object, but an inventory 
        # as some formats keyed off inventory data in the past.
        # make a repository to compare against that claims to have rev1
        tree_b = bzrdir.BzrDir.create_standalone_workingtree('rev1_only')
        # add a real revision 'rev1'
        tree_b.commit('rev1', rev_id='rev1', allow_pointless=True)
        repo_a = self.bzrdir.open_repository()
        repo_b = tree_b.branch.repository
        self.assertEqual(['rev2'],
                         repo_b.missing_revision_ids(repo_a))

    def test_missing_revision_ids_revision_limited(self):
        # revision ids in repository A that are not referenced by the
        # requested revision are not returned.
        # make a repository to compare against that is empty
        tree_b = self.make_branch_and_tree('empty')
        repo_a = self.bzrdir.open_repository()
        repo_b = tree_b.branch.repository
        self.assertEqual(['rev1'],
                         repo_b.missing_revision_ids(repo_a, revision_id='rev1'))

    def test_get_ancestry_missing_revision(self):
        # get_ancestry(missing revision)-> NoSuchRevision
        self.assertRaises(errors.NoSuchRevision,
                          self.bzrdir.open_repository().get_ancestry, 'orphan')
        
