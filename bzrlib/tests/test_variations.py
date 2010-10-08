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
    multiply_tests_by_their_variations,
    multiply_tests_by_variations,
    )


class SimpleVariation(TestVariation):

    def __init__(self, attr_name):
        # this variation is unusual in having constructor parameters -- most
        # will be static -- but this lets us test having multiply variations
        # of a single test
        self.attr_name = attr_name
        
    def scenarios(self):
        return [
            ('a', {self.attr_name: 'a'}),
            ('b', {self.attr_name: 'b'})
        ]


def get_generated_test_attributes(suite, attr_name):
    return sorted([
        getattr(t, attr_name) for t in iter_suite_tests(suite)])


class TestTestVariations(TestCase):

    def test_multiply_tests_by_variations(self):
        loader = TestLoader()
        suite = loader.suiteClass()
        multiply_tests_by_variations(
            self,
            [SimpleVariation('value')],
            suite)
        self.assertEquals(
            get_generated_test_attributes(suite, 'value'),
            ['a', 'b'])

    def test_multiply_tests_by_their_variations(self):
        loader = TestLoader()
        suite = loader.suiteClass()
        multiply_tests_by_their_variations(PretendVaryingTest('test_nothing'),
            suite)
        self.assertEquals(
            get_generated_test_attributes(suite, 'value'),
            ['a', 'a', 'b', 'b'])

    def test_multiply_tests_no_variations(self):
        """Tests with no variations attribute aren't multiplied"""
        suite = TestLoader().suiteClass()
        multiply_tests_by_their_variations(self,
            suite)
        self.assertEquals(
            len(list(iter_suite_tests(suite))), 1)

class PretendVaryingTest(TestCase):
    
    variations = [
        SimpleVariation('value'), 
        SimpleVariation('other'),
        ]

    def test_nothing(self):
        """This test exists just so it can be multiplied"""
        pass
