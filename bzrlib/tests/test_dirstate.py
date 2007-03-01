# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests of the dirstate functionality being built for WorkingTreeFormat4."""

import bisect
import os

from bzrlib import (
    dirstate,
    errors,
    osutils,
    )
from bzrlib.memorytree import MemoryTree
from bzrlib.tests import TestCase, TestCaseWithTransport


# TODO:
# test DirStateRevisionTree : test filtering out of deleted files does not
#         filter out files called RECYCLED.BIN ;)
# test 0 parents, 1 parent, 4 parents.
# test unicode parents, non unicode parents
# test all change permutations in one and two parents.
# i.e. file in parent 1, dir in parent 2, symlink in tree.
# test that renames in the tree result in correct parent paths
# Test get state from a file, then asking for lines.
# write a smaller state, and check the file has been truncated.
# add a entry when its in state deleted
# revision attribute for root entries.
# test that utf8 strings are preserved in _row_to_line
# test parent manipulation
# test parents that are null in save : i.e. no record in the parent tree for this.
# todo: _set_data records ghost parents.
# TESTS to write:
# general checks for NOT_IN_MEMORY error conditions.
# set_path_id on a NOT_IN_MEMORY dirstate
# set_path_id  unicode support
# set_path_id  setting id of a path not root
# set_path_id  setting id when there are parents without the id in the parents
# set_path_id  setting id when there are parents with the id in the parents
# set_path_id  setting id when state is not in memory
# set_path_id  setting id when state is in memory unmodified
# set_path_id  setting id when state is in memory modified

class TestCaseWithDirState(TestCaseWithTransport):
    """Helper functions for creating DirState objects with various content."""

    def create_empty_dirstate(self):
        """Return a locked but empty dirstate"""
        state = dirstate.DirState.initialize('dirstate')
        return state

    def create_dirstate_with_root(self):
        """Return a write-locked state with a single root entry."""
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry_direntry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry_direntry]))
        dirblocks.append(('', []))
        state = self.create_empty_dirstate()
        try:
            state._set_data([], dirblocks)
        except:
            state.unlock()
            raise
        return state

    def create_dirstate_with_root_and_subdir(self):
        """Return a locked DirState with a root and a subdir"""
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        subdir_entry = ('', 'subdir', 'subdir-id'), [
            ('d', '', 0, False, packed_stat),
            ]
        state = self.create_dirstate_with_root()
        try:
            dirblocks = list(state._dirblocks)
            dirblocks[1][1].append(subdir_entry)
            state._set_data([], dirblocks)
        except:
            state.unlock()
            raise
        return state

    def create_complex_dirstate(self):
        """This dirstate contains multiple files and directories.

         /        a-root-value
         a/       a-dir
         b/       b-dir
         c        c-file
         d        d-file
         a/e/     e-dir
         a/f      f-file
         b/g      g-file
         b/h\xc3\xa5  h-\xc3\xa5-file  #This is u'\xe5' encoded into utf-8

        # Notice that a/e is an empty directory.
        """
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        null_sha = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        root_entry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat),
            ]
        a_entry = ('', 'a', 'a-dir'), [
            ('d', '', 0, False, packed_stat),
            ]
        b_entry = ('', 'b', 'b-dir'), [
            ('d', '', 0, False, packed_stat),
            ]
        c_entry = ('', 'c', 'c-file'), [
            ('f', null_sha, 10, False, packed_stat),
            ]
        d_entry = ('', 'd', 'd-file'), [
            ('f', null_sha, 20, False, packed_stat),
            ]
        e_entry = ('a', 'e', 'e-dir'), [
            ('d', '', 0, False, packed_stat),
            ]
        f_entry = ('a', 'f', 'f-file'), [
            ('f', null_sha, 30, False, packed_stat),
            ]
        g_entry = ('b', 'g', 'g-file'), [
            ('f', null_sha, 30, False, packed_stat),
            ]
        h_entry = ('b', 'h\xc3\xa5', 'h-\xc3\xa5-file'), [
            ('f', null_sha, 40, False, packed_stat),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry]))
        dirblocks.append(('', [a_entry, b_entry, c_entry, d_entry]))
        dirblocks.append(('a', [e_entry, f_entry]))
        dirblocks.append(('b', [g_entry, h_entry]))
        state = dirstate.DirState.initialize('dirstate')
        try:
            state._set_data([], dirblocks)
        except:
            state.unlock()
            raise
        return state

    def check_state_with_reopen(self, expected_result, state):
        """Check that state has current state expected_result.

        This will check the current state, open the file anew and check it
        again.
        This function expects the current state to be locked for writing, and
        will unlock it before re-opening.
        This is required because we can't open a lock_read() while something
        else has a lock_write().
            write => mutually exclusive lock
            read => shared lock
        """
        # The state should already be write locked, since we just had to do
        # some operation to get here.
        assert state._lock_token is not None
        try:
            self.assertEqual(expected_result[0],  state.get_parent_ids())
            # there should be no ghosts in this tree.
            self.assertEqual([], state.get_ghosts())
            # there should be one fileid in this tree - the root of the tree.
            self.assertEqual(expected_result[1], list(state._iter_entries()))
            state.save()
        finally:
            state.unlock()
        del state # Callers should unlock
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(expected_result[1], list(state._iter_entries()))
        finally:
            state.unlock()


