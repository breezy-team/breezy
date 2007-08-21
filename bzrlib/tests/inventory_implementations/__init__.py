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
    
    def test_construction(self):
        pass


def _inventory_test_scenarios():
    """Return a sequence of test scenarios.

    Each scenario is (scenario_name_suffix, params).  The params are each 
    set as attributes on the test case.
    """
    yield 'Inventory', dict(inventory_class=Inventory)


def test_suite():
    """Generate suite containing all parameterized tests"""
    modules_to_test = [
            'bzrlib.tests.inventory_implementations',
            ]
    return multiply_tests_from_modules(modules_to_test,
            _inventory_test_scenarios())
