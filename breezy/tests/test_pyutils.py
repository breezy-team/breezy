# Copyright (C) 2010 Canonical Ltd
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

"""Tests for breezy.pyutils."""

from breezy import branch, tests

from ..pyutils import calc_parent_name, get_named_object


class TestGetNamedObject(tests.TestCase):
    """Tests for get_named_object."""

    def test_module_only(self):
        import sys

        self.assertIs(sys, get_named_object("sys"))

    def test_dotted_module(self):
        self.assertIs(branch, get_named_object("breezy.branch"))

    def test_module_attr(self):
        self.assertIs(branch.Branch, get_named_object("breezy.branch", "Branch"))

    def test_dotted_attr(self):
        self.assertIs(
            branch.Branch.hooks, get_named_object("breezy.branch", "Branch.hooks")
        )

    def test_package(self):
        # breezy.tests is a package, not simply a module
        self.assertIs(tests, get_named_object("breezy.tests"))

    def test_package_attr(self):
        # breezy.tests is a package, not simply a module
        self.assertIs(tests.TestCase, get_named_object("breezy.tests", "TestCase"))

    def test_import_error(self):
        self.assertRaises(ModuleNotFoundError, get_named_object, "NO_SUCH_MODULE")

    def test_attribute_error(self):
        self.assertRaises(AttributeError, get_named_object, "sys", "NO_SUCH_ATTR")


class TestCalcParent_name(tests.TestCase):
    """Tests for calc_parent_name."""

    def test_dotted_member(self):
        self.assertEqual(
            ("mod_name", "attr1", "attr2"), calc_parent_name("mod_name", "attr1.attr2")
        )

    def test_undotted_member(self):
        self.assertEqual(
            ("mod_name", None, "attr1"), calc_parent_name("mod_name", "attr1")
        )

    def test_dotted_module_no_member(self):
        self.assertEqual(("mod", None, "sub_mod"), calc_parent_name("mod.sub_mod"))

    def test_undotted_module_no_member(self):
        err = self.assertRaises(AssertionError, calc_parent_name, "mod_name")
        self.assertEqual(
            "No parent object for top-level module 'mod_name'", err.args[0]
        )
