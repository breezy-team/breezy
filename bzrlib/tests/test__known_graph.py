# Copyright (C) 2009 Canonical Ltd
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

"""Tests for the python and pyrex extensions of KnownGraph"""

from bzrlib import (
    errors,
    graph as _mod_graph,
    _known_graph_py,
    tests,
    )
from bzrlib.tests import test_graph
from bzrlib.revision import NULL_REVISION


def load_tests(standard_tests, module, loader):
    """Parameterize tests for all versions of groupcompress."""
    scenarios = [
        ('python', {'module': _known_graph_py, 'do_cache': True}),
    ]
    caching_scenarios = [
        ('python-nocache', {'module': _known_graph_py, 'do_cache': False}),
    ]
    suite = loader.suiteClass()
    if CompiledKnownGraphFeature.available():
        from bzrlib import _known_graph_pyx
        scenarios.append(('C', {'module': _known_graph_pyx, 'do_cache': True}))
        caching_scenarios.append(('C-nocache',
                          {'module': _known_graph_pyx, 'do_cache': False}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledKnownGraphFeature)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    # TestKnownGraphHeads needs to be permutated with and without caching.
    # All other TestKnownGraph tests only need to be tested across module
    heads_suite, other_suite = tests.split_suite_by_condition(
        standard_tests, tests.condition_isinstance(TestKnownGraphHeads))
    suite = tests.multiply_tests(other_suite, scenarios, suite)
    suite = tests.multiply_tests(heads_suite, scenarios + caching_scenarios,
                                 suite)
    return suite


class _CompiledKnownGraphFeature(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._known_graph_pyx
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._known_graph_pyx'

CompiledKnownGraphFeature = _CompiledKnownGraphFeature()


#  a
#  |\
#  b |
#  | |
#  c |
#   \|
#    d
alt_merge = {'a': [], 'b': ['a'], 'c': ['b'], 'd': ['a', 'c']}


class TestCaseWithKnownGraph(tests.TestCase):

    module = None # Set by load_tests

    def make_known_graph(self, ancestry):
        return self.module.KnownGraph(ancestry, do_cache=self.do_cache)


class TestKnownGraph(TestCaseWithKnownGraph):

    def assertGDFO(self, graph, rev, gdfo):
        node = graph._nodes[rev]
        self.assertEqual(gdfo, node.gdfo)

    def test_children_ancestry1(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(['rev1'], graph._nodes[NULL_REVISION].child_keys)
        self.assertEqual(['rev2a', 'rev2b'],
                         sorted(graph._nodes['rev1'].child_keys))
        self.assertEqual(['rev3'], sorted(graph._nodes['rev2a'].child_keys))
        self.assertEqual(['rev4'], sorted(graph._nodes['rev3'].child_keys))
        self.assertEqual(['rev4'], sorted(graph._nodes['rev2b'].child_keys))

    def test_gdfo_ancestry_1(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertGDFO(graph, 'rev1', 2)
        self.assertGDFO(graph, 'rev2b', 3)
        self.assertGDFO(graph, 'rev2a', 3)
        self.assertGDFO(graph, 'rev3', 4)
        self.assertGDFO(graph, 'rev4', 5)

    def test_gdfo_feature_branch(self):
        graph = self.make_known_graph(test_graph.feature_branch)
        self.assertGDFO(graph, 'rev1', 2)
        self.assertGDFO(graph, 'rev2b', 3)
        self.assertGDFO(graph, 'rev3b', 4)

    def test_gdfo_extended_history_shortcut(self):
        graph = self.make_known_graph(test_graph.extended_history_shortcut)
        self.assertGDFO(graph, 'a', 2)
        self.assertGDFO(graph, 'b', 3)
        self.assertGDFO(graph, 'c', 4)
        self.assertGDFO(graph, 'd', 5)
        self.assertGDFO(graph, 'e', 6)
        self.assertGDFO(graph, 'f', 6)

    def test_gdfo_with_ghost(self):
        graph = self.make_known_graph(test_graph.with_ghost)
        self.assertGDFO(graph, 'f', 2)
        self.assertGDFO(graph, 'e', 3)
        self.assertGDFO(graph, 'g', 1)
        self.assertGDFO(graph, 'b', 4)
        self.assertGDFO(graph, 'd', 4)
        self.assertGDFO(graph, 'a', 5)
        self.assertGDFO(graph, 'c', 5)


class TestKnownGraphHeads(TestCaseWithKnownGraph):

    do_cache = None # Set by load_tests

    def test_heads_null(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(set(['null:']), graph.heads(['null:']))
        self.assertEqual(set(['rev1']), graph.heads(['null:', 'rev1']))
        self.assertEqual(set(['rev1']), graph.heads(['rev1', 'null:']))
        self.assertEqual(set(['rev1']), graph.heads(set(['rev1', 'null:'])))
        self.assertEqual(set(['rev1']), graph.heads(('rev1', 'null:')))

    def test_heads_one(self):
        # A single node will always be a head
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(set(['null:']), graph.heads(['null:']))
        self.assertEqual(set(['rev1']), graph.heads(['rev1']))
        self.assertEqual(set(['rev2a']), graph.heads(['rev2a']))
        self.assertEqual(set(['rev2b']), graph.heads(['rev2b']))
        self.assertEqual(set(['rev3']), graph.heads(['rev3']))
        self.assertEqual(set(['rev4']), graph.heads(['rev4']))

    def test_heads_single(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(set(['rev4']), graph.heads(['null:', 'rev4']))
        self.assertEqual(set(['rev2a']), graph.heads(['rev1', 'rev2a']))
        self.assertEqual(set(['rev2b']), graph.heads(['rev1', 'rev2b']))
        self.assertEqual(set(['rev3']), graph.heads(['rev1', 'rev3']))
        self.assertEqual(set(['rev3']), graph.heads(['rev3', 'rev2a']))
        self.assertEqual(set(['rev4']), graph.heads(['rev1', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev2a', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev2b', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev3', 'rev4']))

    def test_heads_two_heads(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(set(['rev2a', 'rev2b']),
                         graph.heads(['rev2a', 'rev2b']))
        self.assertEqual(set(['rev3', 'rev2b']),
                         graph.heads(['rev3', 'rev2b']))

    def test_heads_criss_cross(self):
        graph = self.make_known_graph(test_graph.criss_cross)
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
        graph = self.make_known_graph(test_graph.history_shortcut)
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

    def test_heads_linear(self):
        graph = self.make_known_graph(test_graph.racing_shortcuts)
        self.assertEqual(set(['w']), graph.heads(['w', 's']))
        self.assertEqual(set(['z']), graph.heads(['w', 's', 'z']))
        self.assertEqual(set(['w', 'q']), graph.heads(['w', 's', 'q']))
        self.assertEqual(set(['z']), graph.heads(['s', 'z']))

    def test_heads_alt_merge(self):
        graph = self.make_known_graph(alt_merge)
        self.assertEqual(set(['c']), graph.heads(['a', 'c']))

    def test_heads_with_ghost(self):
        graph = self.make_known_graph(test_graph.with_ghost)
        self.assertEqual(set(['e', 'g']), graph.heads(['e', 'g']))
        self.assertEqual(set(['a', 'c']), graph.heads(['a', 'c']))
        self.assertEqual(set(['a', 'g']), graph.heads(['a', 'g']))
        self.assertEqual(set(['f', 'g']), graph.heads(['f', 'g']))
        self.assertEqual(set(['c']), graph.heads(['c', 'g']))
        self.assertEqual(set(['c']), graph.heads(['c', 'b', 'd', 'g']))
        self.assertEqual(set(['a', 'c']), graph.heads(['a', 'c', 'e', 'g']))
        self.assertEqual(set(['a', 'c']), graph.heads(['a', 'c', 'f']))


class TestKnownGraphTopoSort(TestCaseWithKnownGraph):

    def assertTopoSortOrder(self, ancestry):
        """Check topo_sort and iter_topo_order is genuinely topological order.

        For every child in the graph, check if it comes after all of it's
        parents.
        """
        graph = self.make_known_graph(ancestry)
        sort_result = graph.topo_sort()
        # We should have an entry in sort_result for every entry present in the
        # graph.
        self.assertEqual(len(ancestry), len(sort_result))
        node_idx = dict((node, idx) for idx, node in enumerate(sort_result))
        for node in sort_result:
            parents = ancestry[node]
            for parent in parents:
                if parent not in ancestry:
                    # ghost
                    continue
                if node_idx[node] <= node_idx[parent]:
                    self.fail("parent %s must come before child %s:\n%s"
                              % (parent, node, sort_result))

    def test_topo_sort_empty(self):
        """TopoSort empty list"""
        self.assertTopoSortOrder({})

    def test_topo_sort_easy(self):
        """TopoSort list with one node"""
        self.assertTopoSortOrder({0: []})

    def test_topo_sort_cycle(self):
        """TopoSort traps graph with cycles"""
        g = self.module.KnownGraph({0: [1],
                                    1: [0]})
        self.assertRaises(errors.GraphCycleError, g.topo_sort)

    def test_topo_sort_cycle_2(self):
        """TopoSort traps graph with longer cycle"""
        g = self.module.KnownGraph({0: [1],
                                    1: [2],
                                    2: [0]})
        self.assertRaises(errors.GraphCycleError, g.topo_sort)

    def test_topo_sort_cycle_with_tail(self):
        """TopoSort traps graph with longer cycle"""
        g = self.module.KnownGraph({0: [1],
                                    1: [2],
                                    2: [3, 4],
                                    3: [0],
                                    4: []})
        self.assertRaises(errors.GraphCycleError, g.topo_sort)

    def test_topo_sort_1(self):
        """TopoSort simple nontrivial graph"""
        self.assertTopoSortOrder({0: [3],
                                  1: [4],
                                  2: [1, 4],
                                  3: [],
                                  4: [0, 3]})

    def test_topo_sort_partial(self):
        """Topological sort with partial ordering.

        Multiple correct orderings are possible, so test for
        correctness, not for exact match on the resulting list.
        """
        self.assertTopoSortOrder({0: [],
                                  1: [0],
                                  2: [0],
                                  3: [0],
                                  4: [1, 2, 3],
                                  5: [1, 2],
                                  6: [1, 2],
                                  7: [2, 3],
                                  8: [0, 1, 4, 5, 6]})

    def test_topo_sort_ghost_parent(self):
        """Sort nodes, but don't include some parents in the output"""
        self.assertTopoSortOrder({0: [1],
                                  1: [2]})
