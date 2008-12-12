# Copyright (C) 2008 Canonical Ltd
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

"""Persistent maps from tuple_of_strings->string using CHK stores.

Overview and current status:

The CHKMap class implements a dict from tuple_of_strings->string by using a trie
with internal nodes of 8-bit fan out; The key tuples are mapped to strings by
joining them by \x00, and \x00 padding shorter keys out to the length of the
longest key. Leaf nodes are packed as densely as possible, and internal nodes
are all and additional 8-bits wide leading to a sparse upper tree.

Updates to a CHKMap are done preferentially via the apply_delta method, to
allow optimisation of the update operation; but individual map/unmap calls are
possible and supported. All changes via map/unmap are buffered in memory until
the _save method is called to force serialisation of the tree. apply_delta
performs a _save implicitly.

TODO:
-----

Densely packed upper nodes.

"""

import heapq

from bzrlib import lazy_import
lazy_import.lazy_import(globals(), """
from bzrlib import versionedfile
""")
from bzrlib.lru_cache import LRUCache

# approx 2MB
_PAGE_CACHE_SIZE = 2*1024*1024 / 4*1024
_page_cache = LRUCache(_PAGE_CACHE_SIZE)


class CHKMap(object):
    """A persistent map from string to string backed by a CHK store."""

    def __init__(self, store, root_key):
        """Create a CHKMap object.

        :param store: The store the CHKMap is stored in.
        :param root_key: The root key of the map. None to create an empty
            CHKMap.
        """
        self._store = store
        if root_key is None:
            self._root_node = LeafNode()
        else:
            self._root_node = self._node_key(root_key)

    def apply_delta(self, delta):
        """Apply a delta to the map.

        :param delta: An iterable of old_key, new_key, new_value tuples.
            If new_key is not None, then new_key->new_value is inserted
            into the map; if old_key is not None, then the old mapping
            of old_key is removed.
        """
        for old, new, value in delta:
            if old is not None and old != new:
                # unmap
                self.unmap(old)
        for old, new, value in delta:
            if new is not None:
                # map
                self.map(new, value)
        return self._save()

    def _ensure_root(self):
        """Ensure that the root node is an object not a key."""
        if type(self._root_node) == tuple:
            # Demand-load the root
            self._root_node = self._get_node(self._root_node)

    def _get_node(self, node):
        """Get a node.

        Node that this does not update the _items dict in objects containing a
        reference to this node. As such it does not prevent subsequent IO being
        performed.

        :param node: A tuple key or node object.
        :return: A node object.
        """
        if type(node) == tuple:
            bytes = self._read_bytes(node)
            return _deserialise(bytes, node)
        else:
            return node

    def _read_bytes(self, key):
        stream = self._store.get_record_stream([key], 'unordered', True)
        return stream.next().get_bytes_as('fulltext')

    def _dump_tree(self):
        """Return the tree in a string representation."""
        self._ensure_root()
        res = self._dump_tree_node(self._root_node, prefix='', indent='')
        res.append('') # Give a trailing '\n'
        return '\n'.join(res)

    def _dump_tree_node(self, node, prefix, indent):
        """For this node and all children, generate a string representation."""
        result = []
        node_key = node.key()
        if node_key is not None:
            node_key = node_key[0]
        result.append('%s%r %s %s' % (indent, prefix, node.__class__.__name__,
                                        node_key))
        if isinstance(node, InternalNode):
            # Trigger all child nodes to get loaded
            list(node._iter_nodes(self._store))
            for prefix, sub in sorted(node._items.iteritems()):
                result.extend(self._dump_tree_node(sub, prefix, indent + '  '))
        else:
            for key, value in sorted(node._items.iteritems()):
                result.append('      %r %r' % (key, value))
        return result

    @classmethod
    def from_dict(klass, store, initial_value, maximum_size=0, key_width=1):
        """Create a CHKMap in store with initial_value as the content.

        :param store: The store to record initial_value in, a VersionedFiles
            object with 1-tuple keys supporting CHK key generation.
        :param initial_value: A dict to store in store. Its keys and values
            must be bytestrings.
        :param maximum_size: The maximum_size rule to apply to nodes. This
            determines the size at which no new data is added to a single node.
        :param key_width: The number of elements in each key_tuple being stored
            in this map.
        :return: The root chk of te resulting CHKMap.
        """
        result = CHKMap(store, None)
        result._root_node.set_maximum_size(maximum_size)
        result._root_node._key_width = key_width
        delta = []
        for key, value in initial_value.items():
            delta.append((None, key, value))
        result.apply_delta(delta)
        return result._save()

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
        #    {'a': InternalNode={'aa':LeafNode={'aaa':'foo', 'aab':'bar'}, 'ab':LeafNode={'ab':'bar'}}
        #     'b': LeafNode={'b'}}
        #    the node with aaa/aab will only be encountered in the second tree
        #    after reading the 'a' subtree, but it is encountered in the first
        #    tree immediately. Variations on this may have read internal nodes like this.
        #    we want to cut the entire pending subtree when we realise we have a common node.
        #    For this we use a list of keys - the path to a node - and check the entire path is
        #    clean as we process each item.
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
        def process_node(prefix, node, path, a_map, pending):
            # take a node and expand it
            node = a_map._get_node(node)
            if type(node) == LeafNode:
                path = (node._key, path)
                for key, value in node._items.items():
                    heapq.heappush(pending, ('\x00'.join(key), value, path))
            else:
                # type(node) == InternalNode
                path = (node._key, path)
                for prefix, child in node._items.items():
                    heapq.heappush(pending, (prefix, child, path))
        process_node(None, self_node, None, self, self_pending)
        process_node(None, basis_node, None, basis, basis_pending)
        self_seen = set()
        basis_seen = set()
        excluded_keys = set()
        def check_excluded(key_path):
            # Note that this is N^2, it depends on us trimming trees
            # aggressively to not become slow.
            # A better implementation would probably have a reverse map
            # back to the children of a node, and jump straight to it when
            # a common node is detected, the proceed to remove the already
            # pending children. bzrlib.graph has a searcher module with a
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
                for prefix, node, path in basis_pending:
                    if check_excluded(path):
                        continue
                    node = basis._get_node(node)
                    if type(node) == str:
                        # a value
                        yield (tuple(prefix.split('\x00')), node, None)
                    else:
                        # subtree - fastpath the entire thing.
                        for key, value in node.iteritems(basis._store):
                            yield (key, value, None)
                return
            elif not basis_pending:
                # basis is exhausted: output remainder of self.
                for prefix, node, path in self_pending:
                    if check_excluded(path):
                        continue
                    node = self._get_node(node)
                    if type(node) == str:
                        # a value
                        yield (tuple(prefix.split('\x00')), None, node)
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
                    prefix, node, path = heapq.heappop(self_pending)
                    if check_excluded(path):
                        continue
                    if type(node) == str:
                        # a value
                        yield (tuple(prefix.split('\x00')), None, node)
                    else:
                        process_node(prefix, node, path, self, self_pending)
                        continue
                elif self_pending[0][0] > basis_pending[0][0]:
                    # expand basis
                    prefix, node, path = heapq.heappop(basis_pending)
                    if check_excluded(path):
                        continue
                    if type(node) == str:
                        # a value
                        yield (tuple(prefix.split('\x00')), node, None)
                    else:
                        process_node(prefix, node, path, basis, basis_pending)
                        continue
                else:
                    # common prefix: possibly expand both
                    if type(self_pending[0][1]) != str:
                        # process next self
                        read_self = True
                    else:
                        read_self = False
                    if type(basis_pending[0][1]) != str:
                        # process next basis
                        read_basis = True
                    else:
                        read_basis = False
                    if not read_self and not read_basis:
                        # compare a common value
                        self_details = heapq.heappop(self_pending)
                        basis_details = heapq.heappop(basis_pending)
                        if self_details[1] != basis_details[1]:
                            yield (tuple(self_details[0].split('\x00')),
                                basis_details[1], self_details[1])
                        continue
                    # At least one side wasn't a string.
                    if (self._node_key(self_pending[0][1]) ==
                        self._node_key(basis_pending[0][1])):
                        # Identical pointers, skip (and don't bother adding to
                        # excluded, it won't turn up again.
                        heapq.heappop(self_pending)
                        heapq.heappop(basis_pending)
                        continue
                    # Now we need to expand this node before we can continue
                    if read_self:
                        prefix, node, path = heapq.heappop(self_pending)
                        if check_excluded(path):
                            continue
                        process_node(prefix, node, path, self, self_pending)
                    if read_basis:
                        prefix, node, path = heapq.heappop(basis_pending)
                        if check_excluded(path):
                            continue
                        process_node(prefix, node, path, basis, basis_pending)
        # print loop_counter

    def iteritems(self, key_filter=None):
        """Iterate over the entire CHKMap's contents."""
        self._ensure_root()
        return self._root_node.iteritems(self._store, key_filter=key_filter)

    def key(self):
        """Return the key for this map."""
        if isinstance(self._root_node, tuple):
            return self._root_node
        else:
            return self._root_node._key

    def __len__(self):
        self._ensure_root()
        return len(self._root_node)

    def map(self, key, value):
        """Map a key tuple to value."""
        # Need a root object.
        self._ensure_root()
        prefix, node_details = self._root_node.map(self._store, key, value)
        if len(node_details) == 1:
            self._root_node = node_details[0][1]
        else:
            self._root_node = InternalNode(prefix)
            self._root_node.set_maximum_size(node_details[0][1].maximum_size)
            self._root_node._key_width = node_details[0][1]._key_width
            for split, node in node_details:
                self._root_node.add_node(split, node)

    def _node_key(self, node):
        """Get the key for a node whether its a tuple o r node."""
        if type(node) == tuple:
            return node
        else:
            return node._key

    def unmap(self, key):
        """remove key from the map."""
        self._ensure_root()
        unmapped = self._root_node.unmap(self._store, key)
        self._root_node = unmapped

    def _save(self):
        """Save the map completely.

        :return: The key of the root node.
        """
        if type(self._root_node) == tuple:
            # Already saved.
            return self._root_node
        keys = list(self._root_node.serialise(self._store))
        return keys[-1]


