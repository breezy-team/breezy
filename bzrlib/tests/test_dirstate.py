# Copyright (C) 2006 by Canonical Ltd
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

class TestTreeToDirstate(TestCaseWithTransport):

    def test_empty_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        def check_state():
            # an inner function because there is no parameterisation at this point
            # if we make it reusable that would be a good thing.
            self.assertEqual([],  state.get_parent_ids())
            # there should be no ghosts in this tree.
            self.assertEqual([], state.get_ghosts())
            # there should be one fileid in this tree - the root of the tree.
            root_stat_pack = dirstate.pack_stat(os.stat(tree.basedir))
            self.assertEqual(
                [(('', '', 'directory', tree.inventory.root.file_id, 0, root_stat_pack, ''), [])],
                list(state._iter_rows()))
        check_state()
        state = dirstate.DirState.on_file('dirstate')
        check_state()

    def test_1_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        # we now have parent revisions, and all the files in the tree were
        # last modified in the parent.
        expected_lines_re = (
            '#bazaar dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 1\n'
            '1\x00.*\x00\n\x00'
            '0\x00\n\x00'
            '\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00%s\x00d\x00\x00\x00\x00n\x00\x00\n'
            '\x00$') % rev_id.encode('utf8')
        self.assertContainsRe(''.join(lines), expected_lines_re)

    def test_2_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        rev_id2 = tree2.commit('second post', allow_pointless=True)
        tree.merge_from_branch(tree2.branch)
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        # we now have parent revisions, and all the files in the tree were
        # last modified in the parent.
        expected_lines_re = (
            '#bazaar dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 1\n'
            '2\x00.*\x00.*\x00\n\x00'
            '0\x00\n\x00'
            '\x00\x00d\x00TREE_ROOT\x000\x00[0-9a-zA-Z+/]{32}\x00\x00%s\x00d\x00\x00\x00\x00n\x00\x00%s\x00d\x00\x00\x00\x00n\x00\x00\n'
            '\x00$') % (rev_id.encode('utf8'), rev_id2.encode('utf8'))
        self.assertContainsRe(''.join(lines), expected_lines_re)
        
    def test_empty_unknowns_are_ignored_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unknown'])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        expected_lines_re = (
            '#bazaar dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 1\n'
            '0\x00\n\x00'
            '0\x00\n\x00'
            '\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00\n'
            '\x00$')
        self.assertContainsRe(''.join(lines), expected_lines_re)
        
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
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        expected_lines_re = (
            '#bazaar dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 2\n'
            '0\x00\n\x00'
            '0\x00\n\x00'
            '\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00\n'
            '\x00\x00a file\x00f\x00a file id\x0024\x00[0-9a-zA-Z+/]{32}\x00c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8\x00'
            '\n\x00$')
        self.assertContainsRe(''.join(lines), expected_lines_re)

    def test_1_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit('first post')
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([('tree/a file', 'new content\n')])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        # we now have parent revisions, and all the files in the tree were
        # last modified in the parent.
        expected_lines_re = (
            '#bazaar dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 2\n'
            '1\x00.*\x00\n\x00'
            '0\x00\n\x00'
            '\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00%s\x00d\x00\x00\x00\x00n\x00\x00\n'
            '\x00\x00a file\x00f\x00a file id\x0012\x00[0-9a-zA-Z+/]{32}\x008b787bd9293c8b962c7a637a9fdbf627fe68610e\x00%s\x00f\x00\x00a file\x0024\x00n\x00c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8\x00\n'
            '\x00$')  % (rev_id.encode('utf8'), rev_id.encode('utf8'))
        self.assertContainsRe(''.join(lines), expected_lines_re)

    def test_2_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([('tree2/a file', 'merge content\n')])
        rev_id2 = tree2.commit('second post')
        tree.merge_from_branch(tree2.branch)
        # change the current content to be different this will alter stat, sha
        # and length again, giving us three distinct values:
        self.build_tree_contents([('tree/a file', 'new content\n')])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        # we now have parent revisions, and all the files in the tree were
        # last modified in the parent.
        expected_lines_re = (
            '#bazaar dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 2\n'
            '2\x00.*\x00.*\x00\n\x00'
            '0\x00\n\x00'
            '\x00\x00d\x00TREE_ROOT\x000\x00[0-9a-zA-Z+/]{32}\x00\x00%s\x00d\x00\x00\x00\x00n\x00\x00%s\x00d\x00\x00\x00\x00n\x00\x00\n\x00'
            '\x00a file\x00f\x00a file id\x0012\x00[0-9a-zA-Z+/]{32}\x008b787bd9293c8b962c7a637a9fdbf627fe68610e\x00%s\x00f\x00\x00a file\x0024\x00n\x00c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8\x00%s\x00f\x00\x00a file\x0014\x00n\x00314d796174c9412647c3ce07dfb5d36a94e72958\x00\n\x00$'
            % (rev_id.encode('utf8'), rev_id2.encode('utf8'),
               rev_id.encode('utf8'), rev_id2.encode('utf8')))
        self.assertContainsRe(''.join(lines), expected_lines_re)


