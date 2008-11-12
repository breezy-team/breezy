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

import osutils


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
            self._root_node = root_key

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
            bytes = self._read_bytes(self._root_node)
            root_key = self._root_node
            self._root_node = _deserialise(bytes, root_key)

    def _read_bytes(self, key):
        stream = self._store.get_record_stream([key], 'unordered', True)
        return stream.next().get_bytes_as('fulltext')

    @classmethod
    def from_dict(klass, store, initial_value, maximum_size=0):
        """Create a CHKMap in store with initial_value as the content.
        
        :param store: The store to record initial_value in, a VersionedFiles
            object with 1-tuple keys supporting CHK key generation.
        :param initial_value: A dict to store in store. Its keys and values
            must be bytestrings.
        :param maximum_size: The maximum_size rule to apply to nodes. This
            determines the size at which no new data is added to a single node.
        :return: The root chk of te resulting CHKMap.
        """
        result = CHKMap(store, None)
        result._root_node.set_maximum_size(maximum_size)
        delta = []
        for key, value in initial_value.items():
            delta.append((None, key, value))
        result.apply_delta(delta)
        return result._save()

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
            self._root_node = InternalNode()
            self._root_node.set_maximum_size(node_details[0][1].maximum_size)
            self._root_node._key_width = node_details[0][1]._key_width
            for split, node in node_details:
                self._root_node.add_node(split, node)

    def _map(self, key, value):
        """Map key to value."""
        # Ne
        self._ensure_root()
        # Store the value
        bytes = ValueNode(value).serialise()
        # Experimental code to probe for keys rather than just adding; its not
        # clear if it is an improvement.
        #chk = ("sha1:%s" % osutils.sha_string(bytes),)
        #if not self._store.get_parent_map([key]):
        sha1, _, _ = self._store.add_lines((None,), (), osutils.split_lines(bytes))
        chk = ("sha1:" + sha1,)
        # And link into the root
        self._root_node.add_child(key, chk)

    def unmap(self, key):
        """remove key from the map."""
        self._ensure_root()
        self._root_node.unmap(self._store, key)

    def _unmap(self, key):
        """remove key from the map."""
        self._ensure_root()
        self._root_node.remove_child(key)

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


