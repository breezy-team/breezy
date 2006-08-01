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
#

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
            '\x00')
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
            '\x00') # % rev_id.encode('utf8')
        self.assertContainsRe(''.join(lines), expected_lines_re)

    def test_2_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        tree2.commit('second post', allow_pointless=True)
        self.merge(tree2.branch, tree)
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
            '\x00') # % rev_id.encode('utf8')
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
            '\x00')
        self.assertContainsRe(''.join(lines), expected_lines_re)
        
    def test_non_empty_no_parents_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a file'])
        tree.add('a file', 'a file id')
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
            '\n\x00')
        self.assertContainsRe(''.join(lines), expected_lines_re)

    def test_1_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a file'])
        #tree.add('a file', 'a file id')
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
            '\x00') # % rev_id.encode('utf8')
        self.assertContainsRe(''.join(lines), expected_lines_re)

    def test_2_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        tree2.commit('second post', allow_pointless=True)
        self.merge(tree2.branch, tree)
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
            '\x00') # % rev_id.encode('utf8')
        self.assertContainsRe(''.join(lines), expected_lines_re)
