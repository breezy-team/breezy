# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

"""Compiled extensions for doing compression."""


cdef extern from "python-compat.h":
    pass

from cpython.bytes cimport (PyBytes_AS_STRING, PyBytes_CheckExact,
                            PyBytes_FromStringAndSize, PyBytes_GET_SIZE)
from cpython.mem cimport PyMem_Free, PyMem_Malloc
from cpython.object cimport PyObject
from libc.stdlib cimport free
from libc.string cimport memcpy


cdef extern from "delta.h":
    struct source_info:
        void *buf
        unsigned long size
        unsigned long agg_offset
    struct delta_index:
        pass
    ctypedef enum delta_result:
        DELTA_OK
        DELTA_OUT_OF_MEMORY
        DELTA_INDEX_NEEDED
        DELTA_SOURCE_EMPTY
        DELTA_SOURCE_BAD
        DELTA_BUFFER_EMPTY
        DELTA_SIZE_TOO_BIG
    delta_result create_delta_index(source_info *src,
                                    delta_index *old,
                                    delta_index **fresh,
                                    int max_entries) nogil
    delta_result create_delta_index_from_delta(source_info *delta,
                                               delta_index *old,
                                               delta_index **fresh) nogil
    void free_delta_index(delta_index *index) nogil
    delta_result create_delta(delta_index *indexes,
                              void *buf, unsigned long bufsize,
                              unsigned long *delta_size,
                              unsigned long max_delta_size,
                              void **delta_data) nogil
    unsigned long get_delta_hdr_size(unsigned char **datap,
                                     unsigned char *top) nogil
    unsigned long sizeof_delta_index(delta_index *index)
    Py_ssize_t DELTA_SIZE_MIN
    int get_hash_offset(delta_index *index, int pos, unsigned int *hash_offset)
    int get_entry_summary(delta_index *index, int pos,
                          unsigned int *global_offset, unsigned int *hash_val)
    unsigned int rabin_hash (unsigned char *data)


def make_delta_index(source):
    return DeltaIndex(source)


cdef object _translate_delta_failure(delta_result result):
    if result == DELTA_OUT_OF_MEMORY:
        return MemoryError("Delta function failed to allocate memory")
    elif result == DELTA_INDEX_NEEDED:
        return ValueError("Delta function requires delta_index param")
    elif result == DELTA_SOURCE_EMPTY:
        return ValueError("Delta function given empty source_info param")
    elif result == DELTA_SOURCE_BAD:
        return RuntimeError("Delta function given invalid source_info param")
    elif result == DELTA_BUFFER_EMPTY:
        return ValueError("Delta function given empty buffer params")
    return AssertionError("Unrecognised delta result code: %d" % result)


def _rabin_hash(content):
    if not PyBytes_CheckExact(content):
        raise ValueError('content must be a string')
    if len(content) < 16:
        raise ValueError('content must be at least 16 bytes long')
    # Try to cast it to an int, if it can fit
    return int(rabin_hash(<unsigned char*>(PyBytes_AS_STRING(content))))


