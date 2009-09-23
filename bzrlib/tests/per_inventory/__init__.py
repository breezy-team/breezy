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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for different inventory implementations"""

from bzrlib import (
    groupcompress,
    tests,
    transport,
    )

def load_tests(basic_tests, module, loader):
    """Generate suite containing all parameterized tests"""
    modules_to_test = [
        'bzrlib.tests.per_inventory.basics',
        ]
    from bzrlib.inventory import Inventory, CHKInventory
    scenarios = [('Inventory', {'inventory_class': Inventory,
                                'to_inventory': lambda x: x
                               }),
                 ('CHKInventory', {'inventory_class':CHKInventory,
                                   'to_inventory': CHKInventory.from_inventory
                                  })]
    # add the tests for the sub modules
    return tests.multiply_tests(
        loader.loadTestsFromModuleNames(modules_to_test),
        scenarios, basic_tests)


class TestCaseWithInventory(tests.TestCase):

