/* Copyright © 2008 Jelmer Vernooij <jelmer@samba.org>
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
#include <stdbool.h>
#include <Python.h>
#include <apr_general.h>
#include <svn_types.h>
#include <svn_delta.h>

#include "editor.h"
#include "util.h"

typedef struct {
	PyObject_HEAD
	const svn_delta_editor_t *editor;
	void *baton;
	apr_pool_t *pool;
	void (*done_cb) (void *baton);
	void *done_baton;
} EditorObject;

PyObject *new_editor_object(const svn_delta_editor_t *editor, void *baton, apr_pool_t *pool, PyTypeObject *type, void (*done_cb) (void *), void *done_baton)
{
	EditorObject *obj = PyObject_New(EditorObject, type);
	if (obj == NULL)
		return NULL;
	obj->editor = editor;
	obj->baton = baton;
	obj->pool = pool;
	obj->done_cb = done_cb;
	obj->done_baton = done_baton;
	return (PyObject *)obj;
}

static void py_editor_dealloc(PyObject *self)
{
	EditorObject *editor = (EditorObject *)self;
	apr_pool_destroy(editor->pool);
	PyObject_Del(self);
}

static PyObject *txdelta_call(PyObject *self, PyObject *args, PyObject *kwargs)
{
	char *kwnames[] = { "window", NULL };
	svn_txdelta_window_t window;
	TxDeltaWindowHandlerObject *obj = (TxDeltaWindowHandlerObject *)self;
	PyObject *py_window, *py_ops, *py_new_data;
	int i;
	svn_string_t new_data;
	svn_txdelta_op_t *ops;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O", kwnames, &py_window))
		return NULL;

	if (py_window == Py_None) {
		if (!check_error(obj->txdelta_handler(NULL, obj->txdelta_baton)))
			return NULL;
		Py_RETURN_NONE;
	}

	if (!PyArg_ParseTuple(py_window, "LIIiOO", &window.sview_offset, &window.sview_len, 
											&window.tview_len, &window.src_ops, &py_ops, &py_new_data))
		return NULL;

	if (py_new_data == Py_None) {
		window.new_data = NULL;
	} else {
		new_data.data = PyString_AsString(py_new_data);
		new_data.len = PyString_Size(py_new_data);
		window.new_data = &new_data;
	}

	if (!PyList_Check(py_ops)) {
		PyErr_SetString(PyExc_TypeError, "ops not a list");
		return NULL;
	}

	window.num_ops = PyList_Size(py_ops);

	window.ops = ops = malloc(sizeof(svn_txdelta_op_t) * window.num_ops);

	for (i = 0; i < window.num_ops; i++) {
		if (!PyArg_ParseTuple(PyList_GetItem(py_ops, i), "iII", &ops[i].action_code, &ops[i].offset, &ops[i].length)) {
			free(ops);
			return NULL;
		}
	}

	if (!check_error(obj->txdelta_handler(&window, obj->txdelta_baton))) {
		free(ops);
		return NULL;
	}

	free(ops);

	Py_RETURN_NONE;
}

PyTypeObject TxDeltaWindowHandler_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	"ra.TxDeltaWindowHandler", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(TxDeltaWindowHandlerObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	(destructor)PyObject_Del, /*	destructor tp_dealloc;	*/
	NULL, /*	printfunc tp_print;	*/
	NULL, /*	getattrfunc tp_getattr;	*/
	NULL, /*	setattrfunc tp_setattr;	*/
	NULL, /*	cmpfunc tp_compare;	*/
	NULL, /*	reprfunc tp_repr;	*/
	
	/* Method suites for standard classes */
	
	NULL, /*	PyNumberMethods *tp_as_number;	*/
	NULL, /*	PySequenceMethods *tp_as_sequence;	*/
	NULL, /*	PyMappingMethods *tp_as_mapping;	*/
	
	/* More standard operations (here for binary compatibility) */
	
	NULL, /*	hashfunc tp_hash;	*/
	txdelta_call, /*	ternaryfunc tp_call;	*/
	
};

