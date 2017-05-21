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

"""Pyrex implementation of _read_stanza_*."""

#python2.4 support
cdef extern from "python-compat.h":
    pass

cdef extern from "stdlib.h":
    void *malloc(int)
    void *realloc(void *, int)
    void free(void *)

cdef extern from "Python.h":
    ctypedef int Py_ssize_t # Required for older pyrex versions
    ctypedef int Py_UNICODE
    char *PyString_AS_STRING(object s)
    Py_ssize_t PyString_GET_SIZE(object t) except -1
    object PyUnicode_DecodeUTF8(char *string, Py_ssize_t length, char *errors)
    object PyString_FromStringAndSize(char *s, Py_ssize_t len)
    int PyString_CheckExact(object)
    int PyUnicode_CheckExact(object)
    object PyUnicode_Join(object, object)
    object PyUnicode_EncodeASCII(Py_UNICODE *, int, char *)
    Py_UNICODE *PyUnicode_AS_UNICODE(object)
    Py_UNICODE *PyUnicode_AsUnicode(object)
    Py_ssize_t PyUnicode_GET_SIZE(object) except -1
    int PyList_Append(object, object) except -1    
    int Py_UNICODE_ISLINEBREAK(Py_UNICODE)
    object PyUnicode_FromUnicode(Py_UNICODE *, int)
    void *Py_UNICODE_COPY(Py_UNICODE *, Py_UNICODE *, int)

cdef extern from "string.h":
    void *memcpy(void *, void *, int)

from bzrlib.rio import Stanza

cdef int _valid_tag_char(char c): # cannot_raise
    return (c == c'_' or c == c'-' or 
            (c >= c'a' and c <= c'z') or
            (c >= c'A' and c <= c'Z') or
            (c >= c'0' and c <= c'9'))


def _valid_tag(tag):
    cdef char *c_tag
    cdef Py_ssize_t c_len
    cdef int i
    if not PyString_CheckExact(tag):
        raise TypeError(tag)
    c_tag = PyString_AS_STRING(tag)
    c_len = PyString_GET_SIZE(tag)
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
            return PyString_FromStringAndSize(line, i)
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
            return PyUnicode_EncodeASCII(line, i, "strict")
    raise ValueError("tag/value separator not found in line %r" %
                     PyUnicode_FromUnicode(line, len))


def _read_stanza_utf8(line_iter):
    cdef char *c_line
    cdef Py_ssize_t c_len
    cdef char *accum_value, *new_accum_value
    cdef Py_ssize_t accum_len, accum_size
    pairs = []
    tag = None
    accum_len = 0
    accum_size = 4096
    accum_value = <char *>malloc(accum_size)
    if accum_value == NULL:
        raise MemoryError
    try:
        for line in line_iter:
            if line is None:
                break # end of file
            if not PyString_CheckExact(line):
                raise TypeError("%r is not a plain string" % line)
            c_line = PyString_AS_STRING(line)
            c_len = PyString_GET_SIZE(line)
            if c_len < 1:
                break       # end of file
            if c_len == 1 and c_line[0] == c"\n":
                break       # end of stanza
            if accum_len + c_len > accum_size:
                accum_size = (accum_len + c_len)
                new_accum_value = <char *>realloc(accum_value, accum_size)
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
                (tag, PyUnicode_DecodeUTF8(accum_value, accum_len-1, "strict")))
            return Stanza.from_pairs(pairs)
        else:     # didn't see any content
            return None
    finally:
        free(accum_value)


def _read_stanza_unicode(unicode_iter):
    cdef Py_UNICODE *c_line
    cdef int c_len
    cdef Py_UNICODE *accum_value, *new_accum_value
    cdef Py_ssize_t accum_len, accum_size
    pairs = []
    tag = None
    accum_len = 0
    accum_size = 4096
    accum_value = <Py_UNICODE *>malloc(accum_size*sizeof(Py_UNICODE))
    if accum_value == NULL:
        raise MemoryError
    try:
        for line in unicode_iter:
            if line is None:
                break       # end of file
            if not PyUnicode_CheckExact(line):
                raise TypeError("%r is not a unicode string" % line)
            c_line = PyUnicode_AS_UNICODE(line)
            c_len = PyUnicode_GET_SIZE(line)
            if c_len < 1:
                break        # end of file
            if Py_UNICODE_ISLINEBREAK(c_line[0]):
                break       # end of stanza
            if accum_len + c_len > accum_size:
                accum_size = accum_len + c_len
                new_accum_value = <Py_UNICODE *>realloc(accum_value, 
                    accum_size*sizeof(Py_UNICODE))
                if new_accum_value == NULL:
                    raise MemoryError
                else:
                    accum_value = new_accum_value
            if c_line[0] == c'\t': # continues previous value,
                if tag is None:
                    raise ValueError('invalid continuation line %r' % line)
                memcpy(&accum_value[accum_len], &c_line[1],
                    (c_len-1)*sizeof(Py_UNICODE))
                accum_len = accum_len + (c_len-1)
            else: # new tag:value line
                if tag is not None:
                    PyList_Append(pairs, 
                        (tag, PyUnicode_FromUnicode(accum_value, accum_len-1)))
                tag = _split_first_line_unicode(c_line, c_len, accum_value, 
                                                &accum_len)
                if not _valid_tag(tag):
                    raise ValueError("invalid rio tag %r" % (tag,))
        if tag is not None: # add last tag-value
            PyList_Append(pairs,
                    (tag, PyUnicode_FromUnicode(accum_value, accum_len-1)))
            return Stanza.from_pairs(pairs)
        else:     # didn't see any content
            return None
    finally:
        free(accum_value)
