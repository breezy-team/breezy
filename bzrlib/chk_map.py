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
    def from_dict(klass, store, initial_value):
        """Create a CHKMap in store with initial_value as the content.
        
        :param store: The store to record initial_value in, a VersionedFiles
            object with 1-tuple keys supporting CHK key generation.
        :param initial_value: A dict to store in store. Its keys and values
            must be bytestrings.
        :return: The root chk of te resulting CHKMap.
        """
        result = CHKMap(store, None)
        for key, value in initial_value.items():
            result._map(key, value)
        return result._save()

    def iteritems(self):
        """Iterate over the entire CHKMap's contents."""
        self._ensure_root()
        for name, key, in self._root_node._nodes.iteritems():
            bytes = self._read_bytes(key)
            yield name, ValueNode.deserialise(bytes).value

    def _map(self, key, value):
        """Map key to value."""
        self._ensure_root()
        # Store the value
        bytes = ValueNode(value).serialise()
        sha1, _, _ = self._store.add_lines((None,), (), osutils.split_lines(bytes))
        # And link into the root
        self._root_node.add_child(key, ("sha1:" + sha1,))

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


class RootNode(object):
    """A root node in a CHKMap."""

    def __init__(self):
        self._nodes = {}

    def add_child(self, name, child):
        """Add a child to the node.

        If the node changes, it's key is reset.

        :param name: The name of the child. A bytestring.
        :param child: The child, a key tuple for the childs value.
        """
        self._nodes[name] = child
        self._key = None

    def deserialise(self, bytes, key):
        """Set the nodes value to that contained in bytes.
        
        :param bytes: The bytes of the node.
        :param key: The key that the serialised node has.
        """
        lines = bytes.splitlines()
        nodes = {}
        if lines[0] != 'chkroot:':
            raise ValueError("not a serialised root node: %r" % bytes)
        for line in lines[1:]:
            name, value = line.split('\x00')
            nodes[name] = (value,)
        self._nodes = nodes
        self._key = key

    def remove_child(self, name):
        """Remove name from the node.

        If the node changes, it's key is reset.

        :param name: The name to remove from the node.
        """
        del self._nodes[name]
        self._key = None

    def serialise(self):
        """Flatten the node to a bytestring.

        :return: A bytestring.
        """
        lines = ["chkroot:\n"]
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
