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

"""Pyrex extensions to btree node parsing."""

#python2.4 support
cdef extern from "python-compat.h":
    pass

cdef extern from "stdlib.h":
    ctypedef unsigned size_t

cdef extern from "Python.h":
    ctypedef int Py_ssize_t # Required for older pyrex versions
    ctypedef struct PyObject:
        pass
    int PyList_Append(object lst, object item) except -1

    char *PyString_AsString(object p) except NULL
    object PyString_FromStringAndSize(char *, Py_ssize_t)
    PyObject *PyString_FromStringAndSize_ptr "PyString_FromStringAndSize" (char *, Py_ssize_t)
    object PyString_FromFormat(char *, ...)
    int PyString_CheckExact(object s)
    int PyString_CheckExact_ptr "PyString_CheckExact" (PyObject *)
    Py_ssize_t PyString_Size(object p)
    Py_ssize_t PyString_GET_SIZE_ptr "PyString_GET_SIZE" (PyObject *)
    char * PyString_AS_STRING_ptr "PyString_AS_STRING" (PyObject *)
    char * PyString_AS_STRING(object)
    Py_ssize_t PyString_GET_SIZE(object)
    int PyString_AsStringAndSize_ptr(PyObject *, char **buf, Py_ssize_t *len)
    void PyString_InternInPlace(PyObject **)
    int PyTuple_CheckExact(object t)
    object PyTuple_New(Py_ssize_t n_entries)
    void PyTuple_SET_ITEM(object, Py_ssize_t offset, object) # steals the ref
    Py_ssize_t PyTuple_GET_SIZE(object t)
    PyObject *PyTuple_GET_ITEM_ptr_object "PyTuple_GET_ITEM" (object tpl, int index)
    void Py_INCREF(object)
    void Py_DECREF_ptr "Py_DECREF" (PyObject *)
    void *PyMem_Malloc(size_t nbytes)
    void PyMem_Free(void *)
    void memset(void *, int, size_t)

cdef extern from "string.h":
    void *memcpy(void *dest, void *src, size_t n)
    void *memchr(void *s, int c, size_t n)
    int memcmp(void *s1, void *s2, size_t n)
    # GNU extension
    # void *memrchr(void *s, int c, size_t n)
    int strncmp(char *s1, char *s2, size_t n)
    unsigned long strtoul(char *s1, char **out, int base)
    unsigned long long strtoull(char *s1, char **out, int base)

# It seems we need to import the definitions so that the pyrex compiler has
# local names to access them.
from _static_tuple_c cimport StaticTuple, \
    import_static_tuple_c, StaticTuple_New, \
    StaticTuple_Intern, StaticTuple_SET_ITEM, StaticTuple_CheckExact


# TODO: Find some way to import this from _dirstate_helpers
cdef void* _my_memrchr(void *s, int c, size_t n): # cannot_raise
    # memrchr seems to be a GNU extension, so we have to implement it ourselves
    # It is not present in any win32 standard library
    cdef char *pos
    cdef char *start

    start = <char*>s
    pos = start + n - 1
    while pos >= start:
        if pos[0] == c:
            return <void*>pos
        pos = pos - 1
    return NULL


# TODO: Import this from _dirstate_helpers when it is merged
cdef object safe_string_from_size(char *s, Py_ssize_t size):
    if size < 0:
        raise AssertionError(
            'tried to create a string with an invalid size: %d @0x%x'
            % (size, <int>s))
    return PyString_FromStringAndSize(s, size)


cdef object safe_interned_string_from_size(char *s, Py_ssize_t size):
    cdef PyObject *py_str
    if size < 0:
        raise AssertionError(
            'tried to create a string with an invalid size: %d @0x%x'
            % (size, <int>s))
    py_str = PyString_FromStringAndSize_ptr(s, size)
    PyString_InternInPlace(&py_str)
    result = <object>py_str
    # Casting a PyObject* to an <object> triggers an INCREF from Pyrex, so we
    # DECREF it to avoid geting immortal strings
    Py_DECREF_ptr(py_str)
    return result

