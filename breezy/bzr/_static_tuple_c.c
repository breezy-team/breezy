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

/* Must be defined before importing _static_tuple_c.h so that we get the right
 * linkage.
 */
#define STATIC_TUPLE_MODULE

#include <Python.h>
#include "../python-compat.h"

#include "_static_tuple_c.h"
#include "_export_c_api.h"

#include "_simple_set_pyx_api.h"

#if defined(__GNUC__)
#   define inline __inline__
#elif defined(_MSC_VER)
#   define inline __inline
#else
#   define inline
#endif


/* The one and only StaticTuple with no values */
static StaticTuple *_empty_tuple = NULL;
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

static StaticTuple *
StaticTuple_Intern(StaticTuple *self)
{
    PyObject *canonical_tuple = NULL;

    if (_interned_tuples == NULL || _StaticTuple_is_interned(self)) {
        Py_INCREF(self);
        return self;
    }
    /* SimpleSet_Add returns whatever object is present at self
     * or the new object if it needs to add it.
     */
    canonical_tuple = SimpleSet_Add(_interned_tuples, (PyObject *)self);
    if (!canonical_tuple) {
        // Some sort of exception, propogate it.
        return NULL;
    }
    if (canonical_tuple != (PyObject *)self) {
        // There was already a tuple with that value
        return (StaticTuple *)canonical_tuple;
    }
    self->flags |= STATIC_TUPLE_INTERNED_FLAG;
    // The two references in the dict do not count, so that the StaticTuple
    // object does not become immortal just because it was interned.
    Py_SET_REFCNT(self, Py_REFCNT(self) - 1);
    return self;
}

static char StaticTuple_Intern_doc[] = "intern() => unique StaticTuple\n"
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
        /* revive dead object temporarily for Discard */
        Py_SET_REFCNT(self, 2);
        if (SimpleSet_Discard(_interned_tuples, (PyObject*)self) != 1)
            Py_FatalError("deletion of interned StaticTuple failed");
        self->flags &= ~STATIC_TUPLE_INTERNED_FLAG;
    }
    len = self->size;
    for (i = 0; i < len; ++i) {
        Py_XDECREF(self->items[i]);
    }
    Py_TYPE(self)->tp_free((PyObject *)self);
}


/* Similar to PyTuple_New() */
static StaticTuple *
StaticTuple_New(Py_ssize_t size)
{
    StaticTuple *stuple;

    if (size < 0 || size > 255) {
        /* Too big or too small */
        PyErr_SetString(PyExc_ValueError, "StaticTuple(...)"
            " takes from 0 to 255 items");
        return NULL;
    }
    if (size == 0 && _empty_tuple != NULL) {
        Py_INCREF(_empty_tuple);
        return _empty_tuple;
    }
    /* Note that we use PyObject_NewVar because we want to allocate a variable
     * width entry. However we *aren't* truly a PyVarObject because we don't
     * use a long for ob_size. Instead we use a plain 'size' that is an int,
     * and will be overloaded with flags in the future.
     * As such we do the alloc, and then have to clean up anything it does
     * incorrectly.
     */
    stuple = PyObject_NewVar(StaticTuple, &StaticTuple_Type, size);
    if (stuple == NULL) {
        return NULL;
    }
    stuple->size = size;
    stuple->flags = 0;
    stuple->_unused0 = 0;
    stuple->_unused1 = 0;
    if (size > 0) {
        memset(stuple->items, 0, sizeof(PyObject *) * size);
    }
#if STATIC_TUPLE_HAS_HASH
    stuple->hash = -1;
#endif
    return stuple;
}


