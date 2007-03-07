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

"""Tests for the test trees used by the tree_implementations tests."""

from bzrlib.tests.tree_implementations import TestCaseWithTree


class TestTreeShapes(TestCaseWithTree):

    def test_empty_tree_no_parents(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_no_parents_no_content(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        self.assertEqual(['empty-root-id'], list(iter(tree)))
        self.assertEqual(
            [('', 'empty-root-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])

    def test_abc_tree_no_parents(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_no_parents_abc_content(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set(['root-id', 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', 'root-id'), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))

    def test_abc_tree_content_2_no_parents(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_no_parents_abc_content_2(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set(['root-id', 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', 'root-id'), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('foobar\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))

    def test_abc_tree_content_3_no_parents(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_no_parents_abc_content_3(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set(['root-id', 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', 'root-id'), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertTrue(tree.is_executable('c-id'))

    def test_abc_tree_content_4_no_parents(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_no_parents_abc_content_4(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set(['root-id', 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', 'root-id'), ('b', 'b-id'), ('d', 'a-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))

    def test_abc_tree_content_5_no_parents(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_no_parents_abc_content_5(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set(['root-id', 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', 'root-id'), ('b', 'b-id'), ('d', 'a-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('bar\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))

    def test_abc_tree_content_6_no_parents(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_no_parents_abc_content_6(tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set(['root-id', 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', 'root-id'), ('a', 'a-id'), ('b', 'b-id'), ('e', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertTrue(tree.is_executable('c-id'))

    def test_tree_with_subdirs_and_all_content_types(self):
        # currently this test tree requires unicode. It might be good
        # to have it simply stop having the single unicode file in it
        # when dealing with a non-unicode filesystem.
        tree = self.get_tree_with_subdirs_and_all_content_types()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        tree_root = tree.path2id('')
        self.assertEqual(
            set([tree_root,
                '2file',
                '1top-dir',
                '1file-in-1topdir',
                '0dir-in-1topdir',
                 u'0utf\u1234file'.encode('utf8'),
                'symlink',
                 ]),
            set(iter(tree)))
        # note that the order of the paths and fileids is deliberately 
        # mismatched to ensure that the result order is path based.
        self.assertEqual(
            [('', tree_root, 'directory'),
             ('0file', '2file', 'file'),
             ('1top-dir', '1top-dir', 'directory'),
             (u'2utf\u1234file', u'0utf\u1234file'.encode('utf8'), 'file'),
             ('symlink', 'symlink', 'symlink'),
             ('1top-dir/0file-in-1topdir', '1file-in-1topdir', 'file'),
             ('1top-dir/1dir-in-1topdir', '0dir-in-1topdir', 'directory')],
            [(path, node.file_id, node.kind) for path, node in tree.iter_entries_by_dir()])

    def test_tree_with_utf8(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_with_utf8(tree)

        revision_id = u'r\xe9v-1'.encode('utf8')
        root_id = 'TREE_ROOT'
        bar_id = u'b\xe5r-id'.encode('utf8')
        foo_id = u'f\xf6-id'.encode('utf8')
        baz_id = u'b\xe1z-id'.encode('utf8')
        path_and_ids = [(u'', root_id, None),
                        (u'b\xe5r', bar_id, root_id),
                        (u'f\xf6', foo_id, root_id),
                        (u'b\xe5r/b\xe1z', baz_id, bar_id),
                       ]
        tree.lock_read()
        try:
            path_entries = list(tree.iter_entries_by_dir())
        finally:
            tree.unlock()

        for expected, (path, ie) in zip(path_and_ids, path_entries):
            self.assertEqual(expected[0], path) # Paths should match
            self.assertIsInstance(path, unicode)
            self.assertEqual(expected[1], ie.file_id)
            self.assertIsInstance(ie.file_id, str)
            self.assertEqual(expected[2], ie.parent_id)
            if expected[2] is not None:
                self.assertIsInstance(ie.parent_id, str)
            # WorkingTree's return None for the last modified revision
            if ie.revision is not None:
                self.assertIsInstance(ie.revision, str)
                if expected[0] != '':
                    # Some trees will preserve the revision id of the tree root,
                    # but not all will
                    self.assertEqual(revision_id, ie.revision)
        self.assertEqual(len(path_and_ids), len(path_entries))
        get_revision_id = getattr(tree, 'get_revision_id', None)
        if get_revision_id is not None:
            self.assertIsInstance(get_revision_id(), str)
        last_revision = getattr(tree, 'last_revision', None)
        if last_revision is not None:
            self.assertIsInstance(last_revision(), str)

    def test_tree_with_merged_utf8(self):
        tree = self.make_branch_and_tree('.')
        tree = self.get_tree_with_merged_utf8(tree)

        revision_id_1 = u'r\xe9v-1'.encode('utf8')
        revision_id_2 = u'r\xe9v-2'.encode('utf8')
        root_id = 'TREE_ROOT'
        bar_id = u'b\xe5r-id'.encode('utf8')
        foo_id = u'f\xf6-id'.encode('utf8')
        baz_id = u'b\xe1z-id'.encode('utf8')
        zez_id = u'z\xf7z-id'.encode('utf8')
        path_and_ids = [(u'', root_id, None, None),
                        (u'b\xe5r', bar_id, root_id, revision_id_1),
                        (u'f\xf6', foo_id, root_id, revision_id_1),
                        (u'b\xe5r/b\xe1z', baz_id, bar_id, revision_id_1),
                        (u'b\xe5r/z\xf7z', zez_id, bar_id, revision_id_2),
                       ]
        tree.lock_read()
        try:
            path_entries = list(tree.iter_entries_by_dir())
        finally:
            tree.unlock()

        for expected, (path, ie) in zip(path_and_ids, path_entries):
            self.assertEqual(expected[0], path) # Paths should match
            self.assertIsInstance(path, unicode)
            self.assertEqual(expected[1], ie.file_id)
            self.assertIsInstance(ie.file_id, str)
            self.assertEqual(expected[2], ie.parent_id)
            if expected[2] is not None:
                self.assertIsInstance(ie.parent_id, str)
            # WorkingTree's return None for the last modified revision
            if ie.revision is not None:
                self.assertIsInstance(ie.revision, str)
                if expected[0] == '':
                    # Some trees will preserve the revision id of the tree root,
                    # but not all will
                    continue
                self.assertEqual(expected[3], ie.revision)
        self.assertEqual(len(path_and_ids), len(path_entries))
        get_revision_id = getattr(tree, 'get_revision_id', None)
        if get_revision_id is not None:
            self.assertIsInstance(get_revision_id(), str)
        last_revision = getattr(tree, 'last_revision', None)
        if last_revision is not None:
            self.assertIsInstance(last_revision(), str)
