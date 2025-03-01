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

from .. import errors, tests
from .. import graph as _mod_graph
from ..revision import NULL_REVISION
from . import TestCaseWithMemoryTransport

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
ancestry_1 = {
    b"rev1": [NULL_REVISION],
    b"rev2a": [b"rev1"],
    b"rev2b": [b"rev1"],
    b"rev3": [b"rev2a"],
    b"rev4": [b"rev3", b"rev2b"],
}


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
ancestry_2 = {
    b"rev1a": [NULL_REVISION],
    b"rev2a": [b"rev1a"],
    b"rev1b": [NULL_REVISION],
    b"rev3a": [b"rev2a"],
    b"rev4a": [b"rev3a"],
}


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
criss_cross = {
    b"rev1": [NULL_REVISION],
    b"rev2a": [b"rev1"],
    b"rev2b": [b"rev1"],
    b"rev3a": [b"rev2a", b"rev2b"],
    b"rev3b": [b"rev2b", b"rev2a"],
}


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
criss_cross2 = {
    b"rev1a": [NULL_REVISION],
    b"rev1b": [NULL_REVISION],
    b"rev2a": [b"rev1a", b"rev1b"],
    b"rev2b": [b"rev1b", b"rev1a"],
}


# Mainline:
#
#  NULL_REVISION
#       |
#      rev1
#      /  \
#      | rev2b
#      |  /
#     rev2a
mainline = {
    b"rev1": [NULL_REVISION],
    b"rev2a": [b"rev1", b"rev2b"],
    b"rev2b": [b"rev1"],
}


# feature branch:
#
#  NULL_REVISION
#       |
#      rev1
#       |
#     rev2b
#       |
#     rev3b
feature_branch = {b"rev1": [NULL_REVISION], b"rev2b": [b"rev1"], b"rev3b": [b"rev2b"]}


# History shortcut
#  NULL_REVISION
#       |
#     rev1------
#     /  \      \
#  rev2a rev2b rev2c
#    |  /   \   /
#  rev3a    rev3b
history_shortcut = {
    b"rev1": [NULL_REVISION],
    b"rev2a": [b"rev1"],
    b"rev2b": [b"rev1"],
    b"rev2c": [b"rev1"],
    b"rev3a": [b"rev2a", b"rev2b"],
    b"rev3b": [b"rev2b", b"rev2c"],
}

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
extended_history_shortcut = {
    b"a": [NULL_REVISION],
    b"b": [b"a"],
    b"c": [b"b"],
    b"d": [b"c"],
    b"e": [b"d"],
    b"f": [b"a", b"d"],
}

# Double shortcut
# Both sides will see b'A' first, even though it is actually a decendent of a
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

