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
#include <svn_ra.h>
#include <svn_path.h>
#include <apr_file_io.h>
#include <apr_portable.h>

#include <structmember.h>

#include "editor.h"
#include "util.h"
#include "ra.h"

static PyObject *busy_exc;

PyAPI_DATA(PyTypeObject) Reporter_Type;
PyAPI_DATA(PyTypeObject) RemoteAccess_Type;
PyAPI_DATA(PyTypeObject) AuthProvider_Type;
PyAPI_DATA(PyTypeObject) CredentialsIter_Type;
PyAPI_DATA(PyTypeObject) TxDeltaWindowHandler_Type;

static svn_error_t *py_commit_callback(const svn_commit_info_t *commit_info, void *baton, apr_pool_t *pool)
{
	PyObject *fn = (PyObject *)baton, *ret;

	if (fn == Py_None)
		return NULL;

	ret = PyObject_CallFunction(fn, "izz", 
								commit_info->revision, commit_info->date, 
								commit_info->author);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static PyObject *pyify_lock(const svn_lock_t *lock)
{
	return Py_BuildValue("(ssszbLL)", 
						 lock->path, lock->token, 
						 lock->owner, lock->comment,
						 lock->is_dav_comment,
						 lock->creation_date,
						 lock->expiration_date);
}

static svn_error_t *py_lock_func (void *baton, const char *path, int do_lock, 
						   const svn_lock_t *lock, svn_error_t *ra_err, 
						   apr_pool_t *pool)
{
	PyObject *py_ra_err = Py_None, *ret, *py_lock;
	if (ra_err != NULL) {
		py_ra_err = PyErr_NewSubversionException(ra_err);
	}
	py_lock = pyify_lock(lock);
	ret = PyObject_CallFunction((PyObject *)baton, "zbOO", path, do_lock, 
						  py_lock, py_ra_err);
	Py_DECREF(py_lock);
	Py_DECREF(py_ra_err);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

/** Connection to a remote Subversion repository. */
typedef struct {
	PyObject_HEAD
	svn_ra_session_t *ra;
	apr_pool_t *pool;
	const char *url;
	PyObject *progress_func;
	AuthObject *auth;
	bool busy;
	PyObject *client_string_func;
	PyObject *open_tmp_file_func;
	char *root;
} RemoteAccessObject;

typedef struct {
	PyObject_HEAD
	const svn_ra_reporter2_t *reporter;
	void *report_baton;
	apr_pool_t *pool;
	RemoteAccessObject *ra;
} ReporterObject;

static PyObject *reporter_set_path(PyObject *self, PyObject *args)
{
	char *path; 
	svn_revnum_t revision; 
	bool start_empty; 
	char *lock_token = NULL;
	ReporterObject *reporter = (ReporterObject *)self;

	if (!PyArg_ParseTuple(args, "slb|z", &path, &revision, &start_empty, 
						  &lock_token))
		return NULL;

	if (!check_error(reporter->reporter->set_path(reporter->report_baton, 
												  path, revision, start_empty, 
					 lock_token, reporter->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *reporter_delete_path(PyObject *self, PyObject *args)
{
	ReporterObject *reporter = (ReporterObject *)self;
	char *path;
	if (!PyArg_ParseTuple(args, "s", &path))
		return NULL;

	if (!check_error(reporter->reporter->delete_path(reporter->report_baton, 
													path, reporter->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *reporter_link_path(PyObject *self, PyObject *args)
{
	char *path, *url;
	svn_revnum_t revision;
	bool start_empty;
	char *lock_token = NULL;
	ReporterObject *reporter = (ReporterObject *)self;

	if (!PyArg_ParseTuple(args, "sslb|z", &path, &url, &revision, &start_empty, &lock_token))
		return NULL;

	if (!check_error(reporter->reporter->link_path(reporter->report_baton, path, url, 
				revision, start_empty, lock_token, reporter->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *reporter_finish(PyObject *self)
{
	ReporterObject *reporter = (ReporterObject *)self;

	reporter->ra->busy = false;

	if (!check_error(reporter->reporter->finish_report(reporter->report_baton, 
													  reporter->pool)))
		return NULL;

	Py_XDECREF(reporter->ra);

	Py_RETURN_NONE;
}

static PyObject *reporter_abort(PyObject *self)
{
	ReporterObject *reporter = (ReporterObject *)self;
	
	reporter->ra->busy = false;

	if (!check_error(reporter->reporter->abort_report(reporter->report_baton, 
													 reporter->pool)))
		return NULL;

	Py_XDECREF(reporter->ra);

	Py_RETURN_NONE;
}

static PyMethodDef reporter_methods[] = {
	{ "abort", (PyCFunction)reporter_abort, METH_NOARGS, NULL },
	{ "finish", (PyCFunction)reporter_finish, METH_NOARGS, NULL },
	{ "link_path", (PyCFunction)reporter_link_path, METH_VARARGS, NULL },
	{ "set_path", (PyCFunction)reporter_set_path, METH_VARARGS, NULL },
	{ "delete_path", (PyCFunction)reporter_delete_path, METH_VARARGS, NULL },
	{ NULL, }
};

static void reporter_dealloc(PyObject *self)
{
	ReporterObject *reporter = (ReporterObject *)self;
	/* FIXME: Warn the user if abort_report/finish_report wasn't called? */
	apr_pool_destroy(reporter->pool);
	PyObject_Del(self);
}

PyTypeObject Reporter_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	"ra.Reporter", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(ReporterObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	reporter_dealloc, /*	destructor tp_dealloc;	*/
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
	reporter_methods, /*	struct PyMethodDef *tp_methods;	*/

};

/**
 * Get libsvn_ra version information.
 *
 * :return: tuple with major, minor, patch version number and tag.
 */
static PyObject *version(PyObject *self)
{
	const svn_version_t *ver = svn_ra_version();
	return Py_BuildValue("(iiis)", ver->major, ver->minor, 
						 ver->patch, ver->tag);
}

static svn_error_t *py_cb_editor_set_target_revision(void *edit_baton, svn_revnum_t target_revision, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)edit_baton, *ret;

	ret = PyObject_CallMethod(self, "set_target_revision", "l", target_revision);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_open_root(void *edit_baton, svn_revnum_t base_revision, apr_pool_t *pool, void **root_baton)
{
	PyObject *self = (PyObject *)edit_baton, *ret;
	*root_baton = NULL;
	ret = PyObject_CallMethod(self, "open_root", "l", base_revision);
	if (ret == NULL)
		return py_svn_error();
	*root_baton = (void *)ret;
	return NULL;
}

static svn_error_t *py_cb_editor_delete_entry(const char *path, long revision, void *parent_baton, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)parent_baton, *ret;
	ret = PyObject_CallMethod(self, "delete_entry", "sl", path, revision);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_add_directory(const char *path, void *parent_baton, const char *copyfrom_path, long copyfrom_revision, apr_pool_t *pool, void **child_baton)
{
	PyObject *self = (PyObject *)parent_baton, *ret;
	*child_baton = NULL;
	if (copyfrom_path == NULL) {
		ret = PyObject_CallMethod(self, "add_directory", "s", path);
	} else {
		ret = PyObject_CallMethod(self, "add_directory", "ssl", path, copyfrom_path, copyfrom_revision);
	}
	if (ret == NULL)
		return py_svn_error();
	*child_baton = (void *)ret;
	return NULL;
}

static svn_error_t *py_cb_editor_open_directory(const char *path, void *parent_baton, long base_revision, apr_pool_t *pool, void **child_baton)
{
	PyObject *self = (PyObject *)parent_baton, *ret;
	*child_baton = NULL;
	ret = PyObject_CallMethod(self, "open_directory", "sl", path, base_revision);
	if (ret == NULL)
		return py_svn_error();
	*child_baton = (void *)ret;
	return NULL;
}

static svn_error_t *py_cb_editor_change_prop(void *dir_baton, const char *name, const svn_string_t *value, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)dir_baton, *ret;

	if (value != NULL) {
		ret = PyObject_CallMethod(self, "change_prop", "sz#", name, value->data, value->len);
	} else {
		ret = PyObject_CallMethod(self, "change_prop", "sO", name, Py_None);
	}
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_close_directory(void *dir_baton, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)dir_baton, *ret;
	ret = PyObject_CallMethod(self, "close", "");
	Py_DECREF(self);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_absent_directory(const char *path, void *parent_baton, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)parent_baton, *ret;
	ret = PyObject_CallMethod(self, "absent_directory", "s", path);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_add_file(const char *path, void *parent_baton, const char *copy_path, long copy_revision, apr_pool_t *file_pool, void **file_baton)
{
	PyObject *self = (PyObject *)parent_baton, *ret;
	if (copy_path == NULL) {
		ret = PyObject_CallMethod(self, "add_file", "s", path);
	} else {
		ret = PyObject_CallMethod(self, "add_file", "ssl", path, copy_path, 
								  copy_revision);
	}
	if (ret == NULL)
		return py_svn_error();
	*file_baton = (void *)ret;
	return NULL;
}

static svn_error_t *py_cb_editor_open_file(const char *path, void *parent_baton, long base_revision, apr_pool_t *file_pool, void **file_baton)
{
	PyObject *self = (PyObject *)parent_baton, *ret;
	ret = PyObject_CallMethod(self, "open_file", "sl", path, base_revision);
	if (ret == NULL)
		return py_svn_error();
	*file_baton = (void *)ret;
	return NULL;
}

static svn_error_t *py_txdelta_window_handler(svn_txdelta_window_t *window, void *baton)
{
	int i;
	PyObject *ops, *ret;
	PyObject *fn = (PyObject *)baton, *py_new_data, *py_window;
	if (fn == Py_None) {
		/* User doesn't care about deltas */
		return NULL;
	}

	if (window == NULL) {
		py_window = Py_None;
		Py_INCREF(py_window);
	} else {
		ops = PyList_New(window->num_ops);
		if (ops == NULL)
			return NULL;
		for (i = 0; i < window->num_ops; i++) {
			PyObject *pyval = Py_BuildValue("(iII)", 
											window->ops[i].action_code, 
											window->ops[i].offset, 
											window->ops[i].length);
			if (pyval == NULL)
				return NULL;
			PyList_SetItem(ops, i, pyval);
		}
		if (window->new_data != NULL && window->new_data->data != NULL) {
			py_new_data = PyString_FromStringAndSize(window->new_data->data, window->new_data->len);
		} else {
			py_new_data = Py_None;
		}
		py_window = Py_BuildValue("((LIIiOO))", 
								  window->sview_offset, 
								  window->sview_len, 
								  window->tview_len, 
								  window->src_ops, ops, py_new_data);
		if (py_window == NULL)
			return NULL;
		Py_DECREF(ops);
		Py_DECREF(py_new_data);
	}
	ret = PyObject_CallFunction(fn, "O", py_window);
	Py_DECREF(py_window);
	if (window == NULL) {
		/* Signals all delta windows have been received */
		Py_DECREF(fn);
	}
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_apply_textdelta(void *file_baton, const char *base_checksum, apr_pool_t *pool, svn_txdelta_window_handler_t *handler, void **handler_baton)
{
	PyObject *self = (PyObject *)file_baton, *ret;
	*handler_baton = NULL;

	ret = PyObject_CallMethod(self, "apply_textdelta", "z", base_checksum);
	if (ret == NULL)
		return py_svn_error();
	*handler_baton = (void *)ret;
	*handler = py_txdelta_window_handler;
	return NULL;
}

static svn_error_t *py_cb_editor_close_file(void *file_baton, 
										 const char *text_checksum, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)file_baton, *ret;

	if (text_checksum != NULL) {
		ret = PyObject_CallMethod(self, "close", "");
	} else {
		ret = PyObject_CallMethod(self, "close", "s", text_checksum);
	}
	Py_DECREF(self);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_absent_file(const char *path, void *parent_baton, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)parent_baton, *ret;
	ret = PyObject_CallMethod(self, "absent_file", "s", path);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_close_edit(void *edit_baton, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)edit_baton, *ret;
	ret = PyObject_CallMethod(self, "close", "");
	Py_DECREF(self);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_cb_editor_abort_edit(void *edit_baton, apr_pool_t *pool)
{
	PyObject *self = (PyObject *)edit_baton, *ret;
	ret = PyObject_CallMethod(self, "abort", "");
	Py_DECREF(self);
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static const svn_delta_editor_t py_editor = {
	py_cb_editor_set_target_revision,
	py_cb_editor_open_root,
	py_cb_editor_delete_entry,
	py_cb_editor_add_directory,
	py_cb_editor_open_directory,
	py_cb_editor_change_prop,
	py_cb_editor_close_directory,
	py_cb_editor_absent_directory,
	py_cb_editor_add_file,
	py_cb_editor_open_file,
	py_cb_editor_apply_textdelta,
	py_cb_editor_change_prop,
	py_cb_editor_close_file,
	py_cb_editor_absent_file,
	py_cb_editor_close_edit,
	py_cb_editor_abort_edit
};

static svn_error_t *py_file_rev_handler(void *baton, const char *path, svn_revnum_t rev, apr_hash_t *rev_props, svn_txdelta_window_handler_t *delta_handler, void **delta_baton, apr_array_header_t *prop_diffs, apr_pool_t *pool)
{
	PyObject *fn = (PyObject *)baton, *ret, *py_rev_props;

	py_rev_props = prop_hash_to_dict(rev_props);
	if (py_rev_props == NULL)
		return py_svn_error();

	ret = PyObject_CallFunction(fn, "slO", path, rev, py_rev_props);
	Py_DECREF(py_rev_props);
	if (ret == NULL)
		return py_svn_error();

	*delta_baton = (void *)ret;
	*delta_handler = py_txdelta_window_handler;
	return NULL;
}


static void ra_done_handler(void *_ra)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)_ra;

	ra->busy = false;

	Py_XDECREF(ra);
}

#define RUN_RA_WITH_POOL(pool, ra, cmd)  \
	if (!check_error((cmd))) { \
		apr_pool_destroy(pool); \
		ra->busy = false; \
		return NULL; \
	} \
	ra->busy = false;

static bool ra_check_busy(RemoteAccessObject *raobj)
{
	if (raobj->busy) {
		PyErr_SetString(busy_exc, "Remote access object already in use");
		return true;
	}
	raobj->busy = true;
	return false;
}

#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
static svn_error_t *py_get_client_string(void *baton, const char **name, apr_pool_t *pool)
{
	RemoteAccessObject *self = (RemoteAccessObject *)baton;
	PyObject *ret;

	if (self->client_string_func == Py_None) {
		*name = NULL;
		return NULL;
	}

	ret = PyObject_CallFunction(self->client_string_func, "");

	if (ret == NULL)
		return py_svn_error();

	*name = apr_pstrdup(pool, PyString_AsString(ret));
	Py_DECREF(ret);

	return NULL;
}
#endif

/* Based on svn_swig_py_make_file() from Subversion */
static svn_error_t *py_open_tmp_file(apr_file_t **fp, void *callback,
									 apr_pool_t *pool)
{
	RemoteAccessObject *self = (RemoteAccessObject *)callback;
	PyObject *ret;
	apr_status_t status;

	if (self->open_tmp_file_func == Py_None) {
		const char *path;

		SVN_ERR (svn_io_temp_dir (&path, pool));
		path = svn_path_join (path, "tempfile", pool);
		SVN_ERR (svn_io_open_unique_file (fp, NULL, path, ".tmp", TRUE, pool));

		return NULL;
	}

	ret = PyObject_CallFunction(self->open_tmp_file_func, "");

	if (ret == NULL) 
		return py_svn_error();
	
	if (PyString_Check(ret)) {
		char* fname = PyString_AsString(ret);
		status = apr_file_open(fp, fname, APR_CREATE | APR_READ | APR_WRITE, APR_OS_DEFAULT, 
								pool);
		if (status) {
			PyErr_SetAprStatus(status);
			Py_DECREF(ret);
			return NULL;
		}
		Py_DECREF(ret);
	} else if (PyFile_Check(ret)) {
		FILE *file;
		apr_os_file_t osfile;

		file = PyFile_AsFile(ret);
#ifdef WIN32
		osfile = (apr_os_file_t)_get_osfhandle(_fileno(file));
#else
		osfile = (apr_os_file_t)fileno(file);
#endif
		status = apr_os_file_put(fp, &osfile, O_CREAT | O_WRONLY, pool);
		if (status) {
			PyErr_SetAprStatus(status);
			Py_DECREF(ret);
			return NULL;
		}
	} else {
		PyErr_SetString(PyExc_TypeError, "Unknown type for file variable");
		Py_DECREF(ret);
		return NULL;
	}	

	return NULL;
}

static void py_progress_func(apr_off_t progress, apr_off_t total, void *baton, apr_pool_t *pool)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)baton;
	PyObject *fn = (PyObject *)ra->progress_func, *ret;
	if (fn == Py_None) {
		return;
	}
	ret = PyObject_CallFunction(fn, "LL", progress, total);
	/* TODO: What to do with exceptions raised here ? */
	Py_XDECREF(ret);
}

static PyObject *ra_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
	char *kwnames[] = { "url", "progress_cb", "auth", "config", "client_string_func", 
						"open_tmp_file_func", NULL };
	char *url;
	PyObject *progress_cb = Py_None;
	AuthObject *auth = (AuthObject *)Py_None;
	PyObject *config = Py_None;
	PyObject *client_string_func = Py_None, *open_tmp_file_func = Py_None;
	RemoteAccessObject *ret;
	apr_hash_t *config_hash;
	svn_ra_callbacks2_t *callbacks2;
	svn_auth_baton_t *auth_baton;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|OOOOO", kwnames, &url, &progress_cb, 
									 (PyObject **)&auth, &config, &client_string_func,
									 &open_tmp_file_func))
		return NULL;

	ret = PyObject_New(RemoteAccessObject, &RemoteAccess_Type);
	if (ret == NULL)
		return NULL;

	if ((PyObject *)auth == Py_None) {
		auth_baton = NULL;
		ret->auth = NULL;
	} else {
		/* FIXME: check auth is an instance of Auth_Type */
		Py_INCREF(auth);
		ret->auth = auth;
		auth_baton = ret->auth->auth_baton;
	}

	ret->root = NULL;
	ret->pool = Pool(NULL);
	if (ret->pool == NULL)
		return NULL;
	ret->url = apr_pstrdup(ret->pool, url);
	if (!check_error(svn_ra_create_callbacks(&callbacks2, ret->pool))) {
		apr_pool_destroy(ret->pool);
		PyObject_Del(ret);
		return NULL;
	}

	ret->client_string_func = client_string_func;
	ret->open_tmp_file_func = open_tmp_file_func;
	Py_INCREF(client_string_func);
	callbacks2->progress_func = py_progress_func;
	callbacks2->auth_baton = auth_baton;
	callbacks2->open_tmp_file = py_open_tmp_file;
	ret->progress_func = progress_cb;
	callbacks2->progress_baton = (void *)ret;
#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
	callbacks2->get_client_string = py_get_client_string;
#endif
	Py_INCREF(config);
	config_hash = config_hash_from_object(config, ret->pool);
	if (config_hash == NULL) {
		apr_pool_destroy(ret->pool);
		PyObject_Del(ret);
		return NULL;
	}
	if (!check_error(svn_ra_open2(&ret->ra, apr_pstrdup(ret->pool, url), 
								  callbacks2, ret, config_hash, ret->pool))) {
		apr_pool_destroy(ret->pool);
		PyObject_Del(ret);
		return NULL;
	}
	ret->busy = false;
	return (PyObject *)ret;
}

 /**
  * Obtain the globally unique identifier for this repository.
  */
static PyObject *ra_get_uuid(PyObject *self)
{
	const char *uuid;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	PyObject *ret;
	apr_pool_t *temp_pool;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_uuid(ra->ra, &uuid, temp_pool));
	ret = PyString_FromString(uuid);
	apr_pool_destroy(temp_pool);
	return ret;
}

/** Switch to a different url. */
static PyObject *ra_reparent(PyObject *self, PyObject *args)
{
	char *url;
	apr_pool_t *temp_pool;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;

	if (!PyArg_ParseTuple(args, "s", &url))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	ra->url = svn_path_canonicalize(url, ra->pool);
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_reparent(ra->ra, ra->url, temp_pool));
	apr_pool_destroy(temp_pool);
	Py_RETURN_NONE;
}

/**
 * Obtain the number of the latest committed revision in the 
 * connected repository.
 */
static PyObject *ra_get_latest_revnum(PyObject *self)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	svn_revnum_t latest_revnum;
	apr_pool_t *temp_pool;
	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra,
				  svn_ra_get_latest_revnum(ra->ra, &latest_revnum, temp_pool));
	apr_pool_destroy(temp_pool);
	return PyInt_FromLong(latest_revnum);
}

static PyObject *ra_get_log(PyObject *self, PyObject *args, PyObject *kwargs)
{
	char *kwnames[] = { "callback", "paths", "start", "end", "limit",
		"discover_changed_paths", "strict_node_history", "include_merged_revisions", "revprops", NULL };
	PyObject *callback, *paths;
	svn_revnum_t start = 0, end = 0;
	int limit=0; 
	bool discover_changed_paths=false, strict_node_history=true,include_merged_revisions=false;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	PyObject *revprops = Py_None;
	apr_pool_t *temp_pool;
	apr_array_header_t *apr_paths;
	apr_array_header_t *apr_revprops;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OOll|ibbbO:get_log", kwnames, 
						 &callback, &paths, &start, &end, &limit,
						 &discover_changed_paths, &strict_node_history,
						 &include_merged_revisions, &revprops))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	if (paths == Py_None) {
		/* FIXME: The subversion libraries don't behave as expected, 
		 * so tweak our own parameters a bit. */
		apr_paths = apr_array_make(temp_pool, 1, sizeof(char *));
		APR_ARRAY_PUSH(apr_paths, char *) = apr_pstrdup(temp_pool, "");
		apr_paths = NULL;
	} else if (!string_list_to_apr_array(temp_pool, paths, &apr_paths)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}

#if SVN_VER_MAJOR <= 1 && SVN_VER_MINOR < 5
	if (revprops == Py_None) {
		PyErr_SetString(PyExc_NotImplementedError, "fetching all revision properties not supported");	
		apr_pool_destroy(temp_pool);
		return NULL;
	} else if (!PyList_Check(revprops)) {
		PyErr_SetString(PyExc_TypeError, "revprops should be a list");
		apr_pool_destroy(temp_pool);
		return NULL;
	} else {
		int i;
		for (i = 0; i < PyList_Size(revprops); i++) {
			const char *n = PyString_AsString(PyList_GetItem(revprops, i));
			if (strcmp(SVN_PROP_REVISION_LOG, n) && 
				strcmp(SVN_PROP_REVISION_AUTHOR, n) &&
				strcmp(SVN_PROP_REVISION_DATE, n)) {
				PyErr_SetString(PyExc_NotImplementedError, 
								"fetching custom revision properties not supported");	
				apr_pool_destroy(temp_pool);
				return NULL;
			}
		}
	}

	if (include_merged_revisions) {
		PyErr_SetString(PyExc_NotImplementedError, "include_merged_revisions not supported in Subversion 1.4");
		apr_pool_destroy(temp_pool);
		return NULL;
	}
#endif

	if (!string_list_to_apr_array(temp_pool, revprops, &apr_revprops)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}

#if SVN_VER_MAJOR == 1 && SVN_VER_MINOR >= 5
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_log2(ra->ra, 
			apr_paths, start, end, limit,
			discover_changed_paths, strict_node_history, 
			include_merged_revisions,
			apr_revprops,
			py_svn_log_entry_receiver, 
			callback, temp_pool));
#else
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_log(ra->ra, 
			apr_paths, start, end, limit,
			discover_changed_paths, strict_node_history, py_svn_log_wrapper, 
			callback, temp_pool));
#endif
	apr_pool_destroy(temp_pool);
	Py_RETURN_NONE;
}

/**
 * Obtain the URL of the root of this repository.
 */
static PyObject *ra_get_repos_root(PyObject *self)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	const char *root;
	apr_pool_t *temp_pool;

	if (ra->root == NULL) {
		if (ra_check_busy(ra))
			return NULL;

		temp_pool = Pool(NULL);
		if (temp_pool == NULL)
			return NULL;
		RUN_RA_WITH_POOL(temp_pool, ra,
						  svn_ra_get_repos_root(ra->ra, &root, temp_pool));
		ra->root = apr_pstrdup(ra->pool, root);
		apr_pool_destroy(temp_pool);
	}

	return PyString_FromString(ra->root);
}

