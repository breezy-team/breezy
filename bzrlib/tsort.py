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

def topo_sort(nodes, pairs):
    """Topological sort a graph.

    nodes -- list of all nodes in the graph
    pairs -- list of (a, b) pairs, meaning a is a predecessor of b. 
        both a and b must occur in the node list.

    node identifiers can be any hashable object, and are typically strings.
    """
    parents = {}  # node -> list of parents
    children = {} # node -> list of children
    for n in nodes:
        parents[n] = set()
        children[n] = set()
    for p, c in pairs:
        parents[c].add(p)
        children[p].add(c)
    result = []
    while parents:
        # find nodes with no parents, and take them now
        ready = [n for n in parents if len(parents[n]) == 0]
        if not ready:
            raise AssertionError('cycle in graph?')
        for n in ready:
            result.append(n)
            for child in children[n]:
                assert n in parents[child]
                parents[child].remove(n)
            del children[n]
            del parents[n]
    return result