static StaticTuple *
StaticTuple_FromSequence(PyObject *sequence)
{
    StaticTuple *new = NULL;
    PyObject *as_tuple = NULL;
    PyObject *item;
    Py_ssize_t i, size;

    if (StaticTuple_CheckExact(sequence)) {
        Py_INCREF(sequence);
        return (StaticTuple *)sequence;
    }
    if (!PySequence_Check(sequence)) {
        as_tuple = PySequence_Tuple(sequence);
        if (as_tuple == NULL)
            goto done;
        sequence = as_tuple;
    }
    size = PySequence_Size(sequence);
    if (size == -1) {
        goto done;
    }
    new = StaticTuple_New(size);
    if (new == NULL) {
        goto done;
    }
    for (i = 0; i < size; ++i) {
        // This returns a new reference, which we then 'steal' with 
        // StaticTuple_SET_ITEM
        item = PySequence_GetItem(sequence, i);
        if (item == NULL) {
            Py_DECREF(new);
            new = NULL;
            goto done;
        }
        StaticTuple_SET_ITEM(new, i, item);
    }
done:
    Py_XDECREF(as_tuple);
    return (StaticTuple *)new;
}

static StaticTuple *
StaticTuple_from_sequence(PyObject *self, PyObject *args, PyObject *kwargs)
{
    PyObject *sequence;
    if (!PyArg_ParseTuple(args, "O", &sequence))
        return NULL;
    return StaticTuple_FromSequence(sequence);
}


/* Check that all items we point to are 'valid' */
static int
StaticTuple_check_items(StaticTuple *self)
{
    int i;
    PyObject *obj;

    for (i = 0; i < self->size; ++i) {
        obj = self->items[i];
        if (obj == NULL) {
            PyErr_SetString(PyExc_RuntimeError, "StaticTuple(...)"
                " should not have a NULL entry.");
            return 0;
        }
        if (PyBytes_CheckExact(obj)
            || StaticTuple_CheckExact(obj)
            || obj == Py_None
            || PyBool_Check(obj)
#if PY_MAJOR_VERSION >= 3
#else
            || PyInt_CheckExact(obj)
#endif
            || PyLong_CheckExact(obj)
            || PyFloat_CheckExact(obj)
            || PyUnicode_CheckExact(obj)
            ) continue;
        PyErr_Format(PyExc_TypeError, "StaticTuple(...)"
            " requires that all items are one of"
            " str, StaticTuple, None, bool, int, long, float, or unicode"
            " not %s.", Py_TYPE(obj)->tp_name);
        return 0;
    }
    return 1;
}

static PyObject *
StaticTuple_new_constructor(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    StaticTuple *self;
    PyObject *obj = NULL;
    Py_ssize_t i, len = 0;

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
        /* Check the length here so we can raise a TypeError instead of
         * StaticTuple_New's ValueError.
         */
        PyErr_SetString(PyExc_TypeError, "StaticTuple(...)"
            " takes from 0 to 255 items");
        return NULL;
    }
    self = (StaticTuple *)StaticTuple_New(len);
    if (self == NULL) {
        return NULL;
    }
    for (i = 0; i < len; ++i) {
        obj = PyTuple_GET_ITEM(args, i);
        Py_INCREF(obj);
        self->items[i] = obj;
    }
    if (!StaticTuple_check_items(self)) {
        type->tp_dealloc((PyObject *)self);
        return NULL;
    }
    return (PyObject *)self;
}

static PyObject *
StaticTuple_repr(StaticTuple *self)
{
    PyObject *as_tuple, *tuple_repr, *result;

    as_tuple = StaticTuple_as_tuple(self);
    if (as_tuple == NULL) {
        return NULL;
    }
    tuple_repr = PyObject_Repr(as_tuple);
    Py_DECREF(as_tuple);
    if (tuple_repr == NULL) {
        return NULL;
    }
#if PY_MAJOR_VERSION >= 3
    result = PyUnicode_FromFormat("StaticTuple%U", tuple_repr);
#else
    result = PyString_FromFormat("StaticTuple%s",
                                 PyString_AsString(tuple_repr));
#endif
    return result;
}

/* adapted from tuplehash(), is the specific hash value considered
 * 'stable'?
 */

