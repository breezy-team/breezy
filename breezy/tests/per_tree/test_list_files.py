# Copyright (C) 2007 Canonical Ltd
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

"""Test that all trees support Tree.list_files()"""

from breezy.tests.per_tree import TestCaseWithTree
from breezy.tests import TestNotApplicable


class TestListFiles(TestCaseWithTree):

    def test_list_files_with_root(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [('', 'V', 'directory', tree.path2id('')),
                    ('a', 'V', 'file', tree.path2id('a')),
                    ('b', 'V', 'directory', tree.path2id('b')),
                    ('b/c', 'V', 'file', tree.path2id('b/c')),
                    ]
        with tree.lock_read():
            actual = [(path, status, kind, ie.file_id)
                      for path, status, kind, ie in
                      tree.list_files(include_root=True)]
        self.assertEqual(expected, actual)

    def test_list_files_no_root(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [('a', 'V', 'file', tree.path2id('a')),
                    ('b', 'V', 'directory', tree.path2id('b')),
                    ('b/c', 'V', 'file', tree.path2id('b/c')),
                    ]
        with tree.lock_read():
            actual = [(path, status, kind, ie.file_id)
                      for path, status, kind, ie in
                      tree.list_files()]
        self.assertEqual(expected, actual)

    def test_list_files_with_root_no_recurse(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [('', 'V', 'directory', tree.path2id('')),
                    ('a', 'V', 'file', tree.path2id('a')),
                    ]
        expected.append(
            ('b', 'V', 'directory', tree.path2id('b')))
        with tree.lock_read():
            actual = [(path, status, kind, ie.file_id)
                      for path, status, kind, ie in
                      tree.list_files(include_root=True, recursive=False)]
        self.assertEqual(expected, actual)

    def test_list_files_no_root_no_recurse(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [('a', 'V', 'file', tree.path2id('a'))]
        expected.append(
            ('b', 'V', 'directory', tree.path2id('b')))
        with tree.lock_read():
            actual = [(path, status, kind, ie.file_id)
                      for path, status, kind, ie in
                      tree.list_files(recursive=False)]
        self.assertEqual(expected, actual)

    def test_list_files_from_dir(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [('c', 'V', 'file', tree.path2id('b/c')),
                    ]
        with tree.lock_read():
            actual = [(path, status, kind, ie.file_id)
                      for path, status, kind, ie in
                      tree.list_files(from_dir=u'b')]
        self.assertEqual(expected, actual)

    def test_list_files_from_dir_no_recurse(self):
        # The test trees don't have much nesting so test with an explicit root
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        expected = [('a', 'V', 'file', tree.path2id('a'))]
        expected.append(
            ('b', 'V', 'directory', tree.path2id('b')))

        with tree.lock_read():
            actual = [(path, status, kind, ie.file_id)
                      for path, status, kind, ie in
                      tree.list_files(from_dir='', recursive=False)]
        self.assertEqual(expected, actual)

    def skip_if_no_reference(self, tree):
        if not getattr(tree, 'supports_tree_reference', lambda: False)():
            raise TestNotApplicable('Tree references not supported')

    def create_nested(self):
        work_tree = self.make_branch_and_tree('wt')
        with work_tree.lock_write():
            self.skip_if_no_reference(work_tree)
            subtree = self.make_branch_and_tree('wt/subtree')
            self.build_tree(['wt/subtree/a'])
            subtree.add(['a'])
            subtree.commit('foo')
            work_tree.add_reference(subtree)
        tree = self._convert_tree(work_tree)
        self.skip_if_no_reference(tree)
        return tree, subtree

    def test_list_files_with_unfollowed_reference(self):
        tree, subtree = self.create_nested()
        expected = [
            ('', 'V', 'directory', tree.path2id('')),
            ('subtree', 'V', 'tree-reference', tree.path2id('subtree'))]
        with tree.lock_read():
            actual = [(path, status, kind, ie.file_id)
                      for path, status, kind, ie in
                      tree.list_files(recursive=True, recurse_nested=False, include_root=True)]
        self.assertEqual(expected, actual)

    def test_list_files_with_followed_reference(self):
        tree, subtree = self.create_nested()
        expected = [
            ('', 'V', 'directory'),
            ('subtree', 'V', 'directory'),
            ('subtree/a', 'V', 'file'),
            ]
        with tree.lock_read():
            actual = [(path, status, kind)
                      for path, status, kind, ie in
                      tree.list_files(
                          recursive=True, recurse_nested=True,
                          include_root=True)]
        self.assertEqual(expected, actual)
