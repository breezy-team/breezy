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

#include "python-compat.h"

#if defined(__GNUC__)
#   define inline __inline__
#elif defined(_MSC_VER)
#   define inline __inline
#else
#   define inline
#endif


/* This defines a single variable-width key.
 * It is basically the same as a tuple, but
 * 1) Lighter weight in memory
 * 2) Only supports strings.
 * It is mostly used as a helper. Note that Keys() is a similar structure for
 * lists of Key objects. Its main advantage, though, is that it inlines all of
 * the Key objects so that you have 1 python object overhead for N Keys, rather
 * than N objects.
 */
typedef struct {
    PyObject_VAR_HEAD
    PyStringObject *key_strings[1];
} Key;
extern PyTypeObject KeyType;

/* Because of object alignment, it seems that using unsigned char doesn't make
 * things any smaller than using an 'int'... :(
 * Perhaps we should use the high bits for extra flags?
 */
typedef struct {
    PyObject_HEAD
    // unsigned char key_width;
    // unsigned char num_keys;
    // unsigned char flags; /* not used yet */
    unsigned int info; /* Broken down into 4 1-byte fields */
    PyStringObject *key_strings[1]; /* key_width * num_keys entries */
} Keys;

/* Forward declaration */
extern PyTypeObject KeysType;
static PyObject *Keys_item(Keys *self, Py_ssize_t offset);


static PyObject *
Key_as_tuple(Key *self)
{
    PyObject *tpl = NULL, *obj = NULL;
    Py_ssize_t i;

    tpl = PyTuple_New(self->ob_size);
    if (!tpl) {
        /* Malloc failure */
        return NULL;
    }
    for (i = 0; i < self->ob_size; ++i) {
        obj = (PyObject *)self->key_strings[i];
        Py_INCREF(obj);
        PyTuple_SET_ITEM(tpl, i, obj);
    }
    return tpl;
}

static char Key_as_tuple_doc[] = "as_tuple() => tuple";

static void
Key_dealloc(Key *self)
{
    Py_ssize_t i;

    for (i = 0; i < self->ob_size; ++i) {
        Py_XDECREF(self->key_strings[i]);
    }
    Py_TYPE(self)->tp_free((PyObject *)self);
}


static PyObject *
Key_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    Key *self;
    PyObject *obj = NULL;
    Py_ssize_t i, len = 0;

    if (type != &KeyType) {
        PyErr_SetString(PyExc_TypeError, "we only support creating Key");
        return NULL;
    }
    if (!PyTuple_CheckExact(args)) {
        PyErr_SetString(PyExc_TypeError, "args must be a tuple");
        return NULL;
    }
    len = PyTuple_GET_SIZE(args);
    if (len <= 0 || len > 256) {
        /* Too big or too small */
        PyErr_SetString(PyExc_ValueError, "Key.__init__(...)"
            " takes from 1 to 256 key bits");
        return NULL;
    }
    self = (Key *)(type->tp_alloc(type, len));
    self->ob_size = len;
    for (i = 0; i < len; ++i) {
        obj = PyTuple_GET_ITEM(args, i);
        if (!PyString_CheckExact(obj)) {
            PyErr_SetString(PyExc_TypeError, "Key.__init__(...)"
                " requires that all key bits are strings.");
            /* TODO: What is the proper way to dealloc ? */
            type->tp_dealloc((PyObject *)self);
            return NULL;
        }
        Py_INCREF(obj);
        self->key_strings[i] = (PyStringObject *)obj;
    }
    return (PyObject *)self;
}

static Py_ssize_t
Key_length(Key *self)
{
    return self->ob_size;
}

static PyObject *
Key_item(Key *self, Py_ssize_t offset)
{
    PyObject *obj;
    if (offset < 0 || offset > self->ob_size) {
        PyErr_SetString(PyExc_IndexError, "Key index out of range");
        return NULL;
    }
    obj = (PyObject *)self->key_strings[offset];
    Py_INCREF(obj);
    return obj;
}

static char Key_doc[] =
    "C implementation of a Key structure."
    "\n This is used as Key(key_bit_1, key_bit_2, key_bit_3, ...)"
    "\n This is similar to tuple, just less flexible in what it"
    "\n supports, but also lighter memory consumption.";

static PyMethodDef Key_methods[] = {
    {"as_tuple", (PyCFunction)Key_as_tuple, METH_NOARGS, Key_as_tuple_doc},
    {NULL, NULL} /* sentinel */
};