class TestTreeToDirState(TestCaseWithDirState):

    def test_empty_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        expected_result = ([], [
            (('', '', tree.path2id('')), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ])])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def test_1_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post').encode('utf8')
        root_stat_pack = dirstate.pack_stat(os.stat(tree.basedir))
        expected_result = ([rev_id], [
            (('', '', tree.path2id('')), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
              ('d', '', 0, False, rev_id), # first parent details
             ])])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def test_2_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        rev_id2 = tree2.commit('second post', allow_pointless=True)
        tree.merge_from_branch(tree2.branch)
        expected_result = ([rev_id, rev_id2], [
            (('', '', tree.path2id('')), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
              ('d', '', 0, False, rev_id), # first parent details
              ('d', '', 0, False, rev_id2), # second parent details
             ])])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def test_empty_unknowns_are_ignored_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unknown'])
        expected_result = ([], [
            (('', '', tree.path2id('')), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ])])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def get_tree_with_a_file(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a file'])
        tree.add('a file', 'a file id')
        return tree

    def test_non_empty_no_parents_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are files on disk and no parents
        tree = self.get_tree_with_a_file()
        expected_result = ([], [
            (('', '', tree.path2id('')), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a file', 'a file id'), # common
             [('f', '', 0, False, dirstate.DirState.NULLSTAT), # current
             ]),
            ])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def test_1_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit('first post').encode('utf8')
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([('tree/a file', 'new content\n')])
        expected_result = ([rev_id], [
            (('', '', tree.path2id('')), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
              ('d', '', 0, False, rev_id), # first parent details
             ]),
            (('', 'a file', 'a file id'), # common
             [('f', '', 0, False, dirstate.DirState.NULLSTAT), # current
              ('f', 'c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8', 24, False,
               rev_id), # first parent
             ]),
            ])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def test_2_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit('first post').encode('utf8')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([('tree2/a file', 'merge content\n')])
        rev_id2 = tree2.commit('second post').encode('utf8')
        tree.merge_from_branch(tree2.branch)
        # change the current content to be different this will alter stat, sha
        # and length again, giving us three distinct values:
        self.build_tree_contents([('tree/a file', 'new content\n')])
        expected_result = ([rev_id, rev_id2], [
            (('', '', tree.path2id('')), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
              ('d', '', 0, False, rev_id), # first parent details
              ('d', '', 0, False, rev_id2), # second parent details
             ]),
            (('', 'a file', 'a file id'), # common
             [('f', '', 0, False, dirstate.DirState.NULLSTAT), # current
              ('f', 'c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8', 24, False,
               rev_id), # first parent
              ('f', '314d796174c9412647c3ce07dfb5d36a94e72958', 14, False,
               rev_id2), # second parent
             ]),
            ])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)


class TestDirStateOnFile(TestCaseWithDirState):

    def test_construct_with_path(self):
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate.from_tree')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        state.unlock()
        self.build_tree_contents([('dirstate', ''.join(lines))])
        # get a state object
        # no parents, default tree content
        expected_result = ([], [
            (('', '', tree.path2id('')), # common details
             # current tree details, but new from_tree skips statting, it
             # uses set_state_from_inventory, and thus depends on the
             # inventory state.
             [('d', '', 0, False, dirstate.DirState.NULLSTAT),
             ])
            ])
        state = dirstate.DirState.on_file('dirstate')
        state.lock_write() # check_state_with_reopen will save() and unlock it
        self.check_state_with_reopen(expected_result, state)

    def test_can_save_clean_on_file(self):
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        try:
            # doing a save should work here as there have been no changes.
            state.save()
            # TODO: stat it and check it hasn't changed; may require waiting
            # for the state accuracy window.
        finally:
            state.unlock()


class TestDirStateInitialize(TestCaseWithDirState):

    def test_initialize(self):
        expected_result = ([], [
            (('', '', 'TREE_ROOT'), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ])
            ])
        state = dirstate.DirState.initialize('dirstate')
        try:
            self.assertIsInstance(state, dirstate.DirState)
            lines = state.get_lines()
            self.assertFileEqual(''.join(state.get_lines()),
                'dirstate')
            self.check_state_with_reopen(expected_result, state)
        except:
            state.unlock()
            raise


