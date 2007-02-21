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

import os

from bzrlib import dirstate, errors
from bzrlib.dirstate import DirState
from bzrlib.memorytree import MemoryTree
from bzrlib.tests import TestCaseWithTransport


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
        state = dirstate.DirState.initialize('dirstate')
        return state

    def create_dirstate_with_root(self):
        state = self.create_empty_dirstate()
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry_direntry = ('', '', 'a-root-value'), [
            ('directory', '', 0, False, packed_stat),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry_direntry]))
        dirblocks.append(('', []))
        state._set_data([], dirblocks)
        return state

    def create_dirstate_with_root_and_subdir(self):
        state = self.create_dirstate_with_root()
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        dirblocks = list(state._dirblocks)
        subdir_entry = ('', 'subdir', 'subdir-id'), [
            ('directory', '', 0, False, packed_stat),
            ]
        dirblocks[1][1].append(subdir_entry)
        state._set_data([], dirblocks)
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
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        null_sha = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        root_entry = ('', '', 'a-root-value'), [
            ('directory', '', 0, False, packed_stat),
            ]
        a_entry = ('', 'a', 'a-dir'), [
            ('directory', '', 0, False, packed_stat),
            ]
        b_entry = ('', 'b', 'b-dir'), [
            ('directory', '', 0, False, packed_stat),
            ]
        c_entry = ('', 'c', 'c-file'), [
            ('file', null_sha, 10, False, packed_stat),
            ]
        d_entry = ('', 'd', 'd-file'), [
            ('file', null_sha, 20, False, packed_stat),
            ]
        e_entry = ('a', 'e', 'e-dir'), [
            ('directory', '', 0, False, packed_stat),
            ]
        f_entry = ('a', 'f', 'f-file'), [
            ('file', null_sha, 30, False, packed_stat),
            ]
        g_entry = ('b', 'g', 'g-file'), [
            ('file', null_sha, 30, False, packed_stat),
            ]
        h_entry = ('b', 'h\xc3\xa5', 'h-\xc3\xa5-file'), [
            ('file', null_sha, 40, False, packed_stat),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry]))
        dirblocks.append(('', [a_entry, b_entry, c_entry, d_entry]))
        dirblocks.append(('a', [e_entry, f_entry]))
        dirblocks.append(('b', [g_entry, h_entry]))
        state._set_data([], dirblocks)
        return state

    def check_state_with_reopen(self, expected_result, state):
        """Check that state has current state expected_result.
        
        This will check the current state, open the file anew and check it
        again.
        """
        self.assertEqual(expected_result[0],  state.get_parent_ids())
        # there should be no ghosts in this tree.
        self.assertEqual([], state.get_ghosts())
        # there should be one fileid in this tree - the root of the tree.
        self.assertEqual(expected_result[1], list(state._iter_entries()))
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_result[1], list(state._iter_entries()))


class TestTreeToDirState(TestCaseWithDirState):

    def test_empty_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        expected_result = ([], [
            (('', '', tree.path2id('')), # common details
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
             ])])
        self.check_state_with_reopen(expected_result, state)

    def test_1_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post').encode('utf8')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        root_stat_pack = dirstate.pack_stat(os.stat(tree.basedir))
        expected_result = ([rev_id], [
            (('', '', tree.path2id('')), # common details
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
              ('directory', '', 0, False, rev_id), # first parent details
             ])])
        self.check_state_with_reopen(expected_result, state)

    def test_2_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        rev_id2 = tree2.commit('second post', allow_pointless=True)
        tree.merge_from_branch(tree2.branch)
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        expected_result = ([rev_id, rev_id2], [
            (('', '', tree.path2id('')), # common details
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
              ('directory', '', 0, False, rev_id), # first parent details
              ('directory', '', 0, False, rev_id2), # second parent details
             ])])
        self.check_state_with_reopen(expected_result, state)
        
    def test_empty_unknowns_are_ignored_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unknown'])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        expected_result = ([], [
            (('', '', tree.path2id('')), # common details
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
             ])])
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
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        expected_result = ([], [
            (('', '', tree.path2id('')), # common details
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
             ]),
            (('', 'a file', 'a file id'), # common
             [('file', '', 0, False, dirstate.DirState.NULLSTAT), # current
             ]),
            ])
        self.check_state_with_reopen(expected_result, state)

    def test_1_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit('first post').encode('utf8')
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([('tree/a file', 'new content\n')])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        expected_result = ([rev_id], [
            (('', '', tree.path2id('')), # common details
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
              ('directory', '', 0, False, rev_id), # first parent details
             ]),
            (('', 'a file', 'a file id'), # common
             [('file', '', 0, False, dirstate.DirState.NULLSTAT), # current
              ('file', 'c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8', 24, False, rev_id), # first parent
             ]),
            ])
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
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        expected_result = ([rev_id, rev_id2], [
            (('', '', tree.path2id('')), # common details
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
              ('directory', '', 0, False, rev_id), # first parent details
              ('directory', '', 0, False, rev_id2), # second parent details
             ]),
            (('', 'a file', 'a file id'), # common
             [('file', '', 0, False, dirstate.DirState.NULLSTAT), # current
              ('file', 'c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8', 24, False, rev_id), # first parent
              ('file', '314d796174c9412647c3ce07dfb5d36a94e72958', 14, False, rev_id2), # second parent
             ]),
            ])
        self.check_state_with_reopen(expected_result, state)


