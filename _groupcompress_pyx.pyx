# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
# 

"""Compiled extensions for doing compression."""

cdef extern from *:
    ctypedef unsigned long size_t
    void * malloc(size_t)
    void * realloc(void *, size_t)
    void free(void *)
    void memcpy(void *, void *, size_t)

cdef extern from "delta.h":
    struct source_info:
        void *buf
        unsigned long size
        unsigned long agg_offset
    struct delta_index:
        pass
    delta_index * create_delta_index(source_info *src, delta_index *old)
    delta_index * create_delta_index_from_delta(source_info *delta,
                                                delta_index *old)
    void free_delta_index(delta_index *index)
    void *create_delta(delta_index *indexes,
             void *buf, unsigned long bufsize,
             unsigned long *delta_size, unsigned long max_delta_size)
    unsigned long get_delta_hdr_size(unsigned char **datap,
                                     unsigned char *top)
    Py_ssize_t DELTA_SIZE_MIN
    void *patch_delta(void *src_buf, unsigned long src_size,
                      void *delta_buf, unsigned long delta_size,
                      unsigned long *dst_size)

cdef extern from "Python.h":
    int PyString_CheckExact(object)
    char * PyString_AS_STRING(object)
    Py_ssize_t PyString_GET_SIZE(object)
    object PyString_FromStringAndSize(char *, Py_ssize_t)


cdef void *safe_malloc(size_t count) except NULL:
    cdef void *result
    result = malloc(count)
    if result == NULL:
        raise MemoryError('Failed to allocate %d bytes of memory' % (count,))
    return result


cdef void *safe_realloc(void * old, size_t count) except NULL:
    cdef void *result
    result = realloc(old, count)
    if result == NULL:
        raise MemoryError('Failed to reallocate to %d bytes of memory'
                          % (count,))
    return result


cdef int safe_free(void **val) except -1:
    assert val != NULL
    if val[0] != NULL:
        free(val[0])
        val[0] = NULL

def make_delta_index(source):
    return DeltaIndex(source)


cdef class DeltaIndex:

    # We need Pyrex 0.9.8+ to understand a 'list' definition, and this object
    # isn't performance critical
    # cdef readonly list _sources
    cdef readonly object _sources
    cdef source_info *_source_infos
    cdef delta_index *_index
    cdef readonly unsigned int _max_num_sources
    cdef public unsigned long _source_offset

    def __repr__(self):
        return '%s(%d, %d)' % (self.__class__.__name__,
            len(self._sources), self._source_offset)

    def __init__(self, source=None):
        self._sources = []
        self._index = NULL
        self._max_num_sources = 65000
        self._source_infos = <source_info *>safe_malloc(sizeof(source_info)
                                                        * self._max_num_sources)
        self._source_offset = 0

        if source is not None:
            self.add_source(source, 0)

    def __dealloc__(self):
        if self._index != NULL:
            free_delta_index(self._index)
            self._index = NULL
        safe_free(<void **>&self._source_infos)

    def add_delta_source(self, delta, unadded_bytes):
        """Add a new delta to the source texts.

        :param delta: The text of the delta, this must be a byte string.
        :param unadded_bytes: Number of bytes that were added to the source
            that were not indexed.
        """
        cdef char *c_delta
        cdef Py_ssize_t c_delta_size
        cdef delta_index *index
        cdef unsigned int source_location
        cdef source_info *src
        cdef unsigned int num_indexes

        if not PyString_CheckExact(delta):
            raise TypeError('delta is not a str')

        source_location = len(self._sources)
        if source_location >= self._max_num_sources:
            self._expand_sources()
        self._sources.append(delta)
        c_delta = PyString_AS_STRING(delta)
        c_delta_size = PyString_GET_SIZE(delta)
        src = self._source_infos + source_location
        src.buf = c_delta
        src.size = c_delta_size
        src.agg_offset = self._source_offset + unadded_bytes
        index = create_delta_index_from_delta(src, self._index)
        self._source_offset = src.agg_offset + src.size
        if index != NULL:
            free_delta_index(self._index)
            self._index = index

    def add_source(self, source, unadded_bytes):
        """Add a new bit of source text to the delta indexes.

        :param source: The text in question, this must be a byte string
        :param unadded_bytes: Assume there are this many bytes that didn't get
            added between this source and the end of the previous source.
        """
        cdef char *c_source
        cdef Py_ssize_t c_source_size
        cdef delta_index *index
        cdef unsigned int source_location
        cdef source_info *src
        cdef unsigned int num_indexes

        if not PyString_CheckExact(source):
            raise TypeError('source is not a str')

        source_location = len(self._sources)
        if source_location >= self._max_num_sources:
            self._expand_sources()
        self._sources.append(source)
        c_source = PyString_AS_STRING(source)
        c_source_size = PyString_GET_SIZE(source)
        src = self._source_infos + source_location
        src.buf = c_source
        src.size = c_source_size

        src.agg_offset = self._source_offset + unadded_bytes
        index = create_delta_index(src, self._index)
        self._source_offset = src.agg_offset + src.size
        if index != NULL:
            free_delta_index(self._index)
            self._index = index

    cdef _expand_sources(self):
        raise RuntimeError('if we move self._source_infos, then we need to'
                           ' change all of the index pointers as well.')
        self._max_num_sources = self._max_num_sources * 2
        self._source_infos = <source_info *>safe_realloc(self._source_infos,
                                                sizeof(source_info)
                                                * self._max_num_sources)

    def make_delta(self, target_bytes, max_delta_size=0):
        """Create a delta from the current source to the target bytes."""
        cdef char *target
        cdef Py_ssize_t target_size
        cdef void * delta
        cdef unsigned long delta_size

        if self._index == NULL:
            return None

        if not PyString_CheckExact(target_bytes):
            raise TypeError('target is not a str')

        target = PyString_AS_STRING(target_bytes)
        target_size = PyString_GET_SIZE(target_bytes)

        # TODO: inline some of create_delta so we at least don't have to double
        #       malloc, and can instead use PyString_FromStringAndSize, to
        #       allocate the bytes into the final string
        delta = create_delta(self._index,
                             target, target_size,
                             &delta_size, max_delta_size)
        result = None
        if delta:
            result = PyString_FromStringAndSize(<char *>delta, delta_size)
            free(delta)
        return result


