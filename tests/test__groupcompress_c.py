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

"""Tests for the pyrex extension of groupcompress"""

from bzrlib import tests

from bzrlib.plugins.groupcompress import groupcompress


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


class TestCompiledEquivalenceTable(tests.TestCase):
    """Direct tests for the compiled Equivalence Table."""

    _tests_need_features = [CompiledGroupCompress]

    # These tests assume that hash(int) == int
    # If that ever changes, we can simply change this code to use a custom
    # class that has precomputed values returned from __hash__.


    # TODO: We need a test that forces a rebuild of the hash array, and makes
    #       sure that the lines that should not be indexed *stay* not indexed

    def setUp(self):
        super(TestCompiledEquivalenceTable, self).setUp()
        from bzrlib.plugins.groupcompress import _groupcompress_c
        self._gc_module = _groupcompress_c

    def test_minimum_hash_size(self):
        eq = self._gc_module.EquivalenceTable([])
        # We request at least 50% free space in the hash (to make collisions
        # more bearable)
        self.assertEqual(1024, eq._py_compute_minimum_hash_size(512))
        self.assertEqual(2048, eq._py_compute_minimum_hash_size(513))
        self.assertEqual(2048, eq._py_compute_minimum_hash_size(1000))
        self.assertEqual(2048, eq._py_compute_minimum_hash_size(1024))

    def test_recommended_hash_size(self):
        eq = self._gc_module.EquivalenceTable([])
        # We always recommend a minimum of 8k
        self.assertEqual(8192, eq._py_compute_recommended_hash_size(10))
        self.assertEqual(8192, eq._py_compute_recommended_hash_size(1000))
        self.assertEqual(8192, eq._py_compute_recommended_hash_size(2000))
        self.assertEqual(16384, eq._py_compute_recommended_hash_size(4000))

        # And we recommend at least 75% free slots
        self.assertEqual(16384, eq._py_compute_recommended_hash_size(4096))
        self.assertEqual(32768, eq._py_compute_recommended_hash_size(4097))

    def test__raw_lines(self):
        eq = self._gc_module.EquivalenceTable([1, 2, 3])
        self.assertEqual([(1, 1, 1, -1), (2, 2, 2, -1), (3, 3, 3, -1)],
                         eq._inspect_left_lines())

    def test_build_hash(self):
        eq = self._gc_module.EquivalenceTable([1, 2, 3])
        # (size, [(offset, head_offset_in_lines, count)])
        self.assertEqual((8192, [(1, 0, 1), (2, 1, 1), (3, 2, 1)]),
                         eq._inspect_hash_table())

    def test_build_hash_with_duplicates(self):
        eq = self._gc_module.EquivalenceTable([1, 2, 4, 0, 1, 4, 2, 4])
        self.assertEqual([
            (1, 1, 1, 4),
            (2, 2, 2, 6),
            (4, 4, 4, 5),
            (0, 0, 0, -1),
            (1, 1, 1, -1),
            (4, 4, 4, 7),
            (2, 2, 2, -1),
            (4, 4, 4, -1),
            ], eq._inspect_left_lines())
        # (hash_offset, head_offset_in_lines, count)
        self.assertEqual((8192, [
            (0, 3, 1),
            (1, 0, 2),
            (2, 1, 2),
            (4, 2, 3),
            ]), eq._inspect_hash_table())

    def test_build_hash_table_with_wraparound(self):
        eq = self._gc_module.EquivalenceTable([1, 2+8192])
        self.assertEqual([
            (1, 1, 1, -1),
            (8194, 8194, 2, -1),
            ], eq._inspect_left_lines())
        self.assertEqual((8192, [
            (1, 0, 1),
            (2, 1, 1),
            ]), eq._inspect_hash_table())

    def test_build_hash_table_with_collisions(self):
        # We build up backwards, so # 2+8192 will wrap around to 2, and take
        # its spot because the 2 offset is taken, then the real '2' will get
        # bumped to 3, which will bump 3 into 4.  then when we have 5, it will
        # be fine, but the 8192+5 will get bumped to 6
        eq = self._gc_module.EquivalenceTable([1, 5+8192, 5, 3, 2, 2+8192])
        self.assertEqual([
            (1, 1, 1, -1),
            (8197, 8197, 6, -1),
            (5, 5, 5, -1),
            (3, 3, 4, -1),
            (2, 2, 3, -1),
            (8194, 8194, 2, -1),
            ], eq._inspect_left_lines())
        self.assertEqual((8192, [
            (1, 0, 1),
            (2, 5, 1),
            (3, 4, 1),
            (4, 3, 1),
            (5, 2, 1),
            (6, 1, 1),
            ]), eq._inspect_hash_table())

    def test_build_hash_table_with_wrapped_collisions(self):
        eq = self._gc_module.EquivalenceTable([0, 8191+8192, 8191])
        self.assertEqual([
            (0, 0, 1, -1),
            (16383, 16383, 0, -1),
            (8191, 8191, 8191, -1),
            ], eq._inspect_left_lines())
        self.assertEqual((8192, [
            (0, 1, 1),
            (1, 0, 1),
            (8191, 2, 1),
            ]), eq._inspect_hash_table())

    def test_build_hash_table_with_strings(self):
        eq = self._gc_module.EquivalenceTable(['a', 'b', 'c', 'b'])
        self.assertEqual([
            ('a', hash('a'), hash('a') & 8191, -1),
            ('b', hash('b'), hash('b') & 8191, 3),
            ('c', hash('c'), hash('c') & 8191, -1),
            ('b', hash('b'), hash('b') & 8191, -1),
            ], eq._inspect_left_lines())
        self.assertEqual((8192, sorted([
            (hash('a') & 8191, 0, 1),
            (hash('b') & 8191, 1, 2),
            (hash('c') & 8191, 2, 1),
            ])), eq._inspect_hash_table())

    def test_with_unhashable(self):
        self.assertRaises(TypeError, self._gc_module.EquivalenceTable,
                [['unhashable', 'list'], 'foo'])
        self.assertRaises(TypeError, self._gc_module.EquivalenceTable,
                ('foo', ['unhashable', 'list']))

    def test_extend_lines(self):
        eq = self._gc_module.EquivalenceTable([10, 20, 30, 20])
        eq.extend_lines([30, 20, 40], [True, True, True])
        self.assertEqual([
            (10, 10, 10, -1),
            (20, 20, 20, 3),
            (30, 30, 30, 4),
            (20, 20, 20, 5),
            (30, 30, 30, -1),
            (20, 20, 20, -1),
            (40, 40, 40, -1),
            ], eq._inspect_left_lines())
        # (hash_offset, head_offset_in_lines, count)
        self.assertEqual((8192, [
            (10, 0, 1),
            (20, 1, 3),
            (30, 2, 2),
            (40, 6, 1),
            ]), eq._inspect_hash_table())

    def test_extend_lines_ignored(self):
        eq = self._gc_module.EquivalenceTable([10, 20, 30, 20])
        eq.extend_lines([30, 20, 40], [True, False, False])
        self.assertEqual([
            (10, 10, 10, -1),
            (20, 20, 20, 3),
            (30, 30, 30, 4),
            (20, 20, 20, -1),
            (30, 30, 30, -1),
            (20, 20, -1, -1),
            (40, 40, -1, -1),
            ], eq._inspect_left_lines())
        # (hash_offset, head_offset_in_lines, count)
        self.assertEqual((8192, [
            (10, 0, 1),
            (20, 1, 2),
            (30, 2, 2),
            ]), eq._inspect_hash_table())


