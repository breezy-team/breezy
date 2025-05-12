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
#
# cython: language_level=3

cdef extern from "python-compat.h":
    pass

from cpython.bytes cimport (PyBytes_AS_STRING, PyBytes_CheckExact,
                            PyBytes_FromStringAndSize, PyBytes_GET_SIZE)
from cpython.dict cimport PyDict_SetItem
from cpython.long cimport PyLong_AsUnsignedLongMask
from cpython.object cimport PyObject
from cpython.ref cimport Py_INCREF
from cpython.tuple cimport PyTuple_CheckExact, PyTuple_GET_SIZE, PyTuple_New, PyTuple_SET_ITEM
from libc.stdio cimport sprintf
from libc.stdlib cimport strtol
from libc.string cimport memchr, memcmp, memcpy

# cimport all of the definitions we will need to access
from ._str_helpers cimport _my_memrchr, safe_interned_string_from_size

cdef object crc32
from zlib import crc32


cdef object _LeafNode
_LeafNode = None
cdef object _InternalNode
_InternalNode = None
cdef object _unknown
_unknown = None


def _search_key_16(key):
    """See chk_map._search_key_16."""
    cdef Py_ssize_t num_bits
    cdef Py_ssize_t i, j
    cdef Py_ssize_t num_out_bytes
    cdef unsigned long crc_val
    cdef Py_ssize_t out_off
    cdef char *c_out

    num_bits = len(key)
    # 4 bytes per crc32, and another 1 byte between bits
    num_out_bytes = (9 * num_bits) - 1
    out = PyBytes_FromStringAndSize(NULL, num_out_bytes)
    c_out = PyBytes_AS_STRING(out)
    for i from 0 <= i < num_bits:
        if i > 0:
            c_out[0] = c'\x00'
            c_out = c_out + 1
        crc_val = PyLong_AsUnsignedLongMask(crc32(key[i])) & 0xFFFFFFFFUL
        # Hex(val) order
        sprintf(c_out, '%08lX', crc_val)
        c_out = c_out + 8
    return out


def _search_key_255(key):
    """See chk_map._search_key_255."""
    cdef Py_ssize_t num_bits
    cdef Py_ssize_t i, j
    cdef Py_ssize_t num_out_bytes
    cdef unsigned long crc_val
    cdef Py_ssize_t out_off
    cdef char *c_out

    num_bits = len(key)
    # 4 bytes per crc32, and another 1 byte between bits
    num_out_bytes = (5 * num_bits) - 1
    out = PyBytes_FromStringAndSize(NULL, num_out_bytes)
    c_out = PyBytes_AS_STRING(out)
    for i from 0 <= i < num_bits:
        if i > 0:
            c_out[0] = c'\x00'
            c_out = c_out + 1
        crc_val = PyLong_AsUnsignedLongMask(crc32(key[i]))
        # MSB order
        c_out[0] = (crc_val >> 24) & 0xFF
        c_out[1] = (crc_val >> 16) & 0xFF
        c_out[2] = (crc_val >> 8) & 0xFF
        c_out[3] = (crc_val >> 0) & 0xFF
        for j from 0 <= j < 4:
            if c_out[j] == c'\n':
                c_out[j] = c'_'
        c_out = c_out + 4
    return out


cdef int _get_int_from_line(char **cur, char *end, char *message) except -1:
    """Read a positive integer from the data stream.

    :param cur: The start of the data, this will be moved to after the
        trailing newline when done.
    :param end: Do not parse any data past this byte.
    :return: The integer stored in those bytes
    """
    cdef int value
    cdef char *next_line
    cdef char *next_int

    next_line = <char *>memchr(cur[0], c'\n', end - cur[0])
    if next_line == NULL:
        raise ValueError("Missing %s line\n" % message)

    value = strtol(cur[0], &next_int, 10)
    if next_int != next_line:
        raise ValueError("%s line not a proper int\n" % message)
    cur[0] = next_line + 1
    return value


