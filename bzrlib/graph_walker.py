# Copyright (C) 2007 Canonical Ltd
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

from bzrlib import graph
from bzrlib.revision import NULL_REVISION


class GraphWalker(object):
    """Provide incremental access to revision graphs"""

    def __init__(self, graph):
        self._graph = graph
        self._ancestors = dict(self._graph.get_ancestors())
        self._descendants = dict(self._graph.get_descendants())
        self._descendants[NULL_REVISION] = {}
        self._ancestors[NULL_REVISION] = []
        for root in self._graph.roots:
            self._descendants[NULL_REVISION][root] = 1
            self._ancestors[root] = self._ancestors[root] + [NULL_REVISION]
        for ghost in self._graph.ghosts:
            # ghosts act as roots for the purpose of finding
            # the longest paths from the root: any ghost *might*
            # be directly attached to the root, so we treat them
            # as being such.
            # ghost now descends from NULL
            self._descendants[NULL_REVISION][ghost] = 1
            # that is it has an ancestor of NULL
            self._ancestors[ghost] = [NULL_REVISION]

    def distance_from_origin(self, revisions):
        """Determine the of the named revisions from the origin

        :param revisions: The revisions to examine
        :return: A list of revision distances.  None is provided if no distance
            could be found.
        """
        distances = graph.node_distances(self._descendants, self._ancestors,
                                         NULL_REVISION)
        return [distances.get(r) for r in revisions]

    def minimal_common(self, *revisions):
        """Determine the minimal common ancestors of the provided revisions

        A minimal common ancestor is a common ancestor none of whose
        descendants are common ancestors.  (This is not quite the standard
        graph theory definition)
        """
        common = set(self._get_ancestry(revisions[0]))
        for revision in revisions[1:]:
            common.intersection_update(self._get_ancestry(revision))
        common.add(NULL_REVISION)
        mca = set()
        for ancestor in common:
            if len([d for d in self._descendants.get(ancestor, []) if d in
                    common]) == 0:
                mca.add(ancestor)
        return mca

    def unique_common(self, left_revision, right_revision):
        """Find a unique minimal common ancestor.

        Find minimal common ancestors.  If there is no unique minimal common
        ancestor, find the minimal common ancestors of those ancestors.

        Iteration stops when a unique minimal common ancestor is found.
        The graph origin is necessarily a unique common ancestor

        Note that None is not an acceptable substitute for NULL_REVISION.
        """
        revisions = [left_revision, right_revision]
        while True:
            minimal = self.minimal_common(*revisions)
            if len(minimal) == 1:
                return minimal.pop()
            revisions = minimal

    def _get_ancestry(self, revision):
        if revision == NULL_REVISION:
            ancestry = []
        else:
            ancestry = self._graph.get_ancestry(revision)
        ancestry.append(NULL_REVISION)
        return ancestry
