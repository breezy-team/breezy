# Copyright (C) 2008 Canonical Limited.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#

from bzrlib import tests

from bzrlib.plugins.groupcompress import equivalence_table


class TestEquivalenceTable(tests.TestCase):

    def test_create(self):
        eq = equivalence_table.EquivalenceTable(['a', 'b'])
        eq.set_right_lines(['b', 'd'])

    def test_matching_lines(self):
        lines = ['a', 'b', 'c', 'b']
        eq = equivalence_table.EquivalenceTable(lines)
        self.assertEqual(lines, eq._left_lines)
        self.assertEqual({'a': ([0], []), 'b': ([1, 3], []), 'c': ([2], [])},
                         eq._matching_lines)

    def test_add_right_lines(self):
        left_lines = ['a', 'b', 'c', 'b']
        eq = equivalence_table.EquivalenceTable(left_lines)
        self.assertEqual({'a': ([0], []), 'b': ([1, 3], []), 'c': ([2], [])},
                         eq._matching_lines)
        right_lines = ['b', 'c', 'd', 'c']
        eq.set_right_lines(right_lines)
        self.assertEqual({'a': ([0], []), 'b': ([1, 3], [0]),
                          'c': ([2], [1, 3]), 'd': ([], [2])},
                         eq._matching_lines)

    def test_add_new_right_lines(self):
        eq = equivalence_table.EquivalenceTable(['a', 'b', 'c', 'b'])
        eq.set_right_lines(['b', 'c', 'd', 'c'])
        eq.set_right_lines(['a', 'f', 'c', 'f'])
        self.assertEqual({'a': ([0], [0]), 'b': ([1, 3], []),
                          'c': ([2], [2]), 'f': ([], [1, 3])},
                         eq._matching_lines)

    def assertGetLeftMatches(self, expected_left, eq, right_idx):
        """Assert that we find the right matching lines."""
        self.assertEqual(expected_left, eq.get_left_matches(right_idx))

    def test_get_matching(self):
        eq = equivalence_table.EquivalenceTable(['a', 'b', 'c', 'b'])
        eq.set_right_lines(['b', 'c', 'd', 'c'])

        self.assertGetLeftMatches([1, 3], eq, 0)
        self.assertGetLeftMatches([2], eq, 1)
        self.assertGetLeftMatches([], eq, 2)
        self.assertGetLeftMatches([2], eq, 3)

    def test_extend_left_lines(self):
        eq = equivalence_table.EquivalenceTable(['a', 'b', 'c', 'b'])
        eq.set_right_lines(['b', 'c', 'd', 'c'])
        eq.extend_left_lines(['d', 'e', 'c'])
        self.assertEqual(['a', 'b', 'c', 'b', 'd', 'e', 'c'],
                         eq._left_lines)
        self.assertEqual({'a': ([0], []), 'b': ([1, 3], [0]),
                          'c': ([2, 6], [1, 3]), 'd': ([4], [2]),
                          'e': ([5], [])},
                         eq._matching_lines)
