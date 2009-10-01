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
#include <string.h>

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

#define StaticTuple_CheckExact(op) (Py_TYPE(op) == &StaticTuple_Type)
#define StaticTuple_SET_ITEM(key, offset, val) \
    ((((StaticTuple*)(key))->items[(offset)]) = ((PyObject *)(val)))
#define StaticTuple_GET_ITEM(key, offset) (((StaticTuple*)key)->items[offset])


static const char *_C_API_NAME = "_C_API";

#ifdef STATIC_TUPLE_MODULE
/* Used when compiling _static_tuple_c.c */

static StaticTuple * StaticTuple_New(Py_ssize_t);
static StaticTuple * StaticTuple_intern(StaticTuple *self);

#else
/* Used as the foreign api */

static StaticTuple *(*StaticTuple_New)(Py_ssize_t);
static StaticTuple *(*StaticTuple_intern)(StaticTuple *);
static PyTypeObject *_p_StaticTuple_Type;

#define StaticTuple_CheckExact(op) (Py_TYPE(op) == _p_StaticTuple_Type)
static int (*_StaticTuple_CheckExact)(PyObject *);


static int _import_function(PyObject *module, char *funcname,
                            void **f, char *signature)
{
    PyObject *d = NULL;
    PyObject *c_obj = NULL;
    char *desc = NULL;

    d = PyObject_GetAttrString(module, _C_API_NAME);
    if (!d) {
        // PyObject_GetAttrString sets an appropriate exception
        goto bad;
    }
    c_obj = PyDict_GetItemString(d, funcname);
    if (!c_obj) {
        // PyDict_GetItemString does not set an exception
        PyErr_Format(PyExc_AttributeError,
            "Module %s did not export a function named %s\n",
            PyModule_GetName(module), funcname);
        goto bad;
    }
    desc = (char *)PyCObject_GetDesc(c_obj);
    if (!desc || strcmp(desc, signature) != 0) {
        if (desc == NULL) {
            desc = "<null>";
        }
        PyErr_Format(PyExc_TypeError,
            "C function %s.%s has wrong signature (expected %s, got %s)",
                PyModule_GetName(module), funcname, signature, desc);
        goto bad;
    }
    *f = PyCObject_AsVoidPtr(c_obj);
    Py_DECREF(d);
    return 0;
bad:
    Py_XDECREF(d);
    return -1;
}


static PyTypeObject *
_import_type(PyObject *module, char *class_name)
{
    PyObject *type = NULL;

    type = PyObject_GetAttrString(module, class_name);
    if (!type) {
        goto bad;
    }
    if (!PyType_Check(type)) {
        PyErr_Format(PyExc_TypeError,
            "%s.%s is not a type object",
            PyModule_GetName(module), class_name);
        goto bad;
    }
    return (PyTypeObject *)type;
bad:
    Py_XDECREF(type);
    return NULL;
}


/* Return -1 and set exception on error, 0 on success */
static int
import_static_tuple_c(void)
{
    /* This is modeled after the implementation in Pyrex, which uses a
     * dictionary and descriptors, rather than using plain offsets into a
     * void ** array.
     */
    PyObject *module = NULL;
    
    module = PyImport_ImportModule("bzrlib._static_tuple_c");
    if (!module) goto bad;
    if (_import_function(module, "StaticTuple_New", (void **)&StaticTuple_New,
                         "StaticTuple *(Py_ssize_t)") < 0)
        goto bad;
    if (_import_function(module, "StaticTuple_intern",
                         (void **)&StaticTuple_intern,
                         "StaticTuple *(StaticTuple *)") < 0)
        goto bad;
    if (_import_function(module, "_StaticTuple_CheckExact",
                         (void **)&_StaticTuple_CheckExact,
                         "int(PyObject *)") < 0)
        goto bad;
    _p_StaticTuple_Type = _import_type(module, "StaticTuple");
    if (!_p_StaticTuple_Type) {
        goto bad;
    }
    Py_DECREF(module); 
    return 0;
bad:
    Py_XDECREF(module);
    return -1;
}

#endif // !STATIC_TUPLE_MODULE
#endif // !_STATIC_TUPLE_H_
