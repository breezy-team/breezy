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

"""Tests for the python and pyrex extensions of groupcompress"""

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
        ('python-nocache', {'module': _known_graph_py, 'do_cache': False}),
    ]
    suite = loader.suiteClass()
    if CompiledKnownGraphFeature.available():
        from bzrlib import _known_graph_pyx
        scenarios.append(('C', {'module': _known_graph_pyx, 'do_cache': True}))
        scenarios.append(('C-nocache',
                          {'module': _known_graph_pyx, 'do_cache': False}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledKnownGraphFeature)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    result = tests.multiply_tests(standard_tests, scenarios, suite)
    return result


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


class TestKnownGraph(tests.TestCase):

    module = None # Set by load_tests
    do_cache = None # Set by load_tests

    def make_known_graph(self, ancestry):
        return self.module.KnownGraph(ancestry, do_cache=self.do_cache)

    def assertDominator(self, graph, rev, dominator, distance):
        node = graph._nodes[rev]
        self.assertEqual(dominator, node.linear_dominator)
        self.assertEqual(distance, node.dominator_distance)

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

    def test_dominators_ancestry_1(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertDominator(graph, 'rev1', NULL_REVISION, 1)
        self.assertDominator(graph, 'rev2b', 'rev2b', 0)
        self.assertDominator(graph, 'rev2a', 'rev2a', 0)
        self.assertDominator(graph, 'rev3', 'rev2a', 1)
        self.assertDominator(graph, 'rev4', 'rev4', 0)

    def test_dominators_feature_branch(self):
        graph = self.make_known_graph(test_graph.feature_branch)
        self.assertDominator(graph, 'rev1', NULL_REVISION, 1)
        self.assertDominator(graph, 'rev2b', NULL_REVISION, 2)
        self.assertDominator(graph, 'rev3b', NULL_REVISION, 3)

    def test_dominators_extended_history_shortcut(self):
        graph = self.make_known_graph(test_graph.extended_history_shortcut)
        self.assertDominator(graph, 'a', NULL_REVISION, 1)
        self.assertDominator(graph, 'b', 'b', 0)
        self.assertDominator(graph, 'c', 'b', 1)
        self.assertDominator(graph, 'd', 'b', 2)
        self.assertDominator(graph, 'e', 'e', 0)
        self.assertDominator(graph, 'f', 'f', 0)

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
