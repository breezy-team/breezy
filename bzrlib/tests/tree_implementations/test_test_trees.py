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

"""Tests for the test trees used by the tree_implementations tests."""

from bzrlib import inventory 
from bzrlib.tests.tree_implementations import TestCaseWithTree


class TestTreeShapes(TestCaseWithTree):

    def test_empty_tree_no_parents(self):
        tree = self.get_tree_no_parents_no_content()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        self.assertEqual([inventory.ROOT_ID], list(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID)],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])

    def test_abc_tree_no_parents(self):
        tree = self.get_tree_no_parents_abc_content()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))

    def test_abc_tree_content_2_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_2()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('foobar\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))
        
    def test_abc_tree_content_3_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_3()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertTrue(tree.is_executable('c-id'))
        
    def test_abc_tree_content_4_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_4()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('b', 'b-id'), ('d', 'a-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))
        
    def test_abc_tree_content_5_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_5()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('b', 'b-id'), ('d', 'a-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('bar\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))
        
    def test_abc_tree_content_6_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_6()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('a', 'a-id'), ('b', 'b-id'), ('e', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertTrue(tree.is_executable('c-id'))

    def test_tree_with_subdirs_and_all_content_types(self):
        # currently this test tree requires unicode. It might be good
        # to have it simply stop having the single unicode file in it
        # when dealing with a non-unicode filesystem.
        tree = self.get_tree_with_subdirs_and_all_content_types()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID,
                '2file',
                '1top-dir',
                '1file-in-1topdir',
                '0dir-in-1topdir',
                 u'0utf\u1234file',
                'symlink',
                 ]),
            set(iter(tree)))
        # note that the order of the paths and fileids is deliberately 
        # mismatched to ensure that the result order is path based.
        self.assertEqual(
            [('', inventory.ROOT_ID, 'root_directory'),
             ('0file', '2file', 'file'),
             ('1top-dir', '1top-dir', 'directory'),
             (u'2utf\u1234file', u'0utf\u1234file', 'file'),
             ('symlink', 'symlink', 'symlink'),
             ('1top-dir/0file-in-1topdir', '1file-in-1topdir', 'file'),
             ('1top-dir/1dir-in-1topdir', '0dir-in-1topdir', 'directory')],
            [(path, node.file_id, node.kind) for path, node in tree.iter_entries_by_dir()])
