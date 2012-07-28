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
# in common. The extra nodes at the beginning are because we want to avoid
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
#     | g h
#     |/| |
#     i j |
#     | | |
#     | k |
#     | | |
#     | l |
#     |/|/
#     m n
complex_shortcut = {'a':[NULL_REVISION], 'b':['a'], 'c':['b'], 'd':['c'],
                    'e':['d'], 'f':['d'], 'g':['f'], 'h':['f'],
                    'i':['e', 'g'], 'j':['g'], 'k':['j'],
                    'l':['k'], 'm':['i', 'l'], 'n':['l', 'h']}

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
#     e |
#     | |
#     f |
#     | |
#     g h
#     | |\
#     i | j
#     |\| |
#     | k |
#     | | |
#     | l |
#     | | |
#     | m |
#     | | |
#     | n |
#     | | |
#     | o |
#     | | |
#     | p |
#     | | |
#     | q |
#     | | |
#     | r |
#     | | |
#     | s |
#     | | |
#     |/|/
#     t u
complex_shortcut2 = {'a':[NULL_REVISION], 'b':['a'], 'c':['b'], 'd':['c'],
                    'e':['d'], 'f':['e'], 'g':['f'], 'h':['d'], 'i':['g'],
                    'j':['h'], 'k':['h', 'i'], 'l':['k'], 'm':['l'], 'n':['m'],
                    'o':['n'], 'p':['o'], 'q':['p'], 'r':['q'], 's':['r'],
                    't':['i', 's'], 'u':['s', 'j'],
                    }

# Graph where different walkers will race to find the common and uncommon
# nodes.
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
#     e k
#     | |
#     f-+-p
#     | | |
#     | l |
#     | | |
#     | m |
#     | |\|
#     g n q
#     |\| |
#     h o |
#     |/| |
#     i r |
#     | | |
#     | s |
#     | | |
#     | t |
#     | | |
#     | u |
#     | | |
#     | v |
#     | | |
#     | w |
#     | | |
#     | x |
#     | |\|
#     | y z
#     |/
#     j
#
# x is found to be common right away, but is the start of a long series of
# common commits.
# o is actually common, but the i-j shortcut makes it look like it is actually
# unique to j at first, you have to traverse all of x->o to find it.
# q,m gives the walker from j a common point to stop searching, as does p,f.
# k-n exists so that the second pass still has nodes that are worth searching,
# rather than instantly cancelling the extra walker.

racing_shortcuts = {'a':[NULL_REVISION], 'b':['a'], 'c':['b'], 'd':['c'],
    'e':['d'], 'f':['e'], 'g':['f'], 'h':['g'], 'i':['h', 'o'], 'j':['i', 'y'],
    'k':['d'], 'l':['k'], 'm':['l'], 'n':['m'], 'o':['n', 'g'], 'p':['f'],
    'q':['p', 'm'], 'r':['o'], 's':['r'], 't':['s'], 'u':['t'], 'v':['u'],
    'w':['v'], 'x':['w'], 'y':['x'], 'z':['x', 'q']}


# A graph with multiple nodes unique to one side.
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
#     |\ \
#     g h i
#     |\ \ \
#     j k l m
#     | |/ x|
#     | n o p
#     | |/  |
#     | q   |
#     | |   |
#     | r   |
#     | |   |
#     | s   |
#     | |   |
#     | t   |
#     | |   |
#     | u   |
#     | |   |
#     | v   |
#     | |   |
#     | w   |
#     | |   |
#     | x   |
#     |/ \ /
#     y   z
#

multiple_interesting_unique = {'a':[NULL_REVISION], 'b':['a'], 'c':['b'],
    'd':['c'], 'e':['d'], 'f':['d'], 'g':['e'], 'h':['e'], 'i':['f'],
    'j':['g'], 'k':['g'], 'l':['h'], 'm':['i'], 'n':['k', 'l'],
    'o':['m'], 'p':['m', 'l'], 'q':['n', 'o'], 'r':['q'], 's':['r'],
    't':['s'], 'u':['t'], 'v':['u'], 'w':['v'], 'x':['w'],
    'y':['j', 'x'], 'z':['x', 'p']}


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


# A graph that contains a ghost
#  NULL_REVISION
#       |
#       f
#       |
#       e   g
#      / \ /
#     b   d
#     | \ |
#     a   c

with_ghost = {'a': ['b'], 'c': ['b', 'd'], 'b':['e'], 'd':['e', 'g'],
              'e': ['f'], 'f':[NULL_REVISION], NULL_REVISION:()}

# A graph that shows we can shortcut finding revnos when reaching them from the
# side.
#  NULL_REVISION
#       |
#       a
#       |
#       b
#       |
#       c
#       |
#       d
#       |
#       e
#      / \
#     f   g
#     |
#     h
#     |
#     i

with_tail = {'a':[NULL_REVISION], 'b':['a'], 'c':['b'], 'd':['c'], 'e':['d'],
             'f':['e'], 'g':['e'], 'h':['f'], 'i':['h']}


class InstrumentedParentsProvider(object):

    def __init__(self, parents_provider):
        self.calls = []
        self._real_parents_provider = parents_provider
        get_cached = getattr(parents_provider, 'get_cached_parent_map', None)
        if get_cached is not None:
            # Only expose the underlying 'get_cached_parent_map' function if
            # the wrapped provider has it.
            self.get_cached_parent_map = self._get_cached_parent_map

    def get_parent_map(self, nodes):
        self.calls.extend(nodes)
        return self._real_parents_provider.get_parent_map(nodes)

    def _get_cached_parent_map(self, nodes):
        self.calls.append(('cached', sorted(nodes)))
        return self._real_parents_provider.get_cached_parent_map(nodes)


