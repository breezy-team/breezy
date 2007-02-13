# Copyright (C) 2004, 2005 Canonical Ltd
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

import os

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.branch import Branch
from bzrlib import inventory
from bzrlib.revision import Revision
import bzrlib.xml6


class TestBasisInventory(TestCaseWithWorkingTree):

    def test_create(self):
        # This test is not applicable to DirState based trees: the basis is
        # not separate is mandatory.
        if isinstance(self.workingtree_format,
            bzrlib.workingtree_4.WorkingTreeFormat4):
            return
        # TODO: jam 20051218 this probably should add more than just
        #                    a couple files to the inventory

        # Make sure the basis file is created by a commit
        t = self.make_branch_and_tree('.')
        b = t.branch
        open('a', 'wb').write('a\n')
        t.add('a')
        t.commit('a', rev_id='r1')

        t._control_files.get_utf8('basis-inventory-cache')

        basis_inv = t.basis_tree().inventory
        self.assertEquals('r1', basis_inv.revision_id)
        
        store_inv = b.repository.get_inventory('r1')
        self.assertEquals(store_inv._byid, basis_inv._byid)

        open('b', 'wb').write('b\n')
        t.add('b')
        t.commit('b', rev_id='r2')

        t._control_files.get_utf8('basis-inventory-cache')

        basis_inv_txt = t.read_basis_inventory()
        basis_inv = bzrlib.xml6.serializer_v6.read_inventory_from_string(basis_inv_txt)
        self.assertEquals('r2', basis_inv.revision_id)
        store_inv = b.repository.get_inventory('r2')

        self.assertEquals(store_inv._byid, basis_inv._byid)

    def test_wrong_format(self):
        """WorkingTree.basis safely ignores junk basis inventories"""
        # This test is not applicable to DirState based trees: the basis is
        # not separate and ignorable.
        if isinstance(self.workingtree_format,
            bzrlib.workingtree_4.WorkingTreeFormat4):
            return
        t = self.make_branch_and_tree('.')
        b = t.branch
        open('a', 'wb').write('a\n')
        t.add('a')
        t.commit('a', rev_id='r1')
        t._control_files.put_utf8('basis-inventory-cache', 'booga')
        t.basis_tree()
        t._control_files.put_utf8('basis-inventory-cache', '<xml/>')
        t.basis_tree()
        t._control_files.put_utf8('basis-inventory-cache', '<inventory />')
        t.basis_tree()
        t._control_files.put_utf8('basis-inventory-cache', 
                                  '<inventory format="pi"/>')
        t.basis_tree()
