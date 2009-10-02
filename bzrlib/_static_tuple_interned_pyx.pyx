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

    PyTypeObject *Py_TYPE(PyObject *)
        
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
    other_hash = Py_TYPE(other).tp_hash(other)
    if other_hash != this_hash:
        return 0
    res = Py_TYPE(this).tp_richcompare(this, other, Py_EQ)
    if res == Py_True:
        Py_DECREF(res)
        return 1
    # Only handled for now because we are testing with stuff like tuples versus
    # StaticTuple objects. If we decide to limit StaticTupleInterner to
    # strictly only allowing StaticTuple objects, then this is no longer
    # required, and Py_NotImplemented => not equal
    if res == Py_NotImplemented:
        Py_DECREF(res)
        res = Py_TYPE(other).tp_richcompare(other, this, Py_EQ)
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
    # Attributes are defined in the .pxd file
    DEF DEFAULT_SIZE=1024
    DEF PERTURB_SHIFT=5

    # Note that most of the members on this class are just thunks over to the C
    # api. However, this provides a nice Python/Pyrex api, as well as making it
    # easy to test the C api from pure python.

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

        slot = _lookup(self, key)
        if slot[0] == NULL:
            res = '<null>'
        elif slot[0] == _dummy:
            res = '<dummy>'
        else:
            res = <object>slot[0]
        return <int>(slot - self.table), res

    def __contains__(self, key):
        """Is key present in this StaticTupleInterner."""
        cdef PyObject **slot

        slot = _lookup(self, key)
        if slot[0] == NULL or slot[0] == _dummy:
            return False
        return True

    cdef PyObject *_get(self, object key) except? NULL:
        """Return the object (or nothing) define at the given location."""
        cdef PyObject **slot

        slot = _lookup(self, key)
        if slot[0] == NULL or slot[0] == _dummy:
            return NULL
        return slot[0]

    def __getitem__(self, key):
        """Return a stored item that is equivalent to key."""
        cdef PyObject *py_val

        py_val = self._get(key)
        if py_val == NULL:
            raise KeyError("Key %s is not present" % key)
        val = <object>(py_val)
        return val

    # def __setitem__(self, key, value):
    #     assert key == value
    #     self._add(key)

    cpdef object add(self, key):
        """Similar to set.add(), start tracking this key.
        
        There is one small difference, which is that we return the object that
        is stored at the given location. (which is closer to the
        dict.setdefault() functionality.)
        """
        cdef PyObject **slot, *py_key

        slot = _lookup(self, key)
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
        # No else: clause. If _lookup returns a pointer to
        # a live object, then we already have a value at this location.
        return <object>(slot[0])

    cpdef int discard(self, key) except -1:
        """Remove key from the dict, whether it exists or not.

        :return: 0 if the item did not exist, 1 if it did
        """
        cdef PyObject **slot, *py_key

        slot = _lookup(self, key)
        if slot[0] == NULL or slot[0] == _dummy:
            return 0
        self.used -= 1
        Py_DECREF(slot[0])
        slot[0] = _dummy
        return 1


    def __delitem__(self, key):
        """Remove the given item from the dict.

        Raise a KeyError if the key was not present.
        """
        cdef int exists
        exists = self.discard(key)
        if not exists:
            raise KeyError('Key %s not present' % (key,))


cdef api StaticTupleInterner StaticTupleInterner_New():
    """Create a new StaticTupleInterner object."""
    return StaticTupleInterner()


cdef inline int _check_self_not_none(object self) except -1:
    """Check that the parameter is not None.

    Pyrex/Cython will do type checking, but only to ensure that an object is
    either the right type or None. You can say "object foo not None" for pure
    python functions, but not for C functions.
    So this is just a helper for all the apis that need to do the check.
    """
    if self is None:
        raise TypeError('self must not be None')


cdef inline PyObject **_lookup(StaticTupleInterner self,
                               object key) except NULL:
    """Find the slot where 'key' would fit.

    This is the same as a dicts 'lookup' function.

    :param key: An object we are looking up
    :param hash: The hash for key
    :return: The location in self.table where key should be put
        should never be NULL, but may reference a NULL (PyObject*)
    """
    # This is the heart of most functions, which is why it is pulled out as an
    # cdef inline function.
    cdef size_t i, perturb
    cdef Py_ssize_t mask
    cdef long key_hash
    cdef long this_hash
    cdef PyObject **table, **cur, **free_slot, *py_key

    key_hash = hash(key)
    mask = self.mask
    table = self.table
    i = key_hash & mask
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
        if _is_equal(py_key, key_hash, cur[0]):
            # Both py_key and cur[0] belong in this slot, return it
            return cur
        free_slot = NULL
    # size_t is unsigned, hash is signed...
    perturb = key_hash
    while True:
        i = (i << 2) + i + perturb + 1
        cur = &table[i & mask]
        if cur[0] == NULL: # Found an empty spot
            if free_slot: # Did we find a _dummy earlier?
                return free_slot
            else:
                return cur
        if (cur[0] == py_key # exact match
            or _is_equal(py_key, key_hash, cur[0])): # Equivalent match
            return cur
        if (cur[0] == _dummy and free_slot == NULL):
            free_slot = cur
        perturb >>= PERTURB_SHIFT
    raise AssertionError('should never get here')


cdef api PyObject **_StaticTupleInterner_Lookup(object self,
                                                object key) except NULL:
    """Find the slot where 'key' would fit.

    This is the same as a dicts 'lookup' function. This is a private
    api because mutating what you get without maintaing the other invariants
    is a 'bad thing'.

    :param key: An object we are looking up
    :param hash: The hash for key
    :return: The location in self.table where key should be put
        should never be NULL, but may reference a NULL (PyObject*)
    """
    _check_self_not_none(self)
    return _lookup(self, key)


cdef api object StaticTupleInterner_Add(object self, object key):
    """Add a key to the StaticTupleInterner (set).

    :param self: The StaticTupleInterner to add the key to.
    :param key: The key to be added. If the key is already present,
        self will not be modified
    :return: The current key stored at the location defined by 'key'.
        This may be the same object, or it may be an equivalent object.
        (consider dict.setdefault(key, key))
    """
    cdef StaticTupleInterner true_self
    _check_self_not_none(self)
    true_self = self
    return true_self.add(key)
    

cdef api bint StaticTupleInterner_Contains(object self, object key) except -1:
    """Is key present in self?"""
    cdef StaticTupleInterner true_self
    _check_self_not_none(self)
    true_self = self
    return key in true_self


cdef api int StaticTupleInterner_Discard(StaticTupleInterner self,
                                         object key) except -1:
    """Remove the object referenced at location 'key'.

    :param self: The StaticTupleInterner being modified
    :param key: The key we are checking on
    :return: 1 if there was an object present, 0 if there was not, and -1 on
        error.
    """
    cdef StaticTupleInterner true_self
    _check_self_not_none(self)
    true_self = self
    return true_self.discard(key)


cdef api PyObject *StaticTupleInterner_Get(StaticTupleInterner self,
                                           object key) except? NULL:
    """Get a pointer to the object present at location 'key'.

    This returns an object which is equal to key which was previously added to
    self. This returns a borrowed reference, as it may also return NULL if no
    value is present at that location.

    :param key: The value we are looking for
    :return: The object present at that location
    """
    cdef StaticTupleInterner true_self
    _check_self_not_none(self)
    true_self = self
    return true_self._get(key)


cdef api Py_ssize_t StaticTupleInterner_Size(object self) except -1:
    """Get the number of active entries in 'self'"""
    cdef StaticTupleInterner true_self = self
    _check_self_not_none(self)
    return true_self.used