def make_delta(source_bytes, target_bytes):
    """Create a delta, this is a wrapper around DeltaIndex.make_delta."""
    di = DeltaIndex(source_bytes)
    return di.make_delta(target_bytes)


def apply_delta(source_bytes, delta_bytes):
    """Apply a delta generated by make_delta to source_bytes."""
    cdef char *source
    cdef Py_ssize_t source_size
    cdef char *delta
    cdef Py_ssize_t delta_size
    cdef unsigned char *data, *top
    cdef unsigned char *dst_buf, *out, cmd
    cdef Py_ssize_t size
    cdef unsigned long cp_off, cp_size

    if not PyString_CheckExact(source_bytes):
        raise TypeError('source is not a str')
    if not PyString_CheckExact(delta_bytes):
        raise TypeError('delta is not a str')

    source = PyString_AS_STRING(source_bytes)
    source_size = PyString_GET_SIZE(source_bytes)
    delta = PyString_AS_STRING(delta_bytes)
    delta_size = PyString_GET_SIZE(delta_bytes)

    # Code taken from patch-delta.c, only brought here to give better error
    # handling, and to avoid double allocating memory
    if (delta_size < DELTA_SIZE_MIN):
        # XXX: Invalid delta block
        raise RuntimeError('delta_size %d smaller than min delta size %d'
                           % (delta_size, DELTA_SIZE_MIN))

    data = <unsigned char *>delta
    top = data + delta_size

    # make sure the orig file size matches what we expect
    # XXX: gcc warns because data isn't defined as 'const'
    size = get_delta_hdr_size(&data, top)
    if (size > source_size):
        # XXX: mismatched source size
        raise RuntimeError('source size %d < expected source size %d'
                           % (source_size, size))
    source_size = size

    # now the result size
    size = get_delta_hdr_size(&data, top)
    result = PyString_FromStringAndSize(NULL, size)
    dst_buf = <unsigned char*>PyString_AS_STRING(result)
    # XXX: The original code added a trailing null here, but this shouldn't be
    #      necessary when using PyString_FromStringAndSize
    # dst_buf[size] = 0

    out = dst_buf
    while (data < top):
        cmd = data[0]
        data = data + 1
        if (cmd & 0x80):
            cp_off = cp_size = 0
            if (cmd & 0x01):
                cp_off = data[0]
                data = data + 1
            if (cmd & 0x02):
                cp_off = cp_off | (data[0] << 8)
                data = data + 1
            if (cmd & 0x04):
                cp_off = cp_off | (data[0] << 16)
                data = data + 1
            if (cmd & 0x08):
                cp_off = cp_off | (data[0] << 24)
                data = data + 1
            if (cmd & 0x10):
                cp_size = data[0]
                data = data + 1
            if (cmd & 0x20):
                cp_size = cp_size | (data[0] << 8)
                data = data + 1
            if (cmd & 0x40):
                cp_size = cp_size | (data[0] << 16)
                data = data + 1
            if (cp_size == 0):
                cp_size = 0x10000
            if (cp_off + cp_size < cp_size or
                cp_off + cp_size > source_size or
                cp_size > size):
                raise RuntimeError('Something wrong with:'
                    ' cp_off = %s, cp_size = %s'
                    ' source_size = %s, size = %s'
                    % (cp_off, cp_size, source_size, size))
            memcpy(out, source + cp_off, cp_size)
            out = out + cp_size
            size = size - cp_size
        elif (cmd):
            if (cmd > size):
                raise RuntimeError('Insert instruction longer than remaining'
                    ' bytes: %d > %d' % (cmd, size))
            memcpy(out, data, cmd)
            out = out + cmd
            data = data + cmd
            size = size - cmd
        else:
            # /*
            #  * cmd == 0 is reserved for future encoding
            #  * extensions. In the mean time we must fail when
            #  * encountering them (might be data corruption).
            #  */
            ## /* XXX: error("unexpected delta opcode 0"); */
            raise RuntimeError('Got delta opcode: 0, not supported')

    # /* sanity check */
    if (data != top or size != 0):
        ## /* XXX: error("delta replay has gone wild"); */
        raise RuntimeError('Did not extract the number of bytes we expected'
            ' we were left with %d bytes in "size", and top - data = %d'
            % (size, <int>(top - data)))
        return None

    # *dst_size = out - dst_buf;
    assert (out - dst_buf) == PyString_GET_SIZE(result)
    return result
