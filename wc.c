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
#include <Python.h>
#include <apr_general.h>
#include <svn_wc.h>
#include <svn_path.h>
#include <structmember.h>
#include <stdbool.h>

#include "util.h"
#include "editor.h"

PyAPI_DATA(PyTypeObject) Entry_Type;
PyAPI_DATA(PyTypeObject) Adm_Type;

static PyObject *py_entry(const svn_wc_entry_t *entry);

static svn_error_t *py_ra_report_set_path(void *baton, const char *path, long revision, int start_empty, const char *lock_token, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)baton, *py_lock_token, *ret;
	if (lock_token == NULL) {
		py_lock_token = Py_None;
	} else {
		py_lock_token = PyString_FromString(lock_token);
	}
	ret = PyObject_CallMethod(self, "set_path", "slbO", path, revision, start_empty, py_lock_token);
	if (ret == NULL)
		return py_svn_error();
	return NULL;
}

static svn_error_t *py_ra_report_delete_path(void *baton, const char *path, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)baton, *ret;
	ret = PyObject_CallMethod(self, "delete_path", "s", path);
	if (ret == NULL)
		return py_svn_error();
	return NULL;
}

static svn_error_t *py_ra_report_link_path(void *report_baton, const char *path, const char *url, long revision, int start_empty, const char *lock_token, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)report_baton, *ret, *py_lock_token;
	if (lock_token == NULL) {
		py_lock_token = Py_None;
	} else { 
		py_lock_token = PyString_FromString(lock_token);
	}
	ret = PyObject_CallMethod(self, "link_path", "sslbO", path, url, revision, start_empty, py_lock_token);
	if (ret == NULL)
		return py_svn_error();
	return NULL;
}

static svn_error_t *py_ra_report_finish(void *baton, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)baton, *ret;
	ret = PyObject_CallMethod(self, "finish", "");
	if (ret == NULL)
		return py_svn_error();
	return NULL;
}

static svn_error_t *py_ra_report_abort(void *baton, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)baton, *ret;
	ret = PyObject_CallMethod(self, "abort", "");
	if (ret == NULL)
		return py_svn_error();
	return NULL;
}

static const svn_ra_reporter2_t py_ra_reporter = {
	py_ra_report_set_path,
	py_ra_report_delete_path,
	py_ra_report_link_path,
	py_ra_report_finish,
	py_ra_report_abort,
};



/**
 * Get libsvn_wc version information.
 *
 * :return: tuple with major, minor, patch version number and tag.
 */
static PyObject *version(PyObject *self)
{
	const svn_version_t *ver = svn_wc_version();
	return Py_BuildValue("(iiis)", ver->major, ver->minor, 
						 ver->patch, ver->tag);
}

static svn_error_t *py_wc_found_entry(const char *path, const svn_wc_entry_t *entry, void *walk_baton, apr_pool_t *pool)
{
	PyObject *fn = (PyObject *)walk_baton, *ret;
	ret = PyObject_CallFunction(fn, "sO", path, py_entry(entry));
	if (ret == NULL)
		return py_svn_error();
	return NULL;
}

static svn_wc_entry_callbacks_t py_wc_entry_callbacks = {
	py_wc_found_entry
};

void py_wc_notify_func(void *baton, const svn_wc_notify_t *notify, apr_pool_t *pool)
{
	PyObject *func = baton, *ret;
	if (func == Py_None)
		return;

	if (notify->err != NULL) {
		ret = PyObject_CallFunction(func, "O", PyErr_NewSubversionException(notify->err));
		Py_XDECREF(ret);
		/* FIXME: Use return value */
	}
}

typedef struct {
	PyObject_HEAD
	apr_pool_t *pool;
	svn_wc_entry_t entry;
} EntryObject;

static void entry_dealloc(PyObject *self)
{
	apr_pool_destroy(((EntryObject *)self)->pool);
	PyObject_Del(self);
}

