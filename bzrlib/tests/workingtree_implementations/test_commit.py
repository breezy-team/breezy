# Copyright (C) 2005, 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

from cStringIO import StringIO
import os

from bzrlib import branch, bzrdir, errors, ui, workingtree
from bzrlib.errors import (NotBranchError, NotVersionedError, 
                           UnsupportedOperation)
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.tests import TestSkipped, TestCase
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.trace import mutter
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)


class CapturingUIFactory(ui.UIFactory):
    """A UI Factory for testing - capture the updates made through it."""

    def __init__(self):
        super(CapturingUIFactory, self).__init__()
        self._calls = []
        self.depth = 0

    def clear(self):
        """See progress.ProgressBar.clear()."""

    def clear_term(self):
        """See progress.ProgressBar.clear_term()."""

    def finished(self):
        """See progress.ProgressBar.finished()."""
        self.depth -= 1

    def note(self, fmt_string, *args, **kwargs):
        """See progress.ProgressBar.note()."""

    def progress_bar(self):
        return self
    
    def nested_progress_bar(self):
        self.depth += 1
        return self

    def update(self, message, count=None, total=None):
        """See progress.ProgressBar.update()."""
        if self.depth == 1:
            self._calls.append(("update", count, total))


class TestCapturingUI(TestCase):

    def test_nested_ignore_depth_beyond_one(self):
        # we only want to capture the first level out progress, not
        # want sub-components might do. So we have nested bars ignored.
        factory = CapturingUIFactory()
        pb1 = factory.nested_progress_bar()
        pb1.update('foo', 0, 1)
        pb2 = factory.nested_progress_bar()
        pb2.update('foo', 0, 1)
        pb2.finished()
        pb1.finished()
        self.assertEqual([("update", 0, 1)], factory._calls)


