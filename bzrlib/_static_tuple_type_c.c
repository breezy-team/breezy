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

#include "Python.h"
#include "_static_tuple_type_c.h"
#include "_static_tuple_pyx_api.h"

#include "python-compat.h"

#if defined(__GNUC__)
#   define inline __inline__
#elif defined(_MSC_VER)
#   define inline __inline
#else
#   define inline
#endif


/* The one and only StaticTuple with no values */
static PyObject *_interned_tuples = NULL;


static inline int
_StaticTuple_is_interned(StaticTuple *self)
{
    return self->flags & STATIC_TUPLE_INTERNED_FLAG;
}



static PyObject *
StaticTuple_as_tuple(StaticTuple *self)
{
    PyObject *tpl = NULL, *obj = NULL;
    int i, len;

    len = self->size;
    tpl = PyTuple_New(len);
    if (!tpl) {
        /* Malloc failure */
        return NULL;
    }
    for (i = 0; i < len; ++i) {
        obj = (PyObject *)self->items[i];
        Py_INCREF(obj);
        PyTuple_SET_ITEM(tpl, i, obj);
    }
    return tpl;
}


static char StaticTuple_as_tuple_doc[] = "as_tuple() => tuple";

static PyObject *
_StaticTuple_intern(StaticTuple *self)
{
    return (PyObject *)StaticTuple_Intern(self);
}

static char StaticTuple_intern_doc[] = "intern() => unique StaticTuple\n"
    "Return a 'canonical' StaticTuple object.\n"
    "Similar to intern() for strings, this makes sure there\n"
    "is only one StaticTuple object for a given value\n."
    "Common usage is:\n"
    "  key = StaticTuple('foo', 'bar').intern()\n";


static void
StaticTuple_dealloc(StaticTuple *self)
{
    int i, len;

    if (_StaticTuple_is_interned(self)) {
        /* revive dead object temporarily for DelItem */
        // Py_REFCNT(self) = 2;
        if (StaticTupleInterner_Discard(_interned_tuples, (PyObject*)self) != 1)
            Py_FatalError("deletion of interned StaticTuple failed");
    }
    len = self->size;
    for (i = 0; i < len; ++i) {
        Py_XDECREF(self->items[i]);
    }
    Py_TYPE(self)->tp_free((PyObject *)self);
}


static PyObject *
StaticTuple_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    StaticTuple *self;
    PyObject *obj = NULL;
    Py_ssize_t i, len = 0;
    int is_all_str;

    if (type != &StaticTuple_Type) {
        PyErr_SetString(PyExc_TypeError, "we only support creating StaticTuple");
        return NULL;
    }
    if (!PyTuple_CheckExact(args)) {
        PyErr_SetString(PyExc_TypeError, "args must be a tuple");
        return NULL;
    }
    len = PyTuple_GET_SIZE(args);
    if (len < 0 || len > 255) {
        /* Too big or too small */
        PyErr_SetString(PyExc_ValueError, "StaticTuple.__init__(...)"
            " takes from 0 to 255 key bits");
        return NULL;
    }
    self = (StaticTuple *)StaticTuple_New(len);
    if (self == NULL) {
        return NULL;
    }
    is_all_str = 1;
    for (i = 0; i < len; ++i) {
        obj = PyTuple_GET_ITEM(args, i);
        if (!PyString_CheckExact(obj)) {
            is_all_str = 0;
            if (!_StaticTuple_CheckExact(obj)) {
                PyErr_SetString(PyExc_TypeError, "StaticTuple.__init__(...)"
                    " requires that all key bits are strings or StaticTuple.");
                /* TODO: What is the proper way to dealloc ? */
                type->tp_dealloc((PyObject *)self);
                return NULL;
            }
        }
        Py_INCREF(obj);
        self->items[i] = obj;
    }
    if (is_all_str) {
        self->flags |= STATIC_TUPLE_ALL_STRING;
    }
    return (PyObject *)self;
}

