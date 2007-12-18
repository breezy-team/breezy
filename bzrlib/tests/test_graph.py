# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib import (
    errors,
    graph as _mod_graph,
    tests,
    )
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCaseWithMemoryTransport


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
ancestry_1 = {'rev1': [NULL_REVISION], 'rev2a': ['rev1'], 'rev2b': ['rev1'],
              'rev3': ['rev2a'], 'rev4': ['rev3', 'rev2b']}


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
ancestry_2 = {'rev1a': [NULL_REVISION], 'rev2a': ['rev1a'],
              'rev1b': [NULL_REVISION], 'rev3a': ['rev2a'], 'rev4a': ['rev3a']}


# Criss cross ancestry
#
#     NULL_REVISION
#         |
#        rev1
#        /  \
#    rev2a  rev2b
#       |\  /|
#       |  X |
#       |/  \|
#    rev3a  rev3b
criss_cross = {'rev1': [NULL_REVISION], 'rev2a': ['rev1'], 'rev2b': ['rev1'],
               'rev3a': ['rev2a', 'rev2b'], 'rev3b': ['rev2b', 'rev2a']}


# Criss-cross 2
#
#  NULL_REVISION
#    /   \
# rev1a  rev1b
#   |\   /|
#   | \ / |
#   |  X  |
#   | / \ |
#   |/   \|
# rev2a  rev2b
criss_cross2 = {'rev1a': [NULL_REVISION], 'rev1b': [NULL_REVISION],
                'rev2a': ['rev1a', 'rev1b'], 'rev2b': ['rev1b', 'rev1a']}


# Mainline:
#
#  NULL_REVISION
#       |
#      rev1
#      /  \
#      | rev2b
#      |  /
#     rev2a
mainline = {'rev1': [NULL_REVISION], 'rev2a': ['rev1', 'rev2b'],
            'rev2b': ['rev1']}


# feature branch:
#
#  NULL_REVISION
#       |
#      rev1
#       |
#     rev2b
#       |
#     rev3b
feature_branch = {'rev1': [NULL_REVISION],
                  'rev2b': ['rev1'], 'rev3b': ['rev2b']}


# History shortcut
#  NULL_REVISION
#       |
#     rev1------
#     /  \      \
#  rev2a rev2b rev2c
#    |  /   \   /
#  rev3a    rev3b
history_shortcut = {'rev1': [NULL_REVISION], 'rev2a': ['rev1'],
                    'rev2b': ['rev1'], 'rev2c': ['rev1'],
                    'rev3a': ['rev2a', 'rev2b'], 'rev3b': ['rev2b', 'rev2c']}

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
extended_history_shortcut = {'a': [NULL_REVISION],
                             'b': ['a'],
                             'c': ['b'],
                             'd': ['c'],
                             'e': ['d'],
                             'f': ['a', 'd'],
                            }

# Double shortcut
# Both sides will see 'A' first, even though it is actually a decendent of a
# different common revision.
#
#  NULL_REVISION
#       |
#       a
#      /|\
#     / b \
#    /  |  \
#   |   c   |
#   |  / \  |
#   | d   e |
#   |/     \|
#   f       g

double_shortcut = {'a':[NULL_REVISION], 'b':['a'], 'c':['b'],
                   'd':['c'], 'e':['c'], 'f':['a', 'd'],
                   'g':['a', 'e']}

# Complex shortcut
# This has a failure mode in that a shortcut will find some nodes in common,
# but the common searcher won't have time to find that one branch is actually
# in common. The extra nodes at the top are because we want to avoid
# walking off the graph. Specifically, node G should be considered common, but
# is likely to be seen by M long before the common searcher finds it.
#
# NULL_REVISION
#     |
#     a
#     |
#     b
#     |
#     c
#     |
#     d
#     |\
#     e f
#     | |\
#     i | h
#     |\| |
#     | g |
#     | | |
#     | j |
#     | | |
#     | k |
#     | | |
#     | l |
#     |/|/
#     m n
complex_shortcut = {'d':[NULL_REVISION],
                    'x':['d'], 'y':['x'],
                    'e':['y'], 'f':['d'], 'g':['f', 'i'], 'h':['f'],
                    'i':['e'], 'j':['g'], 'k':['j'],
                    'l':['k'], 'm':['i', 's'], 'n':['s', 'h'],
                    'o':['l'], 'p':['o'], 'q':['p'],
                    'r':['q'], 's':['r'],
                    }