static PySequenceMethods Key_as_sequence = {
    (lenfunc)Key_length,            /* sq_length */
    0,                              /* sq_concat */
    0,                              /* sq_repeat */
    (ssizeargfunc)Key_item,         /* sq_item */
    0,                              /* sq_slice */
    0,                              /* sq_ass_item */
    0,                              /* sq_ass_slice */
    0,                              /* sq_contains */
};

static PyTypeObject KeyType = {
    PyObject_HEAD_INIT(NULL)
    0,                                           /* ob_size */
    "Key",                                       /* tp_name */
    sizeof(Key) - sizeof(PyStringObject *),      /* tp_basicsize */
    sizeof(PyObject *),                          /* tp_itemsize */
    (destructor)Key_dealloc,                     /* tp_dealloc */
    0,                                           /* tp_print */
    0,                                           /* tp_getattr */
    0,                                           /* tp_setattr */
    0,                                           /* tp_compare */
    0, //(reprfunc)Keys_repr,                         /* tp_repr */
    0,                                           /* tp_as_number */
    &Key_as_sequence,                            /* tp_as_sequence */
    0,                                           /* tp_as_mapping */
    0, //(hashfunc)Keys_hash,                         /* tp_hash */
    0,                                           /* tp_call */
    0,                                           /* tp_str */
    PyObject_GenericGetAttr,                     /* tp_getattro */
    0,                                           /* tp_setattro */
    0,                                           /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                          /* tp_flags*/
    Key_doc,                                     /* tp_doc */
    // might want to set this, except we don't participate in gc, so it might
    // confuse things
    0,                                           /* tp_traverse */
    0,                                           /* tp_clear */
    // TODO: implement richcompare, we should probably be able to compare vs an
    //       tuple, as well as versus another Keys object.
    0, //Key_richcompare,                             /* tp_richcompare */
    0,                                           /* tp_weaklistoffset */
    // We could implement this as returning tuples of keys...
    0,                                           /* tp_iter */
    0,                                           /* tp_iternext */
    Key_methods,                                 /* tp_methods */
    0,                                           /* tp_members */
    0,                                           /* tp_getset */
    0,                                           /* tp_base */
    0,                                           /* tp_dict */
    0,                                           /* tp_descr_get */
    0,                                           /* tp_descr_set */
    0,                                           /* tp_dictoffset */
    0,                                           /* tp_init */
    0,                                           /* tp_alloc */
    Key_new,                                     /* tp_new */
};

static inline void
Keys_set_info(Keys *self, int key_width,
                          int num_keys, int flags)
{
    self->info = ((unsigned int)key_width)
                 | (((unsigned int) num_keys) << 8)
                 | (((unsigned int) flags) << 24);
}

static inline int 
Keys_get_key_width(Keys *self)
{
    return (int)(self->info & 0xFF);
}

static inline int 
Keys_get_num_keys(Keys *self)
{
    return (int)((self->info >> 8) & 0xFF);
}

static inline int 
Keys_get_flags(Keys *self)
{
    return (int)((self->info >> 24) & 0xFF);
}

#define Keys_CheckExact(op) (Py_TYPE(op) == &KeysType)

static void
Keys_dealloc(Keys *self)
{
    int num_keys;
    num_keys = Keys_get_num_keys(self);
    /* Do we want to use the Py_TRASHCAN_SAFE_BEGIN/END operations? */
    if (num_keys > 0) {
        /* tuple deallocs from the end to the beginning. Not sure why, but
         * we'll do the same here.
         */
        int i;
        for(i = num_keys - 1; i >= 0; --i) {
            Py_XDECREF(self->key_strings[i]);
        }
    }
    Py_TYPE(self)->tp_free((PyObject *)self);
}


