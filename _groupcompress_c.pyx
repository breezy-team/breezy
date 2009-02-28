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
    void * diff_delta(void *src_buf, unsigned long src_bufsize,
           void *trg_buf, unsigned long trg_bufsize,
           unsigned long *delta_size, unsigned long max_delta_size)
    struct delta_index:
        unsigned long memsize
        void *src_buf
        unsigned long src_size
        unsigned int hash_mask
        # struct index_entry *hash[]
    delta_index * create_delta_index(void *buf, unsigned long bufsize)
    void free_delta_index(delta_index *index)
    void * create_delta(delta_index *index,
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


# cdef void *safe_malloc(size_t count) except NULL:
#     cdef void *result
#     result = malloc(count)
#     if result == NULL:
#         raise MemoryError('Failed to allocate %d bytes of memory' % (count,))
#     return result
# 
# 
# cdef void *safe_realloc(void * old, size_t count) except NULL:
#     cdef void *result
#     result = realloc(old, count)
#     if result == NULL:
#         raise MemoryError('Failed to reallocate to %d bytes of memory'
#                           % (count,))
#     return result
# 
# 
# cdef int safe_free(void **val) except -1:
#     assert val != NULL
#     if val[0] != NULL:
#         free(val[0])
#         val[0] = NULL

cdef class DeltaIndex:

    cdef object _source
    cdef delta_index *_index

    def __repr__(self):
        if self._index == NULL:
            return '%s(NULL)' % (self.__class__.__name__,)
        return '%s(%d)' % (self.__class__.__name__,
            len(self._source))

    def __init__(self, source):
        self._source = None
        self._index = NULL

        self._create_delta_index(source)

    def _create_delta_index(self, source):
        cdef char *c_source
        cdef Py_ssize_t c_source_size

        if not PyString_CheckExact(source):
            raise TypeError('source is not a str')

        self._source = source
        c_source = PyString_AS_STRING(source)
        c_source_size = PyString_GET_SIZE(source)

        # TODO: Are usage is ultimately going to be different than the one that
        #       was originally designed. Specifically, we are going to want to
        #       be able to update the index by hashing future data. It should
        #       fit just fine into the structure. But for now, we just wrap
        #       create_delta_index (For example, we could always reserve enough
        #       space to hash a 4MB string, etc.)
        self._index = create_delta_index(c_source, c_source_size)
        # TODO: Handle if _index == NULL

    cdef _ensure_no_index(self):
        if self._index != NULL:
            free_delta_index(self._index)
            self._index = NULL

    def __dealloc__(self):
        self._ensure_no_index()

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
        delta = create_delta(self._index, target, target_size,
                             &delta_size, max_delta_size)
        result = None
        if delta:
            result = PyString_FromStringAndSize(<char *>delta, delta_size)
            free(delta)
        return result


def make_delta(source_bytes, target_bytes):
    """Create a delta from source_bytes => target_bytes."""
    cdef char *source
    cdef Py_ssize_t source_size
    cdef char *target
    cdef Py_ssize_t target_size
    cdef delta_index *index
    cdef void * delta
    cdef unsigned long delta_size
    cdef unsigned long max_delta_size

    max_delta_size = 0 # Unlimited

    if not PyString_CheckExact(source_bytes):
        raise TypeError('source is not a str')
    if not PyString_CheckExact(target_bytes):
        raise TypeError('target is not a str')

    source = PyString_AS_STRING(source_bytes)
    source_size = PyString_GET_SIZE(source_bytes)
    target = PyString_AS_STRING(target_bytes)
    target_size = PyString_GET_SIZE(target_bytes)

    result = None
    index = create_delta_index(source, source_size)
    if index != NULL:
        delta = create_delta(index, target, target_size,
                             &delta_size, max_delta_size)
        free_delta_index(index);
        if delta:
            result = PyString_FromStringAndSize(<char *>delta, delta_size)
            free(delta)
    return result


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
        return None

    data = <unsigned char *>delta
    top = data + delta_size

    # make sure the orig file size matches what we expect
    # XXX: gcc warns because data isn't defined as 'const'
    size = get_delta_hdr_size(&data, top)
    if (size > source_size):
        # XXX: mismatched source size
        return None
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
                cp_off |= (data[0] << 8)
                data = data + 1
            if (cmd & 0x04):
                cp_off |= (data[0] << 16)
                data = data + 1
            if (cmd & 0x08):
                cp_off |= (data[0] << 24)
                data[0] += 1
            if (cmd & 0x10):
                cp_size = data[0]
                data = data + 1
            if (cmd & 0x20):
                cp_size |= (data[0] << 8)
                data = data + 1
            if (cmd & 0x40):
                cp_size |= (data[0] << 16)
                data = data + 1
            if (cp_size == 0):
                cp_size = 0x10000
            if (cp_off + cp_size < cp_size or
                cp_off + cp_size > source_size or
                cp_size > size):
                break
            memcpy(out, source + cp_off, cp_size)
            out = out + cp_size
            size -= cp_size
        elif (cmd):
            if (cmd > size):
                break
            memcpy(out, data, cmd)
            out = out + cmd
            data = data + cmd
            size -= cmd
        else:
            # /*
            #  * cmd == 0 is reserved for future encoding
            #  * extensions. In the mean time we must fail when
            #  * encountering them (might be data corruption).
            #  */
            ## /* XXX: error("unexpected delta opcode 0"); */
            return None

    # /* sanity check */
    if (data != top or size != 0):
        ## /* XXX: error("delta replay has gone wild"); */
        return None

    # *dst_size = out - dst_buf;
    assert (out - dst_buf) == PyString_GET_SIZE(result)
    return result


def apply_delta2(source_bytes, delta_bytes):
    """Apply a delta generated by make_delta to source_bytes."""
    # This defers to the patch-delta code rather than implementing it here
    # If this is faster, we can bring the memory allocation and error handling
    # into apply_delta(), and leave the primary loop in a separate C func.
    cdef char *source, *delta, *target
    cdef Py_ssize_t source_size, delta_size
    cdef unsigned long target_size

    if not PyString_CheckExact(source_bytes):
        raise TypeError('source is not a str')
    if not PyString_CheckExact(delta_bytes):
        raise TypeError('delta is not a str')

    source = PyString_AS_STRING(source_bytes)
    source_size = PyString_GET_SIZE(source_bytes)
    delta = PyString_AS_STRING(delta_bytes)
    delta_size = PyString_GET_SIZE(delta_bytes)

    target = <char *>patch_delta(source, source_size,
                                 delta, delta_size,
                                 &target_size)
    if target == NULL:
        return None
    result = PyString_FromStringAndSize(target, target_size)
    free(target)
    return result
