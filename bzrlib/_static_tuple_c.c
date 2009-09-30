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

/* Must be defined before importing _static_tuple_c.h so that we get the right
 * linkage.
 */
#if defined(_WIN32)
#  define KeysAPI_FUNC(RTYPE) __declspec(dllexport) RTYPE
#endif

#include "_static_tuple_c.h"

#include "python-compat.h"

#if defined(__GNUC__)
#   define inline __inline__
#elif defined(_MSC_VER)
#   define inline __inline
#else
#   define inline
#endif


static PyObject *Keys_item(Keys *self, Py_ssize_t offset);
static PyObject *_interned_keys = NULL;


static inline int
_Key_is_interned(Key *self)
{
    return self->flags & KEY_INTERNED_FLAG;
}



#define Key_CheckExact(op) (Py_TYPE(op) == &Key_Type)

static PyObject *
Key_as_tuple(Key *self)
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
        obj = (PyObject *)self->key_bits[i];
        Py_INCREF(obj);
        PyTuple_SET_ITEM(tpl, i, obj);
    }
    return tpl;
}


static char Key_as_tuple_doc[] = "as_tuple() => tuple";

static Key *
Key_intern(Key *self)
{
    PyObject *unique_key = NULL;

    if (_interned_keys == NULL) {
        return self;
    }
    if (_Key_is_interned(self)) {
        // Already interned
        Py_INCREF(self);
        return self;
    }
    unique_key = PyDict_GetItem((PyObject *)_interned_keys, (PyObject *)self);
    if (unique_key) {
        // An entry already existed, return it, instead of self
        Py_INCREF(unique_key);
        return (Key *)unique_key;
    }
    // An entry did not exist, make 'self' the unique item
    if (PyDict_SetItem(_interned_keys, (PyObject *)self, (PyObject *)self) < 0) {
        // Suppress an error
        PyErr_Clear();
        return self;
    }
    // self was added to the dict, return it.
    Py_INCREF(self);
    self->flags |= KEY_INTERNED_FLAG;
    // The two references in the dict do not count, so that the Key object
    // does not become immortal just because it was interned.
    Py_REFCNT(self) -= 2;
    return self;
}

static char Key_intern_doc[] = "intern() => unique Key\n"
    "Return a 'canonical' Key object.\n"
    "Similar to intern() for strings, this makes sure there\n"
    "is only one Key object for a given value\n."
    "Common usage is:\n"
    "  key = Key('foo', 'bar').intern()\n";


static void
Key_dealloc(Key *self)
{
    int i, len;

    if (_Key_is_interned(self)) {
        /* revive dead object temporarily for DelItem */
        Py_REFCNT(self) = 3;
        if (PyDict_DelItem(_interned_keys, (PyObject *)self) != 0) {
            Py_FatalError("deletion of interned Key failed");
        }
    }
    len = self->size;
    for (i = 0; i < len; ++i) {
        Py_XDECREF(self->key_bits[i]);
    }
    Py_TYPE(self)->tp_free((PyObject *)self);
}


/* Similar to PyTuple_New() */
PyObject *
Key_New(Py_ssize_t size)
{
    Key *key;
    if (size < 0) {
        PyErr_BadInternalCall();
        return NULL;
    }

    /* Note that we use PyObject_NewVar because we want to allocate a variable
     * width entry. However we *aren't* truly a PyVarObject because we don't
     * use a long for ob_size. Instead we use a plain 'size' that is an int,
     * and will be overloaded with flags in the future.
     * As such we do the alloc, and then have to clean up anything it does
     * incorrectly.
     */
    key = PyObject_NewVar(Key, &Key_Type, size);
    if (key == NULL) {
        return NULL;
    }
    key->size = size;
    key->flags = 0;
    key->_unused0 = 0;
    key->_unused1 = 0;
    memset(key->key_bits, 0, sizeof(PyStringObject *) * size);
#if KEY_HAS_HASH
    key->hash = -1;
#endif
    return (PyObject *)key;
}


