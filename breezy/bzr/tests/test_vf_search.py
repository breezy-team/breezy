# Copyright (C) 2007-2011 Canonical Ltd
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

from ... import (
    graph as _mod_graph,
    tests,
    )
from .. import (
    vf_search,
    )
from ...revision import NULL_REVISION
from ...tests.test_graph import TestGraphBase

# Ancestry 1:
#
#  NULL_REVISION
#       |
#     rev1
#      /\
#  rev2a rev2b
#     |    |
#   rev3  /
#     |  /
#   rev4
ancestry_1 = {b'rev1': [NULL_REVISION],
              b'rev2a': [b'rev1'],
              b'rev2b': [b'rev1'],
              b'rev3': [b'rev2a'],
              b'rev4': [b'rev3', b'rev2b']}

# Ancestry 2:
#
#  NULL_REVISION
#    /    \
# rev1a  rev1b
#   |
# rev2a
#   |
# rev3a
#   |
# rev4a
ancestry_2 = {b'rev1a': [NULL_REVISION],
              b'rev2a': [b'rev1a'],
              b'rev1b': [NULL_REVISION],
              b'rev3a': [b'rev2a'],
              b'rev4a': [b'rev3a']}


# Extended history shortcut
#  NULL_REVISION
#       |
#       a
#       |\
#       b |
#       | |
#       c |
#       | |
#       d |
#       |\|
#       e f
extended_history_shortcut = {b'a': [NULL_REVISION],
                             b'b': [b'a'],
                             b'c': [b'b'],
                             b'd': [b'c'],
                             b'e': [b'd'],
                             b'f': [b'a', b'd'],
                             }


class TestSearchResultRefine(tests.TestCase):

    def make_graph(self, ancestors):
        return _mod_graph.Graph(_mod_graph.DictParentsProvider(ancestors))

    def test_refine(self):
        # Used when pulling from a stacked repository, so test some revisions
        # being satisfied from the stacking branch.
        self.make_graph(
            {b"tip": [b"mid"], b"mid": [b"base"], b"tag": [b"base"],
             b"base": [NULL_REVISION], NULL_REVISION: []})
        result = vf_search.SearchResult(
            {b'tip', b'tag'},
            {NULL_REVISION}, 4, {b'tip', b'mid', b'tag', b'base'})
        result = result.refine({b'tip'}, {b'mid'})
        recipe = result.get_recipe()
        # We should be starting from tag (original head) and mid (seen ref)
        self.assertEqual({b'mid', b'tag'}, recipe[1])
        # We should be stopping at NULL (original stop) and tip (seen head)
        self.assertEqual({NULL_REVISION, b'tip'}, recipe[2])
        self.assertEqual(3, recipe[3])
        result = result.refine({b'mid', b'tag', b'base'},
                               {NULL_REVISION})
        recipe = result.get_recipe()
        # We should be starting from nothing (NULL was known as a cut point)
        self.assertEqual(set([]), recipe[1])
        # We should be stopping at NULL (original stop) and tip (seen head) and
        # tag (seen head) and mid(seen mid-point head). We could come back and
        # define this as not including mid, for minimal results, but it is
        # still 'correct' to include mid, and simpler/easier.
        self.assertEqual({NULL_REVISION, b'tip', b'tag', b'mid'}, recipe[2])
        self.assertEqual(0, recipe[3])
        self.assertTrue(result.is_empty())


class TestSearchResultFromParentMap(TestGraphBase):

    def assertSearchResult(self, start_keys, stop_keys, key_count, parent_map,
                           missing_keys=()):
        (start, stop, count) = vf_search.search_result_from_parent_map(
            parent_map, missing_keys)
        self.assertEqual((sorted(start_keys), sorted(stop_keys), key_count),
                         (sorted(start), sorted(stop), count))

    def test_no_parents(self):
        self.assertSearchResult([], [], 0, {})
        self.assertSearchResult([], [], 0, None)

    def test_ancestry_1(self):
        self.assertSearchResult([b'rev4'], [NULL_REVISION], len(ancestry_1),
                                ancestry_1)

    def test_ancestry_2(self):
        self.assertSearchResult([b'rev1b', b'rev4a'], [NULL_REVISION],
                                len(ancestry_2), ancestry_2)
        self.assertSearchResult([b'rev1b', b'rev4a'], [],
                                len(ancestry_2) + 1, ancestry_2,
                                missing_keys=[NULL_REVISION])

    def test_partial_search(self):
        parent_map = dict((k, extended_history_shortcut[k])
                          for k in [b'e', b'f'])
        self.assertSearchResult([b'e', b'f'], [b'd', b'a'], 2,
                                parent_map)
        parent_map.update((k, extended_history_shortcut[k])
                          for k in [b'd', b'a'])
        self.assertSearchResult([b'e', b'f'], [b'c', NULL_REVISION], 4,
                                parent_map)
        parent_map[b'c'] = extended_history_shortcut[b'c']
        self.assertSearchResult([b'e', b'f'], [b'b'], 6,
                                parent_map, missing_keys=[NULL_REVISION])
        parent_map[b'b'] = extended_history_shortcut[b'b']
        self.assertSearchResult([b'e', b'f'], [], 7,
                                parent_map, missing_keys=[NULL_REVISION])