class Node(object):
    """Base class defining the protocol for CHK Map nodes."""

    def __init__(self, key_width=1):
        """Create a node.

        :param key_width: The width of keys for this node.
        """
        self._key = None
        # Current number of elements
        self._len = 0
        self._maximum_size = 0
        self._key_width = 1
        # current size in bytes
        self._size = 0
        # The pointers/values this node has - meaning defined by child classes.
        self._items = {}
        # The common lookup prefix
        self._lookup_prefix = None

    def __repr__(self):
        items_str = sorted(self._items)
        if len(items_str) > 20:
            items_str = items_str[16] + '...]'
        return '%s(key:%s len:%s size:%s max:%s prefix:%s items:%s)' % (
            self.__class__.__name__, self._key, self._len, self._size,
            self._maximum_size, self._lookup_prefix, items_str)

    def key(self):
        return self._key

    def __len__(self):
        return self._len

    @property
    def maximum_size(self):
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
        # Is there a better way to do this?
        for pos, (left, right) in enumerate(zip(prefix, key)):
            if left != right:
                pos -= 1
                break
        assert pos <= len(prefix)
        assert pos <= len(key)
        common = prefix[:pos+1]
        assert key.startswith(common)
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
                return ''
        if common_prefix is None:
            return ''
        return common_prefix


