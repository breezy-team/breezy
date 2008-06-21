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
#include <svn_opt.h>
#include <svn_client.h>
#include <svn_config.h>

#include "util.h"
#include "ra.h"

PyAPI_DATA(PyTypeObject) Client_Type;

static int client_set_auth(PyObject *self, PyObject *auth, void *closure);

static bool to_opt_revision(PyObject *arg, svn_opt_revision_t *ret)
{
    if (PyInt_Check(arg)) {
        ret->kind = svn_opt_revision_number;
        ret->value.number = PyLong_AsLong(arg);
        return true;
    } else if (arg == Py_None) {
        ret->kind = svn_opt_revision_unspecified;
        return true;
    } else if (PyString_Check(arg)) {
        char *text = PyString_AsString(arg);
        if (!strcmp(text, "HEAD")) {
            ret->kind = svn_opt_revision_head;
            return true;
        } else if (!strcmp(text, "WORKING")) {
            ret->kind = svn_opt_revision_working;
            return true;
        } else if (!strcmp(text, "BASE")) {
            ret->kind = svn_opt_revision_base;
            return true;
        } 
    } 

    PyErr_SetString(PyExc_ValueError, "Unable to parse revision");
    return false;
}

static PyObject *wrap_py_commit_items(const apr_array_header_t *commit_items)
{
	PyObject *ret;
	int i;

    ret = PyList_New(commit_items->nelts);
	if (ret == NULL)
		return NULL;

	assert(commit_items->elt_size == sizeof(svn_client_commit_item_2_t *));

	for (i = 0; i < commit_items->nelts; i++) {
		svn_client_commit_item2_t *commit_item = 
			APR_ARRAY_IDX(commit_items, i, svn_client_commit_item2_t *);
		PyObject *item, *copyfrom;

		if (commit_item->copyfrom_url != NULL)
			copyfrom = Py_BuildValue("(si)", commit_item->copyfrom_url, 
									 commit_item->copyfrom_rev);
		else
			copyfrom = Py_None;

		item = Py_BuildValue("(szlOi)", 
							 /* commit_item->path */ "foo",
							 commit_item->url, commit_item->revision, 
							 copyfrom,
							 commit_item->state_flags);

		if (PyList_SetItem(ret, i, item) != 0)
			return NULL;
	}

	return ret;
}

static svn_error_t *py_log_msg_func2(const char **log_msg, const char **tmp_file, const apr_array_header_t *commit_items, void *baton, apr_pool_t *pool)
{
    PyObject *py_commit_items, *ret, *py_log_msg, *py_tmp_file;
    if (baton == Py_None)
        return NULL;

	py_commit_items = wrap_py_commit_items(commit_items);
	if (py_commit_items == NULL)
		return py_svn_error();

    ret = PyObject_CallFunction(baton, "O", py_commit_items);
	Py_DECREF(py_commit_items);
	if (ret == NULL)
		return py_svn_error();
    if (PyTuple_Check(ret)) {
        py_log_msg = PyTuple_GetItem(ret, 0);
        py_tmp_file = PyTuple_GetItem(ret, 1);
    } else {
        py_tmp_file = Py_None;
        py_log_msg = ret;
    }
    if (py_log_msg != Py_None) {
        *log_msg = PyString_AsString(py_log_msg);
    }
    if (py_tmp_file != Py_None) {
        *tmp_file = PyString_AsString(py_tmp_file);
    }
	Py_DECREF(ret);
    return NULL;
}

static PyObject *py_commit_info_tuple(svn_commit_info_t *ci)
{
	if (ci == NULL)
		Py_RETURN_NONE;
    if (ci->revision == SVN_INVALID_REVNUM)
        Py_RETURN_NONE;
    return Py_BuildValue("(izz)", ci->revision, ci->date, ci->author);
}

typedef struct {
    PyObject_HEAD
    svn_client_ctx_t *client;
    apr_pool_t *pool;
    PyObject *callbacks;
	PyObject *py_auth;
} ClientObject;

