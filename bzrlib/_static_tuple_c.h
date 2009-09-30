/* Copyright (C) 2009 Canonical Ltd
 * 
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#include <Python.h>

#if !defined(StaticTupleAPI_FUNC)
#  if defined(_WIN32)
#    define StaticTupleAPI_FUNC(RTYPE) __declspec(dllexport) RTYPE
#  else
#    define StaticTupleAPI_FUNC(RTYPE) RTYPE
#  endif
#endif

#define STATIC_TUPLE_HAS_HASH 0
/* Caching the hash adds memory, but allows us to save a little time during
 * lookups. TIMEIT hash(key) shows it as
 *  0.108usec w/ hash
 *  0.160usec w/o hash
 * Note that the entries themselves are strings, which already cache their
 * hashes. So while there is a 1.5:1 difference in the time for hash(), it is
 * already a function which is quite fast. Probably the only reason we might
 * want to do so, is if we implement a KeyIntern dict that assumes it is
 * available, and can then drop the 'hash' value from the item pointers. Then
 * again, if Key_hash() is fast enough, we may not even care about that.
 */

/* This defines a single variable-width key.
 * It is basically the same as a tuple, but
 * 1) Lighter weight in memory
 * 2) Only supports strings.
 * It is mostly used as a helper. Note that Keys() is a similar structure for
 * lists of Key objects. Its main advantage, though, is that it inlines all of
 * the Key objects so that you have 1 python object overhead for N Keys, rather
 * than N objects.
 */

#define STATIC_TUPLE_INTERNED_FLAG 0x01
typedef struct {
    PyObject_HEAD
    unsigned char size;
    unsigned char flags;
    unsigned char _unused0;
    unsigned char _unused1;
    // Note that on 64-bit, we actually have 4-more unused bytes
    // because key_bits will always be aligned to a 64-bit boundary
#if STATIC_TUPLE_HAS_HASH
    long hash;
#endif
    PyObject *key_bits[1];
} StaticTuple;
extern PyTypeObject StaticTuple_Type;

/* TODO: we need to change this into an api table, look at the python extension
 *       docs.
 */
StaticTupleAPI_FUNC(PyObject *) StaticTuple_New(Py_ssize_t size);

typedef struct {
    PyObject_VAR_HEAD
    PyObject *table[1];
} KeyIntern;
extern PyTypeObject StaticTuple_Type;

#define StaticTuple_CheckExact(op) (Py_TYPE(op) == &StaticTuple_Type)
#define StaticTuple_SET_ITEM(key, offset, val) \
    ((((StaticTuple*)(key))->key_bits[(offset)]) = ((PyObject *)(val))
#define StaticTuple_GET_ITEM(key, offset) (((StaticTuple*)key)->key_bits[offset])

