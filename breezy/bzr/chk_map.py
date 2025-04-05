# Copyright (C) 2008-2011 Canonical Ltd
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

r"""Persistent maps from tuple_of_strings->string using CHK stores.

Overview and current status:

The CHKMap class implements a dict from tuple_of_strings->string by using a trie
with internal nodes of 8-bit fan out; The key tuples are mapped to strings by
joining them by \x00, and \x00 padding shorter keys out to the length of the
longest key. Leaf nodes are packed as densely as possible, and internal nodes
are all an additional 8-bits wide leading to a sparse upper tree.

Updates to a CHKMap are done preferentially via the apply_delta method, to
allow optimisation of the update operation; but individual map/unmap calls are
possible and supported. Individual changes via map/unmap are buffered in memory
until the _save method is called to force serialisation of the tree.
apply_delta records its changes immediately by performing an implicit _save.

Todo:
-----
Densely packed upper nodes.

"""

import heapq
import threading
from collections.abc import Callable, Iterator, Generator
from typing import Callable, Optional, Union

from .. import errors, lru_cache, osutils, registry, trace

# approx 4MB
# If each line is 50 bytes, and you have 255 internal pages, with 255-way fan
# out, it takes 3.1MB to cache the layer.
_PAGE_CACHE_SIZE = 4 * 1024 * 1024

Key = tuple[bytes, ...]
SerialisedKey = bytes
SearchKeyFunc = Callable[[Key], bytes]
KeyFilter = list[Key]

# Per thread caches for 2 reasons:
# - in the server we may be serving very different content, so we get less
#   cache thrashing.
# - we avoid locking on every cache lookup.
_thread_caches = threading.local()
# The page cache.
_thread_caches.page_cache = None


def _get_cache():
    """Get the per-thread page cache.

    We need a function to do this because in a new thread the _thread_caches
    threading.local object does not have the cache initialized yet.
    """
    page_cache = getattr(_thread_caches, "page_cache", None)
    if page_cache is None:
        # We are caching bytes so len(value) is perfectly accurate
        page_cache = lru_cache.LRUSizeCache(_PAGE_CACHE_SIZE)
        _thread_caches.page_cache = page_cache
    return page_cache


def clear_cache():
    _get_cache().clear()


# If a ChildNode falls below this many bytes, we check for a remap
_INTERESTING_NEW_SIZE = 50
# If a ChildNode shrinks by more than this amount, we check for a remap
_INTERESTING_SHRINKAGE_LIMIT = 20


def _search_key_plain(key: Key) -> SerialisedKey:
    """Map the key tuple into a search string that just uses the key bytes."""
    return b"\x00".join(key)


search_key_registry = registry.Registry[bytes, Callable[[Key], SerialisedKey]]()
search_key_registry.register(b"plain", _search_key_plain)


