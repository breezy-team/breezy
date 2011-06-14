# Copyright (C) 2005-2011 Canonical Ltd
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

"""Tests for test feature dependencies.
"""

from bzrlib import (
    symbol_versioning,
    tests,
    )
from bzrlib.tests import (
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


simple_thunk_feature = features._CompatabilityThunkFeature(
    symbol_versioning.deprecated_in((2, 1, 0)),
    'bzrlib.tests.test_features',
    'simple_thunk_feature',
    'UnicodeFilename',
    replacement_module='bzrlib.tests.features')


class Test_CompatibilityFeature(tests.TestCase):

    def test_does_thunk(self):
        res = self.callDeprecated(
            ['bzrlib.tests.test_features.simple_thunk_feature '
             'was deprecated in version 2.1.0. '
             'Use bzrlib.tests.features.UnicodeFilename instead.'],
            simple_thunk_feature.available)
        self.assertEqual(features.UnicodeFilename.available(), res)


class TestModuleAvailableFeature(tests.TestCase):

    def test_available_module(self):
        feature = features.ModuleAvailableFeature('bzrlib.tests')
        self.assertEqual('bzrlib.tests', feature.module_name)
        self.assertEqual('bzrlib.tests', str(feature))
        self.assertTrue(feature.available())
        self.assertIs(tests, feature.module)

    def test_unavailable_module(self):
        feature = features.ModuleAvailableFeature(
            'bzrlib.no_such_module_exists')
        self.assertEqual('bzrlib.no_such_module_exists', str(feature))
        self.assertFalse(feature.available())
        self.assertIs(None, feature.module)


class TestUnicodeFilenameFeature(tests.TestCase):

    def test_probe_passes(self):
        """UnicodeFilenameFeature._probe passes."""
        # We can't test much more than that because the behaviour depends
        # on the platform.
        features.UnicodeFilenameFeature._probe()
