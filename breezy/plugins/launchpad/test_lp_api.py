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

import sys

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


class TestGetAuthEngine(TestCase):
    """Tests for get_auth_engine."""

    _test_needs_features = [launchpadlib_feature]

    def test_engine_is_keyed_on_the_application_name(self):
        from launchpadlib.credentials import RequestTokenAuthorizationEngine

        from . import lp_api

        # Constructed here only to work out the expected key.
        expected = RequestTokenAuthorizationEngine(
            "production", application_name="breezy"
        )
        engine = lp_api.get_auth_engine("production")
        self.assertEqual(expected.unique_consumer_id, engine.unique_consumer_id)

    def _get_auth_engine_against(self, launchpad):
        from . import lp_api

        self.overrideAttr(lp_api, "Launchpad", launchpad)
        self.assertEqual("engine", lp_api.get_auth_engine("production"))

    def test_keyword_only_factory(self):
        recorded = {}

        class KeywordOnly:
            @classmethod
            def authorization_engine_factory(cls, **kwargs):
                recorded.update(kwargs)
                return "engine"

        self._get_auth_engine_against(KeywordOnly)
        self.assertEqual(
            {"service_root": "production", "application_name": "breezy"}, recorded
        )

    def test_positional_only_factory(self):
        recorded = []

        class PositionalOnly:
            @classmethod
            def authorization_engine_factory(cls, *args):
                recorded.extend(args)
                return "engine"

        self._get_auth_engine_against(PositionalOnly)
        self.assertEqual(["production", "breezy"], recorded)


class FailingLpApiFinder:
    """Import hook that makes ``from . import lp_api`` raise.

    launchpadlib is installed wherever these tests run, so the only way to
    reach the missing dependency path is to fail the import deliberately.
    """

    name = "breezy.plugins.launchpad.lp_api"

    def __init__(self, exception):
        self.exception = exception

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.name:
            raise self.exception
        return None


class TestIterInstancesWithoutLaunchpadlib(TestCase):
    """Launchpad.iter_instances must cope with launchpadlib absent."""

    def break_lp_api(self, exception):
        """Make importing lp_api raise ``exception`` for this test."""
        from .. import launchpad as lp_package

        finder = FailingLpApiFinder(exception)
        saved = sys.modules.pop(finder.name, None)
        if saved is not None:
            self.addCleanup(sys.modules.__setitem__, finder.name, saved)
        if hasattr(lp_package, "lp_api"):
            self.addCleanup(setattr, lp_package, "lp_api", lp_package.lp_api)
            delattr(lp_package, "lp_api")
        sys.meta_path.insert(0, finder)
        self.addCleanup(sys.meta_path.remove, finder)

    def test_no_instances(self):
        from .forge import Launchpad

        self.break_lp_api(errors.DependencyNotPresent("launchpadlib", "nope"))
        self.assertEqual([], list(Launchpad.iter_instances()))

    def test_reason_is_logged(self):
        from .forge import Launchpad

        self.break_lp_api(errors.DependencyNotPresent("launchpadlib", "nope"))
        list(Launchpad.iter_instances())
        self.assertContainsRe(self.get_log(), "not listing Launchpad instances")

    def test_other_errors_still_propagate(self):
        from .forge import Launchpad

        self.break_lp_api(ValueError("this is a bug, not a missing dependency"))
        self.assertRaises(ValueError, list, Launchpad.iter_instances())

    def test_instances_are_listed_when_launchpadlib_is_present(self):
        self.requireFeature(launchpadlib_feature)
        from . import lp_api
        from .forge import Launchpad

        class AuthEngine:
            unique_consumer_id = "breezy"

        class Store:
            def load(self, consumer_id):
                return object()

        self.overrideAttr(lp_api, "get_credential_store", Store)
        self.overrideAttr(lp_api, "get_auth_engine", lambda root: AuthEngine())
        instances = list(Launchpad.iter_instances())
        self.assertNotEqual([], instances)
        for instance in instances:
            self.assertIsInstance(instance, Launchpad)
