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

#include <structmember.h>

#include "editor.h"
#include "util.h"
#include "ra.h"

static PyObject *busy_exc;

PyAPI_DATA(PyTypeObject) Reporter_Type;
PyAPI_DATA(PyTypeObject) RemoteAccess_Type;
PyAPI_DATA(PyTypeObject) AuthProvider_Type;
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
    Py_RETURN_NONE; /* FIXME */
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
	if (ret == NULL)
		return py_svn_error();
	Py_DECREF(ret);
	return NULL;
}

static void py_progress_func(apr_off_t progress, apr_off_t total, void *baton, apr_pool_t *pool)
{
    PyObject *fn = (PyObject *)baton, *ret;
    if (fn == Py_None) {
        return;
	}
	ret = PyObject_CallFunction(fn, "ll", progress, total);
	/* TODO: What to do with exceptions raised here ? */
	if (ret == NULL)
		return;
	Py_DECREF(ret);
}


typedef struct {
	PyObject_HEAD
    const svn_ra_reporter2_t *reporter;
    void *report_baton;
    apr_pool_t *pool;
	void (*done_cb)(void *baton);
	void *done_baton;
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

	if (reporter->done_cb != NULL)
		reporter->done_cb(reporter->done_baton);

	if (!check_error(reporter->reporter->finish_report(reporter->report_baton, 
													  reporter->pool)))
		return NULL;

	Py_RETURN_NONE;
}

static PyObject *reporter_abort(PyObject *self)
{
	ReporterObject *reporter = (ReporterObject *)self;
	
	if (reporter->done_cb != NULL)
		reporter->done_cb(reporter->done_baton);

	if (!check_error(reporter->reporter->abort_report(reporter->report_baton, 
													 reporter->pool)))
		return NULL;

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
	.tp_name = "ra.Reporter",
	.tp_basicsize = sizeof(ReporterObject),
	.tp_methods = reporter_methods,
	.tp_dealloc = reporter_dealloc,
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
    if (window == NULL) {
        /* Signals all delta windows have been received */
        Py_DECREF(fn);
        return NULL;
	}
    if (fn == Py_None) {
        /* User doesn't care about deltas */
        return NULL;
	}
    ops = PyList_New(window->num_ops);
	for (i = 0; i < window->num_ops; i++) {
		PyList_SetItem(ops, i, Py_BuildValue("(iII)", window->ops[i].action_code, 
					window->ops[i].offset, 
					window->ops[i].length));
	}
	if (window->new_data != NULL && window->new_data->data != NULL) {
		py_new_data = PyString_FromStringAndSize(window->new_data->data, window->new_data->len);
	} else {
		py_new_data = Py_None;
	}
	py_window = Py_BuildValue("((LIIiOO))", window->sview_offset, window->sview_len, window->tview_len, 
								window->src_ops, ops, py_new_data);
	ret = PyObject_CallFunction(fn, "O", py_window);
	Py_DECREF(py_window);
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
	.set_target_revision = py_cb_editor_set_target_revision,
	.open_root = py_cb_editor_open_root,
	.delete_entry = py_cb_editor_delete_entry,
	.add_directory = py_cb_editor_add_directory,
	.open_directory = py_cb_editor_open_directory,
	.change_dir_prop = py_cb_editor_change_prop,
	.close_directory = py_cb_editor_close_directory,
	.absent_directory = py_cb_editor_absent_directory,
	.add_file = py_cb_editor_add_file,
	.open_file = py_cb_editor_open_file,
	.apply_textdelta = py_cb_editor_apply_textdelta,
	.change_file_prop = py_cb_editor_change_prop,
	.close_file = py_cb_editor_close_file,
	.absent_file = py_cb_editor_absent_file,
	.close_edit = py_cb_editor_close_edit,
	.abort_edit = py_cb_editor_abort_edit
};

