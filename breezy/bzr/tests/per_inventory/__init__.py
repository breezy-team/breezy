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

"""Tests for different inventory implementations."""

from breezy import tests
from breezy.bzr import groupcompress


def load_tests(loader, basic_tests, pattern):
    """Generate suite containing all parameterized tests."""
    modules_to_test = [
        "breezy.bzr.tests.per_inventory.basics",
    ]
    from breezy.bzr.inventory import CHKInventory, Inventory

    def inv_to_chk_inv(test, inv):
        """CHKInventory needs a backing VF, so we create one."""
        factory = groupcompress.make_pack_factory(True, True, 1)
        trans = test.get_transport("chk-inv")
        trans.ensure_base()
        vf = factory(trans)
        # We intentionally use a non-standard maximum_size, so that we are more
        # likely to trigger splits, and get increased test coverage.
        chk_inv = CHKInventory.from_inventory(
            vf, inv, maximum_size=100, search_key_name=b"hash-255-way"
        )
        return chk_inv

    scenarios = [
        (
            "Inventory",
            {"_inventory_class": Inventory, "_inv_to_test_inv": lambda test, inv: inv},
        ),
        (
            "CHKInventory",
            {
                "_inventory_class": CHKInventory,
                "_inv_to_test_inv": inv_to_chk_inv,
            },
        ),
    ]
    # add the tests for the sub modules
    return tests.multiply_tests(
        loader.loadTestsFromModuleNames(modules_to_test), scenarios, basic_tests
    )


class TestCaseWithInventory(tests.TestCaseWithMemoryTransport):
    _inventory_class = None  # set by load_tests
    _inv_to_test_inv = None  # set by load_tests

    def make_test_inventory(self):
        """Return an instance of the Inventory class under test."""
        return self._inventory_class()

    def inv_to_test_inv(self, inv):
        """Convert a regular Inventory object into an inventory under test."""
        return self._inv_to_test_inv(self, inv)