static PyObject *ra_do_update(PyObject *self, PyObject *args)
{
	svn_revnum_t revision_to_update_to;
	char *update_target; 
	bool recurse;
	PyObject *update_editor;
	const svn_ra_reporter2_t *reporter;
	void *report_baton;
	apr_pool_t *temp_pool;
	ReporterObject *ret;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;

	if (!PyArg_ParseTuple(args, "lsbO:do_update", &revision_to_update_to, &update_target, &recurse, &update_editor))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	Py_INCREF(update_editor);
	if (!check_error(svn_ra_do_update(ra->ra, &reporter, 
												  &report_baton, 
												  revision_to_update_to, 
												  update_target, recurse, 
												  &py_editor, update_editor, 
												  temp_pool))) {
		apr_pool_destroy(temp_pool);
		ra->busy = false;
		return NULL;
	}
	ret = PyObject_New(ReporterObject, &Reporter_Type);
	if (ret == NULL)
		return NULL;
	ret->reporter = reporter;
	ret->report_baton = report_baton;
	ret->pool = temp_pool;
	Py_INCREF(ra);
	ret->ra = ra;
	return (PyObject *)ret;
}

static PyObject *ra_do_switch(PyObject *self, PyObject *args)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	svn_revnum_t revision_to_update_to;
	char *update_target; 
	bool recurse;
	char *switch_url; 
	PyObject *update_editor;
	const svn_ra_reporter2_t *reporter;
	void *report_baton;
	apr_pool_t *temp_pool;
	ReporterObject *ret;

	if (!PyArg_ParseTuple(args, "lsbsO:do_switch", &revision_to_update_to, &update_target, 
						  &recurse, &switch_url, &update_editor))
		return NULL;
	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	Py_INCREF(update_editor);
	if (!check_error(svn_ra_do_switch(
						ra->ra, &reporter, &report_baton, 
						revision_to_update_to, update_target, 
						recurse, switch_url, &py_editor, 
						update_editor, temp_pool))) {
		apr_pool_destroy(temp_pool);
		ra->busy = false;
		return NULL;
	}
	ret = PyObject_New(ReporterObject, &Reporter_Type);
	if (ret == NULL)
		return NULL;
	ret->reporter = reporter;
	ret->report_baton = report_baton;
	ret->pool = temp_pool;
	Py_INCREF(ra);
	ret->ra = ra;
	return (PyObject *)ret;
}

