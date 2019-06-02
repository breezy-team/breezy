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

"""Test that WorkingTree.basis_tree() yields a valid tree."""

from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestBasisTree(TestCaseWithWorkingTree):

    def test_emtpy_tree(self):
        """A working tree with no parents."""
        tree = self.make_branch_and_tree('tree')
        basis_tree = tree.basis_tree()

        with basis_tree.lock_read():
            self.assertEqual(
                [], list(basis_tree.list_files(include_root=True)))

    def test_same_tree(self):
        """Test basis_tree when working tree hasn't been modified."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file', 'dir/', 'dir/subfile'])
        tree.add(['file', 'dir', 'dir/subfile'])
        revision_id = tree.commit('initial tree')

        basis_tree = tree.basis_tree()
        with basis_tree.lock_read():
            self.assertEqual(revision_id, basis_tree.get_revision_id())
            # list_files() may return in either dirblock or sorted order
            # TODO: jam 20070215 Should list_files have an explicit order?
            self.assertEqual(
                ['', 'dir', 'dir/subfile', 'file'],
                sorted(info[0] for info in basis_tree.list_files(True)))

    def test_altered_tree(self):
        """Test basis really is basis after working has been modified."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file', 'dir/', 'dir/subfile'])
        tree.add(['file', 'dir', 'dir/subfile'])
        revision_id = tree.commit('initial tree')

        self.build_tree(['new file', 'new dir/'])
        tree.rename_one('file', 'dir/new file')
        tree.unversion(['dir/subfile'])
        tree.add(['new file', 'new dir'])

        basis_tree = tree.basis_tree()
        with basis_tree.lock_read():
            self.assertEqual(revision_id, basis_tree.get_revision_id())
            # list_files() may return in either dirblock or sorted order
            # TODO: jam 20070215 Should list_files have an explicit order?
            self.assertEqual(
                ['', 'dir', 'dir/subfile', 'file'],
                sorted(info[0] for info in basis_tree.list_files(True)))
