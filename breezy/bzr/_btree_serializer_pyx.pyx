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

"""Pyrex extensions to btree node parsing."""


cdef extern from "python-compat.h":
    pass

from cpython.bytes cimport (PyBytes_AS_STRING, PyBytes_AsString,
                            PyBytes_CheckExact, PyBytes_FromFormat,
                            PyBytes_FromStringAndSize, PyBytes_GET_SIZE,
                            PyBytes_Size)
from cpython.list cimport PyList_Append
from cpython.mem cimport PyMem_Free, PyMem_Malloc
from cpython.object cimport PyObject
from cpython.ref cimport Py_INCREF
from cpython.tuple cimport (PyTuple_CheckExact, PyTuple_GET_ITEM,
                            PyTuple_GET_SIZE, PyTuple_New, PyTuple_SET_ITEM)
from libc.stdlib cimport strtoul, strtoull
from libc.string cimport memchr, memcmp, memcpy, strncmp

from ._str_helpers cimport (_my_memrchr, safe_interned_string_from_size,
                            safe_string_from_size)

import sys


cdef class BTreeLeafParser:
    """Parse the leaf nodes of a BTree index.

    :ivar data: The PyBytes object containing the uncompressed text for the
        node.
    :ivar key_length: An integer describing how many pieces the keys have for
        this index.
    :ivar ref_list_length: An integer describing how many references this index
        contains.
    :ivar keys: A PyList of keys found in this node.

    :ivar _cur_str: A pointer to the start of the next line to parse
    :ivar _end_str: A pointer to the end of bytes
    :ivar _start: Pointer to the location within the current line while
        parsing.
    :ivar _header_found: True when we have parsed the header for this node
    """

    cdef object data
    cdef int key_length
    cdef int ref_list_length
    cdef object keys

    cdef char * _cur_str
    cdef char * _end_str
    # The current start point for parsing
    cdef char * _start

    cdef int _header_found

    def __init__(self, data, key_length, ref_list_length):
        self.data = data
        self.key_length = key_length
        self.ref_list_length = ref_list_length
        self.keys = []
        self._cur_str = NULL
        self._end_str = NULL
        self._header_found = 0
        # keys are tuples

    cdef extract_key(self, char * last):
        """Extract a key.

        :param last: points at the byte after the last byte permitted for the
            key.
        """
        cdef char *temp_ptr
        cdef int loop_counter
        cdef tuple key

        key = PyTuple_New(self.key_length)
        for loop_counter from 0 <= loop_counter < self.key_length:
            # grab a key segment
            temp_ptr = <char*>memchr(self._start, c'\0', last - self._start)
            if temp_ptr == NULL:
                if loop_counter + 1 == self.key_length:
                    # capture to last
                    temp_ptr = last
                else:
                    # Invalid line
                    failure_string = ("invalid key, wanted segment from " +
                        repr(safe_string_from_size(self._start,
                                                   last - self._start)))
                    raise AssertionError(failure_string)
            # capture the key string
            if (self.key_length == 1
                and (temp_ptr - self._start) == 45
                and strncmp(self._start, b'sha1:', 5) == 0):
                key_element = safe_string_from_size(self._start,
                                                    temp_ptr - self._start)
            else:
                key_element = safe_interned_string_from_size(self._start,
                                                         temp_ptr - self._start)
            # advance our pointer
            self._start = temp_ptr + 1
            Py_INCREF(key_element)
            PyTuple_SET_ITEM(key, loop_counter, key_element)
        return key

    cdef int process_line(self) except -1:
        """Process a line in the bytes."""
        cdef char *last
        cdef char *temp_ptr
        cdef char *ref_ptr
        cdef char *next_start
        cdef int loop_counter
        cdef Py_ssize_t str_len

        self._start = self._cur_str
        # Find the next newline
        last = <char*>memchr(self._start, c'\n', self._end_str - self._start)
        if last == NULL:
            # Process until the end of the file
            last = self._end_str
            self._cur_str = self._end_str
        else:
            # And the next string is right after it
            self._cur_str = last + 1
            # The last character is right before the '\n'

        if last == self._start:
            # parsed it all.
            return 0
        if last < self._start:
            # Unexpected error condition - fail
            raise AssertionError("last < self._start")
        if 0 == self._header_found:
            # The first line in a leaf node is the header "type=leaf\n"
            if strncmp(b"type=leaf", self._start, last - self._start) == 0:
                self._header_found = 1
                return 0
            else:
                raise AssertionError('Node did not start with "type=leaf": %r'
                    % (safe_string_from_size(self._start, last - self._start)))

        key = self.extract_key(last)
        # find the value area
        temp_ptr = <char*>_my_memrchr(self._start, c'\0', last - self._start)
        if temp_ptr == NULL:
            # Invalid line
            raise AssertionError("Failed to find the value area")
        else:
            # Because of how conversions were done, we ended up with *lots* of
            # values that are identical. These are all of the 0-length nodes
            # that are referred to by the TREE_ROOT (and likely some other
            # directory nodes.) For example, bzr has 25k references to
            # something like '12607215 328306 0 0', which ends up consuming 1MB
            # of memory, just for those strings.
            str_len = last - temp_ptr - 1
            if (str_len > 4
                and strncmp(b" 0 0", last - 4, 4) == 0):
                # This drops peak mem for bzr.dev from 87.4MB => 86.2MB
                # For Launchpad 236MB => 232MB
                value = safe_interned_string_from_size(temp_ptr + 1, str_len)
            else:
                value = safe_string_from_size(temp_ptr + 1, str_len)
            # shrink the references end point
            last = temp_ptr

        if self.ref_list_length:
            ref_lists = PyTuple_New(self.ref_list_length)
            loop_counter = 0
            while loop_counter < self.ref_list_length:
                ref_list = []
                # extract a reference list
                loop_counter = loop_counter + 1
                if last < self._start:
                    raise AssertionError("last < self._start")
                # find the next reference list end point:
                temp_ptr = <char*>memchr(self._start, c'\t', last - self._start)
                if temp_ptr == NULL:
                    # Only valid for the last list
                    if loop_counter != self.ref_list_length:
                        # Invalid line
                        raise AssertionError(
                            "invalid key, loop_counter != self.ref_list_length")
                    else:
                        # scan to the end of the ref list area
                        ref_ptr = last
                        next_start = last
                else:
                    # scan to the end of this ref list
                    ref_ptr = temp_ptr
                    next_start = temp_ptr + 1
                # Now, there may be multiple keys in the ref list.
                while self._start < ref_ptr:
                    # loop finding keys and extracting them
                    temp_ptr = <char*>memchr(self._start, c'\r',
                                             ref_ptr - self._start)
                    if temp_ptr == NULL:
                        # key runs to the end
                        temp_ptr = ref_ptr

                    PyList_Append(ref_list, self.extract_key(temp_ptr))
                ref_list = tuple(ref_list)
                Py_INCREF(ref_list)
                PyTuple_SET_ITEM(ref_lists, loop_counter - 1, ref_list)
                # prepare for the next reference list
                self._start = next_start
            node_value = (value, ref_lists)
        else:
            if last != self._start:
                # unexpected reference data present
                raise AssertionError("unexpected reference data present")
            node_value = (value, ())
        PyList_Append(self.keys, (key, node_value))
        return 0

    def parse(self):
        cdef Py_ssize_t byte_count
        if not PyBytes_CheckExact(self.data):
            raise AssertionError('self.data is not a byte string.')
        byte_count = PyBytes_GET_SIZE(self.data)
        self._cur_str = PyBytes_AS_STRING(self.data)
        # This points to the last character in the string
        self._end_str = self._cur_str + byte_count
        while self._cur_str < self._end_str:
            self.process_line()
        return self.keys