static PyMemberDef entry_members[] = {
	{ "name", T_STRING, offsetof(EntryObject, entry.name), READONLY, NULL },
	{ "copyfrom_url", T_STRING, offsetof(EntryObject, entry.copyfrom_url), READONLY, NULL },
	{ "copyfrom_rev", T_LONG, offsetof(EntryObject, entry.copyfrom_rev), READONLY, NULL },
	{ "url", T_STRING, offsetof(EntryObject, entry.url), READONLY, NULL },
	{ "repos", T_STRING, offsetof(EntryObject, entry.repos), READONLY, NULL },
	{ "schedule", T_INT, offsetof(EntryObject, entry.schedule), READONLY, NULL },
	{ "kind", T_INT, offsetof(EntryObject, entry.kind), READONLY, NULL },
	{ "revision", T_LONG, offsetof(EntryObject, entry.revision), READONLY, NULL },
	{ "cmt_rev", T_LONG, offsetof(EntryObject, entry.cmt_rev), READONLY, NULL },
	{ NULL, }
};

PyTypeObject Entry_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	"wc.Entry", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(EntryObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	entry_dealloc, /*	destructor tp_dealloc;	*/
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
	NULL, /*	struct PyMethodDef *tp_methods;	*/
	entry_members, /*	struct PyMemberDef *tp_members;	*/

};

static PyObject *py_entry(const svn_wc_entry_t *entry)
{
	EntryObject *ret = PyObject_New(EntryObject, &Entry_Type);
	if (ret == NULL)
		return NULL;

	ret->pool = Pool(NULL);
	if (ret->pool == NULL)
		return NULL;
	ret->entry = *svn_wc_entry_dup(entry, ret->pool);
	return (PyObject *)ret;
}

typedef struct {
	PyObject_HEAD
	svn_wc_adm_access_t *adm;
	apr_pool_t *pool;
} AdmObject;

static PyObject *adm_init(PyTypeObject *self, PyObject *args, PyObject *kwargs)
{
	PyObject *associated;
	char *path;
	bool write_lock=false;
	int depth=0;
	PyObject *cancel_func=Py_None;
	svn_wc_adm_access_t *parent_wc;
	AdmObject *ret;
	char *kwnames[] = { "associated", "path", "write_lock", "depth", "cancel_func", NULL };

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "Os|biO", kwnames, &associated, &path, &write_lock, &depth, &cancel_func))
		return NULL;

	ret = PyObject_New(AdmObject, &Adm_Type);
	if (ret == NULL)
		return NULL;

	ret->pool = Pool(NULL);
	if (ret->pool == NULL)
		return NULL;
	if (associated == Py_None) {
		parent_wc = NULL;
	} else {
		parent_wc = ((AdmObject *)associated)->adm;
	}
	if (!check_error(svn_wc_adm_open3(&ret->adm, parent_wc, path, 
					 write_lock, depth, py_cancel_func, cancel_func, 
					 ret->pool)))
		return NULL;

	return (PyObject *)ret;
}

static PyObject *adm_access_path(PyObject *self)
{
	AdmObject *admobj = (AdmObject *)self;
	return PyString_FromString(svn_wc_adm_access_path(admobj->adm));
}

static PyObject *adm_locked(PyObject *self)
{
	AdmObject *admobj = (AdmObject *)self;
	return PyBool_FromLong(svn_wc_adm_locked(admobj->adm));
}

static PyObject *adm_prop_get(PyObject *self, PyObject *args)
{
	char *name, *path;
	AdmObject *admobj = (AdmObject *)self;
	const svn_string_t *value;
	apr_pool_t *temp_pool;
	PyObject *ret;

	if (!PyArg_ParseTuple(args, "ss", &name, &path))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_prop_get(&value, name, path, admobj->adm, temp_pool));
	if (value == NULL || value->data == NULL) {
		ret = Py_None;
	} else {
		ret = PyString_FromStringAndSize(value->data, value->len);
	}
	apr_pool_destroy(temp_pool);
	return ret;
}