#if PY_MAJOR_VERSION > 3 || (PY_MAJOR_VERSION == 3 && PY_MINOR_VERSION >= 8)
/* Hash for tuples. This is a slightly simplified version of the xxHash
   non-cryptographic hash:
   - we do not use any parallellism, there is only 1 accumulator.
   - we drop the final mixing since this is just a permutation of the
     output space: it does not help against collisions.
   - at the end, we mangle the length with a single constant.
   For the xxHash specification, see
   https://github.com/Cyan4973/xxHash/blob/master/doc/xxhash_spec.md

   Below are the official constants from the xxHash specification. Optimizing
   compilers should emit a single "rotate" instruction for the
   _PyHASH_XXROTATE() expansion. If that doesn't happen for some important
   platform, the macro could be changed to expand to a platform-specific rotate
   spelling instead.
*/
#if SIZEOF_PY_UHASH_T > 4
#define _PyHASH_XXPRIME_1 ((Py_uhash_t)11400714785074694791ULL)
#define _PyHASH_XXPRIME_2 ((Py_uhash_t)14029467366897019727ULL)
#define _PyHASH_XXPRIME_5 ((Py_uhash_t)2870177450012600261ULL)
#define _PyHASH_XXROTATE(x) ((x << 31) | (x >> 33))  /* Rotate left 31 bits */
#else
#define _PyHASH_XXPRIME_1 ((Py_uhash_t)2654435761UL)
#define _PyHASH_XXPRIME_2 ((Py_uhash_t)2246822519UL)
#define _PyHASH_XXPRIME_5 ((Py_uhash_t)374761393UL)
#define _PyHASH_XXROTATE(x) ((x << 13) | (x >> 19))  /* Rotate left 13 bits */
#endif

/* Tests have shown that it's not worth to cache the hash value, see
   https://bugs.python.org/issue9685 */
static Py_hash_t
StaticTuple_hash(StaticTuple *self)
{
    Py_ssize_t i, len = self->size;
    PyObject **item = self->items;

#if STATIC_TUPLE_HAS_HASH
    if (self->hash != -1) {
        return self->hash;
    }
#endif

    Py_uhash_t acc = _PyHASH_XXPRIME_5;
    for (i = 0; i < len; i++) {
        Py_uhash_t lane = PyObject_Hash(item[i]);
        if (lane == (Py_uhash_t)-1) {
            return -1;
        }
        acc += lane * _PyHASH_XXPRIME_2;
        acc = _PyHASH_XXROTATE(acc);
        acc *= _PyHASH_XXPRIME_1;
    }

    /* Add input length, mangled to keep the historical value of hash(()). */
    acc += len ^ (_PyHASH_XXPRIME_5 ^ 3527539UL);

    if (acc == (Py_uhash_t)-1) {
        acc = 1546275796;
    }

#if STATIC_TUPLE_HAS_HASH
    self->hash = acc;
#endif
    return acc;
}


#else
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
    // TODO: We could set specific flags if we know that, for example, all the
    //       items are strings. I haven't seen a real-world benefit to that
    //       yet, though.
    while (--len >= 0) {
        y = PyObject_Hash(*p++);
        if (y == -1) /* failure */
            return -1;
        x = (x ^ y) * mult;
        /* the cast might truncate len; that doesn't change hash stability */
        mult += (long)(82520L + len + len);
    }
    x += 97531L;
    if (x == -1)
        x = -2;
#if STATIC_TUPLE_HAS_HASH
    self->hash = x;
#endif
    return x;
}
#endif

static PyObject *
StaticTuple_richcompare_to_tuple(StaticTuple *v, PyObject *wt, int op)
{
    PyObject *vt;
    PyObject *result = NULL;

    vt = StaticTuple_as_tuple((StaticTuple *)v);
    if (vt == NULL) {
        goto done;
    }
    if (!PyTuple_Check(wt)) {
        PyErr_BadInternalCall();
        goto done;
    }
    /* Now we have 2 tuples to compare, do it */
    result = PyTuple_Type.tp_richcompare(vt, wt, op);
done:
    Py_XDECREF(vt);
    return result;
}

/** Compare two objects to determine if they are equivalent.
 * The basic flow is as follows
 *  1) First make sure that both objects are StaticTuple instances. If they
 *     aren't then cast self to a tuple, and have the tuple do the comparison.
 *  2) Special case comparison to Py_None, because it happens to occur fairly
 *     often in the test suite.
 *  3) Special case when v and w are the same pointer. As we know the answer to
 *     all queries without walking individual items.
 *  4) For all operations, we then walk the items to find the first paired
 *     items that are not equal.
 *  5) If all items found are equal, we then check the length of self and
 *     other to determine equality.
 *  6) If an item differs, then we apply "op" to those last two items. (eg.
 *     StaticTuple(A, B) > StaticTuple(A, C) iff B > C)
 */

