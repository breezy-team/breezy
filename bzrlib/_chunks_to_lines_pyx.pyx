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
#

"""Pyrex extensions for converting chunks to lines."""

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

    int PyString_CheckExact(object p)
    char *PyString_AS_STRING(object p)
    Py_ssize_t PyString_GET_SIZE(object p)
    object PyString_FromStringAndSize(char *c_str, Py_ssize_t len)

cdef extern from "string.h":
    void *memchr(void *s, int c, size_t n)


def chunks_to_lines(chunks):
    """Re-split chunks into simple lines.

    Each entry in the result should contain a single newline at the end. Except
    for the last entry which may not have a final newline. If chunks is already
    a simple list of lines, we return it directly.

    :param chunks: An list/tuple of strings. If chunks is already a list of
        lines, then we will return it as-is.
    :return: A list of strings.
    """
    cdef char *c_str
    cdef char *newline
    cdef char *c_last # the last valid character of the string
    cdef Py_ssize_t the_len
    cdef Py_ssize_t chunks_len
    cdef int last_no_newline
    cdef int is_already_lines

    # Check to see if the chunks are already lines
    chunks_len = len(chunks)
    if chunks_len == 0:
        return chunks

    lines = []
    tail = None # Any remainder from the previous chunk
    last_no_newline = 0
    is_already_lines = 1
    for chunk in chunks:
        if last_no_newline:
            # We have a chunk which followed a chunk without a newline, so this
            # is not a simple list of lines.
            is_already_lines = 0
        if tail is not None:
            chunk = tail + chunk
            tail = None
        # Switching from PyString_AsStringAndSize to PyString_CheckExact and
        # then the macros GET_SIZE and AS_STRING saved us 40us / 470us.
        # It seems PyString_AsStringAndSize can actually trigger a conversion,
        # which we don't want anyway.
        if not PyString_CheckExact(chunk):
            raise TypeError('chunk is not a string')
        the_len = PyString_GET_SIZE(chunk)
        if the_len == 0:
            # An empty string is never a valid line, and we don't need to
            # append anything
            is_already_lines = 0
            continue
        c_str = PyString_AS_STRING(chunk)
        c_last = c_str + the_len - 1
        newline = <char *>memchr(c_str, c'\n', the_len)
        if newline == c_last:
            # A simple line
            PyList_Append(lines, chunk)
        elif newline == NULL:
            # A chunk without a newline, if this is the last entry, then we
            # allow it
            tail = chunk
            last_no_newline = 1
        else:
            # We have a newline in the middle, loop until we've consumed all
            # lines
            is_already_lines = 0
            while newline != NULL:
                line = PyString_FromStringAndSize(c_str, newline - c_str + 1)
                PyList_Append(lines, line)
                c_str = newline + 1
                if c_str > c_last: # We are done
                    break
                the_len = c_last - c_str + 1
                newline = <char *>memchr(c_str, c'\n', the_len)
                if newline == NULL:
                    tail = PyString_FromStringAndSize(c_str, the_len)
                    break
    if is_already_lines:
        return chunks
    if tail is not None:
        PyList_Append(lines, tail)
    return lines
