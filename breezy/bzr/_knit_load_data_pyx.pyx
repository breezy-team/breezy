# Copyright (C) 2007-2010 Canonical Ltd
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

"""Pyrex extensions to knit parsing."""

import sys

from .knit import KnitCorrupt

from libc.stdlib cimport strtol
from libc.string cimport memchr

from cpython.bytes cimport (
    PyBytes_AsString,
    PyBytes_CheckExact,
    PyBytes_FromStringAndSize,
    PyBytes_Size,
    )
from cpython.dict cimport (
    PyDict_CheckExact,
    PyDict_SetItem,
    )
from cpython.list cimport (
    PyList_Append,
    PyList_CheckExact,
    PyList_GET_ITEM,
    )

cdef extern from "Python.h":
    void *PyDict_GetItem_void "PyDict_GetItem" (object p, object key)
    void *PyTuple_GetItem_void_void "PyTuple_GET_ITEM" (void* tpl, int index)


cdef int string_to_int_safe(char *s, char *end, int *out) except -1:
    """Convert a base10 string to an integer.

    This makes sure the whole string is consumed, or it raises ValueError.
    This is similar to how int(s) works, except you don't need a Python
    String object.

    :param s: The string to convert
    :param end: The character after the integer. So if the string is '12\0',
        this should be pointing at the '\0'. If the string was '12 ' then this
        should point at the ' '.
    :param out: This is the integer that will be returned
    :return: -1 if an exception is raised. 0 otherwise
    """
    cdef char *integer_end

    # We can't just return the integer because of how pyrex determines when
    # there is an exception.
    out[0] = <int>strtol(s, &integer_end, 10)
    if integer_end != end:
        py_s = PyBytes_FromStringAndSize(s, end-s)
        raise ValueError('%r is not a valid integer' % (py_s,))
    return 0


