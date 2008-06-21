/*
 * Copyright © 2008 Jelmer Vernooij <jelmer@samba.org>
 * -*- coding: utf-8 -*-
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

#ifndef _BZR_SVN_RA_H_
#define _BZR_SVN_RA_H_

PyAPI_DATA(PyTypeObject) Auth_Type;

typedef struct {
	PyObject_HEAD
    svn_auth_baton_t *auth_baton;
    apr_pool_t *pool;
    PyObject *providers;
} AuthObject;

#endif /* _BZR_SVN_RA_H_ */
