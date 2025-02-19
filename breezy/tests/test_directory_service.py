# Copyright (C) 2008-2012, 2016 Canonical Ltd
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

"""Test directory service implementation"""

from .. import transport, urlutils
from ..directory_service import (
    AliasDirectory,
    DirectoryServiceRegistry,
    InvalidLocationAlias,
    UnsetLocationAlias,
    directories,
)
from . import TestCase, TestCaseWithTransport


class FooService:
    """A directory service that maps the name to a FILE url"""

    # eg 'file:///foo' on Unix, or 'file:///C:/foo' on Windows
    base = urlutils.local_path_to_url("/foo")

    def look_up(self, name, url, purpose=None):
        return self.base + name


class TestDirectoryLookup(TestCase):
    def setUp(self):
        super().setUp()
        self.registry = DirectoryServiceRegistry()
        self.registry.register("foo:", FooService, "Map foo URLs to http urls")

    def test_get_directory_service(self):
        directory, suffix = self.registry.get_prefix("foo:bar")
        self.assertIs(FooService, directory)
        self.assertEqual("bar", suffix)

    def test_dereference(self):
        self.assertEqual(FooService.base + "bar", self.registry.dereference("foo:bar"))
        self.assertEqual(
            FooService.base + "bar",
            self.registry.dereference("foo:bar", purpose="write"),
        )
        self.assertEqual("baz:qux", self.registry.dereference("baz:qux"))
        self.assertEqual(
            "baz:qux", self.registry.dereference("baz:qux", purpose="write")
        )

    def test_get_transport(self):
        directories.register("foo:", FooService, "Map foo URLs to http urls")
        self.addCleanup(directories.remove, "foo:")
        self.assertEqual(
            FooService.base + "bar/", transport.get_transport("foo:bar").base
        )


class OldService:
    """A directory service that maps the name to a FILE url"""

    # eg 'file:///foo' on Unix, or 'file:///C:/foo' on Windows
    base = urlutils.local_path_to_url("/foo")

    def look_up(self, name, url):
        return self.base + name


class TestOldDirectoryLookup(TestCase):
    """Test compatibility with older implementations of Directory
    that don't support the purpose argument.
    """

    def setUp(self):
        super().setUp()
        self.registry = DirectoryServiceRegistry()
        self.registry.register("old:", OldService, "Map foo URLs to http urls")

    def test_dereference(self):
        self.assertEqual(OldService.base + "bar", self.registry.dereference("old:bar"))
        self.assertEqual(
            OldService.base + "bar",
            self.registry.dereference("old:bar", purpose="write"),
        )
        self.assertEqual("baz:qux", self.registry.dereference("baz:qux"))
        self.assertEqual(
            "baz:qux", self.registry.dereference("baz:qux", purpose="write")
        )


class TestAliasDirectory(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.branch = self.make_branch(".")

    def assertAliasFromBranch(self, setter, value, alias):
        setter(value)
        self.assertEqual(value, directories.dereference(alias))

    def test_lookup_parent(self):
        self.assertAliasFromBranch(self.branch.set_parent, "http://a", ":parent")

    def test_lookup_submit(self):
        self.assertAliasFromBranch(self.branch.set_submit_branch, "http://b", ":submit")

    def test_lookup_public(self):
        self.assertAliasFromBranch(self.branch.set_public_branch, "http://c", ":public")

    def test_lookup_bound(self):
        self.assertAliasFromBranch(self.branch.set_bound_location, "http://d", ":bound")

    def test_lookup_push(self):
        self.assertAliasFromBranch(self.branch.set_push_location, "http://e", ":push")

    def test_lookup_this(self):
        self.assertEqual(self.branch.base, directories.dereference(":this"))

    def test_extra_path(self):
        self.assertEqual(
            urlutils.join(self.branch.base, "arg"), directories.dereference(":this/arg")
        )

    def test_lookup_badname(self):
        e = self.assertRaises(InvalidLocationAlias, directories.dereference, ":booga")
        self.assertEqual('":booga" is not a valid location alias.', str(e))

    def test_lookup_badvalue(self):
        e = self.assertRaises(UnsetLocationAlias, directories.dereference, ":parent")
        self.assertEqual("No parent location assigned.", str(e))

    def test_register_location_alias(self):
        self.addCleanup(AliasDirectory.branch_aliases.remove, "booga")
        AliasDirectory.branch_aliases.register(
            "booga", lambda b: "UHH?", help="Nobody knows"
        )
        self.assertEqual("UHH?", directories.dereference(":booga"))


class TestColocatedDirectory(TestCaseWithTransport):
    def test_lookup_non_default(self):
        default = self.make_branch(".")
        non_default = default.controldir.create_branch(name="nondefault")
        self.assertEqual(non_default.base, directories.dereference("co:nondefault"))

    def test_lookup_default(self):
        default = self.make_branch(".")
        non_default = default.controldir.create_branch(name="nondefault")
        self.assertEqual(
            urlutils.join_segment_parameters(
                default.controldir.user_url, {"branch": ""}
            ),
            directories.dereference("co:"),
        )

    def test_no_such_branch(self):
        # No error is raised in this case, that is up to the code that actually
        # opens the branch.
        default = self.make_branch(".")
        self.assertEqual(
            urlutils.join_segment_parameters(
                default.controldir.user_url, {"branch": "foo"}
            ),
            directories.dereference("co:foo"),
        )
