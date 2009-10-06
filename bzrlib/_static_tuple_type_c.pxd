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

cdef extern from "Python.h":
    ctypedef struct PyObject:
        pass

cdef extern from "_static_tuple_type_c.h":
    ctypedef class bzrlib._static_tuple_type_c.StaticTuple [object StaticTuple]:
        cdef unsigned char size
        cdef unsigned char flags
        cdef unsigned char _unused0
        cdef unsigned char _unused1
        cdef PyObject *items[0]
    int STATIC_TUPLE_ALL_STRING
    int STATIC_TUPLE_INTERNED_FLAG

    # Steals a reference and Val must be a PyStringObject, no checking is done
    void StaticTuple_SET_ITEM(StaticTuple key, Py_ssize_t offset, object val)
    object StaticTuple_GET_ITEM(StaticTuple key, Py_ssize_t offset)



