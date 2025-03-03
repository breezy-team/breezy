# Copyright (C) 2007-2011 Canonical Ltd
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

"""Searching in versioned file repositories."""

import itertools

from .. import debug, revision, trace
from ..graph import DictParentsProvider, Graph, invert_parent_map
from ..repository import AbstractSearchResult


class AbstractSearch:
    """A search that can be executed, producing a search result.

    :seealso: AbstractSearchResult
    """

    def execute(self):
        """Construct a network-ready search result from this search description.

        This may take some time to search repositories, etc.

        :return: A search result (an object that implements
            AbstractSearchResult's API).
        """
        raise NotImplementedError(self.execute)


class SearchResult(AbstractSearchResult):
    """The result of a breadth first search.

    A SearchResult provides the ability to reconstruct the search or access a
    set of the keys the search found.
    """

    def __init__(self, start_keys, exclude_keys, key_count, keys):
        """Create a SearchResult.

        :param start_keys: The keys the search started at.
        :param exclude_keys: The keys the search excludes.
        :param key_count: The total number of keys (from start to but not
            including exclude).
        :param keys: The keys the search found. Note that in future we may get
            a SearchResult from a smart server, in which case the keys list is
            not necessarily immediately available.
        """
        self._recipe = ("search", start_keys, exclude_keys, key_count)
        self._keys = frozenset(keys)

    def __repr__(self):
        kind, start_keys, exclude_keys, key_count = self._recipe
        if len(start_keys) > 5:
            start_keys_repr = repr(list(start_keys)[:5])[:-1] + ", ...]"
        else:
            start_keys_repr = repr(start_keys)
        if len(exclude_keys) > 5:
            exclude_keys_repr = repr(list(exclude_keys)[:5])[:-1] + ", ...]"
        else:
            exclude_keys_repr = repr(exclude_keys)
        return f"<{self.__class__.__name__} {kind}:({start_keys_repr}, {exclude_keys_repr}, {key_count})>"

    def get_recipe(self):
        """Return a recipe that can be used to replay this search.

        The recipe allows reconstruction of the same results at a later date
        without knowing all the found keys. The essential elements are a list
        of keys to start and to stop at. In order to give reproducible
        results when ghosts are encountered by a search they are automatically
        added to the exclude list (or else ghost filling may alter the
        results).

        :return: A tuple ('search', start_keys_set, exclude_keys_set,
            revision_count). To recreate the results of this search, create a
            breadth first searcher on the same graph starting at start_keys.
            Then call next() (or next_with_ghosts()) repeatedly, and on every
            result, call stop_searching_any on any keys from the exclude_keys
            set. The revision_count value acts as a trivial cross-check - the
            found revisions of the new search should have as many elements as
            revision_count. If it does not, then additional revisions have been
            ghosted since the search was executed the first time and the second
            time.
        """
        return self._recipe

    def get_network_struct(self):
        start_keys = b" ".join(self._recipe[1])
        stop_keys = b" ".join(self._recipe[2])
        count = str(self._recipe[3]).encode("ascii")
        return (
            self._recipe[0].encode("ascii"),
            b"\n".join((start_keys, stop_keys, count)),
        )

    def get_keys(self):
        """Return the keys found in this search.

        :return: A set of keys.
        """
        return self._keys

    def is_empty(self):
        """Return false if the search lists 1 or more revisions."""
        return self._recipe[3] == 0

    def refine(self, seen, referenced):
        """Create a new search by refining this search.

        :param seen: Revisions that have been satisfied.
        :param referenced: Revision references observed while satisfying some
            of this search.
        """
        start = self._recipe[1]
        exclude = self._recipe[2]
        count = self._recipe[3]
        keys = self.get_keys()
        # New heads = referenced + old heads - seen things - exclude
        pending_refs = set(referenced)
        pending_refs.update(start)
        pending_refs.difference_update(seen)
        pending_refs.difference_update(exclude)
        # New exclude = old exclude + satisfied heads
        seen_heads = start.intersection(seen)
        exclude.update(seen_heads)
        # keys gets seen removed
        keys = keys - seen
        # length is reduced by len(seen)
        count -= len(seen)
        return SearchResult(pending_refs, exclude, count, keys)


