# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Implementation of Graph algorithms when we have already loaded everything."""

from collections import deque

from . import errors, revision


class _KnownGraphNode:
    """Represents a single object in the known graph."""

    __slots__ = ("child_keys", "gdfo", "key", "parent_keys")

    def __init__(self, key, parent_keys):
        self.key = key
        self.parent_keys = parent_keys
        self.child_keys = []
        # Greatest distance from origin
        self.gdfo = None

    def __repr__(self):
        return "{}({}  gdfo:{} par:{} child:{})".format(
            self.__class__.__name__,
            self.key,
            self.gdfo,
            self.parent_keys,
            self.child_keys,
        )


class _MergeSortNode:
    """Information about a specific node in the merge graph."""

    __slots__ = ("end_of_merge", "key", "merge_depth", "revno")

    def __init__(self, key, merge_depth, revno, end_of_merge):
        self.key = key
        self.merge_depth = merge_depth
        self.revno = revno
        self.end_of_merge = end_of_merge


class KnownGraph:
    """This is a class which assumes we already know the full graph."""

    def __init__(self, parent_map, do_cache=True):
        """Create a new KnownGraph instance.

        :param parent_map: A dictionary mapping key => parent_keys
        """
        self._nodes = {}
        # Maps {frozenset(revision_id, revision_id): heads}
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
        """
        nodes = self._nodes
        for key, parent_keys in parent_map.items():
            if key in nodes:
                node = nodes[key]
                node.parent_keys = parent_keys
            else:
                node = _KnownGraphNode(key, parent_keys)
                nodes[key] = node
            for parent_key in parent_keys:
                try:
                    parent_node = nodes[parent_key]
                except KeyError:
                    parent_node = _KnownGraphNode(parent_key, None)
                    nodes[parent_key] = parent_node
                parent_node.child_keys.append(key)

    def _find_tails(self):
        return [node for node in self._nodes.values() if not node.parent_keys]

    def _find_tips(self):
        return [node for node in self._nodes.values() if not node.child_keys]

    def _find_gdfo(self):
        nodes = self._nodes
        known_parent_gdfos = {}
        pending = []

        for node in self._find_tails():
            node.gdfo = 1
            pending.append(node)

        while pending:
            node = pending.pop()
            for child_key in node.child_keys:
                child = nodes[child_key]
                if child_key in known_parent_gdfos:
                    known_gdfo = known_parent_gdfos[child_key] + 1
                    present = True
                else:
                    known_gdfo = 1
                    present = False
                if child.gdfo is None or node.gdfo + 1 > child.gdfo:
                    child.gdfo = node.gdfo + 1
                if known_gdfo == len(child.parent_keys):
                    # We are the last parent updating that node, we can
                    # continue from there
                    pending.append(child)
                    if present:
                        del known_parent_gdfos[child_key]
                else:
                    # Update known_parent_gdfos for a key we couldn't process
                    known_parent_gdfos[child_key] = known_gdfo

    def add_node(self, key, parent_keys):
        """Add a new node to the graph.

        If this fills in a ghost, then the gdfos of all children will be
        updated accordingly.

        :param key: The node being added. If this is a duplicate, this is a
            no-op.
        :param parent_keys: The parents of the given node.
        :return: None (should we return if this was a ghost, etc?)
        """
        nodes = self._nodes
        if key in nodes:
            node = nodes[key]
            if node.parent_keys is None:
                node.parent_keys = parent_keys
                # A ghost is being added, we can no-longer trust the heads
                # cache, so clear it
                self._known_heads.clear()
            else:
                # Make sure we compare a list to a list, as tuple != list.
                parent_keys = list(parent_keys)
                existing_parent_keys = list(node.parent_keys)
                if parent_keys == existing_parent_keys:
                    return  # Identical content
                else:
                    raise ValueError(
                        "Parent key mismatch, existing node %s"
                        " has parents of %s not %s"
                        % (key, existing_parent_keys, parent_keys)
                    )
        else:
            node = _KnownGraphNode(key, parent_keys)
            nodes[key] = node
        parent_gdfo = 0
        for parent_key in parent_keys:
            try:
                parent_node = nodes[parent_key]
            except KeyError:
                parent_node = _KnownGraphNode(parent_key, None)
                # Ghosts and roots have gdfo 1
                parent_node.gdfo = 1
                nodes[parent_key] = parent_node
            if parent_gdfo < parent_node.gdfo:
                parent_gdfo = parent_node.gdfo
            parent_node.child_keys.append(key)
        node.gdfo = parent_gdfo + 1
        # Now fill the gdfo to all children
        # Note that this loop is slightly inefficient, in that we may visit the
        # same child (and its decendents) more than once, however, it is
        # 'efficient' in that we only walk to nodes that would be updated,
        # rather than all nodes
        # We use a deque rather than a simple list stack, to go for BFD rather
        # than DFD. So that if a longer path is possible, we walk it before we
        # get to the final child
        pending = deque([node])
        while pending:
            node = pending.popleft()
            next_gdfo = node.gdfo + 1
            for child_key in node.child_keys:
                child = nodes[child_key]
                if child.gdfo < next_gdfo:
                    # This child is being updated, we need to check its
                    # children
                    child.gdfo = next_gdfo
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
        candidate_nodes = {key: self._nodes[key] for key in keys}
        if revision.NULL_REVISION in candidate_nodes:
            # NULL_REVISION is only a head if it is the only entry
            candidate_nodes.pop(revision.NULL_REVISION)
            if not candidate_nodes:
                return frozenset([revision.NULL_REVISION])
        if len(candidate_nodes) < 2:
            # No or only one candidate
            return frozenset(candidate_nodes)
        heads_key = frozenset(candidate_nodes)
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

    def topo_sort(self):
        """Return the nodes in topological order.

        All parents must occur before all children.
        """
        for node in self._nodes.values():
            if node.gdfo is None:
                raise errors.GraphCycleError(self._nodes)
        pending = self._find_tails()
        pending_pop = pending.pop
        pending_append = pending.append

        topo_order = []
        topo_order_append = topo_order.append

        num_seen_parents = dict.fromkeys(self._nodes, 0)
        while pending:
            node = pending_pop()
            if node.parent_keys is not None:
                # We don't include ghost parents
                topo_order_append(node.key)
            for child_key in node.child_keys:
                child_node = self._nodes[child_key]
                seen_parents = num_seen_parents[child_key] + 1
                if seen_parents == len(child_node.parent_keys):
                    # All parents have been processed, enqueue this child
                    pending_append(child_node)
                    # This has been queued up, stop tracking it
                    del num_seen_parents[child_key]
                else:
                    num_seen_parents[child_key] = seen_parents
        # We started from the parents, so we don't need to do anymore work
        return topo_order

    def gc_sort(self):
        """Return a reverse topological ordering which is 'stable'.

        There are a few constraints:
          1) Reverse topological (all children before all parents)
          2) Grouped by prefix
          3) 'stable' sorting, so that we get the same result, independent of
             machine, or extra data.
        To do this, we use the same basic algorithm as topo_sort, but when we
        aren't sure what node to access next, we sort them lexicographically.
        """
        tips = self._find_tips()
        # Split the tips based on prefix
        prefix_tips = {}
        for node in tips:
            if node.key.__class__ is str or len(node.key) == 1:
                prefix = ""
            else:
                prefix = node.key[0]
            prefix_tips.setdefault(prefix, []).append(node)

        num_seen_children = dict.fromkeys(self._nodes, 0)

        result = []
        for prefix in sorted(prefix_tips):
            pending = sorted(prefix_tips[prefix], key=lambda n: n.key, reverse=True)
            while pending:
                node = pending.pop()
                if node.parent_keys is None:
                    # Ghost node, skip it
                    continue
                result.append(node.key)
                for parent_key in sorted(node.parent_keys, reverse=True):
                    parent_node = self._nodes[parent_key]
                    seen_children = num_seen_children[parent_key] + 1
                    if seen_children == len(parent_node.child_keys):
                        # All children have been processed, enqueue this parent
                        pending.append(parent_node)
                        # This has been queued up, stop tracking it
                        del num_seen_children[parent_key]
                    else:
                        num_seen_children[parent_key] = seen_children
        return result

    def merge_sort(self, tip_key):
        """Compute the merge sorted graph output."""
        from breezy import tsort

        as_parent_map = {
            node.key: node.parent_keys
            for node in self._nodes.values()
            if node.parent_keys is not None
        }
        # We intentionally always generate revnos and never force the
        # mainline_revisions
        # Strip the sequence_number that merge_sort generates
        return [
            _MergeSortNode(key, merge_depth, revno, end_of_merge)
            for _, key, merge_depth, revno, end_of_merge in tsort.merge_sort(
                as_parent_map, tip_key, mainline_revisions=None, generate_revno=True
            )
        ]

    def get_parent_keys(self, key):
        """Get the parents for a key

        Returns a list containg the parents keys. If the key is a ghost,
        None is returned. A KeyError will be raised if the key is not in
        the graph.

        :param keys: Key to check (eg revision_id)
        :return: A list of parents
        """
        return self._nodes[key].parent_keys

    def get_child_keys(self, key):
        """Get the children for a key

        Returns a list containg the children keys. A KeyError will be raised
        if the key is not in the graph.

        :param keys: Key to check (eg revision_id)
        :return: A list of children
        """
        return self._nodes[key].child_keys