static PyObject *adm_prop_set(PyObject *self, PyObject *args)
{
	char *name, *value, *path; 
	AdmObject *admobj = (AdmObject *)self;
	bool skip_checks=false;
	apr_pool_t *temp_pool;
	int vallen;
	svn_string_t *cvalue;

	if (!PyArg_ParseTuple(args, "ss#s|b", &name, &value, &vallen, &path, &skip_checks))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	cvalue = svn_string_ncreate(value, vallen, temp_pool);
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_prop_set2(name, cvalue, path, admobj->adm, 
				skip_checks, temp_pool));
	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
}

static PyObject *adm_entries_read(PyObject *self, PyObject *args)
{
	apr_hash_t *entries;
	AdmObject *admobj = (AdmObject *)self;
	apr_pool_t *temp_pool;
	bool show_hidden=false;
	apr_hash_index_t *idx;
	const char *key;
	apr_ssize_t klen;
	svn_wc_entry_t *entry;
	PyObject *py_entries;

	if (!PyArg_ParseTuple(args, "|b", &show_hidden))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_entries_read(&entries, admobj->adm, 
				 show_hidden, temp_pool));
	py_entries = PyDict_New();
	idx = apr_hash_first(temp_pool, entries);
	while (idx != NULL) {
		apr_hash_this(idx, (const void **)&key, &klen, (void **)&entry);
		PyDict_SetItemString(py_entries, key, py_entry(entry));
		idx = apr_hash_next(idx);
	}
	apr_pool_destroy(temp_pool);
	return py_entries;
}

static PyObject *adm_walk_entries(PyObject *self, PyObject *args)
{
	char *path;
	PyObject *callbacks; 
	bool show_hidden=false;
	PyObject *cancel_func=Py_None;
	apr_pool_t *temp_pool;
	AdmObject *admobj = (AdmObject *)self;

	if (!PyArg_ParseTuple(args, "sO|bO", &path, &callbacks, &show_hidden, &cancel_func))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_walk_entries2(path, admobj->adm, 
				&py_wc_entry_callbacks, (void *)callbacks,
				show_hidden, py_cancel_func, (void *)cancel_func,
				temp_pool));
	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
}

static PyObject *adm_entry(PyObject *self, PyObject *args)
{
	char *path;
	bool show_hidden=false;
	apr_pool_t *temp_pool;
	AdmObject *admobj = (AdmObject *)self;
	const svn_wc_entry_t *entry;

	if (!PyArg_ParseTuple(args, "s|b", &path, &show_hidden))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_entry(&entry, path, admobj->adm, show_hidden, temp_pool));
	apr_pool_destroy(temp_pool);

	return py_entry(entry);
}

static PyObject *adm_get_prop_diffs(PyObject *self, PyObject *args)
{
	char *path;
	apr_pool_t *temp_pool;
	apr_array_header_t *propchanges;
	apr_hash_t *original_props;
	AdmObject *admobj = (AdmObject *)self;
	svn_prop_t el;
	int i;
	PyObject *py_propchanges, *py_orig_props, *pyval;

	if (!PyArg_ParseTuple(args, "s", &path))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_get_prop_diffs(&propchanges, &original_props, 
				svn_path_canonicalize(path, temp_pool), admobj->adm, temp_pool));
	py_propchanges = PyList_New(propchanges->nelts);
	for (i = 0; i < propchanges->nelts; i++) {
		el = APR_ARRAY_IDX(propchanges, i, svn_prop_t);
		pyval = Py_BuildValue("(ss#)", el.name, el.value->data, el.value->len);
		if (pyval == NULL) {
			apr_pool_destroy(temp_pool);
			return NULL;
		}
		PyList_SetItem(py_propchanges, i, pyval);
	}
	py_orig_props = prop_hash_to_dict(original_props);
	apr_pool_destroy(temp_pool);
	if (py_orig_props == NULL)
		return NULL;
	return Py_BuildValue("(NN)", py_propchanges, py_orig_props);
}