class LeafNode(Node):
    """A node containing actual key:value pairs.
    
    :ivar _items: A dict of key->value items. The key is in tuple form.
    """

    def __init__(self):
        Node.__init__(self)
        # The size of a leaf node with default values and no children.
        self._size = 12

    def _current_size(self):
        """Answer the current serialised size of this node."""
        return (self._size + len(str(self._len)) + len(str(self._key_width)) +
            len(str(self._maximum_size)))

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
            elements = line.split('\x00')
            items[tuple(elements[:-1])] = elements[-1]
        if len(items) != length:
            raise AssertionError("item count mismatch")
        result._items = items
        result._len = length
        result._maximum_size = maximum_size
        result._key = key
        result._key_width = width
        result._size = len(bytes)
        return result

    def iteritems(self, store, key_filter=None):
        if key_filter is not None:
            for item in self._items.iteritems():
                if item[0] in key_filter:
                    yield item
        else:
            for item in self._items.iteritems():
                yield item

    def key(self):
        return self._key

    def _key_count(self, parent_width, cut_width):
        """Return the number of keys in/under this node between two widths.

        :param parent_width: The start offset in keys to consider.
        :param cut_width: The width to stop considering at.
        """
        # This assumes the keys are unique up to parent_width.
        serialised_keys = set()
        for key in self._items:
            serialised_key = '\x00'.join(key)
            serialised_keys.add(serialised_key[parent_width:cut_width])
        return len(serialised_keys)

    def map(self, store, key, value):
        """Map key to value."""
        if key in self._items:
            self._size -= 2 + len('\x00'.join(key)) + len(self._items[key])
            self._len -= 1
        self._items[key] = value
        self._size += 2 + len('\x00'.join(key)) + len(value)
        self._len += 1
        self._key = None
        if (self._maximum_size and self._current_size() > self._maximum_size and
            self._len > 1):
            common_prefix = self.unique_serialised_prefix()
            split_at = len(common_prefix) + 1
            result = {}
            for key, value in self._items.iteritems():
                serialised_key = self._serialised_key(key)
                prefix = serialised_key[:split_at]
                if prefix not in result:
                    node = LeafNode()
                    node.set_maximum_size(self._maximum_size)
                    node._key_width = self._key_width
                    result[prefix] = node
                else:
                    node = result[prefix]
                node.map(store, key, value)
            return common_prefix, result.items()
        else:
            return self.unique_serialised_prefix(), [("", self)]

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
            lines.append("%s\x00%s\n" % ('\x00'.join(key), value))
        sha1, _, _ = store.add_lines((None,), (), lines)
        self._key = ("sha1:" + sha1,)
        return [self._key]

    def _serialised_key(self, key):
        """Return the serialised key for key in this node."""
        return '\x00'.join(key)

    def unique_serialised_prefix(self):
        """Return the unique key prefix for this node.

        :return: A bytestring of the longest serialised key prefix that is
            unique within this node.
        """
        # may want to cache this eventually :- but wait for enough
        # functionality to profile.
        keys = list(self._items.keys())
        if not keys:
            return ""
        current_prefix = self._serialised_key(keys.pop(-1))
        while current_prefix and keys:
            next_key = self._serialised_key(keys.pop(-1))
            for pos, (left, right) in enumerate(zip(current_prefix, next_key)):
                if left != right:
                    pos -= 1
                    break
            current_prefix = current_prefix[:pos + 1]
        return current_prefix

    def unmap(self, store, key):
        """Unmap key from the node."""
        self._size -= 2 + len('\x00'.join(key)) + len(self._items[key])
        self._len -= 1
        del self._items[key]
        self._key = None
        return self