class TestDirStateManipulations(TestCaseWithDirState):

    def test_set_state_from_inventory_no_content_no_parents(self):
        # setting the current inventory is a slow but important api to support.
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        try:
            tree1.add('')
            revid1 = tree1.commit('foo').encode('utf8')
            root_id = tree1.inventory.root.file_id
            inv = tree1.inventory
        finally:
            tree1.unlock()
        expected_result = [], [
            (('', '', root_id), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT)])]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_state_from_inventory(inv)
            self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                             state._header_state)
            self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                             state._dirblock_state)
        except:
            state.unlock()
            raise
        else:
            # This will unlock it
            self.check_state_with_reopen(expected_result, state)

    def test_set_path_id_no_parents(self):
        """The id of a path can be changed trivally with no parents."""
        state = dirstate.DirState.initialize('dirstate')
        try:
            # check precondition to be sure the state does change appropriately.
            self.assertEqual(
                [(('', '', 'TREE_ROOT'), [('d', '', 0, False,
                   'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')])],
                list(state._iter_entries()))
            state.set_path_id('', 'foobarbaz')
            expected_rows = [
                (('', '', 'foobarbaz'), [('d', '', 0, False,
                   'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')])]
            self.assertEqual(expected_rows, list(state._iter_entries()))
            # should work across save too
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(expected_rows, list(state._iter_entries()))
        finally:
            state.unlock()

    def test_set_path_id_with_parents(self):
        """Set the root file id in a dirstate with parents"""
        mt = self.make_branch_and_tree('mt')
        # may need to set the root when the default format is one where it's
        # not TREE_ROOT
        mt.commit('foo', rev_id='parent-revid')
        rt = mt.branch.repository.revision_tree('parent-revid')
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_parent_trees([('parent-revid', rt)], ghosts=[])
            state.set_path_id('', 'foobarbaz')
            # now see that it is what we expected
            expected_rows = [
                (('', '', 'TREE_ROOT'),
                    [('a', '', 0, False, ''),
                     ('d', '', 0, False, 'parent-revid'),
                     ]),
                (('', '', 'foobarbaz'),
                    [('d', '', 0, False, ''),
                     ('a', '', 0, False, ''),
                     ]),
                ]
            self.assertEqual(expected_rows, list(state._iter_entries()))
            # should work across save too
            state.save()
        finally:
            state.unlock()
        # now flush & check we get the same
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(expected_rows, list(state._iter_entries()))
        finally:
            state.unlock()

    def test_set_parent_trees_no_content(self):
        # set_parent_trees is a slow but important api to support.
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        try:
            tree1.add('')
            revid1 = tree1.commit('foo')
        finally:
            tree1.unlock()
        branch2 = tree1.branch.bzrdir.clone('tree2').open_branch()
        tree2 = MemoryTree.create_on_branch(branch2)
        tree2.lock_write()
        try:
            revid2 = tree2.commit('foo')
            root_id = tree2.inventory.root.file_id
        finally:
            tree2.unlock()
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_path_id('', root_id)
            state.set_parent_trees(
                ((revid1, tree1.branch.repository.revision_tree(revid1)),
                 (revid2, tree2.branch.repository.revision_tree(revid2)),
                 ('ghost-rev', None)),
                ['ghost-rev'])
            # check we can reopen and use the dirstate after setting parent
            # trees.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_write()
        try:
            self.assertEqual([revid1, revid2, 'ghost-rev'],
                             state.get_parent_ids())
            # iterating the entire state ensures that the state is parsable.
            list(state._iter_entries())
            # be sure that it sets not appends - change it
            state.set_parent_trees(
                ((revid1, tree1.branch.repository.revision_tree(revid1)),
                 ('ghost-rev', None)),
                ['ghost-rev'])
            # and now put it back.
            state.set_parent_trees(
                ((revid1, tree1.branch.repository.revision_tree(revid1)),
                 (revid2, tree2.branch.repository.revision_tree(revid2)),
                 ('ghost-rev', tree2.branch.repository.revision_tree(None))),
                ['ghost-rev'])
            self.assertEqual([revid1, revid2, 'ghost-rev'],
                             state.get_parent_ids())
            # the ghost should be recorded as such by set_parent_trees.
            self.assertEqual(['ghost-rev'], state.get_ghosts())
            self.assertEqual(
                [(('', '', root_id), [
                  ('d', '', 0, False, dirstate.DirState.NULLSTAT),
                  ('d', '', 0, False, revid1),
                  ('d', '', 0, False, revid2)
                  ])],
                list(state._iter_entries()))
        finally:
            state.unlock()

    def test_set_parent_trees_file_missing_from_tree(self):
        # Adding a parent tree may reference files not in the current state.
        # they should get listed just once by id, even if they are in two
        # separate trees.
        # set_parent_trees is a slow but important api to support.
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        try:
            tree1.add('')
            tree1.add(['a file'], ['file-id'], ['file'])
            tree1.put_file_bytes_non_atomic('file-id', 'file-content')
            revid1 = tree1.commit('foo')
        finally:
            tree1.unlock()
        branch2 = tree1.branch.bzrdir.clone('tree2').open_branch()
        tree2 = MemoryTree.create_on_branch(branch2)
        tree2.lock_write()
        try:
            tree2.put_file_bytes_non_atomic('file-id', 'new file-content')
            revid2 = tree2.commit('foo')
            root_id = tree2.inventory.root.file_id
        finally:
            tree2.unlock()
        # check the layout in memory
        expected_result = [revid1.encode('utf8'), revid2.encode('utf8')], [
            (('', '', root_id), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT),
             ('d', '', 0, False, revid1.encode('utf8')),
             ('d', '', 0, False, revid2.encode('utf8'))
             ]),
            (('', 'a file', 'file-id'), [
             ('a', '', 0, False, ''),
             ('f', '2439573625385400f2a669657a7db6ae7515d371', 12, False,
              revid1.encode('utf8')),
             ('f', '542e57dc1cda4af37cb8e55ec07ce60364bb3c7d', 16, False,
              revid2.encode('utf8'))
             ])
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_path_id('', root_id)
            state.set_parent_trees(
                ((revid1, tree1.branch.repository.revision_tree(revid1)),
                 (revid2, tree2.branch.repository.revision_tree(revid2)),
                 ), [])
        except:
            state.unlock()
            raise
        else:
            # check_state_with_reopen will unlock
            self.check_state_with_reopen(expected_result, state)

    ### add a path via _set_data - so we dont need delta work, just
    # raw data in, and ensure that it comes out via get_lines happily.

    def test_add_path_to_root_no_parents_all_data(self):
        # The most trivial addition of a path is when there are no parents and
        # its in the root and all data about the file is supplied
        self.build_tree(['a file'])
        stat = os.lstat('a file')
        # the 1*20 is the sha1 pretend value.
        state = dirstate.DirState.initialize('dirstate')
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a file', 'a file id'), [
             ('f', '1'*20, 19, False, dirstate.pack_stat(stat)), # current tree
             ]),
            ]
        try:
            state.add('a file', 'a file id', 'file', stat, '1'*20)
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(expected_entries, list(state._iter_entries()))
        finally:
            state.unlock()

    def test_add_path_to_unversioned_directory(self):
        """Adding a path to an unversioned directory should error.

        This is a duplicate of TestWorkingTree.test_add_in_unversioned,
        once dirstate is stable and if it is merged with WorkingTree3, consider
        removing this copy of the test.
        """
        self.build_tree(['unversioned/', 'unversioned/a file'])
        state = dirstate.DirState.initialize('dirstate')
        try:
            self.assertRaises(errors.NotVersionedError, state.add,
                'unversioned/a file', 'a file id', 'file', None, None)
        finally:
            state.unlock()

    def test_add_directory_to_root_no_parents_all_data(self):
        # The most trivial addition of a dir is when there are no parents and
        # its in the root and all data about the file is supplied
        self.build_tree(['a dir/'])
        stat = os.lstat('a dir')
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a dir', 'a dir id'), [
             ('d', '', 0, False, dirstate.pack_stat(stat)), # current tree
             ]),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.add('a dir', 'a dir id', 'directory', stat, None)
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(expected_entries, list(state._iter_entries()))
        finally:
            state.unlock()

    def test_add_symlink_to_root_no_parents_all_data(self):
        # The most trivial addition of a symlink when there are no parents and
        # its in the root and all data about the file is supplied
        ## TODO: windows: dont fail this test. Also, how are symlinks meant to
        # be represented on windows.
        os.symlink('target', 'a link')
        stat = os.lstat('a link')
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a link', 'a link id'), [
             ('l', 'target', 6, False, dirstate.pack_stat(stat)), # current tree
             ]),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.add('a link', 'a link id', 'symlink', stat, 'target')
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(expected_entries, list(state._iter_entries()))
        finally:
            state.unlock()

    def test_add_directory_and_child_no_parents_all_data(self):
        # after adding a directory, we should be able to add children to it.
        self.build_tree(['a dir/', 'a dir/a file'])
        dirstat = os.lstat('a dir')
        filestat = os.lstat('a dir/a file')
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a dir', 'a dir id'), [
             ('d', '', 0, False, dirstate.pack_stat(dirstat)), # current tree
             ]),
            (('a dir', 'a file', 'a file id'), [
             ('f', '1'*20, 25, False,
              dirstate.pack_stat(filestat)), # current tree details
             ]),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.add('a dir', 'a dir id', 'directory', dirstat, None)
            state.add('a dir/a file', 'a file id', 'file', filestat, '1'*20)
            # added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(expected_entries, list(state._iter_entries()))
        finally:
            state.unlock()


