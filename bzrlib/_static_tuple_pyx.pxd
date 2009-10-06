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

"""Interface definition of a class to intern StaticTuple objects."""

cdef extern from "Python.h":
    ctypedef struct PyObject:
        pass


cdef extern from "_static_tuple_pyx_macros.h":
    # Steals a reference and Val must be a PyStringObject, no checking is done
    void StaticTuple_SET_ITEM(object key, Py_ssize_t offset, object val)
    object StaticTuple_GET_ITEM(object key, Py_ssize_t offset)
    int STATIC_TUPLE_INTERNED_FLAG
    int STATIC_TUPLE_ALL_STRING


cdef public api class StaticTuple [object StaticTuple, type StaticTuple_Type]:
    cdef unsigned char size
    cdef unsigned char flags
    cdef unsigned char _unused0
    cdef unsigned char _unused1
    cdef PyObject *items[0]

cdef api StaticTuple StaticTuple_New(Py_ssize_t)
cdef api StaticTuple StaticTuple_Intern(StaticTuple)
cdef api int StaticTuple_CheckExact(object)


cdef public api class StaticTupleInterner [object StaticTupleInternerObject,
                                           type StaticTupleInterner_type]:

    cdef readonly Py_ssize_t used    # active
    cdef readonly Py_ssize_t fill    # active + dummy
    cdef readonly Py_ssize_t mask    # Table contains (mask+1) slots, a power
                                     # of 2
    cdef PyObject **table   # Pyrex/Cython doesn't support arrays to 'object'
                            # so we manage it manually

    cdef PyObject *_get(self, object key) except? NULL
    cpdef object add(self, key)
    cpdef int discard(self, key) except -1
    cdef int _insert_clean(self, PyObject *key) except -1
    cpdef Py_ssize_t _resize(self, Py_ssize_t min_unused) except -1

# TODO: might want to export more of the C api here, though it is all available
#       from the class object...
cdef api object StaticTupleInterner_Add(object self, object key)

