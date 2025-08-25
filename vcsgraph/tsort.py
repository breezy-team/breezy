# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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

"""Topological sorting routines."""

from . import graph as _mod_graph
from ._known_graph_py import KnownGraph

__all__ = ["topo_sort"]

# The Rust implementations are optional
try:
    from ._graph_rs import MergeSorter, TopoSorter, merge_sort
    __all__.extend(["MergeSorter", "TopoSorter", "merge_sort"])
except ImportError:
    # Rust extensions not available
    MergeSorter = None
    TopoSorter = None
    merge_sort = None


def topo_sort(graph):
    """Topological sort a graph.

    graph -- sequence of pairs of node->parents_list.

    The result is a list of node names, such that all parents come before their
    children.

    node identifiers can be any hashable object, and are typically strings.

    This function has the same purpose as the TopoSorter class, but uses a
    different algorithm to sort the graph. That means that while both return a
    list with parents before their child nodes, the exact ordering can be
    different.

    topo_sort is faster when the whole list is needed, while when iterating
    over a part of the list, TopoSorter.iter_topo_order should be used.
    """
    kg = KnownGraph(dict(graph))
    return kg.topo_sort()
