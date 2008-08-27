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

#ifndef _BZR_SVN_UTIL_H_
#define _BZR_SVN_UTIL_H_

/* There's no Py_ssize_t in 2.4, apparently */
#if PY_MAJOR_VERSION == 2 && PY_MINOR_VERSION < 5
typedef int Py_ssize_t;
#endif

#pragma GCC visibility push(hidden)

__attribute__((warn_unused_result)) apr_pool_t *Pool(apr_pool_t *parent);
__attribute__((warn_unused_result)) bool check_error(svn_error_t *error);
bool string_list_to_apr_array(apr_pool_t *pool, PyObject *l, apr_array_header_t **);
bool path_list_to_apr_array(apr_pool_t *pool, PyObject *l, apr_array_header_t **);
PyObject *prop_hash_to_dict(apr_hash_t *props);
apr_hash_t *prop_dict_to_hash(apr_pool_t *pool, PyObject *py_props);
svn_error_t *py_svn_log_wrapper(void *baton, apr_hash_t *changed_paths, 
								long revision, const char *author, 
								const char *date, const char *message, 
								apr_pool_t *pool);
svn_error_t *py_svn_error(void);
void PyErr_SetSubversionException(svn_error_t *error);

#define RUN_SVN(cmd) { \
	svn_error_t *err; \
	PyThreadState *_save; \
	_save = PyEval_SaveThread(); \
	err = (cmd); \
	PyEval_RestoreThread(_save); \
	if (!check_error(err)) { \
		return NULL; \
	} \
}

#define RUN_SVN_WITH_POOL(pool, cmd) { \
	svn_error_t *err; \
	PyThreadState *_save; \
	_save = PyEval_SaveThread(); \
	err = (cmd); \
	PyEval_RestoreThread(_save); \
	if (!check_error(err)) { \
		apr_pool_destroy(pool); \
		return NULL; \
	} \
}

PyObject *wrap_lock(svn_lock_t *lock);
apr_array_header_t *revnum_list_to_apr_array(apr_pool_t *pool, PyObject *l);
svn_stream_t *new_py_stream(apr_pool_t *pool, PyObject *py);
PyObject *PyErr_NewSubversionException(svn_error_t *error);
svn_error_t *py_cancel_func(void *cancel_baton);
apr_hash_t *config_hash_from_object(PyObject *config, apr_pool_t *pool);
void PyErr_SetAprStatus(apr_status_t status);

#if SVN_VER_MAJOR == 1 && SVN_VER_MINOR >= 5
svn_error_t *py_svn_log_entry_receiver(void *baton, svn_log_entry_t *log_entry, apr_pool_t *pool);
#endif

#pragma GCC visibility pop

#define CB_CHECK_PYRETVAL(ret) \
	if (ret == NULL) { \
		PyGILState_Release(state); \
		return py_svn_error(); \
	}

#endif /* _BZR_SVN_UTIL_H_ */
