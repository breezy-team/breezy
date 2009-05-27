# Copyright (C) 2007,2009 Canonical Ltd
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
    long PyInt_GetMax()
    object PyLong_FromLong(unsigned long)

cdef extern from "stddef.h":
    ctypedef unsigned int size_t

cdef extern from "stdlib.h":
    void free(void *memblock)
    void *malloc(size_t size)
    void *realloc(void *memblock, size_t size)
    long int strtol(char *nptr, char **endptr, int base)


cdef extern from "string.h":
    void *memcpy(void *dest, void *src, size_t count)
    char *memchr(void *dest, int size, char c)

cdef extern from "python-compat.h":
    int snprintf(char* buffer, size_t nsize, char* fmt, ...)


cdef class Decoder:
    """Bencode decoder"""

    cdef readonly char *tail
    cdef readonly int   size

    cdef readonly long   _MAXINT
    cdef readonly int    _MAXN
    cdef readonly object _longint
    cdef readonly int    _yield_tuples

    def __init__(self, s, yield_tuples=0):
        """Initialize decoder engine.
        @param  s:  Python string.
        """
        if not PyString_CheckExact(s):
            raise TypeError("String required")

        self.tail = PyString_AS_STRING(s)
        self.size = PyString_GET_SIZE(s)
        self._yield_tuples = int(yield_tuples)

        self._MAXINT = PyInt_GetMax()
        self._MAXN = len(str(self._MAXINT))
        self._longint = long(0)

    def decode(self):
        result = self.decode_object()
        if self.size != 0:
            raise ValueError('junk in stream')
        return result

    def decode_object(self):
        cdef char ch

        if 0 == self.size:
            raise ValueError('stream underflow')

        ch = self.tail[0]

        if ch == c'i':
            self._update_tail(1)
            return self._decode_int()
        elif c'0' <= ch <= c'9':
            return self._decode_string()
        elif ch == c'l':
            self._update_tail(1)
            return self._decode_list()
        elif ch == c'd':
            self._update_tail(1)
            return self._decode_dict()
        else:
            raise ValueError('unknown object type identifier %r' % ch)

    cdef void _update_tail(self, int n):
        """Update tail pointer and resulting size by n characters"""
        self.size = self.size - n
        self.tail = &self.tail[n]

    cdef object _decode_int(self):
        cdef int result
        result = self._decode_int_until(c'e')
        if result != self._MAXINT:
            return result
        else:
            return self._longint

    cdef int _decode_int_until(self, char stop_char) except? -1:
        """Decode int from stream until stop_char encountered"""
        cdef char *actual_tail, *expected_tail
        cdef int n
        expected_tail = memchr(self.tail, self.size, stop_char)
        if expected_tail == NULL:
            raise ValueError
        ret = PyLong_FromLong(strtol(self.tail, &actual_tail, 10))
        if actual_tail != expected_tail or actual_tail == self.tail:
            raise ValueError
        self._update_tail(actual_tail - self.tail)
        return ret

    cdef object _decode_string(self):
        cdef int n

        n = self._decode_int_until(c':')
        if n == 0:
            return ''
        if n == self._MAXINT:
            # strings longer than 1GB is not supported
            raise ValueError('too long string')
        if n > self.size:
            raise ValueError('stream underflow')
        if n < 0:
            raise ValueError('string size below zero: %d' % n)

        result = PyString_FromStringAndSize(self.tail, n)
        self._update_tail(n)
        return result

    cdef object _decode_list(self):
        result = []

        while self.size > 0:
            if self.tail[0] == c'e':
                self._update_tail(1)
                if self._yield_tuples:
                    return tuple(result)
                else:
                    return result
            else:
                result.append(self.decode_object())

        raise ValueError('malformed list')

    cdef object _decode_dict(self):
        cdef char ch

        result = {}
        lastkey = None

        while self.size > 0:
            ch = self.tail[0]
            if ch == c'e':
                self._update_tail(1)
                return result
            elif c'0' <= ch <= c'9':
                # keys should be strings only
                key = self._decode_string()
                if lastkey >= key:
                    raise ValueError('dict keys disordered')
                else:
                    lastkey = key
                value = self.decode_object()
                result[key] = value
            else:
                raise ValueError('keys in dict should be strings only')

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


cdef class Encoder:
    """Bencode encoder"""

    cdef readonly char *buffer
    cdef readonly int   maxsize
    cdef readonly char *tail
    cdef readonly int   size

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

    def __del__(self):
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

    cdef void _update_tail(self, int n):
        """Update tail pointer and resulting size by n characters"""
        self.size = self.size + n
        self.tail = &self.tail[n]

    cdef int _encode_int(self, int x) except 0:
        """Encode int to bencode string iNNNe
        @param  x:  value to encode
        """
        cdef int n
        self._ensure_buffer(32)
        n = snprintf(self.tail, 32, "i%de", x)
        if n < 0:
            raise MemoryError('int %d too big to encode' % x)
        self._update_tail(n)
        return 1

    cdef int _encode_long(self, x) except 0:
        return self._append_string(''.join(('i', str(x), 'e')))

    cdef int _append_string(self, s) except 0:
        self._ensure_buffer(PyString_GET_SIZE(s))
        memcpy(self.tail, PyString_AS_STRING(s), PyString_GET_SIZE(s))
        self._update_tail(PyString_GET_SIZE(s))
        return 1

    cdef int _encode_string(self, x) except 0:
        cdef int n
        self._ensure_buffer(PyString_GET_SIZE(x) + 32)
        n = snprintf(self.tail, 32, '%d:', PyString_GET_SIZE(x))
        if n < 0:
            raise MemoryError('string %s too big to encode' % x)
        memcpy(<void *>self.tail+n, PyString_AS_STRING(x), 
               PyString_GET_SIZE(x))
        self._update_tail(n+PyString_GET_SIZE(x))
        return 1

    cdef int _encode_list(self, x) except 0:
        self._ensure_buffer(2)
        self.tail[0] = c'l'
        self._update_tail(1)

        for i in x:
            self.process(i)

        self.tail[0] = c'e'
        self._update_tail(1)
        return 1

    cdef int _encode_dict(self, x) except 0:
        self._ensure_buffer(2)
        self.tail[0] = c'd'
        self._update_tail(1)

        keys = x.keys()
        keys.sort()
        for k in keys:
            if not PyString_CheckExact(k):
                raise TypeError('key in dict should be string')
            self._encode_string(k)
            self.process(x[k])

        self.tail[0] = c'e'
        self._update_tail(1)
        return 1

    def process(self, object x):
        if PyString_CheckExact(x):
            self._encode_string(x)
        elif PyInt_CheckExact(x):
            self._encode_int(x)
        elif PyLong_CheckExact(x):
            self._encode_long(x)
        elif PyList_CheckExact(x) or PyTuple_CheckExact(x):
            self._encode_list(x)
        elif PyDict_CheckExact(x):
            self._encode_dict(x)
        elif PyBool_Check(x):
            self._encode_int(int(x))
        elif isinstance(x, Bencached):
            self._append_string(x.bencoded)
        else:
            raise TypeError('unsupported type %r' % x)


def bencode(x):
    """Encode Python object x to string"""
    encoder = Encoder()
    encoder.process(x)
    return str(encoder)
