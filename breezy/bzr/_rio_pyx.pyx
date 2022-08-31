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

"""Pyrex implementation of _read_stanza_*."""


cdef extern from "python-compat.h":
    pass

from cpython.bytes cimport (
    PyBytes_CheckExact,
    PyBytes_FromStringAndSize,
    PyBytes_AS_STRING,
    PyBytes_GET_SIZE,
    )
from cpython.unicode cimport (
    PyUnicode_CheckExact,
    PyUnicode_DecodeUTF8,
    # Deprecated after PEP 393 changes
    PyUnicode_AS_UNICODE,
    PyUnicode_FromUnicode,
    PyUnicode_GET_SIZE,
    )
from cpython.list cimport (
    PyList_Append,
    )
from cpython.mem cimport (
    PyMem_Free,
    PyMem_Malloc,
    PyMem_Realloc,
    )
from cpython.version cimport (
    PY_MAJOR_VERSION,
    )

cdef extern from "Python.h":
    ctypedef int Py_UNICODE
    object PyUnicode_EncodeASCII(Py_UNICODE *, int, char *)
    int Py_UNICODE_ISLINEBREAK(Py_UNICODE)

    # GZ 2017-09-11: Not sure why cython unicode module lacks this?
    object PyUnicode_FromStringAndSize(const char *u, Py_ssize_t size)

    # Python 3.3 or later unicode handling
    char* PyUnicode_AsUTF8AndSize(object unicode, Py_ssize_t *size)

from libc.string cimport (
    memcpy,
    )

from .rio import Stanza


cdef int _valid_tag_char(char c): # cannot_raise
    return (c == c'_' or c == c'-' or
            (c >= c'a' and c <= c'z') or
            (c >= c'A' and c <= c'Z') or
            (c >= c'0' and c <= c'9'))


def _valid_tag(tag):
    cdef char *c_tag
    cdef Py_ssize_t c_len
    cdef int i
    # GZ 2017-09-11: Encapsulate native string as ascii tag somewhere neater
    if PY_MAJOR_VERSION >= 3:
        if not PyUnicode_CheckExact(tag):
            raise TypeError(tag)
        c_tag = PyUnicode_AsUTF8AndSize(tag, &c_len)
    else:
        if not PyBytes_CheckExact(tag):
            raise TypeError(tag)
        c_tag = PyBytes_AS_STRING(tag)
        c_len = PyBytes_GET_SIZE(tag)
    if c_len < 1:
        return False
    for i from 0 <= i < c_len:
        if not _valid_tag_char(c_tag[i]):
            return False
    return True


cdef object _split_first_line_utf8(char *line, int len,
                                   char *value, Py_ssize_t *value_len):
    cdef int i
    for i from 0 <= i < len:
        if line[i] == c':':
            if line[i+1] != c' ':
                raise ValueError("invalid tag in line %r" % line)
            memcpy(value, line+i+2, len-i-2)
            value_len[0] = len-i-2
            if PY_MAJOR_VERSION >= 3:
                return PyUnicode_FromStringAndSize(line, i)
            return PyBytes_FromStringAndSize(line, i)
    raise ValueError('tag/value separator not found in line %r' % line)


cdef object _split_first_line_unicode(Py_UNICODE *line, int len,
                                      Py_UNICODE *value, Py_ssize_t *value_len):
    cdef int i
    for i from 0 <= i < len:
        if line[i] == c':':
            if line[i+1] != c' ':
                raise ValueError("invalid tag in line %r" %
                                 PyUnicode_FromUnicode(line, len))
            memcpy(value, &line[i+2], (len-i-2) * sizeof(Py_UNICODE))
            value_len[0] = len-i-2
            if PY_MAJOR_VERSION >= 3:
                return PyUnicode_FromUnicode(line, i)
            return PyUnicode_EncodeASCII(line, i, "strict")
    raise ValueError("tag/value separator not found in line %r" %
                     PyUnicode_FromUnicode(line, len))


def _read_stanza_utf8(line_iter):
    cdef char *c_line
    cdef Py_ssize_t c_len
    cdef char *accum_value
    cdef char *new_accum_value
    cdef Py_ssize_t accum_len, accum_size
    pairs = []
    tag = None
    accum_len = 0
    accum_size = 4096
    accum_value = <char *>PyMem_Malloc(accum_size)
    if accum_value == NULL:
        raise MemoryError
    try:
        for line in line_iter:
            if line is None:
                break # end of file
            if not PyBytes_CheckExact(line):
                raise TypeError("%r is not a plain string" % line)
            c_line = PyBytes_AS_STRING(line)
            c_len = PyBytes_GET_SIZE(line)
            if c_len < 1:
                break       # end of file
            if c_len == 1 and c_line[0] == c"\n":
                break       # end of stanza
            if accum_len + c_len > accum_size:
                accum_size = (accum_len + c_len)
                new_accum_value = <char *>PyMem_Realloc(accum_value, accum_size)
                if new_accum_value == NULL:
                    raise MemoryError
                else:
                    accum_value = new_accum_value
            if c_line[0] == c'\t': # continues previous value
                if tag is None:
                    raise ValueError('invalid continuation line %r' % line)
                memcpy(accum_value+accum_len, c_line+1, c_len-1)
                accum_len = accum_len + c_len-1
            else: # new tag:value line
                if tag is not None:
                    PyList_Append(pairs,
                        (tag, PyUnicode_DecodeUTF8(accum_value, accum_len-1,
                                                   "strict")))
                tag = _split_first_line_utf8(c_line, c_len, accum_value,
                                             &accum_len)
                if not _valid_tag(tag):
                    raise ValueError("invalid rio tag %r" % (tag,))
        if tag is not None: # add last tag-value
            PyList_Append(pairs,
                (tag, PyUnicode_DecodeUTF8(accum_value, accum_len-1, "surrogateescape")))
            return Stanza.from_pairs(pairs)
        else:     # didn't see any content
            return None
    finally:
        PyMem_Free(accum_value)
