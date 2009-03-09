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
    void sprintf(char *, char *, ...)

cdef extern from "Python.h":
    int PyString_CheckExact(object p)
    int PyTuple_CheckExact(object p)
    Py_ssize_t PyTuple_GET_SIZE(object t)
    # Do we want to use the PyObject * instead?
    object PyTuple_GET_ITEM(object t, Py_ssize_t offset)

    Py_ssize_t PyString_GET_SIZE(object s)
    char *PyString_AS_STRING(object s)
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
        bit = PyTuple_GET_ITEM(key, i)
        if not PyString_CheckExact(bit):
            raise TypeError('Bit %d of %r is not a string' % (i, key))
        c_bit = <Bytef *>PyString_AS_STRING(bit)
        c_len = PyString_GET_SIZE(bit)
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
        bit = PyTuple_GET_ITEM(key, i)
        if not PyString_CheckExact(bit):
            raise TypeError('Bit %d of %r is not a string' % (i, key))
        c_bit = <Bytef *>PyString_AS_STRING(bit)
        c_len = PyString_GET_SIZE(bit)
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
