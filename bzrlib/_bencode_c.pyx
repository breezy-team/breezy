# Copyright (C) 2007 Canonical Ltd
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

"""Pyrex implementation for bencode coder/decoder"""


cdef extern from "Python.h":
    ctypedef int  Py_ssize_t
    object Py_BuildValue(char *format, ...)
    int PyInt_CheckExact(object o)
    int PyLong_CheckExact(object o)
    int PyString_CheckExact(object o)
    int PyTuple_CheckExact(object o)
    int PyList_CheckExact(object o)
    int PyDict_CheckExact(object o)
    int PyBool_Check(object o)
    object PyString_FromStringAndSize(char *v, Py_ssize_t len)
    int PyString_AsStringAndSize(object o, char **buffer, Py_ssize_t *length)
    long PyInt_GetMax()
    object PyLong_FromString(char *str, char **pend, int base)

cdef extern from "stddef.h":
    ctypedef unsigned int size_t

cdef extern from "stdlib.h":
    void free(void *memblock)
    void *malloc(size_t size)
    void *realloc(void *memblock, size_t size)

cdef extern from "string.h":
    void *memcpy(void *dest, void *src, size_t count)

cdef extern from "_bencode_c.h":
    int snprintf(char* buffer, size_t nsize, char* fmt, ...)


class NotEnoughMemory(Exception):
    """Memory allocation error"""
    pass


cdef enum:  # Codes for used characters
    MINUS   = 0x2D      # ord(-)
    CHAR_0  = 0x30      # ord(0)
    CHAR_1  = 0x31      # ord(1)
    CHAR_2  = 0x32      # ord(2)
    CHAR_3  = 0x33      # ord(3)
    CHAR_4  = 0x34      # ord(4)
    CHAR_5  = 0x35      # ord(5)
    CHAR_6  = 0x36      # ord(6)
    CHAR_7  = 0x37      # ord(7)
    CHAR_8  = 0x38      # ord(8)
    CHAR_9  = 0x39      # ord(9)
    COLON   = 0x3A      # ord(:)
    SMALL_D = 0x64      # ord(d)
    SMALL_E = 0x65      # ord(e)
    SMALL_I = 0x69      # ord(i)
    SMALL_L = 0x6c      # ord(l)


