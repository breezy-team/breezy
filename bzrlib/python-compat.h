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
 * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 */

/* Provide the typedefs that pyrex does automatically in newer versions, to
 * allow older versions  to build our extensions.
 */

#ifndef _BZR_PYTHON_COMPAT_H
#define _BZR_PYTHON_COMPAT_H

/* http://www.python.org/dev/peps/pep-0353/ */
#if PY_VERSION_HEX < 0x02050000 && !defined(PY_SSIZE_T_MIN)
    typedef int Py_ssize_t;
    #define PY_SSIZE_T_MAX INT_MAX
    #define PY_SSIZE_T_MIN INT_MIN
    #define PyInt_FromSsize_t(z) PyInt_FromLong(z)
    #define PyInt_AsSsize_t(o) PyInt_AsLong(o)
#endif

#endif
