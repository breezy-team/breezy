/* Copyright (C) 2009 Canonical Ltd
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
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#ifndef _IMPORT_C_API_H_
#define _IMPORT_C_API_H_

/**
 * Helper functions to eliminate some of the boilerplate when importing a C API
 * from a CPython extension module.
 *
 * For more information see _export_c_api.h
 */

static const char *_C_API_NAME = "_C_API";

/**
 * Import a function from the _C_API_NAME dict that is part of module.
 *
 * @param   module  The Python module we are importing from
 *                  the attribute _C_API_NAME will be used as a dictionary
 *                  containing the function pointer we are looking for.
 * @param   funcname    Name of the function we want to import
 * @param   func    A pointer to the function handle where we will store the
 *                  function.
 * @param   signature   The C signature of the function. This is validated
 *                      against the signature stored in the C api, to make sure
 *                      there is no versioning skew.
 */
static int _import_function(PyObject *module, const char *funcname,
                            void **func, const char *signature)
{
    PyObject *d = NULL;
    PyObject *capsule = NULL;
    void *pointer;

    d = PyObject_GetAttrString(module, _C_API_NAME);
    if (!d) {
        // PyObject_GetAttrString sets an appropriate exception
        goto bad;
    }
    capsule = PyDict_GetItemString(d, funcname);
    if (!capsule) {
        // PyDict_GetItemString does not set an exception
        PyErr_Format(PyExc_AttributeError,
            "Module %s did not export a function named %s\n",
            PyModule_GetName(module), funcname);
        goto bad;
    }
    pointer = PyCapsule_GetPointer(capsule, signature);
    if (!pointer) {
	// PyCapsule_GetPointer sets an error with a little context
        goto bad;
    }
    *func = pointer;
    Py_DECREF(d);
    return 0;
bad:
    Py_XDECREF(d);
    return -1;
}


/**
 * Get a pointer to an exported PyTypeObject.
 *
 * @param   module        The Python module we are importing from
 * @param   class_name    Attribute of the module that should reference the
 *                        Type object. Note that a PyTypeObject is the python
 *                        description of the type, not the raw C structure.
 * @return  A Pointer to the requested type object. On error NULL will be
 *          returned and an exception will be set.
 */
static PyTypeObject *
_import_type(PyObject *module, const char *class_name)
{
    PyObject *type = NULL;

    type = PyObject_GetAttrString(module, (char *)class_name);
    if (!type) {
        goto bad;
    }
    if (!PyType_Check(type)) {
        PyErr_Format(PyExc_TypeError,
            "%s.%s is not a type object",
            PyModule_GetName(module), class_name);
        goto bad;
    }
    return (PyTypeObject *)type;
bad:
    Py_XDECREF(type);
    return NULL;
}


struct function_description
{
    const char *name;
    void **pointer;
    const char *signature;
};

struct type_description
{
    const char *name;
    PyTypeObject **pointer;
};

/**
 * Helper for importing several functions and types in a data-driven manner.
 *
 * @param   module  The name of the module we will be importing
 * @param   functions   A list of function_description objects, describing the
 *                      functions being imported.
 *                      The list should be terminated with {NULL} to indicate
 *                      there are no more functions to import.
 * @param   types       A list of type_description objects describing type
 *                      objects that we want to import. The list should be
 *                      terminated with {NULL} to indicate there are no more
 *                      types to import.
 * @return  0 on success, -1 on error and an exception should be set.
 */

static int
_import_extension_module(const char *module_name,
                         struct function_description *functions,
                         struct type_description *types)
{
    PyObject *module = NULL;
    struct function_description *cur_func;
    struct type_description *cur_type;
    int ret_code;
    
    module = PyImport_ImportModule((char *)module_name);
    if (!module)
        goto bad;
    if (functions != NULL) {
        cur_func = functions;
        while (cur_func->name != NULL) {
            ret_code = _import_function(module, cur_func->name,
                                        cur_func->pointer,
                                        cur_func->signature);
            if (ret_code < 0)
                goto bad;
            cur_func++;
        }
    }
    if (types != NULL) {
        PyTypeObject *type_p = NULL;
        cur_type = types;
        while (cur_type->name != NULL)  {
            type_p = _import_type(module, cur_type->name);
            if (type_p == NULL)
                goto bad;
            *(cur_type->pointer) = type_p;
            cur_type++;
        }
    }
    
    Py_XDECREF(module);
    return 0;
bad:
    Py_XDECREF(module);
    return -1;
}


#endif // _IMPORT_C_API_H_