class TestGetLines(TestCaseWithDirState):

    def test_get_line_with_2_rows(self):
        state = self.create_dirstate_with_root_and_subdir()
        try:
            self.assertEqual(['#bazaar dirstate flat format 3\n',
                'adler32: -1327947603\n',
                'num_entries: 2\n',
                '0\x00\n\x00'
                '0\x00\n\x00'
                '\x00\x00a-root-value\x00'
                'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\n\x00'
                '\x00subdir\x00subdir-id\x00'
                'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\n\x00'
                ], state.get_lines())
        finally:
            state.unlock()

    def test_entry_to_line(self):
        state = self.create_dirstate_with_root()
        try:
            self.assertEqual(
                '\x00\x00a-root-value\x00d\x00\x000\x00n'
                '\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk',
                state._entry_to_line(state._dirblocks[0][1][0]))
        finally:
            state.unlock()

    def test_entry_to_line_with_parent(self):
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat), # current tree details
             # first: a pointer to the current location
            ('a', 'dirname/basename', 0, False, ''),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            self.assertEqual(
                '\x00\x00a-root-value\x00'
                'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00'
                'a\x00dirname/basename\x000\x00n\x00',
                state._entry_to_line(root_entry))
        finally:
            state.unlock()

    def test_entry_to_line_with_two_parents_at_different_paths(self):
        # / in the tree, at / in one parent and /dirname/basename in the other.
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat), # current tree details
            ('d', '', 0, False, 'rev_id'), # first parent details
             # second: a pointer to the current location
            ('a', 'dirname/basename', 0, False, ''),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            self.assertEqual(
                '\x00\x00a-root-value\x00'
                'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00'
                'd\x00\x000\x00n\x00rev_id\x00'
                'a\x00dirname/basename\x000\x00n\x00',
                state._entry_to_line(root_entry))
        finally:
            state.unlock()

    def test_iter_entries(self):
        # we should be able to iterate the dirstate entries from end to end
        # this is for get_lines to be easy to read.
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        dirblocks = []
        root_entries = [(('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat), # current tree details
            ])]
        dirblocks.append(('', root_entries))
        # add two files in the root
        subdir_entry = ('', 'subdir', 'subdir-id'), [
            ('d', '', 0, False, packed_stat), # current tree details
            ]
        afile_entry = ('', 'afile', 'afile-id'), [
            ('f', 'sha1value', 34, False, packed_stat), # current tree details
            ]
        dirblocks.append(('', [subdir_entry, afile_entry]))
        # and one in subdir
        file_entry2 = ('subdir', '2file', '2file-id'), [
            ('f', 'sha1value', 23, False, packed_stat), # current tree details
            ]
        dirblocks.append(('subdir', [file_entry2]))
        state = dirstate.DirState.initialize('dirstate')
        try:
            state._set_data([], dirblocks)
            expected_entries = [root_entries[0], subdir_entry, afile_entry,
                                file_entry2]
            self.assertEqual(expected_entries, list(state._iter_entries()))
        finally:
            state.unlock()