static PyObject *ra_replay(PyObject *self, PyObject *args)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	apr_pool_t *temp_pool;
	svn_revnum_t revision, low_water_mark;
	PyObject *update_editor;
	bool send_deltas = true;

	if (!PyArg_ParseTuple(args, "llO|b", &revision, &low_water_mark, &update_editor, &send_deltas))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	Py_INCREF(update_editor);
	RUN_RA_WITH_POOL(temp_pool, ra,
					  svn_ra_replay(ra->ra, revision, low_water_mark,
									send_deltas, &py_editor, update_editor, 
									temp_pool));
	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
}

static svn_error_t *py_revstart_cb(svn_revnum_t revision, void *replay_baton,
   const svn_delta_editor_t **editor, void **edit_baton, apr_hash_t *rev_props, apr_pool_t *pool)
{
	PyObject *cbs = (PyObject *)replay_baton;
	PyObject *py_start_fn = PyTuple_GetItem(cbs, 0);
	PyObject *py_revprops = prop_hash_to_dict(rev_props);
	PyObject *ret;

	ret = PyObject_CallFunction(py_start_fn, "lO", revision, py_revprops);
	if (ret == NULL) 
		return py_svn_error();

	*editor = &py_editor;
	*edit_baton = ret;

	return NULL;
}

static svn_error_t *py_revfinish_cb(svn_revnum_t revision, void *replay_baton, 
									const svn_delta_editor_t *editor, void *edit_baton, 
									apr_hash_t *rev_props, apr_pool_t *pool)
{
	PyObject *cbs = (PyObject *)replay_baton;
	PyObject *py_finish_fn = PyTuple_GetItem(cbs, 1);
	PyObject *py_revprops = prop_hash_to_dict(rev_props);
	PyObject *ret;

	ret = PyObject_CallFunction(py_finish_fn, "lOO", revision, py_revprops, edit_baton);
	if (ret == NULL) 
		return py_svn_error();

	Py_DECREF((PyObject *)edit_baton);
	Py_DECREF(ret);

	return NULL;
}

