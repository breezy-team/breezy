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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the BranchBuilder class."""

from bzrlib import (
    branch as _mod_branch,
    errors,
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
        rev_id1 = builder.build_snapshot(None, 'A-id',
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
        rev_id2 = builder.build_snapshot(None, 'B-id',
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
        rev_id2 = builder.build_snapshot(None, 'B-id',
            [('add', ('b', 'b-id', 'directory', None))])
        rev_tree = builder.get_branch().repository.revision_tree('B-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                              (u'b', 'b-id', 'directory'),
                             ], rev_tree)

    def test_modify_file(self):
        builder = self.build_a_rev()
        rev_id2 = builder.build_snapshot(None, 'B-id',
            [('modify', ('a-id', 'new\ncontent\n'))])
        self.assertEqual('B-id', rev_id2)
        branch = builder.get_branch()
        rev_tree = branch.repository.revision_tree(rev_id2)
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertEqual('new\ncontent\n', rev_tree.get_file_text('a-id'))

    def test_delete_file(self):
        builder = self.build_a_rev()
        rev_id2 = builder.build_snapshot(None, 'B-id',
            [('unversion', 'a-id')])
        self.assertEqual('B-id', rev_id2)
        branch = builder.get_branch()
        rev_tree = branch.repository.revision_tree(rev_id2)
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertTreeShape([(u'', 'a-root-id', 'directory')], rev_tree)

    def test_delete_directory(self):
        builder = self.build_a_rev()
        rev_id2 = builder.build_snapshot(None, 'B-id',
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
        builder.build_snapshot(None, 'C-id', [('unversion', 'b-id')])
        rev_tree = builder.get_branch().repository.revision_tree('C-id')
        self.assertTreeShape([(u'', 'a-root-id', 'directory'),
                              (u'a', 'a-id', 'file'),
                             ], rev_tree)

    def test_unknown_action(self):
        builder = self.build_a_rev()
        self.assertRaises(errors.UnknownBuildAction,
            builder.build_snapshot, None, 'B-id', [('weirdo', ('foo',))])