class LeafNode(Node):
    """A node containing actual key:value pairs.

    :ivar _items: A dict of key->value items. The key is in tuple form.
    :ivar _size: The number of bytes that would be used by serializing all of
        the key/value pairs.
    """

    def __init__(self):
        Node.__init__(self)
        # All of the keys in this leaf node share this common prefix
        self._common_serialised_prefix = None
        self._serialise_key = '\x00'.join

    def _current_size(self):
        """Answer the current serialised size of this node.

        This differs from self._size in that it includes the bytes used for the
        header.
        """
        return (12 # bytes overhead for the header and separators
            + len(str(self._len))
            + len(str(self._key_width))
            + len(str(self._maximum_size))
            + self._size)

    @classmethod
    def deserialise(klass, bytes, key):
        """Deserialise bytes, with key key, into a LeafNode.

        :param bytes: The bytes of the node.
        :param key: The key that the serialised node has.
        """
        result = LeafNode()
        lines = bytes.splitlines()
        items = {}
        if lines[0] != 'chkleaf:':
            raise ValueError("not a serialised leaf node: %r" % bytes)
        maximum_size = int(lines[1])
        width = int(lines[2])
        length = int(lines[3])
        for line in lines[4:]:
            elements = line.split('\x00', width)
            items[tuple(elements[:-1])] = elements[-1]
        if len(items) != length:
            raise AssertionError("item count mismatch")
        result._items = items
        result._len = length
        result._maximum_size = maximum_size
        result._key = key
        result._key_width = width
        result._size = len(bytes)
        result._compute_lookup_prefix()
        result._compute_serialised_prefix()
        return result

    def iteritems(self, store, key_filter=None):
        """Iterate over items in the node.

        :param key_filter: A filter to apply to the node. It should be a
            list/set/dict or similar repeatedly iterable container.
        """
        if key_filter is not None:
            # Adjust the filter - short elements go to a prefix filter. Would this
            # be cleaner explicitly? That would be no harder for InternalNode..
            # XXX: perhaps defaultdict? Profiling<rinse and repeat>
            filters = {}
            for key in key_filter:
                length_filter = filters.setdefault(len(key), set())
                length_filter.add(key)
            filters = filters.items()
            for item in self._items.iteritems():
                for length, length_filter in filters:
                    if item[0][:length] in length_filter:
                        yield item
                        break
        else:
            for item in self._items.iteritems():
                yield item

    def _key_value_len(self, key, value):
        # TODO: Should probably be done without actually joining the key, but
        #       then that can be done via the C extension
        return 2 + len(self._serialise_key(key)) + len(value)

    def _map_no_split(self, key, value):
        """Map a key to a value.

        This assumes either the key does not already exist, or you have already
        removed its size and length from self.

        :return: True if adding this node should cause us to split.
        """
        self._items[key] = value
        self._size += self._key_value_len(key, value)
        self._len += 1
        serialised_key = self._serialise_key(key)
        if self._common_serialised_prefix is None:
            self._common_serialised_prefix = serialised_key
        else:
            self._common_serialised_prefix = self.common_prefix(
                self._common_serialised_prefix, serialised_key)
        lookup_key = self._lookup_key(key)
        if self._lookup_prefix is None:
            self._lookup_prefix = lookup_key
        else:
            self._lookup_prefix = self.common_prefix(
                self._lookup_prefix, lookup_key)
        if (self._len > 1
            and self._maximum_size
            and self._current_size() > self._maximum_size):
            return True
        return False

    def _split(self, store):
        """We have overflowed.

        Split this node into multiple LeafNodes, return it up the stack so that
        the next layer creates a new InternalNode and references the new nodes.

        :return: (common_serialised_prefix, [(node_serialised_prefix, node)])
        """
        common_prefix = self._lookup_prefix
        split_at = len(common_prefix) + 1
        result = {}
        for key, value in self._items.iteritems():
            lookup_key = self._lookup_key(key)
            prefix = lookup_key[:split_at]
            # TODO: Generally only 1 key can be exactly the right length,
            #       which means we can only have 1 key in the node pointed
            #       at by the 'prefix\0' key. We might want to consider
            #       folding it into the containing InternalNode rather than
            #       having a fixed length-1 node.
            #       Note this is probably not true for hash keys, as they
            #       may get a '\00' node anywhere, but won't have keys of
            #       different lengths.
            if len(prefix) < split_at:
                prefix += '\x00'*(split_at - len(prefix))
            if prefix not in result:
                node = LeafNode()
                node.set_maximum_size(self._maximum_size)
                node._key_width = self._key_width
                result[prefix] = node
            else:
                node = result[prefix]
            node.map(store, key, value)
        return common_prefix, result.items()

    def map(self, store, key, value):
        """Map key to value."""
        if key in self._items:
            self._size -= self._key_value_len(key, self._items[key])
            self._len -= 1
        self._key = None
        if self._map_no_split(key, value):
            return self._split(store)
        else:
            return self._lookup_prefix, [("", self)]

    def serialise(self, store):
        """Serialise the tree to store.

        :param store: A VersionedFiles honouring the CHK extensions.
        :return: An iterable of the keys inserted by this operation.
        """
        lines = ["chkleaf:\n"]
        lines.append("%d\n" % self._maximum_size)
        lines.append("%d\n" % self._key_width)
        lines.append("%d\n" % self._len)
        for key, value in sorted(self._items.items()):
            lines.append("%s\x00%s\n" % (self._serialise_key(key), value))
        sha1, _, _ = store.add_lines((None,), (), lines)
        self._key = ("sha1:" + sha1,)
        _page_cache.add(self._key, ''.join(lines))
        return [self._key]

    def _lookup_key(self, key):
        """Return the lookup key for a key in this node."""
        return '\x00'.join(key)

    def refs(self):
        """Return the references to other CHK's held by this node."""
        return []

    def _compute_lookup_prefix(self):
        """Determine the common lookup prefix for all keys in this node.

        :return: A bytestring of the longest lookup key prefix that is
            unique within this node.
        """
        lookup_keys = [self._lookup_key(key) for key in self._items]
        self._lookup_prefix = self.common_prefix_for_keys(lookup_keys)
        return self._lookup_prefix

    def _compute_serialised_prefix(self):
        """Determine the common prefix for serialised keys in this node.

        :return: A bytestring of the longest serialised key prefix that is
            unique within this node.
        """
        serialised_keys = [self._serialise_key(key) for key in self._items]
        self._common_serialised_prefix = self.common_prefix_for_keys(
            serialised_keys)

    def unmap(self, store, key):
        """Unmap key from the node."""
        self._size -= self._key_value_len(key, self._items[key])
        self._len -= 1
        del self._items[key]
        self._key = None
        # Recompute from scratch
        self._compute_lookup_prefix()
        self._compute_serialised_prefix()
        return self


