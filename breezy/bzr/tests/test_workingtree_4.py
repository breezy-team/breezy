# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

"""Tests for WorkingTreeFormat4"""

import os
import time

from ... import (
    errors,
    osutils,
    )
from .. import (
    bzrdir,
    dirstate,
    inventory,
    workingtree_4,
    )
from ...lockdir import LockDir
from ...tests import TestCaseWithTransport, TestSkipped, features
from ...tree import InterTree


class TestWorkingTreeFormat4(TestCaseWithTransport):
    """Tests specific to WorkingTreeFormat4."""

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        workingtree_4.WorkingTreeFormat4().initialize(control)
        # we want:
        # format 'Bazaar Working Tree format 4'
        # stat-cache = ??
        t = control.get_workingtree_transport(None)
        with t.get('format') as f:
            self.assertEqualDiff(b'Bazaar Working Tree Format 4 (bzr 0.15)\n',
                                 f.read())
        self.assertFalse(t.has('inventory.basis'))
        # no last-revision file means 'None' or 'NULLREVISION'
        self.assertFalse(t.has('last-revision'))
        state = dirstate.DirState.on_file(t.local_abspath('dirstate'))
        state.lock_read()
        try:
            self.assertEqual([], state.get_parent_ids())
        finally:
            state.unlock()

    def test_resets_ignores_on_last_unlock(self):
        # Only the last unlock call will actually reset the
        # ignores. (bug #785671)
        tree = self.make_workingtree()
        with tree.lock_read():
            with tree.lock_read():
                tree.is_ignored("foo")
            self.assertIsNot(None, tree._ignoreglobster)
        self.assertIs(None, tree._ignoreglobster)

    def test_uses_lockdir(self):
        """WorkingTreeFormat4 uses its own LockDir:

            - lock is a directory
            - when the WorkingTree is locked, LockDir can see that
        """
        # this test could be factored into a subclass of tests common to both
        # format 3 and 4, but for now its not much of an issue as there is only
        # one in common.
        t = self.get_transport()
        tree = self.make_workingtree()
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)
        our_lock = LockDir(t, '.bzr/checkout/lock')
        self.assertEqual(our_lock.peek(), None)
        tree.lock_write()
        self.assertTrue(our_lock.peek())
        tree.unlock()
        self.assertEqual(our_lock.peek(), None)

    def make_workingtree(self, relpath=''):
        url = self.get_url(relpath)
        if relpath:
            self.build_tree([relpath + '/'])
        dir = bzrdir.BzrDirMetaFormat1().initialize(url)
        dir.create_repository()
        dir.create_branch()
        try:
            return workingtree_4.WorkingTreeFormat4().initialize(dir)
        except errors.NotLocalUrl:
            raise TestSkipped('Not a local URL')

    def test_dirstate_stores_all_parent_inventories(self):
        tree = self.make_workingtree()

        # We're going to build in tree a working tree
        # with three parent trees, with some files in common.

        # We really don't want to do commit or merge in the new dirstate-based
        # tree, because that might not work yet.  So instead we build
        # revisions elsewhere and pull them across, doing by hand part of the
        # work that merge would do.

        subtree = self.make_branch_and_tree('subdir')
        # writelock the tree so its repository doesn't get readlocked by
        # the revision tree locks. This works around the bug where we dont
        # permit lock upgrading.
        subtree.lock_write()
        self.addCleanup(subtree.unlock)
        self.build_tree(['subdir/file-a', ])
        subtree.add(['file-a'], ids=[b'id-a'])
        rev1 = subtree.commit('commit in subdir')

        subtree2 = subtree.controldir.sprout('subdir2').open_workingtree()
        self.build_tree(['subdir2/file-b'])
        subtree2.add(['file-b'], ids=[b'id-b'])
        rev2 = subtree2.commit('commit in subdir2')

        subtree.flush()
        subtree3 = subtree.controldir.sprout('subdir3').open_workingtree()
        rev3 = subtree3.commit('merge from subdir2')

        repo = tree.branch.repository
        repo.fetch(subtree.branch.repository, rev1)
        repo.fetch(subtree2.branch.repository, rev2)
        repo.fetch(subtree3.branch.repository, rev3)
        # will also pull the others...

        # create repository based revision trees
        rev1_revtree = repo.revision_tree(rev1)
        rev2_revtree = repo.revision_tree(rev2)
        rev3_revtree = repo.revision_tree(rev3)
        # tree doesn't contain a text merge yet but we'll just
        # set the parents as if a merge had taken place.
        # this should cause the tree data to be folded into the
        # dirstate.
        tree.set_parent_trees([
            (rev1, rev1_revtree),
            (rev2, rev2_revtree),
            (rev3, rev3_revtree), ])

        # create tree-sourced revision trees
        rev1_tree = tree.revision_tree(rev1)
        rev1_tree.lock_read()
        self.addCleanup(rev1_tree.unlock)
        rev2_tree = tree.revision_tree(rev2)
        rev2_tree.lock_read()
        self.addCleanup(rev2_tree.unlock)
        rev3_tree = tree.revision_tree(rev3)
        rev3_tree.lock_read()
        self.addCleanup(rev3_tree.unlock)

        # now we should be able to get them back out
        self.assertTreesEqual(rev1_revtree, rev1_tree)
        self.assertTreesEqual(rev2_revtree, rev2_tree)
        self.assertTreesEqual(rev3_revtree, rev3_tree)

    def test_dirstate_doesnt_read_parents_from_repo_when_setting(self):
        """Setting parent trees on a dirstate working tree takes
        the trees it's given and doesn't need to read them from the
        repository.
        """
        tree = self.make_workingtree()

        subtree = self.make_branch_and_tree('subdir')
        rev1 = subtree.commit('commit in subdir')
        rev1_tree = subtree.basis_tree()
        rev1_tree.lock_read()
        self.addCleanup(rev1_tree.unlock)

        tree.branch.pull(subtree.branch)

        # break the repository's legs to make sure it only uses the trees
        # it's given; any calls to forbidden methods will raise an
        # AssertionError
        repo = tree.branch.repository
        self.overrideAttr(repo, "get_revision", self.fail)
        self.overrideAttr(repo, "get_inventory", self.fail)
        self.overrideAttr(repo, "_get_inventory_xml", self.fail)
        # try to set the parent trees.
        tree.set_parent_trees([(rev1, rev1_tree)])

    def test_dirstate_doesnt_read_from_repo_when_returning_cache_tree(self):
        """Getting parent trees from a dirstate tree does not read from the
        repos inventory store. This is an important part of the dirstate
        performance optimisation work.
        """
        tree = self.make_workingtree()

        subtree = self.make_branch_and_tree('subdir')
        # writelock the tree so its repository doesn't get readlocked by
        # the revision tree locks. This works around the bug where we dont
        # permit lock upgrading.
        subtree.lock_write()
        self.addCleanup(subtree.unlock)
        rev1 = subtree.commit('commit in subdir')
        rev1_tree = subtree.basis_tree()
        rev1_tree.lock_read()
        # Trigger reading of inventory
        rev1_tree.root_inventory
        self.addCleanup(rev1_tree.unlock)
        rev2 = subtree.commit('second commit in subdir', allow_pointless=True)
        rev2_tree = subtree.basis_tree()
        rev2_tree.lock_read()
        # Trigger reading of inventory
        rev2_tree.root_inventory
        self.addCleanup(rev2_tree.unlock)

        tree.branch.pull(subtree.branch)

        # break the repository's legs to make sure it only uses the trees
        # it's given; any calls to forbidden methods will raise an
        # AssertionError
        repo = tree.branch.repository
        # dont uncomment this: the revision object must be accessed to
        # answer 'get_parent_ids' for the revision tree- dirstate does not
        # cache the parents of a parent tree at this point.
        # repo.get_revision = self.fail
        self.overrideAttr(repo, "get_inventory", self.fail)
        self.overrideAttr(repo, "_get_inventory_xml", self.fail)
        # set the parent trees.
        tree.set_parent_trees([(rev1, rev1_tree), (rev2, rev2_tree)])
        # read the first tree
        result_rev1_tree = tree.revision_tree(rev1)
        # read the second
        result_rev2_tree = tree.revision_tree(rev2)
        # compare - there should be no differences between the handed and
        # returned trees
        self.assertTreesEqual(rev2_tree, result_rev2_tree)
        self.assertRaises(
            errors.NoSuchRevisionInTree, self.assertTreesEqual, rev1_tree,
            result_rev1_tree)

    def test_dirstate_doesnt_cache_non_parent_trees(self):
        """Getting parent trees from a dirstate tree does not read from the
        repos inventory store. This is an important part of the dirstate
        performance optimisation work.
        """
        tree = self.make_workingtree()

        # make a tree that we can try for, which is able to be returned but
        # must not be
        subtree = self.make_branch_and_tree('subdir')
        rev1 = subtree.commit('commit in subdir')
        tree.branch.pull(subtree.branch)
        # check it fails
        self.assertRaises(errors.NoSuchRevision, tree.revision_tree, rev1)

    def test_no_dirstate_outside_lock(self):
        # temporary test until the code is mature enough to test from outside.
        """Getting a dirstate object fails if there is no lock."""
        def lock_and_call_current_dirstate(tree, lock_method):
            getattr(tree, lock_method)()
            tree.current_dirstate()
            tree.unlock()
        tree = self.make_workingtree()
        self.assertRaises(errors.ObjectNotLocked, tree.current_dirstate)
        lock_and_call_current_dirstate(tree, 'lock_read')
        self.assertRaises(errors.ObjectNotLocked, tree.current_dirstate)
        lock_and_call_current_dirstate(tree, 'lock_write')
        self.assertRaises(errors.ObjectNotLocked, tree.current_dirstate)
        lock_and_call_current_dirstate(tree, 'lock_tree_write')
        self.assertRaises(errors.ObjectNotLocked, tree.current_dirstate)

    def test_set_parent_trees_uses_update_basis_by_delta(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        self.addCleanup(builder.finish_series)
        builder.build_snapshot([], [
            ('add', ('', b'root-id', 'directory', None)),
            ('add', ('a', b'a-id', 'file', b'content\n'))],
            revision_id=b'A')
        builder.build_snapshot([b'A'], [
            ('modify', ('a', b'new content\nfor a\n')),
            ('add', ('b', b'b-id', 'file', b'b-content\n'))],
            revision_id=b'B')
        tree = self.make_workingtree('tree')
        source_branch = builder.get_branch()
        tree.branch.repository.fetch(source_branch.repository, b'B')
        tree.pull(source_branch, stop_revision=b'A')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        state = tree.current_dirstate()
        called = []
        orig_update = state.update_basis_by_delta

        def log_update_basis_by_delta(delta, new_revid):
            called.append(new_revid)
            return orig_update(delta, new_revid)
        state.update_basis_by_delta = log_update_basis_by_delta
        basis = tree.basis_tree()
        self.assertEqual(b'a-id', basis.path2id('a'))
        self.assertFalse(basis.is_versioned('b'))

        def fail_set_parent_trees(trees, ghosts):
            raise AssertionError('dirstate.set_parent_trees() was called')
        state.set_parent_trees = fail_set_parent_trees
        tree.pull(source_branch, stop_revision=b'B')
        self.assertEqual([b'B'], called)
        basis = tree.basis_tree()
        self.assertEqual(b'a-id', basis.path2id('a'))
        self.assertEqual(b'b-id', basis.path2id('b'))

    def test_set_parent_trees_handles_missing_basis(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        self.addCleanup(builder.finish_series)
        builder.build_snapshot([], [
            ('add', ('', b'root-id', 'directory', None)),
            ('add', ('a', b'a-id', 'file', b'content\n'))],
            revision_id=b'A')
        builder.build_snapshot([b'A'], [
            ('modify', ('a', b'new content\nfor a\n')),
            ('add', ('b', b'b-id', 'file', b'b-content\n'))],
            revision_id=b'B')
        builder.build_snapshot([b'A'], [
            ('add', ('c', b'c-id', 'file', b'c-content\n'))],
            revision_id=b'C')
        b_c = self.make_branch('branch_with_c')
        b_c.pull(builder.get_branch(), stop_revision=b'C')
        b_b = self.make_branch('branch_with_b')
        b_b.pull(builder.get_branch(), stop_revision=b'B')
        # This is reproducing some of what 'switch' does, just to isolate the
        # set_parent_trees() step.
        wt = b_b.create_checkout('tree', lightweight=True)
        fmt = wt.controldir.find_branch_format()
        fmt.set_reference(wt.controldir, None, b_c)
        # Re-open with the new reference
        wt = wt.controldir.open_workingtree()
        wt.set_parent_trees([(b'C', b_c.repository.revision_tree(b'C'))])
        self.assertFalse(wt.basis_tree().is_versioned('b'))

    def test_new_dirstate_on_new_lock(self):
        # until we have detection for when a dirstate can be reused, we
        # want to reparse dirstate on every new lock.
        known_dirstates = set()

        def lock_and_compare_all_current_dirstate(tree, lock_method):
            getattr(tree, lock_method)()
            state = tree.current_dirstate()
            self.assertFalse(state in known_dirstates)
            known_dirstates.add(state)
            tree.unlock()
        tree = self.make_workingtree()
        # lock twice with each type to prevent silly per-lock-type bugs.
        # each lock and compare looks for a unique state object.
        lock_and_compare_all_current_dirstate(tree, 'lock_read')
        lock_and_compare_all_current_dirstate(tree, 'lock_read')
        lock_and_compare_all_current_dirstate(tree, 'lock_tree_write')
        lock_and_compare_all_current_dirstate(tree, 'lock_tree_write')
        lock_and_compare_all_current_dirstate(tree, 'lock_write')
        lock_and_compare_all_current_dirstate(tree, 'lock_write')

    def test_constructing_invalid_interdirstate_raises(self):
        tree = self.make_workingtree()
        rev_id = tree.commit('first post')
        tree.commit('second post')
        rev_tree = tree.branch.repository.revision_tree(rev_id)
        # Exception is not a great thing to raise, but this test is
        # very short, and code is used to sanity check other tests, so
        # a full error object is YAGNI.
        self.assertRaises(
            Exception, workingtree_4.InterDirStateTree, rev_tree, tree)
        self.assertRaises(
            Exception, workingtree_4.InterDirStateTree, tree, rev_tree)

    def test_revtree_to_revtree_not_interdirstate(self):
        # we should not get a dirstate optimiser for two repository sourced
        # revtrees. we can't prove a negative, so we dont do exhaustive tests
        # of all formats; though that could be written in the future it doesn't
        # seem well worth it.
        tree = self.make_workingtree()
        rev_id = tree.commit('first post')
        rev_id2 = tree.commit('second post')
        rev_tree = tree.branch.repository.revision_tree(rev_id)
        rev_tree2 = tree.branch.repository.revision_tree(rev_id2)
        optimiser = InterTree.get(rev_tree, rev_tree2)
        self.assertIsInstance(optimiser, InterTree)
        self.assertFalse(isinstance(
            optimiser, workingtree_4.InterDirStateTree))
        optimiser = InterTree.get(rev_tree2, rev_tree)
        self.assertIsInstance(optimiser, InterTree)
        self.assertFalse(isinstance(
            optimiser, workingtree_4.InterDirStateTree))

    def test_revtree_not_in_dirstate_to_dirstate_not_interdirstate(self):
        # we should not get a dirstate optimiser when the revision id for of
        # the source is not in the dirstate of the target.
        tree = self.make_workingtree()
        rev_id = tree.commit('first post')
        tree.commit('second post')
        rev_tree = tree.branch.repository.revision_tree(rev_id)
        tree.lock_read()
        optimiser = InterTree.get(rev_tree, tree)
        self.assertIsInstance(optimiser, InterTree)
        self.assertFalse(isinstance(
            optimiser, workingtree_4.InterDirStateTree))
        optimiser = InterTree.get(tree, rev_tree)
        self.assertIsInstance(optimiser, InterTree)
        self.assertFalse(isinstance(
            optimiser, workingtree_4.InterDirStateTree))
        tree.unlock()

    def test_empty_basis_to_dirstate_tree(self):
        # we should get a InterDirStateTree for doing
        # 'changes_from' from the first basis dirstate revision tree to a
        # WorkingTree4.
        tree = self.make_workingtree()
        tree.lock_read()
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        optimiser = InterTree.get(basis_tree, tree)
        tree.unlock()
        basis_tree.unlock()
        self.assertIsInstance(optimiser, workingtree_4.InterDirStateTree)

    def test_nonempty_basis_to_dirstate_tree(self):
        # we should get a InterDirStateTree for doing
        # 'changes_from' from a non-null basis dirstate revision tree to a
        # WorkingTree4.
        tree = self.make_workingtree()
        tree.commit('first post')
        tree.lock_read()
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        optimiser = InterTree.get(basis_tree, tree)
        tree.unlock()
        basis_tree.unlock()
        self.assertIsInstance(optimiser, workingtree_4.InterDirStateTree)

    def test_empty_basis_revtree_to_dirstate_tree(self):
        # we should get a InterDirStateTree for doing
        # 'changes_from' from an empty repository based rev tree to a
        # WorkingTree4.
        tree = self.make_workingtree()
        tree.lock_read()
        basis_tree = tree.branch.repository.revision_tree(tree.last_revision())
        basis_tree.lock_read()
        optimiser = InterTree.get(basis_tree, tree)
        tree.unlock()
        basis_tree.unlock()
        self.assertIsInstance(optimiser, workingtree_4.InterDirStateTree)

    def test_nonempty_basis_revtree_to_dirstate_tree(self):
        # we should get a InterDirStateTree for doing
        # 'changes_from' from a non-null repository based rev tree to a
        # WorkingTree4.
        tree = self.make_workingtree()
        tree.commit('first post')
        tree.lock_read()
        basis_tree = tree.branch.repository.revision_tree(tree.last_revision())
        basis_tree.lock_read()
        optimiser = InterTree.get(basis_tree, tree)
        tree.unlock()
        basis_tree.unlock()
        self.assertIsInstance(optimiser, workingtree_4.InterDirStateTree)

    def test_tree_to_basis_in_other_tree(self):
        # we should get a InterDirStateTree when
        # the source revid is in the dirstate object of the target and
        # the dirstates are different. This is largely covered by testing
        # with repository revtrees, so is just for extra confidence.
        tree = self.make_workingtree('a')
        tree.commit('first post')
        tree2 = self.make_workingtree('b')
        tree2.pull(tree.branch)
        basis_tree = tree.basis_tree()
        tree2.lock_read()
        basis_tree.lock_read()
        optimiser = InterTree.get(basis_tree, tree2)
        tree2.unlock()
        basis_tree.unlock()
        self.assertIsInstance(optimiser, workingtree_4.InterDirStateTree)

    def test_merged_revtree_to_tree(self):
        # we should get a InterDirStateTree when
        # the source tree is a merged tree present in the dirstate of target.
        tree = self.make_workingtree('a')
        tree.commit('first post')
        tree.commit('tree 1 commit 2')
        tree2 = self.make_workingtree('b')
        tree2.pull(tree.branch)
        tree2.commit('tree 2 commit 2')
        tree.merge_from_branch(tree2.branch)
        second_parent_tree = tree.revision_tree(tree.get_parent_ids()[1])
        second_parent_tree.lock_read()
        tree.lock_read()
        optimiser = InterTree.get(second_parent_tree, tree)
        tree.unlock()
        second_parent_tree.unlock()
        self.assertIsInstance(optimiser, workingtree_4.InterDirStateTree)

    def test_id2path(self):
        tree = self.make_workingtree('tree')
        self.build_tree(['tree/a', 'tree/b'])
        tree.add(['a'], ids=[b'a-id'])
        self.assertEqual(u'a', tree.id2path(b'a-id'))
        self.assertRaises(errors.NoSuchId, tree.id2path, 'a')
        tree.commit('a')
        tree.add(['b'], ids=[b'b-id'])

        try:
            new_path = u'b\u03bcrry'
            tree.rename_one('a', new_path)
        except UnicodeEncodeError:
            # support running the test on non-unicode platforms
            new_path = 'c'
            tree.rename_one('a', new_path)
        self.assertEqual(new_path, tree.id2path(b'a-id'))
        tree.commit(u'b\xb5rry')
        tree.unversion([new_path])
        self.assertRaises(errors.NoSuchId, tree.id2path, b'a-id')
        self.assertEqual('b', tree.id2path(b'b-id'))
        self.assertRaises(errors.NoSuchId, tree.id2path, b'c-id')

    def test_unique_root_id_per_tree(self):
        # each time you initialize a new tree, it gets a different root id
        format_name = 'development-subtree'
        tree1 = self.make_branch_and_tree('tree1',
                                          format=format_name)
        tree2 = self.make_branch_and_tree('tree2',
                                          format=format_name)
        self.assertNotEqual(tree1.path2id(''), tree2.path2id(''))
        # when you branch, it inherits the same root id
        tree1.commit('first post')
        tree3 = tree1.controldir.sprout('tree3').open_workingtree()
        self.assertEqual(tree3.path2id(''), tree1.path2id(''))

    def test_set_root_id(self):
        # similar to some code that fails in the dirstate-plus-subtree branch
        # -- setting the root id while adding a parent seems to scramble the
        # dirstate invariants. -- mbp 20070303
        def validate():
            with wt.lock_read():
                wt.current_dirstate()._validate()
        wt = self.make_workingtree('tree')
        wt.set_root_id(b'TREE-ROOTID')
        validate()
        wt.commit('somenthing')
        validate()
        # now switch and commit again
        wt.set_root_id(b'tree-rootid')
        validate()
        wt.commit('again')
        validate()

    def test_default_root_id(self):
        tree = self.make_branch_and_tree('tag', format='dirstate-tags')
        self.assertEqual(inventory.ROOT_ID, tree.path2id(''))
        tree = self.make_branch_and_tree('subtree',
                                         format='development-subtree')
        self.assertNotEqual(inventory.ROOT_ID, tree.path2id(''))

    def test_non_subtree_with_nested_trees(self):
        # prior to dirstate, st/diff/commit ignored nested trees.
        # dirstate, as opposed to development-subtree, should
        # behave the same way.
        tree = self.make_branch_and_tree('.', format='dirstate')
        self.assertFalse(tree.supports_tree_reference())
        self.build_tree(['dir/'])
        # for testing easily.
        tree.set_root_id(b'root')
        tree.add(['dir'], ids=[b'dir-id'])
        self.make_branch_and_tree('dir')
        # the most primitive operation: kind
        self.assertEqual('directory', tree.kind('dir'))
        # a diff against the basis should give us a directory and the root (as
        # the root is new too).
        tree.lock_read()
        expected = [(b'dir-id',
                     (None, u'dir'),
                     True,
                     (False, True),
                     (None, b'root'),
                     (None, u'dir'),
                     (None, 'directory'),
                     (None, False), False),
                    (b'root', (None, u''), True, (False, True), (None, None),
                     (None, u''), (None, 'directory'), (None, False), False)]
        self.assertEqual(
            expected,
            list(tree.iter_changes(tree.basis_tree(), specific_files=['dir'])))
        tree.unlock()
        # do a commit, we want to trigger the dirstate fast-path too
        tree.commit('first post')
        # change the path for the subdir, which will trigger getting all
        # its data:
        os.rename('dir', 'also-dir')
        # now the diff will use the fast path
        tree.lock_read()
        expected = [(b'dir-id',
                     (u'dir', u'dir'),
                     True,
                     (True, True),
                     (b'root', b'root'),
                     ('dir', 'dir'),
                     ('directory', None),
                     (False, False), False)]
        self.assertEqual(expected, list(tree.iter_changes(tree.basis_tree())))
        tree.unlock()

    def test_with_subtree_supports_tree_references(self):
        # development-subtree should support tree-references.
        tree = self.make_branch_and_tree('.', format='development-subtree')
        self.assertTrue(tree.supports_tree_reference())
        # having checked this is on, the tree interface, and intertree
        # interface tests, will proceed to test the subtree support of
        # workingtree_4.

    def test_iter_changes_ignores_unversioned_dirs(self):
        """iter_changes should not descend into unversioned directories."""
        tree = self.make_branch_and_tree('.', format='dirstate')
        # We have an unversioned directory at the root, a versioned one with
        # other versioned files and an unversioned directory, and another
        # versioned dir with nothing but an unversioned directory.
        self.build_tree(['unversioned/',
                         'unversioned/a',
                         'unversioned/b/',
                         'versioned/',
                         'versioned/unversioned/',
                         'versioned/unversioned/a',
                         'versioned/unversioned/b/',
                         'versioned2/',
                         'versioned2/a',
                         'versioned2/unversioned/',
                         'versioned2/unversioned/a',
                         'versioned2/unversioned/b/',
                         ])
        tree.add(['versioned', 'versioned2', 'versioned2/a'])
        tree.commit('one', rev_id=b'rev-1')
        # Trap osutils._walkdirs_utf8 to spy on what dirs have been accessed.
        returned = []

        def walkdirs_spy(*args, **kwargs):
            for val in orig(*args, **kwargs):
                returned.append(val[0][0])
                yield val
        orig = self.overrideAttr(osutils, '_walkdirs_utf8', walkdirs_spy)

        basis = tree.basis_tree()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis.lock_read()
        self.addCleanup(basis.unlock)
        changes = [c.path for c in
                   tree.iter_changes(basis, want_unversioned=True)]
        self.assertEqual([(None, 'unversioned'),
                          (None, 'versioned/unversioned'),
                          (None, 'versioned2/unversioned'),
                          ], changes)
        self.assertEqual([b'', b'versioned', b'versioned2'], returned)
        del returned[:]  # reset
        changes = [c[1] for c in tree.iter_changes(basis)]
        self.assertEqual([], changes)
        self.assertEqual([b'', b'versioned', b'versioned2'], returned)

    def test_iter_changes_unversioned_error(self):
        """ Check if a PathsNotVersionedError is correctly raised and the
            paths list contains all unversioned entries only.
        """
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/bar', b'')])
        tree.add(['bar'], ids=[b'bar-id'])
        tree.lock_read()
        self.addCleanup(tree.unlock)

        def tree_iter_changes(files):
            return [
                c for c in tree.iter_changes(
                    tree.basis_tree(), specific_files=files,
                    require_versioned=True)]
        e = self.assertRaises(errors.PathsNotVersionedError,
                              tree_iter_changes, ['bar', 'foo'])
        self.assertEqual(e.paths, ['foo'])

    def test_iter_changes_unversioned_non_ascii(self):
        """Unversioned non-ascii paths should be reported as unicode"""
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('f', b'')])
        tree.add(['f'], ids=[b'f-id'])

        def tree_iter_changes(tree, files):
            return list(tree.iter_changes(
                tree.basis_tree(), specific_files=files,
                require_versioned=True))
        tree.lock_read()
        self.addCleanup(tree.unlock)
        e = self.assertRaises(errors.PathsNotVersionedError,
                              tree_iter_changes, tree, [u'\xa7', u'\u03c0'])
        self.assertEqual(set(e.paths), set([u'\xa7', u'\u03c0']))

    def get_tree_with_cachable_file_foo(self):
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree_contents([('foo', b'a bit of content for foo\n')])
        tree.add(['foo'], ids=[b'foo-id'])
        tree.current_dirstate()._cutoff_time = time.time() + 60
        return tree

    def test_commit_updates_hash_cache(self):
        tree = self.get_tree_with_cachable_file_foo()
        tree.commit('a commit')
        # tree's dirstate should now have a valid stat entry for foo.
        entry = tree._get_entry(path='foo')
        expected_sha1 = osutils.sha_file_by_name('foo')
        self.assertEqual(expected_sha1, entry[1][0][1])
        self.assertEqual(len('a bit of content for foo\n'), entry[1][0][2])

    def test_observed_sha1_cachable(self):
        tree = self.get_tree_with_cachable_file_foo()
        expected_sha1 = osutils.sha_file_by_name('foo')
        statvalue = os.lstat("foo")
        tree._observed_sha1("foo", (expected_sha1, statvalue))
        entry = tree._get_entry(path="foo")
        entry_state = entry[1][0]
        self.assertEqual(expected_sha1, entry_state[1])
        self.assertEqual(statvalue.st_size, entry_state[2])
        tree.unlock()
        tree.lock_read()
        tree = tree.controldir.open_workingtree()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        entry = tree._get_entry(path="foo")
        entry_state = entry[1][0]
        self.assertEqual(expected_sha1, entry_state[1])
        self.assertEqual(statvalue.st_size, entry_state[2])

    def test_observed_sha1_new_file(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'], ids=[b'foo-id'])
        with tree.lock_read():
            current_sha1 = tree._get_entry(path="foo")[1][0][1]
        with tree.lock_write():
            tree._observed_sha1(
                "foo", (osutils.sha_file_by_name('foo'), os.lstat("foo")))
            # Must not have changed
            self.assertEqual(current_sha1,
                             tree._get_entry(path="foo")[1][0][1])

    def test_get_file_with_stat_id_only(self):
        # Explicit test to ensure we get a lstat value from WT4 trees.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        file_obj, statvalue = tree.get_file_with_stat('foo')
        expected = os.lstat('foo')
        self.assertEqualStat(expected, statvalue)
        self.assertEqual([b"contents of foo\n"], file_obj.readlines())


class TestCorruptDirstate(TestCaseWithTransport):
    """Tests for how we handle when the dirstate has been corrupted."""

    def create_wt4(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree_4.WorkingTreeFormat4().initialize(control)
        return tree

    def test_invalid_rename(self):
        tree = self.create_wt4()
        # Create a corrupted dirstate
        with tree.lock_write():
            # We need a parent, or we always compare with NULL
            tree.commit('init')
            state = tree.current_dirstate()
            state._read_dirblocks_if_needed()
            # Now add in an invalid entry, a rename with a dangling pointer
            state._dirblocks[1][1].append(((b'', b'foo', b'foo-id'),
                                           [(b'f', b'', 0, False, b''),
                                            (b'r', b'bar', 0, False, b'')]))
            self.assertListRaises(dirstate.DirstateCorrupt,
                                  tree.iter_changes, tree.basis_tree())

    def get_simple_dirblocks(self, state):
        """Extract the simple information from the DirState.

        This returns the dirblocks, only with the sha1sum and stat details
        filtered out.
        """
        simple_blocks = []
        for block in state._dirblocks:
            simple_block = (block[0], [])
            for entry in block[1]:
                # Include the key for each entry, and for each parent include
                # just the minikind, so we know if it was
                # present/absent/renamed/etc
                simple_block[1].append((entry[0], [i[0] for i in entry[1]]))
            simple_blocks.append(simple_block)
        return simple_blocks

    def test_update_basis_with_invalid_delta(self):
        """When given an invalid delta, it should abort, and not be saved."""
        self.build_tree(['dir/', 'dir/file'])
        tree = self.create_wt4()
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add(['dir', 'dir/file'], ids=[b'dir-id', b'file-id'])
        first_revision_id = tree.commit('init')

        root_id = tree.path2id('')
        state = tree.current_dirstate()
        state._read_dirblocks_if_needed()
        self.assertEqual([
            (b'', [((b'', b'', root_id), [b'd', b'd'])]),
            (b'', [((b'', b'dir', b'dir-id'), [b'd', b'd'])]),
            (b'dir', [((b'dir', b'file', b'file-id'), [b'f', b'f'])]),
        ], self.get_simple_dirblocks(state))

        tree.remove(['dir/file'])
        self.assertEqual([
            (b'', [((b'', b'', root_id), [b'd', b'd'])]),
            (b'', [((b'', b'dir', b'dir-id'), [b'd', b'd'])]),
            (b'dir', [((b'dir', b'file', b'file-id'), [b'a', b'f'])]),
        ], self.get_simple_dirblocks(state))
        # Make sure the removal is written to disk
        tree.flush()

        # self.assertRaises(Exception, tree.update_basis_by_delta,
        new_dir = inventory.InventoryDirectory(b'dir-id', 'new-dir', root_id)
        new_dir.revision = b'new-revision-id'
        new_file = inventory.InventoryFile(b'file-id', 'new-file', root_id)
        new_file.revision = b'new-revision-id'
        self.assertRaises(
            errors.InconsistentDelta,
            tree.update_basis_by_delta, b'new-revision-id',
            [('dir', 'new-dir', b'dir-id', new_dir),
             ('dir/file', 'new-dir/new-file', b'file-id', new_file),
             ])
        del state

        # Now when we re-read the file it should not have been modified
        tree.unlock()
        tree.lock_read()
        self.assertEqual(first_revision_id, tree.last_revision())
        state = tree.current_dirstate()
        state._read_dirblocks_if_needed()
        self.assertEqual([
            (b'', [((b'', b'', root_id), [b'd', b'd'])]),
            (b'', [((b'', b'dir', b'dir-id'), [b'd', b'd'])]),
            (b'dir', [((b'dir', b'file', b'file-id'), [b'a', b'f'])]),
        ], self.get_simple_dirblocks(state))


class TestInventoryCoherency(TestCaseWithTransport):

    def test_inventory_is_synced_when_unversioning_a_dir(self):
        """Unversioning the root of a subtree unversions the entire subtree."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'c/'])
        tree.add(['a', 'a/b', 'c'], ids=[b'a-id', b'b-id', b'c-id'])
        # within a lock unversion should take effect
        tree.lock_write()
        self.addCleanup(tree.unlock)
        # Force access to the in memory inventory to trigger bug #494221: try
        # maintaining the in-memory inventory
        inv = tree.root_inventory
        self.assertTrue(inv.has_id(b'a-id'))
        self.assertTrue(inv.has_id(b'b-id'))
        tree.unversion(['a', 'a/b'])
        self.assertFalse(inv.has_id(b'a-id'))
        self.assertFalse(inv.has_id(b'b-id'))
