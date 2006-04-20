# Copyright (C) 2004, 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.branch import Branch
from bzrlib.xml5 import serializer_v5


class TestBasisInventory(TestCaseWithWorkingTree):

    def test_create(self):
        # TODO: jam 20051218 this probably should add more than just
        #                    a couple files to the inventory

        # Make sure the basis file is created by a commit
        t = self.make_branch_and_tree('.')
        b = t.branch
        open('a', 'wb').write('a\n')
        t.add('a')
        t.commit('a', rev_id='r1')

        t._control_files.get_utf8('basis-inventory')

        basis_inv = t.basis_tree().inventory
        self.assertEquals('r1', basis_inv.revision_id)
        
        store_inv = b.repository.get_inventory('r1')
        self.assertEquals(store_inv._byid, basis_inv._byid)

        open('b', 'wb').write('b\n')
        t.add('b')
        t.commit('b', rev_id='r2')

        t._control_files.get_utf8('basis-inventory')

        basis_inv_txt = t.read_basis_inventory()
        basis_inv = serializer_v5.read_inventory_from_string(basis_inv_txt)
        self.assertEquals('r2', basis_inv.revision_id)
        store_inv = b.repository.get_inventory('r2')

        self.assertEquals(store_inv._byid, basis_inv._byid)