static PyObject *
Key_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    Key *self;
    PyObject *obj = NULL;
    Py_ssize_t i, len = 0;

    if (type != &Key_Type) {
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
    if (self == NULL) {
        return NULL;
    }
    self->size = len;
    self->flags = 0;
    self->_unused0 = 0;
    self->_unused1 = 0;
#if KEY_HAS_HASH
    self->hash = -1;
#endif
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
        self->key_bits[i] = (PyStringObject *)obj;
    }
    return (PyObject *)self;
}

static PyObject *
Key_repr(Key *self)
{
    PyObject *as_tuple, *result;

    as_tuple = Key_as_tuple(self);
    if (as_tuple == NULL) {
        return NULL;
    }
    result = PyObject_Repr(as_tuple);
    Py_DECREF(as_tuple);
    return result;
}

static long
Key_hash(Key *self)
{
    /* adapted from tuplehash(), is the specific hash value considered
     * 'stable'?
     */
	register long x, y;
	Py_ssize_t len = self->size;
	PyStringObject **p;
    hashfunc string_hash;
	long mult = 1000003L;

#if KEY_HAS_HASH
    if (self->hash != -1) {
        return self->hash;
    }
#endif
	x = 0x345678L;
	p = self->key_bits;
	while (--len >= 0) {
        y = Py_TYPE(*p)->tp_hash(*p);
		if (y == -1) /* failure */
			return -1;
		x = (x ^ y) * mult;
		/* the cast might truncate len; that doesn't change hash stability */
		mult += (long)(82520L + len + len);
        p++;
	}
	x += 97531L;
	if (x == -1)
		x = -2;
#if KEY_HAS_HASH
    if (self->hash != -1) {
        if (self->hash != x) {
            fprintf(stderr, "hash changed: %d => %d\n", self->hash, x);
        }
    }
    self->hash = x;
#endif
	return x;
}