class CHKMap:
    """A persistent map from string to string backed by a CHK store."""

    __slots__ = ("_root_node", "_search_key_func", "_store")
    _root_node: "Node"

    def __init__(
        self,
        store,
        root_key: Optional[Key],
        search_key_func: Optional[SearchKeyFunc] = None,
    ):
        """Create a CHKMap object.

        :param store: The store the CHKMap is stored in.
        :param root_key: The root key of the map. None to create an empty
            CHKMap.
        :param search_key_func: A function mapping a key => bytes. These bytes
            are then used by the internal nodes to split up leaf nodes into
            multiple pages.
        """
        self._store = store
        if search_key_func is None:
            search_key_func = _search_key_plain
        self._search_key_func = search_key_func
        if root_key is None:
            self._root_node = LeafNode(search_key_func=search_key_func)
        else:
            self._root_node = self._node_key(root_key)

    def apply_delta(self, delta):
        """Apply a delta to the map.

        :param delta: An iterable of old_key, new_key, new_value tuples.
            If new_key is not None, then new_key->new_value is inserted
            into the map; if old_key is not None, then the old mapping
            of old_key is removed.
        """
        has_deletes = False
        # Check preconditions first.
        new_items = {
            tuple(key) for (old, key, value) in delta if key is not None and old is None
        }
        existing_new = list(self.iteritems(key_filter=new_items))
        if existing_new:
            raise errors.InconsistentDeltaDelta(
                delta, "New items are already in the map {!r}.".format(existing_new)
            )
        # Now apply changes.
        for old, new, _value in delta:
            if old is not None and old != new:
                self.unmap(old, check_remap=False)
                has_deletes = True
        for _old, new, value in delta:
            if new is not None:
                self.map(new, value)
        if has_deletes:
            self._check_remap()
        return self._save()

    def _ensure_root(self) -> None:
        """Ensure that the root node is an object not a key."""
        if isinstance(self._root_node, tuple):
            # Demand-load the root
            self._root_node = self._get_node(self._root_node)

    def _get_node(self, node: Union[Key, "Node"]) -> "Node":
        """Get a node.

        Note that this does not update the _items dict in objects containing a
        reference to this node. As such it does not prevent subsequent IO being
        performed.

        :param node: A tuple key or node object.
        :return: A node object.
        """
        if isinstance(node, tuple):
            bytes = self._read_bytes(node)
            return _deserialise(bytes, node, search_key_func=self._search_key_func)
        else:
            return node

    def _read_bytes(self, key: Key) -> bytes:
        try:
            return _get_cache()[key]
        except KeyError:
            stream = self._store.get_record_stream([key], "unordered", True)
            bytes = next(stream).get_bytes_as("fulltext")
            _get_cache()[key] = bytes
            return bytes

    def _dump_tree(self, include_keys: bool = False, encoding: str = "utf-8") -> str:
        """Return the tree in a string representation."""
        self._ensure_root()

        def decode(x):
            return x.decode(encoding)

        res = self._dump_tree_node(
            self._root_node,
            prefix=b"",
            indent="",
            decode=decode,
            include_keys=include_keys,
        )
        res.append("")  # Give a trailing '\n'
        return "\n".join(res)

    def _dump_tree_node(
        self, node: "Node", prefix, indent, decode, include_keys: bool = True
    ) -> list[str]:
        """For this node and all children, generate a string representation."""
        result = []
        if not include_keys:
            key_str = ""
        else:
            node_key = node.key()
            if node_key is not None:
                key_str = " {}".format(decode(node_key[0]))
            else:
                key_str = " None"
        result.append(
            "{}{!r} {}{}".format(
                indent, decode(prefix), node.__class__.__name__, key_str
            )
        )
        if isinstance(node, InternalNode):
            # Trigger all child nodes to get loaded
            list(node._iter_nodes(self._store))
            for prefix, sub in sorted(node._items.items()):
                result.extend(
                    self._dump_tree_node(
                        sub,
                        prefix,
                        indent + "  ",
                        decode=decode,
                        include_keys=include_keys,
                    )
                )
        else:
            for key, value in sorted(node._items.items()):
                # Don't use prefix nor indent here to line up when used in
                # tests in conjunction with assertEqualDiff
                result.append(
                    "      {!r} {!r}".format(
                        tuple([decode(ke) for ke in key]), decode(value)
                    )
                )
        return result

    @classmethod
    def from_dict(
        cls,
        store,
        initial_value,
        maximum_size: int = 0,
        key_width: int = 1,
        search_key_func: Optional[SearchKeyFunc] = None,
    ):
        """Create a CHKMap in store with initial_value as the content.

        :param store: The store to record initial_value in, a VersionedFiles
            object with 1-tuple keys supporting CHK key generation.
        :param initial_value: A dict to store in store. Its keys and values
            must be bytestrings.
        :param maximum_size: The maximum_size rule to apply to nodes. This
            determines the size at which no new data is added to a single node.
        :param key_width: The number of elements in each key_tuple being stored
            in this map.
        :param search_key_func: A function mapping a key => bytes. These bytes
            are then used by the internal nodes to split up leaf nodes into
            multiple pages.
        :return: The root chk of the resulting CHKMap.
        """
        root_key = cls._create_directly(
            store,
            initial_value,
            maximum_size=maximum_size,
            key_width=key_width,
            search_key_func=search_key_func,
        )
        if not isinstance(root_key, tuple):
            raise AssertionError(
                "we got a {} instead of a tuple".format(type(root_key))
            )
        return root_key

    @classmethod
    def _create_via_map(
        cls,
        store,
        initial_value,
        maximum_size: int = 0,
        key_width: int = 1,
        search_key_func: Optional[SearchKeyFunc] = None,
    ):
        result = cls(store, None, search_key_func=search_key_func)
        result._root_node.set_maximum_size(maximum_size)
        result._root_node._key_width = key_width
        delta = []
        for key, value in initial_value.items():
            delta.append((None, key, value))
        root_key = result.apply_delta(delta)
        return root_key

    @classmethod
    def _create_directly(
        cls,
        store,
        initial_value,
        maximum_size: int = 0,
        key_width: int = 1,
        search_key_func: Optional[SearchKeyFunc] = None,
    ):
        node: Node
        node = LeafNode(search_key_func=search_key_func)
        node.set_maximum_size(maximum_size)
        node._key_width = key_width
        node._items = {tuple(key): val for key, val in initial_value.items()}
        node._raw_size = sum(
            node._key_value_len(key, value) for key, value in node._items.items()
        )
        node._len = len(node._items)
        node._compute_search_prefix()
        node._compute_serialised_prefix()
        if node._len > 1 and maximum_size and node._current_size() > maximum_size:
            prefix, node_details = node._split(store)
            if len(node_details) == 1:
                raise AssertionError("Failed to split using node._split")
            node = InternalNode(prefix, search_key_func=search_key_func)
            node.set_maximum_size(maximum_size)
            node._key_width = key_width
            for split, subnode in node_details:
                node.add_node(split, subnode)
        keys = list(node.serialise(store))
        return keys[-1]

    def iter_changes(self, basis):
        """Iterate over the changes between basis and self.

        :return: An iterator of tuples: (key, old_value, new_value). Old_value
            is None for keys only in self; new_value is None for keys only in
            basis.
        """
        # Overview:
        # Read both trees in lexographic, highest-first order.
        # Any identical nodes we skip
        # Any unique prefixes we output immediately.
        # values in a leaf node are treated as single-value nodes in the tree
        # which allows them to be not-special-cased. We know to output them
        # because their value is a string, not a key(tuple) or node.
        #
        # corner cases to beware of when considering this function:
        # *) common references are at different heights.
        #    consider two trees:
        #    {'a': LeafNode={'aaa':'foo', 'aab':'bar'}, 'b': LeafNode={'b'}}
        #    {'a': InternalNode={'aa':LeafNode={'aaa':'foo', 'aab':'bar'},
        #                        'ab':LeafNode={'ab':'bar'}}
        #     'b': LeafNode={'b'}}
        #    the node with aaa/aab will only be encountered in the second tree
        #    after reading the 'a' subtree, but it is encountered in the first
        #    tree immediately. Variations on this may have read internal nodes
        #    like this.  we want to cut the entire pending subtree when we
        #    realise we have a common node.  For this we use a list of keys -
        #    the path to a node - and check the entire path is clean as we
        #    process each item.
        if self._node_key(self._root_node) == self._node_key(basis._root_node):
            return
        self._ensure_root()
        basis._ensure_root()
        excluded_keys = set()
        self_node = self._root_node
        basis_node = basis._root_node
        # A heap, each element is prefix, node(tuple/NodeObject/string),
        # key_path (a list of tuples, tail-sharing down the tree.)
        self_pending = []
        basis_pending = []

        def process_node(node, path, a_map, pending):
            # take a node and expand it
            node = a_map._get_node(node)
            if isinstance(node, LeafNode):
                path = (node._key, path)
                for key, value in node._items.items():
                    # For a LeafNode, the key is a serialized_key, rather than
                    # a search_key, but the heap is using search_keys
                    search_key = node._search_key_func(key)
                    heapq.heappush(pending, (search_key, key, value, path))
            else:
                # type(node) == InternalNode
                path = (node._key, path)
                for prefix, child in node._items.items():
                    heapq.heappush(pending, (prefix, None, child, path))

        def process_common_internal_nodes(self_node, basis_node):
            self_items = set(self_node._items.items())
            basis_items = set(basis_node._items.items())
            path = (self_node._key, None)
            for prefix, child in self_items - basis_items:
                heapq.heappush(self_pending, (prefix, None, child, path))
            path = (basis_node._key, None)
            for prefix, child in basis_items - self_items:
                heapq.heappush(basis_pending, (prefix, None, child, path))

        def process_common_leaf_nodes(self_node, basis_node):
            self_items = set(self_node._items.items())
            basis_items = set(basis_node._items.items())
            path = (self_node._key, None)
            for key, value in self_items - basis_items:
                prefix = self._search_key_func(key)
                heapq.heappush(self_pending, (prefix, key, value, path))
            path = (basis_node._key, None)
            for key, value in basis_items - self_items:
                prefix = basis._search_key_func(key)
                heapq.heappush(basis_pending, (prefix, key, value, path))

        def process_common_prefix_nodes(self_node, self_path, basis_node, basis_path):
            # Would it be more efficient if we could request both at the same
            # time?
            self_node = self._get_node(self_node)
            basis_node = basis._get_node(basis_node)
            if isinstance(self_node, InternalNode) and isinstance(
                basis_node, InternalNode
            ):
                # Matching internal nodes
                process_common_internal_nodes(self_node, basis_node)
            elif isinstance(self_node, LeafNode) and isinstance(basis_node, LeafNode):
                process_common_leaf_nodes(self_node, basis_node)
            else:
                process_node(self_node, self_path, self, self_pending)
                process_node(basis_node, basis_path, basis, basis_pending)

        process_common_prefix_nodes(self_node, None, basis_node, None)
        excluded_keys = set()

        def check_excluded(key_path):
            # Note that this is N^2, it depends on us trimming trees
            # aggressively to not become slow.
            # A better implementation would probably have a reverse map
            # back to the children of a node, and jump straight to it when
            # a common node is detected, the proceed to remove the already
            # pending children. breezy.graph has a searcher module with a
            # similar problem.
            while key_path is not None:
                key, key_path = key_path
                if key in excluded_keys:
                    return True
            return False

        loop_counter = 0
        while self_pending or basis_pending:
            loop_counter += 1
            if not self_pending:
                # self is exhausted: output remainder of basis
                for _prefix, key, node, path in basis_pending:
                    if check_excluded(path):
                        continue
                    node = basis._get_node(node)
                    if key is not None:
                        # a value
                        yield (key, node, None)
                    else:
                        # subtree - fastpath the entire thing.
                        for key, value in node.iteritems(basis._store):
                            yield (key, value, None)
                return
            elif not basis_pending:
                # basis is exhausted: output remainder of self.
                for _prefix, key, node, path in self_pending:
                    if check_excluded(path):
                        continue
                    node = self._get_node(node)
                    if key is not None:
                        # a value
                        yield (key, None, node)
                    else:
                        # subtree - fastpath the entire thing.
                        for key, value in node.iteritems(self._store):
                            yield (key, None, value)
                return
            else:
                # XXX: future optimisation - yield the smaller items
                # immediately rather than pushing everything on/off the
                # heaps. Applies to both internal nodes and leafnodes.
                if self_pending[0][0] < basis_pending[0][0]:
                    # expand self
                    prefix, key, node, path = heapq.heappop(self_pending)
                    if check_excluded(path):
                        continue
                    if key is not None:
                        # a value
                        yield (key, None, node)
                    else:
                        process_node(node, path, self, self_pending)
                        continue
                elif self_pending[0][0] > basis_pending[0][0]:
                    # expand basis
                    prefix, key, node, path = heapq.heappop(basis_pending)
                    if check_excluded(path):
                        continue
                    if key is not None:
                        # a value
                        yield (key, node, None)
                    else:
                        process_node(node, path, basis, basis_pending)
                        continue
                else:
                    # common prefix: possibly expand both
                    if self_pending[0][1] is None:
                        # process next self
                        read_self = True
                    else:
                        read_self = False
                    if basis_pending[0][1] is None:
                        # process next basis
                        read_basis = True
                    else:
                        read_basis = False
                    if not read_self and not read_basis:
                        # compare a common value
                        self_details = heapq.heappop(self_pending)
                        basis_details = heapq.heappop(basis_pending)
                        if self_details[2] != basis_details[2]:
                            yield (self_details[1], basis_details[2], self_details[2])
                        continue
                    # At least one side wasn't a simple value
                    if self._node_key(self_pending[0][2]) == self._node_key(
                        basis_pending[0][2]
                    ):
                        # Identical pointers, skip (and don't bother adding to
                        # excluded, it won't turn up again.
                        heapq.heappop(self_pending)
                        heapq.heappop(basis_pending)
                        continue
                    # Now we need to expand this node before we can continue
                    if read_self and read_basis:
                        # Both sides start with the same prefix, so process
                        # them in parallel
                        self_prefix, _, self_node, self_path = heapq.heappop(
                            self_pending
                        )
                        basis_prefix, _, basis_node, basis_path = heapq.heappop(
                            basis_pending
                        )
                        if self_prefix != basis_prefix:
                            raise AssertionError(
                                "{!r} != {!r}".format(self_prefix, basis_prefix)
                            )
                        process_common_prefix_nodes(
                            self_node, self_path, basis_node, basis_path
                        )
                        continue
                    if read_self:
                        prefix, key, node, path = heapq.heappop(self_pending)
                        if check_excluded(path):
                            continue
                        process_node(node, path, self, self_pending)
                    if read_basis:
                        prefix, key, node, path = heapq.heappop(basis_pending)
                        if check_excluded(path):
                            continue
                        process_node(node, path, basis, basis_pending)
        # print loop_counter

    def iteritems(
        self, key_filter: Optional[KeyFilter] = None
    ) -> Iterator[tuple[Key, bytes]]:
        """Iterate over the entire CHKMap's contents."""
        self._ensure_root()
        if key_filter is not None:
            key_filter = [tuple(key) for key in key_filter]
        return self._root_node.iteritems(self._store, key_filter=key_filter)

    def key(self) -> Key:
        """Return the key for this map."""
        if isinstance(self._root_node, tuple):
            return self._root_node
        elif isinstance(self._root_node, Node):
            if self._root_node is None:
                raise AssertionError("No root node")
            return self._root_node._key
        else:
            raise AssertionError(
                "Invalid root node type: {!r}".format(type(self._root_node))
            )

    def __len__(self) -> int:
        self._ensure_root()
        return len(self._root_node)

    def map(self, key: Key, value) -> None:
        """Map a key tuple to value.

        :param key: A key to map.
        :param value: The value to assign to key.
        """
        key = tuple(key)
        # Need a root object.
        self._ensure_root()
        prefix, node_details = self._root_node.map(self._store, key, value)
        if len(node_details) == 1:
            self._root_node = node_details[0][1]
        else:
            self._root_node = InternalNode(
                prefix, search_key_func=self._search_key_func
            )
            self._root_node.set_maximum_size(node_details[0][1].maximum_size)
            self._root_node._key_width = node_details[0][1]._key_width
            for split, node in node_details:
                self._root_node.add_node(split, node)

    def _node_key(self, node):
        """Get the key for a node whether it's a tuple or node."""
        if isinstance(node, tuple):
            return node
        elif isinstance(node, Node):
            return node._key
        else:
            raise AssertionError(
                "Invalid node type: {!r}".format(type(node))
            )

    def unmap(self, key: Key, check_remap=True) -> None:
        """Remove key from the map."""
        key = tuple(key)
        self._ensure_root()
        if isinstance(self._root_node, InternalNode):
            unmapped = self._root_node.unmap(self._store, key, check_remap=check_remap)
        else:
            unmapped = self._root_node.unmap(self._store, key)
        self._root_node = unmapped

    def _check_remap(self) -> None:
        """Check if nodes can be collapsed."""
        self._ensure_root()
        if isinstance(self._root_node, InternalNode):
            self._root_node = self._root_node._check_remap(self._store)

    def _save(self):
        """Save the map completely.

        :return: The key of the root node.
        """
        if isinstance(self._root_node, tuple):
            # Already saved.
            return self._root_node
        keys = list(self._root_node.serialise(self._store))
        return keys[-1]