class TestDirStateOnFile(TestCaseWithDirState):

    def test_construct_with_path(self):
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate.from_tree')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        self.build_tree_contents([('dirstate', ''.join(lines))])
        # get a state object
        state = dirstate.DirState.on_file('dirstate')
        # no parents, default tree content
        expected_result = ([], [
            (('', '', tree.path2id('')), # common details
             # current tree details, but new from_tree skips statting, it
             # uses set_state_from_inventory, and thus depends on the
             # inventory state.
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT),
             ])
            ])
        self.check_state_with_reopen(expected_result, state)

    def test_can_save_clean_on_file(self):
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        # doing a save should work here as there have been no changes.
        state.save()
        # TODO: stat it and check it hasn't changed; may require waiting for
        # the state accuracy window.


class TestDirStateInitialize(TestCaseWithDirState):

    def test_initialize(self):
        state = dirstate.DirState.initialize('dirstate')
        self.assertIsInstance(state, dirstate.DirState)
        lines = state.get_lines()
        self.assertFileEqual(''.join(state.get_lines()),
            'dirstate')
        expected_result = ([], [
            (('', '', 'TREE_ROOT'), # common details
             [('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ])
            ])
        self.check_state_with_reopen(expected_result, state)


class TestDirStateManipulations(TestCaseWithDirState):

    def test_set_state_from_inventory_no_content_no_parents(self):
        # setting the current inventory is a slow but important api to support.
        state = dirstate.DirState.initialize('dirstate')
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        tree1.add('')
        revid1 = tree1.commit('foo').encode('utf8')
        root_id = tree1.inventory.root.file_id
        state.set_state_from_inventory(tree1.inventory)
        tree1.unlock()
        self.assertEqual(DirState.IN_MEMORY_UNMODIFIED, state._header_state)
        self.assertEqual(DirState.IN_MEMORY_MODIFIED, state._dirblock_state)
        expected_result = [], [
            (('', '', root_id), [
             ('directory', '', 0, False, DirState.NULLSTAT)])]
        self.check_state_with_reopen(expected_result, state)

    def test_set_path_id_no_parents(self):
        """The id of a path can be changed trivally with no parents."""
        state = dirstate.DirState.initialize('dirstate')
        # check precondition to be sure the state does change appropriately.
        self.assertEqual(
            [(('', '', 'TREE_ROOT'), [('directory', '', 0, False, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')])],
            list(state._iter_entries()))
        state.set_path_id('', 'foobarbaz')
        expected_rows = [
            (('', '', 'foobarbaz'), [('directory', '', 0, False, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')])]
        self.assertEqual(expected_rows, list(state._iter_entries()))
        # should work across save too
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_rows, list(state._iter_entries()))

    def test_set_parent_trees_no_content(self):
        # set_parent_trees is a slow but important api to support.
        state = dirstate.DirState.initialize('dirstate')
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        tree1.add('')
        revid1 = tree1.commit('foo')
        tree1.unlock()
        branch2 = tree1.branch.bzrdir.clone('tree2').open_branch()
        tree2 = MemoryTree.create_on_branch(branch2)
        tree2.lock_write()
        revid2 = tree2.commit('foo')
        root_id = tree2.inventory.root.file_id
        state.set_path_id('', root_id)
        tree2.unlock()
        state.set_parent_trees(
            ((revid1, tree1.branch.repository.revision_tree(revid1)),
             (revid2, tree2.branch.repository.revision_tree(revid2)),
             ('ghost-rev', None)),
            ['ghost-rev'])
        # check we can reopen and use the dirstate after setting parent trees.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual([revid1, revid2, 'ghost-rev'],  state.get_parent_ids())
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
        self.assertEqual([revid1, revid2, 'ghost-rev'],  state.get_parent_ids())
        # the ghost should be recorded as such by set_parent_trees.
        self.assertEqual(['ghost-rev'], state.get_ghosts())
        self.assertEqual(
            [(('', '', root_id), [
              ('directory', '', 0, False, DirState.NULLSTAT),
              ('directory', '', 0, False, revid1),
              ('directory', '', 0, False, revid2)
              ])],
            list(state._iter_entries()))

    def test_set_parent_trees_file_missing_from_tree(self):
        # Adding a parent tree may reference files not in the current state.
        # they should get listed just once by id, even if they are in two  
        # separate trees.
        # set_parent_trees is a slow but important api to support.
        state = dirstate.DirState.initialize('dirstate')
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        tree1.add('')
        tree1.add(['a file'], ['file-id'], ['file'])
        tree1.put_file_bytes_non_atomic('file-id', 'file-content')
        revid1 = tree1.commit('foo')
        tree1.unlock()
        branch2 = tree1.branch.bzrdir.clone('tree2').open_branch()
        tree2 = MemoryTree.create_on_branch(branch2)
        tree2.lock_write()
        tree2.put_file_bytes_non_atomic('file-id', 'new file-content')
        revid2 = tree2.commit('foo')
        root_id = tree2.inventory.root.file_id
        state.set_path_id('', root_id)
        tree2.unlock()
        state.set_parent_trees(
            ((revid1, tree1.branch.repository.revision_tree(revid1)),
             (revid2, tree2.branch.repository.revision_tree(revid2)),
             ), [])
        # check the layout in memory
        expected_result = [revid1.encode('utf8'), revid2.encode('utf8')], [
            (('', '', root_id), [
             ('directory', '', 0, False, DirState.NULLSTAT),
             ('directory', '', 0, False, revid1.encode('utf8')),
             ('directory', '', 0, False, revid2.encode('utf8'))]),
            (('', 'a file', 'file-id'), [
             ('absent', '', 0, False, ''),
             ('file', '2439573625385400f2a669657a7db6ae7515d371', 12, False, revid1.encode('utf8')),
             ('file', '542e57dc1cda4af37cb8e55ec07ce60364bb3c7d', 16, False, revid2.encode('utf8'))])
            ]
        self.check_state_with_reopen(expected_result, state)

    ### add a path via _set_data - so we dont need delta work, just
    # raw data in, and ensure that it comes out via get_lines happily.

    def test_add_path_to_root_no_parents_all_data(self):
        # The most trivial addition of a path is when there are no parents and
        # its in the root and all data about the file is supplied
        state = dirstate.DirState.initialize('dirstate')
        self.build_tree(['a file'])
        stat = os.lstat('a file')
        # the 1*20 is the sha1 pretend value.
        state.add('a file', 'a file id', 'file', stat, '1'*20)
        # having added it, it should be in the output of iter_entries.
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
             ]),
            (('', 'a file', 'a file id'), [
             ('file', '1'*20, 19, False, dirstate.pack_stat(stat)), # current tree details
             ]),
            ]
        self.assertEqual(expected_entries, list(state._iter_entries()))
        # saving and reloading should not affect this.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_path_to_unversioned_directory(self):
        """Adding a path to an unversioned directory should error.
        
        This is a duplicate of TestWorkingTree.test_add_in_unversioned, 
        once dirstate is stable and if it is merged with WorkingTree3, consider
        removing this copy of the test.
        """
        state = dirstate.DirState.initialize('dirstate')
        self.build_tree(['unversioned/', 'unversioned/a file'])
        self.assertRaises(errors.NotVersionedError, state.add,
            'unversioned/a file', 'a file id', 'file', None, None)
        
    def test_add_directory_to_root_no_parents_all_data(self):
        # The most trivial addition of a dir is when there are no parents and
        # its in the root and all data about the file is supplied
        state = dirstate.DirState.initialize('dirstate')
        self.build_tree(['a dir/'])
        stat = os.lstat('a dir')
        state.add('a dir', 'a dir id', 'directory', stat, None)
        # having added it, it should be in the output of iter_entries.
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
             ]),
            (('', 'a dir', 'a dir id'), [
             ('directory', '', 0, False, dirstate.pack_stat(stat)), # current tree details
             ]),
            ]
        self.assertEqual(expected_entries, list(state._iter_entries()))
        # saving and reloading should not affect this.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_symlink_to_root_no_parents_all_data(self):
        # The most trivial addition of a symlink when there are no parents and
        # its in the root and all data about the file is supplied
        state = dirstate.DirState.initialize('dirstate')
        ## TODO: windows: dont fail this test. Also, how are symlinks meant to
        # be represented on windows.
        os.symlink('target', 'a link')
        stat = os.lstat('a link')
        state.add('a link', 'a link id', 'symlink', stat, 'target')
        # having added it, it should be in the output of iter_entries.
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
             ]),
            (('', 'a link', 'a link id'), [
             ('symlink', 'target', 6, False, dirstate.pack_stat(stat)), # current tree details
             ]),
            ]
        self.assertEqual(expected_entries, list(state._iter_entries()))
        # saving and reloading should not affect this.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_directory_and_child_no_parents_all_data(self):
        # after adding a directory, we should be able to add children to it.
        state = dirstate.DirState.initialize('dirstate')
        self.build_tree(['a dir/', 'a dir/a file'])
        stat = os.lstat('a dir')
        state.add('a dir', 'a dir id', 'directory', stat, None)
        filestat = os.lstat('a dir/a file')
        state.add('a dir/a file', 'a file id', 'file', filestat, '1'*20)
        # having added it, it should be in the output of iter_entries.
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('directory', '', 0, False, dirstate.DirState.NULLSTAT), # current tree details
             ]),
            (('', 'a dir', 'a dir id'), [
             ('directory', '', 0, False, dirstate.pack_stat(stat)), # current tree details
             ]),
            (('a dir', 'a file', 'a file id'), [
             ('file', '1'*20, 25, False, dirstate.pack_stat(filestat)), # current tree details
             ]),
            ]
        self.assertEqual(expected_entries, list(state._iter_entries()))
        # saving and reloading should not affect this.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_entries, list(state._iter_entries()))


