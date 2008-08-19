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

import sys

cdef extern from "stdlib.h":
    ctypedef unsigned size_t
    long int strtol(char *nptr, char **endptr, int base)


cdef extern from "Python.h":
    int PyDict_CheckExact(object)
    void *PyDict_GetItem_void "PyDict_GetItem" (object p, object key)
    int PyDict_SetItem(object p, object key, object val) except -1

    int PyList_Append(object lst, object item) except -1
    object PyList_GET_ITEM(object lst, int index)
    int PyList_CheckExact(object)

    void *PyTuple_GetItem_void_void "PyTuple_GET_ITEM" (void* tpl, int index)

    char *PyString_AsString(object p)
    object PyString_FromStringAndSize(char *, int)
    object PyString_FromString(char *)
    int PyString_Size(object p)

    void Py_INCREF(object)


cdef extern from "string.h":
    void *memchr(void *s, int c, size_t n)
    # void *memrchr(void *s, int c, size_t n)
    int strncmp(char *s1, char *s2, size_t n)


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


cdef class BTreeLeafParser:

    cdef object bytes
    cdef int key_length
    cdef int ref_list_length
    cdef object keys

    cdef char * cur_str
    cdef char * end_str
    # The current start point for parsing
    cdef char * start

    cdef int header_found

    def __init__(self, bytes, key_length, ref_list_length):
        self.bytes = bytes
        self.key_length = key_length
        self.ref_list_length = ref_list_length
        self.keys = []
        self.cur_str = NULL
        self.end_str = NULL
        self.header_found = 0

    cdef extract_key(self, char * last):
        """Extract a key.

        :param last: points at the byte after the last byte permitted for the key.
        """
        cdef char *temp_ptr
        cdef int loop_counter
        # keys are tuples
        loop_counter = 0
        key_segments = []
        while loop_counter < self.key_length:
            loop_counter = loop_counter + 1
            # grab a key segment
            temp_ptr = <char*>memchr(self.start, c'\0', last - self.start)
            if temp_ptr == NULL:
                if loop_counter == self.key_length:
                    # capture to last
                    temp_ptr = last
                else:
                    # Invalid line
                    failure_string = ("invalid key, wanted segment from " +
                        repr(PyString_FromStringAndSize(self.start, last-self.start)))
                    raise AssertionError(failure_string)
            # capture the key string
            key_element = PyString_FromStringAndSize(self.start, temp_ptr - self.start)
            # advance our pointer
            self.start = temp_ptr + 1
            PyList_Append(key_segments, key_element)
        return tuple(key_segments)

    cdef int process_line(self) except -1:
        """Process a line in the bytes."""
        cdef char *last
        cdef char *temp_ptr
        cdef char *ref_ptr
        cdef char *next_start
        cdef int loop_counter

        self.start = self.cur_str
        # Find the next newline
        last = <char*>memchr(self.start, c'\n', self.end_str - self.start)
        if last == NULL:
            # Process until the end of the file
            last = self.end_str
            self.cur_str = self.end_str
        else:
            # And the next string is right after it
            self.cur_str = last + 1
            # The last character is right before the '\n'
            last = last

        if last == self.start:
            # parsed it all.
            return 0
        if last < self.start:
            # Unexpected error condition - fail
            return -1
        if 0 == self.header_found:
            if strncmp("type=leaf", self.start, last-self.start) == 0:
                self.header_found = 1
                return 0
            else:
                print "failed strncmp", repr(PyString_FromStringAndSize(self.start, last-self.start))
                return -1

        key = self.extract_key(last)
        # find the value area
        temp_ptr = <char*>_my_memrchr(self.start, c'\0', last - self.start)
        if temp_ptr == NULL:
            # Invalid line
            return -1
        else:
            # capture the value string
            value = PyString_FromStringAndSize(temp_ptr + 1, last - temp_ptr - 1)
            # shrink the references end point
            last = temp_ptr
        if self.ref_list_length:
            ref_lists = []
            loop_counter = 0
            while loop_counter < self.ref_list_length:
                ref_list = []
                # extract a reference list
                loop_counter = loop_counter + 1
                if last < self.start:
                    return -1
                # find the next reference list end point:
                temp_ptr = <char*>memchr(self.start, c'\t', last - self.start)
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
                while self.start < ref_ptr:
                    # loop finding keys and extracting them
                    temp_ptr = <char*>memchr(self.start, c'\r', ref_ptr - self.start)
                    if temp_ptr == NULL:
                        # key runs to the end
                        temp_ptr = ref_ptr
                    PyList_Append(ref_list, self.extract_key(temp_ptr))
                PyList_Append(ref_lists, tuple(ref_list))
                # prepare for the next reference list
                self.start = next_start
            ref_lists = tuple(ref_lists)
            node_value = (value, ref_lists)
        else:
            if last != self.start:
                # unexpected reference data present
                return -1
            node_value = (value, ())
        PyList_Append(self.keys, (key, node_value))
        return 0

    def parse(self):
        cdef int byte_count
        byte_count = PyString_Size(self.bytes)
        self.cur_str = PyString_AsString(self.bytes)
        # This points to the last character in the string
        self.end_str = self.cur_str + byte_count
        while self.cur_str < self.end_str:
            self.process_line()
        return self.keys


def _parse_leaf_lines(bytes, key_length, ref_list_length):
    parser = BTreeLeafParser(bytes, key_length, ref_list_length)
    return parser.parse()