def _parse_leaf_lines(data, key_length, ref_list_length):
    parser = BTreeLeafParser(data, key_length, ref_list_length)
    return parser.parse()


# TODO: We can go from 8 byte offset + 4 byte length to a simple lookup,
#       because the block_offset + length is likely to be repeated. However,
#       the big win there is to cache across pages, and not just one page
#       Though if we did cache in a page, we could certainly use a short int.
#       And this goes from 40 bytes to 30 bytes.
#       One slightly ugly option would be to cache block offsets in a global.
#       However, that leads to thread-safety issues, etc.
ctypedef struct gc_chk_sha1_record:
    unsigned long long block_offset
    unsigned int block_length
    unsigned int record_start
    unsigned int record_end
    char sha1[20]


cdef int _unhexbuf[256]
cdef char *_hexbuf
_hexbuf = b'0123456789abcdef'

cdef _populate_unhexbuf():
    cdef int i
    for i from 0 <= i < 256:
        _unhexbuf[i] = -1
    for i from 0 <= i < 10: # 0123456789 => map to the raw number
        _unhexbuf[(i + c'0')] = i
    for i from 10 <= i < 16: # abcdef => 10, 11, 12, 13, 14, 15, 16
        _unhexbuf[(i - 10 + c'a')] = i
    for i from 10 <= i < 16: # ABCDEF => 10, 11, 12, 13, 14, 15, 16
        _unhexbuf[(i - 10 + c'A')] = i