class SharedInstrumentedParentsProvider(object):

    def __init__(self, parents_provider, calls, info):
        self.calls = calls
        self.info = info
        self._real_parents_provider = parents_provider
        get_cached = getattr(parents_provider, 'get_cached_parent_map', None)
        if get_cached is not None:
            # Only expose the underlying 'get_cached_parent_map' function if
            # the wrapped provider has it.
            self.get_cached_parent_map = self._get_cached_parent_map

    def get_parent_map(self, nodes):
        self.calls.append((self.info, sorted(nodes)))
        return self._real_parents_provider.get_parent_map(nodes)

    def _get_cached_parent_map(self, nodes):
        self.calls.append((self.info, 'cached', sorted(nodes)))
        return self._real_parents_provider.get_cached_parent_map(nodes)


class TestGraphBase(tests.TestCase):

    def make_graph(self, ancestors):
        return _mod_graph.Graph(_mod_graph.DictParentsProvider(ancestors))

    def make_breaking_graph(self, ancestors, break_on):
        """Make a Graph that raises an exception if we hit a node."""
        g = self.make_graph(ancestors)
        orig_parent_map = g.get_parent_map
        def get_parent_map(keys):
            bad_keys = set(keys).intersection(break_on)
            if bad_keys:
                self.fail('key(s) %s was accessed' % (sorted(bad_keys),))
            return orig_parent_map(keys)
        g.get_parent_map = get_parent_map
        return g