class TestGetBlockRowIndex(TestCaseWithDirState):

    def assertBlockRowIndexEqual(self, block_index, row_index, dir_present,
        file_present, state, dirname, basename, tree_index):
        self.assertEqual((block_index, row_index, dir_present, file_present),
            state._get_block_entry_index(dirname, basename, tree_index))
        if dir_present:
            block = state._dirblocks[block_index]
            self.assertEqual(dirname, block[0])
        if dir_present and file_present:
            row = state._dirblocks[block_index][1][row_index]
            self.assertEqual(dirname, row[0][0])
            self.assertEqual(basename, row[0][1])

    def test_simple_structure(self):
        state = self.create_dirstate_with_root_and_subdir()
        self.addCleanup(state.unlock)
        self.assertBlockRowIndexEqual(1, 0, True, True, state, '', 'subdir', 0)
        self.assertBlockRowIndexEqual(1, 0, True, False, state, '', 'bdir', 0)
        self.assertBlockRowIndexEqual(1, 1, True, False, state, '', 'zdir', 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, 'a', 'foo', 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state,
                                      'subdir', 'foo', 0)

    def test_complex_structure_exists(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        # Make sure we can find everything that exists
        self.assertBlockRowIndexEqual(0, 0, True, True, state, '', '', 0)
        self.assertBlockRowIndexEqual(1, 0, True, True, state, '', 'a', 0)
        self.assertBlockRowIndexEqual(1, 1, True, True, state, '', 'b', 0)
        self.assertBlockRowIndexEqual(1, 2, True, True, state, '', 'c', 0)
        self.assertBlockRowIndexEqual(1, 3, True, True, state, '', 'd', 0)
        self.assertBlockRowIndexEqual(2, 0, True, True, state, 'a', 'e', 0)
        self.assertBlockRowIndexEqual(2, 1, True, True, state, 'a', 'f', 0)
        self.assertBlockRowIndexEqual(3, 0, True, True, state, 'b', 'g', 0)
        self.assertBlockRowIndexEqual(3, 1, True, True, state,
                                      'b', 'h\xc3\xa5', 0)

    def test_complex_structure_missing(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        # Make sure things would be inserted in the right locations
        # '_' comes before 'a'
        self.assertBlockRowIndexEqual(0, 0, True, True, state, '', '', 0)
        self.assertBlockRowIndexEqual(1, 0, True, False, state, '', '_', 0)
        self.assertBlockRowIndexEqual(1, 1, True, False, state, '', 'aa', 0)
        self.assertBlockRowIndexEqual(1, 4, True, False, state,
                                      '', 'h\xc3\xa5', 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, '_', 'a', 0)
        self.assertBlockRowIndexEqual(3, 0, False, False, state, 'aa', 'a', 0)
        self.assertBlockRowIndexEqual(4, 0, False, False, state, 'bb', 'a', 0)
        # This would be inserted between a/ and b/
        self.assertBlockRowIndexEqual(3, 0, False, False, state, 'a/e', 'a', 0)
        # Put at the end
        self.assertBlockRowIndexEqual(4, 0, False, False, state, 'e', 'a', 0)


class TestGetEntry(TestCaseWithDirState):

    def assertEntryEqual(self, dirname, basename, file_id, state, path, index):
        """Check that the right entry is returned for a request to getEntry."""
        entry = state._get_entry(index, path_utf8=path)
        if file_id is None:
            self.assertEqual((None, None), entry)
        else:
            cur = entry[0]
            self.assertEqual((dirname, basename, file_id), cur[:3])

    def test_simple_structure(self):
        state = self.create_dirstate_with_root_and_subdir()
        self.addCleanup(state.unlock)
        self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
        self.assertEntryEqual('', 'subdir', 'subdir-id', state, 'subdir', 0)
        self.assertEntryEqual(None, None, None, state, 'missing', 0)
        self.assertEntryEqual(None, None, None, state, 'missing/foo', 0)
        self.assertEntryEqual(None, None, None, state, 'subdir/foo', 0)

    def test_complex_structure_exists(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
        self.assertEntryEqual('', 'a', 'a-dir', state, 'a', 0)
        self.assertEntryEqual('', 'b', 'b-dir', state, 'b', 0)
        self.assertEntryEqual('', 'c', 'c-file', state, 'c', 0)
        self.assertEntryEqual('', 'd', 'd-file', state, 'd', 0)
        self.assertEntryEqual('a', 'e', 'e-dir', state, 'a/e', 0)
        self.assertEntryEqual('a', 'f', 'f-file', state, 'a/f', 0)
        self.assertEntryEqual('b', 'g', 'g-file', state, 'b/g', 0)
        self.assertEntryEqual('b', 'h\xc3\xa5', 'h-\xc3\xa5-file', state,
                              'b/h\xc3\xa5', 0)

    def test_complex_structure_missing(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        self.assertEntryEqual(None, None, None, state, '_', 0)
        self.assertEntryEqual(None, None, None, state, '_\xc3\xa5', 0)
        self.assertEntryEqual(None, None, None, state, 'a/b', 0)
        self.assertEntryEqual(None, None, None, state, 'c/d', 0)

    def test_get_entry_uninitialized(self):
        """Calling get_entry will load data if it needs to"""
        state = self.create_dirstate_with_root()
        try:
            state.save()
        finally:
            state.unlock()
        del state
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._header_state)
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
        finally:
            state.unlock()


class TestDirstateSortOrder(TestCaseWithTransport):
    """Test that DirState adds entries in the right order."""

    def test_add_sorting(self):
        """Add entries in lexicographical order, we get path sorted order.

        This tests it to a depth of 4, to make sure we don't just get it right
        at a single depth. 'a/a' should come before 'a-a', even though it
        doesn't lexicographically.
        """
        dirs = ['a', 'a/a', 'a/a/a', 'a/a/a/a',
                'a-a', 'a/a-a', 'a/a/a-a', 'a/a/a/a-a',
               ]
        null_sha = ''
        state = dirstate.DirState.initialize('dirstate')
        self.addCleanup(state.unlock)

        fake_stat = os.stat('dirstate')
        for d in dirs:
            d_id = d.replace('/', '_')+'-id'
            file_path = d + '/f'
            file_id = file_path.replace('/', '_')+'-id'
            state.add(d, d_id, 'directory', fake_stat, null_sha)
            state.add(file_path, file_id, 'file', fake_stat, null_sha)

        expected = ['', '', 'a',
                'a/a', 'a/a/a', 'a/a/a/a',
                'a/a/a/a-a', 'a/a/a-a', 'a/a-a', 'a-a',
               ]
        split = lambda p:p.split('/')
        self.assertEqual(sorted(expected, key=split), expected)
        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)

    def test_set_parent_trees_correct_order(self):
        """After calling set_parent_trees() we should maintain the order."""
        dirs = ['a', 'a-a', 'a/a']
        null_sha = ''
        state = dirstate.DirState.initialize('dirstate')
        self.addCleanup(state.unlock)

        fake_stat = os.stat('dirstate')
        for d in dirs:
            d_id = d.replace('/', '_')+'-id'
            file_path = d + '/f'
            file_id = file_path.replace('/', '_')+'-id'
            state.add(d, d_id, 'directory', fake_stat, null_sha)
            state.add(file_path, file_id, 'file', fake_stat, null_sha)

        expected = ['', '', 'a', 'a/a', 'a-a']
        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)

        # *really* cheesy way to just get an empty tree
        repo = self.make_repository('repo')
        empty_tree = repo.revision_tree(None)
        state.set_parent_trees([('null:', empty_tree)], [])

        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)


