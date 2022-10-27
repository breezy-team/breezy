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

"""Test that all WorkingTree's implement get_file_mtime."""

import os

from breezy import errors, transport
from breezy.tree import FileTimestampUnavailable
from breezy.tests import TestNotApplicable
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestGetFileMTime(TestCaseWithWorkingTree):
    """Test WorkingTree.get_file_mtime.

    These are more involved because we need to handle files which have been
    renamed, etc.
    """

    def make_basic_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/one'])
        tree.add(['one'])
        return tree

    def test_get_file_mtime_nested(self):
        tree = self.make_basic_tree()
        subtree = self.make_branch_and_tree('tree/sub')
        self.build_tree(['tree/sub/one'])
        subtree.add(['one'])
        subtree.commit('one')
        try:
            tree.add_reference(subtree)
        except errors.UnsupportedOperation:
            raise TestNotApplicable('subtrees not supported')
        tree.commit('sub')

        with tree.lock_read(), subtree.lock_read():
            self.assertEqual(
                tree.get_file_mtime('sub/one'),
                subtree.get_file_mtime('one'))
            self.assertEqual(
                tree.basis_tree().get_file_mtime('sub/one'),
                subtree.basis_tree().get_file_mtime('one'))

    def test_get_file_mtime(self):
        tree = self.make_basic_tree()

        st = os.lstat('tree/one')
        with tree.lock_read():
            mtime_file_id = tree.get_file_mtime('one')
            self.assertIsInstance(mtime_file_id, (float, int))
            self.assertAlmostEqual(st.st_mtime, mtime_file_id)

    def test_after_commit(self):
        """Committing shouldn't change the mtime."""
        tree = self.make_basic_tree()

        st = os.lstat('tree/one')
        tree.commit('one')

        with tree.lock_read():
            mtime = tree.get_file_mtime('one')
            self.assertAlmostEqual(st.st_mtime, mtime)

    def test_get_renamed_time(self):
        """We should handle renamed files."""
        tree = self.make_basic_tree()

        tree.rename_one('one', 'two')
        st = os.lstat('tree/two')

        with tree.lock_read():
            mtime = tree.get_file_mtime('two')
            self.assertAlmostEqual(st.st_mtime, mtime)

    def test_get_renamed_in_subdir_time(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/d/', 'tree/d/a'])
        tree.add(['d', 'd/a'])
        rev_1 = tree.commit('1')

        tree.rename_one('d', 'e')

        st = os.lstat('tree/e/a')
        with tree.lock_read():
            mtime = tree.get_file_mtime('e/a')
            self.assertAlmostEqual(st.st_mtime, mtime)

    def test_missing(self):
        tree = self.make_basic_tree()

        os.remove('tree/one')
        with tree.lock_read():
            self.assertRaises(transport.NoSuchFile, tree.get_file_mtime, 'one')
