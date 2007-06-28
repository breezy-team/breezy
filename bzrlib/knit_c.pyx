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

"""Pyrex extensions to knit parsing."""

import sys

from bzrlib import errors


cdef extern from "stdlib.h":
    long int strtol(char *nptr, char **endptr, int base)
    unsigned long int strtoul(char *nptr, char **endptr, int base)


cdef extern from "Python.h":
    int PyDict_CheckExact(object)
    void *PyDict_GetItem_void "PyDict_GetItem" (object p, object key)
    int PyDict_SetItem(object p, object key, object val) except -1

    int PyList_Append(object lst, object item) except -1
    void *PyList_GetItem_object_void "PyList_GET_ITEM" (object lst, int index)
    object PyList_GET_ITEM (object lst, int index)
    int PyList_CheckExact(object)

    int PyTuple_CheckExact(object)
    void *PyTuple_GetItem_void_void "PyTuple_GET_ITEM" (void* tpl, int index)
    object PyTuple_New(int)
    int PyTuple_SetItem(object tpl, int offset, object val)
    void PyTuple_SET_ITEM(object tpl, int offset, object val)
    object PyTuple_Pack(int n, ...)

    char *PyString_AsString(object p)
    char *PyString_AS_STRING_void "PyString_AS_STRING" (void *p)
    object PyString_FromString(char *)
    object PyString_FromStringAndSize(char *, int)
    int PyString_Size(object p)
    int PyString_GET_SIZE_void "PyString_GET_SIZE" (void *p)
    int PyString_CheckExact(object p)

    void Py_INCREF(object)
    void Py_DECREF(object)


cdef extern from "string.h":
    char *strchr(char *s1, char c)
    int strncmp(char *s1, char *s2, int len)
    int strcmp(char *s1, char *s2)