static PyObject *adm_add(PyObject *self, PyObject *args)
{
	char *path, *copyfrom_url=NULL;
	svn_revnum_t copyfrom_rev=-1; 
	PyObject *cancel_func=Py_None, *notify_func=Py_None;
	AdmObject *admobj = (AdmObject *)self;
	apr_pool_t *temp_pool;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	if (!PyArg_ParseTuple(args, "s|zlOO", &path, &copyfrom_url, &copyfrom_rev, &cancel_func, &notify_func))
		return NULL;

	RUN_SVN_WITH_POOL(temp_pool, svn_wc_add2(path, admobj->adm, copyfrom_url, 
							copyfrom_rev, py_cancel_func, 
							(void *)cancel_func,
							py_wc_notify_func, 
							(void *)notify_func, 
							temp_pool));
	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
}

static PyObject *adm_copy(PyObject *self, PyObject *args)
{
	AdmObject *admobj = (AdmObject *)self;
	char *src, *dst; 
	PyObject *cancel_func=Py_None, *notify_func=Py_None;
	apr_pool_t *temp_pool;

	if (!PyArg_ParseTuple(args, "ss|OO", &src, &dst, &cancel_func, &notify_func))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_copy2(src, admobj->adm, dst,
							py_cancel_func, (void *)cancel_func,
							py_wc_notify_func, (void *)notify_func, 
							temp_pool));
	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
}

static PyObject *adm_delete(PyObject *self, PyObject *args)
{
	AdmObject *admobj = (AdmObject *)self;
	apr_pool_t *temp_pool;
	char *path;
	PyObject *cancel_func=Py_None, *notify_func=Py_None;

	if (!PyArg_ParseTuple(args, "s|OO", &path, &cancel_func, &notify_func))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_delete2(path, admobj->adm, 
							py_cancel_func, (void *)cancel_func,
							py_wc_notify_func, (void *)notify_func, 
							temp_pool));
	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
}

static PyObject *adm_crawl_revisions(PyObject *self, PyObject *args, PyObject *kwargs)
{
	char *path;
	PyObject *reporter;
	bool restore_files=true, recurse=true, use_commit_times=true;
	PyObject *notify_func=Py_None;
	apr_pool_t *temp_pool;
	AdmObject *admobj = (AdmObject *)self;
	svn_wc_traversal_info_t *traversal_info;
	char *kwnames[] = { "path", "reporter", "restore_files", "recurse", "use_commit_times", "notify_func", NULL };

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "sO|bbbO", kwnames, &path, &reporter, &restore_files, &recurse, &use_commit_times,
						  &notify_func))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	traversal_info = svn_wc_init_traversal_info(temp_pool);
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_crawl_revisions2(path, admobj->adm, 
				&py_ra_reporter, (void *)reporter, 
				restore_files, recurse, use_commit_times, 
				py_wc_notify_func, (void *)notify_func,
				traversal_info, temp_pool));
	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
}

static PyObject *adm_get_update_editor(PyObject *self, PyObject *args)
{
	char *target;
	bool use_commit_times=true, recurse=true;
	PyObject * notify_func=Py_None, *cancel_func=Py_None;
	char *diff3_cmd=NULL;
	const svn_delta_editor_t *editor;
	AdmObject *admobj = (AdmObject *)self;
	void *edit_baton;
	apr_pool_t *pool;
	svn_revnum_t *latest_revnum;

	if (!PyArg_ParseTuple(args, "s|bbOOz", &target, &use_commit_times, &recurse, &notify_func, &cancel_func, &diff3_cmd))
		return NULL;

	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;
	latest_revnum = (svn_revnum_t *)apr_palloc(pool, sizeof(svn_revnum_t));
	if (!check_error(svn_wc_get_update_editor2(latest_revnum, admobj->adm, target, 
				use_commit_times, recurse, py_wc_notify_func, (void *)notify_func, 
				py_cancel_func, (void *)cancel_func, diff3_cmd, &editor, &edit_baton, 
				NULL, pool))) {
		apr_pool_destroy(pool);
		return NULL;
	}
	return new_editor_object(editor, edit_baton, pool, &Editor_Type, NULL, NULL);
}

