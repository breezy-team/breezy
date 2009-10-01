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

#ifndef _STATIC_TUPLE_H_
#define _STATIC_TUPLE_H_
#include <Python.h>

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
#define STATIC_TUPLE_ALL_STRING    0x02
#define STATIC_TUPLE_DID_HASH      0x04
typedef struct {
    PyObject_HEAD
    unsigned char size;
    unsigned char flags;
    unsigned char _unused0;
    unsigned char _unused1;
    // Note that on 64-bit, we actually have 4-more unused bytes
    // because items will always be aligned to a 64-bit boundary
#if STATIC_TUPLE_HAS_HASH
    long hash;
#endif
    PyObject *items[0];
} StaticTuple;
extern PyTypeObject StaticTuple_Type;

typedef struct {
    PyObject_VAR_HEAD
    PyObject *table[0];
} KeyIntern;
// extern PyTypeObject StaticTuple_Type;

#define StaticTuple_CheckExact(op) (Py_TYPE(op) == &StaticTuple_Type)
#define StaticTuple_SET_ITEM(key, offset, val) \
    ((((StaticTuple*)(key))->items[(offset)]) = ((PyObject *)(val)))
#define StaticTuple_GET_ITEM(key, offset) (((StaticTuple*)key)->items[offset])


/* C API Functions */
#define StaticTuple_New_NUM 0
#define StaticTuple_intern_NUM 1
#define StaticTuple_CheckExact_NUM 2

/* Total number of C API Pointers */
#define StaticTuple_API_pointers 3

#ifdef STATIC_TUPLE_MODULE
/* Used when compiling _static_tuple_c.c */

static StaticTuple * StaticTuple_New(Py_ssize_t);
static StaticTuple * StaticTuple_intern(StaticTuple *self);

#else
/* Used by foriegn callers */
static void **StaticTuple_API;

static StaticTuple *(*StaticTuple_New)(Py_ssize_t);
static StaticTuple *(*StaticTuple_intern)(StaticTuple *);
#undef StaticTuple_CheckExact
static int (*StaticTuple_CheckExact)(PyObject *);


/* Return -1 and set exception on error, 0 on success */
static int
import_static_tuple(void)
{
    PyObject *module = PyImport_ImportModule("bzrlib._static_tuple_c");
    PyObject *c_api_object;

    if (module == NULL) {
        fprintf(stderr, "Failed to find module _static_tuple_c.\n");
        return -1;
    }
    c_api_object = PyObject_GetAttrString(module, "_C_API");
    if (c_api_object == NULL) {
        fprintf(stderr, "Failed to find _static_tuple_c._C_API.\n");
        return -1;
    }
    if (!PyCObject_Check(c_api_object)) {
        fprintf(stderr, "_static_tuple_c._C_API not a CObject.\n");
        Py_DECREF(c_api_object);
        return -1;
    }
    StaticTuple_API = (void **)PyCObject_AsVoidPtr(c_api_object);
    StaticTuple_New = StaticTuple_API[StaticTuple_New_NUM];
    StaticTuple_intern = StaticTuple_API[StaticTuple_intern_NUM];
    StaticTuple_CheckExact = StaticTuple_API[StaticTuple_CheckExact_NUM];
    Py_DECREF(c_api_object);
    return 0;
}

#endif
#endif // _STATIC_TUPLE_H_