cdef class KnitIndexReader:

    cdef object kndx
    cdef object fp

    cdef object cache
    cdef object history

    cdef char * cur_str
    cdef char * end_str

    cdef int history_len

    def __init__(self, kndx, fp):
        self.kndx = kndx
        self.fp = fp

        self.cache = kndx._cache
        self.history = kndx._history

        self.cur_str = NULL
        self.end_str = NULL
        self.history_len = 0

    cdef int validate(self) except -1:
        if not PyDict_CheckExact(self.cache):
            raise TypeError('kndx._cache must be a python dict')
        if not PyList_CheckExact(self.history):
            raise TypeError('kndx._history must be a python list')
        return 0

    cdef object process_options(self, char *option_str, char *end):
        """Process the options string into a list."""
        cdef char *n

        # This is alternative code which creates a python string and splits it.
        # It is "correct" and more obvious, but slower than the following code.
        # It can be uncommented to switch in case the other code is seen as
        # suspect.
        # options = PyBytes_FromStringAndSize(option_str, end - option_str)
        # return options.split(',')

        final_options = []

        while option_str < end:
            n = <char*>memchr(option_str, c',', end - option_str)
            if n == NULL:
                n = end
            n_option = PyBytes_FromStringAndSize(option_str, n - option_str)
            PyList_Append(final_options, n_option)

            # Move past the ','
            option_str = n+1

        return final_options

    cdef object process_parents(self, char *parent_str, char *end):
        cdef char *n
        cdef int int_parent
        cdef char *parent_end

        # Alternative, correct but slower code.
        #
        # parents = PyBytes_FromStringAndSize(parent_str, end - parent_str)
        # real_parents = []
        # for parent in parents.split():
        #     if parent[0].startswith('.'):
        #         real_parents.append(parent[1:])
        #     else:
        #         real_parents.append(self.history[int(parent)])
        # return real_parents

        parents = []
        while parent_str <= end:
            n = <char*>memchr(parent_str, c' ', end - parent_str)
            if n == NULL or n >= end or n == parent_str:
                break

            if parent_str[0] == c'.':
                # This is an explicit revision id
                parent_str = parent_str + 1
                parent = PyBytes_FromStringAndSize(parent_str, n - parent_str)
            else:
                # This in an integer mapping to original
                string_to_int_safe(parent_str, n, &int_parent)

                if int_parent >= self.history_len:
                    raise IndexError('Parent index refers to a revision which'
                        ' does not exist yet.'
                        ' %d > %d' % (int_parent, self.history_len))
                # PyList_GET_ITEM steals a reference but object cast INCREFs
                parent = <object>PyList_GET_ITEM(self.history, int_parent)
            PyList_Append(parents, parent)
            parent_str = n + 1
        return tuple(parents)

    cdef int process_one_record(self, char *start, char *end) except -1:
        """Take a simple string and split it into an index record."""
        cdef char *version_id_str
        cdef int version_id_size
        cdef char *option_str
        cdef char *option_end
        cdef char *pos_str
        cdef int pos
        cdef char *size_str
        cdef int size
        cdef char *parent_str
        cdef int parent_size
        cdef void *cache_entry

        version_id_str = start
        option_str = <char*>memchr(version_id_str, c' ', end - version_id_str)
        if option_str == NULL or option_str >= end:
            # Short entry
            return 0
        version_id_size = <int>(option_str - version_id_str)
        # Move past the space character
        option_str = option_str + 1

        pos_str = <char*>memchr(option_str, c' ', end - option_str)
        if pos_str == NULL or pos_str >= end:
            # Short entry
            return 0
        option_end = pos_str
        pos_str = pos_str + 1

        size_str = <char*>memchr(pos_str, c' ', end - pos_str)
        if size_str == NULL or size_str >= end:
            # Short entry
            return 0
        size_str = size_str + 1

        parent_str = <char*>memchr(size_str, c' ', end - size_str)
        if parent_str == NULL or parent_str >= end:
            # Missing parents
            return 0
        parent_str = parent_str + 1

        version_id = PyBytes_FromStringAndSize(version_id_str, version_id_size)
        options = self.process_options(option_str, option_end)

        try:
            string_to_int_safe(pos_str, size_str - 1, &pos)
            string_to_int_safe(size_str, parent_str - 1, &size)
            parents = self.process_parents(parent_str, end)
        except (ValueError, IndexError), e:
            py_line = PyBytes_FromStringAndSize(start, end - start)
            raise KnitCorrupt(self.kndx._filename, "line %r: %s" % (py_line, e))

        cache_entry = PyDict_GetItem_void(self.cache, version_id)
        if cache_entry == NULL:
            PyList_Append(self.history, version_id)
            index = self.history_len
            self.history_len = self.history_len + 1
        else:
            # PyTuple_GetItem_void_void does *not* increment the reference
            # counter, but casting to <object> does.
            index = <object>PyTuple_GetItem_void_void(cache_entry, 5)

        PyDict_SetItem(self.cache, version_id,
                       (version_id,
                        options,
                        pos,
                        size,
                        parents,
                        index,
                       ))
        return 1

    cdef int process_next_record(self) except -1:
        """Process the next record in the file."""
        cdef char *last
        cdef char *start

        start = self.cur_str
        # Find the next newline
        last = <char*>memchr(start, c'\n', self.end_str - start)
        if last == NULL:
            # Process until the end of the file
            last = self.end_str - 1
            self.cur_str = self.end_str
        else:
            # The last character is right before the '\n'
            # And the next string is right after it
            self.cur_str = last + 1
            last = last - 1

        if last <= start or last[0] != c':':
            # Incomplete record
            return 0

        return self.process_one_record(start, last)

    def read(self):
        cdef int text_size

        self.validate()

        self.kndx.check_header(self.fp)

        # We read the whole thing at once
        # TODO: jam 2007-05-09 Consider reading incrementally rather than
        #       having to have the whole thing read up front.
        #       we already know that calling f.readlines() versus lots of
        #       f.readline() calls is faster.
        #       The other possibility is to avoid a Python String here
        #       completely. However self.fp may be a 'file-like' object
        #       it is not guaranteed to be a real file.
        text = self.fp.read()
        text_size = PyBytes_Size(text)
        self.cur_str = PyBytes_AsString(text)
        # This points to the last character in the string
        self.end_str = self.cur_str + text_size

        while self.cur_str < self.end_str:
            self.process_next_record()


cpdef _load_data_c(kndx, fp):
    """Load the knit index file into memory."""
    reader = KnitIndexReader(kndx, fp)
    reader.read()