static PyObject *ra_replay_range(PyObject *self, PyObject *args)
{
#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	apr_pool_t *temp_pool;
	svn_revnum_t start_revision, end_revision, low_water_mark;
	PyObject *cbs;
	bool send_deltas = true;

	if (!PyArg_ParseTuple(args, "lllO|b", &start_revision, &end_revision, &low_water_mark, &cbs, &send_deltas))
		return NULL;

	if (!PyTuple_Check(cbs)) {
		PyErr_SetString(PyExc_TypeError, "Expected tuple with callbacks");
		return NULL;
	}

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	Py_INCREF(cbs);
	RUN_RA_WITH_POOL(temp_pool, ra,
					  svn_ra_replay_range(ra->ra, start_revision, end_revision, low_water_mark,
									send_deltas, py_revstart_cb, py_revfinish_cb, cbs, 
									temp_pool));
	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
#else
	PyErr_SetString(PyExc_NotImplementedError, "svn_ra_replay not available with Subversion 1.4");
	return NULL;
#endif
}



static PyObject *ra_rev_proplist(PyObject *self, PyObject *args)
{
	apr_pool_t *temp_pool;
	apr_hash_t *props;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	svn_revnum_t rev;
	PyObject *py_props;
	if (!PyArg_ParseTuple(args, "l", &rev))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra,
					  svn_ra_rev_proplist(ra->ra, rev, &props, temp_pool));
	py_props = prop_hash_to_dict(props);
	apr_pool_destroy(temp_pool);
	return py_props;
}

static PyObject *get_commit_editor(PyObject *self, PyObject *args, PyObject *kwargs)
{
	char *kwnames[] = { "revprops", "callback", "lock_tokens", "keep_locks", 
		NULL };
	PyObject *revprops, *commit_callback = Py_None, *lock_tokens = Py_None;
	bool keep_locks = false;
	apr_pool_t *pool;
	const svn_delta_editor_t *editor;
	void *edit_baton;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	apr_hash_t *hash_lock_tokens;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|OOb", kwnames, &revprops, &commit_callback, &lock_tokens, &keep_locks))
		return NULL;

	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;
	if (lock_tokens == Py_None) {
		hash_lock_tokens = NULL;
	} else {
		Py_ssize_t idx = 0;
		PyObject *k, *v;
		hash_lock_tokens = apr_hash_make(pool);
		while (PyDict_Next(lock_tokens, &idx, &k, &v)) {
			apr_hash_set(hash_lock_tokens, PyString_AsString(k), 
						 PyString_Size(k), PyString_AsString(v));
		}
	}

	if (!PyDict_Check(revprops)) {
		apr_pool_destroy(pool);
		PyErr_SetString(PyExc_TypeError, "Expected dictionary with revision properties");
		return NULL;
	}

	if (ra_check_busy(ra))
		return NULL;

	if (!check_error(svn_ra_get_commit_editor2(ra->ra, &editor, 
		&edit_baton, 
		PyString_AsString(PyDict_GetItemString(revprops, SVN_PROP_REVISION_LOG)), py_commit_callback, 
		commit_callback, hash_lock_tokens, keep_locks, pool))) {
		apr_pool_destroy(pool);
		ra->busy = false;
		return NULL;
	}

	Py_INCREF(ra);
	return new_editor_object(editor, edit_baton, pool, 
								  &Editor_Type, ra_done_handler, ra);
}

static PyObject *ra_change_rev_prop(PyObject *self, PyObject *args)
{
	svn_revnum_t rev;
	char *name;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	char *value;
	int vallen;
	apr_pool_t *temp_pool;
 	svn_string_t *val_string;

	if (!PyArg_ParseTuple(args, "lss#", &rev, &name, &value, &vallen))
		return NULL;
	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	val_string = svn_string_ncreate(value, vallen, temp_pool);
	RUN_RA_WITH_POOL(temp_pool, ra,
					  svn_ra_change_rev_prop(ra->ra, rev, name, val_string, 
											 temp_pool));
	apr_pool_destroy(temp_pool);
	Py_RETURN_NONE;
}
	
static PyObject *ra_get_dir(PyObject *self, PyObject *args)
{
   	apr_pool_t *temp_pool;
	apr_hash_t *dirents;
	apr_hash_index_t *idx;
	apr_hash_t *props;
	svn_revnum_t fetch_rev;
	const char *key;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	svn_dirent_t *dirent;
	apr_ssize_t klen;
	char *path;
	svn_revnum_t revision = -1;
	int dirent_fields = 0;
	PyObject *py_dirents, *py_props;

	if (!PyArg_ParseTuple(args, "s|li", &path, &revision, &dirent_fields))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	if (revision != SVN_INVALID_REVNUM)
		fetch_rev = revision;

	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_dir2(ra->ra, &dirents, &fetch_rev, &props,
					 path, revision, dirent_fields, temp_pool));

	if (dirents == NULL) {
		py_dirents = Py_None;
	} else {
		py_dirents = PyDict_New();
		idx = apr_hash_first(temp_pool, dirents);
		while (idx != NULL) {
			PyObject *py_dirent;
			apr_hash_this(idx, (const void **)&key, &klen, (void **)&dirent);
			py_dirent = PyDict_New();
			if (dirent_fields & 0x1)
				PyDict_SetItemString(py_dirent, "kind", 
									 PyInt_FromLong(dirent->kind));
			if (dirent_fields & 0x2)
				PyDict_SetItemString(py_dirent, "size", 
									 PyLong_FromLong(dirent->size));
			if (dirent_fields & 0x4)
				PyDict_SetItemString(py_dirent, "has_props",
									 PyBool_FromLong(dirent->has_props));
			if (dirent_fields & 0x8)
				PyDict_SetItemString(py_dirent, "created_rev", 
									 PyLong_FromLong(dirent->created_rev));
			if (dirent_fields & 0x10)
				PyDict_SetItemString(py_dirent, "time", 
									 PyLong_FromLong(dirent->time));
			if (dirent_fields & 0x20)
				PyDict_SetItemString(py_dirent, "last_author",
									 PyString_FromString(dirent->last_author));
			PyDict_SetItemString(py_dirents, key, py_dirent);
			idx = apr_hash_next(idx);
		}
	}

	py_props = prop_hash_to_dict(props);
	if (py_props == NULL) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}
	apr_pool_destroy(temp_pool);
	return Py_BuildValue("(NlN)", py_dirents, fetch_rev, py_props);
}

static PyObject *ra_get_file(PyObject *self, PyObject *args)
{
	char *path;
	svn_revnum_t revision = -1;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	apr_hash_t *props;
	svn_revnum_t fetch_rev;
	PyObject *py_stream, *py_props;
	apr_pool_t *temp_pool;

	if (!PyArg_ParseTuple(args, "sO|l", &path, &py_stream, &revision))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	if (revision != SVN_INVALID_REVNUM)
		fetch_rev = revision;

	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_file(ra->ra, path, revision, 
													new_py_stream(temp_pool, py_stream), 
													&fetch_rev, &props, temp_pool));

	py_props = prop_hash_to_dict(props);
	if (py_props == NULL) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}

	apr_pool_destroy(temp_pool);
		 
	return Py_BuildValue("(lN)", fetch_rev, py_props);
}

static PyObject *ra_get_lock(PyObject *self, PyObject *args)
{
	char *path;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	svn_lock_t *lock;
	apr_pool_t *temp_pool;

	if (!PyArg_ParseTuple(args, "s", &path))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra,
				  svn_ra_get_lock(ra->ra, &lock, path, temp_pool));
	apr_pool_destroy(temp_pool);
	return wrap_lock(lock);
}

static PyObject *ra_check_path(PyObject *self, PyObject *args)
{
	char *path; 
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	svn_revnum_t revision;
	svn_node_kind_t kind;
	apr_pool_t *temp_pool;

	if (!PyArg_ParseTuple(args, "sl", &path, &revision))
		return NULL;
	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra,
					  svn_ra_check_path(ra->ra, path, revision, &kind, 
					 temp_pool));
	apr_pool_destroy(temp_pool);
	return PyInt_FromLong(kind);
}

static PyObject *ra_has_capability(PyObject *self, PyObject *args)
{
#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
	char *capability;
	apr_pool_t *temp_pool;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	int has = 0;

	if (!PyArg_ParseTuple(args, "s", &capability))
		return NULL;
	
	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra,
					  svn_ra_has_capability(ra->ra, &has, capability, temp_pool));
	apr_pool_destroy(temp_pool);
	return PyBool_FromLong(has);
#else
	PyErr_SetString(PyExc_NotImplementedError, "has_capability is only supported in Subversion >= 1.5");
	return NULL;
#endif
}

static PyObject *ra_unlock(PyObject *self, PyObject *args)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	PyObject *path_tokens, *lock_func, *k, *v;
	bool break_lock;
	apr_ssize_t idx;
	apr_pool_t *temp_pool;
	apr_hash_t *hash_path_tokens;

	if (!PyArg_ParseTuple(args, "ObO", &path_tokens, &break_lock, &lock_func))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	hash_path_tokens = apr_hash_make(temp_pool);
	while (PyDict_Next(path_tokens, &idx, &k, &v)) {
		apr_hash_set(hash_path_tokens, PyString_AsString(k), PyString_Size(k), (char *)PyString_AsString(v));
	}
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_unlock(ra->ra, hash_path_tokens, break_lock,
					 py_lock_func, lock_func, temp_pool));

	apr_pool_destroy(temp_pool);
	Py_RETURN_NONE;
}

