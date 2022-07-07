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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


import os

from breezy import trace
from breezy.rename_map import RenameMap
from breezy.tests import TestCaseWithTransport


def myhash(val):
    """This the hash used by RenameMap."""
    return hash(val) % (1024 * 1024 * 10)


class TestRenameMap(TestCaseWithTransport):

    a_lines = b'a\nb\nc\n'.splitlines(True)
    b_lines = b'b\nc\nd\n'.splitlines(True)

    def test_add_edge_hashes(self):
        rn = RenameMap(None)
        rn.add_edge_hashes(self.a_lines, 'a')
        self.assertEqual({'a'}, rn.edge_hashes[myhash(('a\n', 'b\n'))])
        self.assertEqual({'a'}, rn.edge_hashes[myhash(('b\n', 'c\n'))])
        self.assertIs(None, rn.edge_hashes.get(myhash(('c\n', 'd\n'))))

    def test_add_file_edge_hashes(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', b''.join(self.a_lines))])
        tree.add('a', ids=b'a')
        rn = RenameMap(tree)
        rn.add_file_edge_hashes(tree, [b'a'])
        self.assertEqual({b'a'}, rn.edge_hashes[myhash(('a\n', 'b\n'))])
        self.assertEqual({b'a'}, rn.edge_hashes[myhash(('b\n', 'c\n'))])
        self.assertIs(None, rn.edge_hashes.get(myhash(('c\n', 'd\n'))))

    def test_hitcounts(self):
        rn = RenameMap(None)
        rn.add_edge_hashes(self.a_lines, 'a')
        rn.add_edge_hashes(self.b_lines, 'b')
        self.assertEqual({'a': 2.5, 'b': 0.5}, rn.hitcounts(self.a_lines))
        self.assertEqual({'a': 1}, rn.hitcounts(self.a_lines[:-1]))
        self.assertEqual({'b': 2.5, 'a': 0.5}, rn.hitcounts(self.b_lines))

    def test_file_match(self):
        tree = self.make_branch_and_tree('tree')
        rn = RenameMap(tree)
        rn.add_edge_hashes(self.a_lines, 'aid')
        rn.add_edge_hashes(self.b_lines, 'bid')
        self.build_tree_contents([('tree/a', b''.join(self.a_lines))])
        self.build_tree_contents([('tree/b', b''.join(self.b_lines))])
        self.assertEqual({'a': 'aid', 'b': 'bid'},
                         rn.file_match(['a', 'b']))

    def test_file_match_no_dups(self):
        tree = self.make_branch_and_tree('tree')
        rn = RenameMap(tree)
        rn.add_edge_hashes(self.a_lines, 'aid')
        self.build_tree_contents([('tree/a', b''.join(self.a_lines))])
        self.build_tree_contents([('tree/b', b''.join(self.b_lines))])
        self.build_tree_contents([('tree/c', b''.join(self.b_lines))])
        self.assertEqual({'a': 'aid'},
                         rn.file_match(['a', 'b', 'c']))

    def test_match_directories(self):
        tree = self.make_branch_and_tree('tree')
        rn = RenameMap(tree)
        required_parents = rn.get_required_parents({
            'path1': 'a',
            'path2/tr': 'b',
            'path3/path4/path5': 'c',
        })
        self.assertEqual(
            {'path2': {'b'}, 'path3/path4': {'c'}, 'path3': set()},
            required_parents)

    def test_find_directory_renames(self):
        tree = self.make_branch_and_tree('tree')
        rn = RenameMap(tree)
        matches = {
            'path1': 'a',
            'path3/path4/path5': 'c',
        }
        required_parents = {
            'path2': {'b'},
            'path3/path4': {'c'},
            'path3': set([])}
        missing_parents = {
            'path2-id': {'b'},
            'path4-id': {'c'},
            'path3-id': {'path4-id'}}
        matches = rn.match_parents(required_parents, missing_parents)
        self.assertEqual({'path3/path4': 'path4-id', 'path2': 'path2-id'},
                         matches)

    def test_guess_renames(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/file'])
        tree.add('file', ids=b'file-id')
        tree.commit('Added file')
        os.rename('tree/file', 'tree/file2')
        RenameMap.guess_renames(tree.basis_tree(), tree)
        self.assertEqual('file2', tree.id2path(b'file-id'))

    def test_guess_renames_handles_directories(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/dir/', 'tree/dir/file'])
        tree.add(['dir', 'dir/file'], ids=[b'dir-id', b'file-id'])
        tree.commit('Added file')
        os.rename('tree/dir', 'tree/dir2')
        RenameMap.guess_renames(tree.basis_tree(), tree)
        self.assertEqual('dir2/file', tree.id2path(b'file-id'))
        self.assertEqual('dir2', tree.id2path(b'dir-id'))

    def test_guess_renames_handles_grandparent_directories(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/topdir/',
                         'tree/topdir/middledir/',
                         'tree/topdir/middledir/file'])
        tree.add(['topdir', 'topdir/middledir', 'topdir/middledir/file'],
                 ids=[b'topdir-id', b'middledir-id', b'file-id'])
        tree.commit('Added files.')
        os.rename('tree/topdir', 'tree/topdir2')
        RenameMap.guess_renames(tree.basis_tree(), tree)
        self.assertEqual('topdir2', tree.id2path(b'topdir-id'))

    def test_guess_renames_preserves_children(self):
        """When a directory has been moved, its children are preserved."""
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree_contents([('tree/foo/', b''),
                                  ('tree/foo/bar', b'bar'),
                                  ('tree/foo/empty', b'')])
        tree.add(['foo', 'foo/bar', 'foo/empty'],
                 ids=[b'foo-id', b'bar-id', b'empty-id'])
        tree.commit('rev1')
        os.rename('tree/foo', 'tree/baz')
        RenameMap.guess_renames(tree.basis_tree(), tree)
        self.assertEqual('baz/empty', tree.id2path(b'empty-id'))

    def test_guess_renames_dry_run(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/file'])
        tree.add('file', ids=b'file-id')
        tree.commit('Added file')
        os.rename('tree/file', 'tree/file2')
        RenameMap.guess_renames(tree.basis_tree(), tree, dry_run=True)
        self.assertEqual('file', tree.id2path(b'file-id'))

    @staticmethod
    def captureNotes(cmd, *args, **kwargs):
        notes = []

        def my_note(fmt, *args):
            notes.append(fmt % args)
        old_note = trace.note
        trace.note = my_note
        try:
            result = cmd(*args, **kwargs)
        finally:
            trace.note = old_note
        return notes, result

    def test_guess_renames_output(self):
        """guess_renames emits output whether dry_run is True or False."""
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/file'])
        tree.add('file', ids=b'file-id')
        tree.commit('Added file')
        os.rename('tree/file', 'tree/file2')
        notes = self.captureNotes(
            RenameMap.guess_renames, tree.basis_tree(), tree,
            dry_run=True)[0]
        self.assertEqual('file => file2', ''.join(notes))
        notes = self.captureNotes(RenameMap.guess_renames, tree.basis_tree(),
                                  tree, dry_run=False)[0]
        self.assertEqual('file => file2', ''.join(notes))

    def test_guess_rename_handles_new_directories(self):
        """When a file was moved into a new directory."""
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        # self.addCleanup(tree.unlock)
        self.build_tree(['file'])
        tree.add('file', ids=b'file-id')
        tree.commit('Added file')
        os.mkdir('folder')
        os.rename('file', 'folder/file2')
        notes = self.captureNotes(
            RenameMap.guess_renames, tree.basis_tree(), tree)[0]
        self.assertEqual('file => folder/file2', ''.join(notes))

        tree.unlock()