cdef _import_globals():
    """Set the global attributes. Done lazy to avoid recursive import loops."""
    global _LeafNode, _InternalNode, _unknown

    from . import chk_map
    _LeafNode = chk_map.LeafNode
    _InternalNode = chk_map.InternalNode
    _unknown = chk_map._unknown


def _deserialise_leaf_node(data, key, search_key_func=None):
    """Deserialise bytes, with key key, into a LeafNode.

    :param bytes: The bytes of the node.
    :param key: The key that the serialised node has.
    """
    cdef char *c_bytes
    cdef char *cur
    cdef char *next
    cdef char *end
    cdef char *next_line
    cdef Py_ssize_t c_bytes_len, prefix_length, items_length
    cdef int maximum_size, width, length, i, prefix_tail_len
    cdef int num_value_lines, num_prefix_bits
    cdef char *prefix
    cdef char *value_start
    cdef char *prefix_tail
    cdef char *next_null
    cdef char *last_null
    cdef char *line_start
    cdef char *c_entry
    cdef char *entry_start
    cdef tuple entry_bits

    if _LeafNode is None:
        _import_globals()

    result = _LeafNode(search_key_func=search_key_func)
    # Splitlines can split on '\r' so don't use it, split('\n') adds an
    # extra '' if the bytes ends in a final newline.
    if not PyBytes_CheckExact(data):
        raise TypeError('expected bytes not %s' % (type(data),))

    c_bytes = PyBytes_AS_STRING(data)
    c_bytes_len = PyBytes_GET_SIZE(data)

    if c_bytes_len < 9 or memcmp(c_bytes, b"chkleaf:\n", 9) != 0:
        raise ValueError("not a serialised leaf node: %r" % data)
    if c_bytes[c_bytes_len - 1] != c'\n':
        raise ValueError("bytes does not end in a newline")

    end = c_bytes + c_bytes_len
    cur = c_bytes + 9
    maximum_size = _get_int_from_line(&cur, end, "maximum_size")
    width = _get_int_from_line(&cur, end, "width")
    length = _get_int_from_line(&cur, end, "length")

    next_line = <char *>memchr(cur, c'\n', end - cur)
    if next_line == NULL:
        raise ValueError('Missing the prefix line\n')
    prefix = cur
    prefix_length = next_line - cur
    cur = next_line + 1

    prefix_bits = []
    prefix_tail = prefix
    num_prefix_bits = 0
    next_null = <char *>memchr(prefix, c'\0', prefix_length)
    while next_null != NULL:
        num_prefix_bits = num_prefix_bits + 1
        prefix_bits.append(
            PyBytes_FromStringAndSize(prefix_tail, next_null - prefix_tail))
        prefix_tail = next_null + 1
        next_null = <char *>memchr(prefix_tail, c'\0', next_line - prefix_tail)
    prefix_tail_len = next_line - prefix_tail

    if num_prefix_bits >= width:
        raise ValueError('Prefix has too many nulls versus width')

    items_length = end - cur
    items = {}
    while cur < end:
        line_start = cur
        next_line = <char *>memchr(cur, c'\n', end - cur)
        if next_line == NULL:
            raise ValueError('null line\n')
        last_null = <char *>_my_memrchr(cur, c'\0', next_line - cur)
        if last_null == NULL:
            raise ValueError('fail to find the num value lines null')
        next_null = last_null + 1 # move past NULL
        num_value_lines = _get_int_from_line(&next_null, next_line + 1,
                                             "num value lines")
        cur = next_line + 1
        value_start = cur
        # Walk num_value_lines forward
        for i from 0 <= i < num_value_lines:
            next_line = <char *>memchr(cur, c'\n', end - cur)
            if next_line == NULL:
                raise ValueError('missing trailing newline')
            cur = next_line + 1
        entry_bits = PyTuple_New(width)
        for i from 0 <= i < num_prefix_bits:
            # TODO: Use PyList_GetItem, or turn prefix_bits into a
            #       tuple
            entry = prefix_bits[i]
            # SET_ITEM 'steals' a reference
            Py_INCREF(entry)
            PyTuple_SET_ITEM(entry_bits, i, entry)
        value = PyBytes_FromStringAndSize(value_start, next_line - value_start)
        # The next entry bit needs the 'tail' from the prefix, and first part
        # of the line
        entry_start = line_start
        next_null = <char *>memchr(entry_start, c'\0',
                                   last_null - entry_start + 1)
        if next_null == NULL:
            raise ValueError('bad no null, bad')
        entry = PyBytes_FromStringAndSize(
            NULL, prefix_tail_len + next_null - line_start)
        c_entry = PyBytes_AS_STRING(entry)
        if prefix_tail_len > 0:
            memcpy(c_entry, prefix_tail, prefix_tail_len)
        if next_null - line_start > 0:
            memcpy(c_entry + prefix_tail_len, line_start, next_null - line_start)
        Py_INCREF(entry)
        i = num_prefix_bits
        PyTuple_SET_ITEM(entry_bits, i, entry)
        while next_null != last_null: # We have remaining bits
            i = i + 1
            if i > width:
                raise ValueError("Too many bits for entry")
            entry_start = next_null + 1
            next_null = <char *>memchr(entry_start, c'\0',
                                       last_null - entry_start + 1)
            if next_null == NULL:
                raise ValueError('bad no null')
            entry = PyBytes_FromStringAndSize(
                entry_start, next_null - entry_start)
            Py_INCREF(entry)
            PyTuple_SET_ITEM(entry_bits, i, entry)
        if PyTuple_GET_SIZE(entry_bits) != width:
            raise AssertionError(
                'Incorrect number of elements (%d vs %d)'
                % (len(entry_bits)+1, width + 1))
        PyDict_SetItem(items, entry_bits, value)
    if len(items) != length:
        raise ValueError("item count (%d) mismatch for key %s,"
                         " bytes %r" % (length, entry_bits, bytes))
    result._items = items
    result._len = length
    result._maximum_size = maximum_size
    result._key = key
    result._key_width = width
    result._raw_size = items_length + length * prefix_length
    if length == 0:
        result._search_prefix = None
        result._common_serialised_prefix = None
    else:
        result._search_prefix = _unknown
        result._common_serialised_prefix = PyBytes_FromStringAndSize(
            prefix, prefix_length)
    if c_bytes_len != result._current_size():
        raise AssertionError('_current_size computed incorrectly %d != %d',
            c_bytes_len, result._current_size())
    return result