class Node:
    """Base class defining the protocol for CHK Map nodes.

    :ivar _raw_size: The total size of the serialized key:value data, before
        adding the header bytes, and without prefix compression.
    """

    __slots__ = (
        "_items",
        "_key",
        "_key_width",
        "_len",
        "_maximum_size",
        "_raw_size",
        "_search_key_func",
        "_search_prefix",
    )

    def __init__(self, key_width=1):
        """Create a node.

        :param key_width: The width of keys for this node.
        """
        self._key = None
        # Current number of elements
        self._len = 0
        self._maximum_size = 0
        self._key_width = key_width
        # current size in bytes
        self._raw_size = 0
        # The pointers/values this node has - meaning defined by child classes.
        self._items = {}
        # The common search prefix
        self._search_prefix = None

    def __repr__(self):
        items_str = str(sorted(self._items))
        if len(items_str) > 20:
            items_str = items_str[:16] + "...]"
        return "{}(key:{} len:{} size:{} max:{} prefix:{} items:{})".format(
            self.__class__.__name__,
            self._key,
            self._len,
            self._raw_size,
            self._maximum_size,
            self._search_prefix,
            items_str,
        )

    def key(self) -> Key:
        """Return the key for this node."""
        return self._key

    def __len__(self) -> int:
        """Return the number of items in this node."""
        return self._len

    @property
    def maximum_size(self) -> int:
        """What is the upper limit for adding references to a node."""
        return self._maximum_size

    def set_maximum_size(self, new_size):
        """Set the size threshold for nodes.

        :param new_size: The size at which no data is added to a node. 0 for
            unlimited.
        """
        self._maximum_size = new_size

    @classmethod
    def common_prefix(cls, prefix, key):
        """Given 2 strings, return the longest prefix common to both.

        :param prefix: This has been the common prefix for other keys, so it is
            more likely to be the common prefix in this case as well.
        :param key: Another string to compare to
        """
        if key.startswith(prefix):
            return prefix
        pos = -1
        # Is there a better way to do this?
        for pos, (left, right) in enumerate(zip(prefix, key)):
            if left != right:
                pos -= 1
                break
        common = prefix[: pos + 1]
        return common

    @classmethod
    def common_prefix_for_keys(cls, keys):
        """Given a list of keys, find their common prefix.

        :param keys: An iterable of strings.
        :return: The longest common prefix of all keys.
        """
        common_prefix = None
        for key in keys:
            if common_prefix is None:
                common_prefix = key
                continue
            common_prefix = cls.common_prefix(common_prefix, key)
            if not common_prefix:
                # if common_prefix is the empty string, then we know it won't
                # change further
                return b""
        return common_prefix

    def serialise(self, store) -> Iterator[Key]:
        """Serialise the node into the store.

        :param store: The store to serialise into.
        :return: An iterable of keys that were written to the store.
        """
        raise NotImplementedError("serialise must be implemented in subclasses")

    def iteritems(
        self, store, key_filter: Optional[KeyFilter] = None
    ) -> Iterator[tuple[Key, bytes]]:
        """Iterate over items in the node.

        :param key_filter: A filter to apply to the node. It should be a
            list/set/dict or similar repeatedly iterable container.
        """
        raise NotImplementedError("iteritems must be implemented in subclasses")

    def add_node(self, prefix: Key, node: "Node") -> None:
        """Add a child node with prefix prefix, and node node.

        :param prefix: The search key prefix for node.
        :param node: The node being added.
        """
        raise NotImplementedError("add_node must be implemented in subclasses")

    def map(self, store, key: Key, value) -> tuple[Key, list[tuple[Key, "Node"]]]:
        """Map key to value."""
        raise NotImplementedError("map must be implemented in subclasses")

    def unmap(self, store, key: Key) -> "Node":
        """Unmap key from the node."""
        raise NotImplementedError("unmap must be implemented in subclasses")


# Singleton indicating we have not computed _search_prefix yet
_unknown = object()


