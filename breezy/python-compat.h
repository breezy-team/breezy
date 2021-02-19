/*
 *  Bazaar -- distributed version control
 *
 * Copyright (C) 2008 by Canonical Ltd
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

/* Provide the typedefs that pyrex does automatically in newer versions, to
 * allow older versions  to build our extensions.
 */

#ifndef _BZR_PYTHON_COMPAT_H
#define _BZR_PYTHON_COMPAT_H

#ifdef _MSC_VER
#define inline __inline
#endif

#if PY_MAJOR_VERSION >= 3

#define PyInt_FromSsize_t PyLong_FromSsize_t

/* On Python 3 just don't intern bytes for now */
#define PyBytes_InternFromStringAndSize PyBytes_FromStringAndSize

/* In Python 3 the Py_TPFLAGS_CHECKTYPES behaviour is on by default */
#define Py_TPFLAGS_CHECKTYPES 0

#define PYMOD_ERROR NULL
#define PYMOD_SUCCESS(val) val
#define PYMOD_INIT_FUNC(name) PyMODINIT_FUNC PyInit_##name(void)
#define PYMOD_CREATE(ob, name, doc, methods) do { \
    static struct PyModuleDef moduledef = { \
        PyModuleDef_HEAD_INIT, name, doc, -1, methods \
    }; \
    ob = PyModule_Create(&moduledef); \
    } while(0)

#else

#define PyBytes_Type PyString_Type
#define PyBytes_CheckExact PyString_CheckExact
#define PyBytes_FromStringAndSize PyString_FromStringAndSize
inline PyObject* PyBytes_InternFromStringAndSize(const char *v, Py_ssize_t len)
{
    PyObject *obj = PyString_FromStringAndSize(v, len);
    if (obj != NULL) {
        PyString_InternInPlace(&obj);
    }
    return obj;
}

/* Lazy hide Python 3.3 only functions, callers must avoid on 2.7 anyway */
#define PyUnicode_AsUTF8AndSize(u, size) NULL

#define PYMOD_ERROR
#define PYMOD_SUCCESS(val)
#define PYMOD_INIT_FUNC(name) void init##name(void)
#define PYMOD_CREATE(ob, name, doc, methods) do { \
    ob = Py_InitModule3(name, methods, doc); \
    } while(0)

#endif

#define BrzPy_EnterRecursiveCall(where) (Py_EnterRecursiveCall(where) == 0)

#if defined(_WIN32) || defined(WIN32)
    /* Defining WIN32_LEAN_AND_MEAN makes including windows quite a bit
     * lighter weight.
     */
    #define WIN32_LEAN_AND_MEAN
    #include <windows.h>

    /* Needed for htonl */
    #include "Winsock2.h"

    /* sys/stat.h doesn't have any of these macro definitions for MSVC, so
     * we'll define whatever is missing that we actually use.
     */
    #if !defined(S_ISDIR)
        #define S_ISDIR(m) (((m) & 0170000) == 0040000)
    #endif
    #if !defined(S_ISREG)
        #define S_ISREG(m) (((m) & 0170000) == 0100000)
    #endif
    #if !defined(S_IXUSR)
        #define S_IXUSR 0000100/* execute/search permission, owner */
    #endif
    /* sys/stat.h doesn't have S_ISLNK on win32, so we fake it by just always
     * returning False
     */
    #if !defined(S_ISLNK)
        #define S_ISLNK(mode) (0)
    #endif
#else /* Not win32 */
    /* For htonl */
    #include "arpa/inet.h"
#endif

#include <stdio.h>

#ifdef _MSC_VER
#define  snprintf  _snprintf
/* gcc (mingw32) has strtoll, while the MSVC compiler uses _strtoi64 */
#define strtoll _strtoi64
#define strtoull _strtoui64
#endif

#if PY_VERSION_HEX < 0x030900A4
#  define Py_SET_REFCNT(obj, refcnt) ((Py_REFCNT(obj) = (refcnt)), (void)0)
#endif

#endif /* _BZR_PYTHON_COMPAT_H */
