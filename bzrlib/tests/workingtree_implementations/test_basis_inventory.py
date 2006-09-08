# Copyright (C) 2004, 2005 by Canonical Ltd
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
from bzrlib.revision import Revision
import bzrlib.xml5


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
        basis_inv = bzrlib.xml5.serializer_v5.read_inventory_from_string(basis_inv_txt)
        basis_inv.root.revision = 'r2'
        self.assertEquals('r2', basis_inv.revision_id)
        store_inv = b.repository.get_inventory('r2')

        self.assertEquals(store_inv._byid, basis_inv._byid)

    def test_basis_inv_gets_revision(self):
        """When the inventory of the basis tree has no revision id it gets set.

        It gets set during set_parent_trees() or set_parent_ids().
        """
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        # TODO change this to use CommitBuilder
        tree.branch.repository.control_weaves.get_weave('inventory',
            tree.branch.repository.get_transaction()
            ).add_lines('r1', [], [
                '<inventory format="5">\n',
                '</inventory>\n'])
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1="",
                       revision_id='r1')
        rev.parent_ids = []
        tree.branch.repository.add_revision('r1', rev)
        tree.unlock()
        tree.branch.append_revision('r1')
        tree.set_parent_trees(
            [('r1', tree.branch.repository.revision_tree('r1'))])
        # TODO: we should deserialise the file here, rather than peeking
        # without parsing, but to do this properly needs a serialiser on the
        # tree object that abstracts whether it is xml/rio/etc.
        self.assertContainsRe(
            tree._control_files.get_utf8('basis-inventory').read(),
            'revision_id="r1"')
        