class TestBisect(TestCaseWithTransport):
    """Test the ability to bisect into the disk format."""

    def create_basic_dirstate(self):
        """Create a dirstate with a few files and directories.

            a
            b/
              c
              d/
                e
            f
        """
        tree = self.make_branch_and_tree('tree')
        paths = ['a', 'b/', 'b/c', 'b/d/', 'b/d/e', 'f']
        file_ids = ['a-id', 'b-id', 'c-id', 'd-id', 'e-id', 'f-id']
        self.build_tree(['tree/' + p for p in paths])
        tree.set_root_id('TREE_ROOT')
        tree.add([p.rstrip('/') for p in paths], file_ids)
        tree.commit('initial', rev_id='rev-1')
        revision_id = 'rev-1'
        # a_packed_stat = dirstate.pack_stat(os.stat('tree/a'))
        t = self.get_transport().clone('tree')
        a_text = t.get_bytes('a')
        a_sha = osutils.sha_string(a_text)
        a_len = len(a_text)
        # b_packed_stat = dirstate.pack_stat(os.stat('tree/b'))
        # c_packed_stat = dirstate.pack_stat(os.stat('tree/b/c'))
        c_text = t.get_bytes('b/c')
        c_sha = osutils.sha_string(c_text)
        c_len = len(c_text)
        # d_packed_stat = dirstate.pack_stat(os.stat('tree/b/d'))
        # e_packed_stat = dirstate.pack_stat(os.stat('tree/b/d/e'))
        e_text = t.get_bytes('b/d/e')
        e_sha = osutils.sha_string(e_text)
        e_len = len(e_text)
        # f_packed_stat = dirstate.pack_stat(os.stat('tree/f'))
        f_text = t.get_bytes('f')
        f_sha = osutils.sha_string(f_text)
        f_len = len(f_text)
        null_stat = dirstate.DirState.NULLSTAT
        expected = {
            '':(('', '', 'TREE_ROOT'), [
                  ('d', '', 0, False, null_stat),
                  ('d', '', 0, False, revision_id),
                ]),
            'a':(('', 'a', 'a-id'), [
                   ('f', '', 0, False, null_stat),
                   ('f', a_sha, a_len, False, revision_id),
                 ]),
            'b':(('', 'b', 'b-id'), [
                  ('d', '', 0, False, null_stat),
                  ('d', '', 0, False, revision_id),
                 ]),
            'b/c':(('b', 'c', 'c-id'), [
                    ('f', '', 0, False, null_stat),
                    ('f', c_sha, c_len, False, revision_id),
                   ]),
            'b/d':(('b', 'd', 'd-id'), [
                    ('d', '', 0, False, null_stat),
                    ('d', '', 0, False, revision_id),
                   ]),
            'b/d/e':(('b/d', 'e', 'e-id'), [
                      ('f', '', 0, False, null_stat),
                      ('f', e_sha, e_len, False, revision_id),
                     ]),
            'f':(('', 'f', 'f-id'), [
                  ('f', '', 0, False, null_stat),
                  ('f', f_sha, f_len, False, revision_id),
                 ]),
        }
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        try:
            state.save()
        finally:
            state.unlock()
        # Use a different object, to make sure nothing is pre-cached in memory.
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                         state._dirblock_state)
        # This is code is only really tested if we actually have to make more
        # than one read, so set the page size to something smaller.
        # We want it to contain about 2.2 records, so that we have a couple
        # records that we can read per attempt
        state._bisect_page_size = 200
        return tree, state, expected

    def create_duplicated_dirstate(self):
        """Create a dirstate with a deleted and added entries.

        This grabs a basic_dirstate, and then removes and re adds every entry
        with a new file id.
        """
        tree, state, expected = self.create_basic_dirstate()
        # Now we will just remove and add every file so we get an extra entry
        # per entry. Unversion in reverse order so we handle subdirs
        tree.unversion(['f-id', 'e-id', 'd-id', 'c-id', 'b-id', 'a-id'])
        tree.add(['a', 'b', 'b/c', 'b/d', 'b/d/e', 'f'],
                 ['a-id2', 'b-id2', 'c-id2', 'd-id2', 'e-id2', 'f-id2'])

        # Update the expected dictionary.
        for path in ['a', 'b', 'b/c', 'b/d', 'b/d/e', 'f']:
            orig = expected[path]
            path2 = path + '2'
            # This record was deleted in the current tree
            expected[path] = (orig[0], [dirstate.DirState.NULL_PARENT_DETAILS,
                                        orig[1][1]])
            new_key = (orig[0][0], orig[0][1], orig[0][2]+'2')
            # And didn't exist in the basis tree
            expected[path2] = (new_key, [orig[1][0],
                                         dirstate.DirState.NULL_PARENT_DETAILS])

        # We will replace the 'dirstate' file underneath 'state', but that is
        # okay as lock as we unlock 'state' first.
        state.unlock()
        try:
            new_state = dirstate.DirState.from_tree(tree, 'dirstate')
            try:
                new_state.save()
            finally:
                new_state.unlock()
        finally:
            # But we need to leave state in a read-lock because we already have
            # a cleanup scheduled
            state.lock_read()
        return tree, state, expected

    def create_renamed_dirstate(self):
        """Create a dirstate with a few internal renames.

        This takes the basic dirstate, and moves the paths around.
        """
        tree, state, expected = self.create_basic_dirstate()
        # Rename a file
        tree.rename_one('a', 'b/g')
        # And a directory
        tree.rename_one('b/d', 'h')

        old_a = expected['a']
        expected['a'] = (old_a[0], [('r', 'b/g', 0, False, ''), old_a[1][1]])
        expected['b/g'] = (('b', 'g', 'a-id'), [old_a[1][0],
                                                ('r', 'a', 0, False, '')])
        old_d = expected['b/d']
        expected['b/d'] = (old_d[0], [('r', 'h', 0, False, ''), old_d[1][1]])
        expected['h'] = (('', 'h', 'd-id'), [old_d[1][0],
                                             ('r', 'b/d', 0, False, '')])

        old_e = expected['b/d/e']
        expected['b/d/e'] = (old_e[0], [('r', 'h/e', 0, False, ''),
                             old_e[1][1]])
        expected['h/e'] = (('h', 'e', 'e-id'), [old_e[1][0],
                                                ('r', 'b/d/e', 0, False, '')])

        state.unlock()
        try:
            new_state = dirstate.DirState.from_tree(tree, 'dirstate')
            try:
                new_state.save()
            finally:
                new_state.unlock()
        finally:
            state.lock_read()
        return tree, state, expected

    def assertBisect(self, expected_map, map_keys, state, paths):
        """Assert that bisecting for paths returns the right result.

        :param expected_map: A map from key => entry value
        :param map_keys: The keys to expect for each path
        :param state: The DirState object.
        :param paths: A list of paths, these will automatically be split into
                      (dir, name) tuples, and sorted according to how _bisect
                      requires.
        """
        dir_names = sorted(osutils.split(p) for p in paths)
        result = state._bisect(dir_names)
        # For now, results are just returned in whatever order we read them.
        # We could sort by (dir, name, file_id) or something like that, but in
        # the end it would still be fairly arbitrary, and we don't want the
        # extra overhead if we can avoid it. So sort everything to make sure
        # equality is true
        assert len(map_keys) == len(dir_names)
        expected = {}
        for dir_name, keys in zip(dir_names, map_keys):
            if keys is None:
                # This should not be present in the output
                continue
            expected[dir_name] = sorted(expected_map[k] for k in keys)

        for dir_name in result:
            result[dir_name].sort()

        self.assertEqual(expected, result)

    def assertBisectDirBlocks(self, expected_map, map_keys, state, paths):
        """Assert that bisecting for dirbblocks returns the right result.

        :param expected_map: A map from key => expected values
        :param map_keys: A nested list of paths we expect to be returned.
            Something like [['a', 'b', 'f'], ['b/c', 'b/d']]
        :param state: The DirState object.
        :param paths: A list of directories
        """
        result = state._bisect_dirblocks(paths)
        assert len(map_keys) == len(paths)

        expected = {}
        for path, keys in zip(paths, map_keys):
            if keys is None:
                # This should not be present in the output
                continue
            expected[path] = sorted(expected_map[k] for k in keys)
        for path in result:
            result[path].sort()

        self.assertEqual(expected, result)

    def assertBisectRecursive(self, expected_map, map_keys, state, paths):
        """Assert the return value of a recursive bisection.

        :param expected_map: A map from key => entry value
        :param map_keys: A list of paths we expect to be returned.
            Something like ['a', 'b', 'f', 'b/d', 'b/d2']
        :param state: The DirState object.
        :param paths: A list of files and directories. It will be broken up
            into (dir, name) pairs and sorted before calling _bisect_recursive.
        """
        expected = {}
        for key in map_keys:
            entry = expected_map[key]
            dir_name_id, trees_info = entry
            expected[dir_name_id] = trees_info

        dir_names = sorted(osutils.split(p) for p in paths)
        result = state._bisect_recursive(dir_names)

        self.assertEqual(expected, result)

    def test_bisect_each(self):
        """Find a single record using bisect."""
        tree, state, expected = self.create_basic_dirstate()

        # Bisect should return the rows for the specified files.
        self.assertBisect(expected, [['']], state, [''])
        self.assertBisect(expected, [['a']], state, ['a'])
        self.assertBisect(expected, [['b']], state, ['b'])
        self.assertBisect(expected, [['b/c']], state, ['b/c'])
        self.assertBisect(expected, [['b/d']], state, ['b/d'])
        self.assertBisect(expected, [['b/d/e']], state, ['b/d/e'])
        self.assertBisect(expected, [['f']], state, ['f'])

    def test_bisect_multi(self):
        """Bisect can be used to find multiple records at the same time."""
        tree, state, expected = self.create_basic_dirstate()
        # Bisect should be capable of finding multiple entries at the same time
        self.assertBisect(expected, [['a'], ['b'], ['f']],
                          state, ['a', 'b', 'f'])
        # ('', 'f') sorts before the others
        self.assertBisect(expected, [['f'], ['b/d'], ['b/d/e']],
                          state, ['b/d', 'b/d/e', 'f'])

    def test_bisect_one_page(self):
        """Test bisect when there is only 1 page to read"""
        tree, state, expected = self.create_basic_dirstate()
        state._bisect_page_size = 5000
        self.assertBisect(expected,[['']], state, [''])
        self.assertBisect(expected,[['a']], state, ['a'])
        self.assertBisect(expected,[['b']], state, ['b'])
        self.assertBisect(expected,[['b/c']], state, ['b/c'])
        self.assertBisect(expected,[['b/d']], state, ['b/d'])
        self.assertBisect(expected,[['b/d/e']], state, ['b/d/e'])
        self.assertBisect(expected,[['f']], state, ['f'])
        self.assertBisect(expected,[['a'], ['b'], ['f']],
                          state, ['a', 'b', 'f'])
        # ('', 'f') sorts before the others
        self.assertBisect(expected, [['f'], ['b/d'], ['b/d/e']],
                          state, ['b/d', 'b/d/e', 'f'])

    def test_bisect_duplicate_paths(self):
        """When bisecting for a path, handle multiple entries."""
        tree, state, expected = self.create_duplicated_dirstate()

        # Now make sure that both records are properly returned.
        self.assertBisect(expected, [['']], state, [''])
        self.assertBisect(expected, [['a', 'a2']], state, ['a'])
        self.assertBisect(expected, [['b', 'b2']], state, ['b'])
        self.assertBisect(expected, [['b/c', 'b/c2']], state, ['b/c'])
        self.assertBisect(expected, [['b/d', 'b/d2']], state, ['b/d'])
        self.assertBisect(expected, [['b/d/e', 'b/d/e2']],
                          state, ['b/d/e'])
        self.assertBisect(expected, [['f', 'f2']], state, ['f'])

    def test_bisect_page_size_too_small(self):
        """If the page size is too small, we will auto increase it."""
        tree, state, expected = self.create_basic_dirstate()
        state._bisect_page_size = 50
        self.assertBisect(expected, [None], state, ['b/e'])
        self.assertBisect(expected, [['a']], state, ['a'])
        self.assertBisect(expected, [['b']], state, ['b'])
        self.assertBisect(expected, [['b/c']], state, ['b/c'])
        self.assertBisect(expected, [['b/d']], state, ['b/d'])
        self.assertBisect(expected, [['b/d/e']], state, ['b/d/e'])
        self.assertBisect(expected, [['f']], state, ['f'])

    def test_bisect_missing(self):
        """Test that bisect return None if it cannot find a path."""
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisect(expected, [None], state, ['foo'])
        self.assertBisect(expected, [None], state, ['b/foo'])
        self.assertBisect(expected, [None], state, ['bar/foo'])

        self.assertBisect(expected, [['a'], None, ['b/d']],
                          state, ['a', 'foo', 'b/d'])

    def test_bisect_rename(self):
        """Check that we find a renamed row."""
        tree, state, expected = self.create_renamed_dirstate()

        # Search for the pre and post renamed entries
        self.assertBisect(expected, [['a']], state, ['a'])
        self.assertBisect(expected, [['b/g']], state, ['b/g'])
        self.assertBisect(expected, [['b/d']], state, ['b/d'])
        self.assertBisect(expected, [['h']], state, ['h'])

        # What about b/d/e? shouldn't that also get 2 directory entries?
        self.assertBisect(expected, [['b/d/e']], state, ['b/d/e'])
        self.assertBisect(expected, [['h/e']], state, ['h/e'])

    def test_bisect_dirblocks(self):
        tree, state, expected = self.create_duplicated_dirstate()
        self.assertBisectDirBlocks(expected,
            [['', 'a', 'a2', 'b', 'b2', 'f', 'f2']], state, [''])
        self.assertBisectDirBlocks(expected,
            [['b/c', 'b/c2', 'b/d', 'b/d2']], state, ['b'])
        self.assertBisectDirBlocks(expected,
            [['b/d/e', 'b/d/e2']], state, ['b/d'])
        self.assertBisectDirBlocks(expected,
            [['', 'a', 'a2', 'b', 'b2', 'f', 'f2'],
             ['b/c', 'b/c2', 'b/d', 'b/d2'],
             ['b/d/e', 'b/d/e2'],
            ], state, ['', 'b', 'b/d'])

    def test_bisect_dirblocks_missing(self):
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisectDirBlocks(expected, [['b/d/e'], None],
            state, ['b/d', 'b/e'])
        # Files don't show up in this search
        self.assertBisectDirBlocks(expected, [None], state, ['a'])
        self.assertBisectDirBlocks(expected, [None], state, ['b/c'])
        self.assertBisectDirBlocks(expected, [None], state, ['c'])
        self.assertBisectDirBlocks(expected, [None], state, ['b/d/e'])
        self.assertBisectDirBlocks(expected, [None], state, ['f'])

    def test_bisect_recursive_each(self):
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, ['a'], state, ['a'])
        self.assertBisectRecursive(expected, ['b/c'], state, ['b/c'])
        self.assertBisectRecursive(expected, ['b/d/e'], state, ['b/d/e'])
        self.assertBisectRecursive(expected, ['b/d', 'b/d/e'],
                                   state, ['b/d'])
        self.assertBisectRecursive(expected, ['b', 'b/c', 'b/d', 'b/d/e'],
                                   state, ['b'])
        self.assertBisectRecursive(expected, ['', 'a', 'b', 'f', 'b/c',
                                              'b/d', 'b/d/e'],
                                   state, [''])

    def test_bisect_recursive_multiple(self):
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, ['a', 'b/c'], state, ['a', 'b/c'])
        self.assertBisectRecursive(expected, ['b/d', 'b/d/e'],
                                   state, ['b/d', 'b/d/e'])

    def test_bisect_recursive_missing(self):
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, [], state, ['d'])
        self.assertBisectRecursive(expected, [], state, ['b/e'])
        self.assertBisectRecursive(expected, [], state, ['g'])
        self.assertBisectRecursive(expected, ['a'], state, ['a', 'g'])

    def test_bisect_recursive_renamed(self):
        tree, state, expected = self.create_renamed_dirstate()

        # Looking for either renamed item should find the other
        self.assertBisectRecursive(expected, ['a', 'b/g'], state, ['a'])
        self.assertBisectRecursive(expected, ['a', 'b/g'], state, ['b/g'])
        # Looking in the containing directory should find the rename target,
        # and anything in a subdir of the renamed target.
        self.assertBisectRecursive(expected, ['a', 'b', 'b/c', 'b/d',
                                              'b/d/e', 'b/g', 'h', 'h/e'],
                                   state, ['b'])