cdef class Decoder:
    """Bencode decoder"""

    cdef readonly object __s
    cdef readonly char *tail
    cdef readonly int   size

    cdef readonly long   _MAXINT
    cdef readonly int    _MAXN
    cdef readonly object _longint

    def __init__(self, s):
        """Initialize decoder engine.
        @param  s:  Python string.
        """
        cdef Py_ssize_t k
        cdef char *pstr

        if not PyString_CheckExact(s):
            raise TypeError

        PyString_AsStringAndSize(s, &pstr, &k)

        if pstr == NULL:
            raise ValueError

        self.__s = s
        self.tail = pstr
        self.size = <int>k

        self._MAXINT = PyInt_GetMax()
        self._MAXN = len(str(self._MAXINT))
        self._longint = long(0)

    def __repr__(self):
        return 'Decoder(%s)' % repr(self.__s)

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

        if ch == SMALL_I:
            self._update_tail(1)
            return self._decode_int()
        elif CHAR_0 <= ch <= CHAR_9:
            return self._decode_string()
        elif ch == SMALL_L:
            self._update_tail(1)
            return self._decode_list()
        elif ch == SMALL_D:
            self._update_tail(1)
            return self._decode_dict()

        raise ValueError('unknown object')

    cdef void _update_tail(self, int n):
        """Update tail pointer and resulting size by n characters"""
        self.size = self.size - n
        self.tail = &self.tail[n]

    cdef object _decode_int(self):
        cdef int result
        result = self._decode_int_until(SMALL_E)
        if result != self._MAXINT:
            return result
        else:
            return self._longint

    cdef int _decode_int_until(self, char stop_char) except? -1:
        """Decode int from stream until stop_char encountered"""
        cdef int result
        cdef int i, n
        cdef int sign
        cdef char digit
        cdef char *longstr

        for n from 0 <= n < self.size:
            if self.tail[n] == stop_char:
                break
        else:
            raise ValueError

        sign = 0
        if MINUS == self.tail[0]:
            sign = 1

        if n-sign == 0:
            raise ValueError    # ie / i-e

        if self.tail[sign] == CHAR_0:   # special check for zero
            if sign:
                raise ValueError    # i-0e
            if n > 1:
                raise ValueError    # i00e / i01e
            self._update_tail(n+1)
            return 0

        if n-sign < self._MAXN:
            # plain int
            result = 0
            for i from sign <= i < n:
                digit = self.tail[i]
                if CHAR_0 <= digit <= CHAR_9:
                    result = result * 10 + (digit - CHAR_0)
                else:
                    raise ValueError
            if sign:
                result = -result
            self._update_tail(n+1)
        else:
            # long int
            result = self._MAXINT
            longstr = <char*>malloc(n+1)
            if NULL == longstr:
                raise NotEnoughMemory
            memcpy(longstr, self.tail, n)
            longstr[n] = 0
            self._longint = PyLong_FromString(longstr, NULL, 10)
            free(longstr)
            self._update_tail(n+1)

        return result

    cdef object _decode_string(self):
        cdef int n

        n = self._decode_int_until(COLON)
        if n == 0:
            return ''
        if n == self._MAXINT:
            # strings longer than 1GB is not supported
            raise ValueError('too long string')
        if n > self.size:
            raise ValueError('stream underflow')

        result = PyString_FromStringAndSize(self.tail, n)
        self._update_tail(n)
        return result

    cdef object _decode_list(self):
        result = []

        while self.size > 0:
            if self.tail[0] == SMALL_E:
                self._update_tail(1)
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
            if ch == SMALL_E:
                self._update_tail(1)
                return result
            elif CHAR_0 <= ch <= CHAR_9:
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
            raise NotEnoughMemory('Not enough memory to allocate buffer '
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
            raise NotEnoughMemory('Cannot realloc buffer for encoder')

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
            raise NotEnoughMemory('int %d too big to encode' % x)
        self._update_tail(n)
        return 1

    cdef int _encode_long(self, x) except 0:
        return self._append_string(''.join(('i', str(x), 'e')))

    cdef int _append_string(self, s) except 0:
        cdef Py_ssize_t k
        cdef int n
        cdef char *pstr

        PyString_AsStringAndSize(s, &pstr, &k)
        k = (<int>k + 1)
        self._ensure_buffer(<int>k)
        n = snprintf(self.tail, k, '%s', pstr)
        if n < 0:
            raise NotEnoughMemory('string %s too big to append' % s)
        self._update_tail(n)
        return 1

    cdef int _encode_string(self, x) except 0:
        cdef Py_ssize_t k
        cdef int n
        cdef char *pstr

        PyString_AsStringAndSize(x, &pstr, &k)
        self._ensure_buffer(<int>k+32)
        n = snprintf(self.tail, k+32, '%d:%s', <int>k, pstr)
        if n < 0:
            raise NotEnoughMemory('string %s too big to encode' % x)
        self._update_tail(n)
        return 1

    cdef int _encode_list(self, x) except 0:
        self._ensure_buffer(2)
        self.tail[0] = SMALL_L
        self._update_tail(1)

        for i in x:
            self.process(i)

        self.tail[0] = SMALL_E
        self._update_tail(1)
        return 1

    cdef int _encode_dict(self, x) except 0:
        self._ensure_buffer(2)
        self.tail[0] = SMALL_D
        self._update_tail(1)

        keys = x.keys()
        keys.sort()
        for k in keys:
            if not PyString_CheckExact(k):
                raise TypeError('key in dict should be string')
            self._encode_string(k)
            self.process(x[k])

        self.tail[0] = SMALL_E
        self._update_tail(1)
        return 1

    def process(self, object x):
        if PyInt_CheckExact(x):
            self._encode_int(x)
        elif PyLong_CheckExact(x):
            self._encode_long(x)
        elif PyString_CheckExact(x):
            self._encode_string(x)
        elif PyList_CheckExact(x) or PyTuple_CheckExact(x):
            self._encode_list(x)
        elif PyDict_CheckExact(x):
            self._encode_dict(x)
        elif PyBool_Check(x):
            self._encode_int(int(x))
        elif isinstance(x, Bencached):
            self._append_string(x.bencoded)
        else:
            raise TypeError('unsupported type')


def bencode(x):
    """Encode Python object x to string"""
    encoder = Encoder()
    encoder.process(x)
    return str(encoder)
