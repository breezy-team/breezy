/* Copyright (C) 2009, 2010 Canonical Ltd
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
#include <string.h>

#define STATIC_TUPLE_HAS_HASH 0
/* Caching the hash adds memory, but allows us to save a little time during
 * lookups. TIMEIT hash(key) shows it as
 *  0.108usec w/ hash
 *  0.160usec w/o hash
 * Note that the entries themselves are strings, which already cache their
 * hashes. So while there is a 1.5:1 difference in the time for hash(), it is
 * already a function which is quite fast. Probably the only reason we might
 * want to do so, is if we customized SimpleSet to the point that the item
 * pointers were exactly certain types, and then accessed table[i]->hash
 * directly. So far StaticTuple_hash() is fast enough to not warrant the memory
 * difference.
 */

/* This defines a single variable-width key.
 * It is basically the same as a tuple, but
 * 1) Lighter weight in memory
 * 2) Only supports strings or other static types (that don't reference other
 *    objects.)
 */

#define STATIC_TUPLE_INTERNED_FLAG 0x01
typedef struct {
    PyObject_HEAD
    // We could go with unsigned short here, and support 64k width tuples
    // without any memory impact, might be worthwhile
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

#define StaticTuple_SET_ITEM(key, offset, val) \
    ((((StaticTuple*)(key))->items[(offset)]) = ((PyObject *)(val)))
#define StaticTuple_GET_ITEM(key, offset) (((StaticTuple*)key)->items[offset])
#define StaticTuple_GET_SIZE(key) (((StaticTuple*)key)->size)


#ifdef STATIC_TUPLE_MODULE
/* Used when compiling _static_tuple_c.c */

static StaticTuple * StaticTuple_New(Py_ssize_t);
static StaticTuple * StaticTuple_Intern(StaticTuple *self);
static StaticTuple * StaticTuple_FromSequence(PyObject *);
#define StaticTuple_CheckExact(op) (Py_TYPE(op) == &StaticTuple_Type)

#else
/* Used as the foreign api */

#include "_import_c_api.h"

static StaticTuple *(*StaticTuple_New)(Py_ssize_t);
static StaticTuple *(*StaticTuple_Intern)(StaticTuple *);
static StaticTuple *(*StaticTuple_FromSequence)(PyObject *);
static PyTypeObject *_p_StaticTuple_Type;

#define StaticTuple_CheckExact(op) (Py_TYPE(op) == _p_StaticTuple_Type)
static int (*_StaticTuple_CheckExact)(PyObject *);


/* Return -1 and set exception on error, 0 on success */
static int
import_static_tuple_c(void)
{
    struct function_description functions[] = {
        {"StaticTuple_New", (void **)&StaticTuple_New,
            "StaticTuple *(Py_ssize_t)"},
        {"StaticTuple_Intern", (void **)&StaticTuple_Intern,
            "StaticTuple *(StaticTuple *)"},
        {"StaticTuple_FromSequence", (void **)&StaticTuple_FromSequence,
            "StaticTuple *(PyObject *)"},
        {"_StaticTuple_CheckExact", (void **)&_StaticTuple_CheckExact,
            "int(PyObject *)"},
        {NULL}};
    struct type_description types[] = {
        {"StaticTuple", &_p_StaticTuple_Type},
        {NULL}};
    return _import_extension_module("breezy.bzr._static_tuple_c",
        functions, types);
}

#endif // !STATIC_TUPLE_MODULE
#endif // !_STATIC_TUPLE_H_
