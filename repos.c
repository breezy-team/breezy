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
#include <svn_fs.h>
#include <svn_repos.h>

#include "util.h"

PyAPI_DATA(PyTypeObject) Repository_Type;
PyAPI_DATA(PyTypeObject) FileSystem_Type;

typedef struct { 
	PyObject_HEAD
    apr_pool_t *pool;
    svn_repos_t *repos;
} RepositoryObject;

static PyObject *repos_create(PyObject *self, PyObject *args)
{
	char *path;
	PyObject *config=Py_None, *fs_config=Py_None;
    svn_repos_t *repos;
    apr_pool_t *pool;
    apr_hash_t *hash_config, *hash_fs_config;
	RepositoryObject *ret;

	if (!PyArg_ParseTuple(args, "s|OO", &path, &config, &fs_config))
		return NULL;

    pool = Pool();
	if (pool == NULL)
		return NULL;
    hash_config = apr_hash_make(pool); /* FIXME */
    hash_fs_config = apr_hash_make(pool); /* FIXME */
    RUN_SVN_WITH_POOL(pool, svn_repos_create(&repos, path, NULL, NULL, 
                hash_config, hash_fs_config, pool));

	ret = PyObject_New(RepositoryObject, &Repository_Type);
	if (ret == NULL)
		return NULL;

	ret->pool = pool;
	ret->repos = repos;

    return (PyObject *)ret;
}

static void repos_dealloc(PyObject *self)
{
	RepositoryObject *repos = (RepositoryObject *)self;

	apr_pool_destroy(repos->pool);
}

static PyObject *repos_init(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
	char *path;
	char *kwnames[] = { "path", NULL };
	RepositoryObject *ret;

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s", kwnames, &path))
		return NULL;

	ret = PyObject_New(RepositoryObject, &Repository_Type);
	if (ret == NULL)
		return NULL;

	ret->pool = Pool();
	if (ret->pool == NULL)
		return NULL;
    if (!check_error(svn_repos_open(&ret->repos, path, ret->pool))) {
		apr_pool_destroy(ret->pool);
		PyObject_Del(ret);
		return NULL;
	}

	return (PyObject *)ret;
}

typedef struct {
	PyObject_HEAD
	RepositoryObject *repos;
	apr_pool_t *pool;
	svn_fs_t *fs;
} FileSystemObject;

static PyObject *repos_fs(PyObject *self)
{
	RepositoryObject *reposobj = (RepositoryObject *)self;
	FileSystemObject *ret;
	svn_fs_t *fs;

	fs = svn_repos_fs(reposobj->repos);

	if (fs == NULL) {
		PyErr_SetString(PyExc_RuntimeError, "Unable to obtain fs handle");
		return NULL;
	}

	ret = PyObject_New(FileSystemObject, &FileSystem_Type);
	if (ret == NULL)
		return NULL;

	ret->fs = fs;
	ret->repos = reposobj;
	ret->pool = reposobj->pool;
	Py_INCREF(reposobj);

	return (PyObject *)ret;
}

static PyObject *fs_get_uuid(PyObject *self)
{
	FileSystemObject *fsobj = (FileSystemObject *)self;
	const char *uuid;
	PyObject *ret;
	apr_pool_t *temp_pool;

	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_fs_get_uuid(fsobj->fs, &uuid, temp_pool));
	ret = PyString_FromString(uuid);
	apr_pool_destroy(temp_pool);

	return ret;
}

static PyMethodDef fs_methods[] = {
	{ "get_uuid", (PyCFunction)fs_get_uuid, METH_NOARGS, NULL },
	{ NULL, }
};

static void fs_dealloc(PyObject *self)
{
	FileSystemObject *fsobj = (FileSystemObject *)self;

	Py_DECREF(fsobj->repos);
	apr_pool_destroy(fsobj->pool);
}

PyTypeObject FileSystem_Type = {
	PyObject_HEAD_INIT(NULL) 0,
	.tp_name = "repos.FileSystem",
	.tp_basicsize = sizeof(FileSystemObject),
	.tp_dealloc = fs_dealloc,
	.tp_methods = fs_methods,
};

static PyObject *repos_load_fs(PyObject *self, PyObject *args, PyObject *kwargs)
{
	const char *parent_dir = "";
	PyObject *dumpstream, *feedback_stream, *cancel_func = Py_None;
	bool use_pre_commit_hook = false, use_post_commit_hook = false;
	char *kwnames[] = { "dumpstream", "feedback_stream", "uuid_action",
		                "parent_dir", "use_pre_commit_hook", 
						"use_post_commit_hook", "cancel_func", NULL };
	int uuid_action;
	apr_pool_t *temp_pool;
	RepositoryObject *reposobj = (RepositoryObject *)self;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OOi|sbbO", kwnames,
								&dumpstream, &feedback_stream, &uuid_action,
								&parent_dir, &use_pre_commit_hook, 
								&use_post_commit_hook,
								&cancel_func))
		return NULL;

	temp_pool = Pool();
	if (temp_pool == NULL)
		return NULL;
	RUN_SVN_WITH_POOL(temp_pool, svn_repos_load_fs2(reposobj->repos, 
				new_py_stream(temp_pool, dumpstream), 
				new_py_stream(temp_pool, feedback_stream),
				uuid_action, parent_dir, use_pre_commit_hook, 
				use_post_commit_hook, py_cancel_func, (void *)cancel_func,
				reposobj->pool));
	apr_pool_destroy(temp_pool);
	Py_RETURN_NONE;
}

static PyMethodDef repos_module_methods[] = {
	{ "create", repos_create, METH_VARARGS, NULL },
	{ NULL, }
};

static PyMethodDef repos_methods[] = {
	{ "load_fs", (PyCFunction)repos_load_fs, METH_VARARGS|METH_KEYWORDS, NULL },
	{ "fs", (PyCFunction)repos_fs, METH_NOARGS, NULL },
	{ NULL, }
};

PyTypeObject Repository_Type = {
	PyObject_HEAD_INIT(&PyType_Type) 0,
	.tp_name = "repos.Repository",
	.tp_basicsize = sizeof(RepositoryObject),
	.tp_dealloc = repos_dealloc,
	.tp_methods = repos_methods,
	.tp_new = repos_init,
};

void initrepos(void)
{
	static apr_pool_t *pool;
	PyObject *mod;

	if (PyType_Ready(&Repository_Type) < 0)
		return;

	if (PyType_Ready(&FileSystem_Type) < 0)
		return;

	apr_initialize();
	pool = Pool();
	if (pool == NULL)
		return;

	svn_fs_initialize(pool);

	mod = Py_InitModule3("repos", repos_module_methods, "Local repository management");
	if (mod == NULL)
		return;

	PyModule_AddObject(mod, "LOAD_UUID_DEFAULT", PyLong_FromLong(0));
	PyModule_AddObject(mod, "LOAD_UUID_IGNORE", PyLong_FromLong(1));
	PyModule_AddObject(mod, "LOAD_UUID_FORCE", PyLong_FromLong(2));

	PyModule_AddObject(mod, "Repository", (PyObject *)&Repository_Type);
	Py_INCREF(&Repository_Type);
}
