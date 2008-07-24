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

    def test_matching_lines(self):
        lines = ['a', 'b', 'c', 'b']
        eq = equivalence_table.EquivalenceTable(lines)
        self.assertEqual(lines, eq.lines)
        self.assertEqual({'a': [0], 'b': [1, 3], 'c': [2]},
                         eq._matching_lines)

    def assertGetLeftMatches(self, expected_left, eq, right):
        """Assert that we find the right matching lines."""
        self.assertEqual(expected_left, eq.get_matches(right))

    def test_get_matching(self):
        eq = equivalence_table.EquivalenceTable(['a', 'b', 'c', 'b'])
        self.assertGetLeftMatches([1, 3], eq, 'b')
        self.assertGetLeftMatches([2], eq, 'c')
        self.assertGetLeftMatches(None, eq, 'd')
        self.assertGetLeftMatches([2], eq, 'c')

    def test_extend_lines(self):
        eq = equivalence_table.EquivalenceTable(['a', 'b', 'c', 'b'])
        eq.extend_lines(['d', 'e', 'c'], [True, True, True])
        self.assertEqual(['a', 'b', 'c', 'b', 'd', 'e', 'c'],
                         eq.lines)
        self.assertEqual({'a': [0], 'b': [1, 3],
                          'c': [2, 6], 'd': [4],
                          'e': [5]},
                         eq._matching_lines)

    def test_extend_lines_ignored(self):
        eq = equivalence_table.EquivalenceTable(['a', 'b', 'c', 'b'])
        eq.extend_lines(['d', 'e', 'c'], [False, False, True])
        self.assertEqual(['a', 'b', 'c', 'b', 'd', 'e', 'c'],
                         eq.lines)
        self.assertEqual({'a': [0], 'b': [1, 3],
                          'c': [2, 6]},
                         eq._matching_lines)

    def test_abusive(self):
        eq = equivalence_table.EquivalenceTable(['a']*1000)
        self.assertEqual({'a': range(1000)}, eq._matching_lines)
        self.assertGetLeftMatches(range(1000), eq, 'a')
