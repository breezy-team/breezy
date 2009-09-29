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

#if !defined(KeysAPI_FUNC)
#  if defined(_WIN32)
#    define KeysAPI_FUNC(RTYPE) __declspec(dllexport) RTYPE
#  else
#    define KeysAPI_FUNC(RTYPE) RTYPE
#  endif
#endif

#define KEY_HAS_HASH 0

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
#if KEY_HAS_HASH
    long hash;
#endif
    PyStringObject *key_bits[1];
} Key;
extern PyTypeObject Key_Type;

/* Do we need a PyAPI_FUNC sort of wrapper? */
KeysAPI_FUNC(PyObject *) Key_New(Py_ssize_t size);

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
    PyStringObject *key_bits[1]; /* key_width * num_keys entries */
} Keys;

/* Forward declaration */
extern PyTypeObject Keys_Type;

typedef struct {
    PyObject_VAR_HEAD
    Key *table[1];
} KeyIntern;
extern PyTypeObject Key_Type;

#define Key_SET_ITEM(key, offset, val) \
    ((((Key*)key)->key_bits[offset]) = (PyStringObject *)val)
#define Key_GET_ITEM(key, offset) (((Key*)key)->key_bits[offset])

