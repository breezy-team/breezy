# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Tests for different inventory implementations"""


from bzrlib.inventory import (
    Inventory,
    )

from bzrlib.tests import (
    TestCase,
    multiply_tests_from_modules,
    )


class TestInventoryBasics(TestCase):
    # Most of these were moved the rather old bzrlib.tests.test_inv module
    
    def make_inventory(self, root_id):
        return self.inventory_class(root_id=root_id)

    def test_add_path_of_root(self):
        # add a root entry by adding its path
        inv = self.make_inventory(root_id=None)
        self.assertIs(None, inv.root)
        ie = inv.add_path("", "directory", "my-root")
        self.assertEqual("my-root", ie.file_id)
        self.assertIs(ie, inv.root)

    def test_add_path(self):
        inv = self.make_inventory(root_id='tree_root')
        ie = inv.add_path('hello', 'file', 'hello-id')
        self.assertEqual('hello-id', ie.file_id)
        self.assertEqual('file', ie.kind)


def _inventory_test_scenarios():
    """Return a sequence of test scenarios.

    Each scenario is (scenario_name_suffix, params).  The params are each 
    set as attributes on the test case.
    """
    yield ('Inventory', dict(inventory_class=Inventory))


def test_suite():
    """Generate suite containing all parameterized tests"""
    modules_to_test = [
            'bzrlib.tests.inventory_implementations',
            ]
    return multiply_tests_from_modules(modules_to_test,
            _inventory_test_scenarios())