class TestGetLongestMatch(tests.TestCase):

    def setUp(self):
        super(TestGetLongestMatch, self).setUp()
        self._longest_match = groupcompress._get_longest_match
        self._eq_class = groupcompress.GroupCompressor._equivalence_table_class

    def assertLongestMatch(self, block, end_pos, matching_locs,
                           eq, start_pos, max_len, known_locs):
        """Check that _get_longest_match gives correct results."""
        the_block, the_end_pos, next_locs = self._longest_match(eq,
                                                start_pos, max_len, known_locs)
        self.assertEqual(block, the_block)
        self.assertEqual(end_pos, the_end_pos)
        if next_locs is not None:
            self.assertEqual(matching_locs, next_locs)

    def test_all_match(self):
        eq = self._eq_class(['a', 'b', 'c'])
        eq.set_right_lines(['a', 'b', 'c'])
        self.assertLongestMatch((0, 0, 3), 3, None,
                                eq, 0, 3, None)
        self.assertLongestMatch((0, 0, 3), 3, None,
                                 eq, 0, 3, [0])
        self.assertLongestMatch((1, 1, 2), 3, None,
                                eq, 1, 3, None)
        self.assertLongestMatch((1, 1, 2), 3, None,
                                eq, 1, 3, [1])

    def test_no_match(self):
        eq = self._eq_class(['a', 'b', 'c'])
        eq.set_right_lines(['d', 'e', 'f'])
        self.assertLongestMatch(None, 1, None,
                                eq, 0, 3, None)
        self.assertLongestMatch(None, 2, None,
                                eq, 1, 3, None)
        self.assertLongestMatch(None, 3, None,
                                eq, 2, 3, None)

    def test_next_match(self):
        eq = self._eq_class(['a', 'b', 'c'])
        eq.set_right_lines(['a', 'c'])
        self.assertLongestMatch((0, 0, 1), 1, [2],
                                eq, 0, 2, None)
        self.assertLongestMatch((2, 1, 1), 2, None,
                                eq, 1, 2, None)

    def test_lots_of_matches(self):
        eq = self._eq_class(['a']*1000)
        eq.set_right_lines(['a']*1000)
        self.assertLongestMatch((0, 0, 1000), 1000, None,
                                eq, 0, 1000, None)
        eq = self._eq_class(['a']*1000)
        eq.set_right_lines(['a']*2000)
        self.assertLongestMatch((0, 0, 1000), 1000, range(1000),
                                eq, 0, 2000, None)
        eq = self._eq_class(['a']*2000)
        eq.set_right_lines(['a']*1000)
        self.assertLongestMatch((0, 0, 1000), 1000, None,
                                eq, 0, 1000, None)


class TestCompiledGetLongestMatch(TestGetLongestMatch):

    _tests_need_features = [CompiledGroupCompress]

    def setUp(self):
        super(TestGetLongestMatch, self).setUp()
        from bzrlib.plugins.groupcompress import _groupcompress_c
        self._longest_match = _groupcompress_c._get_longest_match
        self._eq_class = _groupcompress_c.EquivalenceTable

