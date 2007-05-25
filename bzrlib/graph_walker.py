from bzrlib import graph
from bzrlib.revision import NULL_REVISION

class GraphWalker(object):
    """Provide incremental access to revision graphs"""

    def __init__(self, graph):
        self._graph = graph

    def distance_from_origin(self, revisions):
        ancestors = self._graph.get_ancestors()
        descendants = self._graph.get_descendants()
        descendants[NULL_REVISION] = {}
        ancestors[NULL_REVISION] = []
        for root in self._graph.roots:
            descendants[NULL_REVISION][root] = 1
            ancestors[root].append(NULL_REVISION)
        for ghost in self._graph.ghosts:
            # ghosts act as roots for the purpose of finding
            # the longest paths from the root: any ghost *might*
            # be directly attached to the root, so we treat them
            # as being such.
            # ghost now descends from NULL
            descendants[NULL_REVISION][ghost] = 1
            # that is it has an ancestor of NULL
            ancestors[ghost] = [NULL_REVISION]
        distances = graph.node_distances(descendants, ancestors,
                                         NULL_REVISION)
        return [distances.get(r) for r in revisions]