class TestLimitedSearchResultFromParentMap(TestGraphBase):

    def assertSearchResult(self, start_keys, stop_keys, key_count, parent_map,
                           missing_keys, tip_keys, depth):
        (start, stop, count) = vf_search.limited_search_result_from_parent_map(
            parent_map, missing_keys, tip_keys, depth)
        self.assertEqual((sorted(start_keys), sorted(stop_keys), key_count),
                         (sorted(start), sorted(stop), count))

    def test_empty_ancestry(self):
        self.assertSearchResult([], [], 0, {}, (), [b'tip-rev-id'], 10)

    def test_ancestry_1(self):
        self.assertSearchResult([b'rev4'], [b'rev1'], 4,
                                ancestry_1, (), [b'rev1'], 10)
        self.assertSearchResult([b'rev2a', b'rev2b'], [b'rev1'], 2,
                                ancestry_1, (), [b'rev1'], 1)

    def test_multiple_heads(self):
        self.assertSearchResult([b'e', b'f'], [b'a'], 5,
                                extended_history_shortcut, (), [b'a'], 10)
        # Note that even though we only take 1 step back, we find 'f', which
        # means the described search will still find d and c.
        self.assertSearchResult([b'f'], [b'a'], 4,
                                extended_history_shortcut, (), [b'a'], 1)
        self.assertSearchResult([b'f'], [b'a'], 4,
                                extended_history_shortcut, (), [b'a'], 2)


class TestPendingAncestryResultRefine(tests.TestCase):

    def make_graph(self, ancestors):
        return _mod_graph.Graph(_mod_graph.DictParentsProvider(ancestors))

    def test_refine(self):
        # Used when pulling from a stacked repository, so test some revisions
        # being satisfied from the stacking branch.
        g = self.make_graph(
            {b"tip": [b"mid"], b"mid": [b"base"], b"tag": [b"base"],
             b"base": [NULL_REVISION], NULL_REVISION: []})
        result = vf_search.PendingAncestryResult([b'tip', b'tag'], None)
        result = result.refine({b'tip'}, {b'mid'})
        self.assertEqual({b'mid', b'tag'}, result.heads)
        result = result.refine({b'mid', b'tag', b'base'},
                               {NULL_REVISION})
        self.assertEqual({NULL_REVISION}, result.heads)
        self.assertTrue(result.is_empty())


class TestPendingAncestryResultGetKeys(tests.TestCaseWithMemoryTransport):
    """Tests for breezy.graph.PendingAncestryResult."""

    def test_get_keys(self):
        builder = self.make_branch_builder('b')
        builder.start_series()
        builder.build_snapshot(None, [
            ('add', ('', b'root-id', 'directory', ''))],
            revision_id=b'rev-1')
        builder.build_snapshot([b'rev-1'], [], revision_id=b'rev-2')
        builder.finish_series()
        repo = builder.get_branch().repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        result = vf_search.PendingAncestryResult([b'rev-2'], repo)
        self.assertEqual({b'rev-1', b'rev-2'}, set(result.get_keys()))

    def test_get_keys_excludes_ghosts(self):
        builder = self.make_branch_builder('b')
        builder.start_series()
        builder.build_snapshot(None, [
            ('add', ('', b'root-id', 'directory', ''))],
            revision_id=b'rev-1')
        builder.build_snapshot([b'rev-1', b'ghost'], [], revision_id=b'rev-2')
        builder.finish_series()
        repo = builder.get_branch().repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        result = vf_search.PendingAncestryResult([b'rev-2'], repo)
        self.assertEqual(sorted([b'rev-1', b'rev-2']),
                         sorted(result.get_keys()))

    def test_get_keys_excludes_null(self):
        # Make a 'graph' with an iter_ancestry that returns NULL_REVISION
        # somewhere other than the last element, which can happen in real
        # ancestries.
        class StubGraph(object):
            def iter_ancestry(self, keys):
                return [(NULL_REVISION, ()), (b'foo', (NULL_REVISION,))]
        result = vf_search.PendingAncestryResult([b'rev-3'], None)
        result_keys = result._get_keys(StubGraph())
        # Only the non-null keys from the ancestry appear.
        self.assertEqual({b'foo'}, set(result_keys))