class InternalNode(Node):
    """A node that contains references to other nodes.

    An InternalNode is responsible for mapping lookup key prefixes to child
    nodes.

    :ivar _items: serialised_key => node dictionary. node may be a tuple,
        LeafNode or InternalNode.
    """

    def __init__(self, prefix=''):
        Node.__init__(self)
        # The size of an internalnode with default values and no children.
        # self._size = 12
        # How many octets key prefixes within this node are.
        self._node_width = 0
        self._lookup_prefix = prefix

    def __repr__(self):
        items_str = sorted(self._items)
        if len(items_str) > 20:
            items_str = items_str[16] + '...]'
        return '%s(key:%s len:%s size:%s max:%s prefix:%s items:%s)' % (
            self.__class__.__name__, self._key, self._len, self._size,
            self._maximum_size, self._lookup_prefix, items_str)

    def add_node(self, prefix, node):
        """Add a child node with prefix prefix, and node node.

        :param prefix: The lookup key prefix for node.
        :param node: The node being added.
        """
        assert self._lookup_prefix is not None
        assert prefix.startswith(self._lookup_prefix)
        assert len(prefix) == len(self._lookup_prefix) + 1
        self._len += len(node)
        if not len(self._items):
            self._node_width = len(prefix)
        assert self._node_width == len(self._lookup_prefix) + 1
        self._items[prefix] = node
        self._key = None

    def _current_size(self):
        """Answer the current serialised size of this node."""
        return (self._size + len(str(self._len)) + len(str(self._key_width)) +
            len(str(self._maximum_size)))

    @classmethod
    def deserialise(klass, bytes, key):
        """Deserialise bytes to an InternalNode, with key key.

        :param bytes: The bytes of the node.
        :param key: The key that the serialised node has.
        :return: An InternalNode instance.
        """
        result = InternalNode()
        lines = bytes.splitlines()
        items = {}
        if lines[0] != 'chknode:':
            raise ValueError("not a serialised internal node: %r" % bytes)
        maximum_size = int(lines[1])
        width = int(lines[2])
        length = int(lines[3])
        for line in lines[4:]:
            prefix, flat_key = line.rsplit('\x00', 1)
            items[prefix] = (flat_key,)
        result._items = items
        result._len = length
        result._maximum_size = maximum_size
        result._key = key
        result._key_width = width
        result._size = len(bytes)
        result._node_width = len(prefix)
        result._compute_lookup_prefix()
        return result

    def iteritems(self, store, key_filter=None):
        for node in self._iter_nodes(store, key_filter=key_filter):
            for item in node.iteritems(store, key_filter=key_filter):
                yield item

    def _iter_nodes(self, store, key_filter=None):
        """Iterate over node objects which match key_filter.

        :param store: A store to use for accessing content.
        :param key_filter: A key filter to filter nodes. Only nodes that might
            contain a key in key_filter will be returned.
        :return: An iterable of nodes.
        """
        nodes = []
        keys = {}
        if key_filter is None:
            for prefix, node in self._items.iteritems():
                if type(node) == tuple:
                    keys[node] = prefix
                else:
                    nodes.append(node)
        else:
            # XXX defaultdict ?
            length_filters = {}
            for key in key_filter:
                lookup_key = self._lookup_prefix_filter(key)
                length_filter = length_filters.setdefault(len(lookup_key),
                    set())
                length_filter.add(lookup_key)
            length_filters = length_filters.items()
            for prefix, node in self._items.iteritems():
                for length, length_filter in length_filters:
                    if prefix[:length] in length_filter:
                        if type(node) == tuple:
                            keys[node] = prefix
                        else:
                            nodes.append(node)
                        break
        if keys:
            # Look in the page cache for some more bytes
            found_keys = set()
            for key in keys:
                try:
                    bytes = _page_cache[key]
                except KeyError:
                    continue
                else:
                    node = _deserialise(bytes, key)
                    nodes.append(node)
                    self._items[keys[key]] = node
                    found_keys.add(key)
            for key in found_keys:
                del keys[key]
        if keys:
            # demand load some pages.
            stream = store.get_record_stream(keys, 'unordered', True)
            for record in stream:
                bytes = record.get_bytes_as('fulltext')
                node = _deserialise(bytes, record.key)
                nodes.append(node)
                self._items[keys[record.key]] = node
                _page_cache.add(record.key, bytes)
        return nodes

    def map(self, store, key, value):
        """Map key to value."""
        if not len(self._items):
            raise AssertionError("cant map in an empty InternalNode.")
        lookup_key = self._lookup_key(key)
        assert self._node_width == len(self._lookup_prefix) + 1
        if not lookup_key.startswith(self._lookup_prefix):
            # This key doesn't fit in this index, so we need to split at the
            # point where it would fit, insert self into that internal node,
            # and then map this key into that node.
            new_prefix = self.common_prefix(self._lookup_prefix,
                                            lookup_key)
            new_parent = InternalNode(new_prefix)
            new_parent.set_maximum_size(self._maximum_size)
            new_parent._key_width = self._key_width
            new_parent.add_node(self._lookup_prefix[:len(new_prefix)+1],
                                self)
            return new_parent.map(store, key, value)
        children = self._iter_nodes(store, key_filter=[key])
        if children:
            child = children[0]
        else:
            # new child needed:
            child = self._new_child(lookup_key, LeafNode)
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
            self._items[lookup_key] = child
            self._key = None
            new_node = self
            if (isinstance(child, LeafNode)
                and (old_size is None or child._current_size() < old_size)):
                # The old node was an InternalNode which means it has now
                # collapsed, so we need to check if it will chain to a collapse
                # at this level. Or the LeafNode has shrunk in size, so we need
                # to check that as well.
                new_node = self._check_remap(store)
            assert new_node._lookup_prefix is not None
            return new_node._lookup_prefix, [('', new_node)]
        # child has overflown - create a new intermediate node.
        # XXX: This is where we might want to try and expand our depth
        # to refer to more bytes of every child (which would give us
        # multiple pointers to child nodes, but less intermediate nodes)
        child = self._new_child(lookup_key, InternalNode)
        child._lookup_prefix = prefix
        for split, node in node_details:
            child.add_node(split, node)
        self._len = self._len - old_len + len(child)
        self._key = None
        return self._lookup_prefix, [("", self)]

    def _new_child(self, lookup_key, klass):
        """Create a new child node of type klass."""
        child = klass()
        child.set_maximum_size(self._maximum_size)
        child._key_width = self._key_width
        self._items[lookup_key] = child
        return child

    def serialise(self, store):
        """Serialise the node to store.

        :param store: A VersionedFiles honouring the CHK extensions.
        :return: An iterable of the keys inserted by this operation.
        """
        for node in self._items.itervalues():
            if type(node) == tuple:
                # Never deserialised.
                continue
            if node._key is not None:
                # Never altered
                continue
            for key in node.serialise(store):
                yield key
        lines = ["chknode:\n"]
        lines.append("%d\n" % self._maximum_size)
        lines.append("%d\n" % self._key_width)
        lines.append("%d\n" % self._len)
        for prefix, node in sorted(self._items.items()):
            if type(node) == tuple:
                key = node[0]
            else:
                key = node._key[0]
            lines.append("%s\x00%s\n" % (prefix, key))
        sha1, _, _ = store.add_lines((None,), (), lines)
        self._key = ("sha1:" + sha1,)
        _page_cache.add(self._key, ''.join(lines))
        yield self._key

    def _lookup_key(self, key):
        """Return the serialised key for key in this node."""
        # lookup keys are fixed width. All will be self._node_width wide, so we
        # pad as necessary.
        return ('\x00'.join(key) + '\x00'*self._node_width)[:self._node_width]

    def _lookup_prefix_filter(self, key):
        """Serialise key for use as a prefix filter in iteritems."""
        if len(key) == self._key_width:
            return self._lookup_key(key)
        return '\x00'.join(key)[:self._node_width]

    def _split(self, offset):
        """Split this node into smaller nodes starting at offset.

        :param offset: The offset to start the new child nodes at.
        :return: An iterable of (prefix, node) tuples. prefix is a byte
            prefix for reaching node.
        """
        if offset >= self._node_width:
            for node in self._items.values():
                for result in node._split(offset):
                    yield result
            return
        for key, node in self._items.items():
            pass

    def refs(self):
        """Return the references to other CHK's held by this node."""
        if self._key is None:
            raise AssertionError("unserialised nodes have no refs.")
        refs = []
        for value in self._items.itervalues():
            if type(value) == tuple:
                refs.append(value)
            else:
                refs.append(value.key())
        return refs

    def _compute_lookup_prefix(self, extra_key=None):
        """Return the unique key prefix for this node.

        :return: A bytestring of the longest lookup key prefix that is
            unique within this node.
        """
        self._lookup_prefix = self.common_prefix_for_keys(self._items)
        return self._lookup_prefix

    def unmap(self, store, key):
        """Remove key from this node and it's children."""
        if not len(self._items):
            raise AssertionError("cant unmap in an empty InternalNode.")
        children = self._iter_nodes(store, key_filter=[key])
        if children:
            child = children[0]
        else:
            raise KeyError(key)
        self._len -= 1
        unmapped = child.unmap(store, key)
        self._key = None
        lookup_key = self._lookup_key(key)
        if len(unmapped) == 0:
            # All child nodes are gone, remove the child:
            del self._items[lookup_key]
            unmapped = None
        else:
            # Stash the returned node
            self._items[lookup_key] = unmapped
        if len(self._items) == 1:
            # this node is no longer needed:
            return self._items.values()[0]
        if isinstance(unmapped, InternalNode):
            return self
        return self._check_remap(store)

    def _check_remap(self, store):
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
        new_leaf = LeafNode()
        new_leaf.set_maximum_size(self._maximum_size)
        new_leaf._key_width = self._key_width
        keys = {}
        # There is some overlap with _iter_nodes here, but not a lot, and it
        # allows us to do quick evaluation without paging everything in
        for prefix, node in self._items.iteritems():
            if type(node) == tuple:
                keys[node] = prefix
            else:
                if isinstance(node, InternalNode):
                    # Without looking at any leaf nodes, we are sure
                    return self
                for key, value in node._items.iteritems():
                    if new_leaf._map_no_split(key, value):
                        # Adding this key would cause a split, so we know we
                        # don't need to collapse
                        return self
        # So far, everything fits. Page in the rest of the nodes, and see if it
        # holds true.
        if keys:
            # TODO: Consider looping over a limited set of keys (like 25 or so
            #       at a time). If we have to read more than 25 we almost
            #       certainly won't fit them all into a single new LeafNode, so
            #       reading the extra nodes is a waste.
            #       This will probably matter more with hash serialised keys,
            #       as we will get InternalNodes with more references.
            #       The other argument is that unmap() is uncommon, so we don't
            #       need to optimize it. But map() with a slightly shorter
            #       value may happen a lot.
            stream = store.get_record_stream(keys, 'unordered', True)
            nodes = []
            # Fully consume the stream, even if we could determine that we
            # don't need to continue. We requested the bytes, we may as well
            # use them
            for record in stream:
                node = _deserialise(record.get_bytes_as('fulltext'), record.key)
                self._items[keys[record.key]] = node
                nodes.append(node)
            for node in nodes:
                if isinstance(node, InternalNode):
                    # We know we won't fit
                    return self
                for key, value in node._items.iteritems():
                    if new_leaf._map_no_split(key, value):
                        return self

        # We have gone to every child, and everything fits in a single leaf
        # node, we no longer need this internal node
        return new_leaf