static PyObject *ra_lock(PyObject *self, PyObject *args)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	PyObject *path_revs;
	char *comment;
	int steal_lock;
	PyObject *lock_func, *k, *v;
 	apr_pool_t *temp_pool;
	apr_hash_t *hash_path_revs;
	svn_revnum_t *rev;
	Py_ssize_t idx = 0;

	if (!PyArg_ParseTuple(args, "OsbO", &path_revs, &comment, &steal_lock, 
						  &lock_func))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	if (path_revs == Py_None) {
		hash_path_revs = NULL;
	} else {
		hash_path_revs = apr_hash_make(temp_pool);
	}

	while (PyDict_Next(path_revs, &idx, &k, &v)) {
		rev = (svn_revnum_t *)apr_palloc(temp_pool, sizeof(svn_revnum_t));
		*rev = PyLong_AsLong(v);
		apr_hash_set(hash_path_revs, PyString_AsString(k), PyString_Size(k), 
					 rev);
	}
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_lock(ra->ra, hash_path_revs, comment, steal_lock,
					 py_lock_func, lock_func, temp_pool));
	apr_pool_destroy(temp_pool);
	Py_RETURN_NONE;
}

static PyObject *ra_get_locks(PyObject *self, PyObject *args)
{
	char *path;
	apr_pool_t *temp_pool;
	apr_hash_t *hash_locks;
	apr_hash_index_t *idx;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	char *key;
	apr_ssize_t klen;
	svn_lock_t *lock;
	PyObject *ret;

	if (!PyArg_ParseTuple(args, "s", &path))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_locks(ra->ra, &hash_locks, path, temp_pool));

	ret = PyDict_New();
	for (idx = apr_hash_first(temp_pool, hash_locks); idx != NULL;
		 idx = apr_hash_next(idx)) {
		PyObject *pyval;
		apr_hash_this(idx, (const void **)&key, &klen, (void **)&lock);
		pyval = pyify_lock(lock);
		if (pyval == NULL) {
			apr_pool_destroy(temp_pool);
			return NULL;
		}
		PyDict_SetItemString(ret, key, pyval);
	}

	apr_pool_destroy(temp_pool);
	return ret;
}

static PyObject *ra_get_locations(PyObject *self, PyObject *args)
{
	char *path;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	svn_revnum_t peg_revision;
	PyObject *location_revisions;
	apr_pool_t *temp_pool;
	apr_hash_t *hash_locations;
	apr_hash_index_t *idx;
	svn_revnum_t *key;
	PyObject *ret;
	apr_ssize_t klen;
	char *val;

	if (!PyArg_ParseTuple(args, "slO", &path, &peg_revision, &location_revisions))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_locations(ra->ra, &hash_locations,
					path, peg_revision, 
					revnum_list_to_apr_array(temp_pool, location_revisions),
					temp_pool));
	ret = PyDict_New();

	for (idx = apr_hash_first(temp_pool, hash_locations); idx != NULL; 
		idx = apr_hash_next(idx)) {
		apr_hash_this(idx, (const void **)&key, &klen, (void **)&val);
		PyDict_SetItem(ret, PyInt_FromLong(*key), PyString_FromString(val));
	}
	apr_pool_destroy(temp_pool);
	return ret;
}

#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
static PyObject *range_to_tuple(svn_merge_range_t *range)
{
	return Py_BuildValue("(llb)", range->start, range->end, range->inheritable);
}

static PyObject *merge_rangelist_to_list(apr_array_header_t *rangelist)
{
	PyObject *ret;
	int i;

	ret = PyList_New(rangelist->nelts);

	for (i = 0; i < rangelist->nelts; i++) {
		PyObject *pyval = range_to_tuple(APR_ARRAY_IDX(rangelist, i, svn_merge_range_t *));
		if (pyval == NULL)
			return NULL;
		PyList_SetItem(ret, i, pyval);
	}
	return ret;
}

static PyObject *mergeinfo_to_dict(svn_mergeinfo_t mergeinfo, apr_pool_t *temp_pool)
{
	PyObject *ret = PyDict_New();
	char *key;
	apr_ssize_t klen;
	apr_hash_index_t *idx;
	apr_array_header_t *range;

	for (idx = apr_hash_first(temp_pool, mergeinfo); idx != NULL; 
		idx = apr_hash_next(idx)) {
		PyObject *pyval;
		apr_hash_this(idx, (const void **)&key, &klen, (void **)&range);
		pyval = merge_rangelist_to_list(range);
		if (pyval == NULL)
			return NULL;
		PyDict_SetItemString(ret, key, pyval);
	}

	return ret;
}
#endif

static PyObject *ra_mergeinfo(PyObject *self, PyObject *args)
{
#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	apr_array_header_t *apr_paths;
	apr_pool_t *temp_pool;
	svn_mergeinfo_catalog_t catalog;
	apr_ssize_t klen;
	apr_hash_index_t *idx;
	svn_mergeinfo_t val;
	char *key;
	PyObject *ret;
	svn_revnum_t revision = -1;
	PyObject *paths;
	svn_mergeinfo_inheritance_t inherit = svn_mergeinfo_explicit;
	svn_boolean_t include_descendants;

	if (!PyArg_ParseTuple(args, "O|lib", &paths, &revision, &inherit, &include_descendants))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	if (!string_list_to_apr_array(temp_pool, paths, &apr_paths)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}

	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_mergeinfo(ra->ra, 
                     &catalog, apr_paths, revision, inherit, 
					 include_descendants,
                     temp_pool));

	ret = PyDict_New();

	if (catalog != NULL) {
		for (idx = apr_hash_first(temp_pool, catalog); idx != NULL; 
			idx = apr_hash_next(idx)) {
			PyObject *pyval;
			apr_hash_this(idx, (const void **)&key, &klen, (void **)&val);
			pyval = mergeinfo_to_dict(val, temp_pool);
			if (pyval == NULL) {
				apr_pool_destroy(temp_pool);
				return NULL;
			}
			PyDict_SetItemString(ret, key, pyval);
		}
	}

	apr_pool_destroy(temp_pool);

	return ret;
#else
	PyErr_SetString(PyExc_NotImplementedError, "mergeinfo is only supported in Subversion >= 1.5");
	return NULL;
#endif
}

#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
static svn_error_t *py_location_segment_receiver(svn_location_segment_t *segment, void *baton, apr_pool_t *pool)
{
	PyObject *fn = baton, *ret;

	ret = PyObject_CallFunction(fn, "llz", segment->range_start, segment->range_end, segment->path);
	if (ret == NULL)
		return py_svn_error();
	Py_XDECREF(ret);
	return NULL;
}
#endif

static PyObject *ra_get_location_segments(PyObject *self, PyObject *args)
{
#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	svn_revnum_t peg_revision, start_revision, end_revision;
	char *path;
	PyObject *py_rcvr;
	apr_pool_t *temp_pool;

	if (!PyArg_ParseTuple(args, "slllO", &path, &peg_revision, &start_revision, 
						  &end_revision, &py_rcvr))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_location_segments(ra->ra, 
					 path, peg_revision, start_revision, end_revision,
					 py_location_segment_receiver, 
					 py_rcvr, temp_pool));

	apr_pool_destroy(temp_pool);
	Py_RETURN_NONE;
#else
	PyErr_SetString(PyExc_NotImplementedError, "mergeinfo is only supported in Subversion >= 1.5");
	return NULL;
#endif
}

	
static PyObject *ra_get_file_revs(PyObject *self, PyObject *args)
{
	char *path;
	svn_revnum_t start, end;
	PyObject *file_rev_handler;
	apr_pool_t *temp_pool;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;

	if (!PyArg_ParseTuple(args, "sllO", &path, &start, &end, &file_rev_handler))
		return NULL;

	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;

	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_file_revs(ra->ra, path, start, end, 
				py_file_rev_handler, (void *)file_rev_handler, 
					temp_pool));

	apr_pool_destroy(temp_pool);

	Py_RETURN_NONE;
}

static void ra_dealloc(PyObject *self)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	Py_XDECREF(ra->progress_func);
	apr_pool_destroy(ra->pool);
	Py_XDECREF(ra->auth);
	PyObject_Del(self);
}

static PyObject *ra_repr(PyObject *self)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	return PyString_FromFormat("RemoteAccess(%s)", ra->url);
}

static int ra_set_progress_func(PyObject *self, PyObject *value, void *closure)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	Py_XDECREF(ra->progress_func);
	ra->progress_func = value;
	Py_INCREF(ra->progress_func);
	return 0;
}

static PyGetSetDef ra_getsetters[] = { 
	{ "progress_func", NULL, ra_set_progress_func, NULL },
	{ NULL }
};

