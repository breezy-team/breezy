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
from collections.abc import Callable, Generator, Iterator
from typing import Optional, Union

from .. import errors, lru_cache, osutils, registry, trace
from .._bzr_rs import chk_map as _chk_map_rs

common_prefix_many = _chk_map_rs.common_prefix_many
common_prefix_pair = _chk_map_rs.common_prefix_pair
LeafNode = _chk_map_rs.LeafNode
InternalNode = _chk_map_rs.InternalNode

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


def _search_key_plain(key: Key) -> SerialisedKey:
    """Map the key tuple into a search string that just uses the key bytes."""
    return b"\x00".join(key)


search_key_registry = registry.Registry[bytes, Callable[[Key], SerialisedKey], None]()
search_key_registry.register(b"plain", _search_key_plain)


def _deserialise_leaf_node(data, key, search_key_func=None):
    """Deserialise bytes, with key key, into a LeafNode.

    :param bytes: The bytes of the node.
    :param key: The key that the serialised node has.
    """
    result = LeafNode(search_key_func=search_key_func)
    # Splitlines can split on '\r' so don't use it, split('\n') adds an
    # extra '' if the bytes ends in a final newline.
    lines = data.split(b"\n")
    trailing = lines.pop()
    if trailing != b"":
        raise AssertionError(f"We did not have a final newline for {key}")
    items = {}
    if lines[0] != b"chkleaf:":
        raise ValueError(f"not a serialised leaf node: {bytes!r}")
    maximum_size = int(lines[1])
    width = int(lines[2])
    length = int(lines[3])
    prefix = lines[4]
    pos = 5
    while pos < len(lines):
        line = prefix + lines[pos]
        elements = line.split(b"\x00")
        pos += 1
        if len(elements) != width + 1:
            raise AssertionError(
                "Incorrect number of elements (%d vs %d) for: %r"
                % (len(elements), width + 1, line)
            )
        num_value_lines = int(elements[-1])
        value_lines = lines[pos : pos + num_value_lines]
        pos += num_value_lines
        value = b"\n".join(value_lines)
        items[tuple(elements[:-1])] = value
    if len(items) != length:
        raise AssertionError(
            "item count (%d) mismatch for key %s, bytes %r" % (length, key, bytes)
        )
    result._items = items
    result._len = length
    result._maximum_size = maximum_size
    result._key = key
    result._key_width = width
    result._raw_size = (
        sum(map(len, lines[5:]))  # the length of the suffix
        + (length) * (len(prefix))
        + (len(lines) - 5)
    )
    if not items:
        result._search_prefix = None
        result._common_serialised_prefix = None
    else:
        result._search_prefix = _unknown
        result._common_serialised_prefix = prefix
    if len(data) != result._current_size():
        raise AssertionError("_current_size computed incorrectly")
    return result


def _deserialise_internal_node(data, key, search_key_func=None):
    result = InternalNode(search_key_func=search_key_func)
    # Splitlines can split on '\r' so don't use it, remove the extra ''
    # from the result of split('\n') because we should have a trailing
    # newline
    lines = data.split(b"\n")
    if lines[-1] != b"":
        raise ValueError("last line must be ''")
    lines.pop(-1)
    items = {}
    if lines[0] != b"chknode:":
        raise ValueError(f"not a serialised internal node: {bytes!r}")
    maximum_size = int(lines[1])
    width = int(lines[2])
    length = int(lines[3])
    common_prefix = lines[4]
    for line in lines[5:]:
        line = common_prefix + line
        prefix, flat_key = line.rsplit(b"\x00", 1)
        items[prefix] = (flat_key,)
    if len(items) == 0:
        raise AssertionError(f"We didn't find any item for {key}")
    result._items = items
    result._len = length
    result._maximum_size = maximum_size
    result._key = key
    result._key_width = width
    # XXX: InternalNodes don't really care about their size, and this will
    #      change if we add prefix compression
    result._raw_size = None  # len(bytes)
    result._node_width = len(prefix)
    result._search_prefix = common_prefix
    return result


class CHKMap:
    """A persistent map from string to string backed by a CHK store."""

    __slots__ = ("_root_node", "_search_key_func", "_store")
    _root_node: Union["Node", Key]

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
                delta, f"New items are already in the map {existing_new!r}."
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

    def _dump_tree(self, include_keys=False, encoding="utf-8"):
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
            key_str = f" {decode(node_key[0])}" if node_key is not None else " None"
        result.append(f"{indent}{decode(prefix)!r} {node.__class__.__name__}{key_str}")
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
                    f"      {tuple([decode(ke) for ke in key])!r} {decode(value)!r}"
                )
        return result

    @classmethod
    def from_dict(
        klass, store, initial_value, maximum_size=0, key_width=1, search_key_func=None
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
        root_key = klass._create_directly(
            store,
            initial_value,
            maximum_size=maximum_size,
            key_width=key_width,
            search_key_func=search_key_func,
        )
        if not isinstance(root_key, tuple):
            raise AssertionError(f"we got a {type(root_key)} instead of a tuple")
        return root_key

    @classmethod
    def _create_via_map(
        klass, store, initial_value, maximum_size=0, key_width=1, search_key_func=None
    ):
        result = klass(store, None, search_key_func=search_key_func)
        result._root_node.set_maximum_size(maximum_size)
        result._root_node._key_width = key_width
        delta = []
        for key, value in initial_value.items():
            delta.append((None, key, value))
        root_key = result.apply_delta(delta)
        return root_key

    @classmethod
    def _create_directly(
        klass, store, initial_value, maximum_size=0, key_width=1, search_key_func=None
    ):
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
                            raise AssertionError(f"{self_prefix!r} != {basis_prefix!r}")
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
        if isinstance(self._root_node, tuple):
            raise AssertionError("Cannot iterate over a map with a tuple root node")
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
        if isinstance(self._root_node, tuple):
            raise AssertionError("Cannot map a key to a tuple root node")
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
            raise AssertionError("Invalid node type: {!r}".format(type(node)))

    def unmap(self, key, check_remap=True):
        """Remove key from the map."""
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


from .._bzr_rs import chk_map as _chk_map_rs

_bytes_to_text_key = _chk_map_rs._bytes_to_text_key
_search_key_16 = _chk_map_rs._search_key_16
_search_key_255 = _chk_map_rs._search_key_255

search_key_registry.register(b"hash-16-way", _search_key_16)
search_key_registry.register(b"hash-255-way", _search_key_255)


def _check_key(key):
    """Helper function to assert that a key is properly formatted.

    This generally shouldn't be used in production code, but it can be helpful
    to debug problems.
    """
    if not isinstance(key, tuple):
        raise TypeError(f"key {key!r} is not tuple but {type(key)}")
    if len(key) != 1:
        raise ValueError(f"key {key!r} should have length 1, not {len(key)}")
    if not isinstance(key[0], str):
        raise TypeError(f"key {key!r} should hold a str, not {type(key[0])!r}")
    if not key[0].startswith("sha1:"):
        raise ValueError(f"key {key!r} should point to a sha1:")
