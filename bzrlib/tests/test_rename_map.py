# Copyright (C) 2009 Canonical Ltd
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


import os

from bzrlib.rename_map import RenameMap
from bzrlib.tests import TestCaseWithTransport


def myhash(val):
    """This the hash used by RenameMap."""
    return hash(val) % (1024 * 1024 * 10)


class TestRenameMap(TestCaseWithTransport):

    a_lines = 'a\nb\nc\n'.splitlines(True)
    b_lines = 'b\nc\nd\n'.splitlines(True)


    def test_add_edge_hashes(self):
        rn = RenameMap()
        rn.add_edge_hashes(self.a_lines, 'a')
        self.assertEqual(set(['a']), rn.edge_hashes[myhash(('a\n', 'b\n'))])
        self.assertEqual(set(['a']), rn.edge_hashes[myhash(('b\n', 'c\n'))])
        self.assertIs(None, rn.edge_hashes.get(myhash(('c\n', 'd\n'))))

    def test_add_file_edge_hashes(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', ''.join(self.a_lines))])
        tree.add('a', 'a')
        rn = RenameMap()
        rn.add_file_edge_hashes(tree, ['a'])
        self.assertEqual(set(['a']), rn.edge_hashes[myhash(('a\n', 'b\n'))])
        self.assertEqual(set(['a']), rn.edge_hashes[myhash(('b\n', 'c\n'))])
        self.assertIs(None, rn.edge_hashes.get(myhash(('c\n', 'd\n'))))

    def test_hitcounts(self):
        rn = RenameMap()
        rn.add_edge_hashes(self.a_lines, 'a')
        rn.add_edge_hashes(self.b_lines, 'b')
        self.assertEqual({'a': 2.5, 'b': 0.5}, rn.hitcounts(self.a_lines))
        self.assertEqual({'a': 1}, rn.hitcounts(self.a_lines[:-1]))
        self.assertEqual({'b': 2.5, 'a': 0.5}, rn.hitcounts(self.b_lines))

    def test_file_match(self):
        rn = RenameMap()
        rn.add_edge_hashes(self.a_lines, 'aid')
        rn.add_edge_hashes(self.b_lines, 'bid')
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', ''.join(self.a_lines))])
        self.build_tree_contents([('tree/b', ''.join(self.b_lines))])
        self.assertEqual({'a': 'aid', 'b': 'bid'},
                         rn.file_match(tree, ['a', 'b']))

    def test_file_match_no_dups(self):
        rn = RenameMap()
        rn.add_edge_hashes(self.a_lines, 'aid')
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', ''.join(self.a_lines))])
        self.build_tree_contents([('tree/b', ''.join(self.b_lines))])
        self.build_tree_contents([('tree/c', ''.join(self.b_lines))])
        self.assertEqual({'a': 'aid'},
                         rn.file_match(tree, ['a', 'b', 'c']))

    def test_match_directories(self):
        rn = RenameMap()
        tree = self.make_branch_and_tree('tree')
        required_parents = rn.get_required_parents({
            'path1': 'a',
            'path2/tr': 'b',
            'path3/path4/path5': 'c',
        }, tree)
        self.assertEqual(
            {'path2': set(['b']), 'path3/path4': set(['c']), 'path3': set()},
            required_parents)

    def test_find_directory_renames(self):
        rn = RenameMap()
        tree = self.make_branch_and_tree('tree')
        matches = {
            'path1': 'a',
            'path3/path4/path5': 'c',
        }
        required_parents = {
            'path2': set(['b']),
            'path3/path4': set(['c']),
            'path3': set([])}
        missing_parents = {
            'path2-id': set(['b']),
            'path4-id': set(['c']),
            'path3-id': set(['path4-id'])}
        matches = RenameMap().match_parents(required_parents, missing_parents)
        self.assertEqual({'path3/path4': 'path4-id', 'path2': 'path2-id'},
                         matches)

    def test_guess_renames(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/file'])
        tree.add('file', 'file-id')
        tree.commit('Added file')
        os.rename('tree/file', 'tree/file2')
        RenameMap.guess_renames(tree)
        self.assertEqual('file2', tree.id2path('file-id'))

    def test_guess_renames_handles_directories(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/dir/', 'tree/dir/file'])
        tree.add(['dir', 'dir/file'], ['dir-id', 'file-id'])
        tree.commit('Added file')
        os.rename('tree/dir', 'tree/dir2')
        RenameMap.guess_renames(tree)
        self.assertEqual('dir2/file', tree.id2path('file-id'))
        self.assertEqual('dir2', tree.id2path('dir-id'))
