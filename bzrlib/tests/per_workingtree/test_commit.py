# Copyright (C) 2006-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import os

from bzrlib import (
    branch,
    conflicts,
    controldir,
    errors,
    mutabletree,
    osutils,
    revision as _mod_revision,
    tests,
    transport as _mod_transport,
    ui,
    )
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree
from bzrlib.tests.testui import ProgressRecordingUIFactory


class TestCommit(TestCaseWithWorkingTree):

    def test_autodelete_renamed(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/dir/', 'a/dir/f1', 'a/dir/f2'])
        tree_a.add(['dir', 'dir/f1', 'dir/f2'], ['dir-id', 'f1-id', 'f2-id'])
        rev_id1 = tree_a.commit('init')
        # Start off by renaming entries,
        # but then actually auto delete the whole tree
        # https://bugs.launchpad.net/bzr/+bug/114615
        tree_a.rename_one('dir/f1', 'dir/a')
        tree_a.rename_one('dir/f2', 'dir/z')
        osutils.rmtree('a/dir')
        tree_a.commit('autoremoved')

        tree_a.lock_read()
        try:
            root_id = tree_a.get_root_id()
            paths = [(path, ie.file_id)
                     for path, ie in tree_a.iter_entries_by_dir()]
        finally:
            tree_a.unlock()
        # The only paths left should be the root
        self.assertEqual([('', root_id)], paths)

    def test_no_autodelete_renamed_away(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/dir/', 'a/dir/f1', 'a/dir/f2', 'a/dir2/'])
        tree_a.add(['dir', 'dir/f1', 'dir/f2', 'dir2'],
                   ['dir-id', 'f1-id', 'f2-id', 'dir2-id'])
        rev_id1 = tree_a.commit('init')
        # Rename one entry out of this directory
        tree_a.rename_one('dir/f1', 'dir2/a')
        osutils.rmtree('a/dir')
        tree_a.commit('autoremoved')

        tree_a.lock_read()
        try:
            root_id = tree_a.get_root_id()
            paths = [(path, ie.file_id)
                     for path, ie in tree_a.iter_entries_by_dir()]
        finally:
            tree_a.unlock()
        # The only paths left should be the root
        self.assertEqual([('', root_id), ('dir2', 'dir2-id'),
                          ('dir2/a', 'f1-id'),
                         ], paths)

    def test_no_autodelete_alternate_renamed(self):
        # Test for bug #114615
        tree_a = self.make_branch_and_tree('A')
        self.build_tree(['A/a/', 'A/a/m', 'A/a/n'])
        tree_a.add(['a', 'a/m', 'a/n'], ['a-id', 'm-id', 'n-id'])
        tree_a.commit('init')

        tree_a.lock_read()
        try:
            root_id = tree_a.get_root_id()
        finally:
            tree_a.unlock()

        tree_b = tree_a.bzrdir.sprout('B').open_workingtree()
        self.build_tree(['B/xyz/'])
        tree_b.add(['xyz'], ['xyz-id'])
        tree_b.rename_one('a/m', 'xyz/m')
        osutils.rmtree('B/a')
        tree_b.commit('delete in B')

        paths = [(path, ie.file_id)
                 for path, ie in tree_b.iter_entries_by_dir()]
        self.assertEqual([('', root_id),
                          ('xyz', 'xyz-id'),
                          ('xyz/m', 'm-id'),
                         ], paths)

        self.build_tree_contents([('A/a/n', 'new contents for n\n')])
        tree_a.commit('change n in A')

        # Merging from A should introduce conflicts because 'n' was modified
        # (in A) and removed (in B), so 'a' needs to be restored.
        num_conflicts = tree_b.merge_from_branch(tree_a.branch)
        self.assertEqual(3, num_conflicts)
        paths = [(path, ie.file_id)
                 for path, ie in tree_b.iter_entries_by_dir()]
        self.assertEqual([('', root_id),
                          ('a', 'a-id'),
                          ('xyz', 'xyz-id'),
                          ('a/n.OTHER', 'n-id'),
                          ('xyz/m', 'm-id'),
                         ], paths)
        osutils.rmtree('B/a')
        try:
            # bzr resolve --all
            tree_b.set_conflicts(conflicts.ConflictList())
        except errors.UnsupportedOperation:
            # On WT2, set_conflicts is unsupported, but the rmtree has the same
            # effect.
            pass
        tree_b.commit('autoremove a, without touching xyz/m')
        paths = [(path, ie.file_id)
                 for path, ie in tree_b.iter_entries_by_dir()]
        self.assertEqual([('', root_id),
                          ('xyz', 'xyz-id'),
                          ('xyz/m', 'm-id'),
                         ], paths)

    def test_commit_exclude_pending_merge_fails(self):
        """Excludes are a form of partial commit."""
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add('foo')
        wt.commit('commit one')
        wt2 = wt.bzrdir.sprout('to').open_workingtree()
        wt2.commit('change_right')
        wt.merge_from_branch(wt2.branch)
        try:
            self.assertRaises(errors.CannotCommitSelectedFileMerge,
                wt.commit, 'test', exclude=['foo'])
        except errors.ExcludesUnsupported:
            raise tests.TestNotApplicable("excludes not supported by this "
                "repository format")

    def test_commit_exclude_exclude_changed_is_pointless(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.smart_add(['.'])
        tree.commit('setup test')
        self.build_tree_contents([('a', 'new contents for "a"\n')])
        try:
            self.assertRaises(errors.PointlessCommit, tree.commit, 'test',
                exclude=['a'], allow_pointless=False)
        except errors.ExcludesUnsupported:
            raise tests.TestNotApplicable("excludes not supported by this "
                "repository format")

    def test_commit_exclude_excludes_modified_files(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'c'])
        tree.smart_add(['.'])
        try:
            tree.commit('test', exclude=['b', 'c'])
        except errors.ExcludesUnsupported:
            raise tests.TestNotApplicable("excludes not supported by this "
                "repository format")
        # If b was excluded it will still be 'added' in status.
        tree.lock_read()
        self.addCleanup(tree.unlock)
        changes = list(tree.iter_changes(tree.basis_tree()))
        self.assertEqual(2, len(changes))
        self.assertEqual((None, 'b'), changes[0][1])
        self.assertEqual((None, 'c'), changes[1][1])

    def test_commit_exclude_subtree_of_selected(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b'])
        tree.smart_add(['.'])
        try:
            tree.commit('test', specific_files=['a'], exclude=['a/b'])
        except errors.ExcludesUnsupported:
            raise tests.TestNotApplicable("excludes not supported by this "
                "repository format")
        # If a/b was excluded it will still be 'added' in status.
        tree.lock_read()
        self.addCleanup(tree.unlock)
        changes = list(tree.iter_changes(tree.basis_tree()))
        self.assertEqual(1, len(changes))
        self.assertEqual((None, 'a/b'), changes[0][1])

    def test_commit_sets_last_revision(self):
        tree = self.make_branch_and_tree('tree')
        committed_id = tree.commit('foo', rev_id='foo')
        self.assertEqual(['foo'], tree.get_parent_ids())
        # the commit should have returned the same id we asked for.
        self.assertEqual('foo', committed_id)

    def test_commit_returns_revision_id(self):
        tree = self.make_branch_and_tree('.')
        committed_id = tree.commit('message')
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

    def test_commit_merged_kind_change(self):
        """Test merging a kind change.

        Test making a kind change in a working tree, and then merging that
        from another. When committed it should commit the new kind.
        """
        wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        wt.add(['a'])
        wt.commit('commit one')
        wt2 = wt.bzrdir.sprout('to').open_workingtree()
        os.remove('a')
        os.mkdir('a')
        wt.commit('changed kind')
        wt2.merge_from_branch(wt.branch)
        wt2.commit('merged kind change')

    def test_commit_aborted_does_not_apply_automatic_changes_bug_282402(self):
        wt = self.make_branch_and_tree('.')
        wt.add(['a'], ['a-id'], ['file'])
        def fail_message(obj):
            raise errors.BzrCommandError("empty commit message")
        self.assertRaises(errors.BzrCommandError, wt.commit,
            message_callback=fail_message)
        self.assertEqual('a', wt.id2path('a-id'))

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
                          controldir.ControlDir.open,
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
        self.assertFalse(master.repository.has_revision('foo'))
        self.assertEqual(_mod_revision.NULL_REVISION,
                         (_mod_revision.ensure_null(master.last_revision())))

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
        this_dir = wt.bzrdir.root_transport
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

    def test_commit_deleted_subtree_with_removed(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c', 'd'])
        wt.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        wt.commit('first')
        wt.remove('b/c')
        this_dir = wt.bzrdir.root_transport
        this_dir.delete_tree('b')
        wt.lock_write()
        wt.commit('commit deleted rename')
        self.assertTrue(wt.has_id('a-id'))
        self.assertFalse(wt.has_or_had_id('b-id'))
        self.assertFalse(wt.has_or_had_id('c-id'))
        self.assertTrue(wt.has_filename('a'))
        self.assertFalse(wt.has_filename('b'))
        self.assertFalse(wt.has_filename('b/c'))
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

    def test_nested_commit(self):
        """Commit in multiply-nested trees"""
        tree = self.make_branch_and_tree('.')
        if not tree.supports_tree_reference():
            # inapplicable test.
            return
        subtree = self.make_branch_and_tree('subtree')
        subsubtree = self.make_branch_and_tree('subtree/subtree')
        subtree.add(['subtree'])
        tree.add(['subtree'])
        # use allow_pointless=False to ensure that the deepest tree, which
        # has no commits made to it, does not get a pointless commit.
        rev_id = tree.commit('added reference', allow_pointless=False)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        # the deepest subtree has not changed, so no commit should take place.
        self.assertEqual('null:', subsubtree.last_revision())
        # the intermediate tree should have committed a pointer to the current
        # subtree revision.
        sub_basis = subtree.basis_tree()
        sub_basis.lock_read()
        self.addCleanup(sub_basis.unlock)
        self.assertEqual(subsubtree.last_revision(),
            sub_basis.get_reference_revision(sub_basis.path2id('subtree')))
        # the intermediate tree has changed, so should have had a commit
        # take place.
        self.assertNotEqual(None, subtree.last_revision())
        # the outer tree should have committed a pointer to the current
        # subtree revision.
        basis = tree.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        self.assertEqual(subtree.last_revision(),
            basis.get_reference_revision(basis.path2id('subtree')))
        # the outer tree must have have changed too.
        self.assertNotEqual(None, rev_id)

    def test_nested_commit_second_commit_detects_changes(self):
        """Commit with a nested tree picks up the correct child revid."""
        tree = self.make_branch_and_tree('.')
        if not tree.supports_tree_reference():
            # inapplicable test.
            return
        subtree = self.make_branch_and_tree('subtree')
        tree.add(['subtree'])
        self.build_tree(['subtree/file'])
        subtree.add(['file'], ['file-id'])
        rev_id = tree.commit('added reference', allow_pointless=False)
        tree.get_reference_revision(tree.path2id('subtree'))
        child_revid = subtree.last_revision()
        # now change the child tree
        self.build_tree_contents([('subtree/file', 'new-content')])
        # and commit in the parent should commit the child and grab its revid,
        # we test with allow_pointless=False here so that we are simulating
        # what users will see.
        rev_id2 = tree.commit('changed subtree only', allow_pointless=False)
        # the child tree has changed, so should have had a commit
        # take place.
        self.assertNotEqual(None, subtree.last_revision())
        self.assertNotEqual(child_revid, subtree.last_revision())
        # the outer tree should have committed a pointer to the current
        # subtree revision.
        basis = tree.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        self.assertEqual(subtree.last_revision(),
            basis.get_reference_revision(basis.path2id('subtree')))
        self.assertNotEqual(rev_id, rev_id2)

    def test_nested_pointless_commits_are_pointless(self):
        tree = self.make_branch_and_tree('.')
        if not tree.supports_tree_reference():
            # inapplicable test.
            return
        subtree = self.make_branch_and_tree('subtree')
        tree.add(['subtree'])
        # record the reference.
        rev_id = tree.commit('added reference')
        child_revid = subtree.last_revision()
        # now do a no-op commit with allow_pointless=False
        self.assertRaises(errors.PointlessCommit, tree.commit, '',
            allow_pointless=False)
        self.assertEqual(child_revid, subtree.last_revision())
        self.assertEqual(rev_id, tree.last_revision())


class TestCommitProgress(TestCaseWithWorkingTree):

    def setUp(self):
        super(TestCommitProgress, self).setUp()
        ui.ui_factory = ProgressRecordingUIFactory()

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
        factory = ProgressRecordingUIFactory()
        ui.ui_factory = factory
        # TODO RBC 20060421 it would be nice to merge the reporter output
        # into the factory for this test - just make the test ui factory
        # pun as a reporter. Then we can check the ordering is right.
        tree.commit('second post', specific_files=['b'])
        # 5 steps, the first of which is reported 2 times, once per dir
        self.assertEqual(
            [('update', 1, 5, 'Collecting changes [0] - Stage'),
             ('update', 1, 5, 'Collecting changes [1] - Stage'),
             ('update', 2, 5, 'Saving data locally - Stage'),
             ('update', 3, 5, 'Running pre_commit hooks - Stage'),
             ('update', 4, 5, 'Updating the working tree - Stage'),
             ('update', 5, 5, 'Running post_commit hooks - Stage')],
            factory._calls
           )

    def test_commit_progress_shows_post_hook_names(self):
        tree = self.make_branch_and_tree('.')
        # set a progress bar that captures the calls so we can see what is
        # emitted
        factory = ProgressRecordingUIFactory()
        ui.ui_factory = factory
        def a_hook(_, _2, _3, _4, _5, _6):
            pass
        branch.Branch.hooks.install_named_hook('post_commit', a_hook,
                                               'hook name')
        tree.commit('first post')
        self.assertEqual(
            [('update', 1, 5, 'Collecting changes [0] - Stage'),
             ('update', 1, 5, 'Collecting changes [1] - Stage'),
             ('update', 2, 5, 'Saving data locally - Stage'),
             ('update', 3, 5, 'Running pre_commit hooks - Stage'),
             ('update', 4, 5, 'Updating the working tree - Stage'),
             ('update', 5, 5, 'Running post_commit hooks - Stage'),
             ('update', 5, 5, 'Running post_commit hooks [hook name] - Stage'),
             ],
            factory._calls
           )

    def test_commit_progress_shows_pre_hook_names(self):
        tree = self.make_branch_and_tree('.')
        # set a progress bar that captures the calls so we can see what is
        # emitted
        factory = ProgressRecordingUIFactory()
        ui.ui_factory = factory
        def a_hook(_, _2, _3, _4, _5, _6, _7, _8):
            pass
        branch.Branch.hooks.install_named_hook('pre_commit', a_hook,
                                               'hook name')
        tree.commit('first post')
        self.assertEqual(
            [('update', 1, 5, 'Collecting changes [0] - Stage'),
             ('update', 1, 5, 'Collecting changes [1] - Stage'),
             ('update', 2, 5, 'Saving data locally - Stage'),
             ('update', 3, 5, 'Running pre_commit hooks - Stage'),
             ('update', 3, 5, 'Running pre_commit hooks [hook name] - Stage'),
             ('update', 4, 5, 'Updating the working tree - Stage'),
             ('update', 5, 5, 'Running post_commit hooks - Stage'),
             ],
            factory._calls
           )

    def test_start_commit_hook(self):
        """Make sure a start commit hook can modify the tree that is
        committed."""
        def start_commit_hook_adds_file(tree):
            with open(tree.abspath("newfile"), 'w') as f: f.write("data")
            tree.add(["newfile"])
        def restoreDefaults():
            mutabletree.MutableTree.hooks['start_commit'] = []
        self.addCleanup(restoreDefaults)
        tree = self.make_branch_and_tree('.')
        mutabletree.MutableTree.hooks.install_named_hook(
            'start_commit',
            start_commit_hook_adds_file,
            None)
        revid = tree.commit('first post')
        committed_tree = tree.basis_tree()
        self.assertTrue(committed_tree.has_filename("newfile"))

    def test_post_commit_hook(self):
        """Make sure a post_commit hook is called after a commit."""
        def post_commit_hook_test_params(params):
            self.assertTrue(isinstance(params,
                mutabletree.PostCommitHookParams))
            self.assertTrue(isinstance(params.mutable_tree,
                mutabletree.MutableTree))
            with open(tree.abspath("newfile"), 'w') as f: f.write("data")
            params.mutable_tree.add(["newfile"])
        tree = self.make_branch_and_tree('.')
        mutabletree.MutableTree.hooks.install_named_hook(
            'post_commit',
            post_commit_hook_test_params,
            None)
        self.assertFalse(tree.has_filename("newfile"))
        revid = tree.commit('first post')
        self.assertTrue(tree.has_filename("newfile"))
        committed_tree = tree.basis_tree()
        self.assertFalse(committed_tree.has_filename("newfile"))
