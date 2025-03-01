# Copyright (C) 2005 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for the IdentityMap class."""

# import system imports here

# import breezy specific imports here
from .. import errors as errors
from .. import identitymap as identitymap
from . import TestCase


class TestIdentityMap(TestCase):
    def test_symbols(self):
        pass

    def test_construct(self):
        identitymap.IdentityMap()

    def test_add_weave(self):
        map = identitymap.IdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        self.assertEqual(weave, map.find_weave("id"))

    def test_double_add_weave(self):
        map = identitymap.IdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        self.assertRaises(errors.BzrError, map.add_weave, "id", weave)
        self.assertEqual(weave, map.find_weave("id"))

    def test_remove_object(self):
        map = identitymap.IdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        map.remove_object(weave)
        map.add_weave("id", weave)


class TestNullIdentityMap(TestCase):
    def test_symbols(self):
        pass

    def test_construct(self):
        identitymap.NullIdentityMap()

    def test_add_weave(self):
        map = identitymap.NullIdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        self.assertEqual(None, map.find_weave("id"))

    def test_double_add_weave(self):
        map = identitymap.NullIdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        map.add_weave("id", weave)
        self.assertEqual(None, map.find_weave("id"))

    def test_null_identity_map_has_no_remove(self):
        map = identitymap.NullIdentityMap()
        self.assertEqual(None, getattr(map, "remove_object", None))
