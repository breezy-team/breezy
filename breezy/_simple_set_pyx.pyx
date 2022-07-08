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

"""Definition of a class that is similar to Set with some small changes."""

from cpython.object cimport (
    hashfunc,
    Py_EQ,
    PyObject_Hash,
    PyTypeObject,
    Py_TYPE,
    richcmpfunc,
    traverseproc,
    visitproc,
    )
from cpython.mem cimport (
    PyMem_Malloc,
    PyMem_Free,
    )
from cpython.ref cimport (
    Py_INCREF,
    Py_DECREF,
    )
from libc.string cimport memset


# Dummy is an object used to mark nodes that have been deleted. Since
# collisions require us to move a node to an alternative location, if we just
# set an entry to NULL on delete, we won't find any relocated nodes.
# We have to use _dummy_obj because we need to keep a refcount to it, but we
# also use _dummy as a pointer, because it avoids having to put <PyObject*> all
# over the code base.
cdef object _dummy_obj
cdef PyObject *_dummy
_dummy_obj = object()
_dummy = <PyObject *>_dummy_obj


cdef object _NotImplemented
_NotImplemented = NotImplemented


cdef int _is_equal(object this, long this_hash, object other) except -1:
    cdef long other_hash

    other_hash = PyObject_Hash(other)
    if other_hash != this_hash:
        return 0

    # This implements a subset of the PyObject_RichCompareBool functionality.
    # Namely it:
    #   1) Doesn't try to do anything with old-style classes
    #   2) Assumes that both objects have a tp_richcompare implementation, and
    #      that if that is not enough to compare equal, then they are not
    #      equal. (It doesn't try to cast them both to some intermediate form
    #      that would compare equal.)
    res = Py_TYPE(this).tp_richcompare(this, other, Py_EQ)
    if res is _NotImplemented:
        res = Py_TYPE(other).tp_richcompare(other, this, Py_EQ)
        if res is _NotImplemented:
            return 0
    if res:
        return 1
    return 0


