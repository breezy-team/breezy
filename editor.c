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


PyTypeObject TxDeltaWindowHandler_Type = {
	PyObject_HEAD_INIT(&PyType_Type) 0,
	.tp_basicsize = sizeof(TxDeltaWindowHandlerObject),
	.tp_name = "ra.TxDeltaWindowHandler",
	.tp_call = NULL, /* FIXME */
	.tp_dealloc = (destructor)PyObject_Del
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
	PyObject_HEAD_INIT(&PyType_Type) 0,
	.tp_name = "ra.FileEditor",
	.tp_basicsize = sizeof(EditorObject),
	.tp_methods = py_file_editor_methods,
	.tp_dealloc = (destructor)PyObject_Del,
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
	PyObject_HEAD_INIT(&PyType_Type) 0,
	.tp_name = "ra.DirEditor",
	.tp_basicsize = sizeof(EditorObject),
	.tp_methods = py_dir_editor_methods,
	.tp_dealloc = (destructor)PyObject_Del,
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

	if (editor->done_cb != NULL)
		editor->done_cb(editor->done_baton);

	if (!check_error(editor->editor->close_edit(editor->baton, editor->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *py_editor_abort(PyObject *self)
{
	EditorObject *editor = (EditorObject *)self;

	if (!Editor_Check(self)) {
		PyErr_BadArgument();
		return NULL;
	}

	if (editor->done_cb != NULL)
		editor->done_cb(editor->done_baton);
	
	if (!check_error(editor->editor->abort_edit(editor->baton, editor->pool)))
		return NULL;

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
	PyObject_HEAD_INIT(&PyType_Type) 0,
	.tp_name = "ra.Editor",
	.tp_basicsize = sizeof(EditorObject),
	.tp_methods = py_editor_methods,
	.tp_dealloc = py_editor_dealloc,
};


