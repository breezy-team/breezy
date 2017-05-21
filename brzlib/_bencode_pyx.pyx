# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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

"""Pyrex implementation for bencode coder/decoder"""


cdef extern from "stddef.h":
    ctypedef unsigned int size_t

cdef extern from "Python.h":
    ctypedef int  Py_ssize_t
    int PyInt_CheckExact(object o)
    int PyLong_CheckExact(object o)
    int PyString_CheckExact(object o)
    int PyTuple_CheckExact(object o)
    int PyList_CheckExact(object o)
    int PyDict_CheckExact(object o)
    int PyBool_Check(object o)
    object PyString_FromStringAndSize(char *v, Py_ssize_t len)
    char *PyString_AS_STRING(object o) except NULL
    Py_ssize_t PyString_GET_SIZE(object o) except -1
    object PyInt_FromString(char *str, char **pend, int base)
    int Py_GetRecursionLimit()
    int Py_EnterRecursiveCall(char *)
    void Py_LeaveRecursiveCall()

    int PyList_Append(object, object) except -1

cdef extern from "stdlib.h":
    void free(void *memblock)
    void *malloc(size_t size)
    void *realloc(void *memblock, size_t size)
    long strtol(char *, char **, int)

cdef extern from "string.h":
    void *memcpy(void *dest, void *src, size_t count)

cdef extern from "python-compat.h":
    int snprintf(char* buffer, size_t nsize, char* fmt, ...)

cdef class Decoder
cdef class Encoder

cdef extern from "_bencode_pyx.h":
    void D_UPDATE_TAIL(Decoder, int n)
    void E_UPDATE_TAIL(Encoder, int n)

# To maintain compatibility with older versions of pyrex, we have to use the
# relative import here, rather than 'bzrlib._static_tuple_c'
from _static_tuple_c cimport StaticTuple, StaticTuple_CheckExact, \
    import_static_tuple_c

import_static_tuple_c()