static PyObject *
StaticTuple_richcompare(PyObject *v, PyObject *w, int op)
{
    StaticTuple *v_st, *w_st;
    Py_ssize_t vlen, wlen, min_len, i;
    PyObject *v_obj, *w_obj;
    richcmpfunc string_richcompare;

    if (!StaticTuple_CheckExact(v)) {
        /* This has never triggered, according to python-dev it seems this
         * might trigger if '__op__' is defined but '__rop__' is not, sort of
         * case. Such as "None == StaticTuple()"
         */
        fprintf(stderr, "self is not StaticTuple\n");
        Py_INCREF(Py_NotImplemented);
        return Py_NotImplemented;
    }
    v_st = (StaticTuple *)v;
    if (StaticTuple_CheckExact(w)) {
        /* The most common case */
        w_st = (StaticTuple*)w;
    } else if (PyTuple_Check(w)) {
        /* One of v or w is a tuple, so we go the 'slow' route and cast up to
         * tuples to compare.
         */
        /* TODO: This seems to be triggering more than I thought it would...
         *       We probably want to optimize comparing self to other when
         *       other is a tuple.
         */
        return StaticTuple_richcompare_to_tuple(v_st, w, op);
    } else if (w == Py_None) {
        // None is always less than the object
        switch (op) {
        case Py_NE:
#if PY_MAJOR_VERSION >= 3
#else
        case Py_GT:case Py_GE:
#endif
            Py_INCREF(Py_True);
            return Py_True;
        case Py_EQ:
#if PY_MAJOR_VERSION >= 3
#else
        case Py_LT:case Py_LE:
#endif
            Py_INCREF(Py_False);
            return Py_False;
        default: // Should only happen on Python 3
            return Py_NotImplemented;
        }
    } else {
        /* We don't special case this comparison, we just let python handle
         * it.
         */
         Py_INCREF(Py_NotImplemented);
         return Py_NotImplemented;
    }
    /* Now we know that we have 2 StaticTuple objects, so let's compare them.
     * This code is inspired from tuplerichcompare, except we know our
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
    if (op == Py_EQ
        && _StaticTuple_is_interned(v_st)
        && _StaticTuple_is_interned(w_st))
    {
        /* If both objects are interned, we know they are different if the
         * pointer is not the same, which would have been handled by the
         * previous if. No need to compare the entries.
         */
        Py_INCREF(Py_False);
        return Py_False;
    }

    /* The only time we are likely to compare items of different lengths is in
     * something like the interned_keys set. However, the hash is good enough
     * that it is rare. Note that 'tuple_richcompare' also does not compare
     * lengths here.
     */
    vlen = v_st->size;
    wlen = w_st->size;
    min_len = (vlen < wlen) ? vlen : wlen;
    string_richcompare = PyBytes_Type.tp_richcompare;
    for (i = 0; i < min_len; i++) {
        PyObject *result = NULL;
        v_obj = StaticTuple_GET_ITEM(v_st, i);
        w_obj = StaticTuple_GET_ITEM(w_st, i);
        if (v_obj == w_obj) {
            /* Shortcut case, these must be identical */
            continue;
        }
        if (PyBytes_CheckExact(v_obj) && PyBytes_CheckExact(w_obj)) {
            result = string_richcompare(v_obj, w_obj, Py_EQ);
        } else if (StaticTuple_CheckExact(v_obj) &&
                   StaticTuple_CheckExact(w_obj))
        {
            /* Both are StaticTuple types, so recurse */
            result = StaticTuple_richcompare(v_obj, w_obj, Py_EQ);
        } else {
            /* Fall back to generic richcompare */
            result = PyObject_RichCompare(v_obj, w_obj, Py_EQ);
        }
        if (result == NULL) {
            return NULL; /* There seems to be an error */
        }
        if (result == Py_False) {
            // This entry is not identical, Shortcut for Py_EQ
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
    if (i >= min_len) {
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
    if (PyBytes_CheckExact(v_obj) && PyBytes_CheckExact(w_obj))
    {
        return string_richcompare(v_obj, w_obj, op);
    } else if (StaticTuple_CheckExact(v_obj) &&
               StaticTuple_CheckExact(w_obj))
    {
        /* Both are StaticTuple types, so recurse */
        return StaticTuple_richcompare(v_obj, w_obj, op);
    } else {
        return PyObject_RichCompare(v_obj, w_obj, op);
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
    "Check to see if this tuple has been interned.\n";


static PyObject *
StaticTuple_reduce(StaticTuple *self)
{
    PyObject *result = NULL, *as_tuple = NULL;

    result = PyTuple_New(2);
    if (!result) {
        return NULL;
    }
    as_tuple = StaticTuple_as_tuple(self);
    if (as_tuple == NULL) {
        Py_DECREF(result);
        return NULL;
    }
    Py_INCREF(&StaticTuple_Type);
    PyTuple_SET_ITEM(result, 0, (PyObject *)&StaticTuple_Type);
    PyTuple_SET_ITEM(result, 1, as_tuple);
    return result;
}

static char StaticTuple_reduce_doc[] = "__reduce__() => tuple\n";


static PyObject *
StaticTuple_add(PyObject *v, PyObject *w)
{
    Py_ssize_t i, len_v, len_w;
    PyObject *item;
    StaticTuple *result;
     /* StaticTuples and plain tuples may be added (concatenated) to
      * StaticTuples.
      */
    if (StaticTuple_CheckExact(v)) {
        len_v = ((StaticTuple*)v)->size;
    } else if (PyTuple_Check(v)) {
        len_v = PyTuple_GET_SIZE(v);
    } else {
        Py_INCREF(Py_NotImplemented);
        return Py_NotImplemented;
    }
    if (StaticTuple_CheckExact(w)) {
        len_w = ((StaticTuple*)w)->size;
    } else if (PyTuple_Check(w)) {
        len_w = PyTuple_GET_SIZE(w);
    } else {
        Py_INCREF(Py_NotImplemented);
        return Py_NotImplemented;
    }
    result = StaticTuple_New(len_v + len_w);
    if (result == NULL)
        return NULL;
    for (i = 0; i < len_v; ++i) {
        // This returns a new reference, which we then 'steal' with 
        // StaticTuple_SET_ITEM
        item = PySequence_GetItem(v, i);
        if (item == NULL) {
            Py_DECREF(result);
            return NULL;
        }
        StaticTuple_SET_ITEM(result, i, item);
    }
    for (i = 0; i < len_w; ++i) {
        item = PySequence_GetItem(w, i);
        if (item == NULL) {
            Py_DECREF(result);
            return NULL;
        }
        StaticTuple_SET_ITEM(result, i+len_v, item);
    }
    if (!StaticTuple_check_items(result)) {
        Py_DECREF(result);
        return NULL;
    }
    return (PyObject *)result;
}

static PyObject *
StaticTuple_item(StaticTuple *self, Py_ssize_t offset)
{
    PyObject *obj;
    /* We cast to (int) to avoid worrying about whether Py_ssize_t is a
     * long long, etc. offsets should never be >2**31 anyway.
     */
    if (offset < 0) {
        PyErr_Format(PyExc_IndexError, "StaticTuple_item does not support"
            " negative indices: %d\n", (int)offset);
    } else if (offset >= self->size) {
        PyErr_Format(PyExc_IndexError, "StaticTuple index out of range"
            " %d >= %d", (int)offset, (int)self->size);
        return NULL;
    }
    obj = (PyObject *)self->items[offset];
    Py_INCREF(obj);
    return obj;
}

#if PY_MAJOR_VERSION >= 3
#else
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
#endif

static PyObject *
StaticTuple_subscript(StaticTuple *self, PyObject *key)
{
    PyObject *as_tuple, *result;

    as_tuple = StaticTuple_as_tuple(self);
    if (as_tuple == NULL) {
        return NULL;
    }
    result = PyTuple_Type.tp_as_mapping->mp_subscript(as_tuple, key);
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


static PyObject *
StaticTuple_sizeof(StaticTuple *self)
{
    Py_ssize_t res;

    res = _PyObject_SIZE(&StaticTuple_Type) + (int)self->size * sizeof(void*);
    return PyInt_FromSsize_t(res);
}



static char StaticTuple_doc[] =
    "C implementation of a StaticTuple structure."
    "\n This is used as StaticTuple(item1, item2, item3)"
    "\n This is similar to tuple, less flexible in what it"
    "\n supports, but also lighter memory consumption."
    "\n Note that the constructor mimics the () form of tuples"
    "\n Rather than the 'tuple()' constructor."
    "\n  eg. StaticTuple(a, b) == (a, b) == tuple((a, b))";

static PyMethodDef StaticTuple_methods[] = {
    {"as_tuple", (PyCFunction)StaticTuple_as_tuple, METH_NOARGS, StaticTuple_as_tuple_doc},
    {"intern", (PyCFunction)StaticTuple_Intern, METH_NOARGS, StaticTuple_Intern_doc},
    {"_is_interned", (PyCFunction)StaticTuple__is_interned, METH_NOARGS,
     StaticTuple__is_interned_doc},
    {"from_sequence", (PyCFunction)StaticTuple_from_sequence,
     METH_STATIC | METH_VARARGS,
     "Create a StaticTuple from a given sequence. This functions"
     " the same as the tuple() constructor."},
    {"__reduce__", (PyCFunction)StaticTuple_reduce, METH_NOARGS, StaticTuple_reduce_doc},
    {"__sizeof__",  (PyCFunction)StaticTuple_sizeof, METH_NOARGS}, 
    {NULL, NULL} /* sentinel */
};


static PyNumberMethods StaticTuple_as_number = {
    (binaryfunc) StaticTuple_add,   /* nb_add */
    0,                              /* nb_subtract */
    0,                              /* nb_multiply */
    0,                              /* nb_divide */
    0,                              /* nb_remainder */
    0,                              /* nb_divmod */
    0,                              /* nb_power */
    0,                              /* nb_negative */
    0,                              /* nb_positive */
    0,                              /* nb_absolute */
    0,                              /* nb_nonzero */
    0,                              /* nb_invert */
    0,                              /* nb_lshift */
    0,                              /* nb_rshift */
    0,                              /* nb_and */
    0,                              /* nb_xor */
    0,                              /* nb_or */
    0,                              /* nb_coerce */
};


static PySequenceMethods StaticTuple_as_sequence = {
    (lenfunc)StaticTuple_length,            /* sq_length */
    0,                              /* sq_concat */
    0,                              /* sq_repeat */
    (ssizeargfunc)StaticTuple_item,         /* sq_item */
#if PY_MAJOR_VERSION >= 3
#else
    (ssizessizeargfunc)StaticTuple_slice,   /* sq_slice */
#endif
    0,                              /* sq_ass_item */
    0,                              /* sq_ass_slice */
    0,                              /* sq_contains */
#if PY_MAJOR_VERSION >= 3
    0,                              /* sq_inplace_concat */
    0,                              /* sq_inplace_repeat */
#endif
};


static PyMappingMethods StaticTuple_as_mapping = {
    (lenfunc)StaticTuple_length,            /* mp_length */
    (binaryfunc)StaticTuple_subscript,      /* mp_subscript */
    0,                                      /* mp_ass_subscript */
};


PyTypeObject StaticTuple_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "breezy.bzr._static_tuple_c.StaticTuple",        /* tp_name */
    sizeof(StaticTuple),                         /* tp_basicsize */
    sizeof(PyObject *),                          /* tp_itemsize */
    (destructor)StaticTuple_dealloc,             /* tp_dealloc */
    0,                                           /* tp_print */
    0,                                           /* tp_getattr */
    0,                                           /* tp_setattr */
    0,                                           /* tp_compare */
    (reprfunc)StaticTuple_repr,                  /* tp_repr */
    &StaticTuple_as_number,                      /* tp_as_number */
    &StaticTuple_as_sequence,                    /* tp_as_sequence */
    &StaticTuple_as_mapping,                     /* tp_as_mapping */
    (hashfunc)StaticTuple_hash,                  /* tp_hash */
    0,                                           /* tp_call */
    0,                                           /* tp_str */
    0,                                           /* tp_getattro */
    0,                                           /* tp_setattro */
    0,                                           /* tp_as_buffer */
    /* Py_TPFLAGS_CHECKTYPES tells the number operations that they shouldn't
     * try to 'coerce' but instead stuff like 'add' will check it arguments.
     */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_CHECKTYPES,  /* tp_flags*/
    StaticTuple_doc,                             /* tp_doc */
    /* gc.get_referents checks the IS_GC flag before it calls tp_traverse
     * And we don't include this object in the garbage collector because we
     * know it doesn't create cycles. However, 'meliae' will follow
     * tp_traverse, even if the object isn't GC, and we want that.
     */
    (traverseproc)StaticTuple_traverse,          /* tp_traverse */
    0,                                           /* tp_clear */
    StaticTuple_richcompare,                     /* tp_richcompare */
    0,                                           /* tp_weaklistoffset */
    // without implementing tp_iter, Python will fall back to PySequence*
    // which seems to work ok, we may need something faster/lighter in the
    // future.
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
    StaticTuple_new_constructor,                 /* tp_new */
};


static PyMethodDef static_tuple_c_methods[] = {
    {NULL, NULL}
};


static void
setup_interned_tuples(PyObject *m)
{
    _interned_tuples = (PyObject *)SimpleSet_New();
    if (_interned_tuples != NULL) {
        Py_INCREF(_interned_tuples);
        PyModule_AddObject(m, "_interned_tuples", _interned_tuples);
    }
}


static void
setup_empty_tuple(PyObject *m)
{
    StaticTuple *stuple;
    if (_interned_tuples == NULL) {
        fprintf(stderr, "You need to call setup_interned_tuples() before"
                " setup_empty_tuple, because we intern it.\n");
    }
    // We need to create the empty tuple
    stuple = (StaticTuple *)StaticTuple_New(0);
    _empty_tuple = StaticTuple_Intern(stuple);
    assert(_empty_tuple == stuple);
    // At this point, refcnt is 2: 1 from New(), and 1 from the return from
    // intern(). We will keep 1 for the _empty_tuple global, and use the other
    // for the module reference.
    PyModule_AddObject(m, "_empty_tuple", (PyObject *)_empty_tuple);
}

static int
_StaticTuple_CheckExact(PyObject *obj)
{
    return StaticTuple_CheckExact(obj);
}

static void
setup_c_api(PyObject *m)
{
    _export_function(m, "StaticTuple_New", StaticTuple_New,
        "StaticTuple *(Py_ssize_t)");
    _export_function(m, "StaticTuple_Intern", StaticTuple_Intern,
        "StaticTuple *(StaticTuple *)");
    _export_function(m, "StaticTuple_FromSequence", StaticTuple_FromSequence,
        "StaticTuple *(PyObject *)");
    _export_function(m, "_StaticTuple_CheckExact", _StaticTuple_CheckExact,
        "int(PyObject *)");
}


PYMOD_INIT_FUNC(_static_tuple_c)
{
    PyObject* m;

    StaticTuple_Type.tp_getattro = PyObject_GenericGetAttr;
    if (PyType_Ready(&StaticTuple_Type) < 0) {
        return PYMOD_ERROR;
    }

    PYMOD_CREATE(m, "_static_tuple_c",
                 "C implementation of a StaticTuple structure",
                 static_tuple_c_methods);
    if (m == NULL) {
      return PYMOD_ERROR;
    }

    Py_INCREF(&StaticTuple_Type);
    PyModule_AddObject(m, "StaticTuple", (PyObject *)&StaticTuple_Type);
    if (import_breezy__bzr___simple_set_pyx() == -1) {
        return PYMOD_ERROR;
    }
    setup_interned_tuples(m);
    setup_empty_tuple(m);
    setup_c_api(m);

    return PYMOD_SUCCESS(m);
}

// vim: tabstop=4 sw=4 expandtab