static svn_error_t *py_file_rev_handler(void *baton, const char *path, svn_revnum_t rev, apr_hash_t *rev_props, svn_txdelta_window_handler_t *delta_handler, void **delta_baton, apr_array_header_t *prop_diffs, apr_pool_t *pool)
{
    PyObject *fn = (PyObject *)baton, *ret, *py_rev_props;

	py_rev_props = prop_hash_to_dict(rev_props);
	if (py_rev_props == NULL)
		return py_svn_error();

	/* FIXME: delta handler */
	ret = PyObject_CallFunction(fn, "slO", path, rev, py_rev_props);
	Py_DECREF(py_rev_props);
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
} RemoteAccessObject;

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

	return NULL;
}
#endif

static svn_error_t *py_open_tmp_file(apr_file_t **fp, void *callback,
									 apr_pool_t *pool)
{
	RemoteAccessObject *self = (RemoteAccessObject *)callback;

	PyErr_SetString(PyExc_NotImplementedError, "open_tmp_file not wrapped yet");
	
	return py_svn_error(); /* FIXME */
}

static PyObject *ra_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
	char *kwnames[] = { "url", "progress_cb", "auth", "config", "client_string_func", NULL };
	char *url;
	PyObject *progress_cb = Py_None;
	AuthObject *auth = (AuthObject *)Py_None;
	PyObject *config = Py_None;
	PyObject *client_string_func = Py_None;
	RemoteAccessObject *ret;
	apr_hash_t *config_hash;
	svn_ra_callbacks2_t *callbacks2;
	svn_auth_baton_t *auth_baton;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|OOOO", kwnames, &url, &progress_cb, 
									 (PyObject **)&auth, &config, &client_string_func))
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
	Py_INCREF(client_string_func);
	callbacks2->progress_func = py_progress_func;
	callbacks2->auth_baton = auth_baton;
	callbacks2->open_tmp_file = py_open_tmp_file;
	ret->progress_func = progress_cb;
	callbacks2->progress_baton = (void *)ret->progress_func;
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
		"discover_changed_paths", "strict_node_history", "revprops", NULL };
	PyObject *callback, *paths;
	svn_revnum_t start = 0, end = 0;
	int limit=0; 
	bool discover_changed_paths=false, strict_node_history=true;
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	PyObject *revprops = Py_None;
    apr_pool_t *temp_pool;
	apr_array_header_t *apr_paths;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OOll|ibbO:get_log", kwnames, 
						 &callback, &paths, &start, &end, &limit,
						 &discover_changed_paths, &strict_node_history,
						 &revprops))
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
	} else if (!string_list_to_apr_array(temp_pool, paths, &apr_paths)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_get_log(ra->ra, 
            apr_paths, start, end, limit,
            discover_changed_paths, strict_node_history, py_svn_log_wrapper, 
            callback, temp_pool));
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
	
	if (ra_check_busy(ra))
		return NULL;

	temp_pool = Pool(NULL);
	if (temp_pool == NULL)
		return NULL;
	RUN_RA_WITH_POOL(temp_pool, ra,
					  svn_ra_get_repos_root(ra->ra, &root, temp_pool));
	apr_pool_destroy(temp_pool);
	return PyString_FromString(root);
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
	ret->done_cb = ra_done_handler;
	ret->done_baton = ra;
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
	ret->done_cb = ra_done_handler;
	ret->done_baton = ra;
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
	apr_pool_destroy(temp_pool);
	return Py_BuildValue("(OlO)", py_dirents, fetch_rev, py_props);
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
					 PyString_AsString(v));
	}
	RUN_RA_WITH_POOL(temp_pool, ra, svn_ra_lock(ra->ra, hash_path_revs, comment, steal_lock,
                     py_lock_func, lock_func, temp_pool));
	apr_pool_destroy(temp_pool);
	return NULL;
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
		apr_hash_this(idx, (const void **)&key, &klen, (void **)&lock);
		PyDict_SetItemString(ret, key, pyify_lock(lock));
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
	apr_pool_destroy(ra->pool);
	Py_XDECREF(ra->auth);
	PyObject_Del(self);
}