static PyObject *
StaticTuple_repr(StaticTuple *self)
{
    PyObject *as_tuple, *result;

    as_tuple = StaticTuple_as_tuple(self);
    if (as_tuple == NULL) {
        return NULL;
    }
    result = PyObject_Repr(as_tuple);
    Py_DECREF(as_tuple);
    return result;
}

static long
StaticTuple_hash(StaticTuple *self)
{
    /* adapted from tuplehash(), is the specific hash value considered
     * 'stable'?
     */
	register long x, y;
	Py_ssize_t len = self->size;
	PyObject **p;
	long mult = 1000003L;

#if STATIC_TUPLE_HAS_HASH
    if (self->hash != -1) {
        return self->hash;
    }
#endif
	x = 0x345678L;
	p = self->items;
    if (self->flags & STATIC_TUPLE_ALL_STRING
        && self->flags & STATIC_TUPLE_DID_HASH) {
        /* If we know that we only reference strings, and we've already
         * computed the hash one time before, then we know all the strings will
         * have valid hash entries, and we can just compute, no branching
         * logic.
         */
        while (--len >= 0) {
            y = ((PyStringObject*)(*p))->ob_shash;
            x = (x ^ y) * mult;
            /* the cast might truncate len; that doesn't change hash stability */
            mult += (long)(82520L + len + len);
            p++;
        }
    } else {
        while (--len >= 0) {
            y = PyObject_Hash(*p++);
            if (y == -1) /* failure */
                return -1;
            x = (x ^ y) * mult;
            /* the cast might truncate len; that doesn't change hash stability */
            mult += (long)(82520L + len + len);
        }
    }
	x += 97531L;
	if (x == -1)
		x = -2;
#if STATIC_TUPLE_HAS_HASH
    if (self->hash != -1) {
        if (self->hash != x) {
            fprintf(stderr, "hash changed: %d => %d\n", self->hash, x);
        }
    }
    self->hash = x;
#endif
    self->flags |= STATIC_TUPLE_DID_HASH;
	return x;
}

static PyObject *
StaticTuple_richcompare_to_tuple(StaticTuple *v, PyObject *wt, int op)
{
    PyObject *vt;
    PyObject *result = NULL;
    
    vt = StaticTuple_as_tuple((StaticTuple *)v);
    if (vt == NULL) {
        goto Done;
    }
    if (!PyTuple_Check(wt)) {
        PyErr_BadInternalCall();
        result = NULL;
        goto Done;
    }
    /* Now we have 2 tuples to compare, do it */
    result = PyTuple_Type.tp_richcompare(vt, wt, op);
Done:
    Py_XDECREF(vt);
    return result;
}


