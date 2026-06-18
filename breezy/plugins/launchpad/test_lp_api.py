"""Tests for Launchpad API integration."""

# Copyright (C) 2009, 2010 Canonical Ltd
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

from ... import bedding, errors, osutils
from ...tests import TestCase
from ...tests.features import ModuleAvailableFeature

launchpadlib_feature = ModuleAvailableFeature("launchpadlib")


class TestDependencyManagement(TestCase):
    """Tests for managing the dependency on launchpadlib."""

    _test_needs_features = [launchpadlib_feature]

    def setUp(self):
        super().setUp()
        from . import lp_api

        self.lp_api = lp_api

    def patch(self, obj, name, value):
        """Temporarily set the 'name' attribute of 'obj' to 'value'."""
        self.overrideAttr(obj, name, value)

    def test_get_launchpadlib_version(self):
        # parse_launchpadlib_version returns a tuple of a version number of
        # the style used by launchpadlib.
        version_info = self.lp_api.parse_launchpadlib_version("1.5.1")
        self.assertEqual((1, 5, 1), version_info)

    def test_supported_launchpadlib_version(self):
        # If the installed version of launchpadlib is greater than the minimum
        # required version of launchpadlib, check_launchpadlib_compatibility
        # doesn't raise an error.
        launchpadlib = launchpadlib_feature.module
        self.patch(launchpadlib, "__version__", "1.5.1")
        self.lp_api.MINIMUM_LAUNCHPADLIB_VERSION = (1, 5, 1)
        # Doesn't raise an exception.
        self.lp_api.check_launchpadlib_compatibility()

    def test_unsupported_launchpadlib_version(self):
        # If the installed version of launchpadlib is less than the minimum
        # required version of launchpadlib, check_launchpadlib_compatibility
        # raises an DependencyNotPresent error.
        launchpadlib = launchpadlib_feature.module
        self.patch(launchpadlib, "__version__", "1.5.0")
        self.lp_api.MINIMUM_LAUNCHPADLIB_VERSION = (1, 5, 1)
        self.assertRaises(
            errors.DependencyNotPresent, self.lp_api.check_launchpadlib_compatibility
        )


class TestCacheDirectory(TestCase):
    """Tests for get_cache_directory."""

    _test_needs_features = [launchpadlib_feature]

    def test_get_cache_directory(self):
        # get_cache_directory returns the path to a directory inside the
        # Breezy cache directory.
        from . import lp_api

        try:
            expected_path = osutils.pathjoin(bedding.cache_dir(), "launchpad")
        except OSError:
            self.assertRaises(EnvironmentError, lp_api.get_cache_directory)
        else:
            self.assertEqual(expected_path, lp_api.get_cache_directory())
