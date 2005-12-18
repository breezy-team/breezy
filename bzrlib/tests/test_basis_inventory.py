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
from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.xml5 import serializer_v5

class TestBasisInventory(TestCaseInTempDir):

    def test_create(self):

        # Make sure the basis file is created by a commit
        b = Branch.initialize(u'.')
        t = b.working_tree()
        open('a', 'wb').write('a\n')
        t.add('a')
        t.commit('a', rev_id='r1')

        self.failUnlessExists('.bzr/basis-inventory.r1')

        basis_inv_txt = t.read_basis_inventory('r1')
        basis_inv = serializer_v5.read_inventory_from_string(basis_inv_txt)
        #self.assertEquals('r1', basis_inv.revision_id)
        
        store_inv = b.get_inventory('r1')
        self.assertEquals(store_inv._byid, basis_inv._byid)

        open('b', 'wb').write('b\n')
        t.add('b')
        t.commit('b', rev_id='r2')

        self.failIfExists('.bzr/basis-inventory.r1')
        self.failUnlessExists('.bzr/basis-inventory.r2')

        basis_inv_txt = t.read_basis_inventory('r2')
        basis_inv = serializer_v5.read_inventory_from_string(basis_inv_txt)
        store_inv = b.get_inventory('r2')

        self.assertEquals(store_inv._byid, basis_inv._byid)

