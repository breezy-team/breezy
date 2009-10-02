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
    # Only handled for now because we are testing with stuff like tuples versus
    # StaticTuple objects. If we decide to limit StaticTupleInterner to
    # strictly only allowing StaticTuple objects, then this is no longer
    # required, and Py_NotImplemented => not equal
    if res == Py_NotImplemented:
        Py_DECREF(res)
        res = other.ob_type.tp_richcompare(other, this, Py_EQ)
    if res == Py_True:
        Py_DECREF(res)
        return 1
    Py_DECREF(res)
    return 0


cdef public api class StaticTupleInterner [object StaticTupleInternerObject,
                                           type StaticTupleInterner_type]:
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

    def _test_lookup(self, key):
        cdef PyObject **slot

        slot = _StaticTupleInterner_Lookup(self, key, hash(key))
        if slot[0] == NULL:
            res = '<null>'
        elif slot[0] == _dummy:
            res = '<dummy>'
        else:
            res = <object>slot[0]
        return <int>(slot - self.table), res

    def __contains__(self, key):
        cdef PyObject **slot

        slot = _StaticTupleInterner_Lookup(self, key, hash(key))
        if slot[0] == NULL or slot[0] == _dummy:
            return False
        return True

    def __getitem__(self, key):
        """Return a stored item that is equivalent to key."""
        cdef PyObject **slot
        slot = _StaticTupleInterner_Lookup(self, key, hash(key))
        if slot[0] == NULL or slot[0] == _dummy:
            raise KeyError("Key %s is not present" % key)
        val = <object>(slot[0])
        return val

    # def __setitem__(self, key, value):
    #     assert key == value
    #     self._add(key)

    def add(self, key):
        """Similar to set.add(), start tracking this key.
        
        There is one small difference, which is that we return the object that
        is stored at the given location. (which is closer to the
        dict.setdefault() functionality.)
        """
        return StaticTupleInterner_Add(self, key)

    def discard(self, key):
        """Remove key from the dict, whether it exists or not.

        :return: 0 if the item did not exist, 1 if it did
        """
        return StaticTupleInterner_Discard(self, key)


    def __delitem__(self, key):
        """Remove the given item from the dict.

        Raise a KeyError if the key was not present.
        """
        cdef int exists
        exists = StaticTupleInterner_Discard(self, key)
        if not exists:
            raise KeyError('Key %s not present' % (key,))


cdef api inline PyObject **_StaticTupleInterner_Lookup(
            StaticTupleInterner self, key, long hash) except NULL:
    """Find the slot where 'key' would fit.

    This is the same as a dicts 'lookup' function.

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


cdef api object StaticTupleInterner_Add(StaticTupleInterner self, object key):
    """Add a key to the StaticTupleInterner (set).

    :param self: The StaticTupleInterner to add the key to.
    :param key: The key to be added. If the key is already present,
        self will not be modified
    :return: The current key stored at the location defined by 'key'.
        This may be the same object, or it may be an equivalent object.
        (consider dict.setdefault(key, key))
    """
    cdef PyObject **slot, *py_key

    slot = _StaticTupleInterner_Lookup(self, key, hash(key))
    py_key = <PyObject *>key
    if (slot[0] == NULL):
        Py_INCREF(py_key)
        self.fill += 1
        self.used += 1
        slot[0] = py_key
    elif (slot[0] == _dummy):
        Py_INCREF(py_key)
        self.used += 1
        slot[0] = py_key
    # No else: clause. If _StaticTupleInterner_Lookup returns a pointer to
    # a live object, then we already have a value at this location.
    return <object>(slot[0])


cdef api int StaticTupleInterner_Discard(StaticTupleInterner self,
                                         object key) except -1:
    """Remove the object referenced at location 'key'.

    :param self: The StaticTupleInterner being modified
    :param key: The key we are checking on
    :return: 1 if there was an object present, 0 if there was not, and -1 on
        error.
    """
    cdef PyObject **slot, *py_key

    slot = _StaticTupleInterner_Lookup(self, key, hash(key))
    if slot[0] == NULL or slot[0] == _dummy:
        return 0
    self.used -= 1
    Py_DECREF(slot[0])
    slot[0] = _dummy
    return 1
