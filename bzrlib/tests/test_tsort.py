# Copyright (C) 2005 by Canonical Ltd
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


"""Tests for topological sort."""


from bzrlib.tests import TestCase
from bzrlib.tsort import topo_sort, TopoSorter, MergeSorter, merge_sort
from bzrlib.errors import GraphCycleError


class TopoSortTests(TestCase):

    def assertSortAndIterate(self, graph, result_list):
        """Check that sorting and iter_topo_order on graph works."""
        self.assertEquals(result_list, topo_sort(graph))
        self.assertEqual(result_list,
                         list(TopoSorter(graph).iter_topo_order()))

    def assertSortAndIterateRaise(self, exception_type, graph):
        """Try both iterating and topo_sorting graph and expect an exception."""
        self.assertRaises(exception_type, topo_sort, graph)
        self.assertRaises(exception_type,
                          list,
                          TopoSorter(graph).iter_topo_order())

    def test_tsort_empty(self):
        """TopoSort empty list"""
        self.assertSortAndIterate([], [])

    def test_tsort_easy(self):
        """TopoSort list with one node"""
        self.assertSortAndIterate({0: []}.items(), [0])

    def test_tsort_cycle(self):
        """TopoSort traps graph with cycles"""
        self.assertSortAndIterateRaise(GraphCycleError,
                                       {0: [1], 
                                        1: [0]}.items())

    def test_tsort_cycle_2(self):
        """TopoSort traps graph with longer cycle"""
        self.assertSortAndIterateRaise(GraphCycleError,
                                       {0: [1], 
                                        1: [2], 
                                        2: [0]}.items())
                 
    def test_tsort_1(self):
        """TopoSort simple nontrivial graph"""
        self.assertSortAndIterate({0: [3], 
                                   1: [4],
                                   2: [1, 4],
                                   3: [], 
                                   4: [0, 3]}.items(),
                                  [3, 0, 4, 1, 2])

    def test_tsort_partial(self):
        """Topological sort with partial ordering.

        If the graph does not give an order between two nodes, they are 
        returned in lexicographical order.
        """
        self.assertSortAndIterate(([(0, []),
                                   (1, [0]),
                                   (2, [0]),
                                   (3, [0]),
                                   (4, [1, 2, 3]),
                                   (5, [1, 2]),
                                   (6, [1, 2]),
                                   (7, [2, 3]),
                                   (8, [0, 1, 4, 5, 6])]),
                                  [0, 1, 2, 3, 4, 5, 6, 7, 8])


class MergeSortTests(TestCase):

    def assertSortAndIterate(self, graph, branch_tip, result_list,
            mainline_revisions=None):
        """Check that merge based sorting and iter_topo_order on graph works."""
        self.assertEquals(result_list,
            merge_sort(graph, branch_tip, mainline_revisions=mainline_revisions))
        self.assertEqual(result_list,
            list(MergeSorter(
                graph,
                branch_tip,
                mainline_revisions=mainline_revisions).iter_topo_order()))

    def test_merge_sort_empty(self):
        # sorting of an emptygraph does not error
        self.assertSortAndIterate({}, None, [])

    def test_merge_sort_not_empty_no_tip(self):
        # merge sorting of a branch starting with None should result
        # in an empty list: no revisions are dragged in.
        self.assertSortAndIterate({0: []}.items(), None, [])

    def test_merge_sort_one_revision(self):
        # sorting with one revision as the tip returns the correct fields:
        # sequence - 0, revision id, merge depth - 0, end_of_merge
        self.assertSortAndIterate({'id': []}.items(),
                                  'id',
                                  [(0, 'id', 0, True)])
    
    def test_sequence_numbers_increase_no_merges(self):
        # emit a few revisions with no merges to check the sequence
        # numbering works in trivial cases
        self.assertSortAndIterate(
            {'A': [],
             'B': ['A'],
             'C': ['B']}.items(),
            'C',
            [(0, 'C', 0, False),
             (1, 'B', 0, False),
             (2, 'A', 0, True),
             ]
            )

    def test_sequence_numbers_increase_with_merges(self):
        # test that sequence numbers increase across merges
        self.assertSortAndIterate(
            {'A': [],
             'B': ['A'],
             'C': ['A', 'B']}.items(),
            'C',
            [(0, 'C', 0, False),
             (1, 'B', 1, True),
             (2, 'A', 0, True),
             ]
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
            {'A': ['D', 'B'],
             'B': ['C', 'F'],
             'C': ['H'],
             'D': ['H', 'E'],
             'E': ['G', 'F'],
             'F': ['G'],
             'G': ['H'],
             'H': []
             }.items(),
            'A',
            [(0, 'A', 0, False),
             (1, 'B', 1, False),
             (2, 'C', 1, True),
             (3, 'D', 0, False),
             (4, 'E', 1, False),
             (5, 'F', 2, True),
             (6, 'G', 1, True),
             (7, 'H', 0, True),
             ]
            )
 
    def test_end_of_merge_not_last_revision_in_branch(self):
        # within a branch only the last revision gets an
        # end of merge marker.
        self.assertSortAndIterate(
            {'A': ['B'],
             'B': [],
             },
            'A',
            [(0, 'A', 0, False),
             (1, 'B', 0, True)
             ]
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
            {'A': ['H', 'B', 'E'],
             'B': ['D', 'C'],
             'C': ['D'],
             'D': ['H'],
             'E': ['G', 'F'],
             'F': ['G'],
             'G': ['H'],
             'H': [],
             },
            'A',
            [(0, 'A', 0, False),
             (1, 'B', 1, False),
             (2, 'C', 2, True),
             (3, 'D', 1, True),
             (4, 'E', 1, False),
             (5, 'F', 2, True),
             (6, 'G', 1, True),
             (7, 'H', 0, True),
             ]
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
        # with a mainline of NONE,E,A (the inferred one) this will show the merge
        # depths above.
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
        self.assertSortAndIterate(
            {'A': ['E', 'B'],
             'B': ['D', 'C'],
             'C': ['D'],
             'D': ['E'],
             'E': []
             },
            'A',
            [(0, 'A', 0, False),
             (1, 'B', 0, False),
             (2, 'C', 1, True),
             ],
            mainline_revisions=['D', 'B', 'A']
            )

    def test_mainline_revs_with_none(self):
        # a simple test to ensure that a mainline_revs
        # list which goes all the way to None works
        self.assertSortAndIterate(
            {'A': [],
             },
            'A',
            [(0, 'A', 0, True),
             ],
            mainline_revisions=[None, 'A']
            )

