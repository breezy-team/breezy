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

"""Tests for branch implementations - tests a branch format."""

import os
import sys

import bzrlib.branch as branch
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.commit import commit
import bzrlib.errors as errors
from bzrlib.errors import (NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
import bzrlib.gpg
from bzrlib.osutils import getcwd
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from bzrlib.transport import get_transport
from bzrlib.transport.http import HttpServer
from bzrlib.transport.memory import MemoryServer
from bzrlib.workingtree import WorkingTree

# TODO: Make a branch using basis branch, and check that it 
# doesn't request any files that could have been avoided, by 
# hooking into the Transport.


class TestCaseWithBranch(TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithBranch, self).setUp()
        self.branch = None

    def get_branch(self):
        if self.branch is None:
            self.branch = self.make_branch(None)
        return self.branch

    def make_branch(self, relpath):
        try:
            return self.branch_format.initialize(self.get_url(relpath))
        except UninitializableFormat:
            raise TestSkipped("Format %s is not initializable.")


class TestBranch(TestCaseWithBranch):

    def test_append_revisions(self):
        """Test appending more than one revision"""
        br = self.get_branch()
        br.append_revision("rev1")
        self.assertEquals(br.revision_history(), ["rev1",])
        br.append_revision("rev2", "rev3")
        self.assertEquals(br.revision_history(), ["rev1", "rev2", "rev3"])

    def test_fetch_revisions(self):
        """Test fetch-revision operation."""
        from bzrlib.fetch import Fetcher
        get_transport(self.get_url()).mkdir('b1')
        get_transport(self.get_url()).mkdir('b2')
        b1 = self.make_branch('b1')
        b2 = self.make_branch('b2')
        wt = WorkingTree.create(b1, 'b1')
        file('b1/foo', 'w').write('hello')
        wt.add(['foo'], ['foo-id'])
        wt.commit('lala!', rev_id='revision-1', allow_pointless=False)

        mutter('start fetch')
        f = Fetcher(from_branch=b1, to_branch=b2)
        eq = self.assertEquals
        eq(f.count_copied, 1)
        eq(f._last_revision, 'revision-1')

        rev = b2.repository.get_revision('revision-1')
        tree = b2.repository.revision_tree('revision-1')
        eq(tree.get_file_text('foo-id'), 'hello')

    def test_revision_tree(self):
        b1 = self.get_branch()
        wt = WorkingTree.create(b1, '.')
        wt.commit('lala!', rev_id='revision-1', allow_pointless=True)
        tree = b1.repository.revision_tree('revision-1')
        tree = b1.repository.revision_tree(None)
        self.assertEqual(len(tree.list_files()), 0)
        tree = b1.repository.revision_tree(NULL_REVISION)
        self.assertEqual(len(tree.list_files()), 0)

    def get_unbalanced_tree_pair(self):
        """Return two branches, a and b, with one file in a."""
        get_transport(self.get_url()).mkdir('a')
        br_a = self.make_branch('a')
        tree_a = WorkingTree.create(br_a, 'a')
        file('a/b', 'wb').write('b')
        tree_a.add('b')
        tree_a.commit("silly commit", rev_id='A')

        get_transport(self.get_url()).mkdir('b')
        br_b = self.make_branch('b')
        tree_b = WorkingTree.create(br_b, 'b')
        return tree_a, tree_b

    def get_balanced_branch_pair(self):
        """Returns br_a, br_b as with one commit in a, and b has a's stores."""
        tree_a, tree_b = self.get_unbalanced_tree_pair()
        tree_a.branch.push_stores(tree_b.branch)
        return tree_a, tree_b

    def test_push_stores(self):
        """Copy the stores from one branch to another"""
        tree_a, tree_b = self.get_unbalanced_tree_pair()
        br_a = tree_a.branch
        br_b = tree_b.branch
        # ensure the revision is missing.
        self.assertRaises(NoSuchRevision, br_b.repository.get_revision, 
                          br_a.revision_history()[0])
        br_a.push_stores(br_b)
        # check that b now has all the data from a's first commit.
        rev = br_b.repository.get_revision(br_a.revision_history()[0])
        tree = br_b.repository.revision_tree(br_a.revision_history()[0])
        for file_id in tree:
            if tree.inventory[file_id].kind == "file":
                tree.get_file(file_id).read()

    def test_clone_branch(self):
        """Copy the stores from one branch to another"""
        tree_a, tree_b = self.get_balanced_branch_pair()
        tree_b.commit("silly commit")
        os.mkdir('c')
        br_c = tree_a.branch.clone('c', basis_branch=tree_b.branch)
        self.assertEqual(tree_a.branch.revision_history(),
                         br_c.revision_history())

    def test_clone_partial(self):
        """Copy only part of the history of a branch."""
        get_transport(self.get_url()).mkdir('a')
        br_a = self.make_branch('a')
        wt = WorkingTree.create(br_a, "a")
        self.build_tree(['a/one'])
        wt.add(['one'])
        wt.commit('commit one', rev_id='u@d-1')
        self.build_tree(['a/two'])
        wt.add(['two'])
        wt.commit('commit two', rev_id='u@d-2')
        br_b = br_a.clone('b', revision='u@d-1')
        self.assertEqual(br_b.last_revision(), 'u@d-1')
        self.assertTrue(os.path.exists('b/one'))
        self.assertFalse(os.path.exists('b/two'))
        
    def test_record_initial_ghost_merge(self):
        """A pending merge with no revision present is still a merge."""
        branch = self.get_branch()
        wt = WorkingTree.create(branch, ".")
        wt.add_pending_merge('non:existent@rev--ision--0--2')
        wt.commit('pretend to merge nonexistent-revision', rev_id='first')
        rev = branch.repository.get_revision(branch.last_revision())
        self.assertEqual(len(rev.parent_ids), 1)
        # parent_sha1s is not populated now, WTF. rbc 20051003
        self.assertEqual(len(rev.parent_sha1s), 0)
        self.assertEqual(rev.parent_ids[0], 'non:existent@rev--ision--0--2')

    def test_bad_revision(self):
        self.assertRaises(errors.InvalidRevisionId,
                          self.get_branch().repository.get_revision,
                          None)

# TODO 20051003 RBC:
# compare the gpg-to-sign info for a commit with a ghost and 
#     an identical tree without a ghost
# fetch missing should rewrite the TOC of weaves to list newly available parents.
        
    def test_pending_merges(self):
        """Tracking pending-merged revisions."""
        b = self.get_branch()
        wt = WorkingTree.create(b, '.')
        self.assertEquals(wt.pending_merges(), [])
        wt.add_pending_merge('foo@azkhazan-123123-abcabc')
        self.assertEquals(wt.pending_merges(), ['foo@azkhazan-123123-abcabc'])
        wt.add_pending_merge('foo@azkhazan-123123-abcabc')
        self.assertEquals(wt.pending_merges(), ['foo@azkhazan-123123-abcabc'])
        wt.add_pending_merge('wibble@fofof--20050401--1928390812')
        self.assertEquals(wt.pending_merges(),
                          ['foo@azkhazan-123123-abcabc',
                           'wibble@fofof--20050401--1928390812'])
        wt.commit("commit from base with two merges")
        rev = b.repository.get_revision(b.revision_history()[0])
        self.assertEquals(len(rev.parent_ids), 2)
        self.assertEquals(rev.parent_ids[0],
                          'foo@azkhazan-123123-abcabc')
        self.assertEquals(rev.parent_ids[1],
                           'wibble@fofof--20050401--1928390812')
        # list should be cleared when we do a commit
        self.assertEquals(wt.pending_merges(), [])

    def test_sign_existing_revision(self):
        branch = self.get_branch()
        wt = WorkingTree.create(branch, ".")
        wt.commit("base", allow_pointless=True, rev_id='A')
        from bzrlib.testament import Testament
        strategy = bzrlib.gpg.LoopbackGPGStrategy(None)
        branch.repository.sign_revision('A', strategy)
        self.assertEqual(Testament.from_revision(branch.repository, 
                         'A').as_short_text(),
                         branch.repository.revision_store.get('A', 
                         'sig').read())

    def test_store_signature(self):
        branch = self.get_branch()
        branch.repository.store_revision_signature(
            bzrlib.gpg.LoopbackGPGStrategy(None), 'FOO', 'A')
        self.assertEqual('FOO', 
                         branch.repository.revision_store.get('A', 
                         'sig').read())

    def test_nicks(self):
        """Branch nicknames"""
        t = get_transport(self.get_url())
        t.mkdir('bzr.dev')
        branch = self.make_branch('bzr.dev')
        self.assertEqual(branch.nick, 'bzr.dev')
        t.move('bzr.dev', 'bzr.ab')
        branch = Branch.open(self.get_url('bzr.ab'))
        self.assertEqual(branch.nick, 'bzr.ab')
        branch.nick = "Aaron's branch"
        branch.nick = "Aaron's branch"
        self.failUnless(
            t.has(
                t.relpath(
                    branch.control_files.controlfilename("branch.conf")
                    )
                )
            )
        self.assertEqual(branch.nick, "Aaron's branch")
        t.move('bzr.ab', 'integration')
        branch = Branch.open(self.get_url('integration'))
        self.assertEqual(branch.nick, "Aaron's branch")
        branch.nick = u"\u1234"
        self.assertEqual(branch.nick, u"\u1234")

    def test_commit_nicks(self):
        """Nicknames are committed to the revision"""
        get_transport(self.get_url()).mkdir('bzr.dev')
        branch = self.make_branch('bzr.dev')
        branch.nick = "My happy branch"
        WorkingTree.create(branch, 'bzr.dev').commit('My commit respect da nick.')
        committed = branch.repository.get_revision(branch.last_revision())
        self.assertEqual(committed.properties["branch-nick"], 
                         "My happy branch")

    def test_no_ancestry_weave(self):
        # We no longer need to create the ancestry.weave file
        # since it is *never* used.
        branch = Branch.create('.')
        self.failIfExists('.bzr/ancestry.weave')


class ChrootedTests(TestCaseWithBranch):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.
    """

    def setUp(self):
        super(ChrootedTests, self).setUp()
        if not self.transport_server == MemoryServer:
            self.transport_readonly_server = HttpServer

    def test_open_containing(self):
        self.assertRaises(NotBranchError, Branch.open_containing,
                          self.get_readonly_url(''))
        self.assertRaises(NotBranchError, Branch.open_containing,
                          self.get_readonly_url('g/p/q'))
        try:
            branch = self.branch_format.initialize(self.get_url())
        except UninitializableFormat:
            raise TestSkipped("Format %s is not initializable.")
        branch, relpath = Branch.open_containing(self.get_readonly_url(''))
        self.assertEqual('', relpath)
        branch, relpath = Branch.open_containing(self.get_readonly_url('g/p/q'))
        self.assertEqual('g/p/q', relpath)
        
# TODO: rewrite this as a regular unittest, without relying on the displayed output        
#         >>> from bzrlib.commit import commit
#         >>> bzrlib.trace.silent = True
#         >>> br1 = ScratchBranch(files=['foo', 'bar'])
#         >>> br1.working_tree().add('foo')
#         >>> br1.working_tree().add('bar')
#         >>> commit(br1, "lala!", rev_id="REVISION-ID-1", verbose=False)
#         >>> br2 = ScratchBranch()
#         >>> br2.update_revisions(br1)
#         Added 2 texts.
#         Added 1 inventories.
#         Added 1 revisions.
#         >>> br2.revision_history()
#         [u'REVISION-ID-1']
#         >>> br2.update_revisions(br1)
#         Added 0 revisions.
#         >>> br1.text_store.total_size() == br2.text_store.total_size()
#         True

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


class TestBranchTransaction(TestCaseWithBranch):

    def setUp(self):
        super(TestBranchTransaction, self).setUp()
        self.branch = None
        
    def test_default_get_transaction(self):
        """branch.get_transaction on a new branch should give a PassThrough."""
        self.failUnless(isinstance(self.get_branch().get_transaction(),
                                   transactions.PassThroughTransaction))

    def test__set_new_transaction(self):
        self.get_branch()._set_transaction(transactions.ReadOnlyTransaction())

    def test__set_over_existing_transaction_raises(self):
        self.get_branch()._set_transaction(transactions.ReadOnlyTransaction())
        self.assertRaises(errors.LockError,
                          self.get_branch()._set_transaction,
                          transactions.ReadOnlyTransaction())

    def test_finish_no_transaction_raises(self):
        self.assertRaises(errors.LockError, self.get_branch()._finish_transaction)

    def test_finish_readonly_transaction_works(self):
        self.get_branch()._set_transaction(transactions.ReadOnlyTransaction())
        self.get_branch()._finish_transaction()
        self.assertEqual(None, self.get_branch().control_files._transaction)

    def test_unlock_calls_finish(self):
        self.get_branch().lock_read()
        transaction = InstrumentedTransaction()
        self.get_branch().control_files._transaction = transaction
        self.get_branch().unlock()
        self.assertEqual(['finish'], transaction.calls)

    def test_lock_read_acquires_ro_transaction(self):
        self.get_branch().lock_read()
        self.failUnless(isinstance(self.get_branch().get_transaction(),
                                   transactions.ReadOnlyTransaction))
        self.get_branch().unlock()
        
    def test_lock_write_acquires_passthrough_transaction(self):
        self.get_branch().lock_write()
        # cannot use get_transaction as its magic
        self.failUnless(isinstance(self.get_branch().control_files._transaction,
                                   transactions.PassThroughTransaction))
        self.get_branch().unlock()


class TestBranchPushLocations(TestCaseWithBranch):

    def test_get_push_location_unset(self):
        self.assertEqual(None, self.get_branch().get_push_location())

    def test_get_push_location_exact(self):
        from bzrlib.config import (branches_config_filename,
                                   ensure_config_dir_exists)
        ensure_config_dir_exists()
        fn = branches_config_filename()
        print >> open(fn, 'wt'), ("[%s]\n"
                                  "push_location=foo" %
                                  self.get_branch().base[:-1])
        self.assertEqual("foo", self.get_branch().get_push_location())

    def test_set_push_location(self):
        from bzrlib.config import (branches_config_filename,
                                   ensure_config_dir_exists)
        ensure_config_dir_exists()
        fn = branches_config_filename()
        self.get_branch().set_push_location('foo')
        self.assertFileEqual("[%s]\n"
                             "push_location = foo" % self.get_branch().base[:-1],
                             fn)

    # TODO RBC 20051029 test getting a push location from a branch in a 
    # recursive section - that is, it appends the branch name.


class TestFormat(TestCaseWithBranch):
    """Tests for the format itself."""

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
        made_branch = self.branch_format.initialize(t.base)
        self.failUnless(isinstance(made_branch, branch.Branch))
        self.assertEqual(self.branch_format,
                         branch.BzrBranchFormat.find_format(readonly_t))
        direct_opened_branch = self.branch_format.open(readonly_t)
        opened_branch = branch.Branch.open(t.base)
        self.assertEqual(made_branch._branch_format,
                         opened_branch._branch_format)
        self.assertEqual(direct_opened_branch._branch_format,
                         opened_branch._branch_format)
        self.failUnless(isinstance(opened_branch, branch.Branch))

    def test_open_not_branch(self):
        self.assertRaises(NoSuchFile,
                          self.branch_format.open,
                          get_transport(self.get_readonly_url()))