static PyObject *
StaticTuple_richcompare(PyObject *v, PyObject *w, int op)
{
    StaticTuple *vk, *wk;
    Py_ssize_t vlen, wlen, min_len, i;
    PyObject *v_obj, *w_obj;
    richcmpfunc string_richcompare;

    if (!_StaticTuple_CheckExact(v)) {
        /* This has never triggered, according to python-dev it seems this
         * might trigger if '__op__' is defined but '__rop__' is not, sort of
         * case. Such as "None == StaticTuple()"
         */
        fprintf(stderr, "self is not StaticTuple\n");
        Py_INCREF(Py_NotImplemented);
        return Py_NotImplemented;
    }
    vk = (StaticTuple *)v;
    if (_StaticTuple_CheckExact(w)) {
        /* The most common case */
        wk = (StaticTuple*)w;
    } else if (PyTuple_Check(w)) {
        /* One of v or w is a tuple, so we go the 'slow' route and cast up to
         * tuples to compare.
         */
        /* TODO: This seems to be triggering more than I thought it would...
         *       We probably want to optimize comparing self to other when
         *       other is a tuple.
         */
        return StaticTuple_richcompare_to_tuple(vk, w, op);
    } else if (w == Py_None) {
        // None is always less than the object
		switch (op) {
		case Py_NE:case Py_GT:case Py_GE:
            Py_INCREF(Py_True);
            return Py_True;
        case Py_EQ:case Py_LT:case Py_LE:
            Py_INCREF(Py_False);
            return Py_False;
		}
    } else {
        /* We don't special case this comparison, we just let python handle
         * it.
         */
         Py_INCREF(Py_NotImplemented);
         return Py_NotImplemented;
    }
    /* Now we know that we have 2 StaticTuple objects, so let's compare them.
     * This code is somewhat borrowed from tuplerichcompare, except we know our
     * objects are limited in scope, so we can inline some comparisons.
     */
    if (v == w) {
        /* Identical pointers, we can shortcut this easily. */
		switch (op) {
		case Py_EQ:case Py_LE:case Py_GE:
            Py_INCREF(Py_True);
            return Py_True;
		case Py_NE:case Py_LT:case Py_GT:
            Py_INCREF(Py_False);
            return Py_False;
		}
    }
    /* TODO: if STATIC_TUPLE_INTERNED_FLAG is set on both objects and they are
     *       not the same pointer, then we know they aren't the same object
     *       without having to do sub-by-sub comparison.
     */

    /* It will be rare that we compare tuples of different lengths, so we don't
     * start by optimizing the length comparision, same as the tuple code
     * TODO: Interning may change this, because we'll be comparing lots of
     *       different StaticTuple objects in the intern dict
     */
    vlen = vk->size;
    wlen = wk->size;
	min_len = (vlen < wlen) ? vlen : wlen;
    string_richcompare = PyString_Type.tp_richcompare;
    for (i = 0; i < min_len; i++) {
        PyObject *result = NULL;
        v_obj = StaticTuple_GET_ITEM(vk, i);
        w_obj = StaticTuple_GET_ITEM(wk, i);
        if (PyString_CheckExact(v_obj) && PyString_CheckExact(w_obj)) {
            result = string_richcompare(v_obj, w_obj, Py_EQ);
        } else if (_StaticTuple_CheckExact(v_obj) &&
                   _StaticTuple_CheckExact(w_obj))
        {
            /* Both are StaticTuple types, so recurse */
            result = StaticTuple_richcompare(v_obj, w_obj, Py_EQ);
        } else {
            /* Not the same type, obviously they won't compare equal */
            break;
        }
        if (result == NULL) {
            return NULL; /* There seems to be an error */
        }
        if (result == Py_NotImplemented) {
            PyErr_BadInternalCall();
            Py_DECREF(result);
            return NULL;
        }
        if (result == Py_False) {
            /* This entry is not identical
             * Shortcut for Py_EQ
             */
            if (op == Py_EQ) {
                return result;
            }
            Py_DECREF(result);
            break;
        }
        if (result != Py_True) {
            /* We don't know *what* richcompare is returning, but it
             * isn't something we recognize
             */
            PyErr_BadInternalCall();
            Py_DECREF(result);
            return NULL;
        }
        Py_DECREF(result);
    }
	if (i >= vlen || i >= wlen) {
        /* We walked off one of the lists, but everything compared equal so
         * far. Just compare the size.
         */
		int cmp;
		PyObject *res;
		switch (op) {
		case Py_LT: cmp = vlen <  wlen; break;
		case Py_LE: cmp = vlen <= wlen; break;
		case Py_EQ: cmp = vlen == wlen; break;
		case Py_NE: cmp = vlen != wlen; break;
		case Py_GT: cmp = vlen >  wlen; break;
		case Py_GE: cmp = vlen >= wlen; break;
		default: return NULL; /* cannot happen */
		}
		if (cmp)
			res = Py_True;
		else
			res = Py_False;
		Py_INCREF(res);
		return res;
	}
    /* The last item differs, shortcut the Py_NE case */
    if (op == Py_NE) {
        Py_INCREF(Py_True);
        return Py_True;
    }
    /* It is some other comparison, go ahead and do the real check. */
    if (PyString_CheckExact(v_obj) && PyString_CheckExact(w_obj))
    {
        return string_richcompare(v_obj, w_obj, op);
    } else if (_StaticTuple_CheckExact(v_obj) &&
               _StaticTuple_CheckExact(w_obj))
    {
        /* Both are StaticTuple types, so recurse */
        return StaticTuple_richcompare(v_obj, w_obj, op);
    } else {
        Py_INCREF(Py_NotImplemented);
        return Py_NotImplemented;
    }
}