# Shortcut with extra root
# We have a long history shortcut, and an extra root, which is why we can't
# stop searchers based on seeing NULL_REVISION
#  NULL_REVISION
#       |   |
#       a   |
#       |\  |
#       b | |
#       | | |
#       c | |
#       | | |
#       d | g
#       |\|/
#       e f
shortcut_extra_root = {'a': [NULL_REVISION],
                       'b': ['a'],
                       'c': ['b'],
                       'd': ['c'],
                       'e': ['d'],
                       'f': ['a', 'd', 'g'],
                       'g': [NULL_REVISION],
                      }

#  NULL_REVISION
#       |
#       f
#       |
#       e
#      / \
#     b   d
#     | \ |
#     a   c

boundary = {'a': ['b'], 'c': ['b', 'd'], 'b':['e'], 'd':['e'], 'e': ['f'],
            'f':[NULL_REVISION]}


class InstrumentedParentsProvider(object):

    def __init__(self, parents_provider):
        self.calls = []
        self._real_parents_provider = parents_provider

    def get_parents(self, nodes):
        self.calls.extend(nodes)
        return self._real_parents_provider.get_parents(nodes)

    def get_parent_map(self, nodes):
        self.calls.extend(nodes)
        return self._real_parents_provider.get_parent_map(nodes)