static bool py_dict_to_wcprop_changes(PyObject *dict, apr_pool_t *pool, apr_array_header_t **ret)
{
	PyObject *key, *val;
	Py_ssize_t idx;

	if (dict == Py_None) {
		*ret = NULL;
		return true;
	}

	if (!PyDict_Check(dict)) {
		PyErr_SetString(PyExc_TypeError, "Expected dictionary with property changes");
		return false;
	}

	*ret = apr_array_make(pool, PyDict_Size(dict), sizeof(char *));

	while (PyDict_Next(dict, &idx, &key, &val)) {
		   svn_prop_t *prop = apr_palloc(pool, sizeof(svn_prop_t));
		   prop->name = PyString_AsString(key);
		   if (val == Py_None) {
			   prop->value = NULL;
		   } else {
			   prop->value = svn_string_ncreate(PyString_AsString(val), PyString_Size(val), pool);
		   }
		   APR_ARRAY_PUSH(*ret, svn_prop_t *) = prop;
	}

	return true;
}

static PyObject *adm_process_committed(PyObject *self, PyObject *args, PyObject *kwargs)
{
	char *path, *rev_date, *rev_author;
	bool recurse, remove_lock = false;
	unsigned char *digest = NULL;
	svn_revnum_t new_revnum;
	PyObject *py_wcprop_changes = Py_None;
	apr_array_header_t *wcprop_changes;
	AdmObject *admobj = (AdmObject *)self;
	apr_pool_t *temp_pool;
	char *kwnames[] = { "path", "recurse", "new_revnum", "rev_date", "rev_author", 
						"wcprop_changes", "remove_lock", "digest", NULL };

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "sblss|Obs", kwnames, 
									 &path, &recurse, &new_revnum, &rev_date,
									 &rev_author, &py_wcprop_changes, 
									 &remove_lock, &digest))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	if (!py_dict_to_wcprop_changes(py_wcprop_changes, temp_pool, &wcprop_changes)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}

	RUN_SVN_WITH_POOL(temp_pool, svn_wc_process_committed3(path, admobj->adm, recurse, new_revnum, 
														   rev_date, rev_author, wcprop_changes, 
														   remove_lock, digest, temp_pool));

	apr_pool_destroy(temp_pool);

	return Py_None;
}

static PyObject *adm_close(PyObject *self)
{
	AdmObject *admobj = (AdmObject *)self;
	if (admobj->adm != NULL) {
		svn_wc_adm_close(admobj->adm);
		admobj->adm = NULL;
	}

	Py_RETURN_NONE;
}

static void adm_dealloc(PyObject *self)
{
	apr_pool_destroy(((AdmObject *)self)->pool);
	PyObject_Del(self);
}

