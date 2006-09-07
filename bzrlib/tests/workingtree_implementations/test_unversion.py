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

"""Tests of the WorkingTree.unversion API."""

from bzrlib import errors
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestUnversion(TestCaseWithWorkingTree):

    def test_unversion_requires_write_lock(self):
        """WT.unversion([]) in a read lock raises ReadOnlyError."""
        tree = self.make_branch_and_tree('.')
        tree.lock_read()
        self.assertRaises(errors.ReadOnlyError, tree.unversion, [])
        tree.unlock()

    def test_unversion_missing_file(self):
        """WT.unversion(['missing-id']) raises NoSuchId."""
        tree = self.make_branch_and_tree('.')
        self.assertRaises(errors.NoSuchId, tree.unversion, ['missing-id'])

    def test_unversion_several_files(self):
        """After unversioning several files, they should not be versioned."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'c'])
        tree.add(['a', 'b', 'c'], ['a-id', 'b-id', 'c-id'])
        # within a lock unversion should take effect
        tree.lock_write()
        tree.unversion(['a-id', 'b-id'])
        self.assertFalse(tree.has_id('a-id'))
        self.assertFalse(tree.has_id('b-id'))
        self.assertTrue(tree.has_id('c-id'))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('b'))
        self.assertTrue(tree.has_filename('c'))
        tree.unlock()
        # the changes should have persisted to disk - reopen the workingtree
        # to be sure.
        tree = tree.bzrdir.open_workingtree()
        self.assertFalse(tree.has_id('a-id'))
        self.assertFalse(tree.has_id('b-id'))
        self.assertTrue(tree.has_id('c-id'))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('b'))
        self.assertTrue(tree.has_filename('c'))
        
    def test_unversion_subtree(self):
        """Unversioning the root of a subtree unversions the entire subtree."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'c'])
        tree.add(['a', 'a/b', 'c'], ['a-id', 'b-id', 'c-id'])
        # within a lock unversion should take effect
        tree.lock_write()
        tree.unversion(['a-id'])
        self.assertFalse(tree.has_id('a-id'))
        self.assertFalse(tree.has_id('b-id'))
        self.assertTrue(tree.has_id('c-id'))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('a/b'))
        self.assertTrue(tree.has_filename('c'))
        tree.unlock()