from bzrlib import _static_tuple_c
# This sets up the StaticTuple C_API functionality
import_static_tuple_c()


cdef class BTreeLeafParser:
    """Parse the leaf nodes of a BTree index.

    :ivar bytes: The PyString object containing the uncompressed text for the
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

    cdef object bytes
    cdef int key_length
    cdef int ref_list_length
    cdef object keys

    cdef char * _cur_str
    cdef char * _end_str
    # The current start point for parsing
    cdef char * _start

    cdef int _header_found

    def __init__(self, bytes, key_length, ref_list_length):
        self.bytes = bytes
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
        cdef StaticTuple key

        key = StaticTuple_New(self.key_length)
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
                and strncmp(self._start, 'sha1:', 5) == 0):
                key_element = safe_string_from_size(self._start,
                                                    temp_ptr - self._start)
            else:
                key_element = safe_interned_string_from_size(self._start,
                                                         temp_ptr - self._start)
            # advance our pointer
            self._start = temp_ptr + 1
            Py_INCREF(key_element)
            StaticTuple_SET_ITEM(key, loop_counter, key_element)
        key = StaticTuple_Intern(key)
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
            if strncmp("type=leaf", self._start, last - self._start) == 0:
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
                and strncmp(" 0 0", last - 4, 4) == 0):
                # This drops peak mem for bzr.dev from 87.4MB => 86.2MB
                # For Launchpad 236MB => 232MB
                value = safe_interned_string_from_size(temp_ptr + 1, str_len)
            else:
                value = safe_string_from_size(temp_ptr + 1, str_len)
            # shrink the references end point
            last = temp_ptr

        if self.ref_list_length:
            ref_lists = StaticTuple_New(self.ref_list_length)
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
                ref_list = StaticTuple_Intern(StaticTuple(*ref_list))
                Py_INCREF(ref_list)
                StaticTuple_SET_ITEM(ref_lists, loop_counter - 1, ref_list)
                # prepare for the next reference list
                self._start = next_start
            node_value = StaticTuple(value, ref_lists)
        else:
            if last != self._start:
                # unexpected reference data present
                raise AssertionError("unexpected reference data present")
            node_value = StaticTuple(value, StaticTuple())
        PyList_Append(self.keys, StaticTuple(key, node_value))
        return 0

    def parse(self):
        cdef Py_ssize_t byte_count
        if not PyString_CheckExact(self.bytes):
            raise AssertionError('self.bytes is not a string.')
        byte_count = PyString_Size(self.bytes)
        self._cur_str = PyString_AsString(self.bytes)
        # This points to the last character in the string
        self._end_str = self._cur_str + byte_count
        while self._cur_str < self._end_str:
            self.process_line()
        return self.keys


def _parse_leaf_lines(bytes, key_length, ref_list_length):
    parser = BTreeLeafParser(bytes, key_length, ref_list_length)
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
cdef char *_hexbuf = '0123456789abcdef'

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


cdef int _unhexlify_sha1(char *as_hex, char *as_bin):
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
        j += 1
        bot = _unhexbuf[<unsigned char>(as_hex[j])]
        j += 1
        if top == -1 or bot == -1:
            return 0
        as_bin[i] = <unsigned char>((top << 4) + bot);
    return 1


def _test_unhexlify(as_hex):
    """For the test infrastructure, just thunks to _unhexlify_sha1"""
    if len(as_hex) != 40 or not PyString_CheckExact(as_hex):
        raise ValueError('not a 40-byte hex digest')
    as_bin = PyString_FromStringAndSize(NULL, 20)
    if _unhexlify_sha1(PyString_AS_STRING(as_hex), PyString_AS_STRING(as_bin)):
        return as_bin
    return None


cdef void _hexlify_sha1(char *as_bin, char *as_hex):
    cdef int i, j
    cdef char c

    j = 0
    for i from 0 <= i < 20:
        c = as_bin[i]
        as_hex[j] = _hexbuf[(c>>4)&0xf]
        j += 1
        as_hex[j] = _hexbuf[(c)&0xf]
        j += 1


def _test_hexlify(as_bin):
    """For test infrastructure, thunk to _hexlify_sha1"""
    if len(as_bin) != 20 or not PyString_CheckExact(as_bin):
        raise ValueError('not a 20-byte binary digest')
    as_hex = PyString_FromStringAndSize(NULL, 40)
    _hexlify_sha1(PyString_AS_STRING(as_bin), PyString_AS_STRING(as_hex))
    return as_hex


cdef int _key_to_sha1(key, char *sha1):
    """Map a key into its sha1 content.

    :param key: A tuple of style ('sha1:abcd...',)
    :param sha1: A char buffer of 20 bytes
    :return: 1 if this could be converted, 0 otherwise
    """
    cdef char *c_val
    if not PyTuple_CheckExact(key) and not StaticTuple_CheckExact(key):
        return 0
    if len(key) != 1:
        return 0
    val = key[0]
    if not PyString_CheckExact(val) or PyString_GET_SIZE(val) != 45:
        return 0
    c_val = PyString_AS_STRING(val)
    if strncmp(c_val, 'sha1:', 5) != 0:
        return 0
    if not _unhexlify_sha1(c_val + 5, sha1):
        return 0
    return 1


def _test_key_to_sha1(key):
    """Map a key to a simple sha1 string.

    This is a testing thunk to the C function.
    """
    as_bin_sha = PyString_FromStringAndSize(NULL, 20)
    if _key_to_sha1(key, PyString_AS_STRING(as_bin_sha)):
        return as_bin_sha
    return None


cdef StaticTuple _sha1_to_key(char *sha1):
    """Compute a ('sha1:abcd',) key for a given sha1."""
    cdef StaticTuple key
    cdef object hexxed
    cdef char *c_buf
    hexxed = PyString_FromStringAndSize(NULL, 45)
    c_buf = PyString_AS_STRING(hexxed)
    memcpy(c_buf, 'sha1:', 5)
    _hexlify_sha1(sha1, c_buf+5)
    key = StaticTuple_New(1)
    Py_INCREF(hexxed)
    StaticTuple_SET_ITEM(key, 0, hexxed)
    key = StaticTuple_Intern(key)
    return key


def _test_sha1_to_key(sha1_bin):
    """Test thunk to check the sha1 mapping."""
    if not PyString_CheckExact(sha1_bin) or PyString_GET_SIZE(sha1_bin) != 20:
        raise ValueError('sha1_bin must be a str of exactly 20 bytes')
    return _sha1_to_key(PyString_AS_STRING(sha1_bin))


cdef class GCCHKSHA1LeafNode:
    """Track all the entries for a given leaf node."""

    cdef public int num_entries
    cdef gc_chk_sha1_record *entries
    # This is for the mini-index. We look at all the keys and use whatever byte
    # is first unique across all stored keys (this is often the first byte)
    # we then store the entries offset for the first record that matches that
    # byte. This does assume that we'll never have more than 32k entries, but
    # that doesn't seem to be a terrible assumption (we should have ~100)
    cdef public short interesting_byte
    cdef short offsets[257]

    def __sizeof__(self):
        return (sizeof(GCCHKSHA1LeafNode)
            + sizeof(gc_chk_sha1_record)*self.num_entries)

    def __dealloc__(self):
        if self.entries != NULL:
            PyMem_Free(self.entries)
            self.entries = NULL

    def __init__(self, bytes):
        self._parse_bytes(bytes)

    property min_key:
        def __get__(self):
            if self.num_entries > 0:
                return _sha1_to_key(self.entries[0].sha1)
            return None

    property max_key:
        def __get__(self):
            if self.num_entries > 0:
                return _sha1_to_key(self.entries[self.num_entries-1].sha1)
            return None

    cdef StaticTuple _record_to_value_and_refs(self,
                                               gc_chk_sha1_record *record):
        """Extract the refs and value part of this record."""
        cdef StaticTuple value_and_refs
        cdef StaticTuple empty
        value_and_refs = StaticTuple_New(2)
        # This is really inefficient to go from a logical state back to a
        # string, but it makes things work a bit better internally for now.
        value = PyString_FromFormat('%lu %lu %lu %lu',
                                    <unsigned long>record.block_offset,
                                    record.block_length,
                                    record.record_start, record.record_end)
        Py_INCREF(value)
        StaticTuple_SET_ITEM(value_and_refs, 0, value)
        # Always empty refs
        empty = StaticTuple_New(0)
        Py_INCREF(empty)
        StaticTuple_SET_ITEM(value_and_refs, 1, empty)
        return value_and_refs

    cdef StaticTuple _record_to_item(self, gc_chk_sha1_record *record):
        """Turn a given record back into a fully fledged item.
        """
        cdef StaticTuple item
        cdef StaticTuple key
        cdef StaticTuple value_and_refs
        cdef object value
        key = _sha1_to_key(record.sha1)
        item = StaticTuple_New(2)
        Py_INCREF(key)
        StaticTuple_SET_ITEM(item, 0, key)
        value_and_refs = self._record_to_value_and_refs(record)
        Py_INCREF(value_and_refs)
        StaticTuple_SET_ITEM(item, 1, value_and_refs)
        return item

    cdef gc_chk_sha1_record* _lookup_record(self, char *sha1):
        """Find a gc_chk_sha1_record that matches the sha1 supplied."""
        # For right now we iterate, in the future we should bisect, or create
        # a local index, or use the sha1 as a hash into a local table, etc.
        cdef int i
        for i from 0 <= i < self.num_entries:
            if memcmp(self.entries[i].sha1, sha1, 20) == 0:
                return &self.entries[i]
        return NULL

    def __contains__(self, key):
        cdef char sha1[20]
        cdef gc_chk_sha1_record *record
        if not _key_to_sha1(key, sha1):
            # If it isn't a sha1 key, then it won't be in this leaf node
            return False
        return self._lookup_record(sha1) != NULL

    def __getitem__(self, key):
        cdef char sha1[20]
        cdef gc_chk_sha1_record *record = NULL
        if _key_to_sha1(key, sha1):
            record = self._lookup_record(sha1)
        if record == NULL:
            raise KeyError('key %r is not present' % (key,))
        return self._record_to_value_and_refs(record)

    def __len__(self):
        return self.num_entries

    def all_keys(self):
        cdef int i
        cdef list result = []
        for i from 0 <= i < self.num_entries:
            result.append(_sha1_to_key(self.entries[i].sha1))
        return result

    def all_items(self):
        cdef int i
        cdef list result = []
        for i from 0 <= i < self.num_entries:
            item = self._record_to_item(&self.entries[i])
            result.append(item)
        return result

    cdef _parse_bytes(self, bytes):
        """Parse the string 'bytes' into content."""
        cdef char *c_bytes
        cdef char *c_content
        cdef char *c_cur
        cdef char *c_end
        cdef char *c_next
        cdef Py_ssize_t n_bytes
        cdef int num_entries
        cdef int entry
        cdef gc_chk_sha1_record *cur_record

        if not PyString_CheckExact(bytes):
            raise TypeError('We only support parsing plain 8-bit strings.')
        # Pass 1, count how many entries there will be
        n_bytes = PyString_GET_SIZE(bytes)
        c_bytes = PyString_AS_STRING(bytes)
        c_end = c_bytes + n_bytes
        if strncmp(c_bytes, 'type=leaf\n', 10):
            raise ValueError("bytes did not start with 'type=leaf\\n': %r"
                             % (bytes[:10],))
        c_content = c_bytes + 10
        c_cur = c_content
        num_entries = 0
        while c_cur != NULL and c_cur < c_end:
            c_cur = <char *>memchr(c_cur, c'\n', c_end - c_cur);
            if c_cur == NULL:
                break
            c_cur += 1
            num_entries += 1
        # Now allocate the memory for these items, and go to town
        # We allocate both the offsets and the entries in the same malloc. we
        # should probably pay a bit closer attention to alignment
        self.entries = <gc_chk_sha1_record*>PyMem_Malloc(num_entries *
            (sizeof(unsigned short) + sizeof(gc_chk_sha1_record)))
        self.num_entries = num_entries
        c_cur = c_content
        cur_record = self.entries
        entry = 0
        while c_cur != NULL and c_cur < c_end and entry < num_entries:
            if strncmp(c_cur, 'sha1:', 5):
                raise ValueError('At byte %d, line did not start with sha1: %r'
                    % (c_cur - c_bytes, safe_string_from_size(c_cur, 10)))
            c_cur += 5
            c_next = <char *>memchr(c_cur, c'\0', c_end - c_cur)
            if c_next == NULL or (c_next - c_cur != 40):
                raise ValueError('Line did not contain 40 hex bytes')
            if not _unhexlify_sha1(c_cur, cur_record.sha1):
                raise ValueError('We failed to unhexlify')
            c_cur = c_next + 1
            if c_cur[0] != c'\0':
                raise ValueError('only 1 null, not 2 as expected')
            c_cur += 1
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
            cur_record += 1
            entry += 1
        if (entry != self.num_entries
            or c_cur != c_end
            or cur_record != self.entries + self.num_entries):
            raise ValueError('Something went wrong while parsing.')
        # Pass 3: build the offset map
        # The idea with the offset map is that we should be able to quickly
        # jump to the key that matches a gives sha1. We know that the keys are
        # in sorted order, and we know that a lot of the prefix is going to be
        # the same across them.


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

    if not PyTuple_CheckExact(node) and not StaticTuple_CheckExact(node):
        raise TypeError('We expected a tuple() or StaticTuple() for node not: %s'
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
    string_key = '\0'.join(node[1])

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
                        if (not PyTuple_CheckExact(reference)
                            and not StaticTuple_CheckExact(reference)):
                            raise TypeError(
                                'We expect references to be tuples not: %s'
                                % type(reference))
                        next_len = len(reference)
                        if next_len > 0:
                            # We will need (len - 1) '\x00' characters to
                            # separate the reference key
                            refs_len = refs_len + (next_len - 1)
                            for ref_bit in reference:
                                if not PyString_CheckExact(ref_bit):
                                    raise TypeError('We expect reference bits'
                                        ' to be strings not: %s'
                                        % type(<object>ref_bit))
                                refs_len = refs_len + PyString_GET_SIZE(ref_bit)

    # So we have the (key NULL refs NULL value LF)
    key_len = PyString_Size(string_key)
    val = node[2]
    if not PyString_CheckExact(val):
        raise TypeError('Expected a plain str for value not: %s'
                        % type(val))
    value = PyString_AS_STRING(val)
    value_len = PyString_GET_SIZE(val)
    flat_len = (key_len + 1 + refs_len + 1 + value_len + 1)
    line = PyString_FromStringAndSize(NULL, flat_len)
    # Get a pointer to the new buffer
    out = PyString_AsString(line)
    memcpy(out, PyString_AsString(string_key), key_len)
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
                    ref_bit_len = PyString_GET_SIZE(ref_bit)
                    memcpy(out, PyString_AS_STRING(ref_bit), ref_bit_len)
                    out = out + ref_bit_len
    out[0] = c'\0'
    out = out  + 1
    memcpy(out, value, value_len)
    out = out + value_len
    out[0] = c'\n'
    return string_key, line