static PyMethodDef ra_methods[] = {
	{ "get_file_revs", ra_get_file_revs, METH_VARARGS, NULL },
	{ "get_locations", ra_get_locations, METH_VARARGS, NULL },
	{ "get_locks", ra_get_locks, METH_VARARGS, NULL },
	{ "lock", ra_lock, METH_VARARGS, NULL },
	{ "unlock", ra_unlock, METH_VARARGS, NULL },
	{ "mergeinfo", ra_mergeinfo, METH_VARARGS, NULL },
	{ "get_location_segments", ra_get_location_segments, METH_VARARGS, NULL },
	{ "has_capability", ra_has_capability, METH_VARARGS, NULL },
	{ "check_path", ra_check_path, METH_VARARGS, NULL },
	{ "get_lock", ra_get_lock, METH_VARARGS, NULL },
	{ "get_dir", ra_get_dir, METH_VARARGS, NULL },
	{ "get_file", ra_get_file, METH_VARARGS, NULL },
	{ "change_rev_prop", ra_change_rev_prop, METH_VARARGS, NULL },
	{ "get_commit_editor", (PyCFunction)get_commit_editor, METH_VARARGS|METH_KEYWORDS, NULL },
	{ "rev_proplist", ra_rev_proplist, METH_VARARGS, NULL },
	{ "replay", ra_replay, METH_VARARGS, NULL },
	{ "replay_range", ra_replay_range, METH_VARARGS, NULL },
	{ "do_switch", ra_do_switch, METH_VARARGS, NULL },
	{ "do_update", ra_do_update, METH_VARARGS, NULL },
	{ "get_repos_root", (PyCFunction)ra_get_repos_root, METH_VARARGS|METH_NOARGS, NULL },
	{ "get_log", (PyCFunction)ra_get_log, METH_VARARGS|METH_KEYWORDS, NULL },
	{ "get_latest_revnum", (PyCFunction)ra_get_latest_revnum, METH_NOARGS, NULL },
	{ "reparent", ra_reparent, METH_VARARGS, NULL },
	{ "get_uuid", (PyCFunction)ra_get_uuid, METH_NOARGS, NULL },
	{ NULL, }
};

static PyMemberDef ra_members[] = {
	{ "busy", T_BYTE, offsetof(RemoteAccessObject, busy), READONLY, NULL },
	{ "url", T_STRING, offsetof(RemoteAccessObject, url), READONLY, NULL },
	{ NULL, }
};

PyTypeObject RemoteAccess_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	"ra.RemoteAccess", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(RemoteAccessObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	ra_dealloc, /*	destructor tp_dealloc;	*/
	NULL, /*	printfunc tp_print;	*/
	NULL, /*	getattrfunc tp_getattr;	*/
	NULL, /*	setattrfunc tp_setattr;	*/
	NULL, /*	cmpfunc tp_compare;	*/
	ra_repr, /*	reprfunc tp_repr;	*/
	
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
	ra_methods, /*	struct PyMethodDef *tp_methods;	*/
	ra_members, /*	struct PyMemberDef *tp_members;	*/
	ra_getsetters, /*	struct PyGetSetDef *tp_getset;	*/
	NULL, /*	struct _typeobject *tp_base;	*/
	NULL, /*	PyObject *tp_dict;	*/
	NULL, /*	descrgetfunc tp_descr_get;	*/
	NULL, /*	descrsetfunc tp_descr_set;	*/
	0, /*	Py_ssize_t tp_dictoffset;	*/
	NULL, /*	initproc tp_init;	*/
	NULL, /*	allocfunc tp_alloc;	*/
	ra_new, /*	newfunc tp_new;	*/

};

typedef struct { 
	PyObject_HEAD
	apr_pool_t *pool;
	svn_auth_provider_object_t *provider;
} AuthProviderObject;

static void auth_provider_dealloc(PyObject *self)
{
	AuthProviderObject *auth_provider = (AuthProviderObject *)self;
	apr_pool_destroy(auth_provider->pool);
	PyObject_Del(self);
}

PyTypeObject AuthProvider_Type = { 
	PyObject_HEAD_INIT(NULL) 0,
	"ra.AuthProvider", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(AuthProviderObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	auth_provider_dealloc, /*	destructor tp_dealloc;	*/

};

static PyObject *auth_init(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
	char *kwnames[] = { "providers", NULL };
	apr_array_header_t *c_providers;
	svn_auth_provider_object_t **el;
	PyObject *providers = Py_None;
	AuthObject *ret;
	int i;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|O", kwnames, &providers))
		return NULL;

	ret = PyObject_New(AuthObject, &Auth_Type);
	if (ret == NULL)
		return NULL;

	if (!PyList_Check(providers)) {
		PyErr_SetString(PyExc_TypeError, "Auth providers should be list");
		return NULL;
	}

	ret->pool = Pool(NULL);
	if (ret->pool == NULL)
		return NULL;

	ret->providers = providers;
	Py_INCREF(providers);

	c_providers = apr_array_make(ret->pool, PyList_Size(providers), sizeof(svn_auth_provider_object_t *));
	if (c_providers == NULL) {
		PyErr_NoMemory();
		return NULL;
	}
	for (i = 0; i < PyList_Size(providers); i++) {
		AuthProviderObject *provider;
		el = (svn_auth_provider_object_t **)apr_array_push(c_providers);
		/* FIXME: Check that provider is indeed a AuthProviderObject object */
		provider = (AuthProviderObject *)PyList_GetItem(providers, i);
		*el = provider->provider;
	}
	svn_auth_open(&ret->auth_baton, c_providers, ret->pool);
	return (PyObject *)ret;
}

static PyObject *auth_set_parameter(PyObject *self, PyObject *args)
{
	AuthObject *auth = (AuthObject *)self;
	char *name;
	PyObject *value;
	void *vvalue;
	if (!PyArg_ParseTuple(args, "sO", &name, &value))
		return NULL;

	if (!strcmp(name, SVN_AUTH_PARAM_SSL_SERVER_FAILURES)) {
		vvalue = apr_pcalloc(auth->pool, sizeof(apr_uint32_t));
		*((apr_uint32_t *)vvalue) = PyInt_AsLong(value);
	} else if (!strcmp(name, SVN_AUTH_PARAM_DEFAULT_USERNAME) || 
			   !strcmp(name, SVN_AUTH_PARAM_DEFAULT_PASSWORD)) {
		vvalue = apr_pstrdup(auth->pool, PyString_AsString(value));
	} else {
		PyErr_Format(PyExc_TypeError, "Unsupported auth parameter %s", name);
		return NULL;
	}

	svn_auth_set_parameter(auth->auth_baton, name, (char *)vvalue);

	Py_RETURN_NONE;
}

static PyObject *auth_get_parameter(PyObject *self, PyObject *args)
{
	char *name;
	const void *value;
	AuthObject *auth = (AuthObject *)self;

	if (!PyArg_ParseTuple(args, "s", &name))
		return NULL;

	value = svn_auth_get_parameter(auth->auth_baton, name);

	if (!strcmp(name, SVN_AUTH_PARAM_SSL_SERVER_FAILURES)) {
		return PyInt_FromLong(*((apr_uint32_t *)value));
	} else if (!strcmp(name, SVN_AUTH_PARAM_DEFAULT_USERNAME) ||
			   !strcmp(name, SVN_AUTH_PARAM_DEFAULT_PASSWORD)) {
		return PyString_FromString((const char *)value);
	} else {
		PyErr_Format(PyExc_TypeError, "Unsupported auth parameter %s", name);
		return NULL;
	}
}

typedef struct { 
	PyObject_HEAD
	apr_pool_t *pool;
	char *cred_kind;
	svn_auth_iterstate_t *state;
	void *credentials;
} CredentialsIterObject;

static PyObject *auth_first_credentials(PyObject *self, PyObject *args)
{
	char *cred_kind;
	char *realmstring;
	AuthObject *auth = (AuthObject *)self;
	void *creds;
	apr_pool_t *pool;
	CredentialsIterObject *ret;
	svn_auth_iterstate_t *state;
	
	if (!PyArg_ParseTuple(args, "ss", &cred_kind, &realmstring))
		return NULL;

	pool = Pool(NULL);
	if (pool == NULL)
		return NULL;

	RUN_SVN_WITH_POOL(pool, 
					  svn_auth_first_credentials(&creds, &state, cred_kind, realmstring, auth->auth_baton, pool));

	ret = PyObject_New(CredentialsIterObject, &CredentialsIter_Type);
	if (ret == NULL)
		return NULL;

	ret->pool = pool;
	ret->cred_kind = apr_pstrdup(pool, cred_kind);
	ret->state = state;
	ret->credentials = creds;

	return (PyObject *)ret;
}

static void credentials_iter_dealloc(PyObject *self)
{
	CredentialsIterObject *credsiter = (CredentialsIterObject *)self;
	apr_pool_destroy(credsiter->pool);
	PyObject_Del(self);
}

static PyObject *credentials_iter_next(CredentialsIterObject *iterator)
{
	PyObject *ret;

	if (iterator->credentials == NULL) {
		PyErr_SetString(PyExc_StopIteration, "No more credentials available");
		return NULL;
	}

	if (!strcmp(iterator->cred_kind, SVN_AUTH_CRED_SIMPLE)) {
		svn_auth_cred_simple_t *simple = iterator->credentials;
		ret = Py_BuildValue("(zzb)", simple->username, simple->password, simple->may_save);
	} else if (!strcmp(iterator->cred_kind, SVN_AUTH_CRED_USERNAME)) {
		svn_auth_cred_username_t *uname = iterator->credentials;
		ret = Py_BuildValue("(zb)", uname->username, uname->may_save);
	} else if (!strcmp(iterator->cred_kind, SVN_AUTH_CRED_SSL_CLIENT_CERT)) {
		svn_auth_cred_ssl_client_cert_t *ccert = iterator->credentials;
		ret = Py_BuildValue("(zb)", ccert->cert_file, ccert->may_save);
	} else if (!strcmp(iterator->cred_kind, SVN_AUTH_CRED_SSL_CLIENT_CERT_PW)) {
		svn_auth_cred_ssl_client_cert_pw_t *ccert = iterator->credentials;
		ret = Py_BuildValue("(zb)", ccert->password, ccert->may_save);
	} else if (!strcmp(iterator->cred_kind, SVN_AUTH_CRED_SSL_SERVER_TRUST)) {
		svn_auth_cred_ssl_server_trust_t *ccert = iterator->credentials;
		ret = Py_BuildValue("(ib)", ccert->accepted_failures, ccert->may_save);
	} else {
		PyErr_Format(PyExc_RuntimeError, "Unknown cred kind %s", iterator->cred_kind);
		return NULL;
	}

	RUN_SVN_WITH_POOL(iterator->pool, 
					  svn_auth_next_credentials(&iterator->credentials, iterator->state, iterator->pool));

	return ret;
}

PyTypeObject CredentialsIter_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	"ra.CredentialsIter", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(CredentialsIterObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	(destructor)credentials_iter_dealloc, /*	destructor tp_dealloc;	*/
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
	(iternextfunc)credentials_iter_next, /*	iternextfunc tp_iternext;	*/

};

static PyMethodDef auth_methods[] = {
	{ "set_parameter", auth_set_parameter, METH_VARARGS, NULL },
	{ "get_parameter", auth_get_parameter, METH_VARARGS, NULL },
	{ "credentials", auth_first_credentials, METH_VARARGS, NULL },
	{ NULL, }
};

static void auth_dealloc(PyObject *self)
{
	AuthObject *auth = (AuthObject *)self;
	apr_pool_destroy(auth->pool);
	Py_DECREF(auth->providers);	
}

PyTypeObject Auth_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	"ra.Auth", /*	const char *tp_name;  For printing, in format "<module>.<name>" */
	sizeof(AuthObject), 
	0,/*	Py_ssize_t tp_basicsize, tp_itemsize;  For allocation */
	
	/* Methods to implement standard operations */
	
	auth_dealloc, /*	destructor tp_dealloc;	*/
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
	auth_methods, /*	struct PyMethodDef *tp_methods;	*/
	NULL, /*	struct PyMemberDef *tp_members;	*/
	NULL, /*	struct PyGetSetDef *tp_getset;	*/
	NULL, /*	struct _typeobject *tp_base;	*/
	NULL, /*	PyObject *tp_dict;	*/
	NULL, /*	descrgetfunc tp_descr_get;	*/
	NULL, /*	descrsetfunc tp_descr_set;	*/
	0, /*	Py_ssize_t tp_dictoffset;	*/
	NULL, /*	initproc tp_init;	*/
	NULL, /*	allocfunc tp_alloc;	*/
	auth_init, /*	newfunc tp_new;	*/

};

