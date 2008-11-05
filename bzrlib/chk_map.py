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

"""Persistent maps from string->string using CHK stores."""

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
            self._root_node = RootNode()
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
                self._unmap(old)
        for old, new, value in delta:
            if new is not None:
                # map
                self._map(new, value)
        return self._save()

    def _ensure_root(self):
        """Ensure that the root node is an object not a key."""
        if type(self._root_node) == tuple:
            # Demand-load the root
            bytes = self._read_bytes(self._root_node)
            root_key = self._root_node
            self._root_node = RootNode()
            self._root_node.deserialise(bytes, root_key)

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
        if key_filter is not None:
            for name, key, in self._root_node._nodes.iteritems():
                if name in key_filter:
                    bytes = self._read_bytes(key)
                    yield name, ValueNode.deserialise(bytes).value
        else:
            for name, key, in self._root_node._nodes.iteritems():
                bytes = self._read_bytes(key)
                yield name, ValueNode.deserialise(bytes).value

    def key(self):
        """Return the key for this map."""
        if isinstance(self._root_node, tuple):
            return self._root_node
        else:
            return self._root_node._key

    def __len__(self):
        self._ensure_root()
        return len(self._root_node)

    def _map(self, key, value):
        """Map key to value."""
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
        # TODO: flush root_nodes children?
        bytes = self._root_node.serialise()
        sha1, _, _ = self._store.add_lines((None,), (),
            osutils.split_lines(bytes))
        result = ("sha1:" + sha1,)
        self._root_node._key = result
        return result


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
    """A node containing actual key:value pairs."""

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

    def iteritems(self, key_filter=None):
        if key_filter is not None:
            for item in self._items.iteritems():
                if item[0] in key_filter:
                    yield item
        else:
            for item in self._items.iteritems():
                yield item

    def key(self):
        return self._key

    def map(self, key, value):
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
            result = InternalNode()
            result.set_maximum_size(self._maximum_size)
            result._key_width = self._key_width
            result._add_node(self)
            return result
        else:
            return self

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

    def unmap(self, key):
        """Unmap key from the node."""
        self._size -= 2 + len('\x00'.join(key)) + len(self._items[key])
        self._len -= 1
        del self._items[key]
        self._key = None
        return self


class InternalNode(Node):
    """A node that contains references to other nodes."""

    def __init__(self):
        Node.__init__(self)
        # The size of an internalnode with default values and no children.
        # self._size = 12
        # How many octets key prefixes within this node are.
        self._node_width = 0

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
                child.map(key_value[0], key_value[1])
                self._len += 1
        else:
            raise NotImplementedError(self._add_node)

    def _current_size(self):
        """Answer the current serialised size of this node."""
        return (self._size + len(str(self._len)) + len(str(self._key_width)) +
            len(str(self._maximum_size)))

    def iteritems(self, key_filter=None):
        if key_filter is None:
            for child in self._items.itervalues():
                for item in child.iteritems():
                    yield item
        else:
            serialised_filter = set([self._serialised_key(key) for key in
                key_filter])
            for key, child in self._items.iteritems():
                if key in serialised_filter:
                    for item in child.iteritems(key_filter):
                        yield item

    def map(self, key, value):
        """Map key to value."""
        serialised_key = self._serialised_key(key)
        try:
            child = self._items[serialised_key]
        except KeyError:
            child = LeafNode()
            child.set_maximum_size(self._maximum_size)
            child._key_width = self._key_width
            self._items[serialised_key] = child
        old_len = len(child)
        new_child = child.map(key, value)
        # TODO: rebalance/enforce balance
        if new_child is not child:
            # The child has exceeded its size; if we take more bytes off the
            # key prefix for the child, that may fit into our node;
            # How many more bytes can we fit?
            remaining_size = max(0, self.maximum_size - self._current_size())
            size_per_row = (self._node_width + 45 + 2)
            # without increasing the key width:
            extra_rows = remaining_size / size_per_row
            if extra_rows:
                # What is the minimum node width increase to split new_child:
                offset_bytes = [1]
                offset = self._node_width - 1
                while len(offset_bytes) == 1 and offset < new_child._node_width:
                    offset += 1
                    offset_bytes = set(child_key[offset] for child_key in
                        new_child._items.keys())
                if len(offset_bytes) > 1:
                    # We've found the fan out point
                    increase = self._node_width - offset
                    # calculate how many more pointers we need to carry
                    new_keys = len(offset_bytes)
                    for subnode in self._items.values():
                        new_keys += subnode._key_count(self._node_width, offset)
                    if (new_keys * (offset + 45 + 2) +
                        self._prelude_size() > self._maximum_size):
                        # can't fit it all, accept the new child
                        self._items[serialised_key] = new_child
                    else:
                        # increasing the 
                        pass
                else:
                    # it didn't fan out! wtf!
                    raise AssertionError("no fan out")
            else:
                # leave it split
                self._items[serialised_key] = new_child
        self._len += 1
        return self

    def _serialised_key(self, key):
        """Return the serialised key for key in this node."""
        return ('\x00'.join(key) + '\x00'*self._node_width)[:self._node_width]

    def _key_count(self, parent_width, cut_width):
        """Return the number of keys in/under this node between two widths.

        :param parent_width: The start offset in keys to consider.
        :param cut_width: The width to stop considering at.
        """
        if cut_width > self._node_width:
            raise NotImplementedError(self._key_count)
        # Generate a list of unique substrings


    def unmap(self, key):
        """Remove key from this node and it's children."""
        serialised_key = self._serialised_key(key)
        child = self._items[serialised_key]
        new_child = child.unmap(key)
        # TODO shrink/rebalance
        if not len(new_child):
            del self._items[serialised_key]
            if len(self._items) == 1:
                return self._items.values()[0]
        elif new_child is not child:
            self._items[serialised_key] = new_child
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
    else:
        raise AssertionError("Unknown node type.")
