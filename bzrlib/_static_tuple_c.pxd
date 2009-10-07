# Copyright (C) 2009 Canonical Ltd
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

"""The interface definition file for the StaticTuple class."""


cdef extern from "Python.h":
    ctypedef int Py_ssize_t # Required for older pyrex versions
    ctypedef struct PyObject:
        pass

cdef extern from "_static_tuple_c.h":
    ctypedef class bzrlib._static_tuple_c.StaticTuple [object StaticTuple]:
        cdef unsigned char size
        cdef unsigned char flags
        # We don't need to define _unused attributes, because the raw
        # StaticTuple structure will be referenced
        # cdef unsigned char _unused0
        # cdef unsigned char _unused1
        cdef PyObject *items[0]

    int import_static_tuple_c() except -1
    # ctypedef object (*st_new_type)(Py_ssize_t)
    # st_new_type st_new
    int STATIC_TUPLE_ALL_STRING

    StaticTuple StaticTuple_New(Py_ssize_t)
    StaticTuple StaticTuple_Intern(StaticTuple)
    # Steals a reference and Val must be a PyStringObject, no checking is done
    void StaticTuple_SET_ITEM(StaticTuple key, Py_ssize_t offset, object val)
    object StaticTuple_GET_ITEM(StaticTuple key, Py_ssize_t offset)
    int StaticTuple_CheckExact(object)
