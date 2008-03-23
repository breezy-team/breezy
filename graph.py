# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib import graph
from bzrlib.revision import NULL_REVISION

class CachingParentsProvider(object):
    """A parents provider which will cache the revision => parents in a dict.

    This is useful for providers that have an expensive lookup.
    """

    def __init__(self, parent_provider):
        self._real_provider = parent_provider
        # Theoretically we could use an LRUCache here
        self._cache = {}
        self._lhs_cache = {}

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._real_provider)

    def get_lhs_parent(self, key):
        if key in self._lhs_cache:
            return self._lhs_cache[key]

        if key in self._cache:
            return self._cache[key][0]

        self._lhs_cache[key] = self._real_provider.get_lhs_parent(key)
        return self._lhs_cache[key]

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




class Graph(graph.Graph):
    def __init__(self, parents_provider):
        graph.Graph.__init__(self, parents_provider)
        if hasattr(parents_provider, "get_lhs_parent"):
            self.get_lhs_parent = parents_provider.get_lhs_parent

    def get_lhs_parent(self, revid):
        parents = self.get_parent_map([revid])[revid]
        if parents == () or parents == (NULL_REVISION,):
            return None
        return parents[0]

    def iter_lhs_ancestry(self, revid):
        while revid is not None:
            parent_revid = self.get_lhs_parent(revid)
            yield (revid, parent_revid)
            revid = parent_revid