_populate_unhexbuf()


cdef int _unhexlify_sha1(char *as_hex, char *as_bin): # cannot_raise
    """Take the hex sha1 in as_hex and make it binary in as_bin

    Same as binascii.unhexlify, but working on C strings, not Python objects.
    """
    cdef int top
    cdef int bot
    cdef int i, j
    cdef char *cur

    # binascii does this using isupper() and tolower() and ?: syntax. I'm
    # guessing a simple lookup array should be faster.
    j = 0
    for i from 0 <= i < 20:
        top = _unhexbuf[<unsigned char>(as_hex[j])]
        j = j + 1
        bot = _unhexbuf[<unsigned char>(as_hex[j])]
        j = j + 1
        if top == -1 or bot == -1:
            return 0
        as_bin[i] = <unsigned char>((top << 4) + bot);
    return 1


def _py_unhexlify(as_hex):
    """For the test infrastructure, just thunks to _unhexlify_sha1"""
    if not PyBytes_CheckExact(as_hex) or PyBytes_GET_SIZE(as_hex) != 40:
        raise ValueError('not a 40-byte hex digest')
    as_bin = PyBytes_FromStringAndSize(NULL, 20)
    if _unhexlify_sha1(PyBytes_AS_STRING(as_hex), PyBytes_AS_STRING(as_bin)):
        return as_bin
    return None


cdef void _hexlify_sha1(char *as_bin, char *as_hex): # cannot_raise
    cdef int i, j
    cdef char c

    j = 0
    for i from 0 <= i < 20:
        c = as_bin[i]
        as_hex[j] = _hexbuf[(c>>4)&0xf]
        j = j + 1
        as_hex[j] = _hexbuf[(c)&0xf]
        j = j + 1


def _py_hexlify(as_bin):
    """For test infrastructure, thunk to _hexlify_sha1"""
    if len(as_bin) != 20 or not PyBytes_CheckExact(as_bin):
        raise ValueError('not a 20-byte binary digest')
    as_hex = PyBytes_FromStringAndSize(NULL, 40)
    _hexlify_sha1(PyBytes_AS_STRING(as_bin), PyBytes_AS_STRING(as_hex))
    return as_hex


cdef int _key_to_sha1(key, char *sha1): # cannot_raise
    """Map a key into its sha1 content.

    :param key: A tuple of style ('sha1:abcd...',)
    :param sha1: A char buffer of 20 bytes
    :return: 1 if this could be converted, 0 otherwise
    """
    cdef char *c_val
    cdef PyObject *p_val

    if PyTuple_CheckExact(key) and PyTuple_GET_SIZE(key) == 1:
        p_val = <PyObject *>PyTuple_GET_ITEM(key, 0)
    else:
        # Not a tuple or a PyTuple
        return 0
    if (PyBytes_CheckExact(<object>p_val)
            and PyBytes_GET_SIZE(<object>p_val) == 45):
        c_val = PyBytes_AS_STRING(<object>p_val)
    else:
        return 0
    if strncmp(c_val, b'sha1:', 5) != 0:
        return 0
    if not _unhexlify_sha1(c_val + 5, sha1):
        return 0
    return 1


