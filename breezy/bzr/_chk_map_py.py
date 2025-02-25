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

"""Python implementation of _search_key functions, etc."""

from .static_tuple import StaticTuple

_LeafNode = None
_InternalNode = None
_unknown = None


def _deserialise_leaf_node(data, key, search_key_func=None):
    """Deserialise bytes, with key key, into a LeafNode.

    :param bytes: The bytes of the node.
    :param key: The key that the serialised node has.
    """
    global _unknown, _LeafNode, _InternalNode
    if _LeafNode is None:
        from . import chk_map

        _unknown = chk_map._unknown
        _LeafNode = chk_map.LeafNode
        _InternalNode = chk_map.InternalNode
    result = _LeafNode(search_key_func=search_key_func)
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
        items[StaticTuple.from_sequence(elements[:-1])] = value
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
    global _unknown, _LeafNode, _InternalNode
    if _InternalNode is None:
        from . import chk_map

        _unknown = chk_map._unknown
        _LeafNode = chk_map.LeafNode
        _InternalNode = chk_map.InternalNode
    result = _InternalNode(search_key_func=search_key_func)
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
        items[prefix] = StaticTuple(
            flat_key,
        )
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
