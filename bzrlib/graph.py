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
    revision,
    symbol_versioning,
    tsort,
    )
from bzrlib.deprecated_graph import (node_distances, select_farthest)

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


class DictParentsProvider(object):
    """A parents provider for Graph objects."""

    def __init__(self, ancestry):
        self.ancestry = ancestry

    def __repr__(self):
        return 'DictParentsProvider(%r)' % self.ancestry

    def get_parent_map(self, keys):
        """See _StackedParentsProvider.get_parent_map"""
        ancestry = self.ancestry
        return dict((k, ancestry[k]) for k in keys if k in ancestry)


class _StackedParentsProvider(object):

    def __init__(self, parent_providers):
        self._parent_providers = parent_providers

    def __repr__(self):
        return "_StackedParentsProvider(%r)" % self._parent_providers

    def get_parent_map(self, keys):
        """Get a mapping of keys => parents

        A dictionary is returned with an entry for each key present in this
        source. If this source doesn't have information about a key, it should
        not include an entry.

        [NULL_REVISION] is used as the parent of the first user-committed
        revision.  Its parent list is empty.

        :param keys: An iterable returning keys to check (eg revision_ids)
        :return: A dictionary mapping each key to its parents
        """
        found = {}
        remaining = set(keys)
        for parents_provider in self._parent_providers:
            new_found = parents_provider.get_parent_map(remaining)
            found.update(new_found)
            remaining.difference_update(new_found)
            if not remaining:
                break
        return found


class CachingParentsProvider(object):
    """A parents provider which will cache the revision => parents in a dict.

    This is useful for providers that have an expensive lookup.
    """

    def __init__(self, parent_provider):
        self._real_provider = parent_provider
        # Theoretically we could use an LRUCache here
        self._cache = {}

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._real_provider)

    def get_parent_map(self, keys):
        """See _StackedParentsProvider.get_parent_map"""
        needed = set()
        # If the _real_provider doesn't have a key, we cache a value of None,
        # which we then later use to realize we cannot provide a value for that
        # key.
        parent_map = {}
        cache = self._cache
        for key in keys:
            if key in cache:
                value = cache[key]
                if value is not None:
                    parent_map[key] = value
            else:
                needed.add(key)

        if needed:
            new_parents = self._real_provider.get_parent_map(needed)
            cache.update(new_parents)
            parent_map.update(new_parents)
            needed.difference_update(new_parents)
            cache.update(dict.fromkeys(needed, None))
        return parent_map