def _deserialise_internal_node(data, key, search_key_func=None):
    cdef char *c_bytes
    cdef char *cur
    cdef char *end
    cdef char *next_line
    cdef Py_ssize_t c_bytes_len, prefix_length
    cdef int maximum_size, width, length, i, prefix_tail_len
    cdef char *prefix
    cdef char *line_prefix
    cdef char *next_null
    cdef char *c_item_prefix

    if _InternalNode is None:
        _import_globals()
    result = _InternalNode(search_key_func=search_key_func)

    if not PyTuple_CheckExact(key):
        raise TypeError('key %r is not a tuple' % (key,))
    if not PyBytes_CheckExact(data):
        raise TypeError('expected bytes not %s' % (type(data),))

    c_bytes = PyBytes_AS_STRING(data)
    c_bytes_len = PyBytes_GET_SIZE(data)

    if c_bytes_len < 9 or memcmp(c_bytes, b"chknode:\n", 9) != 0:
        raise ValueError("not a serialised internal node: %r" % data)
    if c_bytes[c_bytes_len - 1] != c'\n':
        raise ValueError("bytes does not end in a newline")

    items = {}
    cur = c_bytes + 9
    end = c_bytes + c_bytes_len
    maximum_size = _get_int_from_line(&cur, end, "maximum_size")
    width = _get_int_from_line(&cur, end, "width")
    length = _get_int_from_line(&cur, end, "length")

    next_line = <char *>memchr(cur, c'\n', end - cur)
    if next_line == NULL:
        raise ValueError('Missing the prefix line\n')
    prefix = cur
    prefix_length = next_line - cur
    cur = next_line + 1

    while cur < end:
        # Find the null separator
        next_line = <char *>memchr(cur, c'\n', end - cur)
        if next_line == NULL:
            raise ValueError('missing trailing newline')
        next_null = <char *>_my_memrchr(cur, c'\0', next_line - cur)
        if next_null == NULL:
            raise ValueError('bad no null')
        item_prefix = PyBytes_FromStringAndSize(
            NULL, prefix_length + next_null - cur)
        c_item_prefix = PyBytes_AS_STRING(item_prefix)
        if prefix_length:
            memcpy(c_item_prefix, prefix, prefix_length)
        memcpy(c_item_prefix + prefix_length, cur, next_null - cur)
        flat_key = PyBytes_FromStringAndSize(
            next_null + 1, next_line - next_null - 1)
        flat_key = (flat_key, )
        PyDict_SetItem(items, item_prefix, flat_key)
        cur = next_line + 1
    assert len(items) > 0
    result._items = items
    result._len = length
    result._maximum_size = maximum_size
    result._key = key
    result._key_width = width
    # XXX: InternalNodes don't really care about their size, and this will
    #      change if we add prefix compression
    result._raw_size = None
    result._node_width = len(item_prefix)
    result._search_prefix = PyBytes_FromStringAndSize(prefix, prefix_length)
    return result