static Py_ssize_t
StaticTuple_length(StaticTuple *self)
{
    return self->size;
}


static PyObject *
StaticTuple__is_interned(StaticTuple *self)
{
    if (_StaticTuple_is_interned(self)) {
        Py_INCREF(Py_True);
        return Py_True;
    }
    Py_INCREF(Py_False);
    return Py_False;
}

static char StaticTuple__is_interned_doc[] = "_is_interned() => True/False\n"
    "Check to see if this key has been interned.\n";


static PyObject *
StaticTuple_item(StaticTuple *self, Py_ssize_t offset)
{
    PyObject *obj;
    if (offset < 0 || offset >= self->size) {
        PyErr_SetString(PyExc_IndexError, "StaticTuple index out of range");
        return NULL;
    }
    obj = (PyObject *)self->items[offset];
    Py_INCREF(obj);
    return obj;
}

static PyObject *
StaticTuple_slice(StaticTuple *self, Py_ssize_t ilow, Py_ssize_t ihigh)
{
    PyObject *as_tuple, *result;

    as_tuple = StaticTuple_as_tuple(self);
    if (as_tuple == NULL) {
        return NULL;
    }
    result = PyTuple_Type.tp_as_sequence->sq_slice(as_tuple, ilow, ihigh);
    Py_DECREF(as_tuple);
    return result;
}

static int
StaticTuple_traverse(StaticTuple *self, visitproc visit, void *arg)
{
    Py_ssize_t i;
    for (i = self->size; --i >= 0;) {
        Py_VISIT(self->items[i]);
    }
    return 0;
}

static char StaticTuple_doc[] =
    "C implementation of a StaticTuple structure."
    "\n This is used as StaticTuple(key_bit_1, key_bit_2, key_bit_3, ...)"
    "\n This is similar to tuple, just less flexible in what it"
    "\n supports, but also lighter memory consumption.";

static PyMethodDef StaticTuple_methods[] = {
    {"as_tuple", (PyCFunction)StaticTuple_as_tuple, METH_NOARGS, StaticTuple_as_tuple_doc},
    // set after loading _static_tuple_pyx
    {"intern", (PyCFunction)_StaticTuple_intern, METH_NOARGS, StaticTuple_intern_doc},
    {"_is_interned", (PyCFunction)StaticTuple__is_interned, METH_NOARGS,
     StaticTuple__is_interned_doc},
    {NULL, NULL} /* sentinel */
};

static PySequenceMethods StaticTuple_as_sequence = {
    (lenfunc)StaticTuple_length,            /* sq_length */
    0,                              /* sq_concat */
    0,                              /* sq_repeat */
    (ssizeargfunc)StaticTuple_item,         /* sq_item */
    (ssizessizeargfunc)StaticTuple_slice,   /* sq_slice */
    0,                              /* sq_ass_item */
    0,                              /* sq_ass_slice */
    0,                              /* sq_contains */
};