static svn_error_t *py_username_prompt(svn_auth_cred_username_t **cred, void *baton, const char *realm, int may_save, apr_pool_t *pool)
{
	PyObject *fn = (PyObject *)baton, *ret;
	PyObject *py_username, *py_may_save;
	ret = PyObject_CallFunction(fn, "sb", realm, may_save);
	if (ret == NULL)
		return py_svn_error();

	if (ret == Py_None)
		return NULL;

	if (!PyTuple_Check(ret)) {
		PyErr_SetString(PyExc_TypeError, "expected tuple with username credentials");
		return py_svn_error();
	}

	if (PyTuple_Size(ret) != 2) {
		PyErr_SetString(PyExc_TypeError, "expected tuple with username credentials to be size 2");
		return py_svn_error();
	}

	py_may_save = PyTuple_GetItem(ret, 1);
	if (!PyBool_Check(py_may_save)) {
		PyErr_SetString(PyExc_TypeError, "may_save should be boolean");
		return py_svn_error();
	}
	py_username = PyTuple_GetItem(ret, 0);
	if (!PyString_Check(py_username)) {
		PyErr_SetString(PyExc_TypeError, "username hsould be string");
		return py_svn_error();
	}

	*cred = apr_pcalloc(pool, sizeof(**cred));
	(*cred)->username = apr_pstrdup(pool, PyString_AsString(py_username));
	(*cred)->may_save = (py_may_save == Py_True);
	Py_DECREF(ret);
	return NULL;
}

static PyObject *get_username_prompt_provider(PyObject *self, PyObject *args)
{
	AuthProviderObject *auth;
	PyObject *prompt_func;
	int retry_limit;
	if (!PyArg_ParseTuple(args, "Oi", &prompt_func, &retry_limit))
		return NULL;
	auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	Py_INCREF(prompt_func);
	svn_auth_get_username_prompt_provider(&auth->provider, py_username_prompt, (void *)prompt_func, retry_limit, auth->pool);
	return (PyObject *)auth;
}

static svn_error_t *py_simple_prompt(svn_auth_cred_simple_t **cred, void *baton, const char *realm, const char *username, int may_save, apr_pool_t *pool)
{
	PyObject *fn = (PyObject *)baton, *ret;
	PyObject *py_may_save, *py_username, *py_password;
	ret = PyObject_CallFunction(fn, "ssb", realm, username, may_save);
	if (ret == NULL)
		return py_svn_error();
	if (!PyTuple_Check(ret)) {
		PyErr_SetString(PyExc_TypeError, "expected tuple with simple credentials");
		return py_svn_error();
	}
	if (PyTuple_Size(ret) != 3) {
		PyErr_SetString(PyExc_TypeError, "expected tuple of size 3");
		return py_svn_error();
	}

	py_may_save = PyTuple_GetItem(ret, 2);

	if (!PyBool_Check(py_may_save)) {
		PyErr_SetString(PyExc_TypeError, "may_save should be boolean");
		return py_svn_error();
	}
	
	py_username = PyTuple_GetItem(ret, 0);
	if (!PyString_Check(py_username)) {
		PyErr_SetString(PyExc_TypeError, "username should be string");
		return py_svn_error();
	}

	py_password = PyTuple_GetItem(ret, 1);
	if (!PyString_Check(py_password)) {
		PyErr_SetString(PyExc_TypeError, "password should be string");
		return py_svn_error();
	}

	*cred = apr_pcalloc(pool, sizeof(**cred));
	(*cred)->username = apr_pstrdup(pool, PyString_AsString(py_username));
	(*cred)->password = apr_pstrdup(pool, PyString_AsString(py_password));
	(*cred)->may_save = (py_may_save == Py_True);
	Py_DECREF(ret);
	return NULL;
}

static PyObject *get_simple_prompt_provider(PyObject *self, PyObject *args)
{
	PyObject *prompt_func;
	int retry_limit;
	AuthProviderObject *auth;

	if (!PyArg_ParseTuple(args, "Oi", &prompt_func, &retry_limit))
		return NULL;

	auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	Py_INCREF(prompt_func);
	svn_auth_get_simple_prompt_provider (&auth->provider, py_simple_prompt, (void *)prompt_func, retry_limit, auth->pool);
	return (PyObject *)auth;
}

static svn_error_t *py_ssl_server_trust_prompt(svn_auth_cred_ssl_server_trust_t **cred, void *baton, const char *realm, apr_uint32_t failures, const svn_auth_ssl_server_cert_info_t *cert_info, svn_boolean_t may_save, apr_pool_t *pool)
{
	PyObject *fn = (PyObject *)baton;
	PyObject *ret;
	PyObject *py_cert, *py_may_save, *py_accepted_failures;

	if (cert_info == NULL) {
		py_cert = Py_None;
	} else {
		py_cert = Py_BuildValue("(sssss)", cert_info->hostname, cert_info->fingerprint, 
						  cert_info->valid_from, cert_info->valid_until, 
						  cert_info->issuer_dname, cert_info->ascii_cert);
	}

	if (py_cert == NULL)
		return py_svn_error();

	ret = PyObject_CallFunction(fn, "slOb", realm, failures, py_cert, may_save);
	Py_DECREF(py_cert);
	if (ret == NULL)
		return py_svn_error();

	if (!PyTuple_Check(ret)) {
		PyErr_SetString(PyExc_TypeError, "expected tuple with server trust credentials");
		return py_svn_error();
	}
	if (PyTuple_Size(ret) != 2) {
		PyErr_SetString(PyExc_TypeError, "expected tuple of size 2");
		return py_svn_error();
	}

	py_accepted_failures = PyTuple_GetItem(ret, 0);
	if (!PyInt_Check(py_accepted_failures)) {
		PyErr_SetString(PyExc_TypeError, "accepted_failures should be integer");
		return py_svn_error();
	}

	py_may_save = PyTuple_GetItem(ret, 1);
	if (!PyBool_Check(py_may_save)) {
		PyErr_SetString(PyExc_TypeError, "may_save should be boolean");
		return py_svn_error();
	}
	
	*cred = apr_pcalloc(pool, sizeof(**cred));
	(*cred)->accepted_failures = PyInt_AsLong(py_accepted_failures);
	(*cred)->may_save = (py_may_save == Py_True);

	Py_DECREF(ret);
	return NULL;
}

static PyObject *get_ssl_server_trust_prompt_provider(PyObject *self, PyObject *args)
{
	AuthProviderObject *auth;
	PyObject *prompt_func;

	if (!PyArg_ParseTuple(args, "O", &prompt_func))
		return NULL;

	auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	if (auth == NULL)
		return NULL;
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	Py_INCREF(prompt_func);
	svn_auth_get_ssl_server_trust_prompt_provider (&auth->provider, py_ssl_server_trust_prompt, (void *)prompt_func, auth->pool);
	return (PyObject *)auth;
}