cdef class DeltaIndex:

    cdef readonly list _sources
    cdef source_info *_source_infos
    cdef delta_index *_index
    cdef public unsigned long _source_offset
    cdef readonly unsigned int _max_num_sources
    cdef public int _max_bytes_to_index

    def __init__(self, source=None, max_bytes_to_index=None):
        self._sources = []
        self._index = NULL
        self._max_num_sources = 65000
        self._source_infos = <source_info *>PyMem_Malloc(
            sizeof(source_info) * self._max_num_sources)
        if self._source_infos == NULL:
            raise MemoryError('failed to allocate memory for DeltaIndex')
        self._source_offset = 0
        self._max_bytes_to_index = 0
        if max_bytes_to_index is not None:
            self._max_bytes_to_index = max_bytes_to_index

        if source is not None:
            self.add_source(source, 0)

    def __sizeof__(self):
        # We want to track the _source_infos allocations, but the referenced
        # void* are actually tracked in _sources itself.
        return (sizeof(DeltaIndex)
                + (sizeof(source_info) * self._max_num_sources)
                + sizeof_delta_index(self._index))

    def __repr__(self):
        return '%s(%d, %d)' % (self.__class__.__name__,
            len(self._sources), self._source_offset)

    def __dealloc__(self):
        if self._index != NULL:
            free_delta_index(self._index)
            self._index = NULL
        PyMem_Free(self._source_infos)

    def _has_index(self):
        return (self._index != NULL)

    def _dump_index(self):
        """Dump the pointers in the index.

        This is an arbitrary layout, used for testing. It is not meant to be
        used in production code.

        :return: (hash_list, entry_list)
            hash_list   A list of offsets, so hash[i] points to the 'hash
                        bucket' starting at the given offset and going until
                        hash[i+1]
            entry_list  A list of (text_offset, hash_val). text_offset is the
                        offset in the "source" texts, and hash_val is the RABIN
                        hash for that offset.
                        Note that the entry should be in the hash bucket
                        defined by
                        hash[(hash_val & mask)] && hash[(hash_val & mask) + 1]
        """
        cdef int pos
        cdef unsigned int text_offset
        cdef unsigned int hash_val
        cdef unsigned int hash_offset
        if self._index == NULL:
            return None
        hash_list = []
        pos = 0
        while get_hash_offset(self._index, pos, &hash_offset):
            hash_list.append(int(hash_offset))
            pos += 1
        entry_list = []
        pos = 0
        while get_entry_summary(self._index, pos, &text_offset, &hash_val):
            # Map back using 'int' so that we don't get Long everywhere, when
            # almost everything is <2**31.
            val = tuple(map(int, [text_offset, hash_val]))
            entry_list.append(val)
            pos += 1
        return hash_list, entry_list

    def add_delta_source(self, delta, unadded_bytes):
        """Add a new delta to the source texts.

        :param delta: The text of the delta, this must be a byte string.
        :param unadded_bytes: Number of bytes that were added to the source
            that were not indexed.
        """
        cdef char *c_delta
        cdef Py_ssize_t c_delta_size
        cdef delta_index *index
        cdef delta_result res
        cdef unsigned int source_location
        cdef source_info *src
        cdef unsigned int num_indexes

        if not PyBytes_CheckExact(delta):
            raise TypeError('delta is not a bytestring')

        source_location = len(self._sources)
        if source_location >= self._max_num_sources:
            self._expand_sources()
        self._sources.append(delta)
        c_delta = PyBytes_AS_STRING(delta)
        c_delta_size = PyBytes_GET_SIZE(delta)
        src = self._source_infos + source_location
        src.buf = c_delta
        src.size = c_delta_size
        src.agg_offset = self._source_offset + unadded_bytes
        with nogil:
            res = create_delta_index_from_delta(src, self._index, &index)
        if res != DELTA_OK:
            raise _translate_delta_failure(res)
        self._source_offset = src.agg_offset + src.size
        if index != self._index:
            free_delta_index(self._index)
            self._index = index

    def add_source(self, source, unadded_bytes):
        """Add a new bit of source text to the delta indexes.

        :param source: The text in question, this must be a byte string
        :param unadded_bytes: Assume there are this many bytes that didn't get
            added between this source and the end of the previous source.
        :param max_pointers: Add no more than this many entries to the index.
            By default, we sample every 16 bytes, if that would require more
            than max_entries, we will reduce the sampling rate.
            A value of 0 means unlimited, None means use the default limit.
        """
        cdef char *c_source
        cdef Py_ssize_t c_source_size
        cdef delta_index *index
        cdef delta_result res
        cdef unsigned int source_location
        cdef source_info *src
        cdef unsigned int num_indexes
        cdef int max_num_entries

        if not PyBytes_CheckExact(source):
            raise TypeError('source is not a bytestring')

        source_location = len(self._sources)
        if source_location >= self._max_num_sources:
            self._expand_sources()
        if source_location != 0 and self._index == NULL:
            # We were lazy about populating the index, create it now
            self._populate_first_index()
        self._sources.append(source)
        c_source = PyBytes_AS_STRING(source)
        c_source_size = PyBytes_GET_SIZE(source)
        src = self._source_infos + source_location
        src.buf = c_source
        src.size = c_source_size

        src.agg_offset = self._source_offset + unadded_bytes
        self._source_offset = src.agg_offset + src.size
        # We delay creating the index on the first insert
        if source_location != 0:
            with nogil:
                res = create_delta_index(src, self._index, &index,
                                         self._max_bytes_to_index)
            if res != DELTA_OK:
                raise _translate_delta_failure(res)
            if index != self._index:
                free_delta_index(self._index)
                self._index = index

    cdef _populate_first_index(self):
        cdef delta_index *index
        cdef delta_result res
        if len(self._sources) != 1 or self._index != NULL:
            raise AssertionError('_populate_first_index should only be'
                ' called when we have a single source and no index yet')

        # We know that self._index is already NULL, so create_delta_index
        # will always create a new index unless there's a malloc failure
        with nogil:
            res = create_delta_index(&self._source_infos[0], NULL, &index,
                                     self._max_bytes_to_index)
        if res != DELTA_OK:
            raise _translate_delta_failure(res)
        self._index = index

    cdef _expand_sources(self):
        raise RuntimeError('if we move self._source_infos, then we need to'
                           ' change all of the index pointers as well.')

    def make_delta(self, target_bytes, max_delta_size=0):
        """Create a delta from the current source to the target bytes."""
        cdef char *target
        cdef Py_ssize_t target_size
        cdef void * delta
        cdef unsigned long delta_size
        cdef unsigned long c_max_delta_size
        cdef delta_result res

        if self._index == NULL:
            if len(self._sources) == 0:
                return None
            # We were just lazy about generating the index
            self._populate_first_index()

        if not PyBytes_CheckExact(target_bytes):
            raise TypeError('target is not a bytestring')

        target = PyBytes_AS_STRING(target_bytes)
        target_size = PyBytes_GET_SIZE(target_bytes)

        # TODO: inline some of create_delta so we at least don't have to double
        #       malloc, and can instead use PyBytes_FromStringAndSize, to
        #       allocate the bytes into the final string
        c_max_delta_size = max_delta_size
        with nogil:
            res = create_delta(self._index, target, target_size,
                               &delta_size, c_max_delta_size, &delta)
        result = None
        if res == DELTA_OK:
            result = PyBytes_FromStringAndSize(<char *>delta, delta_size)
            free(delta)
        elif res != DELTA_SIZE_TOO_BIG:
            raise _translate_delta_failure(res)
        return result


def make_delta(source_bytes, target_bytes):
    """Create a delta, this is a wrapper around DeltaIndex.make_delta."""
    di = DeltaIndex(source_bytes)
    return di.make_delta(target_bytes)