class LeafNode(Node):
    """A node containing actual key:value pairs.

    :ivar _items: A dict of key->value items. The key is in tuple form.
    :ivar _size: The number of bytes that would be used by serializing all of
        the key/value pairs.
    """

    __slots__ = ("_common_serialised_prefix",)

    def __init__(self, search_key_func=None):
        Node.__init__(self)
        # All of the keys in this leaf node share this common prefix
        self._common_serialised_prefix = None
        if search_key_func is None:
            self._search_key_func = _search_key_plain
        else:
            self._search_key_func = search_key_func

    def __repr__(self):
        items_str = str(sorted(self._items))
        if len(items_str) > 20:
            items_str = items_str[:16] + "...]"
        return "{}(key:{} len:{} size:{} max:{} prefix:{} keywidth:{} items:{})".format(
            self.__class__.__name__,
            self._key,
            self._len,
            self._raw_size,
            self._maximum_size,
            self._search_prefix,
            self._key_width,
            items_str,
        )

    def _current_size(self):
        """Answer the current serialised size of this node.

        This differs from self._raw_size in that it includes the bytes used for
        the header.
        """
        if self._common_serialised_prefix is None:
            bytes_for_items = 0
            prefix_len = 0
        else:
            # We will store a single string with the common prefix
            # And then that common prefix will not be stored in any of the
            # entry lines
            prefix_len = len(self._common_serialised_prefix)
            bytes_for_items = self._raw_size - (prefix_len * self._len)
        return (
            9  # 'chkleaf:\n' +
            + len(str(self._maximum_size))
            + 1
            + len(str(self._key_width))
            + 1
            + len(str(self._len))
            + 1
            + prefix_len
            + 1
            + bytes_for_items
        )

    @classmethod
    def deserialise(cls, bytes, key, search_key_func=None):
        """Deserialise bytes, with key key, into a LeafNode.

        :param bytes: The bytes of the node.
        :param key: The key that the serialised node has.
        """
        key = tuple(key)
        return _deserialise_leaf_node(bytes, key, search_key_func=search_key_func)

    def iteritems(self, store, key_filter=None):
        """Iterate over items in the node.

        :param key_filter: A filter to apply to the node. It should be a
            list/set/dict or similar repeatedly iterable container.
        """
        if key_filter is not None:
            # Adjust the filter - short elements go to a prefix filter. All
            # other items are looked up directly.
            # XXX: perhaps defaultdict? Profiling<rinse and repeat>
            filters = {}
            for key in key_filter:
                if len(key) == self._key_width:
                    # This filter is meant to match exactly one key, yield it
                    # if we have it.
                    try:
                        yield key, self._items[key]
                    except KeyError:
                        # This key is not present in this map, continue
                        pass
                else:
                    # Short items, we need to match based on a prefix
                    filters.setdefault(len(key), set()).add(key)
            if filters:
                filters_itemview = filters.items()
                for item in self._items.items():
                    for length, length_filter in filters_itemview:
                        if item[0][:length] in length_filter:
                            yield item
                            break
        else:
            yield from self._items.items()

    def _key_value_len(self, key, value):
        # TODO: Should probably be done without actually joining the key, but
        #       then that can be done via the C extension
        return (
            len(self._serialise_key(key))
            + 1
            + len(b"%d" % value.count(b"\n"))
            + 1
            + len(value)
            + 1
        )

    def _search_key(self, key: Key) -> bytes:
        return self._search_key_func(key)

    def _map_no_split(self, key: Key, value):
        """Map a key to a value.

        This assumes either the key does not already exist, or you have already
        removed its size and length from self.

        :return: True if adding this node should cause us to split.
        """
        self._items[key] = value
        self._raw_size += self._key_value_len(key, value)
        self._len += 1
        serialised_key = self._serialise_key(key)
        if self._common_serialised_prefix is None:
            self._common_serialised_prefix = serialised_key
        else:
            self._common_serialised_prefix = self.common_prefix(
                self._common_serialised_prefix, serialised_key
            )
        search_key = self._search_key(key)
        if self._search_prefix is _unknown:
            self._compute_search_prefix()
        if self._search_prefix is None:
            self._search_prefix = search_key
        else:
            self._search_prefix = self.common_prefix(self._search_prefix, search_key)
        if (
            self._len > 1
            and self._maximum_size
            and self._current_size() > self._maximum_size
        ):
            # Check to see if all of the search_keys for this node are
            # identical. We allow the node to grow under that circumstance
            # (we could track this as common state, but it is infrequent)
            if (
                search_key != self._search_prefix
                or not self._are_search_keys_identical()
            ):
                return True
        return False

    def _split(self, store):
        """We have overflowed.

        Split this node into multiple LeafNodes, return it up the stack so that
        the next layer creates a new InternalNode and references the new nodes.

        :return: (common_serialised_prefix, [(node_serialised_prefix, node)])
        """
        if self._search_prefix is _unknown:
            raise AssertionError("Search prefix must be known")
        common_prefix = self._search_prefix
        split_at = len(common_prefix) + 1
        result = {}
        for key, value in self._items.items():
            search_key = self._search_key(key)
            prefix = search_key[:split_at]
            # TODO: Generally only 1 key can be exactly the right length,
            #       which means we can only have 1 key in the node pointed
            #       at by the 'prefix\0' key. We might want to consider
            #       folding it into the containing InternalNode rather than
            #       having a fixed length-1 node.
            #       Note this is probably not true for hash keys, as they
            #       may get a '\00' node anywhere, but won't have keys of
            #       different lengths.
            if len(prefix) < split_at:
                prefix += b"\x00" * (split_at - len(prefix))
            if prefix not in result:
                node = LeafNode(search_key_func=self._search_key_func)
                node.set_maximum_size(self._maximum_size)
                node._key_width = self._key_width
                result[prefix] = node
            else:
                node = result[prefix]
            sub_prefix, node_details = node.map(store, key, value)
            if len(node_details) > 1:
                if prefix != sub_prefix:
                    # This node has been split and is now found via a different
                    # path
                    result.pop(prefix)
                new_node = InternalNode(
                    sub_prefix, search_key_func=self._search_key_func
                )
                new_node.set_maximum_size(self._maximum_size)
                new_node._key_width = self._key_width
                for split, node in node_details:
                    new_node.add_node(split, node)
                result[prefix] = new_node
        return common_prefix, list(result.items())

    def map(self, store, key: Key, value):
        """Map key to value."""
        if key in self._items:
            self._raw_size -= self._key_value_len(key, self._items[key])
            self._len -= 1
        self._key = None
        if self._map_no_split(key, value):
            return self._split(store)
        else:
            if self._search_prefix is _unknown:
                raise AssertionError("{!r} must be known".format(self._search_prefix))
            return self._search_prefix, [(b"", self)]

    _serialise_key = b"\x00".join

    def serialise(self, store):
        """Serialise the LeafNode to store.

        :param store: A VersionedFiles honouring the CHK extensions.
        :return: An iterable of the keys inserted by this operation.
        """
        lines = [b"chkleaf:\n"]
        lines.append(b"%d\n" % self._maximum_size)
        lines.append(b"%d\n" % self._key_width)
        lines.append(b"%d\n" % self._len)
        if self._common_serialised_prefix is None:
            lines.append(b"\n")
            if len(self._items) != 0:
                raise AssertionError(
                    "If _common_serialised_prefix is None we should have no items"
                )
        else:
            lines.append(b"%s\n" % (self._common_serialised_prefix,))
            prefix_len = len(self._common_serialised_prefix)
        for key, value in sorted(self._items.items()):
            # Always add a final newline
            value_lines = osutils.chunks_to_lines([value + b"\n"])
            serialized = b"%s\x00%d\n" % (self._serialise_key(key), len(value_lines))
            if not serialized.startswith(self._common_serialised_prefix):
                raise AssertionError(
                    "We thought the common prefix was {!r}"
                    " but entry {!r} does not have it in common".format(
                        self._common_serialised_prefix, serialized
                    )
                )
            lines.append(serialized[prefix_len:])
            lines.extend(value_lines)
        sha1, _, _ = store.add_lines((None,), (), lines)
        self._key = (b"sha1:" + sha1,)
        data = b"".join(lines)
        if len(data) != self._current_size():
            raise AssertionError("Invalid _current_size")
        _get_cache()[self._key] = data
        return [self._key]

    def refs(self):
        """Return the references to other CHK's held by this node."""
        return []

    def _compute_search_prefix(self):
        """Determine the common search prefix for all keys in this node.

        :return: A bytestring of the longest search key prefix that is
            unique within this node.
        """
        search_keys = [self._search_key_func(key) for key in self._items]
        self._search_prefix = self.common_prefix_for_keys(search_keys)
        return self._search_prefix

    def _are_search_keys_identical(self):
        """Check to see if the search keys for all entries are the same.

        When using a hash as the search_key it is possible for non-identical
        keys to collide. If that happens enough, we may try overflow a
        LeafNode, but as all are collisions, we must not split.
        """
        common_search_key = None
        for key in self._items:
            search_key = self._search_key(key)
            if common_search_key is None:
                common_search_key = search_key
            elif search_key != common_search_key:
                return False
        return True

    def _compute_serialised_prefix(self):
        """Determine the common prefix for serialised keys in this node.

        :return: A bytestring of the longest serialised key prefix that is
            unique within this node.
        """
        serialised_keys = [self._serialise_key(key) for key in self._items]
        self._common_serialised_prefix = self.common_prefix_for_keys(serialised_keys)
        return self._common_serialised_prefix

    def unmap(self, store, key):
        """Unmap key from the node."""
        try:
            self._raw_size -= self._key_value_len(key, self._items[key])
        except KeyError:
            trace.mutter("key %s not found in %r", key, self._items)
            raise
        self._len -= 1
        del self._items[key]
        self._key = None
        # Recompute from scratch
        self._compute_search_prefix()
        self._compute_serialised_prefix()
        return self


