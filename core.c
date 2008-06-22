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
#include <string.h>
#include <svn_time.h>
#include <svn_config.h>
#include <svn_io.h>
#include <svn_utf.h>

#include "util.h"

/** Parse a Subversion time string and return a UNIX timestamp. */
static PyObject *time_from_cstring(PyObject *self, PyObject *args)
{
    apr_time_t when;
    apr_pool_t *pool;
	char *data;

	if (!PyArg_ParseTuple(args, "s", &data))
		return NULL;

    pool = Pool(NULL);
	if (pool == NULL)
		return NULL;
    RUN_SVN_WITH_POOL(pool, svn_time_from_cstring(&when, data, pool));
    apr_pool_destroy(pool);
    return PyLong_FromLongLong(when);
}

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

static PyMethodDef core_methods[] = {
	{ "time_from_cstring", time_from_cstring, METH_VARARGS, NULL },
	{ NULL, }
};

void initcore(void)
{
	static apr_pool_t *pool;
	PyObject *mod;

	if (PyType_Ready(&Config_Type) < 0)
		return;

	apr_initialize();
	pool = Pool(NULL);
	if (pool == NULL)
		return;
	svn_utf_initialize(pool);

	mod = Py_InitModule3("core", core_methods, "Core functions");
	if (mod == NULL)
		return;

	PyModule_AddIntConstant(mod, "NODE_DIR", svn_node_dir);
	PyModule_AddIntConstant(mod, "NODE_FILE", svn_node_file);
	PyModule_AddIntConstant(mod, "NODE_UNKNOWN", svn_node_unknown);
	PyModule_AddIntConstant(mod, "NODE_NONE", svn_node_none);

	PyModule_AddObject(mod, "SubversionException", 
					   PyErr_NewException("core.SubversionException", NULL, NULL));
}