PyTypeObject StaticTuple_Type = {
    PyObject_HEAD_INIT(NULL)
    0,                                           /* ob_size */
    "StaticTuple",                               /* tp_name */
    sizeof(StaticTuple),                         /* tp_basicsize */
    sizeof(PyObject *),                          /* tp_itemsize */
    (destructor)StaticTuple_dealloc,             /* tp_dealloc */
    0,                                           /* tp_print */
    0,                                           /* tp_getattr */
    0,                                           /* tp_setattr */
    0,                                           /* tp_compare */
    (reprfunc)StaticTuple_repr,                  /* tp_repr */
    0,                                           /* tp_as_number */
    &StaticTuple_as_sequence,                    /* tp_as_sequence */
    0,                                           /* tp_as_mapping */
    (hashfunc)StaticTuple_hash,                  /* tp_hash */
    0,                                           /* tp_call */
    0,                                           /* tp_str */
    PyObject_GenericGetAttr,                     /* tp_getattro */
    0,                                           /* tp_setattro */
    0,                                           /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                          /* tp_flags*/
    StaticTuple_doc,                             /* tp_doc */
    /* gc.get_referents checks the IS_GC flag before it calls tp_traverse
     * And we don't include this object in the garbage collector because we
     * know it doesn't create cycles. However, 'meliae' will follow
     * tp_traverse, even if the object isn't GC, and we want that.
     */
    (traverseproc)StaticTuple_traverse,          /* tp_traverse */
    0,                                           /* tp_clear */
    // TODO: implement richcompare, we should probably be able to compare vs an
    //       tuple, as well as versus another StaticTuples object.
    StaticTuple_richcompare,                     /* tp_richcompare */
    0,                                           /* tp_weaklistoffset */
    // We could implement this as returning tuples of keys...
    0,                                           /* tp_iter */
    0,                                           /* tp_iternext */
    StaticTuple_methods,                         /* tp_methods */
    0,                                           /* tp_members */
    0,                                           /* tp_getset */
    0,                                           /* tp_base */
    0,                                           /* tp_dict */
    0,                                           /* tp_descr_get */
    0,                                           /* tp_descr_set */
    0,                                           /* tp_dictoffset */
    0,                                           /* tp_init */
    0,                                           /* tp_alloc */
    StaticTuple_new,                             /* tp_new */
};


static PyMethodDef static_tuple_c_methods[] = {
//    {"unique_lcs_c", py_unique_lcs, METH_VARARGS},
//    {"recurse_matches_c", py_recurse_matches, METH_VARARGS},
    {NULL, NULL}
};


static void
setup_interned_tuples(PyObject *m)
{
    _interned_tuples = (PyObject *)StaticTupleInterner_New();
    if (_interned_tuples != NULL) {
        Py_INCREF(_interned_tuples);
        PyModule_AddObject(m, "_interned_tuples", _interned_tuples);
    }
}


PyMODINIT_FUNC
init_static_tuple_type_c(void)
{
    PyObject* m;
    fprintf(stderr, "init_static_tuple_type_c\n");

    if (PyType_Ready(&StaticTuple_Type) < 0) {
        fprintf(stderr, "StaticTuple_Type not ready\n");
        return;
    }
    fprintf(stderr, "StaticTuple_Type ready\n");

    m = Py_InitModule3("_static_tuple_type_c", static_tuple_c_methods,
                       "C implementation of a StaticTuple structure");
    if (m == NULL)
      return;

    Py_INCREF(&StaticTuple_Type);
    PyModule_AddObject(m, "StaticTuple", (PyObject *)&StaticTuple_Type);
    fprintf(stderr, "added the StaticTuple type, importing _static_tuple_pyx\n");
    if (import_bzrlib___static_tuple_pyx() == -1) {
        PyObject *m2;
        fprintf(stderr, "Failed to import_bzrlib___static_tuple_pyx.\n");
        // PyErr_SetString(PyExc_ImportError,
        //                 "Failed to import _static_tuple_pyx");

        // m2 = PyImport_ImportModule("bzrlib._static_tuple_pyx");
        // if (m2 == NULL) {
        //     fprintf(stderr, "Failed to import bzrlib._static_tuple_pyx\n");
        // }
        // Py_INCREF(&StaticTuple_Type);
        // if (PyModule_AddObject(m2, "StaticTuple", (PyObject
        //     *)&StaticTuple_Type) == -1) {
        //     fprintf(stderr, "Failed to add StaticTuple to bzrlib._static_tuple_pyx\n");
        // }
        return;
    }
    if (PyErr_Occurred()) {
        fprintf(stderr, "an exception has occurred\n");
    }
    fprintf(stderr, "imported successfully\n");
}