def _py_key_to_sha1(key):
    """Map a key to a simple sha1 string.

    This is a testing thunk to the C function.
    """
    as_bin_sha = PyBytes_FromStringAndSize(NULL, 20)
    if _key_to_sha1(key, PyBytes_AS_STRING(as_bin_sha)):
        return as_bin_sha
    return None


cdef tuple _sha1_to_key(char *sha1):
    """Compute a ('sha1:abcd',) key for a given sha1."""
    cdef tuple key
    cdef object hexxed
    cdef char *c_buf
    hexxed = PyBytes_FromStringAndSize(NULL, 45)
    c_buf = PyBytes_AS_STRING(hexxed)
    memcpy(c_buf, b'sha1:', 5)
    _hexlify_sha1(sha1, c_buf+5)
    key = PyTuple_New(1)
    Py_INCREF(hexxed)
    PyTuple_SET_ITEM(key, 0, hexxed)
    # This is a bit expensive. To parse 120 keys takes 48us, to return them all
    # can be done in 66.6us (so 18.6us to build them all).
    # Adding simple hash() here brings it to 76.6us (so computing the hash
    # value of 120keys is 10us), Intern is 86.9us (another 10us to look and add
    # them to the intern structure.)
    # However, since we only intern keys that are in active use, it is probably
    # a win. Since they would have been read from elsewhere anyway.
    # We *could* hang the PyObject form off of the gc_chk_sha1_record for ones
    # that we have deserialized. Something to think about, at least.
    return key


def _py_sha1_to_key(sha1_bin):
    """Test thunk to check the sha1 mapping."""
    if not PyBytes_CheckExact(sha1_bin) or PyBytes_GET_SIZE(sha1_bin) != 20:
        raise ValueError('sha1_bin must be a str of exactly 20 bytes')
    return _sha1_to_key(PyBytes_AS_STRING(sha1_bin))


cdef unsigned int _sha1_to_uint(char *sha1): # cannot_raise
    cdef unsigned int val
    # Must be in MSB, because that is how the content is sorted
    val = (((<unsigned int>(sha1[0]) & 0xff) << 24)
           | ((<unsigned int>(sha1[1]) & 0xff) << 16)
           | ((<unsigned int>(sha1[2]) & 0xff) << 8)
           | ((<unsigned int>(sha1[3]) & 0xff) << 0))
    return val


cdef _format_record(gc_chk_sha1_record *record):
    # This is inefficient to go from a logical state back to a bytes object,
    # but it makes things work a bit better internally for now.
    if record.block_offset >= 0xFFFFFFFF:
        # Could use %llu which was added to Python 2.7 but it oddly is missing
        # from the Python 3 equivalent functions, so hack still needed. :(
        block_offset_str = b'%d' % record.block_offset
        value = PyBytes_FromFormat(
            '%s %u %u %u', PyBytes_AS_STRING(block_offset_str),
            record.block_length, record.record_start, record.record_end)
    else:
        value = PyBytes_FromFormat(
            '%lu %u %u %u', <unsigned long>record.block_offset,
            record.block_length, record.record_start, record.record_end)
    return value