class InternalNode(Node):
    """A node that contains references to other nodes.
    
    An InternalNode is responsible for mapping serialised key prefixes to child
    nodes. It is greedy - it will defer splitting itself as long as possible.
    """

    def __init__(self):
        Node.__init__(self)
        # The size of an internalnode with default values and no children.
        # self._size = 12
        # How many octets key prefixes within this node are.
        self._node_width = 0

    def add_node(self, prefix, node):
        """Add a child node with prefix prefix, and node node.

        :param prefix: The serialised key prefix for node.
        :param node: The node being added.
        """
        self._len += len(node)
        if not len(self._items):
            self._node_width = len(prefix)
        self._items[prefix] = node
        self._key = None

    def _add_node(self, node):
        """Add a node to the InternalNode.

        :param node: An existing node to add. The node will be examined to see
            if it is over or undersized and rebalanced if needed across this
            nodes children.
        """
        if self._len == 0:
            # new tree level, we're being populated by upspill from a overfull
            # tree.
            # Cheap-to-code-but-slow?
            elements = {}
            max_width = 0
            # suck in all the values
            for key, value in node.iteritems():
                # We work on the serialised keys
                serialised_key = '\x00'.join(key)
                elements[serialised_key] = (key, value)
                max_width = max(len(serialised_key), max_width)
            # Determine the maximum common key width we will internally handle.
            # Start with the full key width; if that exceeds our node size
            # shrink it until we are within the node limit.
            self._node_width = max_width
            width = self._node_width
            # Populate all the resulting keys:
            items = self._items
            for serialised_key, key_value in elements.iteritems():
                actual_key = self._serialised_key(key_value[0])
                child = items.get(actual_key, None)
                if not child:
                    child = LeafNode()
                    child.set_maximum_size(self._maximum_size)
                    child._key_width = self._key_width
                    items[actual_key] = child
                child.map(store, key_value[0], key_value[1])
                self._len += 1
        else:
            raise NotImplementedError(self._add_node)

    def _current_size(self):
        """Answer the current serialised size of this node."""
        return (self._size + len(str(self._len)) + len(str(self._key_width)) +
            len(str(self._maximum_size)))

    @classmethod
    def deserialise(klass, bytes, key):
        """Deseriaise bytes to an InternalNode, with key key.

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
        keys = set()
        if key_filter is None:
            for node in self._items.itervalues():
                if type(node) == tuple:
                    keys.add(node)
                else:
                    nodes.append(node)
        else:
            serialised_filter = set([self._serialised_key(key) for key in
                key_filter])
            for prefix, node in self._items.iteritems():
                if prefix in serialised_filter:
                    if type(node) == tuple:
                        keys.add(node)
                    else:
                        nodes.append(node)
        if keys:
            # demand load some pages.
            stream = store.get_record_stream(keys, 'unordered', True)
            for record in stream:
                node = _deserialise(record.get_bytes_as('fulltext'), record.key)
                nodes.append(node)
        return nodes

    def map(self, store, key, value):
        """Map key to value."""
        if not len(self._items):
            raise AssertionError("cant map in an empty InternalNode.")
        children = self._iter_nodes(store, key_filter=[key])
        serialised_key = self._serialised_key(key)
        if children:
            child = children[0]
        else:
            # new child needed:
            child = self._new_child(serialised_key, LeafNode)
        old_len = len(child)
        prefix, node_details = child.map(store, key, value)
        if len(node_details) == 1:
            # child may have shrunk, or might be the same.
            self._len = self._len - old_len + len(child)
            self._items[serialised_key] = child
            return self.unique_serialised_prefix(), [("", self)]
        # child has overflown - create a new intermediate node.
        # XXX: This is where we might want to try and expand our depth
        # to refer to more bytes of every child (which would give us
        # multiple pointers to child nodes, but less intermediate nodes)
        child = self._new_child(serialised_key, InternalNode)
        for split, node in node_details:
            child.add_node(split, node)
        self._len = self._len - old_len + len(child)
        return self.unique_serialised_prefix(), [("", self)]

    def _new_child(self, serialised_key, klass):
        """Create a new child node of type klass."""
        child = klass()
        child.set_maximum_size(self._maximum_size)
        child._key_width = self._key_width
        self._items[serialised_key] = child
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
        yield self._key

    def _serialised_key(self, key):
        """Return the serialised key for key in this node."""
        return ('\x00'.join(key) + '\x00'*self._node_width)[:self._node_width]

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

    def _key_count(self, parent_width, cut_width):
        """Return the number of keys in/under this node between two widths.

        :param parent_width: The start offset in keys to consider.
        :param cut_width: The width to stop considering at.
        """
        if cut_width > self._node_width:
            raise NotImplementedError(self._key_count)
        # This assumes the keys are unique up to parent_width.
        serialised_keys = set()
        for serialised_key in self._items:
            serialised_keys.add(serialised_key[parent_width:cut_width])
        return len(serialised_keys)

    def _prelude_size(self):
        """Return the size of the node prelude."""
        return 15

    def unique_serialised_prefix(self):
        """Return the unique key prefix for this node.

        :return: A bytestring of the longest serialised key prefix that is
            unique within this node.
        """
        # may want to cache this eventually :- but wait for enough
        # functionality to profile.
        keys = list(self._items.keys())
        if not keys:
            return ""
        current_prefix = keys.pop(-1)
        while current_prefix and keys:
            next_key = keys.pop(-1)
            for pos, (left, right) in enumerate(zip(current_prefix, next_key)):
                if left != right:
                    pos -= 1
                    break
            current_prefix = current_prefix[:pos + 1]
        return current_prefix

    def unmap(self, store, key):
        """Remove key from this node and it's children."""
        if not len(self._items):
            raise AssertionError("cant unmap in an empty InternalNode.")
        serialised_key = self._serialised_key(key)
        children = self._iter_nodes(store, key_filter=[key])
        serialised_key = self._serialised_key(key)
        if children:
            child = children[0]
        else:
            raise KeyError(key)
        self._len -= 1
        unmapped = child.unmap(store, key)
        if len(unmapped) == 0:
            # All child nodes are gone, remove the child:
            del self._items[serialised_key]
        else:
            # Stash the returned node
            self._items[serialised_key] = unmapped
        if len(self._items) == 1:
            # this node is no longer needed:
            return self._items.values()[0]
        return self