cdef public api class SimpleSet [object SimpleSetObject, type SimpleSet_Type]:
    """This class can be used to track canonical forms for objects.

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

    def __init__(self):
        cdef Py_ssize_t size, n_bytes

        size = DEFAULT_SIZE
        self._mask = size - 1
        self._used = 0
        self._fill = 0
        n_bytes = sizeof(PyObject*) * size;
        self._table = <PyObject **>PyMem_Malloc(n_bytes)
        if self._table == NULL:
            raise MemoryError()
        memset(self._table, 0, n_bytes)

    def __sizeof__(self):
        # Note: Pyrex doesn't allow sizeof(class) so we re-implement it here.
        # Bits are:
        #   1: PyObject
        #   2: vtable *
        #   3: 3 Py_ssize_t
        #   4: PyObject**
        # Note that we might get alignment, etc, wrong, but at least this is
        # better than no estimate at all
        # return sizeof(SimpleSet) + (self._mask + 1) * (sizeof(PyObject*))
        return (sizeof(PyObject) + sizeof(void*)
                + 3*sizeof(Py_ssize_t) + sizeof(PyObject**)
                + (self._mask + 1) * sizeof(PyObject*))

    def __dealloc__(self):
        if self._table != NULL:
            PyMem_Free(self._table)
            self._table = NULL

    property used:
        def __get__(self):
            return self._used

    property fill:
        def __get__(self):
            return self._fill

    property mask:
        def __get__(self):
            return self._mask

    def _memory_size(self):
        """Return the number of bytes of memory consumed by this class."""
        return sizeof(self) + (sizeof(PyObject*)*(self._mask + 1))

    def __len__(self):
        return self._used

    def _test_lookup(self, key):
        cdef PyObject **slot

        slot = _lookup(self, key)
        if slot[0] == NULL:
            res = '<null>'
        elif slot[0] == _dummy:
            res = '<dummy>'
        else:
            res = <object>slot[0]
        return <int>(slot - self._table), res

    def __contains__(self, key):
        """Is key present in this SimpleSet."""
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

    cdef int _insert_clean(self, PyObject *key) except -1:
        """Insert a key into self.table.

        This is only meant to be used during times like '_resize',
        as it makes a lot of assuptions about keys not already being present,
        and there being no dummy entries.
        """
        cdef size_t i, n_lookup
        cdef long the_hash
        cdef PyObject **table
        cdef PyObject **slot
        cdef Py_ssize_t mask

        mask = self._mask
        table = self._table

        the_hash = PyObject_Hash(<object>key)
        i = the_hash
        for n_lookup from 0 <= n_lookup <= <size_t>mask: # Don't loop forever
            slot = &table[i & mask]
            if slot[0] == NULL:
                slot[0] = key
                self._fill = self._fill + 1
                self._used = self._used + 1
                return 1
            i = i + 1 + n_lookup
        raise RuntimeError('ran out of slots.')

    def _py_resize(self, min_used):
        """Do not use this directly, it is only exposed for testing."""
        return self._resize(min_used)

    cdef Py_ssize_t _resize(self, Py_ssize_t min_used) except -1:
        """Resize the internal table.

        The final table will be big enough to hold at least min_used entries.
        We will copy the data from the existing table over, leaving out dummy
        entries.

        :return: The new size of the internal table
        """
        cdef Py_ssize_t new_size, n_bytes, remaining
        cdef PyObject **new_table
        cdef PyObject **old_table
        cdef PyObject **slot

        new_size = DEFAULT_SIZE
        while new_size <= min_used and new_size > 0:
            new_size = new_size << 1
        # We rolled over our signed size field
        if new_size <= 0:
            raise MemoryError()
        # Even if min_used == self._mask + 1, and we aren't changing the actual
        # size, we will still run the algorithm so that dummy entries are
        # removed
        # TODO: Test this
        # if new_size < self._used:
        #     raise RuntimeError('cannot shrink SimpleSet to something'
        #                        ' smaller than the number of used slots.')
        n_bytes = sizeof(PyObject*) * new_size;
        new_table = <PyObject **>PyMem_Malloc(n_bytes)
        if new_table == NULL:
            raise MemoryError()

        old_table = self._table
        self._table = new_table
        memset(self._table, 0, n_bytes)
        self._mask = new_size - 1
        self._used = 0
        remaining = self._fill
        self._fill = 0

        # Moving everything to the other table is refcount neutral, so we don't
        # worry about it.
        slot = old_table
        while remaining > 0:
            if slot[0] == NULL: # unused slot
                pass
            elif slot[0] == _dummy: # dummy slot
                remaining = remaining - 1
            else: # active slot
                remaining = remaining - 1
                self._insert_clean(slot[0])
            slot = slot + 1
        PyMem_Free(old_table)
        return new_size

    cpdef object add(self, key):
        """Similar to set.add(), start tracking this key.

        There is one small difference, which is that we return the object that
        is stored at the given location. (which is closer to the
        dict.setdefault() functionality.)
        """
        cdef PyObject **slot
        cdef bint added

        if (Py_TYPE(key).tp_richcompare == NULL
            or Py_TYPE(key).tp_hash == NULL):
            raise TypeError('Types added to SimpleSet must implement'
                            ' both tp_richcompare and tp_hash')
        added = 0
        # We need at least one empty slot
        assert self._used < self._mask
        slot = _lookup(self, key)
        if (slot[0] == NULL):
            Py_INCREF(key)
            self._fill = self._fill + 1
            self._used = self._used + 1
            slot[0] = <PyObject *>key
            added = 1
        elif (slot[0] == _dummy):
            Py_INCREF(key)
            self._used = self._used + 1
            slot[0] = <PyObject *>key
            added = 1
        # No else: clause. If _lookup returns a pointer to
        # a live object, then we already have a value at this location.
        retval = <object>(slot[0])
        # PySet and PyDict use a 2-3rds full algorithm, we'll follow suit
        if added and (self._fill * 3) >= ((self._mask + 1) * 2):
            # However, we always work for a load factor of 2:1
            self._resize(self._used * 2)
        # Even if we resized and ended up moving retval into a different slot,
        # it is still the value that is held at the slot equivalent to 'key',
        # so we can still return it
        return retval

    cpdef bint discard(self, key) except -1:
        """Remove key from the set, whether it exists or not.

        :return: False if the item did not exist, True if it did
        """
        cdef PyObject **slot

        slot = _lookup(self, key)
        if slot[0] == NULL or slot[0] == _dummy:
            return 0
        self._used = self._used - 1
        Py_DECREF(<object>slot[0])
        slot[0] = _dummy
        # PySet uses the heuristic: If more than 1/5 are dummies, then resize
        #                           them away
        #   if ((so->_fill - so->_used) * 5 < so->mask)
        # However, we are planning on using this as an interning structure, in
        # which we will be putting a lot of objects. And we expect that large
        # groups of them are going to have the same lifetime.
        # Dummy entries hurt a little bit because they cause the lookup to keep
        # searching, but resizing is also rather expensive
        # For now, we'll just use their algorithm, but we may want to revisit
        # it
        if ((self._fill - self._used) * 5 > self._mask):
            self._resize(self._used * 2)
        return 1

    def __iter__(self):
        return _SimpleSet_iterator(self)


cdef class _SimpleSet_iterator:
    """Iterator over the SimpleSet structure."""

    cdef Py_ssize_t pos
    cdef SimpleSet set
    cdef Py_ssize_t _used # track if things have been mutated while iterating
    cdef Py_ssize_t len # number of entries left

    def __init__(self, obj):
        self.set = obj
        self.pos = 0
        self._used = self.set._used
        self.len = self.set._used

    def __iter__(self):
        return self

    def __next__(self):
        cdef Py_ssize_t mask, i
        cdef PyObject *key

        if self.set is None:
            raise StopIteration
        if self.set._used != self._used:
            # Force this exception to continue to be raised
            self._used = -1
            raise RuntimeError("Set size changed during iteration")
        if not SimpleSet_Next(self.set, &self.pos, &key):
            self.set = None
            raise StopIteration
        # we found something
        the_key = <object>key # INCREF
        self.len = self.len - 1
        return the_key

    def __length_hint__(self):
        if self.set is not None and self._used == self.set._used:
            return self.len
        return 0


cdef api SimpleSet SimpleSet_New():
    """Create a new SimpleSet object."""
    return SimpleSet()


cdef SimpleSet _check_self(object self):
    """Check that the parameter is not None.

    Pyrex/Cython will do type checking, but only to ensure that an object is
    either the right type or None. You can say "object foo not None" for pure
    python functions, but not for C functions.
    So this is just a helper for all the apis that need to do the check.
    """
    cdef SimpleSet true_self
    if self is None:
        raise TypeError('self must not be None')
    true_self = self
    return true_self


cdef PyObject **_lookup(SimpleSet self, object key) except NULL:
    """Find the slot where 'key' would fit.

    This is the same as a dicts 'lookup' function.

    :param key: An object we are looking up
    :param hash: The hash for key
    :return: The location in self.table where key should be put.
        location == NULL is an exception, but (*location) == NULL just
        indicates the slot is empty and can be used.
    """
    # This uses Quadratic Probing:
    #  http://en.wikipedia.org/wiki/Quadratic_probing
    # with c1 = c2 = 1/2
    # This leads to probe locations at:
    #  h0 = hash(k1)
    #  h1 = h0 + 1
    #  h2 = h0 + 3 = h1 + 1 + 1
    #  h3 = h0 + 6 = h2 + 1 + 2
    #  h4 = h0 + 10 = h2 + 1 + 3
    # Note that all of these are '& mask', but that is computed *after* the
    # offset.
    # This differs from the algorithm used by Set and Dict. Which, effectively,
    # use double-hashing, and a step size that starts large, but dwindles to
    # stepping one-by-one.
    # This gives more 'locality' in that if you have a collision at offset X,
    # the first fallback is X+1, which is fast to check. However, that means
    # that an object w/ hash X+1 will also check there, and then X+2 next.
    # However, for objects with differing hashes, their chains are different.
    # The former checks X, X+1, X+3, ... the latter checks X+1, X+2, X+4, ...
    # So different hashes diverge quickly.
    # A bigger problem is that we *only* ever use the lowest bits of the hash
    # So all integers (x + SIZE*N) will resolve into the same bucket, and all
    # use the same collision resolution. We may want to try to find a way to
    # incorporate the upper bits of the hash with quadratic probing. (For
    # example, X, X+1, X+3+some_upper_bits, X+6+more_upper_bits, etc.)
    cdef size_t i, n_lookup
    cdef Py_ssize_t mask
    cdef long key_hash
    cdef PyObject **table
    cdef PyObject **slot
    cdef PyObject *cur
    cdef PyObject **free_slot

    key_hash = PyObject_Hash(key)
    i = <size_t>key_hash
    mask = self._mask
    table = self._table
    free_slot = NULL
    for n_lookup from 0 <= n_lookup <= <size_t>mask: # Don't loop forever
        slot = &table[i & mask]
        cur = slot[0]
        if cur == NULL:
            # Found a blank spot
            if free_slot != NULL:
                # Did we find an earlier _dummy entry?
                return free_slot
            else:
                return slot
        if cur == <PyObject *>key:
            # Found an exact pointer to the key
            return slot
        if cur == _dummy:
            if free_slot == NULL:
                free_slot = slot
        elif _is_equal(key, key_hash, <object>cur):
            # Both py_key and cur belong in this slot, return it
            return slot
        i = i + 1 + n_lookup
    raise AssertionError('should never get here')


cdef api PyObject **_SimpleSet_Lookup(object self, object key) except NULL:
    """Find the slot where 'key' would fit.

    This is the same as a dicts 'lookup' function. This is a private
    api because mutating what you get without maintaing the other invariants
    is a 'bad thing'.

    :param key: An object we are looking up
    :param hash: The hash for key
    :return: The location in self._table where key should be put
        should never be NULL, but may reference a NULL (PyObject*)
    """
    return _lookup(_check_self(self), key)


cdef api object SimpleSet_Add(object self, object key):
    """Add a key to the SimpleSet (set).

    :param self: The SimpleSet to add the key to.
    :param key: The key to be added. If the key is already present,
        self will not be modified
    :return: The current key stored at the location defined by 'key'.
        This may be the same object, or it may be an equivalent object.
        (consider dict.setdefault(key, key))
    """
    return _check_self(self).add(key)


cdef api int SimpleSet_Contains(object self, object key) except -1:
    """Is key present in self?"""
    return (key in _check_self(self))


cdef api int SimpleSet_Discard(object self, object key) except -1:
    """Remove the object referenced at location 'key'.

    :param self: The SimpleSet being modified
    :param key: The key we are checking on
    :return: 1 if there was an object present, 0 if there was not, and -1 on
        error.
    """
    return _check_self(self).discard(key)


cdef api PyObject *SimpleSet_Get(SimpleSet self, object key) except? NULL:
    """Get a pointer to the object present at location 'key'.

    This returns an object which is equal to key which was previously added to
    self. This returns a borrowed reference, as it may also return NULL if no
    value is present at that location.

    :param key: The value we are looking for
    :return: The object present at that location
    """
    return _check_self(self)._get(key)


cdef api Py_ssize_t SimpleSet_Size(object self) except -1:
    """Get the number of active entries in 'self'"""
    return _check_self(self)._used


cdef api int SimpleSet_Next(object self, Py_ssize_t *pos,
                            PyObject **key) except -1:
    """Walk over items in a SimpleSet.

    :param pos: should be initialized to 0 by the caller, and will be updated
        by this function
    :param key: Will return a borrowed reference to key
    :return: 0 if nothing left, 1 if we are returning a new value
    """
    cdef Py_ssize_t i, mask
    cdef SimpleSet true_self
    cdef PyObject **table
    true_self = _check_self(self)
    i = pos[0]
    if (i < 0):
        return 0
    mask = true_self._mask
    table= true_self._table
    while (i <= mask and (table[i] == NULL or table[i] == _dummy)):
        i = i + 1
    pos[0] = i + 1
    if (i > mask):
        return 0 # All done
    if (key != NULL):
        key[0] = table[i]
    return 1


cdef int SimpleSet_traverse(SimpleSet self, visitproc visit,
                            void *arg) except -1:
    """This is an implementation of 'tp_traverse' that hits the whole table.

    Cython/Pyrex don't seem to let you define a tp_traverse, and they only
    define one for you if you have an 'object' attribute. Since they don't
    support C arrays of objects, we access the PyObject * directly.
    """
    cdef Py_ssize_t pos
    cdef PyObject *next_key
    cdef int ret

    pos = 0
    while SimpleSet_Next(self, &pos, &next_key):
        ret = visit(next_key, arg)
        if ret:
            return ret
    return 0

# It is a little bit ugly to do this, but it works, and means that Meliae can
# dump the total memory consumed by all child objects.
(<PyTypeObject *>SimpleSet).tp_traverse = <traverseproc>SimpleSet_traverse