static PyObject *client_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    ClientObject *ret;
	PyObject *config = Py_None, *auth = Py_None;
    char *kwnames[] = { "config", "auth", NULL };
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|OO", kwnames, &config, &auth))
        return NULL;

    ret = PyObject_New(ClientObject, &Client_Type);
    if (ret == NULL)
        return NULL;

    ret->pool = Pool();
	if (ret->pool == NULL) {
		PyObject_Del(ret);
		return NULL;
	}

    if (!check_error(svn_client_create_context(&ret->client, ret->pool))) {
		apr_pool_destroy(ret->pool);
		PyObject_Del(ret);
        return NULL;
	}

	if (config != Py_None) {
		PyErr_SetString(PyExc_NotImplementedError, "custom config not supported yet");
		return NULL;
	}

	ret->py_auth = NULL;
	client_set_auth((PyObject *)ret, auth, NULL);
    return (PyObject *)ret;
}

static void client_dealloc(PyObject *self)
{
    ClientObject *client = (ClientObject *)self;
	if (client->client->log_msg_func2 != NULL) {
		Py_DECREF((PyObject *)client->client->log_msg_baton2);
	}
	Py_XDECREF(client->py_auth);
    apr_pool_destroy(client->pool);
	PyObject_Del(self);
}

static PyObject *client_get_log_msg_func(PyObject *self, void *closure)
{
    ClientObject *client = (ClientObject *)self;
    if (client->client->log_msg_func2 == NULL)
		Py_RETURN_NONE;
	return client->client->log_msg_baton2;
}

static int client_set_log_msg_func(PyObject *self, PyObject *func, void *closure)
{
    ClientObject *client = (ClientObject *)self;

	if (client->client->log_msg_baton2 != NULL) {
		Py_DECREF((PyObject *)client->client->log_msg_baton2);
	}
	if (func == Py_None) {
		client->client->log_msg_func2 = NULL;
		client->client->log_msg_baton2 = Py_None;
	} else {
		client->client->log_msg_func2 = py_log_msg_func2;
		client->client->log_msg_baton2 = (void *)func;
	}
    Py_INCREF(func);
    return 0;
}

static int client_set_auth(PyObject *self, PyObject *auth, void *closure)
{
	ClientObject *client = (ClientObject *)self;
	apr_array_header_t *auth_providers;

	Py_XDECREF(client->py_auth);

	if (auth == Py_None) {
		auth_providers = apr_array_make(client->pool, 0, 4);
		if (auth_providers == NULL) {
			PyErr_NoMemory();
			return 1;
		}
		svn_auth_open(&client->client->auth_baton, auth_providers, client->pool);
	} else {
		client->client->auth_baton = ((AuthObject *)auth)->auth_baton;
	}

	client->py_auth = auth;
	Py_INCREF(auth);

	return 0;
}


static PyObject *client_add(PyObject *self, PyObject *args, PyObject *kwargs)
{
    char *path; 
    ClientObject *client = (ClientObject *)self;
    bool recursive=true, force=false, no_ignore=false;
	apr_pool_t *temp_pool;
    char *kwnames[] = { "path", "recursive", "force", "no_ignore", NULL };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|bbb", kwnames, 
                          &path, &recursive, &force, &no_ignore))
        return NULL;
	
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;

	RUN_SVN_WITH_POOL(temp_pool, 
					  svn_client_add3(path, recursive, force, no_ignore, 
                client->client, temp_pool));
	apr_pool_destroy(temp_pool);
    Py_RETURN_NONE;
}

static PyObject *client_checkout(PyObject *self, PyObject *args, PyObject *kwargs)
{
    ClientObject *client = (ClientObject *)self;
    char *kwnames[] = { "url", "path", "rev", "peg_rev", "recurse", "ignore_externals", NULL };
    svn_revnum_t result_rev;
    svn_opt_revision_t c_peg_rev, c_rev;
    char *url, *path; 
	apr_pool_t *temp_pool;
    PyObject *peg_rev=Py_None, *rev=Py_None;
    bool recurse=true, ignore_externals=false;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|OObb", kwnames, &url, &path, &rev, &peg_rev, &recurse, &ignore_externals))
        return NULL;

    if (!to_opt_revision(peg_rev, &c_peg_rev))
        return NULL;
    if (!to_opt_revision(rev, &c_rev))
        return NULL;

	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
    RUN_SVN_WITH_POOL(temp_pool, svn_client_checkout2(&result_rev, url, path, 
        &c_peg_rev, &c_rev, recurse, 
        ignore_externals, client->client, temp_pool));
	apr_pool_destroy(temp_pool);
    return PyLong_FromLong(result_rev);
}

