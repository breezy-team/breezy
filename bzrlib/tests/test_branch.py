# (C) 2005 Canonical Ltd

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

import os

from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.clone import copy_branch
from bzrlib.commit import commit
import bzrlib.errors as errors
from bzrlib.errors import NoSuchRevision, UnlistableBranch, NotBranchError
import bzrlib.gpg
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from bzrlib.revision import NULL_REVISION

# TODO: Make a branch using basis branch, and check that it 
# doesn't request any files that could have been avoided, by 
# hooking into the Transport.

class TestBranch(TestCaseInTempDir):

    def test_append_revisions(self):
        """Test appending more than one revision"""
        br = Branch.initialize(u".")
        br.append_revision("rev1")
        self.assertEquals(br.revision_history(), ["rev1",])
        br.append_revision("rev2", "rev3")
        self.assertEquals(br.revision_history(), ["rev1", "rev2", "rev3"])

    def test_fetch_revisions(self):
        """Test fetch-revision operation."""
        from bzrlib.fetch import Fetcher
        os.mkdir('b1')
        os.mkdir('b2')
        b1 = Branch.initialize('b1')
        b2 = Branch.initialize('b2')
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
        b1 = Branch.initialize(u'.')
        b1.working_tree().commit('lala!', rev_id='revision-1', allow_pointless=True)
        tree = b1.revision_tree('revision-1')
        tree = b1.revision_tree(None)
        self.assertEqual(len(tree.list_files()), 0)
        tree = b1.revision_tree(NULL_REVISION)
        self.assertEqual(len(tree.list_files()), 0)

    def get_unbalanced_branch_pair(self):
        """Return two branches, a and b, with one file in a."""
        os.mkdir('a')
        br_a = Branch.initialize("a")
        file('a/b', 'wb').write('b')
        br_a.working_tree().add('b')
        commit(br_a, "silly commit", rev_id='A')
        os.mkdir('b')
        br_b = Branch.initialize("b")
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
        br_a = Branch.initialize('a')
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
        branch = Branch.initialize(u'.')
        branch.working_tree().add_pending_merge('non:existent@rev--ision--0--2')
        branch.working_tree().commit('pretend to merge nonexistent-revision', rev_id='first')
        rev = branch.get_revision(branch.last_revision())
        self.assertEqual(len(rev.parent_ids), 1)
        # parent_sha1s is not populated now, WTF. rbc 20051003
        self.assertEqual(len(rev.parent_sha1s), 0)
        self.assertEqual(rev.parent_ids[0], 'non:existent@rev--ision--0--2')

    def test_bad_revision(self):
        branch = Branch.initialize(u'.')
        self.assertRaises(errors.InvalidRevisionId, branch.get_revision, None)

# TODO 20051003 RBC:
# compare the gpg-to-sign info for a commit with a ghost and 
#     an identical tree without a ghost
# fetch missing should rewrite the TOC of weaves to list newly available parents.
        
    def test_pending_merges(self):
        """Tracking pending-merged revisions."""
        b = Branch.initialize(u'.')
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
        branch = Branch.initialize(u'.')
        branch.working_tree().commit("base", allow_pointless=True, rev_id='A')
        from bzrlib.testament import Testament
        branch.sign_revision('A', bzrlib.gpg.LoopbackGPGStrategy(None))
        self.assertEqual(Testament.from_revision(branch, 'A').as_short_text(),
                         branch.revision_store.get('A', 'sig').read())

    def test_store_signature(self):
        branch = Branch.initialize(u'.')
        branch.store_revision_signature(bzrlib.gpg.LoopbackGPGStrategy(None),
                                        'FOO', 'A')
        self.assertEqual('FOO', branch.revision_store.get('A', 'sig').read())

    def test__relcontrolfilename(self):
        branch = Branch.initialize(u'.')
        self.assertEqual('.bzr/%25', branch._rel_controlfilename('%'))
        
    def test__relcontrolfilename_empty(self):
        branch = Branch.initialize(u'.')
        self.assertEqual('.bzr', branch._rel_controlfilename(''))

    def test_nicks(self):
        """Branch nicknames"""
        os.mkdir('bzr.dev')
        branch = Branch.initialize('bzr.dev')
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
        branch = Branch.initialize('bzr.dev')
        branch.nick = "My happy branch"
        branch.working_tree().commit('My commit respect da nick.')
        committed = branch.get_revision(branch.last_revision())
        self.assertEqual(committed.properties["branch-nick"], 
                         "My happy branch")