class TestGraph(TestCaseWithMemoryTransport):

    def make_graph(self, ancestors):
        return _mod_graph.Graph(_mod_graph.DictParentsProvider(ancestors))

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

    def test_lefthand_distance_smoke(self):
        """A simple does it work test for graph.lefthand_distance(keys)."""
        graph = self.make_graph(history_shortcut)
        distance_graph = graph.find_lefthand_distances(['rev3b', 'rev2a'])
        self.assertEqual({'rev2a': 2, 'rev3b': 3}, distance_graph)

    def test_lefthand_distance_ghosts(self):
        """A simple does it work test for graph.lefthand_distance(keys)."""
        nodes = {'nonghost':[NULL_REVISION], 'toghost':['ghost']}
        graph = self.make_graph(nodes)
        distance_graph = graph.find_lefthand_distances(['nonghost', 'toghost'])
        self.assertEqual({'nonghost': 1, 'toghost': -1}, distance_graph)

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

    def assertRemoveDescendants(self, expected, graph, revisions):
        parents = graph.get_parent_map(revisions)
        self.assertEqual(expected,
                         graph._remove_simple_descendants(revisions, parents))

    def test__remove_simple_descendants(self):
        graph = self.make_graph(ancestry_1)
        self.assertRemoveDescendants(set(['rev1']), graph,
            set(['rev1', 'rev2a', 'rev2b', 'rev3', 'rev4']))

    def test__remove_simple_descendants_disjoint(self):
        graph = self.make_graph(ancestry_1)
        self.assertRemoveDescendants(set(['rev1', 'rev3']), graph,
            set(['rev1', 'rev3']))

    def test__remove_simple_descendants_chain(self):
        graph = self.make_graph(ancestry_1)
        self.assertRemoveDescendants(set(['rev1']), graph,
            set(['rev1', 'rev2a', 'rev3']))

    def test__remove_simple_descendants_siblings(self):
        graph = self.make_graph(ancestry_1)
        self.assertRemoveDescendants(set(['rev2a', 'rev2b']), graph,
            set(['rev2a', 'rev2b', 'rev3']))

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
        self.assertEqual((set(['m', 'i', 'e']), set(['n', 'h'])),
                         graph.find_difference('m', 'n'))

    def test_graph_difference_complex_shortcut2(self):
        graph = self.make_graph(complex_shortcut2)
        self.assertEqual((set(['t']), set(['j', 'u'])),
                         graph.find_difference('t', 'u'))

    def test_graph_difference_shortcut_extra_root(self):
        graph = self.make_graph(shortcut_extra_root)
        self.assertEqual((set(['e']), set(['f', 'g'])),
                         graph.find_difference('e', 'f'))

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

    def test_is_between(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual(True, graph.is_between('null:', 'null:', 'null:'))
        self.assertEqual(True, graph.is_between('rev1', 'null:', 'rev1'))
        self.assertEqual(True, graph.is_between('rev1', 'rev1', 'rev4'))
        self.assertEqual(True, graph.is_between('rev4', 'rev1', 'rev4'))
        self.assertEqual(True, graph.is_between('rev3', 'rev1', 'rev4'))
        self.assertEqual(False, graph.is_between('rev4', 'rev1', 'rev3'))
        self.assertEqual(False, graph.is_between('rev1', 'rev2a', 'rev4'))
        self.assertEqual(False, graph.is_between('null:', 'rev1', 'rev4'))

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

    def test_iter_ancestry(self):
        nodes = boundary.copy()
        nodes[NULL_REVISION] = ()
        graph = self.make_graph(nodes)
        expected = nodes.copy()
        expected.pop('a') # 'a' is not in the ancestry of 'c', all the
                          # other nodes are
        self.assertEqual(expected, dict(graph.iter_ancestry(['c'])))
        self.assertEqual(nodes, dict(graph.iter_ancestry(['a', 'c'])))

    def test_iter_ancestry_with_ghost(self):
        graph = self.make_graph(with_ghost)
        expected = with_ghost.copy()
        # 'a' is not in the ancestry of 'c', and 'g' is a ghost
        expected['g'] = None
        self.assertEqual(expected, dict(graph.iter_ancestry(['a', 'c'])))
        expected.pop('a')
        self.assertEqual(expected, dict(graph.iter_ancestry(['c'])))

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
        def get_parent_map(keys):
            result = {}
            for key in keys:
                if key == 'deeper':
                    self.fail('key deeper was accessed')
                result[key] = graph_dict[key]
            return result
        an_obj = stub()
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

    def test_breadth_first_search_start_ghosts(self):
        graph = self.make_graph({})
        # with_ghosts reports the ghosts
        search = graph._make_breadth_first_searcher(['a-ghost'])
        self.assertEqual((set(), set(['a-ghost'])), search.next_with_ghosts())
        self.assertRaises(StopIteration, search.next_with_ghosts)
        # next includes them
        search = graph._make_breadth_first_searcher(['a-ghost'])
        self.assertEqual(set(['a-ghost']), search.next())
        self.assertRaises(StopIteration, search.next)

    def test_breadth_first_search_deep_ghosts(self):
        graph = self.make_graph({
            'head':['present'],
            'present':['child', 'ghost'],
            'child':[],
            })
        # with_ghosts reports the ghosts
        search = graph._make_breadth_first_searcher(['head'])
        self.assertEqual((set(['head']), set()), search.next_with_ghosts())
        self.assertEqual((set(['present']), set()), search.next_with_ghosts())
        self.assertEqual((set(['child']), set(['ghost'])),
            search.next_with_ghosts())
        self.assertRaises(StopIteration, search.next_with_ghosts)
        # next includes them
        search = graph._make_breadth_first_searcher(['head'])
        self.assertEqual(set(['head']), search.next())
        self.assertEqual(set(['present']), search.next())
        self.assertEqual(set(['child', 'ghost']),
            search.next())
        self.assertRaises(StopIteration, search.next)

    def test_breadth_first_search_change_next_to_next_with_ghosts(self):
        # To make the API robust, we allow calling both next() and
        # next_with_ghosts() on the same searcher.
        graph = self.make_graph({
            'head':['present'],
            'present':['child', 'ghost'],
            'child':[],
            })
        # start with next_with_ghosts
        search = graph._make_breadth_first_searcher(['head'])
        self.assertEqual((set(['head']), set()), search.next_with_ghosts())
        self.assertEqual(set(['present']), search.next())
        self.assertEqual((set(['child']), set(['ghost'])),
            search.next_with_ghosts())
        self.assertRaises(StopIteration, search.next)
        # start with next
        search = graph._make_breadth_first_searcher(['head'])
        self.assertEqual(set(['head']), search.next())
        self.assertEqual((set(['present']), set()), search.next_with_ghosts())
        self.assertEqual(set(['child', 'ghost']),
            search.next())
        self.assertRaises(StopIteration, search.next_with_ghosts)

    def test_breadth_first_change_search(self):
        # Changing the search should work with both next and next_with_ghosts.
        graph = self.make_graph({
            'head':['present'],
            'present':['stopped'],
            'other':['other_2'],
            'other_2':[],
            })
        search = graph._make_breadth_first_searcher(['head'])
        self.assertEqual((set(['head']), set()), search.next_with_ghosts())
        self.assertEqual((set(['present']), set()), search.next_with_ghosts())
        self.assertEqual(set(['present']),
            search.stop_searching_any(['present']))
        self.assertEqual((set(['other']), set(['other_ghost'])),
            search.start_searching(['other', 'other_ghost']))
        self.assertEqual((set(['other_2']), set()), search.next_with_ghosts())
        self.assertRaises(StopIteration, search.next_with_ghosts)
        # next includes them
        search = graph._make_breadth_first_searcher(['head'])
        self.assertEqual(set(['head']), search.next())
        self.assertEqual(set(['present']), search.next())
        self.assertEqual(set(['present']),
            search.stop_searching_any(['present']))
        search.start_searching(['other', 'other_ghost'])
        self.assertEqual(set(['other_2']), search.next())
        self.assertRaises(StopIteration, search.next)

    def assertSeenAndResult(self, instructions, search, next):
        """Check the results of .seen and get_result() for a seach.

        :param instructions: A list of tuples:
            (seen, recipe, included_keys, starts, stops).
            seen, recipe and included_keys are results to check on the search
            and the searches get_result(). starts and stops are parameters to
            pass to start_searching and stop_searching_any during each
            iteration, if they are not None.
        :param search: The search to use.
        :param next: A callable to advance the search.
        """
        for seen, recipe, included_keys, starts, stops in instructions:
            # Adjust for recipe contract changes that don't vary for all the
            # current tests.
            recipe = ('search',) + recipe
            next()
            if starts is not None:
                search.start_searching(starts)
            if stops is not None:
                search.stop_searching_any(stops)
            state = search.get_state()
            self.assertEqual(set(included_keys), state[2])
            self.assertEqual(seen, search.seen)

    def test_breadth_first_get_result_excludes_current_pending(self):
        graph = self.make_graph({
            'head':['child'],
            'child':[NULL_REVISION],
            NULL_REVISION:[],
            })
        search = graph._make_breadth_first_searcher(['head'])
        # At the start, nothing has been seen, to its all excluded:
        state = search.get_state()
        self.assertEqual((set(['head']), set(['head']), set()),
            state)
        self.assertEqual(set(), search.seen)
        # using next:
        expected = [
            (set(['head']), (set(['head']), set(['child']), 1),
             ['head'], None, None),
            (set(['head', 'child']), (set(['head']), set([NULL_REVISION]), 2),
             ['head', 'child'], None, None),
            (set(['head', 'child', NULL_REVISION]), (set(['head']), set(), 3),
             ['head', 'child', NULL_REVISION], None, None),
            ]
        self.assertSeenAndResult(expected, search, search.next)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher(['head'])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_get_result_starts_stops(self):
        graph = self.make_graph({
            'head':['child'],
            'child':[NULL_REVISION],
            'otherhead':['otherchild'],
            'otherchild':['excluded'],
            'excluded':[NULL_REVISION],
            NULL_REVISION:[]
            })
        search = graph._make_breadth_first_searcher([])
        # Starting with nothing and adding a search works:
        search.start_searching(['head'])
        # head has been seen:
        state = search.get_state()
        self.assertEqual((set(['head']), set(['child']), set(['head'])),
            state)
        self.assertEqual(set(['head']), search.seen)
        # using next:
        expected = [
            # stop at child, and start a new search at otherhead:
            # - otherhead counts as seen immediately when start_searching is
            # called.
            (set(['head', 'child', 'otherhead']),
             (set(['head', 'otherhead']), set(['child', 'otherchild']), 2),
             ['head', 'otherhead'], ['otherhead'], ['child']),
            (set(['head', 'child', 'otherhead', 'otherchild']),
             (set(['head', 'otherhead']), set(['child', 'excluded']), 3),
             ['head', 'otherhead', 'otherchild'], None, None),
            # stop searching excluded now
            (set(['head', 'child', 'otherhead', 'otherchild', 'excluded']),
             (set(['head', 'otherhead']), set(['child', 'excluded']), 3),
             ['head', 'otherhead', 'otherchild'], None, ['excluded']),
            ]
        self.assertSeenAndResult(expected, search, search.next)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([])
        search.start_searching(['head'])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_stop_searching_not_queried(self):
        # A client should be able to say 'stop node X' even if X has not been
        # returned to the client.
        graph = self.make_graph({
            'head':['child', 'ghost1'],
            'child':[NULL_REVISION],
            NULL_REVISION:[],
            })
        search = graph._make_breadth_first_searcher(['head'])
        expected = [
            # NULL_REVISION and ghost1 have not been returned
            (set(['head']),
             (set(['head']), set(['child', NULL_REVISION, 'ghost1']), 1),
             ['head'], None, [NULL_REVISION, 'ghost1']),
            # ghost1 has been returned, NULL_REVISION is to be returned in the
            # next iteration.
            (set(['head', 'child', 'ghost1']),
             (set(['head']), set(['ghost1', NULL_REVISION]), 2),
             ['head', 'child'], None, [NULL_REVISION, 'ghost1']),
            ]
        self.assertSeenAndResult(expected, search, search.next)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher(['head'])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_stop_searching_late(self):
        # A client should be able to say 'stop node X' and have it excluded
        # from the result even if X was seen in an older iteration of the
        # search.
        graph = self.make_graph({
            'head':['middle'],
            'middle':['child'],
            'child':[NULL_REVISION],
            NULL_REVISION:[],
            })
        search = graph._make_breadth_first_searcher(['head'])
        expected = [
            (set(['head']), (set(['head']), set(['middle']), 1),
             ['head'], None, None),
            (set(['head', 'middle']), (set(['head']), set(['child']), 2),
             ['head', 'middle'], None, None),
            # 'middle' came from the previous iteration, but we don't stop
            # searching it until *after* advancing the searcher.
            (set(['head', 'middle', 'child']),
             (set(['head']), set(['middle', 'child']), 1),
             ['head'], None, ['middle', 'child']),
            ]
        self.assertSeenAndResult(expected, search, search.next)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher(['head'])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_get_result_ghosts_are_excluded(self):
        graph = self.make_graph({
            'head':['child', 'ghost'],
            'child':[NULL_REVISION],
            NULL_REVISION:[],
            })
        search = graph._make_breadth_first_searcher(['head'])
        # using next:
        expected = [
            (set(['head']),
             (set(['head']), set(['ghost', 'child']), 1),
             ['head'], None, None),
            (set(['head', 'child', 'ghost']),
             (set(['head']), set([NULL_REVISION, 'ghost']), 2),
             ['head', 'child'], None, None),
            ]
        self.assertSeenAndResult(expected, search, search.next)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher(['head'])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_get_result_starting_a_ghost_ghost_is_excluded(self):
        graph = self.make_graph({
            'head':['child'],
            'child':[NULL_REVISION],
            NULL_REVISION:[],
            })
        search = graph._make_breadth_first_searcher(['head'])
        # using next:
        expected = [
            (set(['head', 'ghost']),
             (set(['head', 'ghost']), set(['child', 'ghost']), 1),
             ['head'], ['ghost'], None),
            (set(['head', 'child', 'ghost']),
             (set(['head', 'ghost']), set([NULL_REVISION, 'ghost']), 2),
             ['head', 'child'], None, None),
            ]
        self.assertSeenAndResult(expected, search, search.next)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher(['head'])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_revision_count_includes_NULL_REVISION(self):
        graph = self.make_graph({
            'head':[NULL_REVISION],
            NULL_REVISION:[],
            })
        search = graph._make_breadth_first_searcher(['head'])
        # using next:
        expected = [
            (set(['head']),
             (set(['head']), set([NULL_REVISION]), 1),
             ['head'], None, None),
            (set(['head', NULL_REVISION]),
             (set(['head']), set([]), 2),
             ['head', NULL_REVISION], None, None),
            ]
        self.assertSeenAndResult(expected, search, search.next)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher(['head'])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_search_get_result_after_StopIteration(self):
        # StopIteration should not invalid anything..
        graph = self.make_graph({
            'head':[NULL_REVISION],
            NULL_REVISION:[],
            })
        search = graph._make_breadth_first_searcher(['head'])
        # using next:
        expected = [
            (set(['head']),
             (set(['head']), set([NULL_REVISION]), 1),
             ['head'], None, None),
            (set(['head', 'ghost', NULL_REVISION]),
             (set(['head', 'ghost']), set(['ghost']), 2),
             ['head', NULL_REVISION], ['ghost'], None),
            ]
        self.assertSeenAndResult(expected, search, search.next)
        self.assertRaises(StopIteration, search.next)
        self.assertEqual(set(['head', 'ghost', NULL_REVISION]), search.seen)
        state = search.get_state()
        self.assertEqual(
            (set(['ghost', 'head']), set(['ghost']),
                set(['head', NULL_REVISION])),
            state)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher(['head'])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)
        self.assertRaises(StopIteration, search.next)
        self.assertEqual(set(['head', 'ghost', NULL_REVISION]), search.seen)
        state = search.get_state()
        self.assertEqual(
            (set(['ghost', 'head']), set(['ghost']),
                set(['head', NULL_REVISION])),
            state)


