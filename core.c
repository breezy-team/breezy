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

void initcore(void)
{
	static apr_pool_t *pool;
	PyObject *mod;

	apr_initialize();
	pool = Pool(NULL);
	if (pool == NULL)
		return;
	svn_utf_initialize(pool);

	mod = Py_InitModule3("core", NULL, "Core functions");
	if (mod == NULL)
		return;

	PyModule_AddIntConstant(mod, "NODE_DIR", svn_node_dir);
	PyModule_AddIntConstant(mod, "NODE_FILE", svn_node_file);
	PyModule_AddIntConstant(mod, "NODE_UNKNOWN", svn_node_unknown);
	PyModule_AddIntConstant(mod, "NODE_NONE", svn_node_none);

	PyModule_AddObject(mod, "SubversionException", 
					   PyErr_NewException("core.SubversionException", NULL, NULL));
}
