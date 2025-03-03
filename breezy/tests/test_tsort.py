# Copyright (C) 2005-2009, 2016 Canonical Ltd
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


"""Tests for topological sort."""

import pprint

from breezy.errors import GraphCycleError
from breezy.revision import NULL_REVISION
from breezy.tests import TestCase
from breezy.tsort import MergeSorter, TopoSorter, merge_sort, topo_sort


class TopoSortTests(TestCase):
    def assertSortAndIterate(self, graph, result_list):
        """Check that sorting and iter_topo_order on graph works."""
        self.assertEqual(result_list, topo_sort(graph))
        self.assertEqual(result_list, list(TopoSorter(graph).iter_topo_order()))

    def assertSortAndIterateRaise(self, exception_type, graph):
        """Try iterating and topo_sorting graph and expect an exception."""
        self.assertRaises(exception_type, topo_sort, graph)
        self.assertRaises(exception_type, list, TopoSorter(graph).iter_topo_order())

    def assertSortAndIterateOrder(self, graph):
        """Check topo_sort and iter_topo_order is genuinely topological order.

        For every child in the graph, check if it comes after all of it's
        parents.
        """
        sort_result = topo_sort(graph)
        iter_result = list(TopoSorter(graph).iter_topo_order())
        for node, parents in graph:
            for parent in parents:
                if sort_result.index(node) < sort_result.index(parent):
                    self.fail(
                        "parent {} must come before child {}:\n{}".format(
                            parent, node, sort_result
                        )
                    )
                if iter_result.index(node) < iter_result.index(parent):
                    self.fail(
                        "parent {} must come before child {}:\n{}".format(
                            parent, node, iter_result
                        )
                    )

    def test_tsort_empty(self):
        """TopoSort empty list."""
        self.assertSortAndIterate([], [])

    def test_tsort_easy(self):
        """TopoSort list with one node."""
        self.assertSortAndIterate({0: []}.items(), [0])

    def test_tsort_cycle(self):
        """TopoSort traps graph with cycles."""
        self.assertSortAndIterateRaise(GraphCycleError, {0: [1], 1: [0]}.items())

    def test_tsort_cycle_2(self):
        """TopoSort traps graph with longer cycle."""
        self.assertSortAndIterateRaise(
            GraphCycleError, {0: [1], 1: [2], 2: [0]}.items()
        )

    def test_topo_sort_cycle_with_tail(self):
        """TopoSort traps graph with longer cycle."""
        self.assertSortAndIterateRaise(
            GraphCycleError, {0: [1], 1: [2], 2: [3, 4], 3: [0], 4: []}.items()
        )

    def test_tsort_1(self):
        """TopoSort simple nontrivial graph."""
        self.assertSortAndIterate(
            {0: [3], 1: [4], 2: [1, 4], 3: [], 4: [0, 3]}.items(), [3, 0, 4, 1, 2]
        )

    def test_tsort_partial(self):
        """Topological sort with partial ordering.

        Multiple correct orderings are possible, so test for
        correctness, not for exact match on the resulting list.
        """
        self.assertSortAndIterateOrder(
            [
                (0, []),
                (1, [0]),
                (2, [0]),
                (3, [0]),
                (4, [1, 2, 3]),
                (5, [1, 2]),
                (6, [1, 2]),
                (7, [2, 3]),
                (8, [0, 1, 4, 5, 6]),
            ]
        )

    def test_tsort_unincluded_parent(self):
        """Sort nodes, but don't include some parents in the output."""
        self.assertSortAndIterate([(0, [1]), (1, [2])], [1, 0])