class TestFindUniqueAncestors(TestGraphBase):

    def assertFindUniqueAncestors(self, graph, expected, node, common):
        actual = graph.find_unique_ancestors(node, common)
        self.assertEqual(expected, sorted(actual))

    def test_empty_set(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindUniqueAncestors(graph, [], 'rev1', ['rev1'])
        self.assertFindUniqueAncestors(graph, [], 'rev2b', ['rev2b'])
        self.assertFindUniqueAncestors(graph, [], 'rev3', ['rev1', 'rev3'])

    def test_single_node(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindUniqueAncestors(graph, ['rev2a'], 'rev2a', ['rev1'])
        self.assertFindUniqueAncestors(graph, ['rev2b'], 'rev2b', ['rev1'])
        self.assertFindUniqueAncestors(graph, ['rev3'], 'rev3', ['rev2a'])

    def test_minimal_ancestry(self):
        graph = self.make_breaking_graph(extended_history_shortcut,
                                         [NULL_REVISION, 'a', 'b'])
        self.assertFindUniqueAncestors(graph, ['e'], 'e', ['d'])

        graph = self.make_breaking_graph(extended_history_shortcut,
                                         ['b'])
        self.assertFindUniqueAncestors(graph, ['f'], 'f', ['a', 'd'])

        graph = self.make_breaking_graph(complex_shortcut,
                                         ['a', 'b'])
        self.assertFindUniqueAncestors(graph, ['h'], 'h', ['i'])
        self.assertFindUniqueAncestors(graph, ['e', 'g', 'i'], 'i', ['h'])
        self.assertFindUniqueAncestors(graph, ['h'], 'h', ['g'])
        self.assertFindUniqueAncestors(graph, ['h'], 'h', ['j'])

    def test_in_ancestry(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindUniqueAncestors(graph, [], 'rev1', ['rev3'])
        self.assertFindUniqueAncestors(graph, [], 'rev2b', ['rev4'])

    def test_multiple_revisions(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindUniqueAncestors(graph,
            ['rev4'], 'rev4', ['rev3', 'rev2b'])
        self.assertFindUniqueAncestors(graph,
            ['rev2a', 'rev3', 'rev4'], 'rev4', ['rev2b'])

    def test_complex_shortcut(self):
        graph = self.make_graph(complex_shortcut)
        self.assertFindUniqueAncestors(graph,
            ['h', 'n'], 'n', ['m'])
        self.assertFindUniqueAncestors(graph,
            ['e', 'i', 'm'], 'm', ['n'])

    def test_complex_shortcut2(self):
        graph = self.make_graph(complex_shortcut2)
        self.assertFindUniqueAncestors(graph,
            ['j', 'u'], 'u', ['t'])
        self.assertFindUniqueAncestors(graph,
            ['t'], 't', ['u'])

    def test_multiple_interesting_unique(self):
        graph = self.make_graph(multiple_interesting_unique)
        self.assertFindUniqueAncestors(graph,
            ['j', 'y'], 'y', ['z'])
        self.assertFindUniqueAncestors(graph,
            ['p', 'z'], 'z', ['y'])

    def test_racing_shortcuts(self):
        graph = self.make_graph(racing_shortcuts)
        self.assertFindUniqueAncestors(graph,
            ['p', 'q', 'z'], 'z', ['y'])
        self.assertFindUniqueAncestors(graph,
            ['h', 'i', 'j', 'y'], 'j', ['z'])


class TestGraphFindDistanceToNull(TestGraphBase):
    """Test an api that should be able to compute a revno"""

    def assertFindDistance(self, revno, graph, target_id, known_ids):
        """Assert the output of Graph.find_distance_to_null()"""
        actual = graph.find_distance_to_null(target_id, known_ids)
        self.assertEqual(revno, actual)

    def test_nothing_known(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindDistance(0, graph, NULL_REVISION, [])
        self.assertFindDistance(1, graph, 'rev1', [])
        self.assertFindDistance(2, graph, 'rev2a', [])
        self.assertFindDistance(2, graph, 'rev2b', [])
        self.assertFindDistance(3, graph, 'rev3', [])
        self.assertFindDistance(4, graph, 'rev4', [])

    def test_rev_is_ghost(self):
        graph = self.make_graph(ancestry_1)
        e = self.assertRaises(errors.GhostRevisionsHaveNoRevno,
                              graph.find_distance_to_null, 'rev_missing', [])
        self.assertEqual('rev_missing', e.revision_id)
        self.assertEqual('rev_missing', e.ghost_revision_id)

    def test_ancestor_is_ghost(self):
        graph = self.make_graph({'rev':['parent']})
        e = self.assertRaises(errors.GhostRevisionsHaveNoRevno,
                              graph.find_distance_to_null, 'rev', [])
        self.assertEqual('rev', e.revision_id)
        self.assertEqual('parent', e.ghost_revision_id)

    def test_known_in_ancestry(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindDistance(2, graph, 'rev2a', [('rev1', 1)])
        self.assertFindDistance(3, graph, 'rev3', [('rev2a', 2)])

    def test_known_in_ancestry_limits(self):
        graph = self.make_breaking_graph(ancestry_1, ['rev1'])
        self.assertFindDistance(4, graph, 'rev4', [('rev3', 3)])

    def test_target_is_ancestor(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindDistance(2, graph, 'rev2a', [('rev3', 3)])

    def test_target_is_ancestor_limits(self):
        """We shouldn't search all history if we run into ourselves"""
        graph = self.make_breaking_graph(ancestry_1, ['rev1'])
        self.assertFindDistance(3, graph, 'rev3', [('rev4', 4)])

    def test_target_parallel_to_known_limits(self):
        # Even though the known revision isn't part of the other ancestry, they
        # eventually converge
        graph = self.make_breaking_graph(with_tail, ['a'])
        self.assertFindDistance(6, graph, 'f', [('g', 6)])
        self.assertFindDistance(7, graph, 'h', [('g', 6)])
        self.assertFindDistance(8, graph, 'i', [('g', 6)])
        self.assertFindDistance(6, graph, 'g', [('i', 8)])


class TestFindMergeOrder(TestGraphBase):

    def assertMergeOrder(self, expected, graph, tip, base_revisions):
        self.assertEqual(expected, graph.find_merge_order(tip, base_revisions))

    def test_parents(self):
        graph = self.make_graph(ancestry_1)
        self.assertMergeOrder(['rev3', 'rev2b'], graph, 'rev4',
                                                        ['rev3', 'rev2b'])
        self.assertMergeOrder(['rev3', 'rev2b'], graph, 'rev4',
                                                        ['rev2b', 'rev3'])

    def test_ancestors(self):
        graph = self.make_graph(ancestry_1)
        self.assertMergeOrder(['rev1', 'rev2b'], graph, 'rev4',
                                                        ['rev1', 'rev2b'])
        self.assertMergeOrder(['rev1', 'rev2b'], graph, 'rev4',
                                                        ['rev2b', 'rev1'])

    def test_shortcut_one_ancestor(self):
        # When we have enough info, we can stop searching
        graph = self.make_breaking_graph(ancestry_1, ['rev3', 'rev2b', 'rev4'])
        # Single ancestors shortcut right away
        self.assertMergeOrder(['rev3'], graph, 'rev4', ['rev3'])

    def test_shortcut_after_one_ancestor(self):
        graph = self.make_breaking_graph(ancestry_1, ['rev2a', 'rev2b'])
        self.assertMergeOrder(['rev3', 'rev1'], graph, 'rev4', ['rev1', 'rev3'])


class TestFindDescendants(TestGraphBase):

    def test_find_descendants_rev1_rev3(self):
        graph = self.make_graph(ancestry_1)
        descendants = graph.find_descendants('rev1', 'rev3')
        self.assertEqual(set(['rev1', 'rev2a', 'rev3']), descendants)

    def test_find_descendants_rev1_rev4(self):
        graph = self.make_graph(ancestry_1)
        descendants = graph.find_descendants('rev1', 'rev4')
        self.assertEqual(set(['rev1', 'rev2a', 'rev2b', 'rev3', 'rev4']),
                         descendants)

    def test_find_descendants_rev2a_rev4(self):
        graph = self.make_graph(ancestry_1)
        descendants = graph.find_descendants('rev2a', 'rev4')
        self.assertEqual(set(['rev2a', 'rev3', 'rev4']), descendants)

class TestFindLefthandMerger(TestGraphBase):

    def check_merger(self, result, ancestry, merged, tip):
        graph = self.make_graph(ancestry)
        self.assertEqual(result, graph.find_lefthand_merger(merged, tip))

    def test_find_lefthand_merger_rev2b(self):
        self.check_merger('rev4', ancestry_1, 'rev2b', 'rev4')

    def test_find_lefthand_merger_rev2a(self):
        self.check_merger('rev2a', ancestry_1, 'rev2a', 'rev4')

    def test_find_lefthand_merger_rev4(self):
        self.check_merger(None, ancestry_1, 'rev4', 'rev2a')

    def test_find_lefthand_merger_f(self):
        self.check_merger('i', complex_shortcut, 'f', 'm')

    def test_find_lefthand_merger_g(self):
        self.check_merger('i', complex_shortcut, 'g', 'm')

    def test_find_lefthand_merger_h(self):
        self.check_merger('n', complex_shortcut, 'h', 'n')


class TestGetChildMap(TestGraphBase):

    def test_get_child_map(self):
        graph = self.make_graph(ancestry_1)
        child_map = graph.get_child_map(['rev4', 'rev3', 'rev2a', 'rev2b'])
        self.assertEqual({'rev1': ['rev2a', 'rev2b'],
                          'rev2a': ['rev3'],
                          'rev2b': ['rev4'],
                          'rev3': ['rev4']},
                          child_map)


class TestCachingParentsProvider(tests.TestCase):
    """These tests run with:

    self.inst_pp, a recording parents provider with a graph of a->b, and b is a
    ghost.
    self.caching_pp, a CachingParentsProvider layered on inst_pp.
    """

    def setUp(self):
        super(TestCachingParentsProvider, self).setUp()
        dict_pp = _mod_graph.DictParentsProvider({'a': ('b',)})
        self.inst_pp = InstrumentedParentsProvider(dict_pp)
        self.caching_pp = _mod_graph.CachingParentsProvider(self.inst_pp)

    def test_get_parent_map(self):
        """Requesting the same revision should be returned from cache"""
        self.assertEqual({}, self.caching_pp._cache)
        self.assertEqual({'a':('b',)}, self.caching_pp.get_parent_map(['a']))
        self.assertEqual(['a'], self.inst_pp.calls)
        self.assertEqual({'a':('b',)}, self.caching_pp.get_parent_map(['a']))
        # No new call, as it should have been returned from the cache
        self.assertEqual(['a'], self.inst_pp.calls)
        self.assertEqual({'a':('b',)}, self.caching_pp._cache)

    def test_get_parent_map_not_present(self):
        """The cache should also track when a revision doesn't exist"""
        self.assertEqual({}, self.caching_pp.get_parent_map(['b']))
        self.assertEqual(['b'], self.inst_pp.calls)
        self.assertEqual({}, self.caching_pp.get_parent_map(['b']))
        # No new calls
        self.assertEqual(['b'], self.inst_pp.calls)

    def test_get_parent_map_mixed(self):
        """Anything that can be returned from cache, should be"""
        self.assertEqual({}, self.caching_pp.get_parent_map(['b']))
        self.assertEqual(['b'], self.inst_pp.calls)
        self.assertEqual({'a':('b',)},
                         self.caching_pp.get_parent_map(['a', 'b']))
        self.assertEqual(['b', 'a'], self.inst_pp.calls)

    def test_get_parent_map_repeated(self):
        """Asking for the same parent 2x will only forward 1 request."""
        self.assertEqual({'a':('b',)},
                         self.caching_pp.get_parent_map(['b', 'a', 'b']))
        # Use sorted because we don't care about the order, just that each is
        # only present 1 time.
        self.assertEqual(['a', 'b'], sorted(self.inst_pp.calls))

    def test_note_missing_key(self):
        """After noting that a key is missing it is cached."""
        self.caching_pp.note_missing_key('b')
        self.assertEqual({}, self.caching_pp.get_parent_map(['b']))
        self.assertEqual([], self.inst_pp.calls)
        self.assertEqual(set(['b']), self.caching_pp.missing_keys)

    def test_get_cached_parent_map(self):
        self.assertEqual({}, self.caching_pp.get_cached_parent_map(['a']))
        self.assertEqual([], self.inst_pp.calls)
        self.assertEqual({'a': ('b',)}, self.caching_pp.get_parent_map(['a']))
        self.assertEqual(['a'], self.inst_pp.calls)
        self.assertEqual({'a': ('b',)},
                         self.caching_pp.get_cached_parent_map(['a']))


class TestCachingParentsProviderExtras(tests.TestCaseWithTransport):
    """Test the behaviour when parents are provided that were not requested."""

    def setUp(self):
        super(TestCachingParentsProviderExtras, self).setUp()
        class ExtraParentsProvider(object):

            def get_parent_map(self, keys):
                return {'rev1': [], 'rev2': ['rev1',]}

        self.inst_pp = InstrumentedParentsProvider(ExtraParentsProvider())
        self.caching_pp = _mod_graph.CachingParentsProvider(
            get_parent_map=self.inst_pp.get_parent_map)

    def test_uncached(self):
        self.caching_pp.disable_cache()
        self.assertEqual({'rev1': []},
                         self.caching_pp.get_parent_map(['rev1']))
        self.assertEqual(['rev1'], self.inst_pp.calls)
        self.assertIs(None, self.caching_pp._cache)

    def test_cache_initially_empty(self):
        self.assertEqual({}, self.caching_pp._cache)

    def test_cached(self):
        self.assertEqual({'rev1': []},
                         self.caching_pp.get_parent_map(['rev1']))
        self.assertEqual(['rev1'], self.inst_pp.calls)
        self.assertEqual({'rev1': [], 'rev2': ['rev1']},
                         self.caching_pp._cache)
        self.assertEqual({'rev1': []},
                          self.caching_pp.get_parent_map(['rev1']))
        self.assertEqual(['rev1'], self.inst_pp.calls)

    def test_disable_cache_clears_cache(self):
        # Put something in the cache
        self.caching_pp.get_parent_map(['rev1'])
        self.assertEqual(2, len(self.caching_pp._cache))
        self.caching_pp.disable_cache()
        self.assertIs(None, self.caching_pp._cache)

    def test_enable_cache_raises(self):
        e = self.assertRaises(AssertionError, self.caching_pp.enable_cache)
        self.assertEqual('Cache enabled when already enabled.', str(e))

    def test_cache_misses(self):
        self.caching_pp.get_parent_map(['rev3'])
        self.caching_pp.get_parent_map(['rev3'])
        self.assertEqual(['rev3'], self.inst_pp.calls)

    def test_no_cache_misses(self):
        self.caching_pp.disable_cache()
        self.caching_pp.enable_cache(cache_misses=False)
        self.caching_pp.get_parent_map(['rev3'])
        self.caching_pp.get_parent_map(['rev3'])
        self.assertEqual(['rev3', 'rev3'], self.inst_pp.calls)

    def test_cache_extras(self):
        self.assertEqual({}, self.caching_pp.get_parent_map(['rev3']))
        self.assertEqual({'rev2': ['rev1']},
                         self.caching_pp.get_parent_map(['rev2']))
        self.assertEqual(['rev3'], self.inst_pp.calls)

    def test_extras_using_cached(self):
        self.assertEqual({}, self.caching_pp.get_cached_parent_map(['rev3']))
        self.assertEqual({}, self.caching_pp.get_parent_map(['rev3']))
        self.assertEqual({'rev2': ['rev1']},
                         self.caching_pp.get_cached_parent_map(['rev2']))
        self.assertEqual(['rev3'], self.inst_pp.calls)



class TestCollapseLinearRegions(tests.TestCase):

    def assertCollapsed(self, collapsed, original):
        self.assertEqual(collapsed,
                         _mod_graph.collapse_linear_regions(original))

    def test_collapse_nothing(self):
        d = {1:[2, 3], 2:[], 3:[]}
        self.assertCollapsed(d, d)
        d = {1:[2], 2:[3, 4], 3:[5], 4:[5], 5:[]}
        self.assertCollapsed(d, d)

    def test_collapse_chain(self):
        # Any time we have a linear chain, we should be able to collapse
        d = {1:[2], 2:[3], 3:[4], 4:[5], 5:[]}
        self.assertCollapsed({1:[5], 5:[]}, d)
        d = {5:[4], 4:[3], 3:[2], 2:[1], 1:[]}
        self.assertCollapsed({5:[1], 1:[]}, d)
        d = {5:[3], 3:[4], 4:[1], 1:[2], 2:[]}
        self.assertCollapsed({5:[2], 2:[]}, d)

    def test_collapse_with_multiple_children(self):
        #    7
        #    |
        #    6
        #   / \
        #  4   5
        #  |   |
        #  2   3
        #   \ /
        #    1
        #
        # 4 and 5 cannot be removed because 6 has 2 children
        # 2 and 3 cannot be removed because 1 has 2 parents
        d = {1:[2, 3], 2:[4], 4:[6], 3:[5], 5:[6], 6:[7], 7:[]}
        self.assertCollapsed(d, d)


class TestGraphThunkIdsToKeys(tests.TestCase):

    def test_heads(self):
        # A
        # |\
        # B C
        # |/
        # D
        d = {('D',): [('B',), ('C',)], ('C',):[('A',)],
             ('B',): [('A',)], ('A',): []}
        g = _mod_graph.Graph(_mod_graph.DictParentsProvider(d))
        graph_thunk = _mod_graph.GraphThunkIdsToKeys(g)
        self.assertEqual(['D'], sorted(graph_thunk.heads(['D', 'A'])))
        self.assertEqual(['D'], sorted(graph_thunk.heads(['D', 'B'])))
        self.assertEqual(['D'], sorted(graph_thunk.heads(['D', 'C'])))
        self.assertEqual(['B', 'C'], sorted(graph_thunk.heads(['B', 'C'])))

    def test_add_node(self):
        d = {('C',):[('A',)], ('B',): [('A',)], ('A',): []}
        g = _mod_graph.KnownGraph(d)
        graph_thunk = _mod_graph.GraphThunkIdsToKeys(g)
        graph_thunk.add_node("D", ["A", "C"])
        self.assertEqual(['B', 'D'],
            sorted(graph_thunk.heads(['D', 'B', 'A'])))

    def test_merge_sort(self):
        d = {('C',):[('A',)], ('B',): [('A',)], ('A',): []}
        g = _mod_graph.KnownGraph(d)
        graph_thunk = _mod_graph.GraphThunkIdsToKeys(g)
        graph_thunk.add_node("D", ["A", "C"])
        self.assertEqual([('C', 0, (2,), False), ('A', 0, (1,), True)],
            [(n.key, n.merge_depth, n.revno, n.end_of_merge)
                 for n in graph_thunk.merge_sort('C')])


class TestStackedParentsProvider(tests.TestCase):

    def setUp(self):
        super(TestStackedParentsProvider, self).setUp()
        self.calls = []

    def get_shared_provider(self, info, ancestry, has_cached):
        pp = _mod_graph.DictParentsProvider(ancestry)
        if has_cached:
            pp.get_cached_parent_map = pp.get_parent_map
        return SharedInstrumentedParentsProvider(pp, self.calls, info)

    def test_stacked_parents_provider(self):
        parents1 = _mod_graph.DictParentsProvider({'rev2': ['rev3']})
        parents2 = _mod_graph.DictParentsProvider({'rev1': ['rev4']})
        stacked = _mod_graph.StackedParentsProvider([parents1, parents2])
        self.assertEqual({'rev1':['rev4'], 'rev2':['rev3']},
                         stacked.get_parent_map(['rev1', 'rev2']))
        self.assertEqual({'rev2':['rev3'], 'rev1':['rev4']},
                         stacked.get_parent_map(['rev2', 'rev1']))
        self.assertEqual({'rev2':['rev3']},
                         stacked.get_parent_map(['rev2', 'rev2']))
        self.assertEqual({'rev1':['rev4']},
                         stacked.get_parent_map(['rev1', 'rev1']))

    def test_stacked_parents_provider_overlapping(self):
        # rev2 is availible in both providers.
        # 1
        # |
        # 2
        parents1 = _mod_graph.DictParentsProvider({'rev2': ['rev1']})
        parents2 = _mod_graph.DictParentsProvider({'rev2': ['rev1']})
        stacked = _mod_graph.StackedParentsProvider([parents1, parents2])
        self.assertEqual({'rev2': ['rev1']},
                         stacked.get_parent_map(['rev2']))

    def test_handles_no_get_cached_parent_map(self):
        # this shows that we both handle when a provider doesn't implement
        # get_cached_parent_map
        pp1 = self.get_shared_provider('pp1', {'rev2': ('rev1',)},
                                       has_cached=False)
        pp2 = self.get_shared_provider('pp2', {'rev2': ('rev1',)},
                                       has_cached=True)
        stacked = _mod_graph.StackedParentsProvider([pp1, pp2])
        self.assertEqual({'rev2': ('rev1',)}, stacked.get_parent_map(['rev2']))
        # No call on 'pp1' because it doesn't provide get_cached_parent_map
        self.assertEqual([('pp2', 'cached', ['rev2'])], self.calls)

    def test_query_order(self):
        # We should call get_cached_parent_map on all providers before we call
        # get_parent_map. Further, we should track what entries we have found,
        # and not re-try them.
        pp1 = self.get_shared_provider('pp1', {'a': ()}, has_cached=True)
        pp2 = self.get_shared_provider('pp2', {'c': ('b',)}, has_cached=False)
        pp3 = self.get_shared_provider('pp3', {'b': ('a',)}, has_cached=True)
        stacked = _mod_graph.StackedParentsProvider([pp1, pp2, pp3])
        self.assertEqual({'a': (), 'b': ('a',), 'c': ('b',)},
                         stacked.get_parent_map(['a', 'b', 'c', 'd']))
        self.assertEqual([('pp1', 'cached', ['a', 'b', 'c', 'd']),
                          # No call to pp2, because it doesn't have cached
                          ('pp3', 'cached', ['b', 'c', 'd']),
                          ('pp1', ['c', 'd']),
                          ('pp2', ['c', 'd']),
                          ('pp3', ['d']),
                         ], self.calls)