static PyObject *py_file_editor_apply_textdelta(PyObject *self, PyObject *args)
{
	EditorObject *editor = (EditorObject *)self;
	char *c_base_checksum = NULL;
	svn_txdelta_window_handler_t txdelta_handler;
	void *txdelta_baton;
	TxDeltaWindowHandlerObject *py_txdelta;

	if (!FileEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "|z", &c_base_checksum))
		return NULL;
	if (!check_error(editor->editor->apply_textdelta(editor->baton,
				c_base_checksum, editor->pool, 
				&txdelta_handler, &txdelta_baton)))
		return NULL;
	py_txdelta = PyObject_New(TxDeltaWindowHandlerObject, &TxDeltaWindowHandler_Type);
	py_txdelta->txdelta_handler = txdelta_handler;
	py_txdelta->txdelta_baton = txdelta_baton;
	return (PyObject *)py_txdelta;
}

static PyObject *py_file_editor_change_prop(PyObject *self, PyObject *args)
{
	EditorObject *editor = (EditorObject *)self;
	char *name;
   	svn_string_t c_value;

	if (!FileEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "sz#", &name, &c_value.data, &c_value.len))
		return NULL;
	if (!check_error(editor->editor->change_file_prop(editor->baton, name, 
				&c_value, editor->pool)))
		return NULL;
	Py_RETURN_NONE;
}

static PyObject *py_file_editor_close(PyObject *self, PyObject *args)
{
	EditorObject *editor = (EditorObject *)self;
	char *c_checksum = NULL;

	if (!FileEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "|z", &c_checksum))
		return NULL;
	if (!check_error(editor->editor->close_file(editor->baton, c_checksum, 
					editor->pool)))
		return NULL;
	Py_RETURN_NONE;
}

static PyMethodDef py_file_editor_methods[] = {
	{ "change_prop", py_file_editor_change_prop, METH_VARARGS, NULL },
	{ "close", py_file_editor_close, METH_VARARGS, NULL },
	{ "apply_textdelta", py_file_editor_apply_textdelta, METH_VARARGS, NULL },
	{ NULL }
};

