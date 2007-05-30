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
    """Provide incremental access to revision graphs.

    This is the generic implementation; it is intended to be subclassed to
    specialize it for other repository types.
    """

    def __init__(self, graphs):
        """Construct a GraphWalker that uses several graphs as its input

        This should not normally be invoked directly, because there may be
        specialized implementations for particular repository types.  See
        Repository.get_graph_walker()

        Note that the imput graphs *will* be altered to use NULL_REVISION as
        their origin.
        """
        self._graph = graphs
        self._ancestors = []
        self._descendants = []
        for graph in graphs:
            self._extract_data(graph)

    def _extract_data(self, graph):
        """Convert graph to use NULL_REVISION as origin"""
        ancestors = dict(graph.get_ancestors())
        descendants = dict(graph.get_descendants())
        descendants[NULL_REVISION] = {}
        ancestors[NULL_REVISION] = []
        for root in graph.roots:
            descendants[NULL_REVISION][root] = 1
            ancestors[root] = ancestors[root] + [NULL_REVISION]
        for ghost in graph.ghosts:
            # ghosts act as roots for the purpose of finding
            # the longest paths from the root: any ghost *might*
            # be directly attached to the root, so we treat them
            # as being such.
            # ghost now descends from NULL
            descendants[NULL_REVISION][ghost] = 1
            # that is it has an ancestor of NULL
            ancestors[ghost] = [NULL_REVISION]
        self._ancestors.append(ancestors)
        self._descendants.append(descendants)

    def distance_from_origin(self, revisions):
        """Determine the of the named revisions from the origin

        :param revisions: The revisions to examine
        :return: A list of revision distances.  None is provided if no distance
            could be found.
        """
        distances = graph.node_distances(self._descendants[0],
                                         self._ancestors[0],
                                         NULL_REVISION)
        return [distances.get(r) for r in revisions]

    def distinct_common(self, *revisions):
        """Determine the distinct common ancestors of the provided revisions

        A distinct common ancestor is a common ancestor none of whose
        descendants are common ancestors.
        """
        border_common = self._find_border_ancestors(revisions)
        return self._filter_candidate_dca(border_common)

    def _find_border_ancestors(self, revisions):
        """Find common ancestors with at least one uncommon descendant"""
        walkers = [_AncestryWalker(r, self) for r in revisions]
        active_walkers = walkers[:]
        maybe_distinct_common = set()
        seen_ancestors = set()
        while True:
            if len(active_walkers) == 0:
                return maybe_distinct_common
            newly_seen = set()
            new_active_walkers = []
            for walker in active_walkers:
                try:
                    newly_seen.update(walker.next())
                except StopIteration:
                    pass
                else:
                    new_active_walkers.append(walker)
            active_walkers = new_active_walkers
            for revision in newly_seen:
                for walker in walkers:
                    if revision not in walker.seen:
                        break
                else:
                    maybe_distinct_common.add(revision)
                    for walker in walkers:
                        w_seen_ancestors = walker.find_seen_ancestors(revision)
                        walker.stop_searching_any(w_seen_ancestors)

    def _filter_candidate_dca(self, candidate_dca):
        """Remove candidates which are ancestors of other candidates"""
        walkers = dict((c, _AncestryWalker(c, self)) for c in candidate_dca)
        active_walkers = dict(walkers)
        # skip over the actual candidate for each walker
        for walker in active_walkers.itervalues():
            walker.next()
        while len(active_walkers) > 0:
            for candidate, walker in list(active_walkers.iteritems()):
                try:
                    ancestors = walker.next()
                except StopIteration:
                    del active_walkers[candidate]
                    continue
                for ancestor in ancestors:
                    if ancestor in candidate_dca:
                        candidate_dca.remove(ancestor)
                        del walkers[ancestor]
                        if ancestor in active_walkers:
                            del active_walkers[ancestor]
                    for walker in walkers.itervalues():
                        if ancestor not in walker.seen:
                            break
                    else:
                        # if this revision was seen by all walkers, then it
                        # is a descendant of all candidates, so we can stop
                        # searching it, and any seen ancestors
                        for walker in walkers.itervalues():
                            seen_ancestors =\
                                walker.find_seen_ancestors(ancestor)
                            walker.stop_searching_any(seen_ancestors)
        return candidate_dca

    def unique_common(self, left_revision, right_revision):
        """Find a unique distinct common ancestor.

        Find distinct common ancestors.  If there is no unique distinct common
        ancestor, find the distinct common ancestors of those ancestors.

        Iteration stops when a unique distinct common ancestor is found.
        The graph origin is necessarily a unique common ancestor

        Note that None is not an acceptable substitute for NULL_REVISION.
        """
        revisions = [left_revision, right_revision]
        while True:
            distinct = self.distinct_common(*revisions)
            if len(distinct) == 1:
                return distinct.pop()
            revisions = distinct

    def get_parents(self, revision):
        """Determine the parents of a revision"""
        for ancestors in self._ancestors:
            try:
                return ancestors[revision]
            except KeyError:
                pass
        else:
            raise KeyError


class _AncestryWalker(object):
    """Walk the ancestry of a single revision.

    This class implements the iterator protocol, but additionally
    1. provides a set of seen ancestors, and
    2. allows some ancestries to be unsearched, via stop_searching_any
    """

    def __init__(self, revision, graph_walker):
        self._start = set([revision])
        self._search_revisions = None
        self.seen = set()
        self._graph_walker = graph_walker

    def __repr__(self):
        return '_AncestryWalker(self._search_revisions=%r, self.seen=%r)' %\
            (self._search_revisions, self.seen)

    def next(self):
        """Return the next ancestors of this revision.

        Ancestors are returned in the order they are seen.  No ancestor will
        be returned more than once.
        """
        if self._search_revisions is None:
            self._search_revisions = self._start
        else:
            new_search_revisions = set()
            for revision in self._search_revisions:
                new_search_revisions.update(p for p in
                                 self._graph_walker.get_parents(revision) if p
                                 not in self.seen)
            self._search_revisions = new_search_revisions
        if len(self._search_revisions) == 0:
            raise StopIteration()
        self.seen.update(self._search_revisions)
        return self._search_revisions

    def __iter__(self):
        return self

    def find_seen_ancestors(self, revision):
        """Find ancstors of this revision that have already been seen."""
        walker = _AncestryWalker(revision, self._graph_walker)
        seen_ancestors = set()
        for ancestors in walker:
            for ancestor in ancestors:
                if ancestor not in self.seen:
                    walker.stop_searching_any([ancestor])
                else:
                    seen_ancestors.add(ancestor)
        return seen_ancestors

    def stop_searching_any(self, revisions):
        """
        Remove any of the specified revisions from the search list.

        None of the specified revisions are required to be present in the
        search list.
        """
        self._search_revisions = set(l for l in self._search_revisions
                                     if l not in revisions)