static PyObject *ra_repr(PyObject *self)
{
	RemoteAccessObject *ra = (RemoteAccessObject *)self;
	return PyString_FromFormat("RemoteAccess(%s)", ra->url);
}

static PyMethodDef ra_methods[] = {
	{ "get_file_revs", ra_get_file_revs, METH_VARARGS, NULL },
	{ "get_locations", ra_get_locations, METH_VARARGS, NULL },
	{ "get_locks", ra_get_locks, METH_VARARGS, NULL },
	{ "lock", ra_lock, METH_VARARGS, NULL },
	{ "unlock", ra_unlock, METH_VARARGS, NULL },
	{ "has_capability", ra_has_capability, METH_VARARGS, NULL },
	{ "check_path", ra_check_path, METH_VARARGS, NULL },
	{ "get_lock", ra_get_lock, METH_VARARGS, NULL },
	{ "get_dir", ra_get_dir, METH_VARARGS, NULL },
	{ "change_rev_prop", ra_change_rev_prop, METH_VARARGS, NULL },
	{ "get_commit_editor", (PyCFunction)get_commit_editor, METH_VARARGS|METH_KEYWORDS, NULL },
	{ "rev_proplist", ra_rev_proplist, METH_VARARGS, NULL },
	{ "replay", ra_replay, METH_VARARGS, NULL },
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
	PyObject_HEAD_INIT(&PyType_Type) 0,
	.tp_name = "ra.RemoteAccess",
	.tp_basicsize = sizeof(RemoteAccessObject),
	.tp_new = ra_new,
	.tp_dealloc = ra_dealloc,
	.tp_repr = ra_repr,
	.tp_methods = ra_methods,
	.tp_members = ra_members,
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
	PyObject_HEAD_INIT(&PyType_Type) 0,
	.tp_name = "ra.AuthProvider",
	.tp_basicsize = sizeof(AuthProviderObject),
	.tp_dealloc = auth_provider_dealloc,
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

	ret->pool = Pool(NULL);
	if (ret->pool == NULL)
		return NULL;
	ret->providers = providers;
	Py_INCREF(providers);

    c_providers = apr_array_make(ret->pool, PyList_Size(providers), 4);
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
	char *name, *value;
	if (!PyArg_ParseTuple(args, "ss", &name, &value)) {
        svn_auth_set_parameter(auth->auth_baton, name, (char *)value);
	}

	Py_RETURN_NONE;
}

static PyObject *auth_get_parameter(PyObject *self, PyObject *args)
{
	char *name;
	AuthObject *auth = (AuthObject *)self;

	if (!PyArg_ParseTuple(args, "s", &name))
		return NULL;

	return PyString_FromString(svn_auth_get_parameter(auth->auth_baton, name));
}

static PyMethodDef auth_methods[] = {
	{ "set_parameter", auth_set_parameter, METH_VARARGS, NULL },
	{ "get_parameter", auth_get_parameter, METH_VARARGS, NULL },
	{ NULL, }
};

static void auth_dealloc(PyObject *self)
{
	AuthObject *auth = (AuthObject *)self;
	apr_pool_destroy(auth->pool);
	Py_DECREF(auth->providers);	
}

PyTypeObject Auth_Type = {
	PyObject_HEAD_INIT(&PyType_Type) 0,
	.tp_new = auth_init,
	.tp_basicsize = sizeof(AuthObject),
	.tp_dealloc = auth_dealloc,
	.tp_name = "ra.Auth",
	.tp_methods = auth_methods,
};

