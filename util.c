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
#include <stdbool.h>
#include <Python.h>
#include <apr_general.h>
#include <svn_error.h>
#include <svn_io.h>
#include <apr_errno.h>
#include <svn_error_codes.h>
#include <svn_config.h>
#include <svn_version.h>

#include "util.h"

#define BZR_SVN_APR_ERROR_OFFSET (APR_OS_START_USERERR + \
								  (50 * SVN_ERR_CATEGORY_SIZE))

void PyErr_SetAprStatus(apr_status_t status)
{
	char errmsg[1024];

	PyErr_SetString(PyExc_Exception, 
		apr_strerror(status, errmsg, sizeof(errmsg)));
}


apr_pool_t *Pool(apr_pool_t *parent)
{
	apr_status_t status;
	apr_pool_t *ret;
	ret = NULL;
	status = apr_pool_create(&ret, parent);
	if (status != 0) {
		PyErr_SetAprStatus(status);
		return NULL;
	}
	return ret;
}

PyObject *PyErr_NewSubversionException(svn_error_t *error)
{
	return Py_BuildValue("(si)", error->message, error->apr_err);
}

void PyErr_SetSubversionException(svn_error_t *error)
{
	PyObject *coremod = PyImport_ImportModule("bzrlib.plugins.svn.core"), *excobj;
	PyObject *excval;

	if (coremod == NULL) {
		return;
	}
		
	excobj = PyObject_GetAttrString(coremod, "SubversionException");
	
	if (excobj == NULL) {
		PyErr_BadInternalCall();
		return;
	}

	excval = Py_BuildValue("(si)", error->message, error->apr_err);
	PyErr_SetObject(excobj, excval);
}

bool check_error(svn_error_t *error)
{
	if (error == NULL)
		return true;

	if (error->apr_err == BZR_SVN_APR_ERROR_OFFSET)
		return false; /* Just let Python deal with it */

	if (error->apr_err == SVN_ERR_RA_NOT_IMPLEMENTED) {
		PyErr_SetString(PyExc_NotImplementedError, error->message);
		return false;
	}

	PyErr_SetSubversionException(error);
	return false;
}

bool string_list_to_apr_array(apr_pool_t *pool, PyObject *l, apr_array_header_t **ret)
{
	int i;
	if (l == Py_None) {
		*ret = NULL;
		return true;
	}
	if (!PyList_Check(l)) {
		PyErr_Format(PyExc_TypeError, "Expected list of strings, got: %s",
					 l->ob_type->tp_name);
		return false;
	}
	*ret = apr_array_make(pool, PyList_Size(l), sizeof(char *));
	for (i = 0; i < PyList_GET_SIZE(l); i++) {
		PyObject *item = PyList_GET_ITEM(l, i);
		if (!PyString_Check(item)) {
			PyErr_Format(PyExc_TypeError, "Expected list of strings, item was %s", item->ob_type->tp_name);
			return false;
		}
		APR_ARRAY_PUSH(*ret, char *) = apr_pstrdup(pool, PyString_AsString(item));
	}
	return true;
}

PyObject *prop_hash_to_dict(apr_hash_t *props)
{
	const char *key;
	apr_hash_index_t *idx;
	apr_ssize_t klen;
	svn_string_t *val;
	apr_pool_t *pool;
	PyObject *py_props;
	if (props == NULL) {
		Py_RETURN_NONE;
	}
	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;
	py_props = PyDict_New();
	for (idx = apr_hash_first(pool, props); idx != NULL; 
		 idx = apr_hash_next(idx)) {
		PyObject *py_val;
		apr_hash_this(idx, (const void **)&key, &klen, (void **)&val);
		if (val == NULL || val->data == NULL)
			py_val = Py_None;
		else
			py_val = PyString_FromStringAndSize(val->data, val->len);
		PyDict_SetItemString(py_props, key, py_val);
		Py_DECREF(py_val);
	}
	apr_pool_destroy(pool);
	return py_props;
}

static PyObject *pyify_changed_paths(apr_hash_t *changed_paths, apr_pool_t *pool)
{
	PyObject *py_changed_paths, *pyval;
	apr_hash_index_t *idx;
	const char *key;
	apr_ssize_t klen;
	svn_log_changed_path_t *val;

	if (changed_paths == NULL) {
		py_changed_paths = Py_None;
	} else {
		py_changed_paths = PyDict_New();
		for (idx = apr_hash_first(pool, changed_paths); idx != NULL;
			 idx = apr_hash_next(idx)) {
			apr_hash_this(idx, (const void **)&key, &klen, (void **)&val);
			pyval = Py_BuildValue("(czi)", val->action, val->copyfrom_path, 
										 val->copyfrom_rev);
			if (pyval == NULL)
				return NULL;
			PyDict_SetItemString(py_changed_paths, key, pyval);
		}
	}

	return py_changed_paths;
}

#if SVN_VER_MAJOR == 1 && SVN_VER_MINOR >= 5
svn_error_t *py_svn_log_entry_receiver(void *baton, svn_log_entry_t *log_entry, apr_pool_t *pool)
{
	PyObject *revprops, *py_changed_paths, *ret;

	py_changed_paths = pyify_changed_paths(log_entry->changed_paths, pool);
	if (py_changed_paths == NULL)
		return py_svn_error();

	revprops = prop_hash_to_dict(log_entry->revprops);
	if (revprops == NULL)
		return py_svn_error();

	ret = PyObject_CallFunction((PyObject *)baton, "OlOb", py_changed_paths, 
								 log_entry->revision, revprops, log_entry->has_children);
	Py_DECREF(py_changed_paths);
	Py_DECREF(revprops);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}
