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

import bzrlib.branch
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
import bzrlib.gpg
from bzrlib.osutils import getcwd
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from bzrlib.transport import get_transport
from bzrlib.transport.http import HttpServer
from bzrlib.transport.memory import MemoryServer
from bzrlib.upgrade import upgrade
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
        repo = self.make_repository(relpath)
        # fixme RBC 20060210 this isnt necessarily a fixable thing,
        # Skipped is the wrong exception to raise.
        try:
            return self.branch_format.initialize(repo.bzrdir)
        except errors.UninitializableFormat:
            raise TestSkipped('Uninitializable branch format')

    def make_repository(self, relpath):
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
            made_control = self.bzrdir_format.initialize(url)
            return made_control.create_repository()
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
        wt = self.make_branch_and_tree('b1')
        b1 = wt.branch
        b2 = self.make_branch('b2')
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

    def get_unbalanced_tree_pair(self):
        """Return two branches, a and b, with one file in a."""
        get_transport(self.get_url()).mkdir('a')
        tree_a = self.make_branch_and_tree('a')
        file('a/b', 'wb').write('b')
        tree_a.add('b')
        tree_a.commit("silly commit", rev_id='A')

        get_transport(self.get_url()).mkdir('b')
        tree_b = self.make_branch_and_tree('b')
        return tree_a, tree_b

    def get_balanced_branch_pair(self):
        """Returns br_a, br_b as with one commit in a, and b has a's stores."""
        tree_a, tree_b = self.get_unbalanced_tree_pair()
        tree_b.branch.repository.fetch(tree_a.branch.repository)
        return tree_a, tree_b

    def test_clone_branch(self):
        """Copy the stores from one branch to another"""
        tree_a, tree_b = self.get_balanced_branch_pair()
        tree_b.commit("silly commit")
        os.mkdir('c')
        # this fails to test that the history from a was not used.
        dir_c = tree_a.bzrdir.clone('c', basis=tree_b.bzrdir)
        self.assertEqual(tree_a.branch.revision_history(),
                         dir_c.open_branch().revision_history())

    def test_clone_partial(self):
        """Copy only part of the history of a branch."""
        # TODO: RBC 20060208 test with a revision not on revision-history.
        #       what should that behaviour be ? Emailed the list.
        wt_a = self.make_branch_and_tree('a')
        self.build_tree(['a/one'])
        wt_a.add(['one'])
        wt_a.commit('commit one', rev_id='1')
        self.build_tree(['a/two'])
        wt_a.add(['two'])
        wt_a.commit('commit two', rev_id='2')
        repo_b = self.make_repository('b')
        wt_a.bzrdir.open_repository().copy_content_into(repo_b)
        br_b = wt_a.bzrdir.open_branch().clone(repo_b.bzrdir, revision_id='1')
        self.assertEqual(br_b.last_revision(), '1')

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
        wt_a.bzrdir.open_repository().copy_content_into(repo_b)
        br_b = wt_a.bzrdir.open_branch().sprout(repo_b.bzrdir, revision_id='1')
        self.assertEqual(br_b.last_revision(), '1')

    def test_clone_branch_nickname(self):
        # test the nick name is preserved always
        raise TestSkipped('XXX branch cloning is not yet tested..')

    def test_clone_branch_parent(self):
        # test the parent is preserved always
        raise TestSkipped('XXX branch cloning is not yet tested..')
        
    def test_sprout_branch_nickname(self):
        # test the nick name is reset always
        raise TestSkipped('XXX branch sprouting is not yet tested..')

    def test_sprout_branch_parent(self):
        source = self.make_branch('source')
        target = source.bzrdir.sprout(self.get_url('target')).open_branch()
        self.assertEqual(source.bzrdir.root_transport.base, target.get_parent())
        
    def test_record_initial_ghost_merge(self):
        """A pending merge with no revision present is still a merge."""
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
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
        wt = self.make_branch_and_tree('.')
        b = wt.branch
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
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
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

    def test_branch_keeps_signatures(self):
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        wt.branch.repository.sign_revision('A',
            bzrlib.gpg.LoopbackGPGStrategy(None))
        #FIXME: clone should work to urls,
        # wt.clone should work to disks.
        self.build_tree(['target/'])
        d2 = wt.bzrdir.clone('target')
        self.assertEqual(wt.branch.repository.revision_store.get('A', 
                            'sig').read(),
                         d2.open_repository().revision_store.get('A', 
                            'sig').read())

    def test_upgrade_preserves_signatures(self):
        # this is in the current test format
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        wt.branch.repository.sign_revision('A',
            bzrlib.gpg.LoopbackGPGStrategy(None))
        old_signature = wt.branch.repository.revision_store.get('A',
            'sig').read()
        upgrade(wt.basedir)
        wt = WorkingTree.open(wt.basedir)
        new_signature = wt.branch.repository.revision_store.get('A',
            'sig').read()
        self.assertEqual(old_signature, new_signature)

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
        wt = self.make_branch_and_tree('bzr.dev')
        branch = wt.branch
        branch.nick = "My happy branch"
        wt.commit('My commit respect da nick.')
        committed = branch.repository.get_revision(branch.last_revision())
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
        if not self.transport_server == MemoryServer:
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
        made_branch = self.make_branch('.')
        self.failUnless(isinstance(made_branch, bzrlib.branch.Branch))

        # find it via bzrdir opening:
        opened_control = bzrdir.BzrDir.open(readonly_t.base)
        direct_opened_branch = opened_control.open_branch()
        self.assertEqual(direct_opened_branch.__class__, made_branch.__class__)
        self.assertEqual(opened_control, direct_opened_branch.bzrdir)
        self.failUnless(isinstance(direct_opened_branch._format,
                        self.branch_format.__class__))

        # find it via Branch.open
        opened_branch = bzrlib.branch.Branch.open(readonly_t.base)
        self.failUnless(isinstance(opened_branch, made_branch.__class__))
        self.assertEqual(made_branch._format.__class__,
                         opened_branch._format.__class__)
        # if it has a unique id string, can we probe for it ?
        try:
            self.branch_format.get_format_string()
        except NotImplementedError:
            return
        self.assertEqual(self.branch_format,
                         bzrlib.branch.BranchFormat.find_format(opened_control))