class PendingAncestryResult(AbstractSearchResult):
    """A search result that will reconstruct the ancestry for some graph heads.

    Unlike SearchResult, this doesn't hold the complete search result in
    memory, it just holds a description of how to generate it.
    """

    def __init__(self, heads, repo):
        """Constructor.

        :param heads: an iterable of graph heads.
        :param repo: a repository to use to generate the ancestry for the given
            heads.
        """
        self.heads = frozenset(heads)
        self.repo = repo

    def __repr__(self):
        if len(self.heads) > 5:
            heads_repr = repr(list(self.heads)[:5])[:-1]
            heads_repr += f", <{len(self.heads) - 5} more>...]"
        else:
            heads_repr = repr(self.heads)
        return "<{} heads:{} repo:{!r}>".format(
            self.__class__.__name__, heads_repr, self.repo
        )

    def get_recipe(self):
        """Return a recipe that can be used to replay this search.

        The recipe allows reconstruction of the same results at a later date.

        :seealso SearchResult.get_recipe:

        :return: A tuple ('proxy-search', start_keys_set, set(), -1)
            To recreate this result, create a PendingAncestryResult with the
            start_keys_set.
        """
        return ("proxy-search", self.heads, set(), -1)

    def get_network_struct(self):
        parts = [b"ancestry-of"]
        parts.extend(self.heads)
        return parts

    def get_keys(self):
        """See SearchResult.get_keys.

        Returns all the keys for the ancestry of the heads, excluding
        NULL_REVISION.
        """
        return self._get_keys(self.repo.get_graph())

    def _get_keys(self, graph):
        NULL_REVISION = revision.NULL_REVISION
        keys = [
            key
            for (key, parents) in graph.iter_ancestry(self.heads)
            if key != NULL_REVISION and parents is not None
        ]
        return keys

    def is_empty(self):
        """Return false if the search lists 1 or more revisions."""
        if revision.NULL_REVISION in self.heads:
            return len(self.heads) == 1
        else:
            return len(self.heads) == 0

    def refine(self, seen, referenced):
        """Create a new search by refining this search.

        :param seen: Revisions that have been satisfied.
        :param referenced: Revision references observed while satisfying some
            of this search.
        """
        referenced = self.heads.union(referenced)
        return PendingAncestryResult(referenced - seen, self.repo)


class EmptySearchResult(AbstractSearchResult):
    """An empty search result."""

    def is_empty(self):
        return True


class EverythingResult(AbstractSearchResult):
    """A search result that simply requests everything in the repository."""

    def __init__(self, repo):
        self._repo = repo

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, self._repo)

    def get_recipe(self):
        raise NotImplementedError(self.get_recipe)

    def get_network_struct(self):
        return (b"everything",)

    def get_keys(self):
        if "evil" in debug.debug_flags:
            from . import remote

            if isinstance(self._repo, remote.RemoteRepository):
                # warn developers (not users) not to do this
                trace.mutter_callsite(
                    2, "EverythingResult(RemoteRepository).get_keys() is slow."
                )
        return self._repo.all_revision_ids()

    def is_empty(self):
        # It's ok for this to wrongly return False: the worst that can happen
        # is that RemoteStreamSource will initiate a get_stream on an empty
        # repository.  And almost all repositories are non-empty.
        return False

    def refine(self, seen, referenced):
        heads = set(self._repo.all_revision_ids())
        heads.difference_update(seen)
        heads.update(referenced)
        return PendingAncestryResult(heads, self._repo)


class EverythingNotInOther(AbstractSearch):
    """Find all revisions in that are in one repo but not the other."""

    def __init__(self, to_repo, from_repo, find_ghosts=False):
        self.to_repo = to_repo
        self.from_repo = from_repo
        self.find_ghosts = find_ghosts

    def execute(self):
        return self.to_repo.search_missing_revision_ids(
            self.from_repo, find_ghosts=self.find_ghosts
        )


class NotInOtherForRevs(AbstractSearch):
    """Find all revisions missing in one repo for a some specific heads."""

    def __init__(
        self,
        to_repo,
        from_repo,
        required_ids,
        if_present_ids=None,
        find_ghosts=False,
        limit=None,
    ):
        """Constructor.

        :param required_ids: revision IDs of heads that must be found, or else
            the search will fail with NoSuchRevision.  All revisions in their
            ancestry not already in the other repository will be included in
            the search result.
        :param if_present_ids: revision IDs of heads that may be absent in the
            source repository.  If present, then their ancestry not already
            found in other will be included in the search result.
        :param limit: maximum number of revisions to fetch
        """
        self.to_repo = to_repo
        self.from_repo = from_repo
        self.find_ghosts = find_ghosts
        self.required_ids = required_ids
        self.if_present_ids = if_present_ids
        self.limit = limit

    def __repr__(self):
        if len(self.required_ids) > 5:
            reqd_revs_repr = repr(list(self.required_ids)[:5])[:-1] + ", ...]"
        else:
            reqd_revs_repr = repr(self.required_ids)
        if self.if_present_ids and len(self.if_present_ids) > 5:
            ifp_revs_repr = repr(list(self.if_present_ids)[:5])[:-1] + ", ...]"
        else:
            ifp_revs_repr = repr(self.if_present_ids)

        return (
            "<{} from:{!r} to:{!r} find_ghosts:{!r} req'd:{!r} if-present:{!r}limit:{!r}>"
        ).format(
            self.__class__.__name__,
            self.from_repo,
            self.to_repo,
            self.find_ghosts,
            reqd_revs_repr,
            ifp_revs_repr,
            self.limit,
        )

    def execute(self):
        return self.to_repo.search_missing_revision_ids(
            self.from_repo,
            revision_ids=self.required_ids,
            if_present_ids=self.if_present_ids,
            find_ghosts=self.find_ghosts,
            limit=self.limit,
        )