static PyObject *client_commit(PyObject *self, PyObject *args, PyObject *kwargs)
{
    PyObject *targets; 
    ClientObject *client = (ClientObject *)self;
    bool recurse=true, keep_locks=true;
	apr_pool_t *temp_pool;
    svn_commit_info_t *commit_info = NULL;
	PyObject *ret;
	apr_array_header_t *apr_targets;
    char *kwnames[] = { "targets", "recurse", "keep_locks", NULL };
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|bb", kwnames, &targets, &recurse, &keep_locks))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
	if (!string_list_to_apr_array(temp_pool, targets, &apr_targets)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}
    RUN_SVN_WITH_POOL(temp_pool, svn_client_commit3(&commit_info, 
				apr_targets,
               recurse, keep_locks, client->client, temp_pool));
    ret = py_commit_info_tuple(commit_info);
	apr_pool_destroy(temp_pool);

	return ret;
}

static PyObject *client_mkdir(PyObject *self, PyObject *args)
{
    PyObject *paths;
    svn_commit_info_t *commit_info = NULL;
	apr_pool_t *temp_pool;
	apr_array_header_t *apr_paths;
    ClientObject *client = (ClientObject *)self;
	PyObject *ret;
    if (!PyArg_ParseTuple(args, "O", &paths))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
	if (!string_list_to_apr_array(temp_pool, paths, &apr_paths)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}

    if (!check_error(svn_client_mkdir2(&commit_info, apr_paths,
                client->client, temp_pool)))
        return NULL;
    ret = py_commit_info_tuple(commit_info);
	apr_pool_destroy(temp_pool);

	return ret;
}

static PyObject *client_delete(PyObject *self, PyObject *args)
{
    PyObject *paths; 
    bool force=false;
	apr_pool_t *temp_pool;
    svn_commit_info_t *commit_info = NULL;
	PyObject *ret;
	apr_array_header_t *apr_paths;
    ClientObject *client = (ClientObject *)self;

    if (!PyArg_ParseTuple(args, "O|b", &paths, &force))
        return NULL;

	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
    if (!string_list_to_apr_array(temp_pool, paths, &apr_paths)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}

    RUN_SVN_WITH_POOL(temp_pool, svn_client_delete2(&commit_info, 
													apr_paths,
                force, client->client, temp_pool));

    ret = py_commit_info_tuple(commit_info);

	apr_pool_destroy(temp_pool);

	return ret;
}

static PyObject *client_copy(PyObject *self, PyObject *args)
{
    char *src_path, *dst_path;
    PyObject *src_rev=Py_None;
    svn_commit_info_t *commit_info = NULL;
	apr_pool_t *temp_pool;
    svn_opt_revision_t c_src_rev;
	PyObject *ret;
    ClientObject *client = (ClientObject *)self;
    if (!PyArg_ParseTuple(args, "ss|O", &src_path, &dst_path, &src_rev))
        return NULL;
    if (!to_opt_revision(src_rev, &c_src_rev))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
    RUN_SVN_WITH_POOL(temp_pool, svn_client_copy3(&commit_info, src_path, 
                &c_src_rev, dst_path, client->client, temp_pool));
    ret = py_commit_info_tuple(commit_info);
	apr_pool_destroy(temp_pool);
	return ret;
}

static PyObject *client_propset(PyObject *self, PyObject *args)
{
    char *propname;
    svn_string_t c_propval;
    int recurse = true;
    int skip_checks = false;
    ClientObject *client = (ClientObject *)self;
	apr_pool_t *temp_pool;
    char *target;

    if (!PyArg_ParseTuple(args, "sz#s|bb", &propname, &c_propval.data, &c_propval.len, &target, &recurse, &skip_checks))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_client_propset2(propname, &c_propval,
                target, recurse, skip_checks, client->client, temp_pool));
	apr_pool_destroy(temp_pool);
    Py_RETURN_NONE;
}
    
static PyObject *client_propget(PyObject *self, PyObject *args)
{
    svn_opt_revision_t c_peg_rev;
    svn_opt_revision_t c_rev;
    apr_hash_t *hash_props;
    bool recurse = false;
    char *propname;
	apr_pool_t *temp_pool;
    char *target;
    PyObject *peg_revision;
    PyObject *revision;
    ClientObject *client = (ClientObject *)self;
	PyObject *ret;

    if (!PyArg_ParseTuple(args, "ssOO|b", &propname, &target, &peg_revision, 
                          &revision, &recurse))
        return NULL;
    if (!to_opt_revision(peg_revision, &c_peg_rev))
        return NULL;
    if (!to_opt_revision(revision, &c_rev))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
    RUN_SVN_WITH_POOL(temp_pool, 
					  svn_client_propget2(&hash_props, propname, target,
                &c_peg_rev, &c_rev, recurse, client->client, temp_pool));
    ret = prop_hash_to_dict(hash_props);
	apr_pool_destroy(temp_pool);
	return ret;
}