class RootNode(Node):
    """A root node in a CHKMap."""

    def __init__(self):
        Node.__init__(self)
        self._nodes = {}
        self._size = 12
        self.prefix_width = 0

    def add_child(self, name, child):
        """Add a child to the node.

        If the node changes, it's key is reset.

        :param name: The name of the child. A bytestring.
        :param child: The child, a key tuple for the childs value.
        """
        if self._maximum_size and self._current_size() >= self._maximum_size:
            return False
        if name in self._nodes:
            self.remove_child(name)
        self._nodes[name] = child
        self._len += 1
        self._key = None
        self._size += len(name) + len(child[0]) + 2
        return True

    def _current_size(self):
        """Answer the current serialised size of this node."""
        return (self._size + len(str(self._maximum_size)) + len(str(self._len))
            + len(str(self.prefix_width)))

    def deserialise(self, bytes, key):
        """Set the nodes value to that contained in bytes.
        
        :param bytes: The bytes of the node.
        :param key: The key that the serialised node has.
        """
        lines = bytes.splitlines()
        nodes = {}
        if lines[0] != 'chkroot:':
            raise ValueError("not a serialised root node: %r" % bytes)
        maximum_size = int(lines[1])
        prefix_width = int(lines[2])
        length = int(lines[3])
        for line in lines[4:]:
            name, value = line.split('\x00')
            nodes[name] = (value,)
        self._nodes = nodes
        self._len = length
        self._maximum_size = maximum_size
        self._key = key
        self.prefix_width = prefix_width

    def refs(self):
        """Get the CHK key references this node holds."""
        return self._nodes.values()

    def remove_child(self, name):
        """Remove name from the node.

        If the node changes, it's key is reset.

        :param name: The name to remove from the node.
        """
        node = self._nodes.pop(name)
        self._size -= 2 + len(name) + len(node[0])
        self._len -= 1
        self._key = None

    def serialise(self):
        """Flatten the node to a bytestring.

        :return: A bytestring.
        """
        lines = ["chkroot:\n"]
        lines.append("%d\n" % self._maximum_size)
        lines.append("%d\n" % self.prefix_width)
        lines.append("%d\n" % self._len)
        for name, child in sorted(self._nodes.items()):
            lines.append("%s\x00%s\n" % (name, child[0]))
        return "".join(lines)


class ValueNode(object):
    """A value in a CHKMap."""

    def __init__(self, value):
        """Create a ValueNode.

        :param value: The value of this node, must be a bytestring.
        """
        self.value = value

    @classmethod
    def deserialise(klass, bytes):
        """Get a ValueNode from a serialised bytestring.
        
        :param bytes: The bytes returned by an earlier serialisation.
        """
        if not bytes.startswith("chkvalue:\n"):
            raise ValueError("not a chkvalue %r" % bytes)
        return ValueNode(bytes[10:])

    def serialise(self):
        """Flatten the value to a bytestring.

        :return: A bytestring.
        """
        return "chkvalue:\n" + self.value

    def refs(self):
        """ValueNodes have no refs within the dict."""
        return []


def _deserialise(bytes, key):
    """Helper for repositorydetails - convert bytes to a node."""
    if bytes.startswith("chkvalue:\n"):
        return ValueNode.deserialise(bytes)
    elif bytes.startswith("chkroot:\n"):
        result = RootNode()
        result.deserialise(bytes, key)
        return result
    elif bytes.startswith("chkleaf:\n"):
        return LeafNode.deserialise(bytes, key)
    elif bytes.startswith("chknode:\n"):
        return InternalNode.deserialise(bytes, key)
    else:
        raise AssertionError("Unknown node type.")