cdef class Decoder:
    """Bencode decoder"""

    cdef readonly char *tail
    cdef readonly int size
    cdef readonly int _yield_tuples
    cdef object text

    def __init__(self, s, yield_tuples=0):
        """Initialize decoder engine.
        @param  s:  Python string.
        """
        if not PyString_CheckExact(s):
            raise TypeError("String required")

        self.text = s
        self.tail = PyString_AS_STRING(s)
        self.size = PyString_GET_SIZE(s)
        self._yield_tuples = int(yield_tuples)

    def decode(self):
        result = self._decode_object()
        if self.size != 0:
            raise ValueError('junk in stream')
        return result

    def decode_object(self):
        return self._decode_object()

    cdef object _decode_object(self):
        cdef char ch

        if 0 == self.size:
            raise ValueError('stream underflow')

        if Py_EnterRecursiveCall("_decode_object"):
            raise RuntimeError("too deeply nested")
        try:
            ch = self.tail[0]
            if c'0' <= ch <= c'9':
                return self._decode_string()
            elif ch == c'l':
                D_UPDATE_TAIL(self, 1)
                return self._decode_list()
            elif ch == c'i':
                D_UPDATE_TAIL(self, 1)
                return self._decode_int()
            elif ch == c'd':
                D_UPDATE_TAIL(self, 1)
                return self._decode_dict()
            else:
                raise ValueError('unknown object type identifier %r' % ch)
        finally:
            Py_LeaveRecursiveCall()

    cdef int _read_digits(self, char stop_char) except -1:
        cdef int i
        i = 0
        while ((self.tail[i] >= c'0' and self.tail[i] <= c'9') or
               self.tail[i] == c'-') and i < self.size:
            i = i + 1

        if self.tail[i] != stop_char:
            raise ValueError("Stop character %c not found: %c" % 
                (stop_char, self.tail[i]))
        if (self.tail[0] == c'0' or 
                (self.tail[0] == c'-' and self.tail[1] == c'0')):
            if i == 1:
                return i
            else:
                raise ValueError # leading zeroes are not allowed
        return i

    cdef object _decode_int(self):
        cdef int i
        i = self._read_digits(c'e')
        self.tail[i] = 0
        try:
            ret = PyInt_FromString(self.tail, NULL, 10)
        finally:
            self.tail[i] = c'e'
        D_UPDATE_TAIL(self, i+1)
        return ret

    cdef object _decode_string(self):
        cdef int n
        cdef char *next_tail
        # strtol allows leading whitespace, negatives, and leading zeros
        # however, all callers have already checked that '0' <= tail[0] <= '9'
        # or they wouldn't have called _decode_string
        # strtol will stop at trailing whitespace, etc
        n = strtol(self.tail, &next_tail, 10)
        if next_tail == NULL or next_tail[0] != c':':
            raise ValueError('string len not terminated by ":"')
        # strtol allows leading zeros, so validate that we don't have that
        if (self.tail[0] == c'0'
            and (n != 0 or (next_tail - self.tail != 1))):
            raise ValueError('leading zeros are not allowed')
        D_UPDATE_TAIL(self, next_tail - self.tail + 1)
        if n == 0:
            return ''
        if n > self.size:
            raise ValueError('stream underflow')
        if n < 0:
            raise ValueError('string size below zero: %d' % n)

        result = PyString_FromStringAndSize(self.tail, n)
        D_UPDATE_TAIL(self, n)
        return result

    cdef object _decode_list(self):
        result = []

        while self.size > 0:
            if self.tail[0] == c'e':
                D_UPDATE_TAIL(self, 1)
                if self._yield_tuples:
                    return tuple(result)
                else:
                    return result
            else:
                # As a quick shortcut, check to see if the next object is a
                # string, since we know that won't be creating recursion
                # if self.tail[0] >= c'0' and self.tail[0] <= c'9':
                PyList_Append(result, self._decode_object())

        raise ValueError('malformed list')

    cdef object _decode_dict(self):
        cdef char ch

        result = {}
        lastkey = None

        while self.size > 0:
            ch = self.tail[0]
            if ch == c'e':
                D_UPDATE_TAIL(self, 1)
                return result
            else:
                # keys should be strings only
                if self.tail[0] < c'0' or self.tail[0] > c'9':
                    raise ValueError('key was not a simple string.')
                key = self._decode_string()
                if lastkey >= key:
                    raise ValueError('dict keys disordered')
                else:
                    lastkey = key
                value = self._decode_object()
                result[key] = value

        raise ValueError('malformed dict')


def bdecode(object s):
    """Decode string x to Python object"""
    return Decoder(s).decode()


def bdecode_as_tuple(object s):
    """Decode string x to Python object, using tuples rather than lists."""
    return Decoder(s, True).decode()


class Bencached(object):
    __slots__ = ['bencoded']

    def __init__(self, s):
        self.bencoded = s


cdef enum:
    INITSIZE = 1024     # initial size for encoder buffer
    INT_BUF_SIZE = 32


