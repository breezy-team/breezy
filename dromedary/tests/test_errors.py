# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Tests for dromedary error classes."""

import unittest

from dromedary.errors import SocketConnectionError


class TestSocketConnectionError(unittest.TestCase):
    def assertSocketConnectionError(self, expected, *args, **kwargs):
        e = SocketConnectionError(*args, **kwargs)
        self.assertEqual(expected, str(e))

    def test_default(self):
        self.assertSocketConnectionError("Failed to connect to ahost", "ahost")

    def test_port_none(self):
        self.assertSocketConnectionError(
            "Failed to connect to ahost", "ahost", port=None
        )

    def test_port_supplied(self):
        self.assertSocketConnectionError(
            "Failed to connect to ahost:22", "ahost", port=22
        )

    def test_with_orig_error_and_port(self):
        self.assertSocketConnectionError(
            "Failed to connect to ahost:22; bogus error",
            "ahost",
            port=22,
            orig_error="bogus error",
        )

    def test_with_orig_error_no_port(self):
        self.assertSocketConnectionError(
            "Failed to connect to ahost; bogus error",
            "ahost",
            orig_error="bogus error",
        )

    def test_orig_error_exception_object(self):
        orig_error = ValueError("bad value")
        self.assertSocketConnectionError(
            f"Failed to connect to ahost; {orig_error!s}",
            host="ahost",
            orig_error=orig_error,
        )

    def test_custom_msg(self):
        self.assertSocketConnectionError(
            "Unable to connect to ssh host ahost:444; my_error",
            host="ahost",
            port=444,
            msg="Unable to connect to ssh host",
            orig_error="my_error",
        )