class Graph(object):
    """Provide incremental access to revision graphs.

    This is the generic implementation; it is intended to be subclassed to
    specialize it for other repository types.
    """

    def __init__(self, parents_provider):
        """Construct a Graph that uses several graphs as its input

        This should not normally be invoked directly, because there may be
        specialized implementations for particular repository types.  See
        Repository.get_graph().

        :param parents_provider: An object providing a get_parent_map call
            conforming to the behavior of
            StackedParentsProvider.get_parent_map.
        """
        if getattr(parents_provider, 'get_parents', None) is not None:
            self.get_parents = parents_provider.get_parents
        if getattr(parents_provider, 'get_parent_map', None) is not None:
            self.get_parent_map = parents_provider.get_parent_map
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
        # We may have common ancestors that can be reached from each other.
        # - ask for the heads of them to filter it down to only ones that
        # cannot be reached from each other - phase 2.
        return self.heads(border_common)

    def find_difference(self, left_revision, right_revision):
        """Determine the graph difference between two revisions"""
        border, common, (left, right) = self._find_border_ancestors(
            [left_revision, right_revision])
        return (left.difference(right).difference(common),
                right.difference(left).difference(common))

    @symbol_versioning.deprecated_method(symbol_versioning.one_one)
    def get_parents(self, revisions):
        """Find revision ids of the parents of a list of revisions

        A list is returned of the same length as the input.  Each entry
        is a list of parent ids for the corresponding input revision.

        [NULL_REVISION] is used as the parent of the first user-committed
        revision.  Its parent list is empty.

        If the revision is not present (i.e. a ghost), None is used in place
        of the list of parents.

        Deprecated in bzr 1.2 - please see get_parent_map.
        """
        parents = self.get_parent_map(revisions)
        return [parent.get(r, None) for r in revisions]

    def get_parent_map(self, revisions):
        """Get a map of key:parent_list for revisions.

        This implementation delegates to get_parents, for old parent_providers
        that do not supply get_parent_map.
        """
        result = {}
        for rev, parents in self.get_parents(revisions):
            if parents is not None:
                result[rev] = parents
        return result

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

    def heads(self, keys):
        """Return the heads from amongst keys.

        This is done by searching the ancestries of each key.  Any key that is
        reachable from another key is not returned; all the others are.

        This operation scales with the relative depth between any two keys. If
        any two keys are completely disconnected all ancestry of both sides
        will be retrieved.

        :param keys: An iterable of keys.
        :return: A set of the heads. Note that as a set there is no ordering
            information. Callers will need to filter their input to create
            order if they need it.
        """
        candidate_heads = set(keys)
        if revision.NULL_REVISION in candidate_heads:
            # NULL_REVISION is only a head if it is the only entry
            candidate_heads.remove(revision.NULL_REVISION)
            if not candidate_heads:
                return set([revision.NULL_REVISION])
        if len(candidate_heads) < 2:
            return candidate_heads
        searchers = dict((c, self._make_breadth_first_searcher([c]))
                          for c in candidate_heads)
        active_searchers = dict(searchers)
        # skip over the actual candidate for each searcher
        for searcher in active_searchers.itervalues():
            searcher.next()
        # The common walker finds nodes that are common to two or more of the
        # input keys, so that we don't access all history when a currently
        # uncommon search point actually meets up with something behind a
        # common search point. Common search points do not keep searches
        # active; they just allow us to make searches inactive without
        # accessing all history.
        common_walker = self._make_breadth_first_searcher([])
        while len(active_searchers) > 0:
            ancestors = set()
            # advance searches
            try:
                common_walker.next()
            except StopIteration:
                # No common points being searched at this time.
                pass
            for candidate in active_searchers.keys():
                try:
                    searcher = active_searchers[candidate]
                except KeyError:
                    # rare case: we deleted candidate in a previous iteration
                    # through this for loop, because it was determined to be
                    # a descendant of another candidate.
                    continue
                try:
                    ancestors.update(searcher.next())
                except StopIteration:
                    del active_searchers[candidate]
                    continue
            # process found nodes
            new_common = set()
            for ancestor in ancestors:
                if ancestor in candidate_heads:
                    candidate_heads.remove(ancestor)
                    del searchers[ancestor]
                    if ancestor in active_searchers:
                        del active_searchers[ancestor]
                # it may meet up with a known common node
                if ancestor in common_walker.seen:
                    # some searcher has encountered our known common nodes:
                    # just stop it
                    ancestor_set = set([ancestor])
                    for searcher in searchers.itervalues():
                        searcher.stop_searching_any(ancestor_set)
                else:
                    # or it may have been just reached by all the searchers:
                    for searcher in searchers.itervalues():
                        if ancestor not in searcher.seen:
                            break
                    else:
                        # The final active searcher has just reached this node,
                        # making it be known as a descendant of all candidates,
                        # so we can stop searching it, and any seen ancestors
                        new_common.add(ancestor)
                        for searcher in searchers.itervalues():
                            seen_ancestors =\
                                searcher.find_seen_ancestors(ancestor)
                            searcher.stop_searching_any(seen_ancestors)
            common_walker.start_searching(new_common)
        return candidate_heads

    def find_unique_lca(self, left_revision, right_revision,
                        count_steps=False):
        """Find a unique LCA.

        Find lowest common ancestors.  If there is no unique  common
        ancestor, find the lowest common ancestors of those ancestors.

        Iteration stops when a unique lowest common ancestor is found.
        The graph origin is necessarily a unique lowest common ancestor.

        Note that None is not an acceptable substitute for NULL_REVISION.
        in the input for this method.

        :param count_steps: If True, the return value will be a tuple of
            (unique_lca, steps) where steps is the number of times that
            find_lca was run.  If False, only unique_lca is returned.
        """
        revisions = [left_revision, right_revision]
        steps = 0
        while True:
            steps += 1
            lca = self.find_lca(*revisions)
            if len(lca) == 1:
                result = lca.pop()
                if count_steps:
                    return result, steps
                else:
                    return result
            if len(lca) == 0:
                raise errors.NoCommonAncestor(left_revision, right_revision)
            revisions = lca

    def iter_topo_order(self, revisions):
        """Iterate through the input revisions in topological order.

        This sorting only ensures that parents come before their children.
        An ancestor may sort after a descendant if the relationship is not
        visible in the supplied list of revisions.
        """
        sorter = tsort.TopoSorter(self.get_parent_map(revisions))
        return sorter.iter_topo_order()

    def is_ancestor(self, candidate_ancestor, candidate_descendant):
        """Determine whether a revision is an ancestor of another.

        We answer this using heads() as heads() has the logic to perform the
        smallest number of parent lookups to determine the ancestral
        relationship between N revisions.
        """
        return set([candidate_descendant]) == self.heads(
            [candidate_ancestor, candidate_descendant])