static PyMethodDef adm_methods[] = { 
	{ "prop_set", adm_prop_set, METH_VARARGS, NULL },
	{ "access_path", (PyCFunction)adm_access_path, METH_NOARGS, NULL },
	{ "prop_get", adm_prop_get, METH_VARARGS, NULL },
	{ "entries_read", adm_entries_read, METH_VARARGS, NULL },
	{ "walk_entries", adm_walk_entries, METH_VARARGS, NULL },
	{ "locked", (PyCFunction)adm_locked, METH_NOARGS, NULL },
	{ "get_prop_diffs", adm_get_prop_diffs, METH_VARARGS, NULL },
	{ "add", adm_add, METH_VARARGS, NULL },
	{ "copy", adm_copy, METH_VARARGS, NULL },
	{ "delete", adm_delete, METH_VARARGS, NULL },
	{ "crawl_revisions", (PyCFunction)adm_crawl_revisions, METH_VARARGS|METH_KEYWORDS, NULL },
	{ "get_update_editor", adm_get_update_editor, METH_VARARGS, NULL },
	{ "close", (PyCFunction)adm_close, METH_NOARGS, NULL },
	{ "entry", (PyCFunction)adm_entry, METH_VARARGS, NULL },
	{ "process_committed", (PyCFunction)adm_process_committed, METH_VARARGS|METH_KEYWORDS, NULL },
	{ NULL, }
};

PyTypeObject Adm_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	"wc.WorkingCopy", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(AdmObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	adm_dealloc, /*	destructor tp_dealloc;	*/
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
	adm_methods, /*	struct PyMethodDef *tp_methods;	*/
	NULL, /*	struct PyMemberDef *tp_members;	*/
	NULL, /*	struct PyGetSetDef *tp_getset;	*/
	NULL, /*	struct _typeobject *tp_base;	*/
	NULL, /*	PyObject *tp_dict;	*/
	NULL, /*	descrgetfunc tp_descr_get;	*/
	NULL, /*	descrsetfunc tp_descr_set;	*/
	0, /*	Py_ssize_t tp_dictoffset;	*/
	NULL, /*	initproc tp_init;	*/
	NULL, /*	allocfunc tp_alloc;	*/
	adm_init, /*	newfunc tp_new;	*/

};

/** 
 * Determine the revision status of a specified working copy.
 *
 * :return: Tuple with minimum and maximum revnums found, whether the 
 * working copy was switched and whether it was modified.
 */
static PyObject *revision_status(PyObject *self, PyObject *args, PyObject *kwargs)
{
	char *kwnames[] = { "wc_path", "trail_url", "committed", "cancel_func", NULL };
	char *wc_path, *trail_url=NULL;
	bool committed=false;
	PyObject *cancel_func=Py_None, *ret;
	 svn_wc_revision_status_t *revstatus;
	apr_pool_t *temp_pool;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|zbO", kwnames, &wc_path, &trail_url, &committed, 
						  &cancel_func))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_wc_revision_status(&revstatus, wc_path, trail_url,
				 committed, py_cancel_func, cancel_func, temp_pool));
	ret = Py_BuildValue("(llbb)", revstatus->min_rev, revstatus->max_rev, 
			revstatus->switched, revstatus->modified);
	apr_pool_destroy(temp_pool);
	return ret;
}

static PyObject *is_normal_prop(PyObject *self, PyObject *args)
{
	char *name;

	if (!PyArg_ParseTuple(args, "s", &name))
		return NULL;

	return PyBool_FromLong(svn_wc_is_normal_prop(name));
}

static PyObject *is_adm_dir(PyObject *self, PyObject *args)
{
	char *name;
	apr_pool_t *pool;
	svn_boolean_t ret;

	if (!PyArg_ParseTuple(args, "s", &name))
		return NULL;

	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;

	ret = svn_wc_is_adm_dir(name, pool);

	apr_pool_destroy(pool);

	return PyBool_FromLong(ret);
}

static PyObject *is_wc_prop(PyObject *self, PyObject *args)
{
	char *name;

	if (!PyArg_ParseTuple(args, "s", &name))
		return NULL;

	return PyBool_FromLong(svn_wc_is_wc_prop(name));
}

static PyObject *is_entry_prop(PyObject *self, PyObject *args)
{
	char *name;

	if (!PyArg_ParseTuple(args, "s", &name))
		return NULL;

	return PyBool_FromLong(svn_wc_is_entry_prop(name));
}