class TestGetLines(TestCaseWithDirState):

    def test_get_line_with_2_rows(self):
        state = self.create_dirstate_with_root_and_subdir()
        self.assertEqual(['#bazaar dirstate flat format 2\n',
            'adler32: -1327947603\n',
            'num_entries: 2\n',
            '0\x00\n\x00'
            '0\x00\n\x00'
            '\x00\x00a-root-value\x00'
            'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\n\x00'
            '\x00subdir\x00subdir-id\x00'
            'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\n\x00'],
            state.get_lines())

    def test_entry_to_line(self):
        state = self.create_dirstate_with_root()
        self.assertEqual(
            '\x00\x00a-root-value\x00d\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk',
            state._entry_to_line(state._dirblocks[0][1][0]))

    def test_entry_to_line_with_parent(self):
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry = ('', '', 'a-root-value'), [
            ('directory', '', 0, False, packed_stat), # current tree details
            ('absent', 'dirname/basename', 0, False, ''), # first: a pointer to the current location
            ]
        self.assertEqual(
            '\x00\x00a-root-value\x00'
            'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00'
            'a\x00dirname/basename\x000\x00n\x00',
            state._entry_to_line(root_entry))

    def test_entry_to_line_with_two_parents_at_different_paths(self):
        # / in the tree, at / in one parent and /dirname/basename in the other.
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry = ('', '', 'a-root-value'), [
            ('directory', '', 0, False, packed_stat), # current tree details
            ('directory', '', 0, False, 'rev_id'), # first parent details
            ('absent', 'dirname/basename', 0, False, ''), # second: a pointer to the current location
            ]
        self.assertEqual(
            '\x00\x00a-root-value\x00'
            'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00'
            'd\x00\x000\x00n\x00rev_id\x00'
            'a\x00dirname/basename\x000\x00n\x00',
            state._entry_to_line(root_entry))

    def test_iter_entries(self):
        # we should be able to iterate the dirstate entries from end to end
        # this is for get_lines to be easy to read.
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        dirblocks = []
        root_entries = [(('', '', 'a-root-value'), [
            ('directory', '', 0, False, packed_stat), # current tree details
            ])]
        dirblocks.append(('', root_entries))
        # add two files in the root
        subdir_entry = ('', 'subdir', 'subdir-id'), [
            ('directory', '', 0, False, packed_stat), # current tree details
            ]
        afile_entry = ('', 'afile', 'afile-id'), [
            ('file', 'sha1value', 34, False, packed_stat), # current tree details
            ]
        dirblocks.append(('', [subdir_entry, afile_entry]))
        # and one in subdir
        file_entry2 = ('subdir', '2file', '2file-id'), [
            ('file', 'sha1value', 23, False, packed_stat), # current tree details
            ]
        dirblocks.append(('subdir', [file_entry2]))
        state._set_data([], dirblocks)
        expected_entries = [root_entries[0], subdir_entry, afile_entry, file_entry2]
        self.assertEqual(expected_entries, list(state._iter_entries()))


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
        self.assertBlockRowIndexEqual(1, 0, True, True, state, '', 'subdir', 0)
        self.assertBlockRowIndexEqual(1, 0, True, False, state, '', 'bdir', 0)
        self.assertBlockRowIndexEqual(1, 1, True, False, state, '', 'zdir', 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, 'a', 'foo', 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, 'subdir', 'foo', 0)

    def test_complex_structure_exists(self):
        state = self.create_complex_dirstate()
        # Make sure we can find everything that exists
        self.assertBlockRowIndexEqual(0, 0, True, True, state, '', '', 0)
        self.assertBlockRowIndexEqual(1, 0, True, True, state, '', 'a', 0)
        self.assertBlockRowIndexEqual(1, 1, True, True, state, '', 'b', 0)
        self.assertBlockRowIndexEqual(1, 2, True, True, state, '', 'c', 0)
        self.assertBlockRowIndexEqual(1, 3, True, True, state, '', 'd', 0)
        self.assertBlockRowIndexEqual(2, 0, True, True, state, 'a', 'e', 0)
        self.assertBlockRowIndexEqual(2, 1, True, True, state, 'a', 'f', 0)
        self.assertBlockRowIndexEqual(3, 0, True, True, state, 'b', 'g', 0)
        self.assertBlockRowIndexEqual(3, 1, True, True, state, 'b', 'h\xc3\xa5', 0)

    def test_complex_structure_missing(self):
        state = self.create_complex_dirstate()
        # Make sure things would be inserted in the right locations
        # '_' comes before 'a'
        self.assertBlockRowIndexEqual(0, 0, True, True, state, '', '', 0)
        self.assertBlockRowIndexEqual(1, 0, True, False, state, '', '_', 0)
        self.assertBlockRowIndexEqual(1, 1, True, False, state, '', 'aa', 0)
        self.assertBlockRowIndexEqual(1, 4, True, False, state, '', 'h\xc3\xa5', 0)
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
        self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
        self.assertEntryEqual('', 'subdir', 'subdir-id', state, 'subdir', 0)
        self.assertEntryEqual(None, None, None, state, 'missing', 0)
        self.assertEntryEqual(None, None, None, state, 'missing/foo', 0)
        self.assertEntryEqual(None, None, None, state, 'subdir/foo', 0)

    def test_complex_structure_exists(self):
        state = self.create_complex_dirstate()
        self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
        self.assertEntryEqual('', 'a', 'a-dir', state, 'a', 0)
        self.assertEntryEqual('', 'b', 'b-dir', state, 'b', 0)
        self.assertEntryEqual('', 'c', 'c-file', state, 'c', 0)
        self.assertEntryEqual('', 'd', 'd-file', state, 'd', 0)
        self.assertEntryEqual('a', 'e', 'e-dir', state, 'a/e', 0)
        self.assertEntryEqual('a', 'f', 'f-file', state, 'a/f', 0)
        self.assertEntryEqual('b', 'g', 'g-file', state, 'b/g', 0)
        self.assertEntryEqual('b', 'h\xc3\xa5', 'h-\xc3\xa5-file', state, 'b/h\xc3\xa5', 0)

    def test_complex_structure_missing(self):
        state = self.create_complex_dirstate()
        self.assertEntryEqual(None, None, None, state, '_', 0)
        self.assertEntryEqual(None, None, None, state, '_\xc3\xa5', 0)
        self.assertEntryEqual(None, None, None, state, 'a/b', 0)
        self.assertEntryEqual(None, None, None, state, 'c/d', 0)

    def test_get_entry_uninitialized(self):
        """Calling get_entry will load data if it needs to"""
        state = self.create_dirstate_with_root()
        state.save()
        del state
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(dirstate.DirState.NOT_IN_MEMORY, state._header_state)
        self.assertEqual(dirstate.DirState.NOT_IN_MEMORY, state._dirblock_state)
        self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