class TestCommit(TestCaseWithWorkingTree):

    def test_commit_sets_last_revision(self):
        tree = self.make_branch_and_tree('tree')
        committed_id = tree.commit('foo', rev_id='foo', allow_pointless=True)
        self.assertEqual(['foo'], tree.get_parent_ids())
        # the commit should have returned the same id we asked for.
        self.assertEqual('foo', committed_id)

    def test_commit_returns_revision_id(self):
        tree = self.make_branch_and_tree('.')
        committed_id = tree.commit('message', allow_pointless=True)
        self.assertTrue(tree.branch.repository.has_revision(committed_id))
        self.assertNotEqual(None, committed_id)

    def test_commit_local_unbound(self):
        # using the library api to do a local commit on unbound branches is 
        # also an error
        tree = self.make_branch_and_tree('tree')
        self.assertRaises(errors.LocalRequiresBoundBranch,
                          tree.commit,
                          'foo',
                          local=True)
 
    def test_local_commit_ignores_master(self):
        # a --local commit does not require access to the master branch
        # at all, or even for it to exist.
        # we test this by setting up a bound branch and then corrupting
        # the master.
        master = self.make_branch('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master)
        except errors.UpgradeRequired:
            # older format.
            return
        master.bzrdir.transport.put_bytes('branch-format', 'garbage')
        del master
        # check its corrupted.
        self.assertRaises(errors.UnknownFormatError,
                          bzrdir.BzrDir.open,
                          'master')
        tree.commit('foo', rev_id='foo', local=True)
 
    def test_local_commit_does_not_push_to_master(self):
        # a --local commit does not require access to the master branch
        # at all, or even for it to exist.
        # we test that even when its available it does not push to it.
        master = self.make_branch('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master)
        except errors.UpgradeRequired:
            # older format.
            return
        tree.commit('foo', rev_id='foo', local=True)
        self.failIf(master.repository.has_revision('foo'))
        self.assertEqual(None, master.last_revision())

    def test_record_initial_ghost(self):
        """The working tree needs to record ghosts during commit."""
        wt = self.make_branch_and_tree('.')
        wt.set_parent_ids(['non:existent@rev--ision--0--2'],
            allow_leftmost_as_ghost=True)
        rev_id = wt.commit('commit against a ghost first parent.')
        rev = wt.branch.repository.get_revision(rev_id)
        self.assertEqual(rev.parent_ids, ['non:existent@rev--ision--0--2'])
        # parent_sha1s is not populated now, WTF. rbc 20051003
        self.assertEqual(len(rev.parent_sha1s), 0)

    def test_record_two_ghosts(self):
        """The working tree should preserve all the parents during commit."""
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

    def test_commit_deleted_subtree_and_files_updates_workingtree(self):
        """The working trees inventory may be adjusted by commit."""
        wt = self.make_branch_and_tree('.')
        wt.lock_write()
        self.build_tree(['a', 'b/', 'b/c', 'd'])
        wt.add(['a', 'b', 'b/c', 'd'], ['a-id', 'b-id', 'c-id', 'd-id'])
        this_dir = self.get_transport()
        this_dir.delete_tree('b')
        this_dir.delete('d')
        # now we have a tree with a through d in the inventory, but only
        # a present on disk. After commit b-id, c-id and d-id should be
        # missing from the inventory, within the same tree transaction.
        wt.commit('commit stuff')
        self.assertTrue(wt.has_id('a-id'))
        self.assertFalse(wt.has_or_had_id('b-id'))
        self.assertFalse(wt.has_or_had_id('c-id'))
        self.assertFalse(wt.has_or_had_id('d-id'))
        self.assertTrue(wt.has_filename('a'))
        self.assertFalse(wt.has_filename('b'))
        self.assertFalse(wt.has_filename('b/c'))
        self.assertFalse(wt.has_filename('d'))
        wt.unlock()
        # the changes should have persisted to disk - reopen the workingtree
        # to be sure.
        wt = wt.bzrdir.open_workingtree()
        wt.lock_read()
        self.assertTrue(wt.has_id('a-id'))
        self.assertFalse(wt.has_or_had_id('b-id'))
        self.assertFalse(wt.has_or_had_id('c-id'))
        self.assertFalse(wt.has_or_had_id('d-id'))
        self.assertTrue(wt.has_filename('a'))
        self.assertFalse(wt.has_filename('b'))
        self.assertFalse(wt.has_filename('b/c'))
        self.assertFalse(wt.has_filename('d'))
        wt.unlock()

    def test_commit_move_new(self):
        wt = self.make_branch_and_tree('first')
        wt.commit('first')
        wt2 = wt.bzrdir.sprout('second').open_workingtree()
        self.build_tree(['second/name1'])
        wt2.add('name1', 'name1-id')
        wt2.commit('second')
        wt.merge_from_branch(wt2.branch)
        wt.rename_one('name1', 'name2')
        wt.commit('third')
        wt.path2id('name1-id')
        

class TestCommitProgress(TestCaseWithWorkingTree):
    
    def restoreDefaults(self):
        ui.ui_factory = self.old_ui_factory

    def test_commit_progress_steps(self):
        # during commit we one progress update for every entry in the 
        # inventory, and then one for the inventory, and one for the
        # inventory, and one for the revision insertions.
        # first we need a test commit to do. Lets setup a branch with 
        # 3 files, and alter one in a selected-file commit. This exercises
        # a number of cases quickly. We should also test things like 
        # selective commits which excludes newly added files.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'c'])
        tree.add(['a', 'b', 'c'])
        tree.commit('first post')
        f = file('b', 'wt')
        f.write('new content')
        f.close()
        # set a progress bar that captures the calls so we can see what is 
        # emitted
        self.old_ui_factory = ui.ui_factory
        self.addCleanup(self.restoreDefaults)
        factory = CapturingUIFactory()
        ui.ui_factory = factory
        # TODO RBC 20060421 it would be nice to merge the reporter output
        # into the factory for this test - just make the test ui factory
        # pun as a reporter. Then we can check the ordering is right.
        tree.commit('second post', specific_files=['b'])
        # 9 steps: 1 for rev, 2 for inventory, 1 for finishing. 2 for root
        # and 6 for inventory files.
        # 2 steps don't trigger an update, as 'a' and 'c' are not 
        # committed.
        self.assertEqual(
            [("update", 0, 9),
             ("update", 1, 9),
             ("update", 2, 9),
             ("update", 3, 9),
             ("update", 4, 9),
             ("update", 5, 9),
             ("update", 6, 9),
             ("update", 7, 9)],
            factory._calls
           )
