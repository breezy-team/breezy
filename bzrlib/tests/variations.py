# Copyright (C) 2005-2010 Canonical Ltd
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


from bzrlib.tests import (
    iter_suite_tests,
    multiply_scenarios,
    multiply_tests,
    )


class TestVariation(object):
    """Variations that can be applied to tests"""

    def scenarios(self):
        """Return a list of (name, params) tuples.

        All the tests subject to this varation will be repeated once per
        scenario.
        """
        raise NotImplementedError(self.scenarios)


def load_tests_from_their_variations(standard_tests, module, loader):
    """Multiply tests depending on their 'variations' attribute.

    This can be assigned to 'load_tests' in any test module to make this
    automatically work across tests in the module.
    """
    result = loader.suiteClass()
    multiply_tests_by_their_variations(standard_tests, result)
    return result


def multiply_tests_by_variations(multiplicand, variations, into_suite):
    """Given a test, multiply it by the full expansion of variations.
    
    :param multiplicand: A TestSuite, or a single TestCase to be repeated.
    :param variations: A list of TestVariation objects.
    :param into_suite: A TestSuite into which the resulting tests will be
        inserted.
    """
    # TODO: Document the behaviour if there are no variations or any of them
    # returns empty. -- mbp 2010-10-08
    combined_scenarios = reduce(multiply_scenarios,
        [v.scenarios() for v in variations])
    multiply_tests(multiplicand, combined_scenarios, into_suite)


def multiply_tests_by_their_variations(some_tests, into_suite):
    """Multiply the tests in the given suite by their declared variations.

    Each test must have a 'variations' attribute which is a list of 
    TestVariation objects.
    :param some_tests: TestSuite or Test.
    :param into_suite: A TestSuite into which the resulting tests will be
        inserted.
    """
    for test in iter_suite_tests(some_tests):
        variations = getattr(test, 'variations', None)
        if variations is None:
            into_suite.addTest(test)
        else:
            multiply_tests_by_variations(test, test.variations, into_suite)
