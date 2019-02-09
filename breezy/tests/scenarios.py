# Copyright (C) 2010 Canonical Ltd
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


"""Generate multiple variations in different scenarios.

For a class whose tests should be repeated in varying scenarios, set a
`scenarios` member to a list of scenarios where it should be repeated.

This is similar to the interface provided by
<http://launchpad.net/testscenarios/>.
"""


from . import (
    iter_suite_tests,
    multiply_scenarios,
    multiply_tests,
    )


def load_tests_apply_scenarios(loader, standard_tests, pattern):
    """Multiply tests depending on their 'scenarios' attribute.

    This can be assigned to 'load_tests' in any test module to make this
    automatically work across tests in the module.
    """
    result = loader.suiteClass()
    multiply_tests_by_their_scenarios(standard_tests, result)
    return result


def multiply_tests_by_their_scenarios(some_tests, into_suite):
    """Multiply the tests in the given suite by their declared scenarios.

    Each test must have a 'scenarios' attribute which is a list of
    (name, params) pairs.

    :param some_tests: TestSuite or Test.
    :param into_suite: A TestSuite into which the resulting tests will be
        inserted.
    """
    for test in iter_suite_tests(some_tests):
        scenarios = getattr(test, 'scenarios', None)
        if scenarios is None:
            into_suite.addTest(test)
        else:
            multiply_tests(test, test.scenarios, into_suite)