#endif

svn_error_t *py_svn_log_wrapper(void *baton, apr_hash_t *changed_paths, long revision, const char *author, const char *date, const char *message, apr_pool_t *pool)
{
	PyObject *revprops, *py_changed_paths, *ret;

	py_changed_paths = pyify_changed_paths(changed_paths, pool);
	if (py_changed_paths == NULL)
		return py_svn_error();

	revprops = PyDict_New();
	if (message != NULL) {
		PyDict_SetItemString(revprops, SVN_PROP_REVISION_LOG, 
							 PyString_FromString(message));
	}
	if (author != NULL) {
		PyDict_SetItemString(revprops, SVN_PROP_REVISION_AUTHOR, 
							 PyString_FromString(author));
	}
	if (date != NULL) {
		PyDict_SetItemString(revprops, SVN_PROP_REVISION_DATE, 
							 PyString_FromString(date));
	}
	ret = PyObject_CallFunction((PyObject *)baton, "OlOb", py_changed_paths, 
								 revision, revprops, FALSE);
	Py_DECREF(py_changed_paths);
	Py_DECREF(revprops);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

svn_error_t *py_svn_error()
{
	return svn_error_create(BZR_SVN_APR_ERROR_OFFSET, NULL, "Error occured in python bindings");
}

PyObject *wrap_lock(svn_lock_t *lock)
{
	return Py_BuildValue("(zzzbzz)", lock->path, lock->token, lock->owner, 
						 lock->comment, lock->is_dav_comment, 
						 lock->creation_date, lock->expiration_date);
}

apr_array_header_t *revnum_list_to_apr_array(apr_pool_t *pool, PyObject *l)
{
	int i;
	apr_array_header_t *ret;
	if (l == Py_None) {
		return NULL;
	}
	ret = apr_array_make(pool, PyList_Size(l), sizeof(svn_revnum_t));
	if (ret == NULL) {
		PyErr_NoMemory();
		return NULL;
	}
	for (i = 0; i < PyList_Size(l); i++) {
		APR_ARRAY_PUSH(ret, svn_revnum_t) = PyLong_AsLong(PyList_GetItem(l, i));
	}
	return ret;
}


static svn_error_t *py_stream_read(void *baton, char *buffer, apr_size_t *length)
{
	PyObject *self = (PyObject *)baton, *ret;
	ret = PyObject_CallMethod(self, "read", "i", *length);
	if (ret == NULL)
		return py_svn_error();
	if (!PyString_Check(ret)) {
		PyErr_SetString(PyExc_TypeError, "Expected stream read function to return string");
		return py_svn_error();
	}
	*length = PyString_Size(ret);
	memcpy(buffer, PyString_AS_STRING(ret), *length);
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_stream_write(void *baton, const char *data, apr_size_t *len)
{
	PyObject *self = (PyObject *)baton, *ret;
	ret = PyObject_CallMethod(self, "write", "s#", data, len[0]);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_stream_close(void *baton)
{
	PyObject *self = (PyObject *)baton, *ret;
	ret = PyObject_CallMethod(self, "close", "");
	Py_DECREF(self);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

svn_stream_t *new_py_stream(apr_pool_t *pool, PyObject *py)
{
	svn_stream_t *stream;
	Py_INCREF(py);
	stream = svn_stream_create((void *)py, pool);
	svn_stream_set_read(stream, py_stream_read);
	svn_stream_set_write(stream, py_stream_write);
	svn_stream_set_close(stream, py_stream_close);
	return stream;
}

svn_error_t *py_cancel_func(void *cancel_baton)
{
	PyObject *py_fn = (PyObject *)cancel_baton;
	if (py_fn != Py_None) {
		PyObject *ret = PyObject_CallFunction(py_fn, "");
		if (PyBool_Check(ret) && ret == Py_True) {
			Py_DECREF(ret);
			return svn_error_create(SVN_ERR_CANCELLED, NULL, NULL);
		}
		Py_DECREF(ret);
	}
	return NULL;
}

apr_hash_t *config_hash_from_object(PyObject *config, apr_pool_t *pool)
{
	Py_ssize_t idx = 0;
	PyObject *key, *value;
	apr_hash_t *config_hash;
	PyObject *dict;
	if (config == Py_None) {
		RUN_SVN_WITH_POOL(pool, 
					  svn_config_get_config(&config_hash, NULL, pool));
		return config_hash;
	}

	config_hash = apr_hash_make(pool);

	if (PyDict_Check(config)) {
		dict = config;
	} else {
		dict = PyObject_GetAttrString(config, "__dict__");
	}
	
	if (!PyDict_Check(dict)) {
		PyErr_Format(PyExc_TypeError, "Expected dictionary for config, got %s", dict->ob_type->tp_name);
		return NULL;
	}

	while (PyDict_Next(dict, &idx, &key, &value)) {
		apr_hash_set(config_hash, apr_pstrdup(pool, PyString_AsString(key)), 
					 PyString_Size(key), apr_pstrdup(pool, PyString_AsString(value)));
	}

	return config_hash;
}