class InternalNode(Node):
    """A node that contains references to other nodes.

    An InternalNode is responsible for mapping search key prefixes to child
    nodes.

    :ivar _items: serialised_key => node dictionary. node may be a tuple,
        LeafNode or InternalNode.
    """

    __slots__ = ("_node_width",)

    def __init__(self, prefix=b"", search_key_func=None):
        Node.__init__(self)
        # The size of an internalnode with default values and no children.
        # How many octets key prefixes within this node are.
        self._node_width = 0
        self._search_prefix = prefix
        if search_key_func is None:
            self._search_key_func = _search_key_plain
        else:
            self._search_key_func = search_key_func

    def add_node(self, prefix, node: "Node") -> "Node":
        """Add a child node with prefix prefix, and node node.

        :param prefix: The search key prefix for node.
        :param node: The node being added.
        """
        if self._search_prefix is None:
            raise AssertionError("_search_prefix should not be None")
        if not isinstance(node, (tuple, Node)):
            raise AssertionError(
                "Invalid node type: {!r}".format(type(node))
            )
        if not prefix.startswith(self._search_prefix):
            raise AssertionError(
                "prefixes mismatch: {} must start with {}".format(
                    prefix, self._search_prefix
                )
            )
        if len(prefix) != len(self._search_prefix) + 1:
            raise AssertionError(
                f"prefix wrong length: len({prefix}) is not {len(self._search_prefix) + 1}"
            )
        self._len += len(node)
        if not len(self._items):
            self._node_width = len(prefix)
        if self._node_width != len(self._search_prefix) + 1:
            raise AssertionError(
                f"node width mismatch: {self._node_width} is not {len(self._search_prefix) + 1}"
            )
        self._items[prefix] = node
        self._key = None

    def _current_size(self):
        """Answer the current serialised size of this node."""
        return (
            self._raw_size
            + len(str(self._len))
            + len(str(self._key_width))
            + len(str(self._maximum_size))
        )

    @classmethod
    def deserialise(cls, bytes, key, search_key_func: Optional[SearchKeyFunc] = None):
        """Deserialise bytes to an InternalNode, with key key.

        :param bytes: The bytes of the node.
        :param key: The key that the serialised node has.
        :return: An InternalNode instance.
        """
        key = tuple(key)
        return _deserialise_internal_node(bytes, key, search_key_func=search_key_func)

    def iteritems(self, store, key_filter: Optional[list[Key]] = None) -> Generator[tuple[Key, bytes]]:
        for node, node_filter in self._iter_nodes(store, key_filter=key_filter):
            yield from node.iteritems(store, key_filter=node_filter)

    def _iter_nodes(
            self, store, key_filter: Optional[KeyFilter] =None,
            batch_size: Optional[int] = None
    ) -> Generator[tuple[Node, Optional[list[Key]]]]:
        """Iterate over node objects which match key_filter.

        :param store: A store to use for accessing content.
        :param key_filter: A key filter to filter nodes. Only nodes that might
            contain a key in key_filter will be returned.
        :param batch_size: If not None, then we will return the nodes that had
            to be read using get_record_stream in batches, rather than reading
            them all at once.
        :return: An iterable of nodes. This function does not have to be fully
            consumed.  (There will be no pending I/O when items are being returned.)
        """
        # Map from chk key ('sha1:...',) to (prefix, key_filter)
        # prefix is the key in self._items to use, key_filter is the key_filter
        # entries that would match this node
        keys: dict[Key, tuple[SerialisedKey, Optional[list[Key]]]] = {}
        shortcut = False
        if key_filter is None:
            # yielding all nodes, yield whatever we have, and queue up a read
            # for whatever we are missing
            shortcut = True
            for prefix, node in self._items.items():
                if isinstance(node, tuple):
                    keys[node] = (prefix, None)
                elif isinstance(node, Node):
                    yield node, None
                else:
                    raise AssertionError(
                        "Invalid node type: {!r}".format(type(node))
                    )
        elif len(key_filter) == 1:
            # Technically, this path could also be handled by the first check
            # in 'self._node_width' in length_filters. However, we can handle
            # this case without spending any time building up the
            # prefix_to_keys, etc state.

            # This is a bit ugly, but TIMEIT showed it to be by far the fastest
            # 0.626us   list(key_filter)[0]
            #       is a func() for list(), 2 mallocs, and a getitem
            # 0.489us   [k for k in key_filter][0]
            #       still has the mallocs, avoids the func() call
            # 0.350us   iter(key_filter).next()
            #       has a func() call, and mallocs an iterator
            # 0.125us   for key in key_filter: pass
            #       no func() overhead, might malloc an iterator
            # 0.105us   for key in key_filter: break
            #       no func() overhead, might malloc an iterator, probably
            #       avoids checking an 'else' clause as part of the for
            for key in key_filter:  # noqa: B007
                break
            search_prefix = self._search_prefix_filter(key)
            if len(search_prefix) == self._node_width:
                # This item will match exactly, so just do a dict lookup, and
                # see what we can return
                shortcut = True
                try:
                    node = self._items[search_prefix]
                except KeyError:
                    # A given key can only match 1 child node, if it isn't
                    # there, then we can just return nothing
                    return
                if isinstance(node, tuple):
                    keys[node] = (search_prefix, [key])
                elif isinstance(node, Node):
                    # This is loaded, and the only thing that can match,
                    # return
                    yield node, [key]
                    return
                else:
                    raise AssertionError(
                        "Invalid node type: {!r}".format(type(node))
                    )
        if not shortcut:
            # First, convert all keys into a list of search prefixes
            # Aggregate common prefixes, and track the keys they come from
            prefix_to_keys: dict[SerialisedKey, list[Key]] = {}
            length_filters: dict[int, set[SerialisedKey]] = {}
            node_key_filter: Optional[list[Key]] = None
            if key_filter is None:
                raise AssertionError("key_filter must not be None")
            for key in key_filter:
                search_prefix = self._search_prefix_filter(key)
                length_filter = length_filters.setdefault(len(search_prefix), set())
                length_filter.add(search_prefix)
                prefix_to_keys.setdefault(search_prefix, []).append(key)

            if self._node_width in length_filters and len(length_filters) == 1:
                # all of the search prefixes match exactly _node_width. This
                # means that everything is an exact match, and we can do a
                # lookup into self._items, rather than iterating over the items
                # dict.
                search_prefixes = length_filters[self._node_width]
                for search_prefix in search_prefixes:
                    try:
                        node = self._items[search_prefix]
                    except KeyError:
                        # We can ignore this one
                        continue
                    node_key_filter = prefix_to_keys[search_prefix]
                    if isinstance(node, tuple):
                        keys[node] = (search_prefix, node_key_filter)
                    elif isinstance(node, Node):
                        yield node, node_key_filter
                    else:
                        raise AssertionError(
                            "Invalid node type: {!r}".format(type(node))
                        )
            else:
                # The slow way. We walk every item in self._items, and check to
                # see if there are any matches
                length_filters_itemview = length_filters.items()
                for prefix, node in self._items.items():
                    node_key_filter = []
                    for length, length_filter in length_filters_itemview:
                        sub_prefix = prefix[:length]
                        if sub_prefix in length_filter:
                            node_key_filter.extend(prefix_to_keys[sub_prefix])
                    if node_key_filter:  # this key matched something, yield it
                        if isinstance(node, tuple):
                            keys[node] = (prefix, node_key_filter)
                        elif isinstance(node, Node):
                            yield node, node_key_filter
                        else:
                            raise AssertionError(
                                "Invalid node type: {!r}".format(type(node))
                            )
        if keys:
            # Look in the page cache for some more bytes
            found_keys = set()
            for key in keys:
                try:
                    bytes = _get_cache()[key]
                except KeyError:
                    continue
                else:
                    node = _deserialise(
                        bytes, key, search_key_func=self._search_key_func
                    )
                    prefix, node_key_filter = keys[key]
                    if not isinstance(node, Node):
                        raise AssertionError(
                            "Invalid node type: {!r}".format(type(node))
                        )
                    self._items[prefix] = node
                    found_keys.add(key)
                    yield node, node_key_filter
            for key in found_keys:
                del keys[key]
        if keys:
            # demand load some pages.
            if batch_size is None:
                # Read all the keys in
                batch_size = len(keys)
            key_order = list(keys)
            for batch_start in range(0, len(key_order), batch_size):
                batch = key_order[batch_start : batch_start + batch_size]
                # We have to fully consume the stream so there is no pending
                # I/O, so we buffer the nodes for now.
                stream = store.get_record_stream(batch, "unordered", True)
                node_and_filters = []
                for record in stream:
                    bytes = record.get_bytes_as("fulltext")
                    node = _deserialise(
                        bytes, record.key, search_key_func=self._search_key_func
                    )
                    prefix, node_key_filter = keys[record.key]
                    node_and_filters.append((node, node_key_filter))
                    if not isinstance(node, Node):
                        raise AssertionError(
                            "Invalid node type: {!r}".format(type(node))
                        )
                    self._items[prefix] = node
                    _get_cache()[record.key] = bytes
                yield from node_and_filters

    def map(self, store, key, value):
        """Map key to value."""
        if not len(self._items):
            raise AssertionError("can't map in an empty InternalNode.")
        search_key = self._search_key(key)
        if self._node_width != len(self._search_prefix) + 1:
            raise AssertionError(
                f"node width mismatch: {self._node_width} is not {len(self._search_prefix) + 1}"
            )
        if not search_key.startswith(self._search_prefix):
            # This key doesn't fit in this index, so we need to split at the
            # point where it would fit, insert self into that internal node,
            # and then map this key into that node.
            new_prefix = self.common_prefix(self._search_prefix, search_key)
            new_parent = InternalNode(new_prefix, search_key_func=self._search_key_func)
            new_parent.set_maximum_size(self._maximum_size)
            new_parent._key_width = self._key_width
            new_parent.add_node(self._search_prefix[: len(new_prefix) + 1], self)
            return new_parent.map(store, key, value)
        children = [node for node, _ in self._iter_nodes(store, key_filter=[key])]
        if children:
            child = children[0]
        else:
            # new child needed:
            child = self._new_child(search_key, LeafNode)
        old_len = len(child)
        if isinstance(child, LeafNode):
            old_size = child._current_size()
        else:
            old_size = None
        prefix, node_details = child.map(store, key, value)
        if len(node_details) == 1:
            # child may have shrunk, or might be a new node
            child = node_details[0][1]
            self._len = self._len - old_len + len(child)
            self._items[search_key] = child
            self._key = None
            new_node = self
            if isinstance(child, LeafNode):
                if old_size is None:
                    # The old node was an InternalNode which means it has now
                    # collapsed, so we need to check if it will chain to a
                    # collapse at this level.
                    trace.mutter("checking remap as InternalNode -> LeafNode")
                    new_node = self._check_remap(store)
                else:
                    # If the LeafNode has shrunk in size, we may want to run
                    # a remap check. Checking for a remap is expensive though
                    # and the frequency of a successful remap is very low.
                    # Shrinkage by small amounts is common, so we only do the
                    # remap check if the new_size is low or the shrinkage
                    # amount is over a configurable limit.
                    new_size = child._current_size()
                    shrinkage = old_size - new_size
                    if (
                        shrinkage > 0 and new_size < _INTERESTING_NEW_SIZE
                    ) or shrinkage > _INTERESTING_SHRINKAGE_LIMIT:
                        trace.mutter(
                            "checking remap as size shrunk by %d to be %d",
                            shrinkage,
                            new_size,
                        )
                        new_node = self._check_remap(store)
            if new_node._search_prefix is None:
                raise AssertionError("_search_prefix should not be None")
            return new_node._search_prefix, [(b"", new_node)]
        # child has overflown - create a new intermediate node.
        # XXX: This is where we might want to try and expand our depth
        # to refer to more bytes of every child (which would give us
        # multiple pointers to child nodes, but less intermediate nodes)
        child = self._new_child(search_key, InternalNode)
        child._search_prefix = prefix
        for split, node in node_details:
            child.add_node(split, node)
        self._len = self._len - old_len + len(child)
        self._key = None
        return self._search_prefix, [(b"", self)]

    def _new_child(self, search_key, klass):
        """Create a new child node of type klass."""
        child = klass()
        child.set_maximum_size(self._maximum_size)
        child._key_width = self._key_width
        child._search_key_func = self._search_key_func
        self._items[search_key] = child
        return child

    def serialise(self, store):
        """Serialise the node to store.

        :param store: A VersionedFiles honouring the CHK extensions.
        :return: An iterable of the keys inserted by this operation.
        """
        for node in self._items.values():
            if isinstance(node, tuple):
                # Never deserialised.
                continue
            elif isinstance(node, Node):
                if node._key is not None:
                    # Never altered
                    continue
                for key in node.serialise(store):
                    yield key
            else:
                raise AssertionError(
                    f"InternalNode._items should only contain tuples or Nodes, not {node.__class__}"
                )
        lines = [b"chknode:\n"]
        lines.append(b"%d\n" % self._maximum_size)
        lines.append(b"%d\n" % self._key_width)
        lines.append(b"%d\n" % self._len)
        if self._search_prefix is None:
            raise AssertionError("_search_prefix should not be None")
        lines.append(b"%s\n" % (self._search_prefix,))
        prefix_len = len(self._search_prefix)
        for prefix, node in sorted(self._items.items()):
            if isinstance(node, tuple):
                key = node[0]
            elif isinstance(node, Node):
                key = node._key[0]
            else:
                raise AssertionError(
                    f"InternalNode._items should only contain tuples or Nodes, not {node.__class__}"
                )
            serialised = b"%s\x00%s\n" % (prefix, key)
            if not serialised.startswith(self._search_prefix):
                raise AssertionError(
                    "prefixes mismatch: {} must start with {}".format(
                        serialised, self._search_prefix
                    )
                )
            lines.append(serialised[prefix_len:])
        sha1, _, _ = store.add_lines((None,), (), lines)
        self._key = (b"sha1:" + sha1,)
        _get_cache()[self._key] = b"".join(lines)
        yield self._key

    def _search_key(self, key: Key) -> SerialisedKey:
        """Return the serialised key for key in this node."""
        # search keys are fixed width. All will be self._node_width wide, so we
        # pad as necessary.
        return (self._search_key_func(key) + b"\x00" * self._node_width)[
            : self._node_width
        ]

    def _search_prefix_filter(self, key: Key) -> SerialisedKey:
        """Serialise key for use as a prefix filter in iteritems."""
        return self._search_key_func(key)[: self._node_width]

    def _split(self, offset: int) -> Iterator[tuple[SerialisedKey, Node]]:
        """Split this node into smaller nodes starting at offset.

        :param offset: The offset to start the new child nodes at.
        :return: An iterable of (prefix, node) tuples. prefix is a byte
            prefix for reaching node.
        """
        if offset >= self._node_width:
            for node in self._items.values():
                yield from node._split(offset)

    def refs(self) -> list[tuple[SerialisedKey, Key]]:
        """Return the references to other CHK's held by this node."""
        if self._key is None:
            raise AssertionError("unserialised nodes have no refs.")
        refs = []
        for value in self._items.values():
            if isinstance(value, tuple):
                refs.append(value)
            elif isinstance(value, Node):
                refs.append(value.key())
            else:
                raise AssertionError(
                    f"InternalNode._items should only contain tuples or Nodes, not {value.__class__}"
                )
        return refs

    def _compute_search_prefix(self, extra_key=None):
        """Return the unique key prefix for this node.

        :return: A bytestring of the longest search key prefix that is
            unique within this node.
        """
        self._search_prefix = self.common_prefix_for_keys(self._items)
        return self._search_prefix

    def unmap(self, store, key: Key, check_remap: bool = True) -> Node:
        """Remove key from this node and its children."""
        if not len(self._items):
            raise AssertionError("can't unmap in an empty InternalNode.")
        children = [node for node, _ in self._iter_nodes(store, key_filter=[key])]
        if children:
            child = children[0]
        else:
            raise KeyError(key)
        self._len -= 1
        unmapped = child.unmap(store, key)
        self._key = None
        search_key = self._search_key(key)
        if len(unmapped) == 0:
            # All child nodes are gone, remove the child:
            del self._items[search_key]
            unmapped = None
        else:
            # Stash the returned node
            self._items[search_key] = unmapped
        if len(self._items) == 1:
            # this node is no longer needed:
            return list(self._items.values())[0]
        if isinstance(unmapped, InternalNode):
            return self
        if check_remap:
            return self._check_remap(store)
        else:
            return self

    def _check_remap(self, store) -> "LeafNode":
        """Check if all keys contained by children fit in a single LeafNode.

        :param store: A store to use for reading more nodes
        :return: Either self, or a new LeafNode which should replace self.
        """
        # Logic for how we determine when we need to rebuild
        # 1) Implicitly unmap() is removing a key which means that the child
        #    nodes are going to be shrinking by some extent.
        # 2) If all children are LeafNodes, it is possible that they could be
        #    combined into a single LeafNode, which can then completely replace
        #    this internal node with a single LeafNode
        # 3) If *one* child is an InternalNode, we assume it has already done
        #    all the work to determine that its children cannot collapse, and
        #    we can then assume that those nodes *plus* the current nodes don't
        #    have a chance of collapsing either.
        #    So a very cheap check is to just say if 'unmapped' is an
        #    InternalNode, we don't have to check further.

        # TODO: Another alternative is to check the total size of all known
        #       LeafNodes. If there is some formula we can use to determine the
        #       final size without actually having to read in any more
        #       children, it would be nice to have. However, we have to be
        #       careful with stuff like nodes that pull out the common prefix
        #       of each key, as adding a new key can change the common prefix
        #       and cause size changes greater than the length of one key.
        #       So for now, we just add everything to a new Leaf until it
        #       splits, as we know that will give the right answer
        new_leaf = LeafNode(search_key_func=self._search_key_func)
        new_leaf.set_maximum_size(self._maximum_size)
        new_leaf._key_width = self._key_width
        # A batch_size of 16 was chosen because:
        #   a) In testing, a 4k page held 14 times. So if we have more than 16
        #      leaf nodes we are unlikely to hold them in a single new leaf
        #      node. This still allows for 1 round trip
        #   b) With 16-way fan out, we can still do a single round trip
        #   c) With 255-way fan out, we don't want to read all 255 and destroy
        #      the page cache, just to determine that we really don't need it.
        for node, _ in self._iter_nodes(store, batch_size=16):
            if isinstance(node, InternalNode):
                # Without looking at any leaf nodes, we are sure
                return self
            for key, value in node._items.items():
                if new_leaf._map_no_split(key, value):
                    return self
        trace.mutter("remap generated a new LeafNode")
        return new_leaf


