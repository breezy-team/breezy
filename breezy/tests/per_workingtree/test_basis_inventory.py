# Copyright (C) 2005-2009, 2011, 2012, 2016 Canonical Ltd
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

from breezy.tests import TestNotApplicable
from breezy.tests.per_workingtree import TestCaseWithWorkingTree
import breezy.bzr.xml6


class TestBasisInventory(TestCaseWithWorkingTree):

    def test_create(self):
        # This test is not applicable to DirState based trees: the basis is
        # not separate is mandatory.
        if isinstance(self.workingtree_format,
                      breezy.bzr.workingtree_4.DirStateWorkingTreeFormat):
            raise TestNotApplicable("not applicable to %r"
                                    % (self.workingtree_format,))
        # TODO: jam 20051218 this probably should add more than just
        #                    a couple files to the inventory

        # Make sure the basis file is created by a commit
        t = self.make_branch_and_tree('.')
        if getattr(t, 'root_inventory', None) is None:
            raise TestNotApplicable("not applicable to %r"
                                    % (self.workingtree_format,))

        b = t.branch
        with open('a', 'wb') as f:
            f.write(b'a\n')
        t.add('a')
        r1 = t.commit('a')

        self.assertTrue(t._transport.has('basis-inventory-cache'))

        basis_inv = t.basis_tree().root_inventory
        self.assertEqual(r1, basis_inv.revision_id)

        store_inv = b.repository.get_inventory(r1)
        self.assertEqual([], store_inv._make_delta(basis_inv))

        with open('b', 'wb') as f:
            f.write(b'b\n')
        t.add('b')
        r2 = t.commit('b')

        self.assertTrue(t._transport.has('basis-inventory-cache'))

        basis_inv_lines = t.read_basis_inventory()
        basis_inv = breezy.bzr.xml7.serializer_v7.read_inventory_from_lines(
            basis_inv_lines)
        self.assertEqual(r2, basis_inv.revision_id)
        store_inv = b.repository.get_inventory(r2)

        self.assertEqual([], store_inv._make_delta(basis_inv))

    def test_wrong_format(self):
        """WorkingTree.basis safely ignores junk basis inventories"""
        # This test is not applicable to DirState based trees: the basis is
        # not separate and ignorable.
        if isinstance(self.workingtree_format,
                      breezy.bzr.workingtree_4.DirStateWorkingTreeFormat):
            raise TestNotApplicable("not applicable to %r"
                                    % (self.workingtree_format,))
        t = self.make_branch_and_tree('.')
        if getattr(t, 'root_inventory', None) is None:
            raise TestNotApplicable("not applicable to %r"
                                    % (self.workingtree_format,))

        b = t.branch
        with open('a', 'wb') as f:
            f.write(b'a\n')
        t.add('a')
        t.commit('a')
        t._transport.put_bytes('basis-inventory-cache', b'booga')
        t.basis_tree()
        t._transport.put_bytes('basis-inventory-cache', b'<xml/>')
        t.basis_tree()
        t._transport.put_bytes('basis-inventory-cache', b'<inventory />')
        t.basis_tree()
        t._transport.put_bytes('basis-inventory-cache',
                               b'<inventory format="pi"/>')
        t.basis_tree()