def _deserialise(bytes, key):
    """Helper for repositorydetails - convert bytes to a node."""
    if bytes.startswith("chkleaf:\n"):
        return LeafNode.deserialise(bytes, key)
    elif bytes.startswith("chknode:\n"):
        return InternalNode.deserialise(bytes, key)
    else:
        raise AssertionError("Unknown node type.")


def _find_children_info(store, interesting_keys, uninteresting_keys,
                        adapter, pb):
    """Read the associated records, and determine what is interesting."""
    uninteresting_keys = set(uninteresting_keys)
    chks_to_read = uninteresting_keys.union(interesting_keys)
    next_uninteresting = set()
    next_interesting = set()
    uninteresting_items = set()
    interesting_items = set()
    interesting_records = []
    # records_read = set()
    for record in store.get_record_stream(chks_to_read, 'unordered', True):
        # records_read.add(record.key())
        if pb is not None:
            pb.tick()
        if record.storage_kind != 'fulltext':
            bytes = adapter.get_bytes(record,
                        record.get_bytes_as(record.storage_kind))
        else:
            bytes = record.get_bytes_as('fulltext')
        node = _deserialise(bytes, record.key)
        if record.key in uninteresting_keys:
            if isinstance(node, InternalNode):
                next_uninteresting.update(node.refs())
            else:
                # We know we are at a LeafNode, so we can pass None for the
                # store
                uninteresting_items.update(node.iteritems(None))
        else:
            interesting_records.append(record)
            if isinstance(node, InternalNode):
                next_interesting.update(node.refs())
            else:
                interesting_items.update(node.iteritems(None))
    # TODO: Filter out records that have already been read, as node splitting
    #       can cause us to reference the same nodes via shorter and longer
    #       paths
    return (next_uninteresting, uninteresting_items,
            next_interesting, interesting_records, interesting_items)