def _deserialise(data, key, search_key_func):
    """Helper for repositorydetails - convert bytes to a node."""
    if data.startswith(b"chkleaf:\n"):
        node = LeafNode.deserialise(data, key, search_key_func=search_key_func)
    elif data.startswith(b"chknode:\n"):
        node = InternalNode.deserialise(data, key, search_key_func=search_key_func)
    else:
        raise AssertionError("Unknown node type.")
    return node


class CHKMapDifference:
    """Iterate the stored pages and key,value pairs for (new - old).

    This class provides a generator over the stored CHK pages and the
    (key, value) pairs that are in any of the new maps and not in any of the
    old maps.

    Note that it may yield chk pages that are common (especially root nodes),
    but it won't yield (key,value) pairs that are common.
    """

    def __init__(self, store, new_root_keys, old_root_keys, search_key_func, pb=None):
        # TODO: Should we add a StaticTuple barrier here? It would be nice to
        #       force callers to use StaticTuple, because there will often be
        #       lots of keys passed in here. And even if we cast it locally,
        #       that just meanst that we will have *both* a StaticTuple and a
        #       tuple() in memory, referring to the same object. (so a net
        #       increase in memory, not a decrease.)
        self._store = store
        self._new_root_keys = new_root_keys
        self._old_root_keys = old_root_keys
        self._pb = pb
        # All uninteresting chks that we have seen. By the time they are added
        # here, they should be either fully ignored, or queued up for
        # processing
        # TODO: This might grow to a large size if there are lots of merge
        #       parents, etc. However, it probably doesn't scale to O(history)
        #       like _processed_new_refs does.
        self._all_old_chks = set(self._old_root_keys)
        # All items that we have seen from the old_root_keys
        self._all_old_items = set()
        # These are interesting items which were either read, or already in the
        # interesting queue (so we don't need to walk them again)
        # TODO: processed_new_refs becomes O(all_chks), consider switching to
        #       SimpleSet here.
        self._processed_new_refs = set()
        self._search_key_func = search_key_func

        # The uninteresting and interesting nodes to be searched
        self._old_queue = []
        self._new_queue = []
        # Holds the (key, value) items found when processing the root nodes,
        # waiting for the uninteresting nodes to be walked
        self._new_item_queue = []
        self._state = None

    def _read_nodes_from_store(self, keys):
        # We chose not to use _get_cache(), because we think in
        # terms of records to be yielded. Also, we expect to touch each page
        # only 1 time during this code. (We may want to evaluate saving the
        # raw bytes into the page cache, which would allow a working tree
        # update after the fetch to not have to read the bytes again.)
        stream = self._store.get_record_stream(keys, "unordered", True)
        for record in stream:
            if self._pb is not None:
                self._pb.tick()
            if record.storage_kind == "absent":
                raise errors.NoSuchRevision(self._store, record.key)
            bytes = record.get_bytes_as("fulltext")
            node = _deserialise(
                bytes, record.key, search_key_func=self._search_key_func
            )
            if isinstance(node, InternalNode):
                # Note we don't have to do node.refs() because we know that
                # there are no children that have been pushed into this node
                # Note: Using as_st() here seemed to save 1.2MB, which would
                #       indicate that we keep 100k prefix_refs around while
                #       processing. They *should* be shorter lived than that...
                #       It does cost us ~10s of processing time
                prefix_refs = list(node._items.items())
                items = []
            else:
                prefix_refs = []
                # Note: We don't use a StaticTuple here. Profiling showed a
                #       minor memory improvement (0.8MB out of 335MB peak 0.2%)
                #       But a significant slowdown (15s / 145s, or 10%)
                items = list(node._items.items())
            yield record, node, prefix_refs, items

    def _read_old_roots(self):
        old_chks_to_enqueue = []
        all_old_chks = self._all_old_chks
        for _record, _node, prefix_refs, items in self._read_nodes_from_store(
            self._old_root_keys
        ):
            # Uninteresting node
            prefix_refs = [p_r for p_r in prefix_refs if p_r[1] not in all_old_chks]
            new_refs = [p_r[1] for p_r in prefix_refs]
            all_old_chks.update(new_refs)
            # TODO: This might be a good time to turn items into StaticTuple
            #       instances and possibly intern them. However, this does not
            #       impact 'initial branch' performance, so I'm not worrying
            #       about this yet
            self._all_old_items.update(items)
            # Queue up the uninteresting references
            # Don't actually put them in the 'to-read' queue until we have
            # finished checking the interesting references
            old_chks_to_enqueue.extend(prefix_refs)
        return old_chks_to_enqueue

    def _enqueue_old(self, new_prefixes, old_chks_to_enqueue):
        # At this point, we have read all the uninteresting and interesting
        # items, so we can queue up the uninteresting stuff, knowing that we've
        # handled the interesting ones
        for prefix, ref in old_chks_to_enqueue:
            not_interesting = True
            for i in range(len(prefix), 0, -1):
                if prefix[:i] in new_prefixes:
                    not_interesting = False
                    break
            if not_interesting:
                # This prefix is not part of the remaining 'interesting set'
                continue
            self._old_queue.append(ref)

    def _read_all_roots(self):
        """Read the root pages.

        This is structured as a generator, so that the root records can be
        yielded up to whoever needs them without any buffering.
        """
        # This is the bootstrap phase
        if not self._old_root_keys:
            # With no old_root_keys we can just shortcut and be ready
            # for _flush_new_queue
            self._new_queue = list(self._new_root_keys)
            return
        old_chks_to_enqueue = self._read_old_roots()
        # filter out any root keys that are already known to be uninteresting
        new_keys = set(self._new_root_keys).difference(self._all_old_chks)
        # These are prefixes that are present in new_keys that we are
        # thinking to yield
        new_prefixes = set()
        # We are about to yield all of these, so we don't want them getting
        # added a second time
        processed_new_refs = self._processed_new_refs
        processed_new_refs.update(new_keys)
        for record, _node, prefix_refs, items in self._read_nodes_from_store(new_keys):
            # At this level, we now know all the uninteresting references
            # So we filter and queue up whatever is remaining
            prefix_refs = [
                p_r
                for p_r in prefix_refs
                if p_r[1] not in self._all_old_chks and p_r[1] not in processed_new_refs
            ]
            refs = [p_r[1] for p_r in prefix_refs]
            new_prefixes.update([p_r[0] for p_r in prefix_refs])
            self._new_queue.extend(refs)
            # TODO: We can potentially get multiple items here, however the
            #       current design allows for this, as callers will do the work
            #       to make the results unique. We might profile whether we
            #       gain anything by ensuring unique return values for items
            # TODO: This might be a good time to cast to StaticTuple, as
            #       self._new_item_queue will hold the contents of multiple
            #       records for an extended lifetime
            new_items = [item for item in items if item not in self._all_old_items]
            self._new_item_queue.extend(new_items)
            new_prefixes.update([self._search_key_func(item[0]) for item in new_items])
            processed_new_refs.update(refs)
            yield record
        # For new_prefixes we have the full length prefixes queued up.
        # However, we also need possible prefixes. (If we have a known ref to
        # 'ab', then we also need to include 'a'.) So expand the
        # new_prefixes to include all shorter prefixes
        for prefix in list(new_prefixes):
            new_prefixes.update([prefix[:i] for i in range(1, len(prefix))])
        self._enqueue_old(new_prefixes, old_chks_to_enqueue)

    def _flush_new_queue(self):
        # No need to maintain the heap invariant anymore, just pull things out
        # and process them
        refs = set(self._new_queue)
        self._new_queue = []
        # First pass, flush all interesting items and convert to using direct refs
        all_old_chks = self._all_old_chks
        processed_new_refs = self._processed_new_refs
        all_old_items = self._all_old_items
        new_items = [item for item in self._new_item_queue if item not in all_old_items]
        self._new_item_queue = []
        if new_items:
            yield None, new_items
        refs = refs.difference(all_old_chks)
        processed_new_refs.update(refs)
        while refs:
            # TODO: Using a SimpleSet for self._processed_new_refs and
            #       saved as much as 10MB of peak memory. However, it requires
            #       implementing a non-pyrex version.
            next_refs = set()
            next_refs_update = next_refs.update
            # Inlining _read_nodes_from_store improves 'bzr branch bzr.dev'
            # from 1m54s to 1m51s. Consider it.
            for record, _, p_refs, items in self._read_nodes_from_store(refs):
                if all_old_items:
                    # using the 'if' check saves about 145s => 141s, when
                    # streaming initial branch of Launchpad data.
                    items = [item for item in items if item not in all_old_items]
                yield record, items
                next_refs_update([p_r[1] for p_r in p_refs])
                del p_refs
            # set1.difference(set/dict) walks all of set1, and checks if it
            # exists in 'other'.
            # set1.difference(iterable) walks all of iterable, and does a
            # 'difference_update' on a clone of set1. Pick wisely based on the
            # expected sizes of objects.
            # in our case it is expected that 'new_refs' will always be quite
            # small.
            next_refs = next_refs.difference(all_old_chks)
            next_refs = next_refs.difference(processed_new_refs)
            processed_new_refs.update(next_refs)
            refs = next_refs

    def _process_next_old(self):
        # Since we don't filter uninteresting any further than during
        # _read_all_roots, process the whole queue in a single pass.
        refs = self._old_queue
        self._old_queue = []
        all_old_chks = self._all_old_chks
        for _record, _, prefix_refs, items in self._read_nodes_from_store(refs):
            # TODO: Use StaticTuple here?
            self._all_old_items.update(items)
            refs = [r for _, r in prefix_refs if r not in all_old_chks]
            self._old_queue.extend(refs)
            all_old_chks.update(refs)

    def _process_queues(self):
        while self._old_queue:
            self._process_next_old()
        return self._flush_new_queue()

    def process(self):
        for record in self._read_all_roots():
            yield record, []
        for record, items in self._process_queues():
            yield record, items


