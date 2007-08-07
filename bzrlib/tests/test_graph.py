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
#  rev3a    reveb
history_shortcut = {'rev1': [NULL_REVISION], 'rev2a': ['rev1'],
                    'rev2b': ['rev1'], 'rev2c': ['rev1'],
                    'rev3a': ['rev2a', 'rev2b'], 'rev3b': ['rev2b', 'rev2c']}

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


class DictParentsProvider(object):

    def __init__(self, ancestry):
        self.ancestry = ancestry

    def __repr__(self):
        return 'DictParentsProvider(%r)' % self.ancestry

    def get_parents(self, revisions):
        return [self.ancestry.get(r, None) for r in revisions]


class TestGraph(TestCaseWithMemoryTransport):

    def make_graph(self, ancestors):
        tree = self.prepare_memory_tree('.')
        self.build_ancestry(tree, ancestors)
        tree.unlock()
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

    def test_unique_lca_criss_cross(self):
        """Ensure we don't pick non-unique lcas in a criss-cross"""
        graph = self.make_graph(criss_cross)
        self.assertEqual('rev1', graph.find_unique_lca('rev3a', 'rev3b'))

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

    def test_common_ancestor_two_repos(self):
        """Ensure we do unique_lca using data from two repos"""
        mainline_tree = self.prepare_memory_tree('mainline')
        self.build_ancestry(mainline_tree, mainline)
        mainline_tree.unlock()

        # This is cheating, because the revisions in the graph are actually
        # different revisions, despite having the same revision-id.
        feature_tree = self.prepare_memory_tree('feature')
        self.build_ancestry(feature_tree, feature_branch)
        feature_tree.unlock()
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

    def test_graph_difference_criss_cross(self):
        graph = self.make_graph(criss_cross)
        self.assertEqual((set(['rev3a']), set(['rev3b'])),
                         graph.find_difference('rev3a', 'rev3b'))
        self.assertEqual((set([]), set(['rev3b', 'rev2b'])),
                         graph.find_difference('rev2a', 'rev3b'))

    def test_stacked_parents_provider(self):

        parents1 = DictParentsProvider({'rev2': ['rev3']})
        parents2 = DictParentsProvider({'rev1': ['rev4']})
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
        graph = self.make_graph({'c': ['b', 'd'], 'd': ['e'], 'b': ['a'],
                                 'a': [NULL_REVISION], 'e': [NULL_REVISION]})
        self.assertEqual(['c'], graph._filter_candidate_lca(['a', 'c', 'e']))
