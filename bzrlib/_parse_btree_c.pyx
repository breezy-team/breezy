# Copyright (C) 2008 Canonical Ltd
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

"""Pyrex extensions to btree node parsing."""

cdef extern from "stdlib.h":
    ctypedef unsigned size_t

cdef extern from "Python.h":
    int PyList_Append(object lst, object item) except -1

    char *PyString_AsString(object p)
    object PyString_FromStringAndSize(char *, Py_ssize_t)
    int PyString_CheckExact(object s)
    Py_ssize_t PyString_Size(object p)
    int PyTuple_CheckExact(object t)

cdef extern from "string.h":
    void *memcpy(void *dest, void *src, size_t n)
    void *memchr(void *s, int c, size_t n)
    # GNU extension
    # void *memrchr(void *s, int c, size_t n)
    int strncmp(char *s1, char *s2, size_t n)


# TODO: Find some way to import this from _dirstate_helpers
cdef void* _my_memrchr(void *s, int c, size_t n):
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

    cdef extract_key(self, char * last):
        """Extract a key.

        :param last: points at the byte after the last byte permitted for the
            key.
        """
        cdef char *temp_ptr
        cdef int loop_counter
        # keys are tuples
        loop_counter = 0
        key_segments = []
        while loop_counter < self.key_length:
            loop_counter = loop_counter + 1
            # grab a key segment
            temp_ptr = <char*>memchr(self._start, c'\0', last - self._start)
            if temp_ptr == NULL:
                if loop_counter == self.key_length:
                    # capture to last
                    temp_ptr = last
                else:
                    # Invalid line
                    failure_string = ("invalid key, wanted segment from " +
                        repr(safe_string_from_size(self._start,
                                                   last - self._start)))
                    raise AssertionError(failure_string)
            # capture the key string
            key_element = safe_string_from_size(self._start,
                                                temp_ptr - self._start)
            # advance our pointer
            self._start = temp_ptr + 1
            PyList_Append(key_segments, key_element)
        return tuple(key_segments)

    cdef int process_line(self) except -1:
        """Process a line in the bytes."""
        cdef char *last
        cdef char *temp_ptr
        cdef char *ref_ptr
        cdef char *next_start
        cdef int loop_counter

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
            last = last

        if last == self._start:
            # parsed it all.
            return 0
        if last < self._start:
            # Unexpected error condition - fail
            return -1
        if 0 == self._header_found:
            # The first line in a leaf node is the header "type=leaf\n"
            if strncmp("type=leaf", self._start, last - self._start) == 0:
                self._header_found = 1
                return 0
            else:
                raise AssertionError('Node did not start with "type=leaf": %r'
                    % (safe_string_from_size(self._start, last - self._start)))
                return -1

        key = self.extract_key(last)
        # find the value area
        temp_ptr = <char*>_my_memrchr(self._start, c'\0', last - self._start)
        if temp_ptr == NULL:
            # Invalid line
            return -1
        else:
            # capture the value string
            value = safe_string_from_size(temp_ptr + 1, last - temp_ptr - 1)
            # shrink the references end point
            last = temp_ptr
        if self.ref_list_length:
            ref_lists = []
            loop_counter = 0
            while loop_counter < self.ref_list_length:
                ref_list = []
                # extract a reference list
                loop_counter = loop_counter + 1
                if last < self._start:
                    return -1
                # find the next reference list end point:
                temp_ptr = <char*>memchr(self._start, c'\t', last - self._start)
                if temp_ptr == NULL:
                    # Only valid for the last list
                    if loop_counter != self.ref_list_length:
                        # Invalid line
                        return -1
                        raise AssertionError("invalid key")
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
                PyList_Append(ref_lists, tuple(ref_list))
                # prepare for the next reference list
                self._start = next_start
            ref_lists = tuple(ref_lists)
            node_value = (value, ref_lists)
        else:
            if last != self._start:
                # unexpected reference data present
                return -1
            node_value = (value, ())
        PyList_Append(self.keys, (key, node_value))
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


def _flatten_node(node, reference_lists):
    """Convert a node into the serialized form.

    :param node: A tuple representing a node:
        (index, key_tuple, value, references)
    :param reference_lists: Does this index have reference lists?
    :return: (string_key, flattened)
        string_key  The serialized key for referencing this node
        flattened   A string with the serialized form for the contents
    """
    cdef Py_ssize_t flat_len
    cdef Py_ssize_t key_len
    cdef char * value
    cdef Py_ssize_t value_len
    cdef char * out
    cdef Py_ssize_t ref_len
    cdef Py_ssize_t next_len
    cdef int first_ref_list
    cdef int first_reference
    cdef int first_bit

    # I don't expect that we can do faster than string.join()
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
    ref_len = 0
    if reference_lists:
        # Figure out how many bytes it will take to store the references
        ref_lists = node[3]
        next_len = len(ref_lists) # TODO: use a Py function
        if next_len > 0:
            # If there are no nodes, we don't need to do any work
            # Otherwise we will need (len - 1) '\t' characters to separate
            # the reference lists
            ref_len = ref_len + (next_len - 1)
            for ref_list in ref_lists:
                next_len = len(ref_list)
                if next_len > 0:
                    # We will need (len - 1) '\r' characters to separate the
                    # references
                    ref_len = ref_len + (next_len - 1)
                    for reference in ref_list:
                        next_len = len(reference)
                        if next_len > 0:
                            # We will need (len - 1) '\x00' characters to
                            # separate the reference key
                            ref_len = ref_len + (next_len - 1)
                            for ref in reference:
                                ref_len = ref_len + PyString_Size(ref)

    # So we have the (key NULL refs NULL value LF)
    key_len = PyString_Size(string_key)
    value = PyString_AsString(node[2])
    value_len = PyString_Size(node[2])
    flat_len = (key_len + 1 + ref_len + 1 + value_len + 1)
    line = PyString_FromStringAndSize(NULL, flat_len)
    # Get a pointer to the new buffer
    out = PyString_AsString(line)
    memcpy(out, PyString_AsString(string_key), key_len)
    out = out + key_len
    out[0] = c'\0'
    out = out + 1
    if ref_len > 0:
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
                first_bit = 1
                for bit in reference:
                    if first_bit == 0:
                        out[0] = c'\x00'
                        out = out + 1
                    first_bit = 0
                    next_len = PyString_Size(bit)
                    memcpy(out, PyString_AsString(bit), next_len)
                    out = out + next_len
    out[0] = c'\0'
    out = out  + 1
    memcpy(out, value, value_len)
    out = out + value_len
    out[0] = c'\n'
    return string_key, line