def _bytes_to_text_key(data):
    """Take a CHKInventory value string and return a (file_id, rev_id) tuple"""
    cdef tuple key
    cdef char *byte_str
    cdef char *cur_end
    cdef char *file_id_str
    cdef char *byte_end
    cdef char *revision_str
    cdef Py_ssize_t byte_size, pos, file_id_len

    if not PyBytes_CheckExact(data):
        raise TypeError('expected bytes not %s' % (type(data),))
    byte_str = PyBytes_AS_STRING(data)
    byte_size = PyBytes_GET_SIZE(data)
    byte_end = byte_str + byte_size
    cur_end = <char*>memchr(byte_str, c':', byte_size)
    if cur_end == NULL:
        raise ValueError('No kind section found.')
    if cur_end[1] != c' ':
        raise ValueError(
            'Kind section should end with ": ", got %r' % str(cur_end[:2],))
    file_id_str = cur_end + 2
    # file_id is now the data up until the next newline
    cur_end = <char*>memchr(file_id_str, c'\n', byte_end - file_id_str)
    if cur_end == NULL:
        raise ValueError('no newline after file-id')
    file_id = safe_interned_string_from_size(file_id_str,
                                             cur_end - file_id_str)
    # this is the end of the parent_str
    cur_end = <char*>memchr(cur_end + 1, c'\n', byte_end - cur_end - 1)
    if cur_end == NULL:
        raise ValueError('no newline after parent_str')
    # end of the name str
    cur_end = <char*>memchr(cur_end + 1, c'\n', byte_end - cur_end - 1)
    if cur_end == NULL:
        raise ValueError('no newline after name str')
    # the next section is the revision info
    revision_str = cur_end + 1
    cur_end = <char*>memchr(cur_end + 1, c'\n', byte_end - cur_end - 1)
    if cur_end == NULL:
        # This is probably a dir: entry, which has revision as the last item
        cur_end = byte_end
    revision = safe_interned_string_from_size(revision_str,
        cur_end - revision_str)
    key = PyTuple_New(2)
    Py_INCREF(file_id)
    PyTuple_SET_ITEM(key, 0, file_id)
    Py_INCREF(revision)
    PyTuple_SET_ITEM(key, 1, revision)
    return key
