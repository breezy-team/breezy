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