PyTypeObject FileEditor_Type = { 
	PyObject_HEAD_INIT(NULL) 0, 
	"ra.FileEditor", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(EditorObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	(destructor)PyObject_Del, /*	destructor tp_dealloc;	*/
	NULL, /*	printfunc tp_print;	*/
	NULL, /*	getattrfunc tp_getattr;	*/
	NULL, /*	setattrfunc tp_setattr;	*/
	NULL, /*	cmpfunc tp_compare;	*/
	NULL, /*	reprfunc tp_repr;	*/
	
	/* Method suites for standard classes */
	
	NULL, /*	PyNumberMethods *tp_as_number;	*/
	NULL, /*	PySequenceMethods *tp_as_sequence;	*/
	NULL, /*	PyMappingMethods *tp_as_mapping;	*/
	
	/* More standard operations (here for binary compatibility) */
	
	NULL, /*	hashfunc tp_hash;	*/
	NULL, /*	ternaryfunc tp_call;	*/
	NULL, /*	reprfunc tp_str;	*/
	NULL, /*	getattrofunc tp_getattro;	*/
	NULL, /*	setattrofunc tp_setattro;	*/
	
	/* Functions to access object as input/output buffer */
	NULL, /*	PyBufferProcs *tp_as_buffer;	*/
	
	/* Flags to define presence of optional/expanded features */
	0, /*	long tp_flags;	*/
	
	NULL, /*	const char *tp_doc;  Documentation string */
	
	/* Assigned meaning in release 2.0 */
	/* call function for all accessible objects */
	NULL, /*	traverseproc tp_traverse;	*/
	
	/* delete references to contained objects */
	NULL, /*	inquiry tp_clear;	*/
	
	/* Assigned meaning in release 2.1 */
	/* rich comparisons */
	NULL, /*	richcmpfunc tp_richcompare;	*/
	
	/* weak reference enabler */
	0, /*	Py_ssize_t tp_weaklistoffset;	*/
	
	/* Added in release 2.2 */
	/* Iterators */
	NULL, /*	getiterfunc tp_iter;	*/
	NULL, /*	iternextfunc tp_iternext;	*/
	
	/* Attribute descriptor and subclassing stuff */
	py_file_editor_methods, /*	struct PyMethodDef *tp_methods;	*/
};

static PyObject *py_dir_editor_delete_entry(PyObject *self, PyObject *args)
{
	EditorObject *editor = (EditorObject *)self;
	char *path; 
	svn_revnum_t revision = -1;

	if (!DirectoryEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "s|l", &path, &revision))
		return NULL;

	if (!check_error(editor->editor->delete_entry(path, revision, editor->baton,
											 editor->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *py_dir_editor_add_directory(PyObject *self, PyObject *args)
{
	char *path;
	char *copyfrom_path=NULL; 
	int copyfrom_rev=-1;
   	void *child_baton;
	EditorObject *editor = (EditorObject *)self;

	if (!DirectoryEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "s|zl", &path, &copyfrom_path, &copyfrom_rev))
		return NULL;

	if (!check_error(editor->editor->add_directory(path, editor->baton,
					copyfrom_path, copyfrom_rev, editor->pool, &child_baton)))
		return NULL;

	return new_editor_object(editor->editor, child_baton, editor->pool, 
							 &DirectoryEditor_Type, NULL, NULL);
}

static PyObject *py_dir_editor_open_directory(PyObject *self, PyObject *args)
{
	char *path;
	EditorObject *editor = (EditorObject *)self;
	int base_revision=-1;
	void *child_baton;

	if (!DirectoryEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "s|l", &path, &base_revision))
		return NULL;

	if (!check_error(editor->editor->open_directory(path, editor->baton,
					base_revision, editor->pool, &child_baton)))
		return NULL;

	return new_editor_object(editor->editor, child_baton, editor->pool, 
							 &DirectoryEditor_Type, NULL, NULL);
}

static PyObject *py_dir_editor_change_prop(PyObject *self, PyObject *args)
{
	char *name;
	svn_string_t c_value, *p_c_value;
	EditorObject *editor = (EditorObject *)self;

	if (!DirectoryEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "sz#", &name, &c_value.data, &c_value.len))
		return NULL;

	p_c_value = &c_value;

	if (!check_error(editor->editor->change_dir_prop(editor->baton, name, 
					p_c_value, editor->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *py_dir_editor_close(PyObject *self)
{
	EditorObject *editor = (EditorObject *)self;

	if (!DirectoryEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!check_error(editor->editor->close_directory(editor->baton, 
													 editor->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *py_dir_editor_absent_directory(PyObject *self, PyObject *args)
{
	char *path;
	EditorObject *editor = (EditorObject *)self;

	if (!Editor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}


	if (!PyArg_ParseTuple(args, "s", &path))
		return NULL;
	
	if (!check_error(editor->editor->absent_directory(path, editor->baton, 
					editor->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *py_dir_editor_add_file(PyObject *self, PyObject *args)
{
	char *path, *copy_path=NULL;
	long copy_rev=-1;
	void *file_baton = NULL;
	EditorObject *editor = (EditorObject *)self;

	if (!DirectoryEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "s|zl", &path, &copy_path, &copy_rev))
		return NULL;

	if (!check_error(editor->editor->add_file(path, editor->baton, copy_path,
					copy_rev, editor->pool, &file_baton)))
		return NULL;

	return new_editor_object(editor->editor, file_baton, editor->pool,
							 &FileEditor_Type, NULL, NULL);
}

static PyObject *py_dir_editor_open_file(PyObject *self, PyObject *args)
{
	char *path;
	int base_revision=-1;
	void *file_baton;
	EditorObject *editor = (EditorObject *)self;

	if (!DirectoryEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "s|l", &path, &base_revision))
		return NULL;

	if (!check_error(editor->editor->open_file(path, editor->baton, 
					base_revision, editor->pool, &file_baton)))
		return NULL;

	return new_editor_object(editor->editor, file_baton, editor->pool,
							 &FileEditor_Type, NULL, NULL);
}

static PyObject *py_dir_editor_absent_file(PyObject *self, PyObject *args)
{
	char *path;
	EditorObject *editor = (EditorObject *)self;

	if (!DirectoryEditor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "s", &path))
		return NULL;

	if (!check_error(editor->editor->absent_file(path, editor->baton, editor->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyMethodDef py_dir_editor_methods[] = {
	{ "absent_file", py_dir_editor_absent_file, METH_VARARGS, NULL },
	{ "absent_directory", py_dir_editor_absent_directory, METH_VARARGS, NULL },
	{ "delete_entry", py_dir_editor_delete_entry, METH_VARARGS, NULL },
	{ "add_file", py_dir_editor_add_file, METH_VARARGS, NULL },
	{ "open_file", py_dir_editor_open_file, METH_VARARGS, NULL },
	{ "add_directory", py_dir_editor_add_directory, METH_VARARGS, NULL },
	{ "open_directory", py_dir_editor_open_directory, METH_VARARGS, NULL },
	{ "close", (PyCFunction)py_dir_editor_close, METH_NOARGS, NULL },
	{ "change_prop", py_dir_editor_change_prop, METH_VARARGS, NULL },

	{ NULL, }
};

PyTypeObject DirectoryEditor_Type = { 
	PyObject_HEAD_INIT(NULL) 0,
	"ra.DirEditor", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(EditorObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	(destructor)PyObject_Del, /*	destructor tp_dealloc;	*/
	NULL, /*	printfunc tp_print;	*/
	NULL, /*	getattrfunc tp_getattr;	*/
	NULL, /*	setattrfunc tp_setattr;	*/
	NULL, /*	cmpfunc tp_compare;	*/
	NULL, /*	reprfunc tp_repr;	*/
	
	/* Method suites for standard classes */
	
	NULL, /*	PyNumberMethods *tp_as_number;	*/
	NULL, /*	PySequenceMethods *tp_as_sequence;	*/
	NULL, /*	PyMappingMethods *tp_as_mapping;	*/
	
	/* More standard operations (here for binary compatibility) */
	
	NULL, /*	hashfunc tp_hash;	*/
	NULL, /*	ternaryfunc tp_call;	*/
	NULL, /*	reprfunc tp_str;	*/
	NULL, /*	getattrofunc tp_getattro;	*/
	NULL, /*	setattrofunc tp_setattro;	*/
	
	/* Functions to access object as input/output buffer */
	NULL, /*	PyBufferProcs *tp_as_buffer;	*/
	
	/* Flags to define presence of optional/expanded features */
	0, /*	long tp_flags;	*/
	
	NULL, /*	const char *tp_doc;  Documentation string */
	
	/* Assigned meaning in release 2.0 */
	/* call function for all accessible objects */
	NULL, /*	traverseproc tp_traverse;	*/
	
	/* delete references to contained objects */
	NULL, /*	inquiry tp_clear;	*/
	
	/* Assigned meaning in release 2.1 */
	/* rich comparisons */
	NULL, /*	richcmpfunc tp_richcompare;	*/
	
	/* weak reference enabler */
	0, /*	Py_ssize_t tp_weaklistoffset;	*/
	
	/* Added in release 2.2 */
	/* Iterators */
	NULL, /*	getiterfunc tp_iter;	*/
	NULL, /*	iternextfunc tp_iternext;	*/
	
	/* Attribute descriptor and subclassing stuff */
	py_dir_editor_methods, /*	struct PyMethodDef *tp_methods;	*/
	
};

static PyObject *py_editor_set_target_revision(PyObject *self, PyObject *args)
{
	int target_revision;
	EditorObject *editor = (EditorObject *)self;

	if (!Editor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "i", &target_revision))
		return NULL;

	if (!check_error(editor->editor->set_target_revision(editor->baton,
					target_revision, editor->pool)))
		return NULL;

	Py_RETURN_NONE;
}
	
static PyObject *py_editor_open_root(PyObject *self, PyObject *args)
{
	svn_revnum_t base_revision=-1;
	void *root_baton;
	EditorObject *editor = (EditorObject *)self;

	if (!Editor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!PyArg_ParseTuple(args, "|l:open_root", &base_revision))
		return NULL;

	if (!check_error(editor->editor->open_root(editor->baton, base_revision,
					editor->pool, &root_baton)))
		return NULL;

	return new_editor_object(editor->editor, root_baton, editor->pool,
							 &DirectoryEditor_Type, NULL, NULL);
}

static PyObject *py_editor_close(PyObject *self)
{
	EditorObject *editor = (EditorObject *)self;

	if (!Editor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!check_error(editor->editor->close_edit(editor->baton, editor->pool)))
		return NULL;

	if (editor->done_cb != NULL)
		editor->done_cb(editor->done_baton);

	Py_RETURN_NONE;
}

static PyObject *py_editor_abort(PyObject *self)
{
	EditorObject *editor = (EditorObject *)self;

	if (!Editor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (!check_error(editor->editor->abort_edit(editor->baton, editor->pool)))
		return NULL;

	if (editor->done_cb != NULL)
		editor->done_cb(editor->done_baton);
	
	Py_RETURN_NONE;
}

static PyMethodDef py_editor_methods[] = { 
	{ "abort", (PyCFunction)py_editor_abort, METH_NOARGS, NULL },
	{ "close", (PyCFunction)py_editor_close, METH_NOARGS, NULL },
	{ "open_root", py_editor_open_root, METH_VARARGS, NULL },
	{ "set_target_revision", py_editor_set_target_revision, METH_VARARGS, NULL },
	{ NULL, }
};

PyTypeObject Editor_Type = { 
	PyObject_HEAD_INIT(NULL) 0,
	"ra.Editor", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(EditorObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	py_editor_dealloc, /*	destructor tp_dealloc;	*/
	NULL, /*	printfunc tp_print;	*/
	NULL, /*	getattrfunc tp_getattr;	*/
	NULL, /*	setattrfunc tp_setattr;	*/
	NULL, /*	cmpfunc tp_compare;	*/
	NULL, /*	reprfunc tp_repr;	*/
	
	/* Method suites for standard classes */
	
	NULL, /*	PyNumberMethods *tp_as_number;	*/
	NULL, /*	PySequenceMethods *tp_as_sequence;	*/
	NULL, /*	PyMappingMethods *tp_as_mapping;	*/
	
	/* More standard operations (here for binary compatibility) */
	
	NULL, /*	hashfunc tp_hash;	*/
	NULL, /*	ternaryfunc tp_call;	*/
	NULL, /*	reprfunc tp_str;	*/
	NULL, /*	getattrofunc tp_getattro;	*/
	NULL, /*	setattrofunc tp_setattro;	*/
	
	/* Functions to access object as input/output buffer */
	NULL, /*	PyBufferProcs *tp_as_buffer;	*/
	
	/* Flags to define presence of optional/expanded features */
	0, /*	long tp_flags;	*/
	
	NULL, /*	const char *tp_doc;  Documentation string */
	
	/* Assigned meaning in release 2.0 */
	/* call function for all accessible objects */
	NULL, /*	traverseproc tp_traverse;	*/
	
	/* delete references to contained objects */
	NULL, /*	inquiry tp_clear;	*/
	
	/* Assigned meaning in release 2.1 */
	/* rich comparisons */
	NULL, /*	richcmpfunc tp_richcompare;	*/
	
	/* weak reference enabler */
	0, /*	Py_ssize_t tp_weaklistoffset;	*/
	
	/* Added in release 2.2 */
	/* Iterators */
	NULL, /*	getiterfunc tp_iter;	*/
	NULL, /*	iternextfunc tp_iternext;	*/
	
	/* Attribute descriptor and subclassing stuff */
	py_editor_methods, /*	struct PyMethodDef *tp_methods;	*/
};


