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

"""Tests for topological sort.
"""

import os
import sys

from bzrlib.tests import TestCase
from bzrlib.tsort import topo_sort
from bzrlib.errors import GraphCycleError

class TopoSortTests(TestCase):

    def test_tsort_empty(self):
        """TopoSort empty list"""
        self.assertEquals(topo_sort([]), [])

    def test_tsort_easy(self):
        """TopoSort list with one node"""
        self.assertEquals(topo_sort({0: []}.items()),
                          [0])

    def test_tsort_cycle(self):
        """TopoSort traps graph with cycles"""
        self.assertRaises(GraphCycleError,
                          topo_sort,
                          {0: [1], 
                           1: [0]}.iteritems())

    def test_tsort_cycle_2(self):
        """TopoSort traps graph with longer cycle"""
        self.assertRaises(GraphCycleError,
                          topo_sort,
                          {0: [1], 
                           1: [2], 
                           2: [0]}.iteritems())
                 
    def test_tsort_1(self):
        """TopoSort simple nontrivial graph"""
        self.assertEquals(topo_sort({0: [3], 
                                     1: [4],
                                     2: [1, 4],
                                     3: [], 
                                     4: [0, 3]}.iteritems()),
                          [3, 0, 4, 1, 2])

    def test_tsort_partial(self):
        """Topological sort with partial ordering.

        If the graph does not give an order between two nodes, they are 
        returned in lexicographical order.
        """
        self.assertEquals(topo_sort([(0, []),
                                    (1, [0]),
                                    (2, [0]),
                                    (3, [0]),
                                    (4, [1, 2, 3]),
                                    (5, [1, 2]),
                                    (6, [1, 2]),
                                    (7, [2, 3]),
                                    (8, [0, 1, 4, 5, 6])]),
                          [0, 1, 2, 3, 4, 5, 6, 7, 8, ])