class TestBisectDirblock(TestCase):
    """Test that bisect_dirblock() returns the expected values.

    bisect_dirblock is intended to work like bisect.bisect_left() except it
    knows it is working on dirblocks and that dirblocks are sorted by ('path',
    'to', 'foo') chunks rather than by raw 'path/to/foo'.
    """

    def assertBisect(self, dirblocks, split_dirblocks, path, *args, **kwargs):
        """Assert that bisect_split works like bisect_left on the split paths.

        :param dirblocks: A list of (path, [info]) pairs.
        :param split_dirblocks: A list of ((split, path), [info]) pairs.
        :param path: The path we are indexing.

        All other arguments will be passed along.
        """
        bisect_split_idx = dirstate.bisect_dirblock(dirblocks, path,
                                                 *args, **kwargs)
        split_dirblock = (path.split('/'), [])
        bisect_left_idx = bisect.bisect_left(split_dirblocks, split_dirblock,
                                             *args)
        self.assertEqual(bisect_left_idx, bisect_split_idx,
                         'bisect_split disagreed. %s != %s'
                         ' for key %s'
                         % (bisect_left_idx, bisect_split_idx, path)
                         )

    def paths_to_dirblocks(self, paths):
        """Convert a list of paths into dirblock form.

        Also, ensure that the paths are in proper sorted order.
        """
        dirblocks = [(path, []) for path in paths]
        split_dirblocks = [(path.split('/'), []) for path in paths]
        self.assertEqual(sorted(split_dirblocks), split_dirblocks)
        return dirblocks, split_dirblocks

    def test_simple(self):
        """In the simple case it works just like bisect_left"""
        paths = ['', 'a', 'b', 'c', 'd']
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path)
        self.assertBisect(dirblocks, split_dirblocks, '_')
        self.assertBisect(dirblocks, split_dirblocks, 'aa')
        self.assertBisect(dirblocks, split_dirblocks, 'bb')
        self.assertBisect(dirblocks, split_dirblocks, 'cc')
        self.assertBisect(dirblocks, split_dirblocks, 'dd')
        self.assertBisect(dirblocks, split_dirblocks, 'a/a')
        self.assertBisect(dirblocks, split_dirblocks, 'b/b')
        self.assertBisect(dirblocks, split_dirblocks, 'c/c')
        self.assertBisect(dirblocks, split_dirblocks, 'd/d')

    def test_involved(self):
        """This is where bisect_left diverges slightly."""
        paths = ['', 'a',
                 'a/a', 'a/a/a', 'a/a/z', 'a/a-a', 'a/a-z',
                 'a/z', 'a/z/a', 'a/z/z', 'a/z-a', 'a/z-z',
                 'a-a', 'a-z',
                 'z', 'z/a/a', 'z/a/z', 'z/a-a', 'z/a-z',
                 'z/z', 'z/z/a', 'z/z/z', 'z/z-a', 'z/z-z',
                 'z-a', 'z-z',
                ]
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path)

    def test_involved_cached(self):
        """This is where bisect_left diverges slightly."""
        paths = ['', 'a',
                 'a/a', 'a/a/a', 'a/a/z', 'a/a-a', 'a/a-z',
                 'a/z', 'a/z/a', 'a/z/z', 'a/z-a', 'a/z-z',
                 'a-a', 'a-z',
                 'z', 'z/a/a', 'z/a/z', 'z/a-a', 'z/a-z',
                 'z/z', 'z/z/a', 'z/z/z', 'z/z-a', 'z/z-z',
                 'z-a', 'z-z',
                ]
        cache = {}
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path, cache=cache)