class TestDirStateOnFile(TestCaseWithTransport):

    def test_construct_with_path(self):
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        self.build_tree_contents([('dirstate', ''.join(lines))])
        # get a state object
        state = dirstate.DirState.on_file('dirstate')
        # ask it for a parents list
        self.assertEqual([], state.get_parent_ids())
        # doing a save should work here as there have been no changes.
        state.save()


class TestDirStateInitialize(TestCaseWithTransport):

    def test_initialize(self):
        state = dirstate.DirState.initialize('dirstate')
        self.assertIsInstance(state, dirstate.DirState)
        self.assertFileEqual(
            '#bazaar dirstate flat format 1\n'
            'adler32: -455929114\n'
            'num_entries: 1\n'
            '0\x00\n\x00'
            '0\x00\n\x00'
            # after the 0 parent count, there is the \x00\n\x00 line delim
            # then '' for dir, '' for basame, and then 'd' for directory.
            # then the root value, 0 size, our constant xxxx packed stat, and 
            # an empty sha value. Finally a new \x00\n\x00 delimiter
            '\x00\x00d\x00TREE_ROOT\x000\x00xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\x00\x00\n'
            '\x00',
            'dirstate')
        expected_rows = [
            (('', '', 'directory', 'TREE_ROOT', 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', ''), [])]
        self.assertEqual(expected_rows, list(state._iter_rows()))
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_rows, list(state._iter_rows()))


class TestDirstateManipulations(TestCaseWithTransport):

    def test_add_ghost_tree(self):
        state = dirstate.DirState.initialize('dirstate')
        state.add_parent_tree('a-ghost', None)
        # now the parent list should be changed:
        self.assertEqual(['a-ghost'], state.get_parent_ids())
        self.assertEqual(['a-ghost'], state.get_ghosts())
        # save the state and reopen to check its persistent
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(['a-ghost'], state.get_parent_ids())
        self.assertEqual(['a-ghost'], state.get_ghosts())

    def test_set_path_id_no_parents(self):
        """The id of a path can be changed trivally with no parents."""
        state = dirstate.DirState.initialize('dirstate')
        # check precondition to be sure the state does change appropriately.
        self.assertEqual(
            [(('', '', 'directory', 'TREE_ROOT', 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', ''), [])],
            list(state._iter_rows()))
        state.set_path_id('', 'foobarbaz')
        expected_rows = [
            (('', '', 'directory', 'foobarbaz', 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', ''), [])]
        self.assertEqual(expected_rows, list(state._iter_rows()))
        # should work across save too
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_rows, list(state._iter_rows()))

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
        list(state._iter_rows())
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
            [(('', '', 'directory', root_id, 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', ''), [
             (revid1, 'directory', '', '', 0, False, ''),
             (revid2, 'directory', '', '', 0, False, '')])],
            list(state._iter_rows()))

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
        expected_rows = [
            (('', '', 'directory', root_id, 0, DirState.NULLSTAT, ''),
             [(revid1.encode('utf8'), 'directory', '', '', 0, False, ''),
              (revid2.encode('utf8'), 'directory', '', '', 0, False, '')]),
            (('/', 'RECYCLED.BIN', 'file', 'file-id', 0, DirState.NULLSTAT, ''),
             [(revid1.encode('utf8'), 'file', '', 'a file', 12, False, '2439573625385400f2a669657a7db6ae7515d371'),
              (revid2.encode('utf8'), 'file', '', 'a file', 16, False, '542e57dc1cda4af37cb8e55ec07ce60364bb3c7d')])
            ]
        self.assertEqual(expected_rows, list(state._iter_rows()))
        # check we can reopen and use the dirstate after setting parent trees.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_rows, list(state._iter_rows()))

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
        # having added it, it should be in the output of iter_rows.
        expected_rows = [
            (('', '', 'directory', 'TREE_ROOT', 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', ''), []),
            (('', 'a file', 'file', 'a file id', 19, dirstate.pack_stat(stat), '1'*20), []),
            ]
        self.assertEqual(expected_rows, list(state._iter_rows()))
        # saving and reloading should not affect this.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_rows, list(state._iter_rows()))

    def test_add_path_to_unversioned_directory(self):
        """Adding a path to an unversioned directory should error."""
        state = dirstate.DirState.initialize('dirstate')
        self.build_tree(['unversioned/', 'unversioned/a file'])
        self.assertRaises(errors.NoSuchFile, state.add, 'unversioned/a file',
            'a file id', 'file', None, None)
        
    def test_add_directory_to_root_no_parents_all_data(self):
        # The most trivial addition of a dir is when there are no parents and
        # its in the root and all data about the file is supplied
        state = dirstate.DirState.initialize('dirstate')
        self.build_tree(['a dir/'])
        stat = os.lstat('a dir')
        state.add('a dir', 'a dir id', 'directory', stat, None)
        # having added it, it should be in the output of iter_rows.
        expected_rows = [
            (('', '', 'directory', 'TREE_ROOT', 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', ''), []),
            (('', 'a dir', 'directory', 'a dir id', 0, dirstate.pack_stat(stat), ''), []),
            ]
        self.assertEqual(expected_rows, list(state._iter_rows()))
        # saving and reloading should not affect this.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_rows, list(state._iter_rows()))

    def test_add_symlink_to_root_no_parents_all_data(self):
        # The most trivial addition of a symlink when there are no parents and
        # its in the root and all data about the file is supplied
        state = dirstate.DirState.initialize('dirstate')
        ## TODO: windows: dont fail this test. Also, how are symlinks meant to
        # be represented on windows.
        os.symlink('target', 'a link')
        stat = os.lstat('a link')
        state.add('a link', 'a link id', 'symlink', stat, 'target')
        # having added it, it should be in the output of iter_rows.
        expected_rows = [
            (('', '', 'directory', 'TREE_ROOT', 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', ''), []),
            (('', 'a link', 'symlink', 'a link id', 6, dirstate.pack_stat(stat), 'target'), []),
            ]
        self.assertEqual(expected_rows, list(state._iter_rows()))
        # saving and reloading should not affect this.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_rows, list(state._iter_rows()))

    def test_add_directory_and_child_no_parents_all_data(self):
        # after adding a directory, we should be able to add children to it.
        state = dirstate.DirState.initialize('dirstate')
        self.build_tree(['a dir/', 'a dir/a file'])
        stat = os.lstat('a dir')
        state.add('a dir', 'a dir id', 'directory', stat, None)
        filestat = os.lstat('a dir/a file')
        state.add('a dir/a file', 'a file id', 'file', filestat, '1'*20)
        # having added it, it should be in the output of iter_rows.
        expected_rows = [
            (('', '', 'directory', 'TREE_ROOT', 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', ''), []),
            (('', 'a dir', 'directory', 'a dir id', 0, dirstate.pack_stat(stat), ''), []),
            (('a dir', 'a file', 'file', 'a file id', 25, dirstate.pack_stat(filestat), '1'*20), []),
            ]
        self.assertEqual(expected_rows, list(state._iter_rows()))
        # saving and reloading should not affect this.
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(expected_rows, list(state._iter_rows()))


class TestGetLines(TestCaseWithTransport):

    def test_adding_ghost_tree_sets_ghosts_line(self):
        state = dirstate.DirState.initialize('dirstate')
        state.add_parent_tree('a-ghost', None)
        self.assertEqual(['#bazaar dirstate flat format 1\n',
            'adler32: 1202264142\n',
            'num_entries: 1\n',
            '1\x00a-ghost\x00\n\x00'
            '1\x00a-ghost\x00\n\x00'
            '\x00\x00d\x00TREE_ROOT\x000\x00'
            'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\x00\x00\n\x00'],
            state.get_lines())

    def test_adding_tree_changes_lines(self):
        state = dirstate.DirState.initialize('dirstate')
        lines = list(state.get_lines())
        state.add_parent_tree('a-ghost', None)
        self.assertNotEqual(lines, state.get_lines())

    def test_get_line_with_2_rows(self):
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_row_direntry = ('', '', 'directory', 'a-root-value', 0, packed_stat, '')
        root_row = (root_row_direntry, [])
        dirblocks = []
        # add a file in the root
        subdir_row = (['', 'subdir', 'directory', 'subdir-id', 0, packed_stat, ''], [])
        dirblocks.append(('', [subdir_row]))
        state._set_data([], root_row, dirblocks)
        self.assertEqual(['#bazaar dirstate flat format 1\n',
            'adler32: 1283137489\n',
            'num_entries: 2\n',
            '0\x00\n\x00'
            '0\x00\n\x00'
            '\x00\x00d\x00a-root-value\x000'
            '\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\x00\n\x00\x00subdir\x00'
            'd\x00subdir-id\x000\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\x00'
            '\n\x00'],
            state.get_lines())

    def test_row_to_line(self):
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_row_direntry = ('', '', 'directory', 'a-root-value', 0, packed_stat, '')
        root_parent_direntries = []
        root_row = (root_row_direntry, root_parent_direntries)
        self.assertEqual('\x00\x00d\x00a-root-value\x000\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00', state._row_to_line(root_row))

    def test_row_to_line_with_parent(self):
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_row_direntry = ('', '', 'directory', 'a-root-value', 0, packed_stat, '')
        # one parent that was a file at path /dirname/basename
        root_parent_direntries = [('revid', 'file', 'dirname', 'basename', 0, False, '')]
        root_row = (root_row_direntry, root_parent_direntries)
        self.assertEqual(
            '\x00\x00d\x00a-root-value\x000\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00'
            '\x00revid\x00f\x00dirname\x00basename\x000\x00n\x00',
            state._row_to_line(root_row))

    def test_row_to_line_with_two_parents(self):
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_row_direntry = ('', '', 'directory', 'a-root-value', 0, packed_stat, '')
        # two parent entires: one that was a file at path /dirname/basename
        # and one that was a directory at /
        root_parent_direntries = [('revid', 'file', 'dirname', 'basename', 0, False, ''),
            ('revid2', 'directory', '', '', 0, False, '')]
        root_row = (root_row_direntry, root_parent_direntries)
        self.assertEqual(
            '\x00\x00d\x00a-root-value\x000\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00'
            '\x00revid\x00f\x00dirname\x00basename\x000\x00n\x00'
            '\x00revid2\x00d\x00\x00\x000\x00n\x00',
            state._row_to_line(root_row))

    def test_iter_rows(self):
        # we should be able to iterate the dirstate rows from end to end
        # this is for get_lines to be easy to read.
        state = dirstate.DirState.initialize('dirstate')
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_row_direntry = ('', '', 'directory', 'a-root-value', 0, packed_stat, '')
        root_row = (root_row_direntry, [])
        dirblocks = []
        # add two files in the root
        subdir_row = (['', 'subdir', 'directory', 'subdir-id', 0, packed_stat, ''], [])
        afile_row = (['', 'afile', 'file', 'afile-id', 34, packed_stat, 'sha1value'], [])
        dirblocks.append(('', [subdir_row, afile_row]))
        # and one in subdir
        file_row2 = (['', '2file', 'file', '2file-id', 23, packed_stat, 'sha1value'], [])
        dirblocks.append(('subdir', [file_row2]))
        state._set_data([], root_row, dirblocks)
        expected_rows = [root_row, subdir_row, afile_row, file_row2]
        self.assertEqual(expected_rows, list(state._iter_rows()))