class HeadsCache(object):
    """A cache of results for graph heads calls."""

    def __init__(self, graph):
        self.graph = graph
        self._heads = {}

    def heads(self, keys):
        """Return the heads of keys.

        This matches the API of Graph.heads(), specifically the return value is
        a set which can be mutated, and ordering of the input is not preserved
        in the output.

        :see also: Graph.heads.
        :param keys: The keys to calculate heads for.
        :return: A set containing the heads, which may be mutated without
            affecting future lookups.
        """
        keys = frozenset(keys)
        try:
            return set(self._heads[keys])
        except KeyError:
            heads = self.graph.heads(keys)
            self._heads[keys] = heads
            return set(heads)


class HeadsCache(object):
    """A cache of results for graph heads calls."""

    def __init__(self, graph):
        self.graph = graph
        self._heads = {}

    def heads(self, keys):
        """Return the heads of keys.

        :see also: Graph.heads.
        :param keys: The keys to calculate heads for.
        :return: A set containing the heads, which may be mutated without
            affecting future lookups.
        """
        keys = frozenset(keys)
        try:
            return set(self._heads[keys])
        except KeyError:
            heads = self.graph.heads(keys)
            self._heads[keys] = heads
            return set(heads)


class _BreadthFirstSearcher(object):
    """Parallel search breadth-first the ancestry of revisions.

    This class implements the iterator protocol, but additionally
    1. provides a set of seen ancestors, and
    2. allows some ancestries to be unsearched, via stop_searching_any
    """

    def __init__(self, revisions, parents_provider):
        self._iterations = 0
        self._next_query = set(revisions)
        self.seen = set()
        self._parents_provider = parents_provider
        self._returning = 'next_with_ghosts'

    def __repr__(self):
        if self._iterations:
            prefix = "searching"
        else:
            prefix = "starting"
        search = '%s=%r' % (prefix, list(self._next_query))
        return ('_BreadthFirstSearcher(iterations=%d, %s,'
                ' seen=%r)' % (self._iterations, search, list(self.seen)))

    def next(self):
        """Return the next ancestors of this revision.

        Ancestors are returned in the order they are seen in a breadth-first
        traversal.  No ancestor will be returned more than once. Ancestors are
        returned before their parentage is queried, so ghosts and missing
        revisions (including the start revisions) are included in the result.
        This can save a round trip in LCA style calculation by allowing
        convergence to be detected without reading the data for the revision
        the convergence occurs on.

        :return: A set of revision_ids.
        """
        if self._returning != 'next':
            # switch to returning the query, not the results.
            self._returning = 'next'
            self._iterations += 1
            self.seen.update(self._next_query)
        else:
            self._advance()
        if len(self._next_query) == 0:
            raise StopIteration()
        return self._next_query

    def next_with_ghosts(self):
        """Return the next found ancestors, with ghosts split out.
        
        Ancestors are returned in the order they are seen in a breadth-first
        traversal.  No ancestor will be returned more than once. Ancestors are
        returned only after asking for their parents, which allows us to detect
        which revisions are ghosts and which are not.

        :return: A tuple with (present ancestors, ghost ancestors) sets.
        """
        if self._returning != 'next_with_ghosts':
            # switch to returning the results, not the current query.
            self._returning = 'next_with_ghosts'
            self._advance()
        if len(self._next_query) == 0:
            raise StopIteration()
        self._advance()
        return self._current_present, self._current_ghosts

    def _advance(self):
        """Advance the search.

        Updates self.seen, self._next_query, self._current_present,
        self._current_ghosts, self._current_parents and self._iterations.
        """
        self._iterations += 1
        found, ghosts, next, parents = self._do_query(self._next_query)
        self._current_present = found
        self._current_ghosts = ghosts
        self._next_query = next
        self._current_parents = parents

    def _do_query(self, revisions):
        """Query for revisions.

        :param revisions: Revisions to query.
        :return: A tuple: (set(found_revisions), set(ghost_revisions),
           set(parents_of_found_revisions), dict(found_revisions:parents)).
        """
        found_parents = set()
        parents_of_found = set()
        parent_map = self._parents_provider.get_parent_map(revisions)
        for rev_id, parents in parent_map.iteritems():
            found_parents.add(rev_id)
            parents_of_found.update(p for p in parents if p not in self.seen)
        ghost_parents = revisions - found_parents
        self.seen.update(parents_of_found)
        return found_parents, ghost_parents, parents_of_found, parent_map

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
        revisions = frozenset(revisions)
        if self._returning == 'next':
            stopped = self._next_query.intersection(revisions)
            self._next_query = self._next_query.difference(revisions)
        else:
            stopped = set()
            stopped.update(self._current_present.intersection(revisions))
            stopped.update(self._current_ghosts.intersection(revisions))
            self._current_present.difference_update(stopped)
            self._current_ghosts.difference_update(stopped)
            # stopping 'x' should stop returning parents of 'x', but 
            # not if 'y' always references those same parents
            stop_rev_references = {}
            for rev in stopped:
                for parent_id in self._current_parents[rev]:
                    if parent_id not in stop_rev_references:
                        stop_rev_references[parent_id] = 0
                    stop_rev_references[parent_id] += 1
            # if only the stopped revisions reference it, the ref count will be
            # 0 after this loop
            for parents in self._current_parents.itervalues():
                for parent_id in parents:
                    try:
                        stop_rev_references[parent_id] -= 1
                    except KeyError:
                        pass
            stop_parents = set()
            for rev_id, refs in stop_rev_references.iteritems():
                if refs == 0:
                    stop_parents.add(rev_id)
            self._next_query.difference_update(stop_parents)
        return stopped

    def start_searching(self, revisions):
        """Add revisions to the search.

        The parents of revisions will be returned from the next call to next()
        or next_with_ghosts(). If next_with_ghosts was the most recently used
        next* call then the return value is the result of looking up the
        ghost/not ghost status of revisions. (A tuple (present, ghosted)).
        """
        revisions = frozenset(revisions)
        if self._returning == 'next':
            self._next_query.update(revisions.difference(self.seen))
            self.seen.update(revisions)
        else:
            # perform a query on revisions
            revs, ghosts, query, parents = self._do_query(revisions)
            self._current_present.update(revs)
            self._current_ghosts.update(ghosts)
            self._next_query.update(query)
            self._current_parents.update(parents)
            return revs, ghosts
