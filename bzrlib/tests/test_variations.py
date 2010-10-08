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
    TestCase,
    TestLoader,
    iter_suite_tests,
    )

from bzrlib.tests.variations import (
    TestVariation,
    multiply_tests_by_variations,
    )


class SimpleVariation(TestVariation):

    def scenarios(self):
        return [
            ('a', {'value': 'a'}),
            ('b', {'value': 'b'})
        ]


class TestTestVariations(TestCase):

    def test_multiply_tests_by_variations(self):
        loader = TestLoader()
        suite = loader.suiteClass()
        multiply_tests_by_variations(
            self,
            [SimpleVariation()],
            suite)
        generated_tests = list(iter_suite_tests(suite))
        self.assertEquals(len(generated_tests), 2)
        self.assertEquals(
            sorted([t.value for t in generated_tests]),
            ['a', 'b'])