class MergeSortTests(TestCase):
    def assertSortAndIterate(
        self, graph, branch_tip, result_list, generate_revno, mainline_revisions=None
    ):
        """Check that merge based sort and iter_topo_order on graph works."""
        value = merge_sort(
            graph,
            branch_tip,
            mainline_revisions=mainline_revisions,
            generate_revno=generate_revno,
        )
        if result_list != value:
            self.assertEqualDiff(pprint.pformat(result_list), pprint.pformat(value))
        self.assertEqual(
            result_list,
            list(
                MergeSorter(
                    graph,
                    branch_tip,
                    mainline_revisions=mainline_revisions,
                    generate_revno=generate_revno,
                ).iter_topo_order()
            ),
        )

    def test_merge_sort_empty(self):
        # sorting of an emptygraph does not error
        self.assertSortAndIterate({}, None, [], False)
        self.assertSortAndIterate({}, None, [], True)
        self.assertSortAndIterate({}, NULL_REVISION, [], False)
        self.assertSortAndIterate({}, NULL_REVISION, [], True)

    def test_merge_sort_not_empty_no_tip(self):
        # merge sorting of a branch starting with None should result
        # in an empty list: no revisions are dragged in.
        self.assertSortAndIterate({0: []}.items(), None, [], False)
        self.assertSortAndIterate({0: []}.items(), None, [], True)

    def test_merge_sort_one_revision(self):
        # sorting with one revision as the tip returns the correct fields:
        # sequence - 0, revision id, merge depth - 0, end_of_merge
        self.assertSortAndIterate({"id": []}.items(), "id", [(0, "id", 0, True)], False)
        self.assertSortAndIterate(
            {"id": []}.items(), "id", [(0, "id", 0, (1,), True)], True
        )

    def test_sequence_numbers_increase_no_merges(self):
        # emit a few revisions with no merges to check the sequence
        # numbering works in trivial cases
        self.assertSortAndIterate(
            {"A": [], "B": ["A"], "C": ["B"]}.items(),
            "C",
            [
                (0, "C", 0, False),
                (1, "B", 0, False),
                (2, "A", 0, True),
            ],
            False,
        )
        self.assertSortAndIterate(
            {"A": [], "B": ["A"], "C": ["B"]}.items(),
            "C",
            [
                (0, "C", 0, (3,), False),
                (1, "B", 0, (2,), False),
                (2, "A", 0, (1,), True),
            ],
            True,
        )

    def test_sequence_numbers_increase_with_merges(self):
        # test that sequence numbers increase across merges
        self.assertSortAndIterate(
            {"A": [], "B": ["A"], "C": ["A", "B"]}.items(),
            "C",
            [
                (0, "C", 0, False),
                (1, "B", 1, True),
                (2, "A", 0, True),
            ],
            False,
        )
        self.assertSortAndIterate(
            {"A": [], "B": ["A"], "C": ["A", "B"]}.items(),
            "C",
            [
                (0, "C", 0, (2,), False),
                (1, "B", 1, (1, 1, 1), True),
                (2, "A", 0, (1,), True),
            ],
            True,
        )

    def test_merge_sort_race(self):
        # A
        # |
        # B-.
        # |\ \
        # | | C
        # | |/
        # | D
        # |/
        # F
        graph = {
            "A": [],
            "B": ["A"],
            "C": ["B"],
            "D": ["B", "C"],
            "F": ["B", "D"],
        }
        self.assertSortAndIterate(
            graph,
            "F",
            [
                (0, "F", 0, (3,), False),
                (1, "D", 1, (2, 2, 1), False),
                (2, "C", 2, (2, 1, 1), True),
                (3, "B", 0, (2,), False),
                (4, "A", 0, (1,), True),
            ],
            True,
        )
        # A
        # |
        # B-.
        # |\ \
        # | X C
        # | |/
        # | D
        # |/
        # F
        graph = {
            "A": [],
            "B": ["A"],
            "C": ["B"],
            "X": ["B"],
            "D": ["X", "C"],
            "F": ["B", "D"],
        }
        self.assertSortAndIterate(
            graph,
            "F",
            [
                (0, "F", 0, (3,), False),
                (1, "D", 1, (2, 1, 2), False),
                (2, "C", 2, (2, 2, 1), True),
                (3, "X", 1, (2, 1, 1), True),
                (4, "B", 0, (2,), False),
                (5, "A", 0, (1,), True),
            ],
            True,
        )

    def test_merge_depth_with_nested_merges(self):
        # the merge depth marker should reflect the depth of the revision
        # in terms of merges out from the mainline
        # revid, depth, parents:
        #  A 0   [D, B]
        #  B  1  [C, F]
        #  C  1  [H]
        #  D 0   [H, E]
        #  E  1  [G, F]
        #  F   2 [G]
        #  G  1  [H]
        #  H 0
        self.assertSortAndIterate(
            {
                "A": ["D", "B"],
                "B": ["C", "F"],
                "C": ["H"],
                "D": ["H", "E"],
                "E": ["G", "F"],
                "F": ["G"],
                "G": ["H"],
                "H": [],
            }.items(),
            "A",
            [
                (0, "A", 0, False),
                (1, "B", 1, False),
                (2, "C", 1, True),
                (3, "D", 0, False),
                (4, "E", 1, False),
                (5, "F", 2, True),
                (6, "G", 1, True),
                (7, "H", 0, True),
            ],
            False,
        )
        self.assertSortAndIterate(
            {
                "A": ["D", "B"],
                "B": ["C", "F"],
                "C": ["H"],
                "D": ["H", "E"],
                "E": ["G", "F"],
                "F": ["G"],
                "G": ["H"],
                "H": [],
            }.items(),
            "A",
            [
                (0, "A", 0, (3,), False),
                (1, "B", 1, (1, 3, 2), False),
                (2, "C", 1, (1, 3, 1), True),
                (3, "D", 0, (2,), False),
                (4, "E", 1, (1, 1, 2), False),
                (5, "F", 2, (1, 2, 1), True),
                (6, "G", 1, (1, 1, 1), True),
                (7, "H", 0, (1,), True),
            ],
            True,
        )

    def test_dotted_revnos_with_simple_merges(self):
        # A         1
        # |\
        # B C       2, 1.1.1
        # | |\
        # D E F     3, 1.1.2, 1.2.1
        # |/ /|
        # G H I     4, 1.2.2, 1.3.1
        # |/ /
        # J K       5, 1.3.2
        # |/
        # L         6
        self.assertSortAndIterate(
            {
                "A": [],
                "B": ["A"],
                "C": ["A"],
                "D": ["B"],
                "E": ["C"],
                "F": ["C"],
                "G": ["D", "E"],
                "H": ["F"],
                "I": ["F"],
                "J": ["G", "H"],
                "K": ["I"],
                "L": ["J", "K"],
            }.items(),
            "L",
            [
                (0, "L", 0, (6,), False),
                (1, "K", 1, (1, 3, 2), False),
                (2, "I", 1, (1, 3, 1), True),
                (3, "J", 0, (5,), False),
                (4, "H", 1, (1, 2, 2), False),
                (5, "F", 1, (1, 2, 1), True),
                (6, "G", 0, (4,), False),
                (7, "E", 1, (1, 1, 2), False),
                (8, "C", 1, (1, 1, 1), True),
                (9, "D", 0, (3,), False),
                (10, "B", 0, (2,), False),
                (11, "A", 0, (1,), True),
            ],
            True,
        )
        # Adding a shortcut from the first revision should not change any of
        # the existing numbers
        self.assertSortAndIterate(
            {
                "A": [],
                "B": ["A"],
                "C": ["A"],
                "D": ["B"],
                "E": ["C"],
                "F": ["C"],
                "G": ["D", "E"],
                "H": ["F"],
                "I": ["F"],
                "J": ["G", "H"],
                "K": ["I"],
                "L": ["J", "K"],
                "M": ["A"],
                "N": ["L", "M"],
            }.items(),
            "N",
            [
                (0, "N", 0, (7,), False),
                (1, "M", 1, (1, 4, 1), True),
                (2, "L", 0, (6,), False),
                (3, "K", 1, (1, 3, 2), False),
                (4, "I", 1, (1, 3, 1), True),
                (5, "J", 0, (5,), False),
                (6, "H", 1, (1, 2, 2), False),
                (7, "F", 1, (1, 2, 1), True),
                (8, "G", 0, (4,), False),
                (9, "E", 1, (1, 1, 2), False),
                (10, "C", 1, (1, 1, 1), True),
                (11, "D", 0, (3,), False),
                (12, "B", 0, (2,), False),
                (13, "A", 0, (1,), True),
            ],
            True,
        )

    def test_end_of_merge_not_last_revision_in_branch(self):
        # within a branch only the last revision gets an
        # end of merge marker.
        self.assertSortAndIterate(
            {
                "A": ["B"],
                "B": [],
            },
            "A",
            [(0, "A", 0, False), (1, "B", 0, True)],
            False,
        )
        self.assertSortAndIterate(
            {
                "A": ["B"],
                "B": [],
            },
            "A",
            [(0, "A", 0, (2,), False), (1, "B", 0, (1,), True)],
            True,
        )

    def test_end_of_merge_multiple_revisions_merged_at_once(self):
        # when multiple branches are merged at once, both of their
        # branch-endpoints should be listed as end-of-merge.
        # Also, the order of the multiple merges should be
        # left-right shown top to bottom.
        # * means end of merge
        # A 0    [H, B, E]
        # B  1   [D, C]
        # C   2  [D]       *
        # D  1   [H]       *
        # E  1   [G, F]
        # F   2  [G]       *
        # G  1   [H]       *
        # H 0    []        *
        self.assertSortAndIterate(
            {
                "A": ["H", "B", "E"],
                "B": ["D", "C"],
                "C": ["D"],
                "D": ["H"],
                "E": ["G", "F"],
                "F": ["G"],
                "G": ["H"],
                "H": [],
            },
            "A",
            [
                (0, "A", 0, False),
                (1, "B", 1, False),
                (2, "C", 2, True),
                (3, "D", 1, True),
                (4, "E", 1, False),
                (5, "F", 2, True),
                (6, "G", 1, True),
                (7, "H", 0, True),
            ],
            False,
        )
        self.assertSortAndIterate(
            {
                "A": ["H", "B", "E"],
                "B": ["D", "C"],
                "C": ["D"],
                "D": ["H"],
                "E": ["G", "F"],
                "F": ["G"],
                "G": ["H"],
                "H": [],
            },
            "A",
            [
                (0, "A", 0, (2,), False),
                (1, "B", 1, (1, 3, 2), False),
                (2, "C", 2, (1, 4, 1), True),
                (3, "D", 1, (1, 3, 1), True),
                (4, "E", 1, (1, 1, 2), False),
                (5, "F", 2, (1, 2, 1), True),
                (6, "G", 1, (1, 1, 1), True),
                (7, "H", 0, (1,), True),
            ],
            True,
        )

    def test_mainline_revs_partial(self):
        # when a mainline_revisions list is passed this must
        # override the graphs idea of mainline, and must also
        # truncate the output to the specified range, if needed.
        # so we test both at once: a mainline_revisions list that
        # disagrees with the graph about which revs are 'mainline'
        # and also truncates the output.
        # graph:
        # A 0 [E, B]
        # B 1 [D, C]
        # C 2 [D]
        # D 1 [E]
        # E 0
        # with a mainline of NONE,E,A (the inferred one) this will show the
        # merge depths above.
        # with a overriden mainline of NONE,E,D,B,A it should show:
        # A 0
        # B 0
        # C 1
        # D 0
        # E 0
        # and thus when truncated to D,B,A it should show
        # A 0
        # B 0
        # C 1
        # because C is brought in by B in this view and D
        # is the terminating revision id
        # this should also preserve revision numbers: C should still be 2.1.1
        self.assertSortAndIterate(
            {"A": ["E", "B"], "B": ["D", "C"], "C": ["D"], "D": ["E"], "E": []},
            "A",
            [
                (0, "A", 0, False),
                (1, "B", 0, False),
                (2, "C", 1, True),
            ],
            False,
            mainline_revisions=["D", "B", "A"],
        )
        self.assertSortAndIterate(
            {"A": ["E", "B"], "B": ["D", "C"], "C": ["D"], "D": ["E"], "E": []},
            "A",
            [
                (0, "A", 0, (4,), False),
                (1, "B", 0, (3,), False),
                (2, "C", 1, (2, 1, 1), True),
            ],
            True,
            mainline_revisions=["D", "B", "A"],
        )

    def test_mainline_revs_with_none(self):
        # a simple test to ensure that a mainline_revs
        # list which goes all the way to None works
        self.assertSortAndIterate(
            {
                "A": [],
            },
            "A",
            [
                (0, "A", 0, True),
            ],
            False,
            mainline_revisions=[None, "A"],
        )
        self.assertSortAndIterate(
            {
                "A": [],
            },
            "A",
            [
                (0, "A", 0, (1,), True),
            ],
            True,
            mainline_revisions=[None, "A"],
        )

    def test_mainline_revs_with_ghost(self):
        # We have a mainline, but the end of it is actually a ghost
        # The graph that is passed to tsort has had ghosts filtered out, but
        # the mainline history has not.
        self.assertSortAndIterate(
            {"B": [], "C": ["B"]}.items(),
            "C",
            [
                (0, "C", 0, (2,), False),
                (1, "B", 0, (1,), True),
            ],
            True,
            mainline_revisions=["A", "B", "C"],
        )

    def test_parallel_root_sequence_numbers_increase_with_merges(self):
        """When there are parallel roots, check their revnos."""
        self.assertSortAndIterate(
            {"A": [], "B": [], "C": ["A", "B"]}.items(),
            "C",
            [
                (0, "C", 0, (2,), False),
                (1, "B", 1, (0, 1, 1), True),
                (2, "A", 0, (1,), True),
            ],
            True,
        )

    def test_revnos_are_globally_assigned(self):
        """Revnos are assigned according to the revision they derive from."""
        # in this test we setup a number of branches that all derive from
        # the first revision, and then merge them one at a time, which
        # should give the revisions as they merge numbers still deriving from
        # the revision were based on.
        # merge 3: J: ['G', 'I']
        # branch 3:
        #  I: ['H']
        #  H: ['A']
        # merge 2: G: ['D', 'F']
        # branch 2:
        #  F: ['E']
        #  E: ['A']
        # merge 1: D: ['A', 'C']
        # branch 1:
        #  C: ['B']
        #  B: ['A']
        # root: A: []
        self.assertSortAndIterate(
            {
                "J": ["G", "I"],
                "I": [
                    "H",
                ],
                "H": ["A"],
                "G": ["D", "F"],
                "F": ["E"],
                "E": ["A"],
                "D": ["A", "C"],
                "C": ["B"],
                "B": ["A"],
                "A": [],
            }.items(),
            "J",
            [
                (0, "J", 0, (4,), False),
                (1, "I", 1, (1, 3, 2), False),
                (2, "H", 1, (1, 3, 1), True),
                (3, "G", 0, (3,), False),
                (4, "F", 1, (1, 2, 2), False),
                (5, "E", 1, (1, 2, 1), True),
                (6, "D", 0, (2,), False),
                (7, "C", 1, (1, 1, 2), False),
                (8, "B", 1, (1, 1, 1), True),
                (9, "A", 0, (1,), True),
            ],
            True,
        )

    def test_roots_and_sub_branches_versus_ghosts(self):
        """Extra roots and their mini branches use the same numbering.

        All of them use the 0-node numbering.
        """
        #       A D   K
        #       | |\  |\
        #       B E F L M
        #       | |/  |/
        #       C G   N
        #       |/    |\
        #       H I   O P
        #       |/    |/
        #       J     Q
        #       |.---'
        #       R
        self.assertSortAndIterate(
            {
                "A": [],
                "B": ["A"],
                "C": ["B"],
                "D": [],
                "E": ["D"],
                "F": ["D"],
                "G": ["E", "F"],
                "H": ["C", "G"],
                "I": [],
                "J": ["H", "I"],
                "K": [],
                "L": ["K"],
                "M": ["K"],
                "N": ["L", "M"],
                "O": ["N"],
                "P": ["N"],
                "Q": ["O", "P"],
                "R": ["J", "Q"],
            }.items(),
            "R",
            [
                (0, "R", 0, (6,), False),
                (1, "Q", 1, (0, 4, 5), False),
                (2, "P", 2, (0, 6, 1), True),
                (3, "O", 1, (0, 4, 4), False),
                (4, "N", 1, (0, 4, 3), False),
                (5, "M", 2, (0, 5, 1), True),
                (6, "L", 1, (0, 4, 2), False),
                (7, "K", 1, (0, 4, 1), True),
                (8, "J", 0, (5,), False),
                (9, "I", 1, (0, 3, 1), True),
                (10, "H", 0, (4,), False),
                (11, "G", 1, (0, 1, 3), False),
                (12, "F", 2, (0, 2, 1), True),
                (13, "E", 1, (0, 1, 2), False),
                (14, "D", 1, (0, 1, 1), True),
                (15, "C", 0, (3,), False),
                (16, "B", 0, (2,), False),
                (17, "A", 0, (1,), True),
            ],
            True,
        )
