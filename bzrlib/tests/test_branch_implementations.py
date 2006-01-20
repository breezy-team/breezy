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
from bzrlib.clone import copy_branch
from bzrlib.commit import commit
import bzrlib.errors as errors
from bzrlib.errors import (NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
import bzrlib.gpg
from bzrlib.osutils import getcwd
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from bzrlib.transport import get_transport
from bzrlib.transport.http import HttpServer
from bzrlib.transport.memory import MemoryServer
from bzrlib.revision import NULL_REVISION

# TODO: Make a branch using basis branch, and check that it 
# doesn't request any files that could have been avoided, by 
# hooking into the Transport.


class TestCaseWithBranch(TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithBranch, self).setUp()
        self.branch = None

    def get_branch(self):
        if self.branch is None:
            self.branch = self.make_branch(self.get_url())
        return self.branch

    def make_branch(self, relpath):
        try:
            return self.branch_format.initialize(relpath)
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
        os.mkdir('b1')
        os.mkdir('b2')
        b1 = self.make_branch('b1')
        b2 = self.make_branch('b2')
        file('b1/foo', 'w').write('hello')
        b1.working_tree().add(['foo'], ['foo-id'])
        b1.working_tree().commit('lala!', rev_id='revision-1', allow_pointless=False)

        mutter('start fetch')
        f = Fetcher(from_branch=b1, to_branch=b2)
        eq = self.assertEquals
        eq(f.count_copied, 1)
        eq(f.last_revision, 'revision-1')

        rev = b2.get_revision('revision-1')
        tree = b2.revision_tree('revision-1')
        eq(tree.get_file_text('foo-id'), 'hello')

    def test_revision_tree(self):
        b1 = self.get_branch()
        b1.working_tree().commit('lala!', rev_id='revision-1', allow_pointless=True)
        tree = b1.revision_tree('revision-1')
        tree = b1.revision_tree(None)
        self.assertEqual(len(tree.list_files()), 0)
        tree = b1.revision_tree(NULL_REVISION)
        self.assertEqual(len(tree.list_files()), 0)

    def get_unbalanced_branch_pair(self):
        """Return two branches, a and b, with one file in a."""
        os.mkdir('a')
        br_a = self.make_branch('a')
        file('a/b', 'wb').write('b')
        br_a.working_tree().add('b')
        commit(br_a, "silly commit", rev_id='A')
        os.mkdir('b')
        br_b = self.make_branch('b')
        return br_a, br_b

    def get_balanced_branch_pair(self):
        """Returns br_a, br_b as with one commit in a, and b has a's stores."""
        br_a, br_b = self.get_unbalanced_branch_pair()
        br_a.push_stores(br_b)
        return br_a, br_b

    def test_push_stores(self):
        """Copy the stores from one branch to another"""
        br_a, br_b = self.get_unbalanced_branch_pair()
        # ensure the revision is missing.
        self.assertRaises(NoSuchRevision, br_b.get_revision, 
                          br_a.revision_history()[0])
        br_a.push_stores(br_b)
        # check that b now has all the data from a's first commit.
        rev = br_b.get_revision(br_a.revision_history()[0])
        tree = br_b.revision_tree(br_a.revision_history()[0])
        for file_id in tree:
            if tree.inventory[file_id].kind == "file":
                tree.get_file(file_id).read()
        return br_a, br_b

    def test_copy_branch(self):
        """Copy the stores from one branch to another"""
        br_a, br_b = self.get_balanced_branch_pair()
        commit(br_b, "silly commit")
        os.mkdir('c')
        br_c = copy_branch(br_a, 'c', basis_branch=br_b)
        self.assertEqual(br_a.revision_history(), br_c.revision_history())

    def test_copy_partial(self):
        """Copy only part of the history of a branch."""
        self.build_tree(['a/', 'a/one'])
        br_a = self.make_branch('a')
        br_a.working_tree().add(['one'])
        br_a.working_tree().commit('commit one', rev_id='u@d-1')
        self.build_tree(['a/two'])
        br_a.working_tree().add(['two'])
        br_a.working_tree().commit('commit two', rev_id='u@d-2')
        br_b = copy_branch(br_a, 'b', revision='u@d-1')
        self.assertEqual(br_b.last_revision(), 'u@d-1')
        self.assertTrue(os.path.exists('b/one'))
        self.assertFalse(os.path.exists('b/two'))
        
    def test_record_initial_ghost_merge(self):
        """A pending merge with no revision present is still a merge."""
        branch = self.get_branch()
        branch.working_tree().add_pending_merge('non:existent@rev--ision--0--2')
        branch.working_tree().commit('pretend to merge nonexistent-revision', rev_id='first')
        rev = branch.get_revision(branch.last_revision())
        self.assertEqual(len(rev.parent_ids), 1)
        # parent_sha1s is not populated now, WTF. rbc 20051003
        self.assertEqual(len(rev.parent_sha1s), 0)
        self.assertEqual(rev.parent_ids[0], 'non:existent@rev--ision--0--2')

    def test_bad_revision(self):
        self.assertRaises(errors.InvalidRevisionId, self.get_branch().get_revision, None)

# TODO 20051003 RBC:
# compare the gpg-to-sign info for a commit with a ghost and 
#     an identical tree without a ghost
# fetch missing should rewrite the TOC of weaves to list newly available parents.
        
    def test_pending_merges(self):
        """Tracking pending-merged revisions."""
        b = self.get_branch()
        wt = b.working_tree()
        self.assertEquals(wt.pending_merges(), [])
        wt.add_pending_merge('foo@azkhazan-123123-abcabc')
        self.assertEquals(wt.pending_merges(), ['foo@azkhazan-123123-abcabc'])
        wt.add_pending_merge('foo@azkhazan-123123-abcabc')
        self.assertEquals(wt.pending_merges(), ['foo@azkhazan-123123-abcabc'])
        wt.add_pending_merge('wibble@fofof--20050401--1928390812')
        self.assertEquals(wt.pending_merges(),
                          ['foo@azkhazan-123123-abcabc',
                           'wibble@fofof--20050401--1928390812'])
        b.working_tree().commit("commit from base with two merges")
        rev = b.get_revision(b.revision_history()[0])
        self.assertEquals(len(rev.parent_ids), 2)
        self.assertEquals(rev.parent_ids[0],
                          'foo@azkhazan-123123-abcabc')
        self.assertEquals(rev.parent_ids[1],
                           'wibble@fofof--20050401--1928390812')
        # list should be cleared when we do a commit
        self.assertEquals(wt.pending_merges(), [])

    def test_sign_existing_revision(self):
        branch = self.get_branch()
        branch.working_tree().commit("base", allow_pointless=True, rev_id='A')
        from bzrlib.testament import Testament
        branch.sign_revision('A', bzrlib.gpg.LoopbackGPGStrategy(None))
        self.assertEqual(Testament.from_revision(branch, 'A').as_short_text(),
                         branch.revision_store.get('A', 'sig').read())

    def test_store_signature(self):
        branch = self.get_branch()
        branch.store_revision_signature(bzrlib.gpg.LoopbackGPGStrategy(None),
                                        'FOO', 'A')
        self.assertEqual('FOO', branch.revision_store.get('A', 'sig').read())

    def test__relcontrolfilename(self):
        self.assertEqual('.bzr/%25', self.get_branch()._rel_controlfilename('%'))
        
    def test__relcontrolfilename_empty(self):
        self.assertEqual('.bzr', self.get_branch()._rel_controlfilename(''))

    def test_nicks(self):
        """Branch nicknames"""
        os.mkdir('bzr.dev')
        branch = self.make_branch('bzr.dev')
        self.assertEqual(branch.nick, 'bzr.dev')
        os.rename('bzr.dev', 'bzr.ab')
        branch = Branch.open('bzr.ab')
        self.assertEqual(branch.nick, 'bzr.ab')
        branch.nick = "Aaron's branch"
        branch.nick = "Aaron's branch"
        self.failUnless(os.path.exists(branch.controlfilename("branch.conf")))
        self.assertEqual(branch.nick, "Aaron's branch")
        os.rename('bzr.ab', 'integration')
        branch = Branch.open('integration')
        self.assertEqual(branch.nick, "Aaron's branch")
        branch.nick = u"\u1234"
        self.assertEqual(branch.nick, u"\u1234")

    def test_commit_nicks(self):
        """Nicknames are committed to the revision"""
        os.mkdir('bzr.dev')
        branch = self.get_branch()
        branch.nick = "My happy branch"
        branch.working_tree().commit('My commit respect da nick.')
        committed = branch.get_revision(branch.last_revision())
        self.assertEqual(committed.properties["branch-nick"], 
                         "My happy branch")


class ChrootedTests(TestCaseWithBranch):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.
    """

    def setUp(self):
        super(ChrootedTests, self).setUp()
        if not isinstance(self.transport_server, MemoryServer):
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
        self.assertEqual(None, self.get_branch()._transaction)

    def test_unlock_calls_finish(self):
        self.get_branch().lock_read()
        transaction = InstrumentedTransaction()
        self.get_branch()._transaction = transaction
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
        self.failUnless(isinstance(self.get_branch()._transaction,
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
                                  getcwd())
        self.assertEqual("foo", self.get_branch().get_push_location())

    def test_set_push_location(self):
        from bzrlib.config import (branches_config_filename,
                                   ensure_config_dir_exists)
        ensure_config_dir_exists()
        fn = branches_config_filename()
        self.get_branch().set_push_location('foo')
        self.assertFileEqual("[%s]\n"
                             "push_location = foo" % getcwd(),
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
