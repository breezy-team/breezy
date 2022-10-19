# Copyright (C) 2007-2010 Canonical Ltd
# Copyright (C) 2018 Breezy developers
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

"""Trivial string helpers for use in other cython modules."""

cdef extern from "python-compat.h":
    object PyBytes_FromStringAndSize (char *, Py_ssize_t)


cdef inline void* _my_memrchr(void *s, int c, size_t n): # cannot_raise
    # memrchr seems to be a GNU extension, so we have to implement it ourselves
    cdef char *pos
    cdef char *start

    start = <char*>s
    pos = start + n - 1
    while pos >= start:
        if pos[0] == c:
            return <void*>pos
        pos = pos - 1
    return NULL


cdef inline object safe_string_from_size(char *s, Py_ssize_t size):
    if size < 0:
        raise AssertionError(
            'tried to create a string with an invalid size: %d' % size)
    return PyBytes_FromStringAndSize(s, size)


cdef inline object safe_interned_string_from_size(char *s, Py_ssize_t size):
    if size < 0:
        raise AssertionError(
            'tried to create a string with an invalid size: %d' % size)
    # For now, don't intern on Python 3
    return PyBytes_FromStringAndSize(s, size)