def _find_all_uninteresting(store, interesting_root_keys,
                            uninteresting_root_keys, adapter, pb):
    """Determine the full set of uninteresting keys."""
    # What about duplicates between interesting_root_keys and
    # uninteresting_root_keys?
    if not uninteresting_root_keys:
        # Shortcut case. We know there is nothing uninteresting to filter out
        # So we just let the rest of the algorithm do the work
        # We know there is nothing uninteresting, and we didn't have to read
        # any interesting records yet.
        return (set(), set(), set(interesting_root_keys), [], set())
    all_uninteresting_chks = set(uninteresting_root_keys)
    all_uninteresting_items = set()

    # First step, find the direct children of both the interesting and
    # uninteresting set
    (uninteresting_keys, uninteresting_items,
     interesting_keys, interesting_records,
     interesting_items) = _find_children_info(store, interesting_root_keys,
                                              uninteresting_root_keys,
                                              adapter=adapter, pb=pb)
    all_uninteresting_chks.update(uninteresting_keys)
    all_uninteresting_items.update(uninteresting_items)
    del uninteresting_items
    # Note: Exact matches between interesting and uninteresting do not need
    #       to be search further. Non-exact matches need to be searched in case
    #       there is a future exact-match
    uninteresting_keys.difference_update(interesting_keys)

    # Second, find the full set of uninteresting bits reachable by the
    # uninteresting roots
    chks_to_read = uninteresting_keys
    while chks_to_read:
        next_chks = set()
        for record in store.get_record_stream(chks_to_read, 'unordered', False):
            # TODO: Handle 'absent'
            if pb is not None:
                pb.tick()
            if record.storage_kind != 'fulltext':
                bytes = adapter.get_bytes(record,
                            record.get_bytes_as(record.storage_kind))
            else:
                bytes = record.get_bytes_as('fulltext')
            node = _deserialise(bytes, record.key)
            if isinstance(node, InternalNode):
                # uninteresting_prefix_chks.update(node._items.iteritems())
                chks = node._items.values()
                # TODO: We remove the entries that are already in
                #       uninteresting_chks ?
                next_chks.update(chks)
                all_uninteresting_chks.update(chks)
            else:
                all_uninteresting_items.update(node._items.iteritems())
        chks_to_read = next_chks
    return (all_uninteresting_chks, all_uninteresting_items,
            interesting_keys, interesting_records, interesting_items)


