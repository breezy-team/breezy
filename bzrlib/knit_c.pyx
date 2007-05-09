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


cdef extern from "stdlib.h":
    long int strtol(char *nptr, char **endptr, int base)
    unsigned long int strtoul(char *nptr, char **endptr, int base)


cdef extern from "Python.h":
    int PyDict_CheckExact(object)
    void *PyDict_GetItem(object p, object key)
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

    cdef object text
    cdef char * text_str
    cdef int text_size

    cdef char * cur_str
    cdef char * end_str

    cdef int history_len

    def __new__(self, kndx, fp):
        self.kndx = kndx
        self.fp = fp

        self.cache = kndx._cache
        self.history = kndx._history
        self.text = None

        self.text_str = NULL
        self.text_size = 0
        self.cur_str = NULL
        self.end_str = NULL
        self.history_len = 0

    cdef void validate(self):
        if not PyDict_CheckExact(self.cache):
            raise TypeError('kndx._cache must be a python dict')
        if not PyList_CheckExact(self.history):
            raise TypeError('kndx._history must be a python list')

    cdef void process_one_record(self, char *start, char *end):
        """Take a simple string and split it into an index record."""
        cdef char *version_id_str
        cdef int version_id_size
        cdef char *option_str
        cdef int option_size
        cdef char *pos_str
        cdef int pos
        cdef char *size_str
        cdef int size
        cdef char *parent_str
        cdef int parent_size

        version_id_str = start
        option_str = strchr(version_id_str, c' ')
        if option_str == NULL or option_str >= end:
            # Short entry
            return
        version_id_size = <int>(option_str - version_id_str)
        # Move past the space character
        option_str = option_str + 1

        pos_str = strchr(option_str, c' ')
        if pos_str == NULL or pos_str >= end:
            # Short entry
            return
        option_size = <int>(pos_str - option_str)
        pos_str = pos_str + 1

        size_str = strchr(pos_str, c' ')
        if size_str == NULL or size_str >= end:
            # Short entry
            return
        size_str = size_str + 1

        # TODO: Make sure this works when there are no parents
        parent_str = strchr(size_str, c' ')
        if parent_str == NULL or parent_str >= end:
            # Missing parents
            return
        parent_str = parent_str + 1

        version_id = PyString_FromStringAndSize(version_id_str,
                                                version_id_size)
        options = PyString_FromStringAndSize(option_str, option_size)
        options = options.split(',')

        pos = strtol(pos_str, NULL, 10)
        size = strtol(size_str, NULL, 10)

        # TODO: Check that we are actually reading integers
        parents = PyString_FromStringAndSize(parent_str,
                                             <int>(end - parent_str))
        parents = parents.split()
        real_parents = []
        for parent in parents:
            if parent[0].startswith('.'):
                real_parents.append(parent[1:])
            else:
                real_parents.append(self.history[int(parent)])

        if version_id not in self.cache:
            self.history.append(version_id)
            index = self.history_len
            self.history_len = self.history_len + 1
        else:
            index = self.cache[version_id][5]

        self.cache[version_id] = (version_id,
                                  options,
                                  pos,
                                  size,
                                  real_parents,
                                  index,
                                 )

    cdef void process_next_record(self):
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
            line = PyString_FromStringAndSize(start, <int>(last - start))
            ending = PyString_FromStringAndSize(last, 1)
        else:
            # The last character is right before the '\n'
            # And the next string is right after it
            line = PyString_FromStringAndSize(start, <int>(last - start))
            self.cur_str = last + 1
            last = last - 1
            ending = PyString_FromStringAndSize(last, 3)

        if last <= start or last[0] != c':':
            # Incomplete record
            return

        self.process_one_record(start, last)

    def read(self):
        self.validate()

        kndx = self.kndx
        fp = self.fp
        cache = self.cache
        history = self.history

        kndx.check_header(fp)

        # We read the whole thing at once
        # TODO: jam 2007-05-09 Consider reading incrementally rather than
        #       having to have the whole thing read up front.
        #       we already know that calling f.readlines() versus lots of
        #       f.readline() calls is faster.
        self.text = fp.read()
        self.text_str = PyString_AsString(self.text)
        self.text_size = PyString_Size(self.text)
        self.cur_str = self.text_str
        # This points to the last character in the string
        self.end_str = self.text_str + self.text_size

        while self.cur_str < self.end_str:
            self.process_next_record()


def _load_data_c(kndx, fp):
    """Load the knit index file into memory."""
    reader = KnitIndexReader(kndx, fp)
    reader.read()
