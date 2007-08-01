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

from bzrlib import (
    errors,
    tsort,
    )
from bzrlib.deprecated_graph import (node_distances, select_farthest)
from bzrlib.revision import NULL_REVISION

# DIAGRAM of terminology
#       A
#       /\
#      B  C
#      |  |\
#      D  E F
#      |\/| |
#      |/\|/
#      G  H
#
# In this diagram, relative to G and H:
# A, B, C, D, E are common ancestors.
# C, D and E are border ancestors, because each has a non-common descendant.
# D and E are least common ancestors because none of their descendants are
# common ancestors.
# C is not a least common ancestor because its descendant, E, is a common
# ancestor.
#
# The find_unique_lca algorithm will pick A in two steps:
# 1. find_lca('G', 'H') => ['D', 'E']
# 2. Since len(['D', 'E']) > 1, find_lca('D', 'E') => ['A']



class _StackedParentsProvider(object):

    def __init__(self, parent_providers):
        self._parent_providers = parent_providers

    def __repr__(self):
        return "_StackedParentsProvider(%r)" % self._parent_providers

    def get_parents(self, revision_ids):
        """Find revision ids of the parents of a list of revisions

        A list is returned of the same length as the input.  Each entry
        is a list of parent ids for the corresponding input revision.

        [NULL_REVISION] is used as the parent of the first user-committed
        revision.  Its parent list is empty.

        If the revision is not present (i.e. a ghost), None is used in place
        of the list of parents.
        """
        found = {}
        for parents_provider in self._parent_providers:
            pending_revisions = [r for r in revision_ids if r not in found]
            parent_list = parents_provider.get_parents(pending_revisions)
            new_found = dict((k, v) for k, v in zip(pending_revisions,
                             parent_list) if v is not None)
            found.update(new_found)
            if len(found) == len(revision_ids):
                break
        return [found.get(r, None) for r in revision_ids]


