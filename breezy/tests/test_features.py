# Copyright (C) 2011, 2016 Canonical Ltd
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

"""Tests for test feature dependencies."""

import sys

from .. import (
    plugin as _mod_plugin,
    symbol_versioning,
    tests,
    )
from . import (
    features,
    )


class TestFeature(tests.TestCase):

    def test_caching(self):
        """Feature._probe is called by the feature at most once."""
        class InstrumentedFeature(features.Feature):
            def __init__(self):
                super(InstrumentedFeature, self).__init__()
                self.calls = []

            def _probe(self):
                self.calls.append('_probe')
                return False
        feature = InstrumentedFeature()
        feature.available()
        self.assertEqual(['_probe'], feature.calls)
        feature.available()
        self.assertEqual(['_probe'], feature.calls)

    def test_named_str(self):
        """Feature.__str__ should thunk to feature_name()."""
        class NamedFeature(features.Feature):
            def feature_name(self):
                return 'symlinks'
        feature = NamedFeature()
        self.assertEqual('symlinks', str(feature))

    def test_default_str(self):
        """Feature.__str__ should default to __class__.__name__."""
        class NamedFeature(features.Feature):
            pass
        feature = NamedFeature()
        self.assertEqual('NamedFeature', str(feature))


class TestUnavailableFeature(tests.TestCase):

    def test_access_feature(self):
        feature = features.Feature()
        exception = tests.UnavailableFeature(feature)
        self.assertIs(feature, exception.args[0])


# Although this was deprecated a long time ago, please keep it here because
# it's really just a test fixture for test-feature deprecation.
simple_thunk_feature = features._CompatabilityThunkFeature(
    symbol_versioning.deprecated_in((2, 1, 0)),
    'breezy.tests.test_features',
    'simple_thunk_feature',
    'UnicodeFilenameFeature',
    replacement_module='breezy.tests.features')


class Test_CompatibilityFeature(tests.TestCase):

    def test_does_thunk(self):
        res = self.callDeprecated(
            ['breezy.tests.test_features.simple_thunk_feature '
             'was deprecated in version 2.1.0. '
             'Use breezy.tests.features.UnicodeFilenameFeature instead.'],
            simple_thunk_feature.available)
        self.assertEqual(features.UnicodeFilenameFeature.available(), res)

    def test_reports_correct_location(self):
        a_feature = features._CompatabilityThunkFeature(
            symbol_versioning.deprecated_in((2, 1, 0)),
            'breezy.tests.test_features',
            'a_feature',
            'UnicodeFilenameFeature',
            replacement_module='breezy.tests.features')

        def test_caller(message, category=None, stacklevel=1):
            # Find ourselves back from the right frame
            caller = sys._getframe(stacklevel)
            reported_file = caller.f_globals['__file__']
            reported_lineno = caller.f_lineno
            self.assertEqual(__file__, reported_file)
            # The call we're tracking occurred the line after we grabbed the
            # lineno.
            self.assertEqual(self.lineno + 1, reported_lineno)
        self.overrideAttr(symbol_versioning, 'warn', test_caller)
        # Grab the current lineno
        self.lineno = sys._getframe().f_lineno
        self.requireFeature(a_feature)


class TestModuleAvailableFeature(tests.TestCase):

    def test_available_module(self):
        feature = features.ModuleAvailableFeature('breezy.tests')
        self.assertEqual('breezy.tests', feature.module_name)
        self.assertEqual('breezy.tests', str(feature))
        self.assertTrue(feature.available())
        self.assertIs(tests, feature.module)

    def test_unavailable_module(self):
        feature = features.ModuleAvailableFeature(
            'breezy.no_such_module_exists')
        self.assertEqual('breezy.no_such_module_exists', str(feature))
        self.assertFalse(feature.available())
        self.assertIs(None, feature.module)


class TestPluginLoadedFeature(tests.TestCase):

    def test_available_plugin(self):
        plugins = _mod_plugin.plugins()
        if not plugins:
            self.skipTest('no plugins available to test with')
        a_plugin_name = next(iter(plugins))
        feature = features.PluginLoadedFeature(a_plugin_name)
        self.assertEqual(a_plugin_name, feature.plugin_name)
        self.assertEqual(a_plugin_name + ' plugin', str(feature))
        self.assertTrue(feature.available())

    def test_unavailable_plugin(self):
        feature = features.PluginLoadedFeature('idontexist')
        self.assertEqual('idontexist plugin', str(feature))
        self.assertFalse(feature.available())
        self.assertIs(None, feature.plugin)


class TestUnicodeFilenameFeature(tests.TestCase):

    def test_probe_passes(self):
        """UnicodeFilenameFeature._probe passes."""
        # We can't test much more than that because the behaviour depends
        # on the platform.
        features.UnicodeFilenameFeature._probe()


class TestBackslashFilenameFeature(tests.TestCase):

    def test_probe_passes(self):
        """BackslashFilenameFeature._probe passes."""
        # We can't test much more than that because the behaviour depends
        # on the platform.
        features.BackslashFilenameFeature._probe()
