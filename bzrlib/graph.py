# (C) 2005 Canonical

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

def max_distance(node, ancestors, distances, root_descendants):
    """Calculate the max distance to an ancestor.  
    Return None if not all possible ancestors have known distances"""
    best = None
    if node in distances:
        best = distances[node]
    for ancestor in ancestors[node]:
        # skip ancestors we will never traverse:
        if root_descendants is not None and ancestor not in root_descendants:
            continue
        # An ancestor which is not listed in ancestors will never be in
        # distances, so we pretend it never existed.
        if ancestor not in ancestors:
            continue
        if ancestor not in distances:
            return None
        if best is None or distances[ancestor]+1 > best:
            best = distances[ancestor] + 1
    return best

    
def node_distances(graph, ancestors, start, root_descendants=None):
    """Produce a list of nodes, sorted by distance from a start node.
    This is an algorithm devised by Aaron Bentley, because applying Dijkstra
    backwards seemed too complicated.

    For each node, we walk its descendants.  If all the descendant's ancestors
    have a max-distance-to-start, (excluding ones that can never reach start),
    we calculate their max-distance-to-start, and schedule their descendants.

    So when a node's last parent acquires a distance, it will acquire a
    distance on the next iteration.

    Once we know the max distances for all nodes, we can return a list sorted
    by distance, farthest first.
    """
    distances = {start: 0}
    lines = set([start])
    while len(lines) > 0:
        new_lines = set()
        for line in lines:
            line_descendants = graph[line]
            assert line not in line_descendants, "%s refers to itself" % line
            for descendant in line_descendants:
                distance = max_distance(descendant, ancestors, distances,
                                        root_descendants)
                if distance is None:
                    continue
                distances[descendant] = distance
                new_lines.add(descendant)
        lines = new_lines
    return distances

def nodes_by_distance(distances):
    """Return a list of nodes sorted by distance"""
    def by_distance(n):
        return distances[n],n

    node_list = distances.keys()
    node_list.sort(key=by_distance, reverse=True)
    return node_list

def select_farthest(distances, common):
    """Return the farthest common node, or None if no node qualifies."""
    node_list = nodes_by_distance(distances)
    for node in node_list:
        if node in common:
            return node

def all_descendants(descendants, start):
    """Produce a set of all descendants of the start node.
    The input is a map of node->list of descendants for a graph encompassing
    start.
    """
    result = set()
    lines = set([start])
    while len(lines) > 0:
        new_lines = set()
        for line in lines:
            if line not in descendants:
                continue
            for descendant in descendants[line]:
                if descendant in result:
                    continue
                result.add(descendant)
                new_lines.add(descendant)
        lines = new_lines
    return result


class Graph(object):
    """A graph object which can memoise and cache results for performance."""

    def __init__(self):
        super(Graph, self).__init__()
        self.roots = set([])
        self.ghosts = set([])
        self._graph_ancestors = {}
        self._graph_descendants = {}

    def add_ghost(self, node_id):
        """Add a ghost to the graph."""
        self.ghosts.add(node_id)
        self._ensure_descendant(node_id)

    def add_node(self, node_id, parent_ids):
        """Add node_id to the graph with parent_ids as its parents."""
        if parent_ids == []:
            self.roots.add(node_id)
        self._graph_ancestors[node_id] = list(parent_ids)
        self._ensure_descendant(node_id)
        for parent in parent_ids:
            self._ensure_descendant(parent)
            self._graph_descendants[parent][node_id] = 1
        
    def _ensure_descendant(self, node_id):
        """Ensure that a descendant lookup for node_id will work."""
        if not node_id in self._graph_descendants:
            self._graph_descendants[node_id] = {}

    def get_ancestors(self):
        """Return a dictionary of graph node:ancestor_list entries."""
        return dict(self._graph_ancestors.items())

    def get_descendants(self):
        """Return a dictionary of graph node:child_node:distance entries."""
        return dict(self._graph_descendants.items())