static PyObject *get_adm_dir(PyObject *self)
{
	apr_pool_t *pool;
	PyObject *ret;
	const char *dir;
	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;
	dir = svn_wc_get_adm_dir(pool);
	ret = PyString_FromString(dir);
	apr_pool_destroy(pool);
	return ret;
}

static PyObject *get_pristine_copy_path(PyObject *self, PyObject *args)
{
	apr_pool_t *pool;
	const char *pristine_path;
	char *path;
	PyObject *ret;

	if (!PyArg_ParseTuple(args, "s", &path))
		return NULL;

	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(pool, svn_wc_get_pristine_copy_path(path, &pristine_path, pool));
	ret = PyString_FromString(pristine_path);
	apr_pool_destroy(pool);
	return ret;
}

static PyObject *ensure_adm(PyObject *self, PyObject *args, PyObject *kwargs)
{
	char *path, *uuid, *url;
	char *repos=NULL; 
	svn_revnum_t rev=-1;
	apr_pool_t *pool;
	char *kwnames[] = { "path", "uuid", "url", "repos", "rev", NULL };

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "sss|sl", kwnames, 
									 &path, &uuid, &url, &repos, &rev))
		return NULL;

	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(pool, 
					  svn_wc_ensure_adm2(path, uuid, url, repos, rev, pool));
	apr_pool_destroy(pool);
	Py_RETURN_NONE;
}

static PyObject *check_wc(PyObject *self, PyObject *args)
{
	char *path;
	apr_pool_t *pool;
	int wc_format;

	if (!PyArg_ParseTuple(args, "s", &path))
		return NULL;

	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(pool, svn_wc_check_wc(path, &wc_format, pool));
	apr_pool_destroy(pool);
	return PyLong_FromLong(wc_format);
}

static PyMethodDef wc_methods[] = {
	{ "check_wc", check_wc, METH_VARARGS, NULL },
	{ "ensure_adm", (PyCFunction)ensure_adm, METH_KEYWORDS|METH_VARARGS, NULL },
	{ "get_adm_dir", (PyCFunction)get_adm_dir, METH_NOARGS, NULL },
	{ "get_pristine_copy_path", get_pristine_copy_path, METH_VARARGS, NULL },
	{ "is_adm_dir", is_adm_dir, METH_VARARGS, NULL },
	{ "is_normal_prop", is_normal_prop, METH_VARARGS, NULL },
	{ "is_entry_prop", is_entry_prop, METH_VARARGS, NULL },
	{ "is_wc_prop", is_wc_prop, METH_VARARGS, NULL },
	{ "revision_status", (PyCFunction)revision_status, METH_KEYWORDS|METH_VARARGS, NULL },
	{ "version", (PyCFunction)version, METH_NOARGS, NULL },
	{ NULL, }
};

void initwc(void)
{
	PyObject *mod;

	if (PyType_Ready(&Entry_Type) < 0)
		return;

	if (PyType_Ready(&Adm_Type) < 0)
		return;

	if (PyType_Ready(&Editor_Type) < 0)
		return;

	if (PyType_Ready(&FileEditor_Type) < 0)
		return;

	if (PyType_Ready(&DirectoryEditor_Type) < 0)
		return;

	if (PyType_Ready(&TxDeltaWindowHandler_Type) < 0)
		return;

	apr_initialize();

	mod = Py_InitModule3("wc", wc_methods, "Working Copies");
	if (mod == NULL)
		return;

	PyModule_AddIntConstant(mod, "SCHEDULE_NORMAL", 0);
	PyModule_AddIntConstant(mod, "SCHEDULE_ADD", 1);
	PyModule_AddIntConstant(mod, "SCHEDULE_DELETE", 2);
	PyModule_AddIntConstant(mod, "SCHEDULE_REPLACE", 3);

	PyModule_AddObject(mod, "WorkingCopy", (PyObject *)&Adm_Type);
	Py_INCREF(&Adm_Type);
}