static PyObject *client_update(PyObject *self, PyObject *args)
{
    bool recurse = true;
    bool ignore_externals = false;
	apr_pool_t *temp_pool;
    PyObject *rev = Py_None, *paths;
    apr_array_header_t *result_revs, *apr_paths;
    svn_opt_revision_t c_rev;
    svn_revnum_t ret_rev;
    PyObject *ret;
    int i = 0;
    ClientObject *client = (ClientObject *)self;

    if (!PyArg_ParseTuple(args, "O|Obb", &paths, &rev, &recurse, &ignore_externals))
        return NULL;

    if (!to_opt_revision(rev, &c_rev))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
	if (!string_list_to_apr_array(temp_pool, paths, &apr_paths)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}
    RUN_SVN_WITH_POOL(temp_pool, svn_client_update2(&result_revs, 
            apr_paths, &c_rev, 
            recurse, ignore_externals, client->client, temp_pool));
    ret = PyList_New(result_revs->nelts);
	if (ret == NULL)
		return NULL;
	for (i = 0; i < result_revs->nelts; i++) {
		ret_rev = APR_ARRAY_IDX(result_revs, i, svn_revnum_t);
        if (PyList_SetItem(ret, i, PyLong_FromLong(ret_rev)) != 0)
			return NULL;
    }
	apr_pool_destroy(temp_pool);
    return ret;
}

static PyObject *client_revprop_get(PyObject *self, PyObject *args)
{
    PyObject *rev = Py_None;
    char *propname, *propval, *url;
    svn_revnum_t set_rev;
    svn_opt_revision_t c_rev;
    svn_string_t *c_val;
    ClientObject *client = (ClientObject *)self;
	apr_pool_t *temp_pool;
	PyObject *ret;
    if (!PyArg_ParseTuple(args, "sssO", &propname, &propval, &url, &rev))
        return NULL;
    if (!to_opt_revision(rev, &c_rev))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
    RUN_SVN_WITH_POOL(temp_pool, svn_client_revprop_get(propname, &c_val, url, 
                &c_rev, &set_rev, client->client, temp_pool));
    ret = Py_BuildValue("(z#i)", c_val->data, c_val->len, set_rev);
	apr_pool_destroy(temp_pool);
	return ret;
}

static PyObject *client_revprop_set(PyObject *self, PyObject *args)
{
    PyObject *rev = Py_None;
    bool force = false;
    ClientObject *client = (ClientObject *)self;
    char *propname, *url;
    svn_revnum_t set_rev;
    svn_opt_revision_t c_rev;
	apr_pool_t *temp_pool;
    svn_string_t c_val;
    if (!PyArg_ParseTuple(args, "sz#s|Ob", &propname, &c_val.data, &c_val.len, &url, &rev, &force))
        return NULL;
    if (!to_opt_revision(rev, &c_rev))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
    RUN_SVN_WITH_POOL(temp_pool, svn_client_revprop_set(propname, &c_val, url, 
                &c_rev, &set_rev, force, client->client, temp_pool));
	apr_pool_destroy(temp_pool);
    return PyLong_FromLong(set_rev);
}