static PyObject *
Key_richcompare_to_tuple(Key *v, PyObject *wt, int op)
{
    PyObject *vt;
    PyObject *result = NULL;
    
    vt = Key_as_tuple((Key *)v);
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
Key_richcompare(PyObject *v, PyObject *w, int op)
{
    Key *vk, *wk;
    Py_ssize_t vlen, wlen, min_len, i;
    richcmpfunc string_richcompare;

    if (!Key_CheckExact(v)) {
        /* This has never triggered */
        fprintf(stderr, "self is tuple\n");
        Py_INCREF(Py_NotImplemented);
        return Py_NotImplemented;
    }
    vk = (Key *)v;
    if (PyTuple_Check(w)) {
        /* One of v or w is a tuple, so we go the 'slow' route and cast up to
         * tuples to compare.
         */
        /* TODO: This seems to be triggering more than I thought it would...
         *       We probably want to optimize comparing self to other when
         *       other is a tuple.
         */
        return Key_richcompare_to_tuple(vk, w, op);
    }
    if (!Key_CheckExact(w)) {
        /* Both are not Key objects, and they aren't Tuple objects or the
         * previous path would have been taken. We don't support comparing with
         * anything else.
         */
         fprintf(stderr, "not comparing to key: %s\n", Py_TYPE(w)->tp_name);
         Py_INCREF(Py_NotImplemented);
         return Py_NotImplemented;
    }
    /* Now we know that we have 2 Key objects, so let's compare them.
     * This code is somewhat borrowed from tuplerichcompare, except we know our
     * objects are strings, so we get to cheat a bit.
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
    wk = (Key*)w;

    /* It will be rare that we compare tuples of different lengths, so we don't
     * start by optimizing the length comparision, same as the tuple code
     */
    vlen = vk->size;
    wlen = wk->size;
	min_len = (vlen < wlen) ? vlen : wlen;
    string_richcompare = PyString_Type.tp_richcompare;
    for (i = 0; i < min_len; i++) {
        PyObject *result;
        result = string_richcompare((PyObject *)vk->key_bits[i],
                                    (PyObject *)wk->key_bits[i],
                                    Py_EQ);
        if (result == NULL) {
            return NULL; /* Seems to be an error */
        }
        if (result == Py_NotImplemented) {
            PyErr_BadInternalCall();
            Py_DECREF(result);
            return NULL;
        }
        if (result == Py_False) {
            /* These strings are not identical
             * Shortcut for Py_EQ
             */
            if (op == Py_EQ) {
                return result;
            }
            Py_DECREF(result);
            break;
        }
        if (result != Py_True) {
            /* We don't know *what* string_richcompare is returning, but it
             * isn't correct.
             */
            PyErr_BadInternalCall();
            Py_DECREF(result);
            return NULL;
        }
        Py_DECREF(result);
    }
	if (i >= vlen || i >= wlen) {
		/* No more items to compare -- compare sizes */
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
    return string_richcompare((PyObject *)vk->key_bits[i],
                              (PyObject *)wk->key_bits[i],
                              op);
}


static Py_ssize_t
Key_length(Key *self)
{
    return self->size;
}


static PyObject *
Key__is_interned(Key *self)
{
    if (_Key_is_interned(self)) {
        Py_INCREF(Py_True);
        return Py_True;
    }
    Py_INCREF(Py_False);
    return Py_False;
}

static char Key__is_interned_doc[] = "_is_interned() => True/False\n"
    "Check to see if this key has been interned.\n";


static PyObject *
Key_item(Key *self, Py_ssize_t offset)
{
    PyObject *obj;
    if (offset < 0 || offset >= self->size) {
        PyErr_SetString(PyExc_IndexError, "Key index out of range");
        return NULL;
    }
    obj = (PyObject *)self->key_bits[offset];
    Py_INCREF(obj);
    return obj;
}

static PyObject *
Key_slice(Key *self, Py_ssize_t ilow, Py_ssize_t ihigh)
{
    PyObject *as_tuple, *result;

    as_tuple = Key_as_tuple(self);
    if (as_tuple == NULL) {
        return NULL;
    }
    result = PyTuple_Type.tp_as_sequence->sq_slice(as_tuple, ilow, ihigh);
    Py_DECREF(as_tuple);
    return result;
}

static int
Key_traverse(Key *self, visitproc visit, void *arg)
{
    Py_ssize_t i;
    for (i = Py_SIZE(self); --i >= 0;) {
        Py_VISIT(self->key_bits[i]);
    }
    return 0;
}

static char Key_doc[] =
    "C implementation of a Key structure."
    "\n This is used as Key(key_bit_1, key_bit_2, key_bit_3, ...)"
    "\n This is similar to tuple, just less flexible in what it"
    "\n supports, but also lighter memory consumption.";

static PyMethodDef Key_methods[] = {
    {"as_tuple", (PyCFunction)Key_as_tuple, METH_NOARGS, Key_as_tuple_doc},
    {"intern", (PyCFunction)Key_intern, METH_NOARGS, Key_intern_doc},
    {"_is_interned", (PyCFunction)Key__is_interned, METH_NOARGS,
     Key__is_interned_doc},
    {NULL, NULL} /* sentinel */
};

static PySequenceMethods Key_as_sequence = {
    (lenfunc)Key_length,            /* sq_length */
    0,                              /* sq_concat */
    0,                              /* sq_repeat */
    (ssizeargfunc)Key_item,         /* sq_item */
    (ssizessizeargfunc)Key_slice,   /* sq_slice */
    0,                              /* sq_ass_item */
    0,                              /* sq_ass_slice */
    0,                              /* sq_contains */
};


PyTypeObject Key_Type = {
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
    (reprfunc)Key_repr,                          /* tp_repr */
    0,                                           /* tp_as_number */
    &Key_as_sequence,                            /* tp_as_sequence */
    0,                                           /* tp_as_mapping */
    (hashfunc)Key_hash,                          /* tp_hash */
    0,                                           /* tp_call */
    0,                                           /* tp_str */
    PyObject_GenericGetAttr,                     /* tp_getattro */
    0,                                           /* tp_setattro */
    0,                                           /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                          /* tp_flags*/
    Key_doc,                                     /* tp_doc */
    /* gc.get_referents checks the IS_GC flag before it calls tp_traverse
     * And we don't include this object in the garbage collector because we
     * know it doesn't create cycles. However, 'meliae' will follow
     * tp_traverse, even if the object isn't GC, and we want that.
     */
    (traverseproc)Key_traverse,                  /* tp_traverse */
    0,                                           /* tp_clear */
    // TODO: implement richcompare, we should probably be able to compare vs an
    //       tuple, as well as versus another Keys object.
    Key_richcompare,                             /* tp_richcompare */
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

#define Keys_CheckExact(op) (Py_TYPE(op) == &Keys_Type)

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
            Py_XDECREF(self->key_bits[i]);
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

    if (type != &Keys_Type) {
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
    if (self == NULL) {
        return NULL;
    }
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
        self->key_bits[i] = (PyStringObject *)obj;
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
    PyObject *result = NULL;

    if (Keys_CheckExact(v)) {
        vt = Keys_as_tuple((Keys *)v);
        if (vt == NULL) {
            goto Done;
        }
        vt_to_decref = vt;
    } else if (PyTuple_Check(v)) {
        vt = v;
        vt_to_decref = NULL;
    } else {
        Py_INCREF(Py_NotImplemented);
        result = Py_NotImplemented;
        goto Done;
    }
    if (Keys_CheckExact(w)) {
        wt = Keys_as_tuple((Keys *)w);
        if (wt == NULL) {
            goto Done;
        }
        wt_to_decref = wt;
    } else if (PyTuple_Check(w)) {
        wt = w;
        wt_to_decref = NULL;
    } else {
        Py_INCREF(Py_NotImplemented);
        result = Py_NotImplemented;
        goto Done;
    }
    /* Now we have 2 tuples to compare, do it */
    result = PyTuple_Type.tp_richcompare(vt, wt, op);
Done:
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

static int
Keys_traverse(Keys *self, visitproc visit, void *arg)
{
    Py_ssize_t i, num_key_bits;
    num_key_bits = Keys_get_key_width(self) * Keys_get_num_keys(self);
    for (i = num_key_bits; --i >= 0;) {
        Py_VISIT(self->key_bits[i]);
    }
    return 0;
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
    PyObject *obj;
    Key *key;

    if (offset < 0 || offset >= Keys_get_num_keys(self)) {
        PyErr_SetString(PyExc_IndexError, "Keys index out of range");
        return NULL;
    }
    key_width = Keys_get_key_width(self);
    key = (Key *)Key_New(key_width);
    if (!key) {
        /* Malloc failure */
        return NULL;
    }
    start = offset * key_width;
    for (i = 0; i < key_width; ++i) {
        obj = (PyObject *)self->key_bits[start + i];
        Py_INCREF(obj);
        key->key_bits[i] = (PyStringObject *)obj;
    }
    return (PyObject *)key;
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

PyTypeObject Keys_Type = {
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
    /* See Key_traverse for why we have this, even though we aren't GC */
    (traverseproc)Keys_traverse,                 /* tp_traverse */
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


static char KeyIntern_doc[] = "";

static PyMethodDef KeyIntern_methods[] = {
    // {"as_tuple", (PyCFunction)Keys_as_tuple, METH_NOARGS, Keys_as_tuple_doc},
    {NULL, NULL} /* sentinel */
};

static PySequenceMethods KeyIntern_as_sequence = {
    0, //(lenfunc)Keys_length,           /* sq_length */
    0,                              /* sq_concat */
    0,                              /* sq_repeat */
    0, //(ssizeargfunc)Keys_item,        /* sq_item */
    0,                              /* sq_slice */
    0,                              /* sq_ass_item */
    0,                              /* sq_ass_slice */
    0,                              /* sq_contains */
};

static PyTypeObject KeyIntern_Type = {
    PyObject_HEAD_INIT(NULL)
    0,                                           /* ob_size */
    "KeyIntern",                                 /* tp_name */
    sizeof(KeyIntern) - sizeof(Key *),           /* tp_basicsize */
    sizeof(Key *),                               /* tp_itemsize */
    0, //(destructor)Keys_dealloc,               /* tp_dealloc */
    0,                                           /* tp_print */
    0,                                           /* tp_getattr */
    0,                                           /* tp_setattr */
    0,                                           /* tp_compare */
    // TODO: implement repr() and possibly str()
    0, //(reprfunc)Keys_repr,                         /* tp_repr */
    0,                                           /* tp_as_number */
    &KeyIntern_as_sequence,                      /* tp_as_sequence */
    0,                                           /* tp_as_mapping */
    0, //(hashfunc)Keys_hash,                         /* tp_hash */
    0,                                           /* tp_call */
    0,                                           /* tp_str */
    PyObject_GenericGetAttr,                     /* tp_getattro */
    0,                                           /* tp_setattro */
    0,                                           /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                          /* tp_flags*/
    0, // Keys_doc,                                    /* tp_doc */
    /* See Key_traverse for why we have this, even though we aren't GC */
    0, //(traverseproc)Keys_traverse,                 /* tp_traverse */
    0,                                           /* tp_clear */
    // TODO: implement richcompare, we should probably be able to compare vs an
    //       tuple, as well as versus another Keys object.
    0, //Keys_richcompare,                            /* tp_richcompare */
    0,                                           /* tp_weaklistoffset */
    // We could implement this as returning tuples of keys...
    0,                                           /* tp_iter */
    0,                                           /* tp_iternext */
    KeyIntern_methods,                           /* tp_methods */
    0,                                           /* tp_members */
    0,                                           /* tp_getset */
    0,                                           /* tp_base */
    0,                                           /* tp_dict */
    0,                                           /* tp_descr_get */
    0,                                           /* tp_descr_set */
    0,                                           /* tp_dictoffset */
    0,                                           /* tp_init */
    0,                                           /* tp_alloc */
    0, //Keys_new,                                    /* tp_new */
};


static PyMethodDef keys_type_c_methods[] = {
//    {"unique_lcs_c", py_unique_lcs, METH_VARARGS},
//    {"recurse_matches_c", py_recurse_matches, METH_VARARGS},
    {NULL, NULL}
};


PyMODINIT_FUNC
init_static_tuple_c(void)
{
    PyObject* m;

    if (PyType_Ready(&Key_Type) < 0)
        return;
    if (PyType_Ready(&Keys_Type) < 0)
        return;
    if (PyType_Ready(&KeyIntern_Type) < 0)
        return;

    m = Py_InitModule3("_static_tuple_c", keys_type_c_methods,
                       "C implementation of a Keys structure");
    if (m == NULL)
      return;

    Py_INCREF(&Key_Type);
    PyModule_AddObject(m, "Key", (PyObject *)&Key_Type);
    Py_INCREF(&Keys_Type);
    PyModule_AddObject(m, "Keys", (PyObject *)&Keys_Type);
    // Py_INCREF(&KeyIntern_Type);
    // PyModule_AddObject(m, "KeyIntern", (PyObject *)&KeyIntern_Type);
    // _interned_keys = PyObject_NewVar(KeyIntern, &KeyIntern_Type, 10);
    _interned_keys = PyDict_New();
    if (_interned_keys != NULL) {
        Py_INCREF(_interned_keys);
        PyModule_AddObject(m, "_interned_keys", _interned_keys);
    }
}
