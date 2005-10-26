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

from bzrlib.selftest import TestCase
from bzrlib.tsort import topo_sort

class TopoSortTests(TestCase):

    def test_tsort_empty(self):
        """TopoSort empty list"""
        self.assertEquals(topo_sort([], []), [])

    def test_tsort_easy(self):
        """TopoSort list with one vertex"""
        self.assertEquals(topo_sort([0, 1], [(0, 1)]),
                [0, 1])

    def test_tsort_cycle(self):
        """TopoSort traps graph with cycles."""
        self.assertRaises(AssertionError, 
                topo_sort,
                [0, 1], [(0, 1), (1, 0)])

    def test_tsort_1(self):
        """TopoSort simple nontrivial graph"""
        self.assertEquals(topo_sort([0, 1, 2, 3, 4], 
                                    [(3, 0), (1, 2), (4, 1), (4, 2), (0, 1), (3, 4)]),
                          [3, 0, 4, 1, 2])
