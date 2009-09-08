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


/* Because of object alignment, it seems that using unsigned char doesn't make
 * things any smaller than using an 'int'... :(
 * Perhaps we should use the high bits for extra flags?
 */
typedef struct {
    PyObject_VAR_HEAD
    int key_width;
    PyStringObject *key_strings[1]; /* key_width * num_keys entries */
} Keys;

/* Forward declaration */
extern PyTypeObject KeysType;

static void
Keys_dealloc(Keys *keys)
{
    /* Do we want to use the Py_TRASHCAN_SAFE_BEGIN/END operations? */
    if (keys->ob_size > 0) {
        /* tuple deallocs from the end to the beginning. Not sure why, but
         * we'll do the same here.
         */
        int i;
        for(i = keys->ob_size - 1; i >= 0; --i) {
            Py_XDECREF(keys->key_strings[i]);
        }
    }
    Py_TYPE(keys)->tp_free((PyObject *)keys);
}


static PyObject *
Keys_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    Py_ssize_t num_args;
    Py_ssize_t i;
    long key_width;
    long num_keys;
    long num_key_bits;
	PyObject *obj= NULL;
    Keys *self;

	if (type != &KeysType) {
        PyErr_SetString(PyExc_TypeError, "we only support creating Keys");
        PyErr_BadInternalCall();
        return NULL;
    }
    if (!PyTuple_CheckExact(args)) {
        PyErr_SetString(PyExc_TypeError, "args must be a tuple");
        return NULL;
    }
    num_args = PyTuple_GET_SIZE(args);
    if (num_args < 1) {
        PyErr_SetString(PyExc_TypeError, "Keys.__init__(width, ...) takes at"
            " least one argument.");
        return NULL;
    }
    key_width = PyInt_AsLong(PyTuple_GET_ITEM(args, 0));
    if (key_width == -1 && PyErr_Occurred()) {
        return NULL;
    }
    if (key_width <= 0) {
        PyErr_SetString(PyExc_ValueError, "Keys.__init__(width, ...), width"
            " should be a positive integer.");
        return NULL;
    }
    if (key_width > 256) {
        PyErr_SetString(PyExc_ValueError, "Keys.__init__(width, ...), width"
            " must be <= 256");
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
    self->key_width = (unsigned char)key_width;
    self->ob_size = (unsigned char)num_keys;
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
Keys_length(Keys *k)
{
    return (Py_ssize_t)k->ob_size;
}


static PyObject *
Keys_item(Keys *self, Py_ssize_t offset)
{
    long start, i;
    PyObject *tpl, *obj;

    if (offset < 0 || offset >= self->ob_size) {
        PyErr_SetString(PyExc_IndexError, "Keys index out of range");
        return NULL;
    }
    tpl = PyTuple_New(self->key_width);
    if (!tpl) {
        /* Malloc failure */
        return NULL;
    }
    start = offset * self->key_width;
    for (i = 0; i < self->key_width; ++i) {
        obj = (PyObject *)self->key_strings[start + i];
        Py_INCREF(obj);
        PyTuple_SET_ITEM(tpl, i, obj);
    }
    return tpl;
}


static char Keys_get_key_doc[] = "get_keys(offset)";

static PyMethodDef Keys_methods[] = {
    {NULL, NULL} /* sentinel */
};

static PySequenceMethods Keys_as_sequence = {
	(lenfunc)Keys_length,			/* sq_length */
	0,		                        /* sq_concat */
	0,		                        /* sq_repeat */
	(ssizeargfunc)Keys_item,		/* sq_item */
	0,		                        /* sq_slice */
	0,					            /* sq_ass_item */
	0,					            /* sq_ass_slice */
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
    0,                                           /* tp_repr */
    0,                                           /* tp_as_number */
    &Keys_as_sequence,                            /* tp_as_sequence */
    0,                                           /* tp_as_mapping */
    0,                                           /* tp_hash */
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
    // Probably worth implementing
    0,                                           /* tp_richcompare */
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

    if (PyType_Ready(&KeysType) < 0)
        return;

    m = Py_InitModule3("_keys_type_c", keys_type_c_methods,
                       "C implementation of a Keys structure");
    if (m == NULL)
      return;

    Py_INCREF(&KeysType);
    PyModule_AddObject(m, "Keys", (PyObject *)&KeysType);
}