class TestRemote(TestCaseWithWebserver):

    def test_open_containing(self):
        self.assertRaises(NotBranchError, Branch.open_containing,
                          self.get_remote_url(''))
        self.assertRaises(NotBranchError, Branch.open_containing,
                          self.get_remote_url('g/p/q'))
        b = Branch.initialize(u'.')
        branch, relpath = Branch.open_containing(self.get_remote_url(''))
        self.assertEqual('', relpath)
        branch, relpath = Branch.open_containing(self.get_remote_url('g/p/q'))
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


class TestBranchTransaction(TestCaseInTempDir):

    def setUp(self):
        super(TestBranchTransaction, self).setUp()
        self.branch = Branch.initialize(u'.')
        
    def test_default_get_transaction(self):
        """branch.get_transaction on a new branch should give a PassThrough."""
        self.failUnless(isinstance(self.branch.get_transaction(),
                                   transactions.PassThroughTransaction))

    def test__set_new_transaction(self):
        self.branch._set_transaction(transactions.ReadOnlyTransaction())

    def test__set_over_existing_transaction_raises(self):
        self.branch._set_transaction(transactions.ReadOnlyTransaction())
        self.assertRaises(errors.LockError,
                          self.branch._set_transaction,
                          transactions.ReadOnlyTransaction())

    def test_finish_no_transaction_raises(self):
        self.assertRaises(errors.LockError, self.branch._finish_transaction)

    def test_finish_readonly_transaction_works(self):
        self.branch._set_transaction(transactions.ReadOnlyTransaction())
        self.branch._finish_transaction()
        self.assertEqual(None, self.branch._transaction)

    def test_unlock_calls_finish(self):
        self.branch.lock_read()
        transaction = InstrumentedTransaction()
        self.branch._transaction = transaction
        self.branch.unlock()
        self.assertEqual(['finish'], transaction.calls)

    def test_lock_read_acquires_ro_transaction(self):
        self.branch.lock_read()
        self.failUnless(isinstance(self.branch.get_transaction(),
                                   transactions.ReadOnlyTransaction))
        self.branch.unlock()
        
    def test_lock_write_acquires_passthrough_transaction(self):
        self.branch.lock_write()
        # cannot use get_transaction as its magic
        self.failUnless(isinstance(self.branch._transaction,
                                   transactions.PassThroughTransaction))
        self.branch.unlock()


class TestBranchPushLocations(TestCaseInTempDir):

    def setUp(self):
        super(TestBranchPushLocations, self).setUp()
        self.branch = Branch.initialize(u'.')
        
    def test_get_push_location_unset(self):
        self.assertEqual(None, self.branch.get_push_location())

    def test_get_push_location_exact(self):
        self.build_tree(['.bazaar/'])
        print >> open('.bazaar/branches.conf', 'wt'), ("[%s]\n"
                                                       "push_location=foo" %
                                                       os.getcwdu())
        self.assertEqual("foo", self.branch.get_push_location())

    def test_set_push_location(self):
        self.branch.set_push_location('foo')
        self.assertFileEqual("[%s]\n"
                             "push_location = foo" % os.getcwdu(),
                             '.bazaar/branches.conf')

    # TODO RBC 20051029 test getting a push location from a branch in a 
    # recursive section - that is, it appends the branch name.
