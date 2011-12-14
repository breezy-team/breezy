# Copyright (C) 2007-2011 Canonical Ltd
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

"""Tests for the BranchBuilder class."""

from bzrlib import (
    branch as _mod_branch,
    revision as _mod_revision,
    tests,
    )
from bzrlib.branchbuilder import BranchBuilder


class TestBranchBuilder(tests.TestCaseWithMemoryTransport):

    def test_create(self):
        """Test the constructor api."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        # we dont care if the branch has been built or not at this point.

    def test_get_branch(self):
        """get_branch returns the created branch."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        branch = builder.get_branch()
        self.assertIsInstance(branch, _mod_branch.Branch)
        self.assertEqual(self.get_transport().clone('foo').base,
            branch.base)
        self.assertEqual(
            (0, _mod_revision.NULL_REVISION),
            branch.last_revision_info())

    def test_format(self):
        """Making a BranchBuilder with a format option sets the branch type."""
        builder = BranchBuilder(self.get_transport(), format='dirstate-tags')
        branch = builder.get_branch()
        self.assertIsInstance(branch, _mod_branch.BzrBranch6)

    def test_build_one_commit(self):
        """doing build_commit causes a commit to happen."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id = builder.build_commit()
        branch = builder.get_branch()
        self.assertEqual((1, rev_id), branch.last_revision_info())
        self.assertEqual(
            'commit 1',
            branch.repository.get_revision(branch.last_revision()).message)

    def test_build_commit_timestamp(self):
        """You can set a date when committing."""
        builder = self.make_branch_builder('foo')
        rev_id = builder.build_commit(timestamp=1236043340)
        branch = builder.get_branch()
        self.assertEqual((1, rev_id), branch.last_revision_info())
        rev = branch.repository.get_revision(branch.last_revision())
        self.assertEqual(
            'commit 1',
            rev.message)
        self.assertEqual(
            1236043340,
            int(rev.timestamp))

    def test_build_two_commits(self):
        """The second commit has the right parents and message."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id1 = builder.build_commit()
        rev_id2 = builder.build_commit()
        branch = builder.get_branch()
        self.assertEqual((2, rev_id2), branch.last_revision_info())
        self.assertEqual(
            'commit 2',
            branch.repository.get_revision(branch.last_revision()).message)
        self.assertEqual(
            [rev_id1],
            branch.repository.get_revision(branch.last_revision()).parent_ids)

    def test_build_commit_parent_ids(self):
        """build_commit() takes a parent_ids argument."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id1 = builder.build_commit(
            parent_ids=["ghost"], allow_leftmost_as_ghost=True)
        rev_id2 = builder.build_commit(parent_ids=[])
        branch = builder.get_branch()
        self.assertEqual((1, rev_id2), branch.last_revision_info())
        self.assertEqual(
            ["ghost"],
            branch.repository.get_revision(rev_id1).parent_ids)


class TestBranchBuilderBuildSnapshot(tests.TestCaseWithMemoryTransport):

    def assertTreeShape(self, expected_shape, tree):
        """Check that the tree shape matches expectations."""
        tree.lock_read()
        try:
            entries = [(path, ie.file_id, ie.kind)
                       for path, ie in tree.iter_entries_by_dir()]
        finally:
            tree.unlock()
        self.assertEqual(expected_shape, entries)

    def build_a_rev(self):
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id1 = builder.build_snapshot('A-id', None,
            [('add', ('', 'a-root-id', 'directory', None)),
             ('add', ('a', 'a-id', 'file', 'contents'))])
        self.assertEqual('A-id', rev_id1)
        return builder

    def test_add_one_file(self):
        builder = self.build_a_rev()
        branch = builder.get_branch()
        self.assertEqual((1, 'A-id'), branch.last_revision_info())
        rev_tree = branch.repository.revision_tree('A-id')
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file')], rev_tree)
        self.assertEqual('contents', rev_tree.get_file_text('a-id'))

    def test_add_second_file(self):
        builder = self.build_a_rev()
        rev_id2 = builder.build_snapshot('B-id', None,
            [('add', ('b', 'b-id', 'file', 'content_b'))])
        self.assertEqual('B-id', rev_id2)
        branch = builder.get_branch()
        self.assertEqual((2, rev_id2), branch.last_revision_info())
        rev_tree = branch.repository.revision_tree(rev_id2)
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                              (u'b', 'b-id', 'file')], rev_tree)
        self.assertEqual('content_b', rev_tree.get_file_text('b-id'))

    def test_add_empty_dir(self):
        builder = self.build_a_rev()
        rev_id2 = builder.build_snapshot('B-id', None,
            [('add', ('b', 'b-id', 'directory', None))])
        rev_tree = builder.get_branch().repository.revision_tree('B-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                              (u'b', 'b-id', 'directory'),
                             ], rev_tree)

    def test_commit_timestamp(self):
        builder = self.make_branch_builder('foo')
        rev_id = builder.build_snapshot(None, None,
            [('add', (u'', None, 'directory', None))],
            timestamp=1234567890)
        rev = builder.get_branch().repository.get_revision(rev_id)
        self.assertEqual(
            1234567890,
            int(rev.timestamp))

    def test_commit_message_default(self):
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id = builder.build_snapshot(None, None,
            [('add', (u'', None, 'directory', None))])
        branch = builder.get_branch()
        rev = branch.repository.get_revision(rev_id)
        self.assertEqual(u'commit 1', rev.message)

    def test_commit_message_supplied(self):
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id = builder.build_snapshot(None, None,
            [('add', (u'', None, 'directory', None))],
            message=u'Foo')
        branch = builder.get_branch()
        rev = branch.repository.get_revision(rev_id)
        self.assertEqual(u'Foo', rev.message)

    def test_commit_message_callback(self):
        builder = BranchBuilder(self.get_transport().clone('foo'))
        rev_id = builder.build_snapshot(None, None,
            [('add', (u'', None, 'directory', None))],
            message_callback=lambda x:u'Foo')
        branch = builder.get_branch()
        rev = branch.repository.get_revision(rev_id)
        self.assertEqual(u'Foo', rev.message)

    def test_modify_file(self):
        builder = self.build_a_rev()
        rev_id2 = builder.build_snapshot('B-id', None,
            [('modify', ('a-id', 'new\ncontent\n'))])
        self.assertEqual('B-id', rev_id2)
        branch = builder.get_branch()
        rev_tree = branch.repository.revision_tree(rev_id2)
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertEqual('new\ncontent\n', rev_tree.get_file_text('a-id'))

    def test_delete_file(self):
        builder = self.build_a_rev()
        rev_id2 = builder.build_snapshot('B-id', None,
            [('unversion', 'a-id')])
        self.assertEqual('B-id', rev_id2)
        branch = builder.get_branch()
        rev_tree = branch.repository.revision_tree(rev_id2)
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertTreeShape([(u'', 'a-root-id', 'directory')], rev_tree)

    def test_delete_directory(self):
        builder = self.build_a_rev()
        rev_id2 = builder.build_snapshot('B-id', None,
            [('add', ('b', 'b-id', 'directory', None)),
             ('add', ('b/c', 'c-id', 'file', 'foo\n')),
             ('add', ('b/d', 'd-id', 'directory', None)),
             ('add', ('b/d/e', 'e-id', 'file', 'eff\n')),
            ])
        rev_tree = builder.get_branch().repository.revision_tree('B-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                              (u'b', 'b-id', 'directory'),
                              (u'b/c', 'c-id', 'file'),
                              (u'b/d', 'd-id', 'directory'),
                              (u'b/d/e', 'e-id', 'file')], rev_tree)
        # Removing a directory removes all child dirs
        builder.build_snapshot('C-id', None, [('unversion', 'b-id')])
        rev_tree = builder.get_branch().repository.revision_tree('C-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                             ], rev_tree)

    def test_unknown_action(self):
        builder = self.build_a_rev()
        e = self.assertRaises(ValueError,
            builder.build_snapshot, 'B-id', None, [('weirdo', ('foo',))])
        self.assertEqual('Unknown build action: "weirdo"', str(e))

    def test_rename(self):
        builder = self.build_a_rev()
        builder.build_snapshot('B-id', None,
            [('rename', ('a', 'b'))])
        rev_tree = builder.get_branch().repository.revision_tree('B-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'b', 'a-id', 'file')], rev_tree)

    def test_rename_into_subdir(self):
        builder = self.build_a_rev()
        builder.build_snapshot('B-id', None,
            [('add', ('dir', 'dir-id', 'directory', None)),
             ('rename', ('a', 'dir/a'))])
        rev_tree = builder.get_branch().repository.revision_tree('B-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'dir', 'dir-id', 'directory'),
                              (u'dir/a', 'a-id', 'file')], rev_tree)

    def test_rename_out_of_unversioned_subdir(self):
        builder = self.build_a_rev()
        builder.build_snapshot('B-id', None,
            [('add', ('dir', 'dir-id', 'directory', None)),
             ('rename', ('a', 'dir/a'))])
        builder.build_snapshot('C-id', None,
            [('rename', ('dir/a', 'a')),
             ('unversion', 'dir-id')])
        rev_tree = builder.get_branch().repository.revision_tree('C-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file')], rev_tree)

    def test_set_parent(self):
        builder = self.build_a_rev()
        builder.start_series()
        self.addCleanup(builder.finish_series)
        builder.build_snapshot('B-id', ['A-id'],
            [('modify', ('a-id', 'new\ncontent\n'))])
        builder.build_snapshot('C-id', ['A-id'],
            [('add', ('c', 'c-id', 'file', 'alt\ncontent\n'))])
        # We should now have a graph:
        #   A
        #   |\
        #   C B
        # And not A => B => C
        repo = builder.get_branch().repository
        self.assertEqual({'B-id': ('A-id',), 'C-id': ('A-id',)},
                         repo.get_parent_map(['B-id', 'C-id']))
        b_tree = repo.revision_tree('B-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                             ], b_tree)
        self.assertEqual('new\ncontent\n', b_tree.get_file_text('a-id'))

        # We should still be using the content from A in C, not from B
        c_tree = repo.revision_tree('C-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                              (u'c', 'c-id', 'file'),
                             ], c_tree)
        self.assertEqual('contents', c_tree.get_file_text('a-id'))
        self.assertEqual('alt\ncontent\n', c_tree.get_file_text('c-id'))

    def test_set_merge_parent(self):
        builder = self.build_a_rev()
        builder.start_series()
        self.addCleanup(builder.finish_series)
        builder.build_snapshot('B-id', ['A-id'],
            [('add', ('b', 'b-id', 'file', 'b\ncontent\n'))])
        builder.build_snapshot('C-id', ['A-id'],
            [('add', ('c', 'c-id', 'file', 'alt\ncontent\n'))])
        builder.build_snapshot('D-id', ['B-id', 'C-id'], [])
        repo = builder.get_branch().repository
        self.assertEqual({'B-id': ('A-id',), 'C-id': ('A-id',),
                          'D-id': ('B-id', 'C-id')},
                         repo.get_parent_map(['B-id', 'C-id', 'D-id']))
        d_tree = repo.revision_tree('D-id')
        # Note: by default a merge node does *not* pull in the changes from the
        #       merged tree, you have to supply it yourself.
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                              (u'b', 'b-id', 'file'),
                             ], d_tree)

    def test_set_merge_parent_and_contents(self):
        builder = self.build_a_rev()
        builder.start_series()
        self.addCleanup(builder.finish_series)
        builder.build_snapshot('B-id', ['A-id'],
            [('add', ('b', 'b-id', 'file', 'b\ncontent\n'))])
        builder.build_snapshot('C-id', ['A-id'],
            [('add', ('c', 'c-id', 'file', 'alt\ncontent\n'))])
        builder.build_snapshot('D-id', ['B-id', 'C-id'],
            [('add', ('c', 'c-id', 'file', 'alt\ncontent\n'))])
        repo = builder.get_branch().repository
        self.assertEqual({'B-id': ('A-id',), 'C-id': ('A-id',),
                          'D-id': ('B-id', 'C-id')},
                         repo.get_parent_map(['B-id', 'C-id', 'D-id']))
        d_tree = repo.revision_tree('D-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                              (u'b', 'b-id', 'file'),
                              (u'c', 'c-id', 'file'),
                             ], d_tree)
        # Because we copied the exact text into *this* tree, the 'c' file
        # should look like it was not modified in the merge
        self.assertEqual('C-id', d_tree.get_file_revision('c-id'))

    def test_set_parent_to_null(self):
        builder = self.build_a_rev()
        builder.start_series()
        self.addCleanup(builder.finish_series)
        builder.build_snapshot('B-id', [],
            [('add', ('', None, 'directory', None))])
        # We should now have a graph:
        #   A B
        # And not A => B
        repo = builder.get_branch().repository
        self.assertEqual({'A-id': (_mod_revision.NULL_REVISION,),
                          'B-id': (_mod_revision.NULL_REVISION,),},
                         repo.get_parent_map(['A-id', 'B-id']))

    
    def test_start_finish_series(self):
        builder = BranchBuilder(self.get_transport().clone('foo'))
        builder.start_series()
        try:
            self.assertIsNot(None, builder._tree)
            self.assertEqual('w', builder._tree._lock_mode)
            self.assertTrue(builder._branch.is_locked())
        finally:
            builder.finish_series()
        self.assertIs(None, builder._tree)
        self.assertFalse(builder._branch.is_locked())

    def test_ghost_mainline_history(self):
        builder = BranchBuilder(self.get_transport().clone('foo'))
        builder.start_series()
        try:
            builder.build_snapshot('tip', ['ghost'],
                [('add', ('', 'ROOT_ID', 'directory', ''))],
                allow_leftmost_as_ghost=True)
        finally:
            builder.finish_series()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        self.assertEqual(('ghost',),
            b.repository.get_graph().get_parent_map(['tip'])['tip'])

    def test_unversion_root_add_new_root(self):
        builder = BranchBuilder(self.get_transport().clone('foo'))
        builder.start_series()
        builder.build_snapshot('rev-1', None,
            [('add', ('', 'TREE_ROOT', 'directory', ''))])
        builder.build_snapshot('rev-2', None,
            [('unversion', 'TREE_ROOT'),
             ('add', ('', 'my-root', 'directory', ''))])
        builder.finish_series()
        rev_tree = builder.get_branch().repository.revision_tree('rev-2')
        self.assertTreeShape([(u'', 'my-root', 'directory')], rev_tree)

    def test_empty_flush(self):
        """A flush with no actions before it is a no-op."""
        builder = BranchBuilder(self.get_transport().clone('foo'))
        builder.start_series()
        builder.build_snapshot('rev-1', None,
            [('add', ('', 'TREE_ROOT', 'directory', ''))])
        builder.build_snapshot('rev-2', None, [('flush', None)])
        builder.finish_series()
        rev_tree = builder.get_branch().repository.revision_tree('rev-2')
        self.assertTreeShape([(u'', 'TREE_ROOT', 'directory')], rev_tree)

    def test_kind_change(self):
        """It's possible to change the kind of an entry in a single snapshot
        with a bit of help from the 'flush' action.
        """
        builder = BranchBuilder(self.get_transport().clone('foo'))
        builder.start_series()
        builder.build_snapshot('A-id', None,
            [('add', (u'', 'a-root-id', 'directory', None)),
             ('add', (u'a', 'a-id', 'file', 'content\n'))])
        builder.build_snapshot('B-id', None,
            [('unversion', 'a-id'),
             ('flush', None),
             ('add', (u'a', 'a-id', 'directory', None))])
        builder.finish_series()
        rev_tree = builder.get_branch().repository.revision_tree('B-id')
        self.assertTreeShape(
            [(u'', 'a-root-id', 'directory'), (u'a', 'a-id', 'directory')],
            rev_tree)

    def test_pivot_root(self):
        """It's possible (albeit awkward) to move an existing dir to the root
        in a single snapshot by using unversion then flush then add.
        """
        builder = BranchBuilder(self.get_transport().clone('foo'))
        builder.start_series()
        builder.build_snapshot('A-id', None,
            [('add', (u'', 'orig-root', 'directory', None)),
             ('add', (u'dir', 'dir-id', 'directory', None))])
        builder.build_snapshot('B-id', None,
            [('unversion', 'orig-root'),  # implicitly unversions all children
             ('flush', None),
             ('add', (u'', 'dir-id', 'directory', None))])
        builder.finish_series()
        rev_tree = builder.get_branch().repository.revision_tree('B-id')
        self.assertTreeShape([(u'', 'dir-id', 'directory')], rev_tree)