class Graph(object):
    """Provide incremental access to revision graphs.

    This is the generic implementation; it is intended to be subclassed to
    specialize it for other repository types.
    """

    def __init__(self, parents_provider):
        """Construct a Graph that uses several graphs as its input

        This should not normally be invoked directly, because there may be
        specialized implementations for particular repository types.  See
        Repository.get_graph()

        :param parents_func: an object providing a get_parents call
            conforming to the behavior of StackedParentsProvider.get_parents
        """
        self.get_parents = parents_provider.get_parents
        self._parents_provider = parents_provider

    def __repr__(self):
        return 'Graph(%r)' % self._parents_provider

    def find_lca(self, *revisions):
        """Determine the lowest common ancestors of the provided revisions

        A lowest common ancestor is a common ancestor none of whose
        descendants are common ancestors.  In graphs, unlike trees, there may
        be multiple lowest common ancestors.

        This algorithm has two phases.  Phase 1 identifies border ancestors,
        and phase 2 filters border ancestors to determine lowest common
        ancestors.

        In phase 1, border ancestors are identified, using a breadth-first
        search starting at the bottom of the graph.  Searches are stopped
        whenever a node or one of its descendants is determined to be common

        In phase 2, the border ancestors are filtered to find the least
        common ancestors.  This is done by searching the ancestries of each
        border ancestor.

        Phase 2 is perfomed on the principle that a border ancestor that is
        not an ancestor of any other border ancestor is a least common
        ancestor.

        Searches are stopped when they find a node that is determined to be a
        common ancestor of all border ancestors, because this shows that it
        cannot be a descendant of any border ancestor.

        The scaling of this operation should be proportional to
        1. The number of uncommon ancestors
        2. The number of border ancestors
        3. The length of the shortest path between a border ancestor and an
           ancestor of all border ancestors.
        """
        border_common, common, sides = self._find_border_ancestors(revisions)
        return self._filter_candidate_lca(border_common)

    def find_difference(self, left_revision, right_revision):
        """Determine the graph difference between two revisions"""
        border, common, (left, right) = self._find_border_ancestors(
            [left_revision, right_revision])
        return (left.difference(right).difference(common),
                right.difference(left).difference(common))

    def _make_breadth_first_searcher(self, revisions):
        return _BreadthFirstSearcher(revisions, self)

    def _find_border_ancestors(self, revisions):
        """Find common ancestors with at least one uncommon descendant.

        Border ancestors are identified using a breadth-first
        search starting at the bottom of the graph.  Searches are stopped
        whenever a node or one of its descendants is determined to be common.

        This will scale with the number of uncommon ancestors.

        As well as the border ancestors, a set of seen common ancestors and a
        list of sets of seen ancestors for each input revision is returned.
        This allows calculation of graph difference from the results of this
        operation.
        """
        if None in revisions:
            raise errors.InvalidRevisionId(None, self)
        common_searcher = self._make_breadth_first_searcher([])
        common_ancestors = set()
        searchers = [self._make_breadth_first_searcher([r])
                     for r in revisions]
        active_searchers = searchers[:]
        border_ancestors = set()
        def update_common(searcher, revisions):
            w_seen_ancestors = searcher.find_seen_ancestors(
                revision)
            stopped = searcher.stop_searching_any(w_seen_ancestors)
            common_ancestors.update(w_seen_ancestors)
            common_searcher.start_searching(stopped)

        while True:
            if len(active_searchers) == 0:
                return border_ancestors, common_ancestors, [s.seen for s in
                                                            searchers]
            try:
                new_common = common_searcher.next()
                common_ancestors.update(new_common)
            except StopIteration:
                pass
            else:
                for searcher in active_searchers:
                    for revision in new_common.intersection(searcher.seen):
                        update_common(searcher, revision)

            newly_seen = set()
            new_active_searchers = []
            for searcher in active_searchers:
                try:
                    newly_seen.update(searcher.next())
                except StopIteration:
                    pass
                else:
                    new_active_searchers.append(searcher)
            active_searchers = new_active_searchers
            for revision in newly_seen:
                if revision in common_ancestors:
                    for searcher in searchers:
                        update_common(searcher, revision)
                    continue
                for searcher in searchers:
                    if revision not in searcher.seen:
                        break
                else:
                    border_ancestors.add(revision)
                    for searcher in searchers:
                        update_common(searcher, revision)

    def _filter_candidate_lca(self, candidate_lca):
        """Remove candidates which are ancestors of other candidates.

        This is done by searching the ancestries of each border ancestor.  It
        is perfomed on the principle that a border ancestor that is not an
        ancestor of any other border ancestor is a lowest common ancestor.

        Searches are stopped when they find a node that is determined to be a
        common ancestor of all border ancestors, because this shows that it
        cannot be a descendant of any border ancestor.

        This will scale with the number of candidate ancestors and the length
        of the shortest path from a candidate to an ancestor common to all
        candidates.
        """
        searchers = dict((c, self._make_breadth_first_searcher([c]))
                          for c in candidate_lca)
        active_searchers = dict(searchers)
        # skip over the actual candidate for each searcher
        for searcher in active_searchers.itervalues():
            x = searcher.next()
        while len(active_searchers) > 0:
            for candidate in active_searchers.keys():
                try:
                    searcher = active_searchers[candidate]
                except KeyError:
                    # rare case: we deleted candidate in a previous iteration
                    # through this for loop, because it was determined to be
                    # a descendant of another candidate.
                    continue
                try:
                    ancestors = searcher.next()
                except StopIteration:
                    del active_searchers[candidate]
                    continue
                for ancestor in ancestors:
                    if ancestor in candidate_lca:
                        candidate_lca.remove(ancestor)
                        del searchers[ancestor]
                        if ancestor in active_searchers:
                            del active_searchers[ancestor]
                    for searcher in searchers.itervalues():
                        if ancestor not in searcher.seen:
                            break
                    else:
                        # if this revision was seen by all searchers, then it
                        # is a descendant of all candidates, so we can stop
                        # searching it, and any seen ancestors
                        for searcher in searchers.itervalues():
                            seen_ancestors =\
                                searcher.find_seen_ancestors(ancestor)
                            searcher.stop_searching_any(seen_ancestors)
        return candidate_lca

    def find_unique_lca(self, left_revision, right_revision):
        """Find a unique LCA.

        Find lowest common ancestors.  If there is no unique  common
        ancestor, find the lowest common ancestors of those ancestors.

        Iteration stops when a unique lowest common ancestor is found.
        The graph origin is necessarily a unique lowest common ancestor.

        Note that None is not an acceptable substitute for NULL_REVISION.
        in the input for this method.
        """
        revisions = [left_revision, right_revision]
        while True:
            lca = self.find_lca(*revisions)
            if len(lca) == 1:
                return lca.pop()
            if len(lca) == 0:
                raise errors.NoCommonAncestor(left_revision, right_revision)
            revisions = lca

    def iter_topo_order(self, revisions):
        """Iterate through the input revisions in topological order.

        This sorting only ensures that parents come before their children.
        An ancestor may sort after a descendant if the relationship is not
        visible in the supplied list of revisions.
        """
        sorter = tsort.TopoSorter(zip(revisions, self.get_parents(revisions)))
        return sorter.iter_topo_order()

    def is_ancestor(self, candidate_ancestor, candidate_descendant):
        """Determine whether a revision is an ancestor of another.

        There are two possible outcomes: True and False, but there are three
        possible relationships:

        a) candidate_ancestor is an ancestor of candidate_descendant
        b) candidate_ancestor is an descendant of candidate_descendant
        c) candidate_ancestor is an sibling of candidate_descendant

        To check for a, we walk from candidate_descendant, looking for
        candidate_ancestor.

        To check for b, we walk from candidate_ancestor, looking for
        candidate_descendant.

        To make a and b more efficient, we can stop any searches that hit
        common ancestors.

        If we exhaust our searches, but neither a or b is true, then c is true.

        In order to find c efficiently, we must avoid searching from
        candidate_descendant or candidate_ancestor into common ancestors.  But
        if we don't search common ancestors at all, we won't know if we hit
        common ancestors.  So we have a walker for common ancestors.  Note that
        its searches are not required to terminate in order to determine c to
        be true.
        """
        ancestor_walker = self._make_breadth_first_searcher(
            [candidate_ancestor])
        descendant_walker = self._make_breadth_first_searcher(
            [candidate_descendant])
        common_walker = self._make_breadth_first_searcher([])
        active_ancestor = True
        active_descendant = True
        while (active_ancestor or active_descendant):
            new_common = set()
            if active_descendant:
                try:
                    nodes = descendant_walker.next()
                except StopIteration:
                    active_descendant = False
                else:
                    if candidate_ancestor in nodes:
                        return True
                    new_common.update(nodes.intersection(ancestor_walker.seen))
            if active_ancestor:
                try:
                    nodes = ancestor_walker.next()
                except StopIteration:
                    active_ancestor = False
                else:
                    if candidate_descendant in nodes:
                        return False
                    new_common.update(nodes.intersection(
                        descendant_walker.seen))
            try:
                new_common.update(common_walker.next())
            except StopIteration:
                pass
            for walker in (ancestor_walker, descendant_walker):
                for node in new_common:
                    c_ancestors = walker.find_seen_ancestors(node)
                    walker.stop_searching_any(c_ancestors)
                common_walker.start_searching(new_common)
        return False


