# Copyright (C) 2005-2009, 2016 Canonical Ltd
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

"""Tests for library API infrastructure

This is specifically for things controlling the interface, such as versioning.
Tests for particular parts of the library interface should be in specific
relevant test modules.
"""

import breezy
import breezy.api
from ..errors import IncompatibleAPI
from . import TestCase

class APITests(TestCase):

    def test_library_version(self):
        """Library API version is exposed"""
        self.assertTrue(isinstance(breezy.__version__, str))
        self.assertTrue(isinstance(breezy.version_string, str))
        self.assertTrue(isinstance(breezy.version_info, tuple))
        self.assertEqual(len(breezy.version_info), 5)


class TestAPIVersioning(TestCase):

    def test_get_current_api_version_uses_breezy_version_info(self):
        self.assertEqual(breezy.version_info[0:3],
            breezy.api.get_current_api_version())

    def test_require_any_api_wanted_one(self):
        breezy.api.require_any_api([breezy.version_info[:3]])

    def test_require_any_api_wanted_first_compatible(self):
        breezy.api.require_any_api([breezy.version_info[:3], (5, 6, 7)])

    def test_require_any_api_wanted_second_compatible(self):
        breezy.api.require_any_api([(5, 6, 7), breezy.version_info[:3]])

    def test_require_any_api_wanted_none_compatible(self):
        err = self.assertRaises(IncompatibleAPI, breezy.api.require_any_api,
            [(1, 2, 2), (5, 6, 7)])
        self.assertEqual(err.api, breezy)
        self.assertEqual(err.wanted, (5, 6, 7))
        self.assertEqual(err.current, breezy.version_info[:3])

    def test_require_api_wanted_is_current_is_ok(self):
        breezy.api.require_api(breezy.version_info[:3])

    def test_require_api_wanted_is_not_ok(self):
        err = self.assertRaises(IncompatibleAPI,
            breezy.api.require_api, (1, 1, 1))
        self.assertEqual(err.api, breezy)
        self.assertEqual(err.wanted, (1, 1, 1))
        self.assertEqual(err.current, breezy.version_info[:3])