cdef class KnitIndexReader:

    cdef object kndx
    cdef object fp

    cdef object cache
    cdef object history

    cdef char * cur_str
    cdef char * end_str

    cdef int history_len

    def __new__(self, kndx, fp):
        self.kndx = kndx
        self.fp = fp

        self.cache = kndx._cache
        self.history = kndx._history

        self.cur_str = NULL
        self.end_str = NULL
        self.history_len = 0

    cdef void validate(self):
        if not PyDict_CheckExact(self.cache):
            raise TypeError('kndx._cache must be a python dict')
        if not PyList_CheckExact(self.history):
            raise TypeError('kndx._history must be a python list')

    cdef char * _end_of_option(self, char *option_str, char *end):
        """Find the end of this option string.

        This is similar to doing ``strchr(option_str, ',')``, except
        it knows to stop if it hits 'end' first.
        """
        cdef char * cur

        cur = option_str
        while cur < end:
            if cur[0] == c',' or cur[0] == c' ':
                return cur
            cur = cur + 1
        return end

    cdef object process_options(self, char *option_str, char *end):
        """Process the options string into a list."""
        cdef char *next

        # options = PyString_FromStringAndSize(option_str,
        #                                      end-option_str)
        # return options.split(',')

        final_options = []

        while option_str < end:
            # Using strchr here actually hurts performance dramatically.
            # Because you aren't guaranteed to have a ',' any time soon,
            # so it may have to search for a long time.
            # The closest function is memchr, but that seems to be a
            # GNU extension.
            next = self._end_of_option(option_str, end)
            next_option = PyString_FromStringAndSize(option_str,
                                                     next - option_str)
            PyList_Append(final_options, next_option)
                          
            # Move past the ','
            option_str = next+1

        return final_options

    cdef object process_parents(self, char *parent_str, char *end):
        cdef char *next
        cdef int int_parent
        cdef char *parent_end

        # parents = PyString_FromStringAndSize(parent_str,
        #                                      end - parent_str)
        # real_parents = []
        # for parent in parents.split():
        #     if parent[0].startswith('.'):
        #         real_parents.append(parent[1:])
        #     else:
        #         real_parents.append(self.history[int(parent)])
        # return real_parents

        parents = []
        while parent_str <= end and parent_str != NULL:
            # strchr is safe here, because our lines always end
            # with ' :'
            next = strchr(parent_str, c' ')
            if next == NULL or next >= end or next == parent_str:
                break

            if parent_str[0] == c'.':
                # This is an explicit revision id
                parent_str = parent_str + 1
                parent = PyString_FromStringAndSize(parent_str, next-parent_str)
            else:
                # This in an integer mapping to original
                # TODO: ensure that we are actually parsing the string
                int_parent = strtol(parent_str, &parent_end, 10)

                # Can the parent be decoded to get its parent row? This
                # at a minimum will cause this row to have wrong parents, or
                # even to apply a delta to the wrong base and decode
                # incorrectly. its therefore not usable, and because we have
                # encountered a situation where a new knit index had this
                # corrupt we can't asssume that no other rows referring to the
                # index of this record actually mean the subsequent uncorrupt
                # one, so we error.
                if int_parent >= self.history_len:
                    raise IndexError('Parent index refers to a revision which'
                        ' does not exist yet.'
                        ' %d > %d' % (int_parent, self.history_len))
                if end < next-1:
                    # We didn't process all of the string, which means it isn't
                    # a complete integer.
                    py_parent = PyString_FromStringAndSize(parent_str,
                                                           next - parent_str)
                    raise ValueError('%r is not a valid integer' % (py_parent,))
                parent = PyList_GET_ITEM(self.history, int_parent)
                # PyList_GET_ITEM steals a reference
                Py_INCREF(parent)
            PyList_Append(parents, parent)
            parent_str = next + 1
        return parents

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
        option_str = strchr(version_id_str, c' ')
        if option_str == NULL or option_str >= end:
            # Short entry
            return 0
        version_id_size = <int>(option_str - version_id_str)
        # Move past the space character
        option_str = option_str + 1

        pos_str = strchr(option_str, c' ')
        if pos_str == NULL or pos_str >= end:
            # Short entry
            return 0
        option_end = pos_str
        pos_str = pos_str + 1

        size_str = strchr(pos_str, c' ')
        if size_str == NULL or size_str >= end:
            # Short entry
            return 0
        size_str = size_str + 1

        # TODO: Make sure this works when there are no parents
        parent_str = strchr(size_str, c' ')
        if parent_str == NULL or parent_str >= end:
            # Missing parents
            return 0
        parent_str = parent_str + 1

        version_id = PyString_FromStringAndSize(version_id_str,
                                                version_id_size)
        options = self.process_options(option_str, option_end)

        # TODO: Check that we are actually reading integers
        pos = strtol(pos_str, NULL, 10)
        size = strtol(size_str, NULL, 10)

        try:
            parents = self.process_parents(parent_str, end)
        except (ValueError, IndexError), e:
            py_line = PyString_FromStringAndSize(start, end - start)
            raise errors.KnitCorrupt(self.kndx._filename,
                "line %r: %s" % (py_line, e))

        cache_entry = PyDict_GetItem_void(self.cache, version_id)
        if cache_entry == NULL:
            PyList_Append(self.history, version_id)
            index = self.history_len
            self.history_len = self.history_len + 1
        else:
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
        last = strchr(start, c'\n')
        if last == NULL:
            # Process until the end of the file
            last = self.end_str-1
            self.cur_str = self.end_str
            line = PyString_FromStringAndSize(start, last - start)
            ending = PyString_FromStringAndSize(last, 1)
        else:
            # The last character is right before the '\n'
            # And the next string is right after it
            line = PyString_FromStringAndSize(start, last - start)
            self.cur_str = last + 1
            last = last - 1
            ending = PyString_FromStringAndSize(last, 3)

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
        text_size = PyString_Size(text)
        self.cur_str = PyString_AsString(text)
        # This points to the last character in the string
        self.end_str = self.cur_str + text_size

        while self.cur_str < self.end_str:
            self.process_next_record()


def _load_data_c(kndx, fp):
    """Load the knit index file into memory."""
    reader = KnitIndexReader(kndx, fp)
    reader.read()