cdef class GCCHKSHA1LeafNode:
    """Track all the entries for a given leaf node."""

    cdef gc_chk_sha1_record *records
    cdef public object last_key
    cdef gc_chk_sha1_record *last_record
    cdef public int num_records
    # This is the number of bits to shift to get to the interesting byte. A
    # value of 24 means that the very first byte changes across all keys.
    # Anything else means that there is a common prefix of bits that we can
    # ignore. 0 means that at least the first 3 bytes are identical, though
    # that is going to be very rare
    cdef public unsigned char common_shift
    # This maps an interesting byte to the first record that matches.
    # Equivalent to bisect.bisect_left(self.records, sha1), though only taking
    # into account that one byte.
    cdef unsigned char offsets[257]

    def __sizeof__(self):
        return (
            sizeof(GCCHKSHA1LeafNode) +
            sizeof(gc_chk_sha1_record) * self.num_records)

    def __dealloc__(self):
        if self.records != NULL:
            PyMem_Free(self.records)
            self.records = NULL

    def __init__(self, bytes):
        self._parse_bytes(bytes)
        self.last_key = None
        self.last_record = NULL

    property min_key:
        def __get__(self):
            if self.num_records > 0:
                return _sha1_to_key(self.records[0].sha1)
            return None

    property max_key:
        def __get__(self):
            if self.num_records > 0:
                return _sha1_to_key(self.records[self.num_records-1].sha1)
            return None

    cdef tuple _record_to_value_and_refs(self,
                                               gc_chk_sha1_record *record):
        """Extract the refs and value part of this record."""
        cdef tuple value_and_refs
        cdef tuple empty
        value_and_refs = PyTuple_New(2)
        value = _format_record(record)
        Py_INCREF(value)
        PyTuple_SET_ITEM(value_and_refs, 0, value)
        # Always empty refs
        empty = PyTuple_New(0)
        Py_INCREF(empty)
        PyTuple_SET_ITEM(value_and_refs, 1, empty)
        return value_and_refs

    cdef tuple _record_to_item(self, gc_chk_sha1_record *record):
        """Turn a given record back into a fully fledged item.
        """
        cdef tuple item
        cdef tuple key
        cdef tuple value_and_refs
        cdef object value
        key = _sha1_to_key(record.sha1)
        item = PyTuple_New(2)
        Py_INCREF(key)
        PyTuple_SET_ITEM(item, 0, key)
        value_and_refs = self._record_to_value_and_refs(record)
        Py_INCREF(value_and_refs)
        PyTuple_SET_ITEM(item, 1, value_and_refs)
        return item

    cdef gc_chk_sha1_record* _lookup_record(self, char *sha1) except? NULL:
        """Find a gc_chk_sha1_record that matches the sha1 supplied."""
        cdef int lo, hi, mid, the_cmp
        cdef int offset

        # TODO: We can speed up misses by comparing this sha1 to the common
        #       bits, and seeing if the common prefix matches, if not, we don't
        #       need to search for anything because it cannot match
        # Use the offset array to find the closest fit for this entry
        # follow that up with bisecting, since multiple keys can be in one
        # spot
        # Bisecting dropped us from 7000 comparisons to 582 (4.8/key), using
        # the offset array dropped us from 23us to 20us and 156 comparisions
        # (1.3/key)
        offset = self._offset_for_sha1(sha1)
        lo = self.offsets[offset]
        hi = self.offsets[offset+1]
        if hi == 255:
            # if hi == 255 that means we potentially ran off the end of the
            # list, so push it up to num_records
            # note that if 'lo' == 255, that is ok, because we can start
            # searching from that part of the list.
            hi = self.num_records
        local_n_cmp = 0
        while lo < hi:
            mid = (lo + hi) // 2
            the_cmp = memcmp(self.records[mid].sha1, sha1, 20)
            if the_cmp == 0:
                return &self.records[mid]
            elif the_cmp < 0:
                lo = mid + 1
            else:
                hi = mid
        return NULL

    def __contains__(self, key):
        cdef char sha1[20]
        cdef gc_chk_sha1_record *record
        if _key_to_sha1(key, sha1):
            # If it isn't a sha1 key, then it won't be in this leaf node
            record = self._lookup_record(sha1)
            if record != NULL:
                self.last_key = key
                self.last_record = record
                return True
        return False

    def __getitem__(self, key):
        cdef char sha1[20]
        cdef gc_chk_sha1_record *record
        record = NULL
        if self.last_record != NULL and key is self.last_key:
            record = self.last_record
        elif _key_to_sha1(key, sha1):
            record = self._lookup_record(sha1)
        if record == NULL:
            raise KeyError('key %r is not present' % (key,))
        return self._record_to_value_and_refs(record)

    def __len__(self):
        return self.num_records

    def all_keys(self):
        cdef int i
        result = []
        for i from 0 <= i < self.num_records:
            PyList_Append(result, _sha1_to_key(self.records[i].sha1))
        return result

    def all_items(self):
        cdef int i
        result = []
        for i from 0 <= i < self.num_records:
            item = self._record_to_item(&self.records[i])
            PyList_Append(result, item)
        return result

    cdef int _count_records(self, char *c_content, char *c_end): # cannot_raise
        """Count how many records are in this section."""
        cdef char *c_cur
        cdef int num_records

        c_cur = c_content
        num_records = 0
        while c_cur != NULL and c_cur < c_end:
            c_cur = <char *>memchr(c_cur, c'\n', c_end - c_cur);
            if c_cur == NULL:
                break
            c_cur = c_cur + 1
            num_records = num_records + 1
        return num_records

    cdef _parse_bytes(self, data):
        """Parse the bytes 'data' into content."""
        cdef char *c_bytes
        cdef char *c_cur
        cdef char *c_end
        cdef Py_ssize_t n_bytes
        cdef int num_records
        cdef int entry
        cdef gc_chk_sha1_record *cur_record

        if not PyBytes_CheckExact(data):
            raise TypeError('We only support parsing byte strings.')
        # Pass 1, count how many records there will be
        n_bytes = PyBytes_GET_SIZE(data)
        c_bytes = PyBytes_AS_STRING(data)
        c_end = c_bytes + n_bytes
        if strncmp(c_bytes, b'type=leaf\n', 10):
            raise ValueError("bytes did not start with 'type=leaf\\n': %r"
                             % (data[:10],))
        c_cur = c_bytes + 10
        num_records = self._count_records(c_cur, c_end)
        # Now allocate the memory for these items, and go to town
        self.records = <gc_chk_sha1_record*>PyMem_Malloc(num_records *
            (sizeof(unsigned short) + sizeof(gc_chk_sha1_record)))
        self.num_records = num_records
        cur_record = self.records
        entry = 0
        while c_cur != NULL and c_cur < c_end and entry < num_records:
            c_cur = self._parse_one_entry(c_cur, c_end, cur_record)
            cur_record = cur_record + 1
            entry = entry + 1
        if (entry != self.num_records
            or c_cur != c_end
            or cur_record != self.records + self.num_records):
            raise ValueError('Something went wrong while parsing.')
        # Pass 3: build the offset map
        self._compute_common()

    cdef char *_parse_one_entry(self, char *c_cur, char *c_end,
                                gc_chk_sha1_record *cur_record) except NULL:
        """Read a single sha record from the bytes.

        :param c_cur: The pointer to the start of bytes
        :param cur_record: Record to populate
        """
        cdef char *c_next
        if strncmp(c_cur, 'sha1:', 5):
            raise ValueError('line did not start with sha1: %r'
                % (safe_string_from_size(c_cur, 10),))
        c_cur = c_cur + 5
        c_next = <char *>memchr(c_cur, c'\0', c_end - c_cur)
        if c_next == NULL or (c_next - c_cur != 40):
            raise ValueError('Line did not contain 40 hex bytes')
        if not _unhexlify_sha1(c_cur, cur_record.sha1):
            raise ValueError('We failed to unhexlify')
        c_cur = c_next + 1
        if c_cur[0] != c'\0':
            raise ValueError('only 1 null, not 2 as expected')
        c_cur = c_cur + 1
        cur_record.block_offset = strtoull(c_cur, &c_next, 10)
        if c_cur == c_next or c_next[0] != c' ':
            raise ValueError('Failed to parse block offset')
        c_cur = c_next + 1
        cur_record.block_length = strtoul(c_cur, &c_next, 10)
        if c_cur == c_next or c_next[0] != c' ':
            raise ValueError('Failed to parse block length')
        c_cur = c_next + 1
        cur_record.record_start = strtoul(c_cur, &c_next, 10)
        if c_cur == c_next or c_next[0] != c' ':
            raise ValueError('Failed to parse block length')
        c_cur = c_next + 1
        cur_record.record_end = strtoul(c_cur, &c_next, 10)
        if c_cur == c_next or c_next[0] != c'\n':
            raise ValueError('Failed to parse record end')
        c_cur = c_next + 1
        return c_cur

    cdef int _offset_for_sha1(self, char *sha1) except -1:
        """Find the first interesting 8-bits of this sha1."""
        cdef int this_offset
        cdef unsigned int as_uint
        as_uint = _sha1_to_uint(sha1)
        this_offset = (as_uint >> self.common_shift) & 0xFF
        return this_offset

    def _get_offset_for_sha1(self, sha1):
        return self._offset_for_sha1(PyBytes_AS_STRING(sha1))

    cdef _compute_common(self):
        cdef unsigned int first
        cdef unsigned int this
        cdef unsigned int common_mask
        cdef unsigned char common_shift
        cdef int i
        cdef int offset, this_offset
        cdef int max_offset
        # The idea with the offset map is that we should be able to quickly
        # jump to the key that matches a gives sha1. We know that the keys are
        # in sorted order, and we know that a lot of the prefix is going to be
        # the same across them.
        # By XORing the records together, we can determine what bits are set in
        # all of them
        if self.num_records < 2:
            # Everything is in common if you have 0 or 1 leaves
            # So we'll always just shift to the first byte
            self.common_shift = 24
        else:
            common_mask = 0xFFFFFFFF
            first = _sha1_to_uint(self.records[0].sha1)
            for i from 0 < i < self.num_records:
                this = _sha1_to_uint(self.records[i].sha1)
                common_mask = (~(first ^ this)) & common_mask
            common_shift = 24
            while common_mask & 0x80000000 and common_shift > 0:
                common_mask = common_mask << 1
                common_shift = common_shift - 1
            self.common_shift = common_shift
        offset = 0
        max_offset = self.num_records
        # We cap this loop at 254 records. All the other offsets just get
        # filled with 0xff as the singleton saying 'too many'.
        # It means that if we have >255 records we have to bisect the second
        # half of the list, but this is going to be very rare in practice.
        if max_offset > 255:
            max_offset = 255
        for i from 0 <= i < max_offset:
            this_offset = self._offset_for_sha1(self.records[i].sha1)
            while offset <= this_offset:
                self.offsets[offset] = i
                offset = offset + 1
        while offset < 257:
            self.offsets[offset] = max_offset
            offset = offset + 1

    def _get_offsets(self):
        cdef int i
        result = []
        for i from 0 <= i < 257:
            PyList_Append(result, self.offsets[i])
        return result