static PyObject *
Keys_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    Py_ssize_t num_args;
    Py_ssize_t i;
    long key_width;
    long num_keys;
    long num_key_bits;
    long flags = 0; /* Not used */
    PyObject *obj= NULL;
    Keys *self;

    if (type != &KeysType) {
        PyErr_SetString(PyExc_TypeError, "we only support creating Keys");
        return NULL;
    }
    if (!PyTuple_CheckExact(args)) {
        PyErr_SetString(PyExc_TypeError, "args must be a tuple");
        return NULL;
    }
    num_args = PyTuple_GET_SIZE(args);
    if (num_args < 1) {
        PyErr_SetString(PyExc_TypeError, "Keys.__init__(width, ...)"
            " takes at least two arguments.");
        return NULL;
    }
    key_width = PyInt_AsLong(PyTuple_GET_ITEM(args, 0));
    if (key_width == -1 && PyErr_Occurred()) {
        return NULL;
    }
    if (key_width <= 0) {
        PyErr_SetString(PyExc_ValueError, "Keys.__init__(width, ...)"
            " width should be a positive integer.");
        return NULL;
    }
    if (key_width > 256) {
        PyErr_SetString(PyExc_ValueError, "Keys.__init__(width, ...)"
            " width must be <= 256");
        return NULL;
    }
    /* First arg is the key width, the rest are the actual key items */
    num_key_bits = num_args - 1;
    num_keys = num_key_bits / key_width;
    if (num_keys * key_width != num_key_bits) {
        PyErr_SetString(PyExc_ValueError, "Keys.__init__(width, ...), was"
            " supplied a number of key bits that was not an even multiple"
            " of the key width.");
        return NULL;
    }
    if (num_keys > 256) {
        PyErr_SetString(PyExc_ValueError, "Keys.__init__(width, ...), was"
            " supplied more than 256 keys");
        return NULL;
    }
    self = (Keys *)(type->tp_alloc(type, num_key_bits));
    // self->key_width = (unsigned char)key_width;
    // self->num_keys = (unsigned char)num_keys;
    Keys_set_info(self, key_width, num_keys, flags);
    for (i = 0; i < num_key_bits; i++) {
        obj = PyTuple_GET_ITEM(args, i + 1);
        if (!PyString_CheckExact(obj)) {
            PyErr_SetString(PyExc_TypeError, "Keys.__init__(width, ...)"
                " requires that all key bits are strings.");
            /* TODO: What is the proper way to dealloc ? */
            type->tp_dealloc((PyObject *)self);
            return NULL;
        }
        Py_INCREF(obj);
        self->key_strings[i] = (PyStringObject *)obj;
    }
    return (PyObject *)self;
}

static PyObject *
Keys_as_tuple(Keys *self)
{
    PyObject *as_tuple = NULL;
    PyObject *a_key = NULL;
    Py_ssize_t i;
    int num_keys;

    num_keys = Keys_get_num_keys(self);
    as_tuple = PyTuple_New(num_keys);
    if (as_tuple == NULL) {
        return NULL;
    }
    for (i = 0; i < num_keys; ++i) {
        a_key = Keys_item(self, i);
        if (a_key == NULL) {
            goto Err;
        }
        PyTuple_SET_ITEM(as_tuple, i, a_key);
    }
    return as_tuple;
Err:
    Py_XDECREF(as_tuple);
    return NULL;
}

static long
Keys_hash(Keys *self)
{
    PyObject *as_tuple = NULL;
    long hash = -1;

    as_tuple = Keys_as_tuple(self);
    if (as_tuple == NULL) {
        return -1;
    }
    hash = PyTuple_Type.tp_hash(as_tuple);
    Py_DECREF(as_tuple);
    return hash;
}

static PyObject *
Keys_richcompare(PyObject *v, PyObject *w, int op)
{
    PyObject *vt, *wt;
    PyObject *vt_to_decref = NULL, *wt_to_decref = NULL;
    PyObject *result;
    
    if (Keys_CheckExact(v)) {
        vt = Keys_as_tuple((Keys *)v);
        vt_to_decref = vt;
    } else if (PyTuple_Check(v)) {
        vt = v;
        vt_to_decref = NULL;
    } else {
        Py_INCREF(Py_NotImplemented);
        return Py_NotImplemented;
    }
    if (Keys_CheckExact(w)) {
        wt = Keys_as_tuple((Keys *)w);
        wt_to_decref = wt;
    } else if (PyTuple_Check(w)) {
        wt = w;
        wt_to_decref = NULL;
    } else {
        Py_XDECREF(vt_to_decref);
        Py_INCREF(Py_NotImplemented);
        return Py_NotImplemented;
    }
    /* Now we have 2 tuples to compare, do it */
    result = PyTuple_Type.tp_richcompare(vt, wt, op);
    Py_XDECREF(vt_to_decref);
    Py_XDECREF(wt_to_decref);
    return result;
}

static PyObject *
Keys_repr(Keys *self)
{
    PyObject *as_tpl;
    PyObject *result;

    as_tpl = Keys_as_tuple(self);
    if (as_tpl == NULL) {
        return NULL;
    }
    result = PyObject_Repr(as_tpl);
    Py_DECREF(as_tpl);
    return result;
}

static char Keys_doc[] =
    "C implementation of a Keys structure."
    "\n This is used as Keys(width, key_bit_1, key_bit_2, key_bit_3, ...)"
    "\n For example, to do a single entry, you would do:"
    "\n  Keys(1, 'foo')"
    "\n For a file-key style entry you would do:"
    "\n  Keys(2, 'file-id', 'revision-id')"
    "\n For a parents list of file keys you would do:"
    "\n  Keys(2, 'file-id', 'rev-id1', 'file-id', 'rev-id2')";


