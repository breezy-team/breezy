# (C) 2005 Canonical
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

import pdb

from bzrlib.errors import GraphCycleError

def topo_sort(graph):
    """Topological sort a graph.

    graph -- sequence of pairs of node->parents_list.

    The result is a list of node names, such that all parents come before
    their children.

    Nodes at the same depth are returned in sorted order.

    node identifiers can be any hashable object, and are typically strings.
    """
    parents = {}  # node -> list of parents
    children = {} # node -> list of children
    for node, node_parents in graph:
        assert node not in parents, \
            ('node %r repeated in graph' % node)
        parents[node] = set(node_parents)
        if node not in children:
            children[node] = set()
        for parent in node_parents:
            if parent in children:
                children[parent].add(node)
            else:
                children[parent] = set([node])
    result = []
    while parents:
        # find nodes with no parents, and take them now
        no_parents = [n for n in parents if len(parents[n]) == 0]
        no_parents.sort()
        if not no_parents:
            raise GraphCycleError(parents)
        for n in no_parents:
            result.append(n)
            for child in children[n]:
                assert n in parents[child]
                parents[child].remove(n)
            del children[n]
            del parents[n]
    return result