def search_result_from_parent_map(parent_map, missing_keys):
    """Transform a parent_map into SearchResult information."""
    if not parent_map:
        # parent_map is empty or None, simple search result
        return [], [], 0
    # start_set is all the keys in the cache
    start_set = set(parent_map)
    # result set is all the references to keys in the cache
    result_parents = set(itertools.chain.from_iterable(parent_map.values()))
    stop_keys = result_parents.difference(start_set)
    # We don't need to send ghosts back to the server as a position to
    # stop either.
    stop_keys.difference_update(missing_keys)
    key_count = len(parent_map)
    if (
        revision.NULL_REVISION in result_parents
        and revision.NULL_REVISION in missing_keys
    ):
        # If we pruned NULL_REVISION from the stop_keys because it's also
        # in our cache of "missing" keys we need to increment our key count
        # by 1, because the reconsitituted SearchResult on the server will
        # still consider NULL_REVISION to be an included key.
        key_count += 1
    included_keys = start_set.intersection(result_parents)
    start_set.difference_update(included_keys)
    return start_set, stop_keys, key_count


def _run_search(parent_map, heads, exclude_keys):
    """Given a parent map, run a _BreadthFirstSearcher on it.

    Start at heads, walk until you hit exclude_keys. As a further improvement,
    watch for any heads that you encounter while walking, which means they were
    not heads of the search.

    This is mostly used to generate a succinct recipe for how to walk through
    most of parent_map.

    :return: (_BreadthFirstSearcher, set(heads_encountered_by_walking))
    """
    g = Graph(DictParentsProvider(parent_map))
    s = g._make_breadth_first_searcher(heads)
    found_heads = set()
    while True:
        try:
            next_revs = next(s)
        except StopIteration:
            break
        for parents in s._current_parents.values():
            f_heads = heads.intersection(parents)
            if f_heads:
                found_heads.update(f_heads)
        stop_keys = exclude_keys.intersection(next_revs)
        if stop_keys:
            s.stop_searching_any(stop_keys)
    for parents in s._current_parents.values():
        f_heads = heads.intersection(parents)
        if f_heads:
            found_heads.update(f_heads)
    return s, found_heads


def _find_possible_heads(parent_map, tip_keys, depth):
    """Walk backwards (towards children) through the parent_map.

    This finds 'heads' that will hopefully succinctly describe our search
    graph.
    """
    child_map = invert_parent_map(parent_map)
    heads = set()
    current_roots = tip_keys
    walked = set(current_roots)
    while current_roots and depth > 0:
        depth -= 1
        children = set()
        children_update = children.update
        for p in current_roots:
            # Is it better to pre- or post- filter the children?
            try:
                children_update(child_map[p])
            except KeyError:
                heads.add(p)
        # If we've seen a key before, we don't want to walk it again. Note that
        # 'children' stays relatively small while 'walked' grows large. So
        # don't use 'difference_update' here which has to walk all of 'walked'.
        # '.difference' is smart enough to walk only children and compare it to
        # walked.
        children = children.difference(walked)
        walked.update(children)
        current_roots = children
    if current_roots:
        # We walked to the end of depth, so these are the new tips.
        heads.update(current_roots)
    return heads


def limited_search_result_from_parent_map(parent_map, missing_keys, tip_keys, depth):
    """Transform a parent_map that is searching 'tip_keys' into an
    approximate SearchResult.

    We should be able to generate a SearchResult from a given set of starting
    keys, that covers a subset of parent_map that has the last step pointing at
    tip_keys. This is to handle the case that really-long-searches shouldn't be
    started from scratch on each get_parent_map request, but we *do* want to
    filter out some of the keys that we've already seen, so we don't get
    information that we already know about on every request.

    The server will validate the search (that starting at start_keys and
    stopping at stop_keys yields the exact key_count), so we have to be careful
    to give an exact recipe.

    Basic algorithm is:
        1) Invert parent_map to get child_map (todo: have it cached and pass it
           in)
        2) Starting at tip_keys, walk towards children for 'depth' steps.
        3) At that point, we have the 'start' keys.
        4) Start walking parent_map from 'start' keys, counting how many keys
           are seen, and generating stop_keys for anything that would walk
           outside of the parent_map.

    :param parent_map: A map from {child_id: (parent_ids,)}
    :param missing_keys: parent_ids that we know are unavailable
    :param tip_keys: the revision_ids that we are searching
    :param depth: How far back to walk.
    """
    if not parent_map:
        # No search to send, because we haven't done any searching yet.
        return [], [], 0
    heads = _find_possible_heads(parent_map, tip_keys, depth)
    s, found_heads = _run_search(parent_map, heads, set(tip_keys))
    start_keys, exclude_keys, keys = s.get_state()
    if found_heads:
        # Anything in found_heads are redundant start_keys, we hit them while
        # walking, so we can exclude them from the start list.
        start_keys = set(start_keys).difference(found_heads)
    return start_keys, exclude_keys, len(keys)
