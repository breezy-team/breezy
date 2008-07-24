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

class _CompiledGroupCompress(tests.Feature):

    def _probe(self):
        try:
            import bzrlib.plugins.groupcompress._groupcompress_c
        except ImportError:
            return False
        else:
            return True

    def feature_name(self):
        return 'bzrlib.plugins.groupcompress._groupcompress_c'

CompiledGroupCompress = _CompiledGroupCompress()


class TestEquivalenceTable(tests.TestCase):

    eq_class = equivalence_table.EquivalenceTable

    def test_create(self):
        eq = self.eq_class(['a', 'b'])

    def test_matching_lines(self):
        lines = ['a', 'b', 'c', 'b']
        eq = self.eq_class(lines)
        self.assertEqual(lines, eq.lines)
        self.assertEqual({'a': [0], 'b': [1, 3], 'c': [2]},
                         eq._get_matching_lines())

    def test_set_right_lines(self):
        eq = self.eq_class(['a', 'b', 'c', 'b'])
        eq.set_right_lines(['f', 'b', 'b'])
        self.assertEqual(None, eq.get_idx_matches(0))
        self.assertEqual([1, 3], eq.get_idx_matches(1))
        self.assertEqual([1, 3], eq.get_idx_matches(2))

    def assertGetLeftMatches(self, expected_left, eq, right):
        """Assert that we find the right matching lines."""
        self.assertEqual(expected_left, eq.get_matches(right))

    def test_get_matching(self):
        eq = self.eq_class(['a', 'b', 'c', 'b'])
        self.assertGetLeftMatches([1, 3], eq, 'b')
        self.assertGetLeftMatches([2], eq, 'c')
        self.assertGetLeftMatches(None, eq, 'd')
        self.assertGetLeftMatches([2], eq, 'c')

    def test_extend_lines(self):
        eq = self.eq_class(['a', 'b', 'c', 'b'])
        eq.extend_lines(['d', 'e', 'c'], [True, True, True])
        self.assertEqual(['a', 'b', 'c', 'b', 'd', 'e', 'c'],
                         eq.lines)
        self.assertEqual({'a': [0], 'b': [1, 3],
                          'c': [2, 6], 'd': [4],
                          'e': [5]},
                         eq._get_matching_lines())

    def test_extend_lines_ignored(self):
        eq = self.eq_class(['a', 'b', 'c', 'b'])
        eq.extend_lines(['d', 'e', 'c'], [False, False, True])
        self.assertEqual(['a', 'b', 'c', 'b', 'd', 'e', 'c'],
                         eq.lines)
        self.assertEqual({'a': [0], 'b': [1, 3],
                          'c': [2, 6], 'd': None, 'e': None},
                         eq._get_matching_lines())

    def test_abusive(self):
        eq = self.eq_class(['a']*1000)
        self.assertEqual({'a': range(1000)}, eq._get_matching_lines())
        self.assertGetLeftMatches(range(1000), eq, 'a')


class TestCompiledEquivalenceTable(TestEquivalenceTable):

    _tests_need_features = [CompiledGroupCompress]

    def setUp(self):
        super(TestCompiledEquivalenceTable, self).setUp()
        from bzrlib.plugins.groupcompress import _groupcompress_c
        self.eq_class = _groupcompress_c.EquivalenceTable
