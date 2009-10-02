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

"""Definition of a class that is used to intern StaticTuple objects."""

cdef extern from "Python.h":
    ctypedef unsigned long size_t
    ctypedef struct PyTypeObject
    ctypedef struct PyObject:
        PyTypeObject *ob_type
    ctypedef long (*hashfunc)(PyObject*)
    ctypedef PyObject *(*richcmpfunc)(PyObject *, PyObject *, int)
    int Py_EQ
    PyObject *Py_True
    PyObject *Py_NotImplemented
    void Py_INCREF(PyObject *)
    void Py_DECREF(PyObject *)
    ctypedef struct PyTypeObject:
        hashfunc tp_hash
        richcmpfunc tp_richcompare
        
    void *PyMem_Malloc(size_t nbytes)
    void PyMem_Free(void *)
    void memset(void *, int, size_t)


cdef object _dummy_obj
cdef PyObject *_dummy
_dummy_obj = object()
_dummy = <PyObject *>_dummy_obj


cdef inline int _is_equal(PyObject *this, long this_hash, PyObject *other):
    cdef long other_hash
    cdef PyObject *res

    if this == other:
        return 1
    other_hash = other.ob_type.tp_hash(other)
    if other_hash != this_hash:
        return 0
    res = this.ob_type.tp_richcompare(this, other, Py_EQ)
    if res == Py_True:
        Py_DECREF(res)
        return 1
    if res == Py_NotImplemented:
        Py_DECREF(res)
        res = other.ob_type.tp_richcompare(other, this, Py_EQ)
    if res == Py_True:
        Py_DECREF(res)
        return 1
    Py_DECREF(res)
    return 0


cdef class StaticTupleInterner:
    """This class tracks the canonical forms for StaticTuples.

    It is similar in function to the interned dictionary that is used by
    strings. However:

      1) It assumes that hash(obj) is cheap, so does not need to inline a copy
         of it
      2) It only stores one reference to the object, rather than 2 (key vs
         key:value)

    As such, it uses 1/3rd the amount of memory to store a pointer to the
    interned object.
    """

    cdef readonly Py_ssize_t used    # active
    cdef readonly Py_ssize_t fill    # active + dummy
    cdef readonly Py_ssize_t mask    # Table contains (mask+1) slots, a power
                                     # of 2
    cdef PyObject **table   # Pyrex/Cython doesn't support arrays to 'object'
                            # so we manage it manually

    DEF DEFAULT_SIZE=1024
    DEF PERTURB_SHIFT=5

    def __init__(self):
        cdef Py_ssize_t size, n_bytes

        size = DEFAULT_SIZE
        self.mask = size - 1
        self.used = 0
        self.fill = 0
        n_bytes = sizeof(PyObject*) * size;
        self.table = <PyObject **>PyMem_Malloc(n_bytes)
        # TODO: Raise MemoryError if malloc fails
        memset(self.table, 0, n_bytes)

    def __dealloc__(self):
        if self.table != NULL:
            PyMem_Free(self.table)
            self.table = NULL

    def __len__(self):
        return self.used

    cdef PyObject **_lookup(self, key, long hash) except NULL:
        """Find the slot where 'key' would fit.

        This is the same as a dicts 'lookup' function

        :param key: An object we are looking up
        :param hash: The hash for key
        :return: The location in self.table where key should be put
            should never be NULL, but may reference a NULL (PyObject*)
        """
        cdef size_t i, perturb
        cdef Py_ssize_t mask
        cdef long this_hash
        cdef PyObject **table, **cur, **free_slot, *py_key

        mask = self.mask
        table = self.table
        i = hash & mask
        cur = &table[i]
        py_key = <PyObject *>key
        if cur[0] == NULL:
            # Found a blank spot, or found the exact key
            return cur
        if cur[0] == py_key:
            return cur
        if cur[0] == _dummy:
            free_slot = cur
        else:
            if _is_equal(py_key, hash, cur[0]):
                # Both py_key and cur[0] belong in this slot, return it
                return cur
            free_slot = NULL
        # size_t is unsigned, hash is signed...
        perturb = hash
        while True:
            i = (i << 2) + i + perturb + 1
            cur = &table[i & mask]
            if cur[0] == NULL: # Found an empty spot
                if free_slot: # Did we find a _dummy earlier?
                    return free_slot
                else:
                    return cur
            if (cur[0] == py_key # exact match
                or _is_equal(py_key, hash, cur[0])): # Equivalent match
                return cur
            if (cur[0] == _dummy and free_slot == NULL):
                free_slot = cur
            perturb >>= PERTURB_SHIFT
        raise AssertionError('should never get here')

    def _test_lookup(self, key):
        cdef PyObject **slot

        slot = self._lookup(key, hash(key))
        if slot[0] == NULL:
            res = '<null>'
        elif slot[0] == _dummy:
            res = '<dummy>'
        else:
            res = <object>slot[0]
        return <int>(slot - self.table), res

    def __contains__(self, key):
        cdef PyObject **slot

        slot = self._lookup(key, hash(key))
        if slot[0] == NULL or slot[0] == _dummy:
            return False
        return True

    def __getitem__(self, key):
        cdef PyObject **slot
        slot = self._lookup(key, hash(key))
        if slot[0] == NULL or slot[0] == _dummy:
            raise KeyError("Key %s is not present" % key)
        val = <object>(slot[0])
        return val

    def __setitem__(self, key, value):
        cdef PyObject **slot, *py_key
        assert key == value

        slot = self._lookup(key, hash(key))
        if (slot[0] == NULL or slot[0] == _dummy):
            py_key = <PyObject *>key
            Py_INCREF(py_key)
            slot[0] = py_key

    def __delitem__(self, key):
        cdef PyObject **slot, *py_key

        slot = self._lookup(key, hash(key))
        if (slot[0] == NULL or slot[0] == _dummy):
            pass # Raise KeyError
            return
        # Found it
        # TODO: Check refcounts
        Py_DECREF(slot[0])
        slot[0] = _dummy
