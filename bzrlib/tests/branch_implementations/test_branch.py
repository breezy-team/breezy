# Copyright (C) 2005, 2006 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for branch implementations - tests a branch format."""

import os
import sys

from bzrlib import (
    branch,
    bzrdir,
    errors,
    gpg,
    urlutils,
    transactions,
    remote,
    repository,
    )
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.delta import TreeDelta
from bzrlib.errors import (FileExists,
                           NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
from bzrlib.osutils import getcwd
import bzrlib.revision
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.tests.HttpServer import HttpServer
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryServer
from bzrlib.upgrade import upgrade
from bzrlib.workingtree import WorkingTree


class TestCaseWithBranch(TestCaseWithBzrDir):

    def setUp(self):
        super(TestCaseWithBranch, self).setUp()
        self.branch = None

    def get_branch(self):
        if self.branch is None:
            self.branch = self.make_branch('')
        return self.branch

    def make_branch(self, relpath, format=None):
        repo = self.make_repository(relpath, format=format)
        # fixme RBC 20060210 this isnt necessarily a fixable thing,
        # Skipped is the wrong exception to raise.
        try:
            return self.branch_format.initialize(repo.bzrdir)
        except errors.UninitializableFormat:
            raise TestSkipped('Uninitializable branch format')

    def make_repository(self, relpath, shared=False, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        return made_control.create_repository(shared=shared)


class TestBranch(TestCaseWithBranch):

    def test_append_revisions(self):
        """Test appending more than one revision"""
        wt = self.make_branch_and_tree('tree')
        wt.commit('f', rev_id='rev1')
        wt.commit('f', rev_id='rev2')
        wt.commit('f', rev_id='rev3')

        br = self.get_branch()
        br.fetch(wt.branch)
        br.append_revision("rev1")
        self.assertEquals(br.revision_history(), ["rev1",])
        br.append_revision("rev2", "rev3")
        self.assertEquals(br.revision_history(), ["rev1", "rev2", "rev3"])
        self.assertRaises(errors.ReservedId, br.append_revision, 'current:')

    def test_revision_ids_are_utf8(self):
        wt = self.make_branch_and_tree('tree')
        wt.commit('f', rev_id='rev1')
        wt.commit('f', rev_id='rev2')
        wt.commit('f', rev_id='rev3')

        br = self.get_branch()
        br.fetch(wt.branch)
        br.set_revision_history(['rev1', 'rev2', 'rev3'])
        rh = br.revision_history()
        self.assertEqual(['rev1', 'rev2', 'rev3'], rh)
        for revision_id in rh:
            self.assertIsInstance(revision_id, str)
        last = br.last_revision()
        self.assertEqual('rev3', last)
        self.assertIsInstance(last, str)
        revno, last = br.last_revision_info()
        self.assertEqual(3, revno)
        self.assertEqual('rev3', last)
        self.assertIsInstance(last, str)

    def test_fetch_revisions(self):
        """Test fetch-revision operation."""
        wt = self.make_branch_and_tree('b1')
        b1 = wt.branch
        self.build_tree_contents([('b1/foo', 'hello')])
        wt.add(['foo'], ['foo-id'])
        wt.commit('lala!', rev_id='revision-1', allow_pointless=False)

        b2 = self.make_branch('b2')
        self.assertEqual((1, []), b2.fetch(b1))

        rev = b2.repository.get_revision('revision-1')
        tree = b2.repository.revision_tree('revision-1')
        self.assertEqual(tree.get_file_text('foo-id'), 'hello')

    def test_get_revision_delta(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        self.build_tree(['a/vla'])
        tree_a.add('vla', 'file2')
        tree_a.commit('rev2', rev_id='rev2')

        delta = tree_a.branch.get_revision_delta(1)
        self.assertIsInstance(delta, TreeDelta)
        self.assertEqual([('foo', 'file1', 'file')], delta.added)
        delta = tree_a.branch.get_revision_delta(2)
        self.assertIsInstance(delta, TreeDelta)
        self.assertEqual([('vla', 'file2', 'file')], delta.added)

    def get_unbalanced_tree_pair(self):
        """Return two branches, a and b, with one file in a."""
        tree_a = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/b', 'b')])
        tree_a.add('b')
        tree_a.commit("silly commit", rev_id='A')

        tree_b = self.make_branch_and_tree('b')
        return tree_a, tree_b

    def get_balanced_branch_pair(self):
        """Returns br_a, br_b as with one commit in a, and b has a's stores."""
        tree_a, tree_b = self.get_unbalanced_tree_pair()
        tree_b.branch.repository.fetch(tree_a.branch.repository)
        return tree_a, tree_b

    def test_clone_partial(self):
        """Copy only part of the history of a branch."""
        # TODO: RBC 20060208 test with a revision not on revision-history.
        #       what should that behaviour be ? Emailed the list.
        # First, make a branch with two commits.
        wt_a = self.make_branch_and_tree('a')
        self.build_tree(['a/one'])
        wt_a.add(['one'])
        wt_a.commit('commit one', rev_id='1')
        self.build_tree(['a/two'])
        wt_a.add(['two'])
        wt_a.commit('commit two', rev_id='2')
        # Now make a copy of the repository.
        repo_b = self.make_repository('b')
        wt_a.branch.repository.copy_content_into(repo_b)
        # wt_a might be a lightweight checkout, so get a hold of the actual
        # branch (because you can't do a partial clone of a lightweight
        # checkout).
        branch = wt_a.branch.bzrdir.open_branch()
        # Then make a branch where the new repository is, but specify a revision
        # ID.  The new branch's history will stop at the specified revision.
        br_b = branch.clone(repo_b.bzrdir, revision_id='1')
        self.assertEqual('1', br_b.last_revision())

    def test_sprout_partial(self):
        # test sprouting with a prefix of the revision-history.
        # also needs not-on-revision-history behaviour defined.
        wt_a = self.make_branch_and_tree('a')
        self.build_tree(['a/one'])
        wt_a.add(['one'])
        wt_a.commit('commit one', rev_id='1')
        self.build_tree(['a/two'])
        wt_a.add(['two'])
        wt_a.commit('commit two', rev_id='2')
        repo_b = self.make_repository('b')
        repo_a = wt_a.branch.repository
        repo_a.copy_content_into(repo_b)
        br_b = wt_a.branch.sprout(repo_b.bzrdir, revision_id='1')
        self.assertEqual('1', br_b.last_revision())

    def get_parented_branch(self):
        wt_a = self.make_branch_and_tree('a')
        self.build_tree(['a/one'])
        wt_a.add(['one'])
        wt_a.commit('commit one', rev_id='1')

        branch_b = wt_a.bzrdir.sprout('b', revision_id='1').open_branch()
        self.assertEqual(wt_a.branch.base, branch_b.get_parent())
        return branch_b

    def test_clone_branch_nickname(self):
        # test the nick name is preserved always
        raise TestSkipped('XXX branch cloning is not yet tested..')

    def test_clone_branch_parent(self):
        # test the parent is preserved always
        branch_b = self.get_parented_branch()
        repo_c = self.make_repository('c')
        branch_b.repository.copy_content_into(repo_c)
        branch_c = branch_b.clone(repo_c.bzrdir)
        self.assertNotEqual(None, branch_c.get_parent())
        self.assertEqual(branch_b.get_parent(), branch_c.get_parent())

        # We can also set a specific parent, and it should be honored
        random_parent = 'http://bazaar-vcs.org/path/to/branch'
        branch_b.set_parent(random_parent)
        repo_d = self.make_repository('d')
        branch_b.repository.copy_content_into(repo_d)
        branch_d = branch_b.clone(repo_d.bzrdir)
        self.assertEqual(random_parent, branch_d.get_parent())

    def test_sprout_branch_nickname(self):
        # test the nick name is reset always
        raise TestSkipped('XXX branch sprouting is not yet tested..')

    def test_sprout_branch_parent(self):
        source = self.make_branch('source')
        target = source.bzrdir.sprout(self.get_url('target')).open_branch()
        self.assertEqual(source.bzrdir.root_transport.base, target.get_parent())

    def test_submit_branch(self):
        """Submit location can be queried and set"""
        branch = self.make_branch('branch')
        self.assertEqual(branch.get_submit_branch(), None)
        branch.set_submit_branch('sftp://example.com')
        self.assertEqual(branch.get_submit_branch(), 'sftp://example.com')
        branch.set_submit_branch('sftp://example.net')
        self.assertEqual(branch.get_submit_branch(), 'sftp://example.net')
        
    def test_public_branch(self):
        """public location can be queried and set"""
        branch = self.make_branch('branch')
        self.assertEqual(branch.get_public_branch(), None)
        branch.set_public_branch('sftp://example.com')
        self.assertEqual(branch.get_public_branch(), 'sftp://example.com')
        branch.set_public_branch('sftp://example.net')
        self.assertEqual(branch.get_public_branch(), 'sftp://example.net')
        branch.set_public_branch(None)
        self.assertEqual(branch.get_public_branch(), None)

    def test_record_initial_ghost(self):
        """Branches should support having ghosts."""
        wt = self.make_branch_and_tree('.')
        wt.set_parent_ids(['non:existent@rev--ision--0--2'],
            allow_leftmost_as_ghost=True)
        rev_id = wt.commit('commit against a ghost first parent.')
        rev = wt.branch.repository.get_revision(rev_id)
        self.assertEqual(rev.parent_ids, ['non:existent@rev--ision--0--2'])
        # parent_sha1s is not populated now, WTF. rbc 20051003
        self.assertEqual(len(rev.parent_sha1s), 0)

    def test_record_two_ghosts(self):
        """Recording with all ghosts works."""
        wt = self.make_branch_and_tree('.')
        wt.set_parent_ids([
                'foo@azkhazan-123123-abcabc',
                'wibble@fofof--20050401--1928390812',
            ],
            allow_leftmost_as_ghost=True)
        rev_id = wt.commit("commit from ghost base with one merge")
        # the revision should have been committed with two parents
        rev = wt.branch.repository.get_revision(rev_id)
        self.assertEqual(['foo@azkhazan-123123-abcabc',
            'wibble@fofof--20050401--1928390812'],
            rev.parent_ids)

    def test_bad_revision(self):
        self.assertRaises(errors.InvalidRevisionId,
                          self.get_branch().repository.get_revision,
                          None)

# TODO 20051003 RBC:
# compare the gpg-to-sign info for a commit with a ghost and 
#     an identical tree without a ghost
# fetch missing should rewrite the TOC of weaves to list newly available parents.
        
    def test_sign_existing_revision(self):
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        wt.commit("base", allow_pointless=True, rev_id='A')
        from bzrlib.testament import Testament
        strategy = gpg.LoopbackGPGStrategy(None)
        branch.repository.sign_revision('A', strategy)
        self.assertEqual('-----BEGIN PSEUDO-SIGNED CONTENT-----\n' +
                         Testament.from_revision(branch.repository,
                         'A').as_short_text() +
                         '-----END PSEUDO-SIGNED CONTENT-----\n',
                         branch.repository.get_signature_text('A'))

    def test_store_signature(self):
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        branch.repository.store_revision_signature(
            gpg.LoopbackGPGStrategy(None), 'FOO', 'A')
        self.assertRaises(errors.NoSuchRevision,
                          branch.repository.has_signature_for_revision_id,
                          'A')
        wt.commit("base", allow_pointless=True, rev_id='A')
        self.assertEqual('-----BEGIN PSEUDO-SIGNED CONTENT-----\n'
                         'FOO-----END PSEUDO-SIGNED CONTENT-----\n',
                         branch.repository.get_signature_text('A'))

    def test_branch_keeps_signatures(self):
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        repo = wt.branch.repository
        repo.sign_revision('A', gpg.LoopbackGPGStrategy(None))
        #FIXME: clone should work to urls,
        # wt.clone should work to disks.
        self.build_tree(['target/'])
        d2 = repo.bzrdir.clone(urlutils.local_path_to_url('target'))
        self.assertEqual(repo.get_signature_text('A'),
                         d2.open_repository().get_signature_text('A'))

    def test_nicks(self):
        """Test explicit and implicit branch nicknames.
        
        Nicknames are implicitly the name of the branch's directory, unless an
        explicit nickname is set.  That is, an explicit nickname always
        overrides the implicit one.
        """
        t = get_transport(self.get_url())
        branch = self.make_branch('bzr.dev')
        # The nick will be 'bzr.dev', because there is no explicit nick set.
        self.assertEqual(branch.nick, 'bzr.dev')
        # Move the branch to a different directory, 'bzr.ab'.  Now that branch
        # will report its nick as 'bzr.ab'.
        t.move('bzr.dev', 'bzr.ab')
        branch = Branch.open(self.get_url('bzr.ab'))
        self.assertEqual(branch.nick, 'bzr.ab')
        # Set the branch nick explicitly.  This will ensure there's a branch
        # config file in the branch.
        branch.nick = "Aaron's branch"
        branch.nick = "Aaron's branch"
        if not isinstance(branch, remote.RemoteBranch):
            controlfilename = branch.control_files.controlfilename
            self.failUnless(t.has(t.relpath(controlfilename("branch.conf"))))
        # Because the nick has been set explicitly, the nick is now always
        # "Aaron's branch", regardless of directory name.
        self.assertEqual(branch.nick, "Aaron's branch")
        t.move('bzr.ab', 'integration')
        branch = Branch.open(self.get_url('integration'))
        self.assertEqual(branch.nick, "Aaron's branch")
        branch.nick = u"\u1234"
        self.assertEqual(branch.nick, u"\u1234")

    def test_commit_nicks(self):
        """Nicknames are committed to the revision"""
        wt = self.make_branch_and_tree('bzr.dev')
        branch = wt.branch
        branch.nick = "My happy branch"
        wt.commit('My commit respect da nick.')
        committed = branch.repository.get_revision(branch.last_revision())
        self.assertEqual(committed.properties["branch-nick"],
                         "My happy branch")

    def test_create_open_branch_uses_repository(self):
        try:
            repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            return
        child_transport = repo.bzrdir.root_transport.clone('child')
        child_transport.mkdir('.')
        child_dir = self.bzrdir_format.initialize_on_transport(child_transport)
        try:
            child_branch = self.branch_format.initialize(child_dir)
        except errors.UninitializableFormat:
            # branch references are not default init'able.
            return
        self.assertEqual(repo.bzrdir.root_transport.base,
                         child_branch.repository.bzrdir.root_transport.base)
        child_branch = branch.Branch.open(self.get_url('child'))
        self.assertEqual(repo.bzrdir.root_transport.base,
                         child_branch.repository.bzrdir.root_transport.base)

    def test_format_description(self):
        tree = self.make_branch_and_tree('tree')
        text = tree.branch._format.get_format_description()
        self.failUnless(len(text))

    def test_check_branch_report_results(self):
        """Checking a branch produces results which can be printed"""
        branch = self.make_branch('.')
        result = branch.check()
        # reports results through logging
        result.report_results(verbose=True)
        result.report_results(verbose=False)

    def test_get_commit_builder(self):
        self.assertIsInstance(self.make_branch(".").get_commit_builder([]), 
            repository.CommitBuilder)

    def test_generate_revision_history(self):
        """Create a fake revision history easily."""
        tree = self.make_branch_and_tree('.')
        rev1 = tree.commit('foo')
        orig_history = tree.branch.revision_history()
        rev2 = tree.commit('bar', allow_pointless=True)
        tree.branch.generate_revision_history(rev1)
        self.assertEqual(orig_history, tree.branch.revision_history())

    def test_generate_revision_history_NULL_REVISION(self):
        tree = self.make_branch_and_tree('.')
        rev1 = tree.commit('foo')
        tree.branch.generate_revision_history(bzrlib.revision.NULL_REVISION)
        self.assertEqual([], tree.branch.revision_history())

    def test_create_checkout(self):
        tree_a = self.make_branch_and_tree('a')
        branch_a = tree_a.branch
        checkout_b = branch_a.create_checkout('b')
        self.assertEqual(None, checkout_b.last_revision())
        checkout_b.commit('rev1', rev_id='rev1')
        self.assertEqual('rev1', branch_a.last_revision())
        self.assertNotEqual(checkout_b.branch.base, branch_a.base)

        checkout_c = branch_a.create_checkout('c', lightweight=True)
        self.assertEqual('rev1', checkout_c.last_revision())
        checkout_c.commit('rev2', rev_id='rev2')
        self.assertEqual('rev2', branch_a.last_revision())
        self.assertEqual(checkout_c.branch.base, branch_a.base)

        os.mkdir('d')
        checkout_d = branch_a.create_checkout('d', lightweight=True)
        self.assertEqual('rev2', checkout_d.last_revision())
        os.mkdir('e')
        checkout_e = branch_a.create_checkout('e')
        self.assertEqual('rev2', checkout_e.last_revision())

    def test_create_anonymous_lightweight_checkout(self):
        """A lightweight checkout from a readonly branch should succeed."""
        tree_a = self.make_branch_and_tree('a')
        rev_id = tree_a.commit('put some content in the branch')
        # open the branch via a readonly transport
        source_branch = bzrlib.branch.Branch.open(self.get_readonly_url('a'))
        # sanity check that the test will be valid
        self.assertRaises((errors.LockError, errors.TransportNotPossible),
            source_branch.lock_write)
        checkout = source_branch.create_checkout('c', lightweight=True)
        self.assertEqual(rev_id, checkout.last_revision())

    def test_create_anonymous_heavyweight_checkout(self):
        """A regular checkout from a readonly branch should succeed."""
        tree_a = self.make_branch_and_tree('a')
        rev_id = tree_a.commit('put some content in the branch')
        # open the branch via a readonly transport
        source_branch = bzrlib.branch.Branch.open(self.get_readonly_url('a'))
        # sanity check that the test will be valid
        self.assertRaises((errors.LockError, errors.TransportNotPossible),
            source_branch.lock_write)
        checkout = source_branch.create_checkout('c')
        self.assertEqual(rev_id, checkout.last_revision())

    def test_set_revision_history(self):
        tree = self.make_branch_and_tree('a')
        tree.commit('a commit', rev_id='rev1')
        br = tree.branch
        br.set_revision_history(["rev1"])
        self.assertEquals(br.revision_history(), ["rev1"])
        br.set_revision_history([])
        self.assertEquals(br.revision_history(), [])


class ChrootedTests(TestCaseWithBranch):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.
    """

    def setUp(self):
        super(ChrootedTests, self).setUp()
        if not self.vfs_transport_factory == MemoryServer:
            self.transport_readonly_server = HttpServer

    def test_open_containing(self):
        self.assertRaises(NotBranchError, Branch.open_containing,
                          self.get_readonly_url(''))
        self.assertRaises(NotBranchError, Branch.open_containing,
                          self.get_readonly_url('g/p/q'))
        branch = self.make_branch('.')
        branch, relpath = Branch.open_containing(self.get_readonly_url(''))
        self.assertEqual('', relpath)
        branch, relpath = Branch.open_containing(self.get_readonly_url('g/p/q'))
        self.assertEqual('g/p/q', relpath)
        

class InstrumentedTransaction(object):

    def finish(self):
        self.calls.append('finish')

    def __init__(self):
        self.calls = []


class TestDecorator(object):

    def __init__(self):
        self._calls = []

    def lock_read(self):
        self._calls.append('lr')

    def lock_write(self):
        self._calls.append('lw')

    def unlock(self):
        self._calls.append('ul')

    @needs_read_lock
    def do_with_read(self):
        return 1

    @needs_read_lock
    def except_with_read(self):
        raise RuntimeError

    @needs_write_lock
    def do_with_write(self):
        return 2

    @needs_write_lock
    def except_with_write(self):
        raise RuntimeError


class TestDecorators(TestCase):

    def test_needs_read_lock(self):
        branch = TestDecorator()
        self.assertEqual(1, branch.do_with_read())
        self.assertEqual(['lr', 'ul'], branch._calls)

    def test_excepts_in_read_lock(self):
        branch = TestDecorator()
        self.assertRaises(RuntimeError, branch.except_with_read)
        self.assertEqual(['lr', 'ul'], branch._calls)

    def test_needs_write_lock(self):
        branch = TestDecorator()
        self.assertEqual(2, branch.do_with_write())
        self.assertEqual(['lw', 'ul'], branch._calls)

    def test_excepts_in_write_lock(self):
        branch = TestDecorator()
        self.assertRaises(RuntimeError, branch.except_with_write)
        self.assertEqual(['lw', 'ul'], branch._calls)


class TestBranchPushLocations(TestCaseWithBranch):

    def test_get_push_location_unset(self):
        self.assertEqual(None, self.get_branch().get_push_location())

    def test_get_push_location_exact(self):
        from bzrlib.config import (locations_config_filename,
                                   ensure_config_dir_exists)
        ensure_config_dir_exists()
        fn = locations_config_filename()
        print >> open(fn, 'wt'), ("[%s]\n"
                                  "push_location=foo" %
                                  self.get_branch().base[:-1])
        self.assertEqual("foo", self.get_branch().get_push_location())

    def test_set_push_location(self):
        branch = self.get_branch()
        branch.set_push_location('foo')
        self.assertEqual('foo', branch.get_push_location())


class TestFormat(TestCaseWithBranch):
    """Tests for the format itself."""

    def test_get_reference(self):
        """get_reference on all regular branches should return None."""
        if not self.branch_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        made_branch = self.make_branch('.')
        self.assertEqual(None,
            made_branch._format.get_reference(made_branch.bzrdir))

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.branch_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        t = get_transport(self.get_url())
        readonly_t = get_transport(self.get_readonly_url())
        made_branch = self.make_branch('.')
        self.failUnless(isinstance(made_branch, branch.Branch))

        # find it via bzrdir opening:
        opened_control = bzrdir.BzrDir.open(readonly_t.base)
        direct_opened_branch = opened_control.open_branch()
        self.assertEqual(direct_opened_branch.__class__, made_branch.__class__)
        self.assertEqual(opened_control, direct_opened_branch.bzrdir)
        self.failUnless(isinstance(direct_opened_branch._format,
                        self.branch_format.__class__))

        # find it via Branch.open
        opened_branch = branch.Branch.open(readonly_t.base)
        self.failUnless(isinstance(opened_branch, made_branch.__class__))
        self.assertEqual(made_branch._format.__class__,
                         opened_branch._format.__class__)
        # if it has a unique id string, can we probe for it ?
        try:
            self.branch_format.get_format_string()
        except NotImplementedError:
            return
        self.assertEqual(self.branch_format, opened_control.find_branch_format())


class TestBound(TestCaseWithBranch):

    def test_bind_unbind(self):
        branch = self.make_branch('1')
        branch2 = self.make_branch('2')
        try:
            branch.bind(branch2)
        except errors.UpgradeRequired:
            raise TestSkipped('Format does not support binding')
        self.assertTrue(branch.unbind())
        self.assertFalse(branch.unbind())
        self.assertIs(None, branch.get_bound_location())

    def test_old_bound_location(self):
        branch = self.make_branch('branch1')
        try:
            self.assertIs(None, branch.get_old_bound_location())
        except errors.UpgradeRequired:
            raise TestSkipped('Format does not store old bound locations')
        branch2 = self.make_branch('branch2')
        branch.bind(branch2)
        self.assertIs(None, branch.get_old_bound_location())
        branch.unbind()
        self.assertContainsRe(branch.get_old_bound_location(), '\/branch2\/$')


class TestStrict(TestCaseWithBranch):

    def test_strict_history(self):
        tree1 = self.make_branch_and_tree('tree1')
        try:
            tree1.branch.set_append_revisions_only(True)
        except errors.UpgradeRequired:
            raise TestSkipped('Format does not support strict history')
        tree1.commit('empty commit')
        tree2 = tree1.bzrdir.sprout('tree2').open_workingtree()
        tree2.commit('empty commit 2')
        tree1.pull(tree2.branch)
        tree1.commit('empty commit 3')
        tree2.commit('empty commit 4')
        self.assertRaises(errors.DivergedBranches, tree1.pull, tree2.branch)
        tree2.merge_from_branch(tree1.branch)
        tree2.commit('empty commit 5')
        self.assertRaises(errors.AppendRevisionsOnlyViolation, tree1.pull,
                          tree2.branch)
        tree3 = tree1.bzrdir.sprout('tree3').open_workingtree()
        tree3.merge_from_branch(tree2.branch)
        tree3.commit('empty commit 6')
        tree2.pull(tree3.branch)
