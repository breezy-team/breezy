# Copyright (C) 2009 Canonical Ltd
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

"""Implementation of Graph algorithms when we have already loaded everything.
"""

from bzrlib import (
    revision,
    )


class _KnownGraphNode(object):
    """Represents a single object in the known graph."""

    __slots__ = ('key', 'parent_keys', 'child_keys', 'gdfo')

    def __init__(self, key, parent_keys):
        self.key = key
        self.parent_keys = parent_keys
        self.child_keys = []
        # Greatest distance from origin
        self.gdfo = None

    def __repr__(self):
        return '%s(%s  gdfo:%s par:%s child:%s)' % (
            self.__class__.__name__, self.key, self.gdfo,
            self.parent_keys, self.child_keys)


class KnownGraph(object):
    """This is a class which assumes we already know the full graph."""

    def __init__(self, parent_map, do_cache=True):
        """Create a new KnownGraph instance.

        :param parent_map: A dictionary mapping key => parent_keys
        """
        self._nodes = {}
        # Maps {sorted(revision_id, revision_id): heads}
        self._known_heads = {}
        self.do_cache = do_cache
        self._initialize_nodes(parent_map)
        self._find_gdfo()

    def _initialize_nodes(self, parent_map):
        """Populate self._nodes.

        After this has finished:
        - self._nodes will have an entry for every entry in parent_map.
        - ghosts will have a parent_keys = None,
        - all nodes found will also have .child_keys populated with all known
          child_keys,
        - self._tails will list all the nodes without parents.
        """
        tails = self._tails = set()
        nodes = self._nodes
        for key, parent_keys in parent_map.iteritems():
            if key in nodes:
                node = nodes[key]
                node.parent_keys = parent_keys
                if parent_keys:
                    # This node has been added before being seen in parent_map
                    # (see below)
                    tails.remove(node)
            else:
                node = _KnownGraphNode(key, parent_keys)
                nodes[key] = node
            for parent_key in parent_keys:
                try:
                    parent_node = nodes[parent_key]
                except KeyError:
                    parent_node = _KnownGraphNode(parent_key, None)
                    nodes[parent_key] = parent_node
                    # Potentially a tail, if we're wrong we'll remove it later
                    # (see above)
                    tails.add(parent_node)
                parent_node.child_keys.append(key)

    def _find_gdfo(self):
        nodes = self._nodes
        known_parent_gdfos = {}
        pending = []

        for node in self._tails:
            node.gdfo = 1
            pending.append(node)

        while pending:
            node = pending.pop()
            for child_key in node.child_keys:
                child = nodes[child_key]
                try:
                    known_parent_gdfos[child_key] += 1
                except KeyError:
                    known_parent_gdfos[child_key] = 1
                if child.gdfo is None or node.gdfo + 1 > child.gdfo:
                    child.gdfo = node.gdfo + 1
                if known_parent_gdfos[child_key] == len(child.parent_keys):
                    # We are the last parent updating that node, we can
                    # continue from there
                    pending.append(child)

    def heads(self, keys):
        """Return the heads from amongst keys.

        This is done by searching the ancestries of each key.  Any key that is
        reachable from another key is not returned; all the others are.

        This operation scales with the relative depth between any two keys. It
        uses gdfo to avoid walking all ancestry.

        :param keys: An iterable of keys.
        :return: A set of the heads. Note that as a set there is no ordering
            information. Callers will need to filter their input to create
            order if they need it.
        """
        candidate_nodes = dict((key, self._nodes[key]) for key in keys)
        if revision.NULL_REVISION in candidate_nodes:
            # NULL_REVISION is only a head if it is the only entry
            candidate_nodes.pop(revision.NULL_REVISION)
            if not candidate_nodes:
                return frozenset([revision.NULL_REVISION])
        if len(candidate_nodes) < 2:
            # No or only one candidate
            return frozenset(candidate_nodes)
        heads_key = frozenset(candidate_nodes)
        if heads_key != frozenset(keys):
            # Mention duplicates
            note('%s != %s', heads_key, frozenset(keys))
        # Do we have a cached result ?
        try:
            heads = self._known_heads[heads_key]
            return heads
        except KeyError:
            pass
        # Let's compute the heads
        seen = set()
        pending = []
        min_gdfo = None
        for node in candidate_nodes.values():
            if node.parent_keys:
                pending.extend(node.parent_keys)
            if min_gdfo is None or node.gdfo < min_gdfo:
                min_gdfo = node.gdfo
        nodes = self._nodes
        while pending:
            node_key = pending.pop()
            if node_key in seen:
                # node already appears in some ancestry
                continue
            seen.add(node_key)
            node = nodes[node_key]
            if node.gdfo <= min_gdfo:
                continue
            if node.parent_keys:
                pending.extend(node.parent_keys)
        heads = heads_key.difference(seen)
        if self.do_cache:
            self._known_heads[heads_key] = heads
        return heads