cdef class Encoder:
    """Bencode encoder"""

    cdef readonly char *tail
    cdef readonly int size
    cdef readonly char *buffer
    cdef readonly int maxsize

    def __init__(self, int maxsize=INITSIZE):
        """Initialize encoder engine
        @param  maxsize:    initial size of internal char buffer
        """
        cdef char *p

        self.maxsize = 0
        self.size = 0
        self.tail = NULL

        p = <char*>malloc(maxsize)
        if p == NULL:
            raise MemoryError('Not enough memory to allocate buffer '
                              'for encoder')
        self.buffer = p
        self.maxsize = maxsize
        self.tail = p

    def __dealloc__(self):
        free(self.buffer)
        self.buffer = NULL
        self.maxsize = 0

    def __str__(self):
        if self.buffer != NULL and self.size != 0:
            return PyString_FromStringAndSize(self.buffer, self.size)
        else:
            return ''

    cdef int _ensure_buffer(self, int required) except 0:
        """Ensure that tail of CharTail buffer has enough size.
        If buffer is not big enough then function try to
        realloc buffer.
        """
        cdef char *new_buffer
        cdef int   new_size

        if self.size + required < self.maxsize:
            return 1

        new_size = self.maxsize
        while new_size < self.size + required:
            new_size = new_size * 2
        new_buffer = <char*>realloc(self.buffer, <size_t>new_size)
        if new_buffer == NULL:
            raise MemoryError('Cannot realloc buffer for encoder')

        self.buffer = new_buffer
        self.maxsize = new_size
        self.tail = &new_buffer[self.size]
        return 1

    cdef int _encode_int(self, int x) except 0:
        """Encode int to bencode string iNNNe
        @param  x:  value to encode
        """
        cdef int n
        self._ensure_buffer(INT_BUF_SIZE)
        n = snprintf(self.tail, INT_BUF_SIZE, "i%de", x)
        if n < 0:
            raise MemoryError('int %d too big to encode' % x)
        E_UPDATE_TAIL(self, n)
        return 1

    cdef int _encode_long(self, x) except 0:
        return self._append_string(''.join(('i', str(x), 'e')))

    cdef int _append_string(self, s) except 0:
        cdef Py_ssize_t n
        n = PyString_GET_SIZE(s)
        self._ensure_buffer(n)
        memcpy(self.tail, PyString_AS_STRING(s), n)
        E_UPDATE_TAIL(self, n)
        return 1

    cdef int _encode_string(self, x) except 0:
        cdef int n
        cdef Py_ssize_t x_len
        x_len = PyString_GET_SIZE(x)
        self._ensure_buffer(x_len + INT_BUF_SIZE)
        n = snprintf(self.tail, INT_BUF_SIZE, '%d:', x_len)
        if n < 0:
            raise MemoryError('string %s too big to encode' % x)
        memcpy(<void *>(self.tail+n), PyString_AS_STRING(x), x_len)
        E_UPDATE_TAIL(self, n + x_len)
        return 1

    cdef int _encode_list(self, x) except 0:
        self._ensure_buffer(1)
        self.tail[0] = c'l'
        E_UPDATE_TAIL(self, 1)

        for i in x:
            self.process(i)

        self._ensure_buffer(1)
        self.tail[0] = c'e'
        E_UPDATE_TAIL(self, 1)
        return 1

    cdef int _encode_dict(self, x) except 0:
        self._ensure_buffer(1)
        self.tail[0] = c'd'
        E_UPDATE_TAIL(self, 1)

        keys = x.keys()
        keys.sort()
        for k in keys:
            if not PyString_CheckExact(k):
                raise TypeError('key in dict should be string')
            self._encode_string(k)
            self.process(x[k])

        self._ensure_buffer(1)
        self.tail[0] = c'e'
        E_UPDATE_TAIL(self, 1)
        return 1

    def process(self, object x):
        if Py_EnterRecursiveCall("encode"):
            raise RuntimeError("too deeply nested")
        try:
            if PyString_CheckExact(x):
                self._encode_string(x)
            elif PyInt_CheckExact(x):
                self._encode_int(x)
            elif PyLong_CheckExact(x):
                self._encode_long(x)
            elif (PyList_CheckExact(x) or PyTuple_CheckExact(x)
                  or StaticTuple_CheckExact(x)):
                self._encode_list(x)
            elif PyDict_CheckExact(x):
                self._encode_dict(x)
            elif PyBool_Check(x):
                self._encode_int(int(x))
            elif isinstance(x, Bencached):
                self._append_string(x.bencoded)
            else:
                raise TypeError('unsupported type %r' % x)
        finally:
            Py_LeaveRecursiveCall()


def bencode(x):
    """Encode Python object x to string"""
    encoder = Encoder()
    encoder.process(x)
    return str(encoder)