class _BreadthFirstSearcher(object):
    """Parallel search the breadth-first the ancestry of revisions.

    This class implements the iterator protocol, but additionally
    1. provides a set of seen ancestors, and
    2. allows some ancestries to be unsearched, via stop_searching_any
    """

    def __init__(self, revisions, parents_provider):
        self._start = set(revisions)
        self._search_revisions = None
        self.seen = set(revisions)
        self._parents_provider = parents_provider 

    def __repr__(self):
        return ('_BreadthFirstSearcher(self._search_revisions=%r,'
                ' self.seen=%r)' % (self._search_revisions, self.seen))

    def next(self):
        """Return the next ancestors of this revision.

        Ancestors are returned in the order they are seen in a breadth-first
        traversal.  No ancestor will be returned more than once.
        """
        if self._search_revisions is None:
            self._search_revisions = self._start
        else:
            new_search_revisions = set()
            for parents in self._parents_provider.get_parents(
                self._search_revisions):
                if parents is None:
                    continue
                new_search_revisions.update(p for p in parents if
                                            p not in self.seen)
            self._search_revisions = new_search_revisions
        if len(self._search_revisions) == 0:
            raise StopIteration()
        self.seen.update(self._search_revisions)
        return self._search_revisions

    def __iter__(self):
        return self

    def find_seen_ancestors(self, revision):
        """Find ancestors of this revision that have already been seen."""
        searcher = _BreadthFirstSearcher([revision], self._parents_provider)
        seen_ancestors = set()
        for ancestors in searcher:
            for ancestor in ancestors:
                if ancestor not in self.seen:
                    searcher.stop_searching_any([ancestor])
                else:
                    seen_ancestors.add(ancestor)
        return seen_ancestors

    def stop_searching_any(self, revisions):
        """
        Remove any of the specified revisions from the search list.

        None of the specified revisions are required to be present in the
        search list.  In this case, the call is a no-op.
        """
        stopped = self._search_revisions.intersection(revisions)
        self._search_revisions = self._search_revisions.difference(revisions)
        return stopped

    def start_searching(self, revisions):
        if self._search_revisions is None:
            self._start = set(revisions)
        else:
            self._search_revisions.update(revisions.difference(self.seen))
        self.seen.update(revisions)
