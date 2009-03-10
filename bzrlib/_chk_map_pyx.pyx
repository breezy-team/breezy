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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


cdef extern from *:
    ctypedef unsigned int size_t
    int memcmp(void *, void*, size_t)
    void *memchr(void *s, int c, size_t len)
    long strtol(char *, char **, int)
    void sprintf(char *, char *, ...)

cdef extern from "Python.h":
    struct _PyObject:
        pass
    ctypedef _PyObject PyObject
    int PyTuple_CheckExact(object p)
    Py_ssize_t PyTuple_GET_SIZE(object t)
    int PyString_CheckExact(object)
    char *PyString_AS_STRING(object s)
    Py_ssize_t PyString_GET_SIZE(object)

    PyObject * PyTuple_GET_ITEM_ptr "PyTuple_GET_ITEM" (object t,
                                                        Py_ssize_t offset)
    int PyString_CheckExact_ptr "PyString_CheckExact" (PyObject *p)
    Py_ssize_t PyString_GET_SIZE_ptr "PyString_GET_SIZE" (PyObject *s)
    char *PyString_AS_STRING_ptr "PyString_AS_STRING" (PyObject *s)
    object PyString_FromStringAndSize(char*, Py_ssize_t)

cdef extern from "zlib.h":
    ctypedef unsigned long uLong
    ctypedef unsigned int uInt
    ctypedef unsigned char Bytef

    uLong crc32(uLong crc, Bytef *buf, uInt len)


def _search_key_16(key):
    """See chk_map._search_key_16."""
    cdef Py_ssize_t num_bits
    cdef Py_ssize_t i, j
    cdef Py_ssize_t num_out_bytes
    cdef Bytef *c_bit
    cdef uLong c_len
    cdef uInt crc_val
    cdef Py_ssize_t out_off
    cdef char *c_out
    cdef PyObject *bit

    if not PyTuple_CheckExact(key):
        raise TypeError('key %r is not a tuple' % (key,))
    num_bits = PyTuple_GET_SIZE(key)
    # 4 bytes per crc32, and another 1 byte between bits
    num_out_bytes = (9 * num_bits) - 1
    out = PyString_FromStringAndSize(NULL, num_out_bytes)
    c_out = PyString_AS_STRING(out)
    for i from 0 <= i < num_bits:
        if i > 0:
            c_out[0] = c'\x00'
            c_out = c_out + 1
        # We use the _ptr variant, because GET_ITEM returns a borrowed
        # reference, and Pyrex assumes that returned 'object' are a new
        # reference
        bit = PyTuple_GET_ITEM_ptr(key, i)
        if not PyString_CheckExact_ptr(bit):
            raise TypeError('Bit %d of %r is not a string' % (i, key))
        c_bit = <Bytef *>PyString_AS_STRING_ptr(bit)
        c_len = PyString_GET_SIZE_ptr(bit)
        crc_val = crc32(0, c_bit, c_len)
        # Hex(val) order
        sprintf(c_out, '%08X', crc_val)
        c_out = c_out + 8
    return out


def _search_key_255(key):
    """See chk_map._search_key_255."""
    cdef Py_ssize_t num_bits
    cdef Py_ssize_t i, j
    cdef Py_ssize_t num_out_bytes
    cdef Bytef *c_bit
    cdef uLong c_len
    cdef uInt crc_val
    cdef Py_ssize_t out_off
    cdef char *c_out
    cdef PyObject *bit

    if not PyTuple_CheckExact(key):
        raise TypeError('key %r is not a tuple' % (key,))
    num_bits = PyTuple_GET_SIZE(key)
    # 4 bytes per crc32, and another 1 byte between bits
    num_out_bytes = (5 * num_bits) - 1
    out = PyString_FromStringAndSize(NULL, num_out_bytes)
    c_out = PyString_AS_STRING(out)
    for i from 0 <= i < num_bits:
        if i > 0:
            c_out[0] = c'\x00'
            c_out = c_out + 1
        bit = PyTuple_GET_ITEM_ptr(key, i)
        if not PyString_CheckExact_ptr(bit):
            raise TypeError('Bit %d of %r is not a string: %r' % (i, key,
            <object>bit))
        c_bit = <Bytef *>PyString_AS_STRING_ptr(bit)
        c_len = PyString_GET_SIZE_ptr(bit)
        crc_val = crc32(0, c_bit, c_len)
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
    cdef char *next_line, *next

    next_line = <char *>memchr(cur[0], c'\n', end - cur[0])
    if next_line == NULL:
        raise ValueError("Missing %s line\n" % message)

    value = strtol(cur[0], &next, 10)
    if next != next_line:
        raise ValueError("%s line not a proper int\n" % message)
    cur[0] = next_line + 1
    return value


def _deserialise_leaf_node(bytes, key, search_key_func=None):
    """Deserialise bytes, with key key, into a LeafNode.

    :param bytes: The bytes of the node.
    :param key: The key that the serialised node has.
    """
    cdef Py_ssize_t offset, next_offset
    cdef char *c_bytes, *cur, *next, *end
    cdef char *next_line
    cdef Py_ssize_t c_bytes_len, prefix_length
    cdef int maximum_size, width, length, i
    cdef char *prefix, *value_start

    from bzrlib.chk_map import LeafNode, _unknown

    result = LeafNode(search_key_func=search_key_func)
    # Splitlines can split on '\r' so don't use it, split('\n') adds an
    # extra '' if the bytes ends in a final newline.
    if not PyString_CheckExact(bytes):
        raise TypeError('bytes must be a plain string not %s' % (type(bytes),))

    c_bytes = PyString_AS_STRING(bytes)
    c_bytes_len = PyString_GET_SIZE(bytes)

    if c_bytes[c_bytes_len - 1] != c'\n':
        raise ValueError("bytes does not end in a newline")

    if c_bytes_len < 9 or memcmp(c_bytes, "chkleaf:\n", 9) != 0:
        raise ValueError("not a serialised leaf node: %r" % bytes)

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

    py_prefix = PyString_FromStringAndSize(prefix, prefix_length)

    items = {}
    while cur < end:
        next_line = <char *>memchr(cur, c'\n', end - cur)
        if next_line == NULL:
            raise ValueError('null line\n')
        line = PyString_FromStringAndSize(cur, next_line - cur)
        line = py_prefix + line
        elements = line.split('\x00')
        if len(elements) != width + 1:
            raise AssertionError(
                'Incorrect number of elements (%d vs %d) for: %r'
                % (len(elements), width + 1, line))
        num_value_lines = int(elements[-1])
        cur = next_line + 1
        value_start = cur
        # Walk num_value_lines forward
        for i from 0 <= i < num_value_lines:
            next_line = <char *>memchr(cur, c'\n', end - cur)
            if next_line == NULL:
                raise ValueError('null line\n')
            cur = next_line + 1
        # Trim off the final newline
        value = PyString_FromStringAndSize(value_start, next_line - value_start)
        items[tuple(elements[:-1])] = value
    if len(items) != length:
        raise ValueError("item count (%d) mismatch for key %s,"
                         " bytes %r" % (length, key, bytes))
    result._items = items
    result._len = length
    result._maximum_size = maximum_size
    result._key = key
    result._key_width = width
    result._raw_size = 0
    if length == 0:
        result._search_prefix = None
        result._common_serialised_prefix = None
    else:
        result._search_prefix = _unknown
        result._common_serialised_prefix = py_prefix
    # if c_bytes_len !+ result._current_size():
    #     raise AssertionError('_current_size computed incorrectly')
    return result