static Py_ssize_t
Keys_length(Keys *self)
{
    return (Py_ssize_t)Keys_get_num_keys(self);
}


static PyObject *
Keys_item(Keys *self, Py_ssize_t offset)
{
    long start, i;
    int key_width;
    PyObject *tpl, *obj;

    if (offset < 0 || offset >= Keys_get_num_keys(self)) {
        PyErr_SetString(PyExc_IndexError, "Keys index out of range");
        return NULL;
    }
    key_width = Keys_get_key_width(self);
    tpl = PyTuple_New(key_width);
    if (!tpl) {
        /* Malloc failure */
        return NULL;
    }
    start = offset * key_width;
    for (i = 0; i < key_width; ++i) {
        obj = (PyObject *)self->key_strings[start + i];
        Py_INCREF(obj);
        PyTuple_SET_ITEM(tpl, i, obj);
    }
    return tpl;
}


static char Keys_as_tuple_doc[] = "as_tuple() => tuple";

static PyMethodDef Keys_methods[] = {
    {"as_tuple", (PyCFunction)Keys_as_tuple, METH_NOARGS, Keys_as_tuple_doc},
    {NULL, NULL} /* sentinel */
};

static PySequenceMethods Keys_as_sequence = {
    (lenfunc)Keys_length,           /* sq_length */
    0,                              /* sq_concat */
    0,                              /* sq_repeat */
    (ssizeargfunc)Keys_item,        /* sq_item */
    0,                              /* sq_slice */
    0,                              /* sq_ass_item */
    0,                              /* sq_ass_slice */
    0,                              /* sq_contains */
};

static PyTypeObject KeysType = {
    PyObject_HEAD_INIT(NULL)
    0,                                           /* ob_size */
    "Keys",                                      /* tp_name */
    sizeof(Keys) - sizeof(PyStringObject *),     /* tp_basicsize */
    sizeof(PyObject *),                          /* tp_itemsize */
    (destructor)Keys_dealloc,                    /* tp_dealloc */
    0,                                           /* tp_print */
    0,                                           /* tp_getattr */
    0,                                           /* tp_setattr */
    0,                                           /* tp_compare */
    // TODO: implement repr() and possibly str()
    (reprfunc)Keys_repr,                         /* tp_repr */
    0,                                           /* tp_as_number */
    &Keys_as_sequence,                           /* tp_as_sequence */
    0,                                           /* tp_as_mapping */
    (hashfunc)Keys_hash,                         /* tp_hash */
    0,                                           /* tp_call */
    0,                                           /* tp_str */
    PyObject_GenericGetAttr,                     /* tp_getattro */
    0,                                           /* tp_setattro */
    0,                                           /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                          /* tp_flags*/
    Keys_doc,                                    /* tp_doc */
    // might want to set this, except we don't participate in gc, so it might
    // confuse things
    0,                                           /* tp_traverse */
    0,                                           /* tp_clear */
    // TODO: implement richcompare, we should probably be able to compare vs an
    //       tuple, as well as versus another Keys object.
    Keys_richcompare,                            /* tp_richcompare */
    0,                                           /* tp_weaklistoffset */
    // We could implement this as returning tuples of keys...
    0,                                           /* tp_iter */
    0,                                           /* tp_iternext */
    Keys_methods,                                /* tp_methods */
    0,                                           /* tp_members */
    0,                                           /* tp_getset */
    0,                                           /* tp_base */
    0,                                           /* tp_dict */
    0,                                           /* tp_descr_get */
    0,                                           /* tp_descr_set */
    0,                                           /* tp_dictoffset */
    0,                                           /* tp_init */
    0,                                           /* tp_alloc */
    Keys_new,                                    /* tp_new */
};

static PyMethodDef keys_type_c_methods[] = {
//    {"unique_lcs_c", py_unique_lcs, METH_VARARGS},
//    {"recurse_matches_c", py_recurse_matches, METH_VARARGS},
    {NULL, NULL}
};


PyMODINIT_FUNC
init_keys_type_c(void)
{
    PyObject* m;

    if (PyType_Ready(&KeyType) < 0)
        return;
    if (PyType_Ready(&KeysType) < 0)
        return;

    m = Py_InitModule3("_keys_type_c", keys_type_c_methods,
                       "C implementation of a Keys structure");
    if (m == NULL)
      return;

    Py_INCREF(&KeyType);
    PyModule_AddObject(m, "Key", (PyObject *)&KeyType);
    Py_INCREF(&KeysType);
    PyModule_AddObject(m, "Keys", (PyObject *)&KeysType);
}