def iter_interesting_nodes(store, interesting_root_keys,
                           uninteresting_root_keys, pb=None):
    """Given root keys, find interesting nodes.

    Evaluate nodes referenced by interesting_root_keys. Ones that are also
    referenced from uninteresting_root_keys are not considered interesting.

    :param interesting_root_keys: keys which should be part of the
        "interesting" nodes (which will be yielded)
    :param uninteresting_root_keys: keys which should be filtered out of the
        result set.
    :return: Yield
        (interesting records, interesting chk's, interesting key:values)
    """
    # TODO: consider that it may be more memory efficient to use the 20-byte
    #       sha1 string, rather than tuples of hexidecimal sha1 strings.

    # A way to adapt from the compressed texts back into fulltexts
    # In a way, this seems like a layering inversion to have CHKMap know the
    # details of versionedfile
    adapter_class = versionedfile.adapter_registry.get(
        ('knit-ft-gz', 'fulltext'))
    adapter = adapter_class(store)

    (all_uninteresting_chks, all_uninteresting_items, interesting_keys,
     interesting_records, interesting_items) = _find_all_uninteresting(store,
        interesting_root_keys, uninteresting_root_keys, adapter, pb)

    # Now that we know everything uninteresting, we can yield information from
    # our first request
    interesting_items.difference_update(all_uninteresting_items)
    records = dict((record.key, record) for record in interesting_records
                    if record.key not in all_uninteresting_chks)
    if records or interesting_items:
        yield records, interesting_items
    interesting_keys.difference_update(all_uninteresting_chks)

    chks_to_read = interesting_keys
    while chks_to_read:
        next_chks = set()
        for record in store.get_record_stream(chks_to_read, 'unordered', False):
            if pb is not None:
                pb.tick()
            # TODO: Handle 'absent'?
            if record.storage_kind != 'fulltext':
                bytes = adapter.get_bytes(record,
                            record.get_bytes_as(record.storage_kind))
            else:
                bytes = record.get_bytes_as('fulltext')
            node = _deserialise(bytes, record.key)
            if isinstance(node, InternalNode):
                chks = set(node.refs())
                chks.difference_update(all_uninteresting_chks)
                # Is set() and .difference_update better than:
                # chks = [chk for chk in node.refs()
                #              if chk not in all_uninteresting_chks]
                next_chks.update(chks)
                # These are now uninteresting everywhere else
                all_uninteresting_chks.update(chks)
                interesting_items = []
            else:
                interesting_items = [item for item in node._items.iteritems()
                                     if item not in all_uninteresting_items]
                # TODO: Do we need to filter out items that we have already
                #       seen on other pages? We don't really want to buffer the
                #       whole thing, but it does mean that callers need to
                #       understand they may get duplicate values.
                # all_uninteresting_items.update(interesting_items)
            yield {record.key: record}, interesting_items
        chks_to_read = next_chks