def iter_interesting_nodes(
    store, interesting_root_keys, uninteresting_root_keys, pb=None
):
    """Given root keys, find interesting nodes.

    Evaluate nodes referenced by interesting_root_keys. Ones that are also
    referenced from uninteresting_root_keys are not considered interesting.

    :param interesting_root_keys: keys which should be part of the
        "interesting" nodes (which will be yielded)
    :param uninteresting_root_keys: keys which should be filtered out of the
        result set.
    :return: Yield
        (interesting record, {interesting key:values})
    """
    iterator = CHKMapDifference(
        store,
        interesting_root_keys,
        uninteresting_root_keys,
        search_key_func=store._search_key_func,
        pb=pb,
    )
    return iterator.process()


try:
    from ._chk_map_pyx import (
        _bytes_to_text_key,
        _deserialise_internal_node,
        _deserialise_leaf_node,
        _search_key_16,
        _search_key_255,
    )
except ImportError as e:
    osutils.failed_to_load_extension(e)
    from ._chk_map_py import (
        _bytes_to_text_key,  # noqa: F401
        _deserialise_internal_node,
        _deserialise_leaf_node,
        _search_key_16,
        _search_key_255,
    )
search_key_registry.register(b"hash-16-way", _search_key_16)
search_key_registry.register(b"hash-255-way", _search_key_255)


def _check_key(key):
    """Helper function to assert that a key is properly formatted.

    This generally shouldn't be used in production code, but it can be helpful
    to debug problems.
    """
    if not isinstance(key, tuple):
        raise TypeError("key {!r} is not tuple but {}".format(key, type(key)))
    if len(key) != 1:
        raise ValueError(f"key {key!r} should have length 1, not {len(key)}")
    if not isinstance(key[0], str):
        raise TypeError(
            "key {!r} should hold a str, not {!r}".format(key, type(key[0]))
        )
    if not key[0].startswith("sha1:"):
        raise ValueError("key {!r} should point to a sha1:".format(key))