double_shortcut = {
    b"a": [NULL_REVISION],
    b"b": [b"a"],
    b"c": [b"b"],
    b"d": [b"c"],
    b"e": [b"c"],
    b"f": [b"a", b"d"],
    b"g": [b"a", b"e"],
}

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
complex_shortcut = {
    b"a": [NULL_REVISION],
    b"b": [b"a"],
    b"c": [b"b"],
    b"d": [b"c"],
    b"e": [b"d"],
    b"f": [b"d"],
    b"g": [b"f"],
    b"h": [b"f"],
    b"i": [b"e", b"g"],
    b"j": [b"g"],
    b"k": [b"j"],
    b"l": [b"k"],
    b"m": [b"i", b"l"],
    b"n": [b"l", b"h"],
}

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
complex_shortcut2 = {
    b"a": [NULL_REVISION],
    b"b": [b"a"],
    b"c": [b"b"],
    b"d": [b"c"],
    b"e": [b"d"],
    b"f": [b"e"],
    b"g": [b"f"],
    b"h": [b"d"],
    b"i": [b"g"],
    b"j": [b"h"],
    b"k": [b"h", b"i"],
    b"l": [b"k"],
    b"m": [b"l"],
    b"n": [b"m"],
    b"o": [b"n"],
    b"p": [b"o"],
    b"q": [b"p"],
    b"r": [b"q"],
    b"s": [b"r"],
    b"t": [b"i", b"s"],
    b"u": [b"s", b"j"],
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

racing_shortcuts = {
    b"a": [NULL_REVISION],
    b"b": [b"a"],
    b"c": [b"b"],
    b"d": [b"c"],
    b"e": [b"d"],
    b"f": [b"e"],
    b"g": [b"f"],
    b"h": [b"g"],
    b"i": [b"h", b"o"],
    b"j": [b"i", b"y"],
    b"k": [b"d"],
    b"l": [b"k"],
    b"m": [b"l"],
    b"n": [b"m"],
    b"o": [b"n", b"g"],
    b"p": [b"f"],
    b"q": [b"p", b"m"],
    b"r": [b"o"],
    b"s": [b"r"],
    b"t": [b"s"],
    b"u": [b"t"],
    b"v": [b"u"],
    b"w": [b"v"],
    b"x": [b"w"],
    b"y": [b"x"],
    b"z": [b"x", b"q"],
}


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

multiple_interesting_unique = {
    b"a": [NULL_REVISION],
    b"b": [b"a"],
    b"c": [b"b"],
    b"d": [b"c"],
    b"e": [b"d"],
    b"f": [b"d"],
    b"g": [b"e"],
    b"h": [b"e"],
    b"i": [b"f"],
    b"j": [b"g"],
    b"k": [b"g"],
    b"l": [b"h"],
    b"m": [b"i"],
    b"n": [b"k", b"l"],
    b"o": [b"m"],
    b"p": [b"m", b"l"],
    b"q": [b"n", b"o"],
    b"r": [b"q"],
    b"s": [b"r"],
    b"t": [b"s"],
    b"u": [b"t"],
    b"v": [b"u"],
    b"w": [b"v"],
    b"x": [b"w"],
    b"y": [b"j", b"x"],
    b"z": [b"x", b"p"],
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
shortcut_extra_root = {
    b"a": [NULL_REVISION],
    b"b": [b"a"],
    b"c": [b"b"],
    b"d": [b"c"],
    b"e": [b"d"],
    b"f": [b"a", b"d", b"g"],
    b"g": [NULL_REVISION],
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

boundary = {
    b"a": [b"b"],
    b"c": [b"b", b"d"],
    b"b": [b"e"],
    b"d": [b"e"],
    b"e": [b"f"],
    b"f": [NULL_REVISION],
}


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

with_ghost = {
    b"a": [b"b"],
    b"c": [b"b", b"d"],
    b"b": [b"e"],
    b"d": [b"e", b"g"],
    b"e": [b"f"],
    b"f": [NULL_REVISION],
    NULL_REVISION: (),
}

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

with_tail = {
    b"a": [NULL_REVISION],
    b"b": [b"a"],
    b"c": [b"b"],
    b"d": [b"c"],
    b"e": [b"d"],
    b"f": [b"e"],
    b"g": [b"e"],
    b"h": [b"f"],
    b"i": [b"h"],
}


class InstrumentedParentsProvider:
    def __init__(self, parents_provider):
        self.calls = []
        self._real_parents_provider = parents_provider
        get_cached = getattr(parents_provider, "get_cached_parent_map", None)
        if get_cached is not None:
            # Only expose the underlying 'get_cached_parent_map' function if
            # the wrapped provider has it.
            self.get_cached_parent_map = self._get_cached_parent_map

    def get_parent_map(self, nodes):
        self.calls.extend(nodes)
        return self._real_parents_provider.get_parent_map(nodes)

    def _get_cached_parent_map(self, nodes):
        self.calls.append(("cached", sorted(nodes)))
        return self._real_parents_provider.get_cached_parent_map(nodes)


class SharedInstrumentedParentsProvider:
    def __init__(self, parents_provider, calls, info):
        self.calls = calls
        self.info = info
        self._real_parents_provider = parents_provider
        get_cached = getattr(parents_provider, "get_cached_parent_map", None)
        if get_cached is not None:
            # Only expose the underlying 'get_cached_parent_map' function if
            # the wrapped provider has it.
            self.get_cached_parent_map = self._get_cached_parent_map

    def get_parent_map(self, nodes):
        self.calls.append((self.info, sorted(nodes)))
        return self._real_parents_provider.get_parent_map(nodes)

    def _get_cached_parent_map(self, nodes):
        self.calls.append((self.info, "cached", sorted(nodes)))
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
                self.fail("key(s) {} was accessed".format(sorted(bad_keys)))
            return orig_parent_map(keys)

        g.get_parent_map = get_parent_map
        return g


class TestGraph(TestCaseWithMemoryTransport):
    def make_graph(self, ancestors):
        return _mod_graph.Graph(_mod_graph.DictParentsProvider(ancestors))

    def prepare_memory_tree(self, location):
        tree = self.make_branch_and_memory_tree(location)
        tree.lock_write()
        tree.add(".")
        return tree

    def build_ancestry(self, tree, ancestors):
        """Create an ancestry as specified by a graph dict.

        :param tree: A tree to use
        :param ancestors: a dict of {node: [node_parent, ...]}
        """
        pending = [NULL_REVISION]
        descendants = {}
        for descendant, parents in ancestors.items():
            for parent in parents:
                descendants.setdefault(parent, []).append(descendant)
        while len(pending) > 0:
            cur_node = pending.pop()
            for descendant in descendants.get(cur_node, []):
                if tree.branch.repository.has_revision(descendant):
                    continue
                parents = [p for p in ancestors[descendant] if p is not NULL_REVISION]
                if (
                    len(
                        [
                            p
                            for p in parents
                            if not tree.branch.repository.has_revision(p)
                        ]
                    )
                    > 0
                ):
                    continue
                tree.set_parent_ids(parents)
                if len(parents) > 0:
                    left_parent = parents[0]
                else:
                    left_parent = NULL_REVISION
                tree.branch.set_last_revision_info(
                    len(tree.branch._lefthand_history(left_parent)), left_parent
                )
                tree.commit(descendant, rev_id=descendant)
                pending.append(descendant)

    def test_lca(self):
        """Test finding least common ancestor.

        ancestry_1 should always have a single common ancestor
        """
        graph = self.make_graph(ancestry_1)
        self.assertRaises(errors.InvalidRevisionId, graph.find_lca, None)
        self.assertEqual({NULL_REVISION}, graph.find_lca(NULL_REVISION, NULL_REVISION))
        self.assertEqual({NULL_REVISION}, graph.find_lca(NULL_REVISION, b"rev1"))
        self.assertEqual({b"rev1"}, graph.find_lca(b"rev1", b"rev1"))
        self.assertEqual({b"rev1"}, graph.find_lca(b"rev2a", b"rev2b"))

    def test_no_unique_lca(self):
        """Test error when one revision is not in the graph."""
        graph = self.make_graph(ancestry_1)
        self.assertRaises(
            errors.NoCommonAncestor, graph.find_unique_lca, b"rev1", b"1rev"
        )

    def test_lca_criss_cross(self):
        """Test least-common-ancestor after a criss-cross merge."""
        graph = self.make_graph(criss_cross)
        self.assertEqual({b"rev2a", b"rev2b"}, graph.find_lca(b"rev3a", b"rev3b"))
        self.assertEqual({b"rev2b"}, graph.find_lca(b"rev3a", b"rev3b", b"rev2b"))

    def test_lca_shortcut(self):
        """Test least-common ancestor on this history shortcut."""
        graph = self.make_graph(history_shortcut)
        self.assertEqual({b"rev2b"}, graph.find_lca(b"rev3a", b"rev3b"))

    def test_lefthand_distance_smoke(self):
        """A simple does it work test for graph.lefthand_distance(keys)."""
        graph = self.make_graph(history_shortcut)
        distance_graph = graph.find_lefthand_distances([b"rev3b", b"rev2a"])
        self.assertEqual({b"rev2a": 2, b"rev3b": 3}, distance_graph)

    def test_lefthand_distance_ghosts(self):
        """A simple does it work test for graph.lefthand_distance(keys)."""
        nodes = {b"nonghost": [NULL_REVISION], b"toghost": [b"ghost"]}
        graph = self.make_graph(nodes)
        distance_graph = graph.find_lefthand_distances([b"nonghost", b"toghost"])
        self.assertEqual({b"nonghost": 1, b"toghost": -1}, distance_graph)

    def test_recursive_unique_lca(self):
        """Test finding a unique least common ancestor.

        ancestry_1 should always have a single common ancestor
        """
        graph = self.make_graph(ancestry_1)
        self.assertEqual(
            NULL_REVISION, graph.find_unique_lca(NULL_REVISION, NULL_REVISION)
        )
        self.assertEqual(NULL_REVISION, graph.find_unique_lca(NULL_REVISION, b"rev1"))
        self.assertEqual(b"rev1", graph.find_unique_lca(b"rev1", b"rev1"))
        self.assertEqual(b"rev1", graph.find_unique_lca(b"rev2a", b"rev2b"))
        self.assertEqual(
            (
                b"rev1",
                1,
            ),
            graph.find_unique_lca(b"rev2a", b"rev2b", count_steps=True),
        )

    def assertRemoveDescendants(self, expected, graph, revisions):
        parents = graph.get_parent_map(revisions)
        self.assertEqual(expected, graph._remove_simple_descendants(revisions, parents))

    def test__remove_simple_descendants(self):
        graph = self.make_graph(ancestry_1)
        self.assertRemoveDescendants(
            {b"rev1"}, graph, {b"rev1", b"rev2a", b"rev2b", b"rev3", b"rev4"}
        )

    def test__remove_simple_descendants_disjoint(self):
        graph = self.make_graph(ancestry_1)
        self.assertRemoveDescendants({b"rev1", b"rev3"}, graph, {b"rev1", b"rev3"})

    def test__remove_simple_descendants_chain(self):
        graph = self.make_graph(ancestry_1)
        self.assertRemoveDescendants({b"rev1"}, graph, {b"rev1", b"rev2a", b"rev3"})

    def test__remove_simple_descendants_siblings(self):
        graph = self.make_graph(ancestry_1)
        self.assertRemoveDescendants(
            {b"rev2a", b"rev2b"}, graph, {b"rev2a", b"rev2b", b"rev3"}
        )

    def test_unique_lca_criss_cross(self):
        """Ensure we don't pick non-unique lcas in a criss-cross."""
        graph = self.make_graph(criss_cross)
        self.assertEqual(b"rev1", graph.find_unique_lca(b"rev3a", b"rev3b"))
        lca, steps = graph.find_unique_lca(b"rev3a", b"rev3b", count_steps=True)
        self.assertEqual(b"rev1", lca)
        self.assertEqual(2, steps)

    def test_unique_lca_null_revision(self):
        """Ensure we pick NULL_REVISION when necessary."""
        graph = self.make_graph(criss_cross2)
        self.assertEqual(b"rev1b", graph.find_unique_lca(b"rev2a", b"rev1b"))
        self.assertEqual(NULL_REVISION, graph.find_unique_lca(b"rev2a", b"rev2b"))

    def test_unique_lca_null_revision2(self):
        """Ensure we pick NULL_REVISION when necessary."""
        graph = self.make_graph(ancestry_2)
        self.assertEqual(NULL_REVISION, graph.find_unique_lca(b"rev4a", b"rev1b"))

    def test_lca_double_shortcut(self):
        graph = self.make_graph(double_shortcut)
        self.assertEqual(b"c", graph.find_unique_lca(b"f", b"g"))

    def test_common_ancestor_two_repos(self):
        """Ensure we do unique_lca using data from two repos."""
        mainline_tree = self.prepare_memory_tree("mainline")
        self.build_ancestry(mainline_tree, mainline)
        self.addCleanup(mainline_tree.unlock)

        # This is cheating, because the revisions in the graph are actually
        # different revisions, despite having the same revision-id.
        feature_tree = self.prepare_memory_tree("feature")
        self.build_ancestry(feature_tree, feature_branch)
        self.addCleanup(feature_tree.unlock)

        graph = mainline_tree.branch.repository.get_graph(
            feature_tree.branch.repository
        )
        self.assertEqual(b"rev2b", graph.find_unique_lca(b"rev2a", b"rev3b"))

    def test_graph_difference(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual((set(), set()), graph.find_difference(b"rev1", b"rev1"))
        self.assertEqual(
            (set(), {b"rev1"}), graph.find_difference(NULL_REVISION, b"rev1")
        )
        self.assertEqual(
            ({b"rev1"}, set()), graph.find_difference(b"rev1", NULL_REVISION)
        )
        self.assertEqual(
            ({b"rev2a", b"rev3"}, {b"rev2b"}), graph.find_difference(b"rev3", b"rev2b")
        )
        self.assertEqual(
            ({b"rev4", b"rev3", b"rev2a"}, set()),
            graph.find_difference(b"rev4", b"rev2b"),
        )

    def test_graph_difference_separate_ancestry(self):
        graph = self.make_graph(ancestry_2)
        self.assertEqual(
            ({b"rev1a"}, {b"rev1b"}), graph.find_difference(b"rev1a", b"rev1b")
        )
        self.assertEqual(
            ({b"rev1a", b"rev2a", b"rev3a", b"rev4a"}, {b"rev1b"}),
            graph.find_difference(b"rev4a", b"rev1b"),
        )

    def test_graph_difference_criss_cross(self):
        graph = self.make_graph(criss_cross)
        self.assertEqual(
            ({b"rev3a"}, {b"rev3b"}), graph.find_difference(b"rev3a", b"rev3b")
        )
        self.assertEqual(
            (set(), {b"rev3b", b"rev2b"}), graph.find_difference(b"rev2a", b"rev3b")
        )

    def test_graph_difference_extended_history(self):
        graph = self.make_graph(extended_history_shortcut)
        self.assertEqual(({b"e"}, {b"f"}), graph.find_difference(b"e", b"f"))
        self.assertEqual(({b"f"}, {b"e"}), graph.find_difference(b"f", b"e"))

    def test_graph_difference_double_shortcut(self):
        graph = self.make_graph(double_shortcut)
        self.assertEqual(
            ({b"d", b"f"}, {b"e", b"g"}), graph.find_difference(b"f", b"g")
        )

    def test_graph_difference_complex_shortcut(self):
        graph = self.make_graph(complex_shortcut)
        self.assertEqual(
            ({b"m", b"i", b"e"}, {b"n", b"h"}), graph.find_difference(b"m", b"n")
        )

    def test_graph_difference_complex_shortcut2(self):
        graph = self.make_graph(complex_shortcut2)
        self.assertEqual(({b"t"}, {b"j", b"u"}), graph.find_difference(b"t", b"u"))

    def test_graph_difference_shortcut_extra_root(self):
        graph = self.make_graph(shortcut_extra_root)
        self.assertEqual(({b"e"}, {b"f", b"g"}), graph.find_difference(b"e", b"f"))

    def test_iter_topo_order(self):
        graph = self.make_graph(ancestry_1)
        args = [b"rev2a", b"rev3", b"rev1"]
        topo_args = list(graph.iter_topo_order(args))
        self.assertEqual(set(args), set(topo_args))
        self.assertTrue(topo_args.index(b"rev2a") > topo_args.index(b"rev1"))
        self.assertTrue(topo_args.index(b"rev2a") < topo_args.index(b"rev3"))

    def test_is_ancestor(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual(True, graph.is_ancestor(b"null:", b"null:"))
        self.assertEqual(True, graph.is_ancestor(b"null:", b"rev1"))
        self.assertEqual(False, graph.is_ancestor(b"rev1", b"null:"))
        self.assertEqual(True, graph.is_ancestor(b"null:", b"rev4"))
        self.assertEqual(False, graph.is_ancestor(b"rev4", b"null:"))
        self.assertEqual(False, graph.is_ancestor(b"rev4", b"rev2b"))
        self.assertEqual(True, graph.is_ancestor(b"rev2b", b"rev4"))
        self.assertEqual(False, graph.is_ancestor(b"rev2b", b"rev3"))
        self.assertEqual(False, graph.is_ancestor(b"rev3", b"rev2b"))
        instrumented_provider = InstrumentedParentsProvider(graph)
        instrumented_graph = _mod_graph.Graph(instrumented_provider)
        instrumented_graph.is_ancestor(b"rev2a", b"rev2b")
        self.assertTrue(b"null:" not in instrumented_provider.calls)

    def test_is_between(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual(True, graph.is_between(b"null:", b"null:", b"null:"))
        self.assertEqual(True, graph.is_between(b"rev1", b"null:", b"rev1"))
        self.assertEqual(True, graph.is_between(b"rev1", b"rev1", b"rev4"))
        self.assertEqual(True, graph.is_between(b"rev4", b"rev1", b"rev4"))
        self.assertEqual(True, graph.is_between(b"rev3", b"rev1", b"rev4"))
        self.assertEqual(False, graph.is_between(b"rev4", b"rev1", b"rev3"))
        self.assertEqual(False, graph.is_between(b"rev1", b"rev2a", b"rev4"))
        self.assertEqual(False, graph.is_between(b"null:", b"rev1", b"rev4"))

    def test_is_ancestor_boundary(self):
        """Ensure that we avoid searching the whole graph.

        This requires searching through b as a common ancestor, so we
        can identify that e is common.
        """
        graph = self.make_graph(boundary)
        instrumented_provider = InstrumentedParentsProvider(graph)
        graph = _mod_graph.Graph(instrumented_provider)
        self.assertFalse(graph.is_ancestor(b"a", b"c"))
        self.assertTrue(b"null:" not in instrumented_provider.calls)

    def test_iter_ancestry(self):
        nodes = boundary.copy()
        nodes[NULL_REVISION] = ()
        graph = self.make_graph(nodes)
        expected = nodes.copy()
        expected.pop(b"a")  # b'a' is not in the ancestry of b'c', all the
        # other nodes are
        self.assertEqual(expected, dict(graph.iter_ancestry([b"c"])))
        self.assertEqual(nodes, dict(graph.iter_ancestry([b"a", b"c"])))

    def test_iter_ancestry_with_ghost(self):
        graph = self.make_graph(with_ghost)
        expected = with_ghost.copy()
        # b'a' is not in the ancestry of b'c', and b'g' is a ghost
        expected[b"g"] = None
        self.assertEqual(expected, dict(graph.iter_ancestry([b"a", b"c"])))
        expected.pop(b"a")
        self.assertEqual(expected, dict(graph.iter_ancestry([b"c"])))

    def test_filter_candidate_lca(self):
        """Test filter_candidate_lca for a corner case.

        This tests the case where we encounter the end of iteration for b'e'
        in the same pass as we discover that b'd' is an ancestor of b'e', and
        therefore b'e' can't be an lca.

        To compensate for different dict orderings on other Python
        implementations, we mirror b'd' and b'e' with b'b' and b'a'.
        """
        # This test is sensitive to the iteration order of dicts.  It will
        # pass incorrectly if b'e' and b'a' sort before b'c'
        #
        # NULL_REVISION
        #     / \
        #    a   e
        #    |   |
        #    b   d
        #     \ /
        #      c
        graph = self.make_graph(
            {
                b"c": [b"b", b"d"],
                b"d": [b"e"],
                b"b": [b"a"],
                b"a": [NULL_REVISION],
                b"e": [NULL_REVISION],
            }
        )
        self.assertEqual({b"c"}, graph.heads([b"a", b"c", b"e"]))

    def test_heads_null(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual({b"null:"}, graph.heads([b"null:"]))
        self.assertEqual({b"rev1"}, graph.heads([b"null:", b"rev1"]))
        self.assertEqual({b"rev1"}, graph.heads([b"rev1", b"null:"]))
        self.assertEqual({b"rev1"}, graph.heads({b"rev1", b"null:"}))
        self.assertEqual({b"rev1"}, graph.heads((b"rev1", b"null:")))

    def test_heads_one(self):
        # A single node will always be a head
        graph = self.make_graph(ancestry_1)
        self.assertEqual({b"null:"}, graph.heads([b"null:"]))
        self.assertEqual({b"rev1"}, graph.heads([b"rev1"]))
        self.assertEqual({b"rev2a"}, graph.heads([b"rev2a"]))
        self.assertEqual({b"rev2b"}, graph.heads([b"rev2b"]))
        self.assertEqual({b"rev3"}, graph.heads([b"rev3"]))
        self.assertEqual({b"rev4"}, graph.heads([b"rev4"]))

    def test_heads_single(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual({b"rev4"}, graph.heads([b"null:", b"rev4"]))
        self.assertEqual({b"rev2a"}, graph.heads([b"rev1", b"rev2a"]))
        self.assertEqual({b"rev2b"}, graph.heads([b"rev1", b"rev2b"]))
        self.assertEqual({b"rev3"}, graph.heads([b"rev1", b"rev3"]))
        self.assertEqual({b"rev4"}, graph.heads([b"rev1", b"rev4"]))
        self.assertEqual({b"rev4"}, graph.heads([b"rev2a", b"rev4"]))
        self.assertEqual({b"rev4"}, graph.heads([b"rev2b", b"rev4"]))
        self.assertEqual({b"rev4"}, graph.heads([b"rev3", b"rev4"]))

    def test_heads_two_heads(self):
        graph = self.make_graph(ancestry_1)
        self.assertEqual({b"rev2a", b"rev2b"}, graph.heads([b"rev2a", b"rev2b"]))
        self.assertEqual({b"rev3", b"rev2b"}, graph.heads([b"rev3", b"rev2b"]))

    def test_heads_criss_cross(self):
        graph = self.make_graph(criss_cross)
        self.assertEqual({b"rev2a"}, graph.heads([b"rev2a", b"rev1"]))
        self.assertEqual({b"rev2b"}, graph.heads([b"rev2b", b"rev1"]))
        self.assertEqual({b"rev3a"}, graph.heads([b"rev3a", b"rev1"]))
        self.assertEqual({b"rev3b"}, graph.heads([b"rev3b", b"rev1"]))
        self.assertEqual({b"rev2a", b"rev2b"}, graph.heads([b"rev2a", b"rev2b"]))
        self.assertEqual({b"rev3a"}, graph.heads([b"rev3a", b"rev2a"]))
        self.assertEqual({b"rev3a"}, graph.heads([b"rev3a", b"rev2b"]))
        self.assertEqual({b"rev3a"}, graph.heads([b"rev3a", b"rev2a", b"rev2b"]))
        self.assertEqual({b"rev3b"}, graph.heads([b"rev3b", b"rev2a"]))
        self.assertEqual({b"rev3b"}, graph.heads([b"rev3b", b"rev2b"]))
        self.assertEqual({b"rev3b"}, graph.heads([b"rev3b", b"rev2a", b"rev2b"]))
        self.assertEqual({b"rev3a", b"rev3b"}, graph.heads([b"rev3a", b"rev3b"]))
        self.assertEqual(
            {b"rev3a", b"rev3b"}, graph.heads([b"rev3a", b"rev3b", b"rev2a", b"rev2b"])
        )

    def test_heads_shortcut(self):
        graph = self.make_graph(history_shortcut)

        self.assertEqual(
            {b"rev2a", b"rev2b", b"rev2c"}, graph.heads([b"rev2a", b"rev2b", b"rev2c"])
        )
        self.assertEqual({b"rev3a", b"rev3b"}, graph.heads([b"rev3a", b"rev3b"]))
        self.assertEqual(
            {b"rev3a", b"rev3b"}, graph.heads([b"rev2a", b"rev3a", b"rev3b"])
        )
        self.assertEqual({b"rev2a", b"rev3b"}, graph.heads([b"rev2a", b"rev3b"]))
        self.assertEqual({b"rev2c", b"rev3a"}, graph.heads([b"rev2c", b"rev3a"]))

    def _run_heads_break_deeper(self, graph_dict, search):
        """Run heads on a graph-as-a-dict.

        If the search asks for the parents of b'deeper' the test will fail.
        """

        class stub:
            pass

        def get_parent_map(keys):
            result = {}
            for key in keys:
                if key == b"deeper":
                    self.fail("key deeper was accessed")
                result[key] = graph_dict[key]
            return result

        an_obj = stub()
        an_obj.get_parent_map = get_parent_map
        graph = _mod_graph.Graph(an_obj)
        return graph.heads(search)

    def test_heads_limits_search(self):
        # test that a heads query does not search all of history
        graph_dict = {
            b"left": [b"common"],
            b"right": [b"common"],
            b"common": [b"deeper"],
        }
        self.assertEqual(
            {b"left", b"right"},
            self._run_heads_break_deeper(graph_dict, [b"left", b"right"]),
        )

    def test_heads_limits_search_assymetric(self):
        # test that a heads query does not search all of history
        graph_dict = {
            b"left": [b"midleft"],
            b"midleft": [b"common"],
            b"right": [b"common"],
            b"common": [b"aftercommon"],
            b"aftercommon": [b"deeper"],
        }
        self.assertEqual(
            {b"left", b"right"},
            self._run_heads_break_deeper(graph_dict, [b"left", b"right"]),
        )

    def test_heads_limits_search_common_search_must_continue(self):
        # test that common nodes are still queried, preventing
        # all-the-way-to-origin behaviour in the following graph:
        graph_dict = {
            b"h1": [b"shortcut", b"common1"],
            b"h2": [b"common1"],
            b"shortcut": [b"common2"],
            b"common1": [b"common2"],
            b"common2": [b"deeper"],
        }
        self.assertEqual(
            {b"h1", b"h2"}, self._run_heads_break_deeper(graph_dict, [b"h1", b"h2"])
        )

    def test_breadth_first_search_start_ghosts(self):
        graph = self.make_graph({})
        # with_ghosts reports the ghosts
        search = graph._make_breadth_first_searcher([b"a-ghost"])
        self.assertEqual((set(), {b"a-ghost"}), search.next_with_ghosts())
        self.assertRaises(StopIteration, search.next_with_ghosts)
        # next includes them
        search = graph._make_breadth_first_searcher([b"a-ghost"])
        self.assertEqual({b"a-ghost"}, next(search))
        self.assertRaises(StopIteration, next, search)

    def test_breadth_first_search_deep_ghosts(self):
        graph = self.make_graph(
            {
                b"head": [b"present"],
                b"present": [b"child", b"ghost"],
                b"child": [],
            }
        )
        # with_ghosts reports the ghosts
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertEqual(({b"head"}, set()), search.next_with_ghosts())
        self.assertEqual(({b"present"}, set()), search.next_with_ghosts())
        self.assertEqual(({b"child"}, {b"ghost"}), search.next_with_ghosts())
        self.assertRaises(StopIteration, search.next_with_ghosts)
        # next includes them
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertEqual({b"head"}, next(search))
        self.assertEqual({b"present"}, next(search))
        self.assertEqual({b"child", b"ghost"}, next(search))
        self.assertRaises(StopIteration, next, search)

    def test_breadth_first_search_change_next_to_next_with_ghosts(self):
        # To make the API robust, we allow calling both next() and
        # next_with_ghosts() on the same searcher.
        graph = self.make_graph(
            {
                b"head": [b"present"],
                b"present": [b"child", b"ghost"],
                b"child": [],
            }
        )
        # start with next_with_ghosts
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertEqual(({b"head"}, set()), search.next_with_ghosts())
        self.assertEqual({b"present"}, next(search))
        self.assertEqual(({b"child"}, {b"ghost"}), search.next_with_ghosts())
        self.assertRaises(StopIteration, next, search)
        # start with next
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertEqual({b"head"}, next(search))
        self.assertEqual(({b"present"}, set()), search.next_with_ghosts())
        self.assertEqual({b"child", b"ghost"}, next(search))
        self.assertRaises(StopIteration, search.next_with_ghosts)

    def test_breadth_first_change_search(self):
        # Changing the search should work with both next and next_with_ghosts.
        graph = self.make_graph(
            {
                b"head": [b"present"],
                b"present": [b"stopped"],
                b"other": [b"other_2"],
                b"other_2": [],
            }
        )
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertEqual(({b"head"}, set()), search.next_with_ghosts())
        self.assertEqual(({b"present"}, set()), search.next_with_ghosts())
        self.assertEqual({b"present"}, search.stop_searching_any([b"present"]))
        self.assertEqual(
            ({b"other"}, {b"other_ghost"}),
            search.start_searching([b"other", b"other_ghost"]),
        )
        self.assertEqual(({b"other_2"}, set()), search.next_with_ghosts())
        self.assertRaises(StopIteration, search.next_with_ghosts)
        # next includes them
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertEqual({b"head"}, next(search))
        self.assertEqual({b"present"}, next(search))
        self.assertEqual({b"present"}, search.stop_searching_any([b"present"]))
        search.start_searching([b"other", b"other_ghost"])
        self.assertEqual({b"other_2"}, next(search))
        self.assertRaises(StopIteration, next, search)

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
            recipe = ("search",) + recipe
            next()
            if starts is not None:
                search.start_searching(starts)
            if stops is not None:
                search.stop_searching_any(stops)
            state = search.get_state()
            self.assertEqual(set(included_keys), state[2])
            self.assertEqual(seen, search.seen)

    def test_breadth_first_get_result_excludes_current_pending(self):
        graph = self.make_graph(
            {
                b"head": [b"child"],
                b"child": [NULL_REVISION],
                NULL_REVISION: [],
            }
        )
        search = graph._make_breadth_first_searcher([b"head"])
        # At the start, nothing has been seen, to its all excluded:
        state = search.get_state()
        self.assertEqual(({b"head"}, {b"head"}, set()), state)
        self.assertEqual(set(), search.seen)
        # using next:
        expected = [
            ({b"head"}, ({b"head"}, {b"child"}, 1), [b"head"], None, None),
            (
                {b"head", b"child"},
                ({b"head"}, {NULL_REVISION}, 2),
                [b"head", b"child"],
                None,
                None,
            ),
            (
                {b"head", b"child", NULL_REVISION},
                ({b"head"}, set(), 3),
                [b"head", b"child", NULL_REVISION],
                None,
                None,
            ),
        ]
        self.assertSeenAndResult(expected, search, search.__next__)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_get_result_starts_stops(self):
        graph = self.make_graph(
            {
                b"head": [b"child"],
                b"child": [NULL_REVISION],
                b"otherhead": [b"otherchild"],
                b"otherchild": [b"excluded"],
                b"excluded": [NULL_REVISION],
                NULL_REVISION: [],
            }
        )
        search = graph._make_breadth_first_searcher([])
        # Starting with nothing and adding a search works:
        search.start_searching([b"head"])
        # head has been seen:
        state = search.get_state()
        self.assertEqual(({b"head"}, {b"child"}, {b"head"}), state)
        self.assertEqual({b"head"}, search.seen)
        # using next:
        expected = [
            # stop at child, and start a new search at otherhead:
            # - otherhead counts as seen immediately when start_searching is
            # called.
            (
                {b"head", b"child", b"otherhead"},
                ({b"head", b"otherhead"}, {b"child", b"otherchild"}, 2),
                [b"head", b"otherhead"],
                [b"otherhead"],
                [b"child"],
            ),
            (
                {b"head", b"child", b"otherhead", b"otherchild"},
                ({b"head", b"otherhead"}, {b"child", b"excluded"}, 3),
                [b"head", b"otherhead", b"otherchild"],
                None,
                None,
            ),
            # stop searching excluded now
            (
                {b"head", b"child", b"otherhead", b"otherchild", b"excluded"},
                ({b"head", b"otherhead"}, {b"child", b"excluded"}, 3),
                [b"head", b"otherhead", b"otherchild"],
                None,
                [b"excluded"],
            ),
        ]
        self.assertSeenAndResult(expected, search, search.__next__)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([])
        search.start_searching([b"head"])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_stop_searching_not_queried(self):
        # A client should be able to say b'stop node X' even if X has not been
        # returned to the client.
        graph = self.make_graph(
            {
                b"head": [b"child", b"ghost1"],
                b"child": [NULL_REVISION],
                NULL_REVISION: [],
            }
        )
        search = graph._make_breadth_first_searcher([b"head"])
        expected = [
            # NULL_REVISION and ghost1 have not been returned
            (
                {b"head"},
                ({b"head"}, {b"child", NULL_REVISION, b"ghost1"}, 1),
                [b"head"],
                None,
                [NULL_REVISION, b"ghost1"],
            ),
            # ghost1 has been returned, NULL_REVISION is to be returned in the
            # next iteration.
            (
                {b"head", b"child", b"ghost1"},
                ({b"head"}, {b"ghost1", NULL_REVISION}, 2),
                [b"head", b"child"],
                None,
                [NULL_REVISION, b"ghost1"],
            ),
        ]
        self.assertSeenAndResult(expected, search, search.__next__)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_stop_searching_late(self):
        # A client should be able to say b'stop node X' and have it excluded
        # from the result even if X was seen in an older iteration of the
        # search.
        graph = self.make_graph(
            {
                b"head": [b"middle"],
                b"middle": [b"child"],
                b"child": [NULL_REVISION],
                NULL_REVISION: [],
            }
        )
        search = graph._make_breadth_first_searcher([b"head"])
        expected = [
            ({b"head"}, ({b"head"}, {b"middle"}, 1), [b"head"], None, None),
            (
                {b"head", b"middle"},
                ({b"head"}, {b"child"}, 2),
                [b"head", b"middle"],
                None,
                None,
            ),
            # b'middle' came from the previous iteration, but we don't stop
            # searching it until *after* advancing the searcher.
            (
                {b"head", b"middle", b"child"},
                ({b"head"}, {b"middle", b"child"}, 1),
                [b"head"],
                None,
                [b"middle", b"child"],
            ),
        ]
        self.assertSeenAndResult(expected, search, search.__next__)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_get_result_ghosts_are_excluded(self):
        graph = self.make_graph(
            {
                b"head": [b"child", b"ghost"],
                b"child": [NULL_REVISION],
                NULL_REVISION: [],
            }
        )
        search = graph._make_breadth_first_searcher([b"head"])
        # using next:
        expected = [
            ({b"head"}, ({b"head"}, {b"ghost", b"child"}, 1), [b"head"], None, None),
            (
                {b"head", b"child", b"ghost"},
                ({b"head"}, {NULL_REVISION, b"ghost"}, 2),
                [b"head", b"child"],
                None,
                None,
            ),
        ]
        self.assertSeenAndResult(expected, search, search.__next__)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_get_result_starting_a_ghost_ghost_is_excluded(self):
        graph = self.make_graph(
            {
                b"head": [b"child"],
                b"child": [NULL_REVISION],
                NULL_REVISION: [],
            }
        )
        search = graph._make_breadth_first_searcher([b"head"])
        # using next:
        expected = [
            (
                {b"head", b"ghost"},
                ({b"head", b"ghost"}, {b"child", b"ghost"}, 1),
                [b"head"],
                [b"ghost"],
                None,
            ),
            (
                {b"head", b"child", b"ghost"},
                ({b"head", b"ghost"}, {NULL_REVISION, b"ghost"}, 2),
                [b"head", b"child"],
                None,
                None,
            ),
        ]
        self.assertSeenAndResult(expected, search, search.__next__)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_revision_count_includes_NULL_REVISION(self):
        graph = self.make_graph(
            {
                b"head": [NULL_REVISION],
                NULL_REVISION: [],
            }
        )
        search = graph._make_breadth_first_searcher([b"head"])
        # using next:
        expected = [
            ({b"head"}, ({b"head"}, {NULL_REVISION}, 1), [b"head"], None, None),
            (
                {b"head", NULL_REVISION},
                ({b"head"}, set(), 2),
                [b"head", NULL_REVISION],
                None,
                None,
            ),
        ]
        self.assertSeenAndResult(expected, search, search.__next__)
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)

    def test_breadth_first_search_get_result_after_StopIteration(self):
        # StopIteration should not invalid anything..
        graph = self.make_graph(
            {
                b"head": [NULL_REVISION],
                NULL_REVISION: [],
            }
        )
        search = graph._make_breadth_first_searcher([b"head"])
        # using next:
        expected = [
            ({b"head"}, ({b"head"}, {NULL_REVISION}, 1), [b"head"], None, None),
            (
                {b"head", b"ghost", NULL_REVISION},
                ({b"head", b"ghost"}, {b"ghost"}, 2),
                [b"head", NULL_REVISION],
                [b"ghost"],
                None,
            ),
        ]
        self.assertSeenAndResult(expected, search, search.__next__)
        self.assertRaises(StopIteration, next, search)
        self.assertEqual({b"head", b"ghost", NULL_REVISION}, search.seen)
        state = search.get_state()
        self.assertEqual(
            ({b"ghost", b"head"}, {b"ghost"}, {b"head", NULL_REVISION}), state
        )
        # using next_with_ghosts:
        search = graph._make_breadth_first_searcher([b"head"])
        self.assertSeenAndResult(expected, search, search.next_with_ghosts)
        self.assertRaises(StopIteration, next, search)
        self.assertEqual({b"head", b"ghost", NULL_REVISION}, search.seen)
        state = search.get_state()
        self.assertEqual(
            ({b"ghost", b"head"}, {b"ghost"}, {b"head", NULL_REVISION}), state
        )


class TestFindUniqueAncestors(TestGraphBase):
    def assertFindUniqueAncestors(self, graph, expected, node, common):
        actual = graph.find_unique_ancestors(node, common)
        self.assertEqual(expected, sorted(actual))

    def test_empty_set(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindUniqueAncestors(graph, [], b"rev1", [b"rev1"])
        self.assertFindUniqueAncestors(graph, [], b"rev2b", [b"rev2b"])
        self.assertFindUniqueAncestors(graph, [], b"rev3", [b"rev1", b"rev3"])

    def test_single_node(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindUniqueAncestors(graph, [b"rev2a"], b"rev2a", [b"rev1"])
        self.assertFindUniqueAncestors(graph, [b"rev2b"], b"rev2b", [b"rev1"])
        self.assertFindUniqueAncestors(graph, [b"rev3"], b"rev3", [b"rev2a"])

    def test_minimal_ancestry(self):
        graph = self.make_breaking_graph(
            extended_history_shortcut, [NULL_REVISION, b"a", b"b"]
        )
        self.assertFindUniqueAncestors(graph, [b"e"], b"e", [b"d"])

        graph = self.make_breaking_graph(extended_history_shortcut, [b"b"])
        self.assertFindUniqueAncestors(graph, [b"f"], b"f", [b"a", b"d"])

        graph = self.make_breaking_graph(complex_shortcut, [b"a", b"b"])
        self.assertFindUniqueAncestors(graph, [b"h"], b"h", [b"i"])
        self.assertFindUniqueAncestors(graph, [b"e", b"g", b"i"], b"i", [b"h"])
        self.assertFindUniqueAncestors(graph, [b"h"], b"h", [b"g"])
        self.assertFindUniqueAncestors(graph, [b"h"], b"h", [b"j"])

    def test_in_ancestry(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindUniqueAncestors(graph, [], b"rev1", [b"rev3"])
        self.assertFindUniqueAncestors(graph, [], b"rev2b", [b"rev4"])

    def test_multiple_revisions(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindUniqueAncestors(graph, [b"rev4"], b"rev4", [b"rev3", b"rev2b"])
        self.assertFindUniqueAncestors(
            graph, [b"rev2a", b"rev3", b"rev4"], b"rev4", [b"rev2b"]
        )

    def test_complex_shortcut(self):
        graph = self.make_graph(complex_shortcut)
        self.assertFindUniqueAncestors(graph, [b"h", b"n"], b"n", [b"m"])
        self.assertFindUniqueAncestors(graph, [b"e", b"i", b"m"], b"m", [b"n"])

    def test_complex_shortcut2(self):
        graph = self.make_graph(complex_shortcut2)
        self.assertFindUniqueAncestors(graph, [b"j", b"u"], b"u", [b"t"])
        self.assertFindUniqueAncestors(graph, [b"t"], b"t", [b"u"])

    def test_multiple_interesting_unique(self):
        graph = self.make_graph(multiple_interesting_unique)
        self.assertFindUniqueAncestors(graph, [b"j", b"y"], b"y", [b"z"])
        self.assertFindUniqueAncestors(graph, [b"p", b"z"], b"z", [b"y"])

    def test_racing_shortcuts(self):
        graph = self.make_graph(racing_shortcuts)
        self.assertFindUniqueAncestors(graph, [b"p", b"q", b"z"], b"z", [b"y"])
        self.assertFindUniqueAncestors(graph, [b"h", b"i", b"j", b"y"], b"j", [b"z"])


class TestGraphFindDistanceToNull(TestGraphBase):
    """Test an api that should be able to compute a revno."""

    def assertFindDistance(self, revno, graph, target_id, known_ids):
        """Assert the output of Graph.find_distance_to_null()."""
        actual = graph.find_distance_to_null(target_id, known_ids)
        self.assertEqual(revno, actual)

    def test_nothing_known(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindDistance(0, graph, NULL_REVISION, [])
        self.assertFindDistance(1, graph, b"rev1", [])
        self.assertFindDistance(2, graph, b"rev2a", [])
        self.assertFindDistance(2, graph, b"rev2b", [])
        self.assertFindDistance(3, graph, b"rev3", [])
        self.assertFindDistance(4, graph, b"rev4", [])

    def test_rev_is_ghost(self):
        graph = self.make_graph(ancestry_1)
        e = self.assertRaises(
            errors.GhostRevisionsHaveNoRevno,
            graph.find_distance_to_null,
            b"rev_missing",
            [],
        )
        self.assertEqual(b"rev_missing", e.revision_id)
        self.assertEqual(b"rev_missing", e.ghost_revision_id)

    def test_ancestor_is_ghost(self):
        graph = self.make_graph({b"rev": [b"parent"]})
        e = self.assertRaises(
            errors.GhostRevisionsHaveNoRevno, graph.find_distance_to_null, b"rev", []
        )
        self.assertEqual(b"rev", e.revision_id)
        self.assertEqual(b"parent", e.ghost_revision_id)

    def test_known_in_ancestry(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindDistance(2, graph, b"rev2a", [(b"rev1", 1)])
        self.assertFindDistance(3, graph, b"rev3", [(b"rev2a", 2)])

    def test_known_in_ancestry_limits(self):
        graph = self.make_breaking_graph(ancestry_1, [b"rev1"])
        self.assertFindDistance(4, graph, b"rev4", [(b"rev3", 3)])

    def test_target_is_ancestor(self):
        graph = self.make_graph(ancestry_1)
        self.assertFindDistance(2, graph, b"rev2a", [(b"rev3", 3)])

    def test_target_is_ancestor_limits(self):
        """We shouldn't search all history if we run into ourselves."""
        graph = self.make_breaking_graph(ancestry_1, [b"rev1"])
        self.assertFindDistance(3, graph, b"rev3", [(b"rev4", 4)])

    def test_target_parallel_to_known_limits(self):
        # Even though the known revision isn't part of the other ancestry, they
        # eventually converge
        graph = self.make_breaking_graph(with_tail, [b"a"])
        self.assertFindDistance(6, graph, b"f", [(b"g", 6)])
        self.assertFindDistance(7, graph, b"h", [(b"g", 6)])
        self.assertFindDistance(8, graph, b"i", [(b"g", 6)])
        self.assertFindDistance(6, graph, b"g", [(b"i", 8)])


class TestFindMergeOrder(TestGraphBase):
    def assertMergeOrder(self, expected, graph, tip, base_revisions):
        self.assertEqual(expected, graph.find_merge_order(tip, base_revisions))

    def test_parents(self):
        graph = self.make_graph(ancestry_1)
        self.assertMergeOrder([b"rev3", b"rev2b"], graph, b"rev4", [b"rev3", b"rev2b"])
        self.assertMergeOrder([b"rev3", b"rev2b"], graph, b"rev4", [b"rev2b", b"rev3"])

    def test_ancestors(self):
        graph = self.make_graph(ancestry_1)
        self.assertMergeOrder([b"rev1", b"rev2b"], graph, b"rev4", [b"rev1", b"rev2b"])
        self.assertMergeOrder([b"rev1", b"rev2b"], graph, b"rev4", [b"rev2b", b"rev1"])

    def test_shortcut_one_ancestor(self):
        # When we have enough info, we can stop searching
        graph = self.make_breaking_graph(ancestry_1, [b"rev3", b"rev2b", b"rev4"])
        # Single ancestors shortcut right away
        self.assertMergeOrder([b"rev3"], graph, b"rev4", [b"rev3"])

    def test_shortcut_after_one_ancestor(self):
        graph = self.make_breaking_graph(ancestry_1, [b"rev2a", b"rev2b"])
        self.assertMergeOrder([b"rev3", b"rev1"], graph, b"rev4", [b"rev1", b"rev3"])


class TestFindDescendants(TestGraphBase):
    def test_find_descendants_rev1_rev3(self):
        graph = self.make_graph(ancestry_1)
        descendants = graph.find_descendants(b"rev1", b"rev3")
        self.assertEqual({b"rev1", b"rev2a", b"rev3"}, descendants)

    def test_find_descendants_rev1_rev4(self):
        graph = self.make_graph(ancestry_1)
        descendants = graph.find_descendants(b"rev1", b"rev4")
        self.assertEqual({b"rev1", b"rev2a", b"rev2b", b"rev3", b"rev4"}, descendants)

    def test_find_descendants_rev2a_rev4(self):
        graph = self.make_graph(ancestry_1)
        descendants = graph.find_descendants(b"rev2a", b"rev4")
        self.assertEqual({b"rev2a", b"rev3", b"rev4"}, descendants)


class TestFindLefthandMerger(TestGraphBase):
    def check_merger(self, result, ancestry, merged, tip):
        graph = self.make_graph(ancestry)
        self.assertEqual(result, graph.find_lefthand_merger(merged, tip))

    def test_find_lefthand_merger_rev2b(self):
        self.check_merger(b"rev4", ancestry_1, b"rev2b", b"rev4")

    def test_find_lefthand_merger_rev2a(self):
        self.check_merger(b"rev2a", ancestry_1, b"rev2a", b"rev4")

    def test_find_lefthand_merger_rev4(self):
        self.check_merger(None, ancestry_1, b"rev4", b"rev2a")

    def test_find_lefthand_merger_f(self):
        self.check_merger(b"i", complex_shortcut, b"f", b"m")

    def test_find_lefthand_merger_g(self):
        self.check_merger(b"i", complex_shortcut, b"g", b"m")

    def test_find_lefthand_merger_h(self):
        self.check_merger(b"n", complex_shortcut, b"h", b"n")


class TestGetChildMap(TestGraphBase):
    def test_get_child_map(self):
        graph = self.make_graph(ancestry_1)
        child_map = graph.get_child_map([b"rev4", b"rev3", b"rev2a", b"rev2b"])
        self.assertEqual(
            {
                b"rev1": [b"rev2a", b"rev2b"],
                b"rev2a": [b"rev3"],
                b"rev2b": [b"rev4"],
                b"rev3": [b"rev4"],
            },
            child_map,
        )


class TestCachingParentsProvider(tests.TestCase):
    """These tests run with:

    self.inst_pp, a recording parents provider with a graph of a->b, and b is a
    ghost.
    self.caching_pp, a CachingParentsProvider layered on inst_pp.
    """

    def setUp(self):
        super().setUp()
        dict_pp = _mod_graph.DictParentsProvider({b"a": (b"b",)})
        self.inst_pp = InstrumentedParentsProvider(dict_pp)
        self.caching_pp = _mod_graph.CachingParentsProvider(self.inst_pp)

    def test_get_parent_map(self):
        """Requesting the same revision should be returned from cache."""
        self.assertEqual({}, self.caching_pp._cache)
        self.assertEqual({b"a": (b"b",)}, self.caching_pp.get_parent_map([b"a"]))
        self.assertEqual([b"a"], self.inst_pp.calls)
        self.assertEqual({b"a": (b"b",)}, self.caching_pp.get_parent_map([b"a"]))
        # No new call, as it should have been returned from the cache
        self.assertEqual([b"a"], self.inst_pp.calls)
        self.assertEqual({b"a": (b"b",)}, self.caching_pp._cache)

    def test_get_parent_map_not_present(self):
        """The cache should also track when a revision doesn't exist."""
        self.assertEqual({}, self.caching_pp.get_parent_map([b"b"]))
        self.assertEqual([b"b"], self.inst_pp.calls)
        self.assertEqual({}, self.caching_pp.get_parent_map([b"b"]))
        # No new calls
        self.assertEqual([b"b"], self.inst_pp.calls)

    def test_get_parent_map_mixed(self):
        """Anything that can be returned from cache, should be."""
        self.assertEqual({}, self.caching_pp.get_parent_map([b"b"]))
        self.assertEqual([b"b"], self.inst_pp.calls)
        self.assertEqual({b"a": (b"b",)}, self.caching_pp.get_parent_map([b"a", b"b"]))
        self.assertEqual([b"b", b"a"], self.inst_pp.calls)

    def test_get_parent_map_repeated(self):
        """Asking for the same parent 2x will only forward 1 request."""
        self.assertEqual(
            {b"a": (b"b",)}, self.caching_pp.get_parent_map([b"b", b"a", b"b"])
        )
        # Use sorted because we don't care about the order, just that each is
        # only present 1 time.
        self.assertEqual([b"a", b"b"], sorted(self.inst_pp.calls))

    def test_note_missing_key(self):
        """After noting that a key is missing it is cached."""
        self.caching_pp.note_missing_key(b"b")
        self.assertEqual({}, self.caching_pp.get_parent_map([b"b"]))
        self.assertEqual([], self.inst_pp.calls)
        self.assertEqual({b"b"}, self.caching_pp.missing_keys)

    def test_get_cached_parent_map(self):
        self.assertEqual({}, self.caching_pp.get_cached_parent_map([b"a"]))
        self.assertEqual([], self.inst_pp.calls)
        self.assertEqual({b"a": (b"b",)}, self.caching_pp.get_parent_map([b"a"]))
        self.assertEqual([b"a"], self.inst_pp.calls)
        self.assertEqual({b"a": (b"b",)}, self.caching_pp.get_cached_parent_map([b"a"]))


class TestCachingParentsProviderExtras(tests.TestCaseWithTransport):
    """Test the behaviour when parents are provided that were not requested."""

    def setUp(self):
        super().setUp()

        class ExtraParentsProvider:
            def get_parent_map(self, keys):
                return {
                    b"rev1": [],
                    b"rev2": [
                        b"rev1",
                    ],
                }

        self.inst_pp = InstrumentedParentsProvider(ExtraParentsProvider())
        self.caching_pp = _mod_graph.CachingParentsProvider(
            get_parent_map=self.inst_pp.get_parent_map
        )

    def test_uncached(self):
        self.caching_pp.disable_cache()
        self.assertEqual({b"rev1": []}, self.caching_pp.get_parent_map([b"rev1"]))
        self.assertEqual([b"rev1"], self.inst_pp.calls)
        self.assertIs(None, self.caching_pp._cache)

    def test_cache_initially_empty(self):
        self.assertEqual({}, self.caching_pp._cache)

    def test_cached(self):
        self.assertEqual({b"rev1": []}, self.caching_pp.get_parent_map([b"rev1"]))
        self.assertEqual([b"rev1"], self.inst_pp.calls)
        self.assertEqual({b"rev1": [], b"rev2": [b"rev1"]}, self.caching_pp._cache)
        self.assertEqual({b"rev1": []}, self.caching_pp.get_parent_map([b"rev1"]))
        self.assertEqual([b"rev1"], self.inst_pp.calls)

    def test_disable_cache_clears_cache(self):
        # Put something in the cache
        self.caching_pp.get_parent_map([b"rev1"])
        self.assertEqual(2, len(self.caching_pp._cache))
        self.caching_pp.disable_cache()
        self.assertIs(None, self.caching_pp._cache)

    def test_enable_cache_raises(self):
        e = self.assertRaises(AssertionError, self.caching_pp.enable_cache)
        self.assertEqual("Cache enabled when already enabled.", str(e))

    def test_cache_misses(self):
        self.caching_pp.get_parent_map([b"rev3"])
        self.caching_pp.get_parent_map([b"rev3"])
        self.assertEqual([b"rev3"], self.inst_pp.calls)

    def test_no_cache_misses(self):
        self.caching_pp.disable_cache()
        self.caching_pp.enable_cache(cache_misses=False)
        self.caching_pp.get_parent_map([b"rev3"])
        self.caching_pp.get_parent_map([b"rev3"])
        self.assertEqual([b"rev3", b"rev3"], self.inst_pp.calls)

    def test_cache_extras(self):
        self.assertEqual({}, self.caching_pp.get_parent_map([b"rev3"]))
        self.assertEqual(
            {b"rev2": [b"rev1"]}, self.caching_pp.get_parent_map([b"rev2"])
        )
        self.assertEqual([b"rev3"], self.inst_pp.calls)

    def test_extras_using_cached(self):
        self.assertEqual({}, self.caching_pp.get_cached_parent_map([b"rev3"]))
        self.assertEqual({}, self.caching_pp.get_parent_map([b"rev3"]))
        self.assertEqual(
            {b"rev2": [b"rev1"]}, self.caching_pp.get_cached_parent_map([b"rev2"])
        )
        self.assertEqual([b"rev3"], self.inst_pp.calls)


class TestCollapseLinearRegions(tests.TestCase):
    def assertCollapsed(self, collapsed, original):
        self.assertEqual(collapsed, _mod_graph.collapse_linear_regions(original))

    def test_collapse_nothing(self):
        d = {1: [2, 3], 2: [], 3: []}
        self.assertCollapsed(d, d)
        d = {1: [2], 2: [3, 4], 3: [5], 4: [5], 5: []}
        self.assertCollapsed(d, d)

    def test_collapse_chain(self):
        # Any time we have a linear chain, we should be able to collapse
        d = {1: [2], 2: [3], 3: [4], 4: [5], 5: []}
        self.assertCollapsed({1: [5], 5: []}, d)
        d = {5: [4], 4: [3], 3: [2], 2: [1], 1: []}
        self.assertCollapsed({5: [1], 1: []}, d)
        d = {5: [3], 3: [4], 4: [1], 1: [2], 2: []}
        self.assertCollapsed({5: [2], 2: []}, d)

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
        d = {1: [2, 3], 2: [4], 4: [6], 3: [5], 5: [6], 6: [7], 7: []}
        self.assertCollapsed(d, d)


class TestGraphThunkIdsToKeys(tests.TestCase):
    def test_heads(self):
        # A
        # |\
        # B C
        # |/
        # D
        d = {
            (b"D",): [(b"B",), (b"C",)],
            (b"C",): [(b"A",)],
            (b"B",): [(b"A",)],
            (b"A",): [],
        }
        g = _mod_graph.Graph(_mod_graph.DictParentsProvider(d))
        graph_thunk = _mod_graph.GraphThunkIdsToKeys(g)
        self.assertEqual([b"D"], sorted(graph_thunk.heads([b"D", b"A"])))
        self.assertEqual([b"D"], sorted(graph_thunk.heads([b"D", b"B"])))
        self.assertEqual([b"D"], sorted(graph_thunk.heads([b"D", b"C"])))
        self.assertEqual([b"B", b"C"], sorted(graph_thunk.heads([b"B", b"C"])))

    def test_add_node(self):
        d = {(b"C",): [(b"A",)], (b"B",): [(b"A",)], (b"A",): []}
        g = _mod_graph.KnownGraph(d)
        graph_thunk = _mod_graph.GraphThunkIdsToKeys(g)
        graph_thunk.add_node(b"D", [b"A", b"C"])
        self.assertEqual([b"B", b"D"], sorted(graph_thunk.heads([b"D", b"B", b"A"])))

    def test_merge_sort(self):
        d = {(b"C",): [(b"A",)], (b"B",): [(b"A",)], (b"A",): []}
        g = _mod_graph.KnownGraph(d)
        graph_thunk = _mod_graph.GraphThunkIdsToKeys(g)
        graph_thunk.add_node(b"D", [b"A", b"C"])
        self.assertEqual(
            [(b"C", 0, (2,), False), (b"A", 0, (1,), True)],
            [
                (n.key, n.merge_depth, n.revno, n.end_of_merge)
                for n in graph_thunk.merge_sort(b"C")
            ],
        )


class TestStackedParentsProvider(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.calls = []

    def get_shared_provider(self, info, ancestry, has_cached):
        pp = _mod_graph.DictParentsProvider(ancestry)
        if has_cached:
            pp.get_cached_parent_map = pp.get_parent_map
        return SharedInstrumentedParentsProvider(pp, self.calls, info)

    def test_stacked_parents_provider(self):
        parents1 = _mod_graph.DictParentsProvider({b"rev2": [b"rev3"]})
        parents2 = _mod_graph.DictParentsProvider({b"rev1": [b"rev4"]})
        stacked = _mod_graph.StackedParentsProvider([parents1, parents2])
        self.assertEqual(
            {b"rev1": [b"rev4"], b"rev2": [b"rev3"]},
            stacked.get_parent_map([b"rev1", b"rev2"]),
        )
        self.assertEqual(
            {b"rev2": [b"rev3"], b"rev1": [b"rev4"]},
            stacked.get_parent_map([b"rev2", b"rev1"]),
        )
        self.assertEqual(
            {b"rev2": [b"rev3"]}, stacked.get_parent_map([b"rev2", b"rev2"])
        )
        self.assertEqual(
            {b"rev1": [b"rev4"]}, stacked.get_parent_map([b"rev1", b"rev1"])
        )

    def test_stacked_parents_provider_overlapping(self):
        # rev2 is availible in both providers.
        # 1
        # |
        # 2
        parents1 = _mod_graph.DictParentsProvider({b"rev2": [b"rev1"]})
        parents2 = _mod_graph.DictParentsProvider({b"rev2": [b"rev1"]})
        stacked = _mod_graph.StackedParentsProvider([parents1, parents2])
        self.assertEqual({b"rev2": [b"rev1"]}, stacked.get_parent_map([b"rev2"]))

    def test_handles_no_get_cached_parent_map(self):
        # this shows that we both handle when a provider doesn't implement
        # get_cached_parent_map
        pp1 = self.get_shared_provider(b"pp1", {b"rev2": (b"rev1",)}, has_cached=False)
        pp2 = self.get_shared_provider(b"pp2", {b"rev2": (b"rev1",)}, has_cached=True)
        stacked = _mod_graph.StackedParentsProvider([pp1, pp2])
        self.assertEqual({b"rev2": (b"rev1",)}, stacked.get_parent_map([b"rev2"]))
        # No call on b'pp1' because it doesn't provide get_cached_parent_map
        self.assertEqual([(b"pp2", "cached", [b"rev2"])], self.calls)

    def test_query_order(self):
        # We should call get_cached_parent_map on all providers before we call
        # get_parent_map. Further, we should track what entries we have found,
        # and not re-try them.
        pp1 = self.get_shared_provider(b"pp1", {b"a": ()}, has_cached=True)
        pp2 = self.get_shared_provider(b"pp2", {b"c": (b"b",)}, has_cached=False)
        pp3 = self.get_shared_provider(b"pp3", {b"b": (b"a",)}, has_cached=True)
        stacked = _mod_graph.StackedParentsProvider([pp1, pp2, pp3])
        self.assertEqual(
            {b"a": (), b"b": (b"a",), b"c": (b"b",)},
            stacked.get_parent_map([b"a", b"b", b"c", b"d"]),
        )
        self.assertEqual(
            [
                (b"pp1", "cached", [b"a", b"b", b"c", b"d"]),
                # No call to pp2, because it doesn't have cached
                (b"pp3", "cached", [b"b", b"c", b"d"]),
                (b"pp1", [b"c", b"d"]),
                (b"pp2", [b"c", b"d"]),
                (b"pp3", [b"d"]),
            ],
            self.calls,
        )
