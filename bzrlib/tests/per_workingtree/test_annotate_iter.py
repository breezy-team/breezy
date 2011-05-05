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

"""Tests for interface conformance of 'WorkingTree.annotate_iter'"""

from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree


class TestAnnotateIter(TestCaseWithWorkingTree):

    def make_single_rev_tree(self):
        builder = self.make_branch_builder('branch')
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        b = builder.get_branch()
        tree = b.create_checkout('tree', lightweight=True)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        return tree

    def test_annotate_same_as_parent(self):
        tree = self.make_single_rev_tree()
        annotations = tree.annotate_iter('file-id')
        self.assertEqual([('rev-1', 'initial content\n')],
                         annotations)

    def test_annotate_mod_from_parent(self):
        tree = self.make_single_rev_tree()
        self.build_tree_contents([('tree/file',
                                   'initial content\nnew content\n')])
        annotations = tree.annotate_iter('file-id')
        self.assertEqual([('rev-1', 'initial content\n'),
                          ('current:', 'new content\n'),
                         ], annotations)

    def test_annotate_merge_parents(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        builder.build_snapshot('rev-2', ['rev-1'], [
            ('modify', ('file-id', 'initial content\ncontent in 2\n')),
            ])
        builder.build_snapshot('rev-3', ['rev-1'], [
            ('modify', ('file-id', 'initial content\ncontent in 3\n')),
            ])
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id='rev-2', lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids(['rev-2', 'rev-3'])
        self.build_tree_contents([('tree/file',
                                   'initial content\ncontent in 2\n'
                                   'content in 3\nnew content\n')])
        annotations = tree.annotate_iter('file-id')
        self.assertEqual([('rev-1', 'initial content\n'),
                          ('rev-2', 'content in 2\n'),
                          ('rev-3', 'content in 3\n'),
                          ('current:', 'new content\n'),
                         ], annotations)

    def test_annotate_merge_parent_no_file(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ])
        builder.build_snapshot('rev-2', ['rev-1'], [
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        builder.build_snapshot('rev-3', ['rev-1'], [])
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id='rev-2', lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids(['rev-2', 'rev-3'])
        self.build_tree_contents([('tree/file',
                                   'initial content\nnew content\n')])
        annotations = tree.annotate_iter('file-id')
        self.assertEqual([('rev-2', 'initial content\n'),
                          ('current:', 'new content\n'),
                         ], annotations)

    def test_annotate_merge_parent_was_directory(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ])
        builder.build_snapshot('rev-2', ['rev-1'], [
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        builder.build_snapshot('rev-3', ['rev-1'], [
            ('add', ('a_dir', 'file-id', 'directory', None)),
            ])
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id='rev-2', lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids(['rev-2', 'rev-3'])
        self.build_tree_contents([('tree/file',
                                   'initial content\nnew content\n')])
        annotations = tree.annotate_iter('file-id')
        self.assertEqual([('rev-2', 'initial content\n'),
                          ('current:', 'new content\n'),
                         ], annotations)

    def test_annotate_same_as_merge_parent(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        builder.build_snapshot('rev-2', ['rev-1'], [
            ])
        builder.build_snapshot('rev-3', ['rev-1'], [
            ('modify', ('file-id', 'initial content\ncontent in 3\n')),
            ])
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id='rev-2', lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids(['rev-2', 'rev-3'])
        self.build_tree_contents([('tree/file',
                                   'initial content\ncontent in 3\n')])
        annotations = tree.annotate_iter('file-id')
        self.assertEqual([('rev-1', 'initial content\n'),
                          ('rev-3', 'content in 3\n'),
                         ], annotations)

    def test_annotate_same_as_merge_parent_supersedes(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        builder.build_snapshot('rev-2', ['rev-1'], [
            ('modify', ('file-id', 'initial content\nnew content\n')),
            ])
        builder.build_snapshot('rev-3', ['rev-2'], [
            ('modify', ('file-id', 'initial content\ncontent in 3\n')),
            ])
        builder.build_snapshot('rev-4', ['rev-3'], [
            ('modify', ('file-id', 'initial content\nnew content\n')),
            ])
        # In this case, the content locally is the same as content in basis
        # tree, but the merge revision states that *it* should win
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id='rev-2', lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids(['rev-2', 'rev-4'])
        annotations = tree.annotate_iter('file-id')
        self.assertEqual([('rev-1', 'initial content\n'),
                          ('rev-4', 'new content\n'),
                         ], annotations)