static svn_error_t *py_ssl_client_cert_pw_prompt(svn_auth_cred_ssl_client_cert_pw_t **cred, void *baton, const char *realm, svn_boolean_t may_save, apr_pool_t *pool)
{
	PyObject *fn = (PyObject *)baton, *ret, *py_may_save, *py_password;
	ret = PyObject_CallFunction(fn, "sb", realm, may_save);
	if (ret == NULL) 
		return py_svn_error();
	if (!PyTuple_Check(ret)) {
		PyErr_SetString(PyExc_TypeError, "expected tuple with client cert pw credentials");
		return py_svn_error();
	}

	if (PyTuple_Size(ret) != 2) {
		PyErr_SetString(PyExc_TypeError, "expected tuple of size 2");
		return py_svn_error();
	}
	py_may_save = PyTuple_GetItem(ret, 1);
	if (!PyBool_Check(py_may_save)) {
		PyErr_SetString(PyExc_TypeError, "may_save should be boolean");
		return py_svn_error();
	}
	py_password = PyTuple_GetItem(ret, 0);
	if (!PyString_Check(py_password)) {
		PyErr_SetString(PyExc_TypeError, "password should be string");
		return py_svn_error();
	}
	*cred = apr_pcalloc(pool, sizeof(**cred));
	(*cred)->password = apr_pstrdup(pool, PyString_AsString(py_password));
	(*cred)->may_save = (py_may_save == Py_True);
	Py_DECREF(ret);
	return NULL;
}

static svn_error_t *py_ssl_client_cert_prompt(svn_auth_cred_ssl_client_cert_t **cred, void *baton, const char *realm, svn_boolean_t may_save, apr_pool_t *pool)
{
	PyObject *fn = (PyObject *)baton, *ret, *py_may_save, *py_cert_file;
	ret = PyObject_CallFunction(fn, "sb", realm, may_save);
	if (ret == NULL) 
		return py_svn_error();

	if (!PyTuple_Check(ret)) {
		PyErr_SetString(PyExc_TypeError, "expected tuple with client cert credentials");
		return py_svn_error();
	}

	if (PyTuple_Size(ret) != 2) {
		PyErr_SetString(PyExc_TypeError, "expected tuple of size 2");
		return py_svn_error();
	}
	py_may_save = PyTuple_GetItem(ret, 1);
	if (!PyBool_Check(py_may_save)) {
		PyErr_SetString(PyExc_TypeError, "may_save should be boolean");
		return py_svn_error();
	}

	py_cert_file = PyTuple_GetItem(ret, 0);
	if (!PyString_Check(py_cert_file)) {
		PyErr_SetString(PyExc_TypeError, "cert_file should be string");
		return py_svn_error();
	}

	*cred = apr_pcalloc(pool, sizeof(**cred));
	(*cred)->cert_file = apr_pstrdup(pool, PyString_AsString(py_cert_file));
	(*cred)->may_save = (py_may_save == Py_True);
	Py_DECREF(ret);
	return NULL;
}



static PyObject *get_ssl_client_cert_pw_prompt_provider(PyObject *self, PyObject *args)
{
	PyObject *prompt_func;
	int retry_limit;
	AuthProviderObject *auth;

	if (!PyArg_ParseTuple(args, "Oi", &prompt_func, &retry_limit))
		return NULL;

	auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	if (auth == NULL)
		return NULL;
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	Py_INCREF(prompt_func);
	svn_auth_get_ssl_client_cert_pw_prompt_provider (&auth->provider, py_ssl_client_cert_pw_prompt, (void *)prompt_func, retry_limit, auth->pool);
	return (PyObject *)auth;
}

static PyObject *get_ssl_client_cert_prompt_provider(PyObject *self, PyObject *args)
{
	PyObject *prompt_func;
	int retry_limit;
	AuthProviderObject *auth;

	if (!PyArg_ParseTuple(args, "Oi", &prompt_func, &retry_limit))
		return NULL;

	auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	if (auth == NULL)
		return NULL;
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	Py_INCREF(prompt_func);
	svn_auth_get_ssl_client_cert_prompt_provider (&auth->provider, py_ssl_client_cert_prompt, (void *)prompt_func, retry_limit, auth->pool);
	return (PyObject *)auth;
}

static PyObject *get_username_provider(PyObject *self)
{
	AuthProviderObject *auth;
	auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	if (auth == NULL)
		return NULL;
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	svn_auth_get_username_provider(&auth->provider, auth->pool);
	return (PyObject *)auth;
}

static PyObject *get_simple_provider(PyObject *self)
{
	AuthProviderObject *auth = PyObject_New(AuthProviderObject, 
											&AuthProvider_Type);
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	svn_auth_get_simple_provider(&auth->provider, auth->pool);
	return (PyObject *)auth;
}

static PyObject *get_ssl_server_trust_file_provider(PyObject *self)
{
	AuthProviderObject *auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	svn_auth_get_ssl_server_trust_file_provider(&auth->provider, auth->pool);
	return (PyObject *)auth;
}

static PyObject *get_ssl_client_cert_file_provider(PyObject *self)
{
	AuthProviderObject *auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	svn_auth_get_ssl_client_cert_file_provider(&auth->provider, auth->pool);
	return (PyObject *)auth;
}

static PyObject *get_ssl_client_cert_pw_file_provider(PyObject *self)
{
	AuthProviderObject *auth = PyObject_New(AuthProviderObject, &AuthProvider_Type);
	auth->pool = Pool(NULL);
	if (auth->pool == NULL)
		return NULL;
	svn_auth_get_ssl_client_cert_pw_file_provider(&auth->provider, auth->pool);
	return (PyObject *)auth;
}

static PyMethodDef ra_module_methods[] = {
	{ "version", (PyCFunction)version, METH_NOARGS, NULL },
	{ "get_ssl_client_cert_pw_file_provider", (PyCFunction)get_ssl_client_cert_pw_file_provider, METH_NOARGS, NULL },
	{ "get_ssl_client_cert_file_provider", (PyCFunction)get_ssl_client_cert_file_provider, METH_NOARGS, NULL },
	{ "get_ssl_server_trust_file_provider", (PyCFunction)get_ssl_server_trust_file_provider, METH_NOARGS, NULL },
	{ "get_simple_provider", (PyCFunction)get_simple_provider, METH_NOARGS, NULL },
	{ "get_username_prompt_provider", (PyCFunction)get_username_prompt_provider, METH_VARARGS, NULL },
	{ "get_simple_prompt_provider", (PyCFunction)get_simple_prompt_provider, METH_VARARGS, NULL },
	{ "get_ssl_server_trust_prompt_provider", (PyCFunction)get_ssl_server_trust_prompt_provider, METH_VARARGS, NULL },
	{ "get_ssl_client_cert_prompt_provider", (PyCFunction)get_ssl_client_cert_prompt_provider, METH_VARARGS, NULL },
	{ "get_ssl_client_cert_pw_prompt_provider", (PyCFunction)get_ssl_client_cert_pw_prompt_provider, METH_VARARGS, NULL },
	{ "get_username_provider", (PyCFunction)get_username_provider, METH_NOARGS, NULL },
	{ NULL, }
};

void initra(void)
{
	static apr_pool_t *pool;
	PyObject *mod;

	if (PyType_Ready(&RemoteAccess_Type) < 0)
		return;

	if (PyType_Ready(&Editor_Type) < 0)
		return;

	if (PyType_Ready(&FileEditor_Type) < 0)
		return;

	if (PyType_Ready(&DirectoryEditor_Type) < 0)
		return;

	if (PyType_Ready(&Reporter_Type) < 0)
		return;

	if (PyType_Ready(&TxDeltaWindowHandler_Type) < 0)
		return;

	if (PyType_Ready(&Auth_Type) < 0)
		return;

	if (PyType_Ready(&CredentialsIter_Type) < 0)
		return;

	if (PyType_Ready(&AuthProvider_Type) < 0)
		return;

	apr_initialize();
	pool = Pool(NULL);
	if (pool == NULL)
		return;
	svn_ra_initialize(pool);

	mod = Py_InitModule3("ra", ra_module_methods, "Remote Access");
	if (mod == NULL)
		return;

	PyModule_AddObject(mod, "RemoteAccess", (PyObject *)&RemoteAccess_Type);
	Py_INCREF(&RemoteAccess_Type);

	PyModule_AddObject(mod, "Auth", (PyObject *)&Auth_Type);
	Py_INCREF(&Auth_Type);

	busy_exc = PyErr_NewException("ra.BusyException", NULL, NULL);
	PyModule_AddObject(mod, "BusyException", busy_exc);

	PyModule_AddIntConstant(mod, "DIRENT_KIND", SVN_DIRENT_KIND);
	PyModule_AddIntConstant(mod, "DIRENT_SIZE", SVN_DIRENT_SIZE);
	PyModule_AddIntConstant(mod, "DIRENT_HAS_PROPS", SVN_DIRENT_HAS_PROPS);
	PyModule_AddIntConstant(mod, "DIRENT_CREATED_REV", SVN_DIRENT_CREATED_REV);
	PyModule_AddIntConstant(mod, "DIRENT_TIME", SVN_DIRENT_TIME);
	PyModule_AddIntConstant(mod, "DIRENT_LAST_AUTHOR", SVN_DIRENT_LAST_AUTHOR);
	PyModule_AddIntConstant(mod, "DIRENT_ALL", SVN_DIRENT_ALL);

#if SVN_VER_MAJOR >= 1 && SVN_VER_MINOR >= 5
	PyModule_AddIntConstant(mod, "MERGEINFO_EXPLICIT", svn_mergeinfo_explicit);
	PyModule_AddIntConstant(mod, "MERGEINFO_INHERITED", svn_mergeinfo_inherited);
	PyModule_AddIntConstant(mod, "MERGEINFO_NEAREST_ANCESTOR", svn_mergeinfo_nearest_ancestor);
#endif

#ifdef SVN_VER_REVISION
	PyModule_AddIntConstant(mod, "SVN_REVISION", SVN_VER_REVISION);
#endif
}
