# Copyright (C) 2011 Canonical Ltd
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

"""Tests for control directory formats."""

from breezy import (
    errors,
    )

from breezy.tests.per_controldir import TestCaseWithControlDir


class TestControlDir(TestCaseWithControlDir):

    def test_get_format_description(self):
        self.assertIsInstance(self.bzrdir_format.get_format_description(),
                              str)

    def test_is_supported(self):
        self.assertIsInstance(self.bzrdir_format.is_supported(), bool)

    def test_upgrade_recommended(self):
        self.assertIsInstance(self.bzrdir_format.upgrade_recommended, bool)

    def test_supports_transport(self):
        self.assertIsInstance(
            self.bzrdir_format.supports_transport(self.get_transport()), bool)

    def test_check_support_status(self):
        if not self.bzrdir_format.is_supported():
            self.assertRaises(errors.UnsupportedFormatError,
                              self.bzrdir_format.check_support_status, False)
        else:
            self.bzrdir_format.check_support_status(True)
            self.bzrdir_format.check_support_status(False)