def _parse_into_chk(bytes, key_length, ref_list_length):
    """Parse into a format optimized for chk records."""
    assert key_length == 1
    assert ref_list_length == 0
    return GCCHKSHA1LeafNode(bytes)


def _flatten_node(node, reference_lists):
    """Convert a node into the serialized form.

    :param node: A tuple representing a node:
        (index, key_tuple, value, references)
    :param reference_lists: Does this index have reference lists?
    :return: (string_key, flattened)
        string_key  The serialized key for referencing this node
        flattened   A string with the serialized form for the contents
    """
    cdef int have_reference_lists
    cdef Py_ssize_t flat_len
    cdef Py_ssize_t key_len
    cdef Py_ssize_t node_len
    cdef char * value
    cdef Py_ssize_t value_len
    cdef char * out
    cdef Py_ssize_t refs_len
    cdef Py_ssize_t next_len
    cdef int first_ref_list
    cdef int first_reference
    cdef int i
    cdef Py_ssize_t ref_bit_len

    if not PyTuple_CheckExact(node):
        raise TypeError('We expected a tuple() for node not: %s'
            % type(node))
    node_len = len(node)
    have_reference_lists = reference_lists
    if have_reference_lists:
        if node_len != 4:
            raise ValueError('With ref_lists, we expected 4 entries not: %s'
                % len(node))
    elif node_len < 3:
        raise ValueError('Without ref_lists, we need at least 3 entries not: %s'
            % len(node))
    # TODO: We can probably do better than string.join(), namely
    #       when key has only 1 item, we can just grab that string
    #       And when there are 2 items, we could do a single malloc + len() + 1
    #       also, doing .join() requires a PyObject_GetAttrString call, which
    #       we could also avoid.
    # TODO: Note that pyrex 0.9.6 generates fairly crummy code here, using the
    #       python object interface, versus 0.9.8+ which uses a helper that
    #       checks if this supports the sequence interface.
    #       We *could* do more work on our own, and grab the actual items
    #       lists. For now, just ask people to use a better compiler. :)
    string_key = b'\0'.join(node[1])

    # TODO: instead of using string joins, precompute the final string length,
    #       and then malloc a single string and copy everything in.

    # TODO: We probably want to use PySequenceFast, because we have lists and
    #       tuples, but we aren't sure which we will get.

    # line := string_key NULL flat_refs NULL value LF
    # string_key := BYTES (NULL BYTES)*
    # flat_refs := ref_list (TAB ref_list)*
    # ref_list := ref (CR ref)*
    # ref := BYTES (NULL BYTES)*
    # value := BYTES
    refs_len = 0
    if have_reference_lists:
        # Figure out how many bytes it will take to store the references
        ref_lists = node[3]
        next_len = len(ref_lists) # TODO: use a Py function
        if next_len > 0:
            # If there are no nodes, we don't need to do any work
            # Otherwise we will need (len - 1) '\t' characters to separate
            # the reference lists
            refs_len = refs_len + (next_len - 1)
            for ref_list in ref_lists:
                next_len = len(ref_list)
                if next_len > 0:
                    # We will need (len - 1) '\r' characters to separate the
                    # references
                    refs_len = refs_len + (next_len - 1)
                    for reference in ref_list:
                        if not PyTuple_CheckExact(reference):
                            raise TypeError(
                                'We expect references to be tuples not: %r'
                                % type(reference))
                        next_len = len(reference)
                        if next_len > 0:
                            # We will need (len - 1) '\x00' characters to
                            # separate the reference key
                            refs_len = refs_len + (next_len - 1)
                            for ref_bit in reference:
                                if not PyBytes_CheckExact(ref_bit):
                                    raise TypeError(
                                        'We expect reference bits to be bytes'
                                        ' not: %r' % type(ref_bit))
                                refs_len = refs_len + PyBytes_GET_SIZE(ref_bit)

    # So we have the (key NULL refs NULL value LF)
    key_len = PyBytes_Size(string_key)
    val = node[2]
    if not PyBytes_CheckExact(val):
        raise TypeError('Expected bytes for value not: %r' % type(val))
    value = PyBytes_AS_STRING(val)
    value_len = PyBytes_GET_SIZE(val)
    flat_len = (key_len + 1 + refs_len + 1 + value_len + 1)
    line = PyBytes_FromStringAndSize(NULL, flat_len)
    # Get a pointer to the new buffer
    out = PyBytes_AsString(line)
    memcpy(out, PyBytes_AsString(string_key), key_len)
    out = out + key_len
    out[0] = c'\0'
    out = out + 1
    if refs_len > 0:
        first_ref_list = 1
        for ref_list in ref_lists:
            if first_ref_list == 0:
                out[0] = c'\t'
                out = out + 1
            first_ref_list = 0
            first_reference = 1
            for reference in ref_list:
                if first_reference == 0:
                    out[0] = c'\r'
                    out = out + 1
                first_reference = 0
                next_len = len(reference)
                for i from 0 <= i < next_len:
                    if i != 0:
                        out[0] = c'\x00'
                        out = out + 1
                    ref_bit = reference[i]
                    ref_bit_len = PyBytes_GET_SIZE(ref_bit)
                    memcpy(out, PyBytes_AS_STRING(ref_bit), ref_bit_len)
                    out = out + ref_bit_len
    out[0] = c'\0'
    out = out  + 1
    memcpy(out, value, value_len)
    out = out + value_len
    out[0] = c'\n'
    return string_key, line
