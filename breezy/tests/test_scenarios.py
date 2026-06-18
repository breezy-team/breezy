# Copyright (C) 2010, 2016 Canonical Ltd
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


"""Tests for generating multiple tests for scenarios."""

from breezy.tests import TestCase, TestLoader, iter_suite_tests, multiply_tests

from .scenarios import (
    load_tests_apply_scenarios,
    multiply_scenarios,
    multiply_tests_by_their_scenarios,
)

# There aren't any actually parameterized tests here, but this exists as a
# demonstration; so that you can interactively observe them being multiplied;
# and so that we check everything hooks up properly.
load_tests = load_tests_apply_scenarios


def vary_by_color():
    """Very simple static variation example."""
    for color in ["red", "green", "blue"]:
        yield (color, {"color": color})


def vary_named_attribute(attr_name):
    """More sophisticated: vary a named parameter."""
    yield ("a", {attr_name: "a"})
    yield ("b", {attr_name: "b"})


def get_generated_test_attributes(suite, attr_name):
    """Return the `attr_name` attribute from all tests in the suite."""
    return sorted([getattr(t, attr_name) for t in iter_suite_tests(suite)])


class TestTestScenarios(TestCase):
    """Test cases for scenario-based test multiplication functionality."""

    def test_multiply_tests(self):
        """Test that tests can be multiplied by scenarios."""
        loader = TestLoader()
        suite = loader.suiteClass()
        multiply_tests(self, vary_by_color(), suite)
        self.assertEqual(
            ["blue", "green", "red"], get_generated_test_attributes(suite, "color")
        )

    def test_multiply_scenarios_from_generators(self):
        """It's safe to multiply scenarios that come from generators."""
        s = multiply_scenarios(
            vary_named_attribute("one"),
            vary_named_attribute("two"),
        )
        self.assertEqual(2 * 2, len(s), s)

    def test_multiply_tests_by_their_scenarios(self):
        """Test that tests are multiplied using their own scenarios."""
        loader = TestLoader()
        suite = loader.suiteClass()
        test_instance = PretendVaryingTest("test_nothing")
        multiply_tests_by_their_scenarios(test_instance, suite)
        self.assertEqual(
            ["a", "a", "b", "b"], get_generated_test_attributes(suite, "value")
        )

    def test_multiply_tests_no_scenarios(self):
        """Tests with no scenarios attribute aren't multiplied."""
        suite = TestLoader().suiteClass()
        multiply_tests_by_their_scenarios(self, suite)
        self.assertLength(1, list(iter_suite_tests(suite)))


class PretendVaryingTest(TestCase):
    """A test class with scenarios for testing scenario multiplication."""

    scenarios = multiply_scenarios(
        vary_named_attribute("value"),
        vary_named_attribute("other"),
    )

    def test_nothing(self):
        """This test exists just so it can be multiplied."""
        pass