static PyObject *client_log(PyObject *self, PyObject *args, PyObject *kwargs)
{
    char *kwnames[] = { "targets", "callback", "peg_revision", "start", "end", "limit", "discover_changed_paths", "strict_node_history", NULL };
    PyObject *targets, *callback, *peg_revision=Py_None, *start=Py_None, 
             *end=Py_None;
    ClientObject *client = (ClientObject *)self;
	apr_pool_t *temp_pool;
    int limit=0; 
    bool discover_changed_paths=true, strict_node_history=true;
    svn_opt_revision_t c_peg_rev, c_start_rev, c_end_rev;
	apr_array_header_t *apr_paths;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OO|OOOlbb", 
                                     kwnames, &targets, &callback, 
                                     &peg_revision, &start, &end, 
                                     &limit, &discover_changed_paths, 
                                     &strict_node_history))
        return NULL;

    if (!to_opt_revision(peg_revision, &c_peg_rev))
        return NULL;
    if (!to_opt_revision(start, &c_start_rev))
        return NULL;
    if (!to_opt_revision(end, &c_end_rev))
        return NULL;
	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
	if (!string_list_to_apr_array(temp_pool, targets, &apr_paths)) {
		apr_pool_destroy(temp_pool);
		return NULL;
	}
	RUN_SVN_WITH_POOL(temp_pool, svn_client_log3(apr_paths,
                &c_peg_rev, &c_start_rev, &c_end_rev, limit, discover_changed_paths, strict_node_history, py_svn_log_wrapper, callback, client->client, temp_pool));
	apr_pool_destroy(temp_pool);
    Py_RETURN_NONE;
}

static PyMethodDef client_methods[] = {
    { "add", (PyCFunction)client_add, METH_VARARGS|METH_KEYWORDS, NULL },
    { "checkout", (PyCFunction)client_checkout, METH_VARARGS|METH_KEYWORDS, NULL },
    { "commit", (PyCFunction)client_commit, METH_VARARGS|METH_KEYWORDS, NULL },
    { "mkdir", client_mkdir, METH_VARARGS, NULL },
    { "delete", client_delete, METH_VARARGS, NULL },
    { "copy", client_copy, METH_VARARGS, NULL },
    { "propset", client_propset, METH_VARARGS, NULL },
    { "propget", client_propget, METH_VARARGS, NULL },
    { "update", client_update, METH_VARARGS, NULL },
    { "revprop_get", client_revprop_get, METH_VARARGS, NULL },
    { "revprop_set", client_revprop_set, METH_VARARGS, NULL },
    { "log", (PyCFunction)client_log, METH_KEYWORDS|METH_VARARGS, NULL },
    { NULL, }
};

static PyGetSetDef client_getset[] = {
	{ "log_msg_func", client_get_log_msg_func, client_set_log_msg_func, NULL },
	{ "auth", NULL, client_set_auth, NULL },
	{ NULL, }
};

typedef struct {
	PyObject_HEAD
	svn_config_t *item;
} ConfigObject;

PyTypeObject Config_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	.tp_name = "core.Config",
	.tp_basicsize = sizeof(ConfigObject),
	.tp_dealloc = (destructor)PyObject_Del,
};



PyTypeObject Client_Type = {
    PyObject_HEAD_INIT(&PyType_Type) 0,
    .tp_name = "client.Client",
    .tp_basicsize = sizeof(ClientObject),
    .tp_methods = client_methods,
    .tp_dealloc = client_dealloc,
    .tp_new = client_new,
	.tp_getset = client_getset
};

static PyObject *get_config(PyObject *self, PyObject *args)
{
    apr_pool_t *pool;
    apr_hash_t *cfg_hash = NULL;
    apr_hash_index_t *idx;
    const char *key;
    svn_config_t *val;
    apr_ssize_t klen;
	char *config_dir = NULL;
	PyObject *ret;

	if (!PyArg_ParseTuple(args, "|z", &config_dir))
		return NULL;

    pool = Pool();
	if (pool == NULL)
		return NULL;

    RUN_SVN_WITH_POOL(pool, 
					  svn_config_get_config(&cfg_hash, config_dir, pool));
    ret = PyDict_New();
    for (idx = apr_hash_first(pool, cfg_hash); idx != NULL; 
		 idx = apr_hash_next(idx)) {
		ConfigObject *data;
        apr_hash_this(idx, (const void **)&key, &klen, (void **)&val);
		data = PyObject_New(ConfigObject, &Config_Type);
		data->item = val;
        PyDict_SetItemString(ret, key, (PyObject *)data);
	}
    apr_pool_destroy(pool);
    return ret;
}

static PyMethodDef client_mod_methods[] = {
	{ "get_config", get_config, METH_VARARGS, NULL },
	{ NULL }
};

void initclient(void)
{
    PyObject *mod;

    if (PyType_Ready(&Client_Type) < 0)
        return;

	/* Make sure APR is initialized */
	apr_initialize();

    mod = Py_InitModule3("client", client_mod_methods, "Client methods");
    if (mod == NULL)
        return;

    Py_INCREF(&Client_Type);
    PyModule_AddObject(mod, "Client", (PyObject *)&Client_Type);
}