static svn_error_t *py_username_prompt(svn_auth_cred_username_t **cred, void *baton, const char *realm, int may_save, apr_pool_t *pool)
{
    PyObject *fn = (PyObject *)baton, *ret;
	ret = PyObject_CallFunction(fn, "sb", realm, may_save);
	if (ret == NULL)
		return py_svn_error();
	(*cred)->username = apr_pstrdup(pool, PyString_AsString(PyTuple_GetItem(ret, 0)));
	(*cred)->may_save = (PyTuple_GetItem(ret, 1) == Py_True);
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
	ret = PyObject_CallFunction(fn, "ssb", realm, username, may_save);
	if (ret == NULL)
		return py_svn_error();
	/* FIXME: Check type of ret */
    (*cred)->username = apr_pstrdup(pool, PyString_AsString(PyTuple_GetItem(ret, 0)));
    (*cred)->password = apr_pstrdup(pool, PyString_AsString(PyTuple_GetItem(ret, 1)));
	(*cred)->may_save = (PyTuple_GetItem(ret, 2) == Py_True);
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

	ret = PyObject_CallFunction(fn, "sl(ssssss)b", realm, failures, 
						  cert_info->hostname, cert_info->fingerprint, 
						  cert_info->valid_from, cert_info->valid_until, 
						  cert_info->issuer_dname, cert_info->ascii_cert, 
						  may_save);
	if (ret == NULL)
		return py_svn_error();

	/* FIXME: Check that ret is a tuple of size 2 */

	(*cred)->may_save = (PyTuple_GetItem(ret, 0) == Py_True);
	(*cred)->accepted_failures = PyLong_AsLong(PyTuple_GetItem(ret, 1));

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
    PyObject *fn = (PyObject *)baton, *ret;
	ret = PyObject_CallFunction(fn, "sb", realm, may_save);
	if (ret == NULL) 
		return py_svn_error();
	/* FIXME: Check ret is a tuple of size 2 */
	(*cred)->password = apr_pstrdup(pool, PyString_AsString(PyTuple_GetItem(ret, 0)));
	(*cred)->may_save = (PyTuple_GetItem(ret, 1) == Py_True);
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

static PyObject *txdelta_send_stream(PyObject *self, PyObject *args)
{
    unsigned char digest[16];
    apr_pool_t *pool;
	PyObject *stream;
	TxDeltaWindowHandlerObject *py_txdelta;

	if (!PyArg_ParseTuple(args, "OO", &stream, &py_txdelta))
		return NULL;

	pool = Pool(NULL);

	if (pool == NULL)
		return NULL;

    if (!check_error(svn_txdelta_send_stream(new_py_stream(pool, stream), py_txdelta->txdelta_handler, py_txdelta->txdelta_baton, (unsigned char *)digest, pool))) {
		apr_pool_destroy(pool);
		return NULL;
	}
    apr_pool_destroy(pool);
    return PyString_FromStringAndSize((char *)digest, 16);
}

static PyMethodDef ra_module_methods[] = {
	{ "version", (PyCFunction)version, METH_NOARGS, NULL },
	{ "txdelta_send_stream", txdelta_send_stream, METH_VARARGS, NULL },
	{ "get_ssl_client_cert_pw_file_provider", (PyCFunction)get_ssl_client_cert_pw_file_provider, METH_NOARGS, NULL },
	{ "get_ssl_client_cert_file_provider", (PyCFunction)get_ssl_client_cert_file_provider, METH_NOARGS, NULL },
	{ "get_ssl_server_trust_file_provider", (PyCFunction)get_ssl_server_trust_file_provider, METH_NOARGS, NULL },
	{ "get_simple_provider", (PyCFunction)get_simple_provider, METH_NOARGS, NULL },
	{ "get_username_prompt_provider", (PyCFunction)get_username_prompt_provider, METH_VARARGS, NULL },
	{ "get_simple_prompt_provider", (PyCFunction)get_simple_prompt_provider, METH_VARARGS, NULL },
	{ "get_ssl_server_trust_prompt_provider", (PyCFunction)get_ssl_server_trust_prompt_provider, METH_VARARGS, NULL },
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

#ifdef SVN_VER_REVISION
	PyModule_AddIntConstant(mod, "SVN_REVISION", SVN_VER_REVISION);
#endif
}
