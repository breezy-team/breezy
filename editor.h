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

#ifndef _BZR_SVN_EDITOR_H_
#define _BZR_SVN_EDITOR_H_

#pragma GCC visibility push(hidden)

PyAPI_DATA(PyTypeObject) DirectoryEditor_Type;
PyAPI_DATA(PyTypeObject) FileEditor_Type;
PyAPI_DATA(PyTypeObject) Editor_Type;
PyAPI_DATA(PyTypeObject) TxDeltaWindowHandler_Type;
PyObject *new_editor_object(const svn_delta_editor_t *editor, void *baton, apr_pool_t *pool, PyTypeObject *type, void (*done_cb) (void *baton), void *done_baton);

#define DirectoryEditor_Check(op) PyObject_TypeCheck(op, &DirectoryEditor_Type)
#define FileEditor_Check(op) PyObject_TypeCheck(op, &FileEditor_Type)
#define Editor_Check(op) PyObject_TypeCheck(op, &Editor_Type)
#define TxDeltaWindowHandler_Check(op) PyObject_TypeCheck(op, &TxDeltaWindowHandler_Type)

typedef struct {
	PyObject_HEAD
	svn_txdelta_window_handler_t txdelta_handler;
	void *txdelta_baton;
} TxDeltaWindowHandlerObject;

#pragma GCC visibility pop

#endif /* _BZR_SVN_EDITOR_H_ */