class TestGraph(TestCaseWithMemoryTransport):

    def make_graph(self, ancestors):
        # XXX: This seems valid, is there a reason to actually create a
        # repository and put things in it?
        return _mod_graph.Graph(_mod_graph.DictParentsProvider(ancestors))
        tree = self.prepare_memory_tree('.')
        self.build_ancestry(tree, ancestors)
        self.addCleanup(tree.unlock)
        return tree.branch.repository.get_graph()

    def prepare_memory_tree(self, location):
        tree = self.make_branch_and_memory_tree(location)
        tree.lock_write()
        tree.add('.')
        return tree

    def build_ancestry(self, tree, ancestors):
        """Create an ancestry as specified by a graph dict

        :param tree: A tree to use
        :param ancestors: a dict of {node: [node_parent, ...]}
        """
        pending = [NULL_REVISION]
        descendants = {}
        for descendant, parents in ancestors.iteritems():
            for parent in parents:
                descendants.setdefault(parent, []).append(descendant)
        while len(pending) > 0:
            cur_node = pending.pop()
            for descendant in descendants.get(cur_node, []):
                if tree.branch.repository.has_revision(descendant):
                    continue
                parents = [p for p in ancestors[descendant] if p is not
                           NULL_REVISION]
                if len([p for p in parents if not
                    tree.branch.repository.has_revision(p)]) > 0:
                    continue
                tree.set_parent_ids(parents)
                if len(parents) > 0:
                    left_parent = parents[0]
                else:
                    left_parent = NULL_REVISION
                tree.branch.set_last_revision_info(
                    len(tree.branch._lefthand_history(left_parent)),
                    left_parent)
                tree.commit(descendant, rev_id=descendant)
                pending.append(descendant)

    def test_lca(self):
        """Test finding least common ancestor.

        ancestry_1 should always have a single common ancestor
        """
        graph = self.make_graph(ancestry_1)
        self.assertRaises(errors.InvalidRevisionId, graph.find_lca, None)
        self.assertEqual(set([NULL_REVISION]),
                         graph.find_lca(NULL_REVISION, NULL_REVISION))
        self.assertEqual(set([NULL_REVISION]),
                         graph.find_lca(NULL_REVISION, 'rev1'))
        self.assertEqual(set(['rev1']), graph.find_lca('rev1', 'rev1'))
        self.assertEqual(set(['rev1']), graph.find_lca('rev2a', 'rev2b'))

    def test_no_unique_lca(self):
        """Test error when one revision is not in the graph"""
        graph = self.make_graph(ancestry_1)
        self.assertRaises(errors.NoCommonAncestor, graph.find_unique_lca,
                          'rev1', '1rev')

    def test_lca_criss_cross(self):
        """Test least-common-ancestor after a criss-cross merge."""
        graph = self.make_graph(criss_cross)
        self.assertEqual(set(['rev2a', 'rev2b']),
                         graph.find_lca('rev3a', 'rev3b'))
        self.assertEqual(set(['rev2b']),
                         graph.find_lca('rev3a', 'rev3b', 'rev2b'))

    def test_lca_shortcut(self):
        """Test least-common ancestor on this history shortcut"""
        graph = self.make_graph(history_shortcut)
        self.assertEqual(set(['rev2b']), graph.find_lca('rev3a', 'rev3b'))

    def test_recursive_unique_lca(self):
        """Test finding a unique least common ancestor.

        ancestry_1 should always have a single common ancestor
        """
        graph = self.make_graph(ancestry_1)
        self.assertEqual(NULL_REVISION,
                         graph.find_unique_lca(NULL_REVISION, NULL_REVISION))
        self.assertEqual(NULL_REVISION,
                         graph.find_unique_lca(NULL_REVISION, 'rev1'))
        self.assertEqual('rev1', graph.find_unique_lca('rev1', 'rev1'))
        self.assertEqual('rev1', graph.find_unique_lca('rev2a', 'rev2b'))
        self.assertEqual(('rev1', 1,),
                         graph.find_unique_lca('rev2a', 'rev2b',
                         count_steps=True))

    def test_unique_lca_criss_cross(self):
        """Ensure we don't pick non-unique lcas in a criss-cross"""
        graph = self.make_graph(criss_cross)
        self.assertEqual('rev1', graph.find_unique_lca('rev3a', 'rev3b'))
        lca, steps = graph.find_unique_lca('rev3a', 'rev3b', count_steps=True)
        self.assertEqual('rev1', lca)
        self.assertEqual(2, steps)

    def test_unique_lca_null_revision(self):
        """Ensure we pick NULL_REVISION when necessary"""
        graph = self.make_graph(criss_cross2)
        self.assertEqual('rev1b', graph.find_unique_lca('rev2a', 'rev1b'))
        self.assertEqual(NULL_REVISION,
                         graph.find_unique_lca('rev2a', 'rev2b'))

    def test_unique_lca_null_revision2(self):
        """Ensure we pick NULL_REVISION when necessary"""
        graph = self.make_graph(ancestry_2)
        self.assertEqual(NULL_REVISION,
                         graph.find_unique_lca('rev4a', 'rev1b'))

    def test_lca_double_shortcut(self):
        graph = self.make_graph(double_shortcut)
        self.assertEqual('c', graph.find_unique_lca('f', 'g'))

    def test_common_ancestor_two_repos(self):
        """Ensure we do unique_lca using data from two repos"""
        mainline_tree = self.prepare_memory_tree('mainline')
        self.build_ancestry(mainline_tree, mainline)
        self.addCleanup(mainline_tree.unlock)

        # This is cheating, because the revisions in the graph are actually
        # different revisions, despite having the same revision-id.
        feature_tree = self.prepare_memory_tree('feature')
        self.build_ancestry(feature_tree, feature_branch)
        self.addCleanup(feature_tree.unlock)

        graph = mainline_tree.branch.repository.get_graph(
            feature_tree.branch.repository)
        self.assertEqual('rev2b', graph.find_unique_lca('rev2a', 'rev3b'))

    def test_graph_difference(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual((set(), set()), graph.find_difference('rev1', 'rev1'))
        self.assertEqual((set(), set(['rev1'])),
                         graph.find_difference(NULL_REVISION, 'rev1'))
        self.assertEqual((set(['rev1']), set()),
                         graph.find_difference('rev1', NULL_REVISION))
        self.assertEqual((set(['rev2a', 'rev3']), set(['rev2b'])),
                         graph.find_difference('rev3', 'rev2b'))
        self.assertEqual((set(['rev4', 'rev3', 'rev2a']), set()),
                         graph.find_difference('rev4', 'rev2b'))

    def test_graph_difference_separate_ancestry(self):
        graph = self.make_graph(ancestry_2)
        self.assertEqual((set(['rev1a']), set(['rev1b'])),
                         graph.find_difference('rev1a', 'rev1b'))
        self.assertEqual((set(['rev1a', 'rev2a', 'rev3a', 'rev4a']),
                          set(['rev1b'])),
                         graph.find_difference('rev4a', 'rev1b'))

    def test_graph_difference_criss_cross(self):
        graph = self.make_graph(criss_cross)
        self.assertEqual((set(['rev3a']), set(['rev3b'])),
                         graph.find_difference('rev3a', 'rev3b'))
        self.assertEqual((set([]), set(['rev3b', 'rev2b'])),
                         graph.find_difference('rev2a', 'rev3b'))

    def test_graph_difference_extended_history(self):
        graph = self.make_graph(extended_history_shortcut)
        self.expectFailure('find_difference cannot handle shortcuts',
            self.assertEqual, (set(['e']), set(['f'])),
                graph.find_difference('e', 'f'))
        self.assertEqual((set(['e']), set(['f'])),
                         graph.find_difference('e', 'f'))
        self.assertEqual((set(['f']), set(['e'])),
                         graph.find_difference('f', 'e'))

    def test_graph_difference_double_shortcut(self):
        graph = self.make_graph(double_shortcut)
        self.assertEqual((set(['d', 'f']), set(['e', 'g'])),
                         graph.find_difference('f', 'g'))

    def test_graph_difference_complex_shortcut(self):
        graph = self.make_graph(complex_shortcut)
        self.expectFailure('find_difference cannot handle shortcuts',
            self.assertEqual, (set(['m']), set(['h', 'n'])),
                graph.find_difference('m', 'n'))
        self.assertEqual((set(['m']), set(['h', 'n'])),
                         graph.find_difference('m', 'n'))

    def test_graph_difference_shortcut_extra_root(self):
        graph = self.make_graph(shortcut_extra_root)
        self.expectFailure('find_difference cannot handle shortcuts',
            self.assertEqual, (set(['e']), set(['f', 'g'])),
                graph.find_difference('e', 'f'))
        self.assertEqual((set(['e']), set(['f', 'g'])),
                         graph.find_difference('e', 'f'))

    def test_stacked_parents_provider(self):

        parents1 = _mod_graph.DictParentsProvider({'rev2': ['rev3']})
        parents2 = _mod_graph.DictParentsProvider({'rev1': ['rev4']})
        stacked = _mod_graph._StackedParentsProvider([parents1, parents2])
        self.assertEqual([['rev4',], ['rev3']],
                         stacked.get_parents(['rev1', 'rev2']))
        self.assertEqual([['rev3',], ['rev4']],
                         stacked.get_parents(['rev2', 'rev1']))
        self.assertEqual([['rev3',], ['rev3']],
                         stacked.get_parents(['rev2', 'rev2']))
        self.assertEqual([['rev4',], ['rev4']],
                         stacked.get_parents(['rev1', 'rev1']))

    def test_iter_topo_order(self):
        graph = self.make_graph(ancestry_1)
        args = ['rev2a', 'rev3', 'rev1']
        topo_args = list(graph.iter_topo_order(args))
        self.assertEqual(set(args), set(topo_args))
        self.assertTrue(topo_args.index('rev2a') > topo_args.index('rev1'))
        self.assertTrue(topo_args.index('rev2a') < topo_args.index('rev3'))

    def test_is_ancestor(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual(True, graph.is_ancestor('null:', 'null:'))
        self.assertEqual(True, graph.is_ancestor('null:', 'rev1'))
        self.assertEqual(False, graph.is_ancestor('rev1', 'null:'))
        self.assertEqual(True, graph.is_ancestor('null:', 'rev4'))
        self.assertEqual(False, graph.is_ancestor('rev4', 'null:'))
        self.assertEqual(False, graph.is_ancestor('rev4', 'rev2b'))
        self.assertEqual(True, graph.is_ancestor('rev2b', 'rev4'))
        self.assertEqual(False, graph.is_ancestor('rev2b', 'rev3'))
        self.assertEqual(False, graph.is_ancestor('rev3', 'rev2b'))
        instrumented_provider = InstrumentedParentsProvider(graph)
        instrumented_graph = _mod_graph.Graph(instrumented_provider)
        instrumented_graph.is_ancestor('rev2a', 'rev2b')
        self.assertTrue('null:' not in instrumented_provider.calls)

    def test_is_ancestor_boundary(self):
        """Ensure that we avoid searching the whole graph.
        
        This requires searching through b as a common ancestor, so we
        can identify that e is common.
        """
        graph = self.make_graph(boundary)
        instrumented_provider = InstrumentedParentsProvider(graph)
        graph = _mod_graph.Graph(instrumented_provider)
        self.assertFalse(graph.is_ancestor('a', 'c'))
        self.assertTrue('null:' not in instrumented_provider.calls)

    def test_filter_candidate_lca(self):
        """Test filter_candidate_lca for a corner case

        This tests the case where we encounter the end of iteration for 'e'
        in the same pass as we discover that 'd' is an ancestor of 'e', and
        therefore 'e' can't be an lca.

        To compensate for different dict orderings on other Python
        implementations, we mirror 'd' and 'e' with 'b' and 'a'.
        """
        # This test is sensitive to the iteration order of dicts.  It will
        # pass incorrectly if 'e' and 'a' sort before 'c'
        #
        # NULL_REVISION
        #     / \
        #    a   e
        #    |   |
        #    b   d
        #     \ /
        #      c
        graph = self.make_graph({'c': ['b', 'd'], 'd': ['e'], 'b': ['a'],
                                 'a': [NULL_REVISION], 'e': [NULL_REVISION]})
        self.assertEqual(set(['c']), graph.heads(['a', 'c', 'e']))

    def test_heads_null(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual(set(['null:']), graph.heads(['null:']))
        self.assertEqual(set(['rev1']), graph.heads(['null:', 'rev1']))
        self.assertEqual(set(['rev1']), graph.heads(['rev1', 'null:']))
        self.assertEqual(set(['rev1']), graph.heads(set(['rev1', 'null:'])))
        self.assertEqual(set(['rev1']), graph.heads(('rev1', 'null:')))

    def test_heads_one(self):
        # A single node will always be a head
        graph = self.make_graph(ancestry_1)
        self.assertEqual(set(['null:']), graph.heads(['null:']))
        self.assertEqual(set(['rev1']), graph.heads(['rev1']))
        self.assertEqual(set(['rev2a']), graph.heads(['rev2a']))
        self.assertEqual(set(['rev2b']), graph.heads(['rev2b']))
        self.assertEqual(set(['rev3']), graph.heads(['rev3']))
        self.assertEqual(set(['rev4']), graph.heads(['rev4']))

    def test_heads_single(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual(set(['rev4']), graph.heads(['null:', 'rev4']))
        self.assertEqual(set(['rev2a']), graph.heads(['rev1', 'rev2a']))
        self.assertEqual(set(['rev2b']), graph.heads(['rev1', 'rev2b']))
        self.assertEqual(set(['rev3']), graph.heads(['rev1', 'rev3']))
        self.assertEqual(set(['rev4']), graph.heads(['rev1', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev2a', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev2b', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev3', 'rev4']))

    def test_heads_two_heads(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual(set(['rev2a', 'rev2b']),
                         graph.heads(['rev2a', 'rev2b']))
        self.assertEqual(set(['rev3', 'rev2b']),
                         graph.heads(['rev3', 'rev2b']))

    def test_heads_criss_cross(self):
        graph = self.make_graph(criss_cross)
        self.assertEqual(set(['rev2a']),
                         graph.heads(['rev2a', 'rev1']))
        self.assertEqual(set(['rev2b']),
                         graph.heads(['rev2b', 'rev1']))
        self.assertEqual(set(['rev3a']),
                         graph.heads(['rev3a', 'rev1']))
        self.assertEqual(set(['rev3b']),
                         graph.heads(['rev3b', 'rev1']))
        self.assertEqual(set(['rev2a', 'rev2b']),
                         graph.heads(['rev2a', 'rev2b']))
        self.assertEqual(set(['rev3a']),
                         graph.heads(['rev3a', 'rev2a']))
        self.assertEqual(set(['rev3a']),
                         graph.heads(['rev3a', 'rev2b']))
        self.assertEqual(set(['rev3a']),
                         graph.heads(['rev3a', 'rev2a', 'rev2b']))
        self.assertEqual(set(['rev3b']),
                         graph.heads(['rev3b', 'rev2a']))
        self.assertEqual(set(['rev3b']),
                         graph.heads(['rev3b', 'rev2b']))
        self.assertEqual(set(['rev3b']),
                         graph.heads(['rev3b', 'rev2a', 'rev2b']))
        self.assertEqual(set(['rev3a', 'rev3b']),
                         graph.heads(['rev3a', 'rev3b']))
        self.assertEqual(set(['rev3a', 'rev3b']),
                         graph.heads(['rev3a', 'rev3b', 'rev2a', 'rev2b']))

    def test_heads_shortcut(self):
        graph = self.make_graph(history_shortcut)

        self.assertEqual(set(['rev2a', 'rev2b', 'rev2c']),
                         graph.heads(['rev2a', 'rev2b', 'rev2c']))
        self.assertEqual(set(['rev3a', 'rev3b']),
                         graph.heads(['rev3a', 'rev3b']))
        self.assertEqual(set(['rev3a', 'rev3b']),
                         graph.heads(['rev2a', 'rev3a', 'rev3b']))
        self.assertEqual(set(['rev2a', 'rev3b']),
                         graph.heads(['rev2a', 'rev3b']))
        self.assertEqual(set(['rev2c', 'rev3a']),
                         graph.heads(['rev2c', 'rev3a']))

    def _run_heads_break_deeper(self, graph_dict, search):
        """Run heads on a graph-as-a-dict.
        
        If the search asks for the parents of 'deeper' the test will fail.
        """
        class stub(object):
            pass
        def get_parents(keys):
            result = []
            for key in keys:
                if key == 'deeper':
                    self.fail('key deeper was accessed')
                result.append(graph_dict[key])
            return result
        def get_parent_map(keys):
            result = {}
            for key in keys:
                if key == 'deeper':
                    self.fail('key deeper was accessed')
                result[key] = graph_dict[key]
            return result
        an_obj = stub()
        an_obj.get_parents = get_parents
        an_obj.get_parent_map = get_parent_map
        graph = _mod_graph.Graph(an_obj)
        return graph.heads(search)

    def test_heads_limits_search(self):
        # test that a heads query does not search all of history
        graph_dict = {
            'left':['common'],
            'right':['common'],
            'common':['deeper'],
        }
        self.assertEqual(set(['left', 'right']),
            self._run_heads_break_deeper(graph_dict, ['left', 'right']))

    def test_heads_limits_search_assymetric(self):
        # test that a heads query does not search all of history
        graph_dict = {
            'left':['midleft'],
            'midleft':['common'],
            'right':['common'],
            'common':['aftercommon'],
            'aftercommon':['deeper'],
        }
        self.assertEqual(set(['left', 'right']),
            self._run_heads_break_deeper(graph_dict, ['left', 'right']))

    def test_heads_limits_search_common_search_must_continue(self):
        # test that common nodes are still queried, preventing
        # all-the-way-to-origin behaviour in the following graph:
        graph_dict = {
            'h1':['shortcut', 'common1'],
            'h2':['common1'],
            'shortcut':['common2'],
            'common1':['common2'],
            'common2':['deeper'],
        }
        self.assertEqual(set(['h1', 'h2']),
            self._run_heads_break_deeper(graph_dict, ['h1', 'h2']))


class TestCachingParentsProvider(tests.TestCase):

    def setUp(self):
        super(TestCachingParentsProvider, self).setUp()
        dict_pp = _mod_graph.DictParentsProvider({'a':('b',)})
        self.inst_pp = InstrumentedParentsProvider(dict_pp)
        self.caching_pp = _mod_graph.CachingParentsProvider(self.inst_pp)

    def test_get_parents(self):
        """Requesting the same revision should be returned from cache"""
        self.assertEqual({}, self.caching_pp._cache)
        self.assertEqual([('b',)], self.caching_pp.get_parents(['a']))
        self.assertEqual(['a'], self.inst_pp.calls)
        self.assertEqual([('b',)], self.caching_pp.get_parents(['a']))
        # No new call, as it should have been returned from the cache
        self.assertEqual(['a'], self.inst_pp.calls)
        self.assertEqual({'a':('b',)}, self.caching_pp._cache)

    def test_get_parents_not_present(self):
        """The cache should also track when a revision doesn't exist"""
        self.assertEqual([None], self.caching_pp.get_parents(['b']))
        self.assertEqual(['b'], self.inst_pp.calls)
        self.assertEqual([None], self.caching_pp.get_parents(['b']))
        # No new calls
        self.assertEqual(['b'], self.inst_pp.calls)
        self.assertEqual({'b':None}, self.caching_pp._cache)

    def test_get_parents_mixed(self):
        """Anything that can be returned from cache, should be"""
        self.assertEqual([None], self.caching_pp.get_parents(['b']))
        self.assertEqual(['b'], self.inst_pp.calls)
        self.assertEqual([('b',), None],
                         self.caching_pp.get_parents(['a', 'b']))
        self.assertEqual(['b', 'a'], self.inst_pp.calls)

    def test_get_parents_repeated(self):
        """Asking for the same parent 2x will only forward 1 request."""
        self.assertEqual([None, ('b',), None],
                         self.caching_pp.get_parents(['b', 'a', 'b']))
        # Use sorted because we don't care about the order, just that each is
        # only present 1 time.
        self.assertEqual(['a', 'b'], sorted(self.inst_pp.calls))
