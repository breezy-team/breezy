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

from bzrlib import dirstate
from bzrlib.tests import TestCaseWithTransport


# TODO:
# test 0 parents, 1 parent, 4 parents.
# test unicode parents, non unicode parents
# test all change permutations in one and two parents.
# i.e. file in parent 1, dir in parent 2, symlink in tree.
# test that renames in the tree result in correct parent paths 
# Test get state from a file, then asking for lines.
# write a smaller state, and check the file has been truncated.
# add a entry when its in state deleted

class TestTreeToDirstate(TestCaseWithTransport):

    def test_empty_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree)
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        expected_lines_re = (
            '#bzr dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 1\n'
            '0\x00\n'
            '\x00\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00\n'
            '\x00$')
        self.assertContainsRe(''.join(lines), expected_lines_re)

    def test_1_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        state = dirstate.DirState.from_tree(tree)
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        # we now have parent revisions, and all the files in the tree were
        # last modified in the parent.
        expected_lines_re = (
            '#bzr dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 1\n'
            '1\x00.*\x00\n'
            '\x00\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00null:\x00\x00\x00\x00\x00\x00\x00\n'
            '\x00$') # % rev_id.encode('utf8')
        self.assertContainsRe(''.join(lines), expected_lines_re)

    def test_2_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        tree2.commit('second post', allow_pointless=True)
        tree.merge_from_branch(tree2.branch)
        state = dirstate.DirState.from_tree(tree)
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        # we now have parent revisions, and all the files in the tree were
        # last modified in the parent.
        expected_lines_re = (
            '#bzr dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 1\n'
            '2\x00.*\x00.*\x00\n'
            '\x00\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00null:\x00\x00\x00\x00\x00\x00\x00null:\x00\x00\x00\x00\x00\x00\x00\n'
            '\x00$') # % rev_id.encode('utf8')
        self.assertContainsRe(''.join(lines), expected_lines_re)
        
    def test_empty_unknowns_are_ignored_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unknown'])
        state = dirstate.DirState.from_tree(tree)
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        expected_lines_re = (
            '#bzr dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 1\n'
            '0\x00\n'
            '\x00\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00\n'
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
        state = dirstate.DirState.from_tree(tree)
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        expected_lines_re = (
            '#bzr dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 2\n'
            '0\x00\n'
            '\x00\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00\n'
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
        state = dirstate.DirState.from_tree(tree)
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        # we now have parent revisions, and all the files in the tree were
        # last modified in the parent.
        expected_lines_re = (
            '#bzr dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 2\n'
            '1\x00.*\x00\n'
            '\x00\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00null:\x00\x00\x00\x00\x00\x00\x00\n'
            '\x00\x00a file\x00f\x00a file id\x0012\x00[0-9a-zA-Z+/]{32}\x008b787bd9293c8b962c7a637a9fdbf627fe68610e\x00%s\x00f\x00\x00a file\x0024\x00n\x00c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8\x00\n'
            '\x00$')  % rev_id.encode('utf8')
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
        state = dirstate.DirState.from_tree(tree)
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        # we now have parent revisions, and all the files in the tree were
        # last modified in the parent.
        expected_lines_re = (
            '#bzr dirstate flat format 1\n'
            'adler32: [0-9-][0-9]*\n'
            'num_entries: 2\n'
            '2\x00.*\x00.*\x00\n'
            '\x00\x00\x00d\x00TREE_ROOT\x00[0-9]+\x00[0-9a-zA-Z+/]{32}\x00\x00null:\x00\x00\x00\x00\x00\x00\x00null:\x00\x00\x00\x00\x00\x00\x00\n'
            '\x00\x00a file\x00f\x00a file id\x0012\x00[0-9a-zA-Z+/]{32}\x008b787bd9293c8b962c7a637a9fdbf627fe68610e\x00%s\x00f\x00\x00a file\x0024\x00n\x00c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8\x00%s\x00f\x00\x00a file\x0014\x00n\x00314d796174c9412647c3ce07dfb5d36a94e72958\x00\n'
            '\x00$') % (rev_id.encode('utf8'), rev_id2.encode('utf8'))
        self.assertContainsRe(''.join(lines), expected_lines_re)


class TestDirStateOnFile(TestCaseWithTransport):

    def test_construct_with_path(self):
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree)
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        self.build_tree_contents([('dirstate', ''.join(lines))])
        # get a state object
        state = dirstate.DirState.on_file('dirstate')
        # ask it for a parents list
        self.assertEqual([], state.get_parent_ids())


class TestDirStateInitialize(TestCaseWithTransport):

    def test_initialize(self):
        state = dirstate.DirState.initialize('dirstate')
        self.assertIsInstance(state, dirstate.DirState)
        self.assertFileEqual(
            '#bzr dirstate flat format 1\n'
            'adler32: 14155835\n'
            'num_entries: 0\n'
            '0\x00\n'
            '\x00',
            'dirstate')


class TestDirstateManipulations(TestCaseWithTransport):

    def test_add_ghost_tree(self):
        state = dirstate.DirState.initialize('dirstate')
        state.add_parent_tree('a-ghost', None)
        # now the parent list should be changed:
        self.assertEqual(['a-ghost'], state.get_parent_ids())
        # save the state and reopen to check its persistent
        state.save()
        state = dirstate.DirState.on_file('dirstate')
        self.assertEqual(['a-ghost'], state.get_parent_ids())


class TestGetLines(TestCaseWithTransport):

    def test_adding_tree_changes_lines(self):
        state = dirstate.DirState.initialize('dirstate')
        lines = list(state.get_lines())
        state.add_parent_tree('a-ghost', None)
        self.assertNotEqual(lines, state.get_lines())
