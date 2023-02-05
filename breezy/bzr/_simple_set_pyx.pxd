# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Interface definition of a class like PySet but without caching the hash.

This is generally useful when you want to 'intern' objects, etc. Note that this
differs from Set in that we:
  1) Don't have all of the .intersection, .difference, etc functions
  2) Do return the object from the set via queries
     eg. SimpleSet.add(key) => saved_key and SimpleSet[key] => saved_key
"""

from cpython.object cimport PyObject


cdef public api class SimpleSet [object SimpleSetObject, type SimpleSet_Type]:
    """A class similar to PySet, but with simpler implementation.

    The main advantage is that this class uses only 2N memory to store N
    objects rather than 4N memory. The main trade-off is that we do not cache
    the hash value of saved objects. As such, it is assumed that computing the
    hash will be cheap (such as strings or tuples of strings, etc.)

    This also differs in that you can get back the objects that are stored
    (like a dict), but we also don't implement the complete list of 'set'
    operations (difference, intersection, etc).
    """
    # Data structure definition:
    #   This is a basic hash table using open addressing.
    #       http://en.wikipedia.org/wiki/Open_addressing
    #   Basically that means we keep an array of pointers to Python objects
    #   (called a table). Each location in the array is called a 'slot'.
    #
    #   An empty slot holds a NULL pointer, a slot where there was an item
    #   which was then deleted will hold a pointer to _dummy, and a filled slot
    #   points at the actual object which fills that slot.
    #
    #   The table is always a power of two, and the default location where an
    #   object is inserted is at hash(object) & (table_size - 1)
    #
    #   If there is a collision, then we search for another location. The
    #   specific algorithm is in _lookup. We search until we:
    #       find the object
    #       find an equivalent object (by tp_richcompare(obj1, obj2, Py_EQ))
    #       find a NULL slot
    #
    #   When an object is deleted, we set its slot to _dummy. this way we don't
    #   have to track whether there was a collision, and find the corresponding
    #   keys. (The collision resolution algorithm makes that nearly impossible
    #   anyway, because it depends on the upper bits of the hash.)
    #   The main effect of this, is that if we find _dummy, then we can insert
    #   an object there, but we have to keep searching until we find NULL to
    #   know that the object is not present elsewhere.

    cdef Py_ssize_t _used   # active
    cdef Py_ssize_t _fill   # active + dummy
    cdef Py_ssize_t _mask   # Table contains (mask+1) slots, a power of 2
    cdef PyObject **_table  # Pyrex/Cython doesn't support arrays to 'object'
                            # so we manage it manually

    cdef PyObject *_get(self, object key) except? NULL
    cpdef object add(self, key)
    cpdef bint discard(self, key) except -1
    cdef int _insert_clean(self, PyObject *key) except -1
    cdef Py_ssize_t _resize(self, Py_ssize_t min_unused) except -1


# TODO: might want to export the C api here, though it is all available from
#       the class object...
cdef api SimpleSet SimpleSet_New()
cdef api object SimpleSet_Add(object self, object key)
cdef api int SimpleSet_Contains(object self, object key) except -1
cdef api int SimpleSet_Discard(object self, object key) except -1
cdef api PyObject *SimpleSet_Get(SimpleSet self, object key) except? NULL
cdef api Py_ssize_t SimpleSet_Size(object self) except -1
cdef api int SimpleSet_Next(object self, Py_ssize_t *pos, PyObject **key) except -1
