# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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

"""Tests for the Branch.create_checkout."""

from breezy.tests import per_branch


class TestCreateCheckout(per_branch.TestCaseWithBranch):
    def test_checkout_format_lightweight(self):
        """Make sure the new light checkout uses the desired branch format."""
        a_branch = self.make_branch("branch")
        tree = a_branch.create_checkout("checkout", lightweight=True)
        # All branches can define the format they want checkouts made in.
        # This checks it is honoured.
        expected_format = a_branch._get_checkout_format(lightweight=True)
        self.assertEqual(
            expected_format.get_branch_format().network_name(),
            tree.branch._format.network_name(),
        )

    def test_checkout_format_heavyweight(self):
        """Make sure the new heavy checkout uses the desired branch format."""
        a_branch = self.make_branch("branch")
        tree = a_branch.create_checkout("checkout", lightweight=False)
        # All branches can define the format they want checkouts made in.
        # This checks it is honoured.
        expected_format = a_branch._get_checkout_format(lightweight=False)
        self.assertEqual(
            expected_format.get_branch_format().network_name(),
            tree.branch._format.network_name(),
        )

    def test_create_revision_checkout(self):
        """Test that we can create a checkout from an earlier revision."""
        tree1 = self.make_branch_and_tree("base")
        self.build_tree(["base/a"])
        tree1.add(["a"])
        rev1 = tree1.commit("first")
        self.build_tree(["base/b"])
        tree1.add(["b"])
        tree1.commit("second")

        tree2 = tree1.branch.create_checkout("checkout", revision_id=rev1)
        self.assertEqual(rev1, tree2.last_revision())
        self.assertPathExists("checkout/a")
        self.assertPathDoesNotExist("checkout/b")

    def test_create_lightweight_checkout(self):
        """We should be able to make a lightweight checkout."""
        tree1 = self.make_branch_and_tree("base")
        tree2 = tree1.branch.create_checkout("checkout", lightweight=True)
        self.assertNotEqual(tree1.basedir, tree2.basedir)
        self.assertEqual(tree1.branch.base, tree2.branch.base)

    def test_create_checkout_exists(self):
        """We shouldn't fail if the directory already exists."""
        tree1 = self.make_branch_and_tree("base")
        self.build_tree(["checkout/"])
        tree1.branch.create_checkout("checkout", lightweight=True)
