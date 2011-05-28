#ifndef __PYX_HAVE_API__bzrlib___simple_set_pyx
#define __PYX_HAVE_API__bzrlib___simple_set_pyx
#include "Python.h"
#include "_simple_set_pyx.h"

static PyTypeObject *__pyx_ptype_6bzrlib_15_simple_set_pyx_SimpleSet;
#define SimpleSet_Type (*__pyx_ptype_6bzrlib_15_simple_set_pyx_SimpleSet)

static struct SimpleSetObject *(*SimpleSet_New)(void);
static PyObject *(*SimpleSet_Add)(PyObject *,PyObject *);
static int (*SimpleSet_Contains)(PyObject *,PyObject *);
static int (*SimpleSet_Discard)(PyObject *,PyObject *);
static PyObject *(*SimpleSet_Get)(struct SimpleSetObject *,PyObject *);
static Py_ssize_t (*SimpleSet_Size)(PyObject *);
static int (*SimpleSet_Next)(PyObject *,Py_ssize_t *,PyObject **);
static PyObject **(*_SimpleSet_Lookup)(PyObject *,PyObject *);

#ifndef __PYX_HAVE_API_FUNC_import_module
#define __PYX_HAVE_API_FUNC_import_module

#ifndef __PYX_HAVE_RT_ImportModule
#define __PYX_HAVE_RT_ImportModule
static PyObject *__Pyx_ImportModule(char *name) {
    PyObject *py_name = 0;
    
    py_name = PyString_FromString(name);
    if (!py_name)
        goto bad;
    return PyImport_Import(py_name);
bad:
    Py_XDECREF(py_name);
    return 0;
}
#endif

#endif


#ifndef __PYX_HAVE_RT_ImportFunction
#define __PYX_HAVE_RT_ImportFunction
static int __Pyx_ImportFunction(PyObject *module, char *funcname, void **f, char *sig) {
    PyObject *d = 0;
    PyObject *cobj = 0;
    char *desc;
    
    d = PyObject_GetAttrString(module, "__pyx_capi__");
    if (!d)
        goto bad;
    cobj = PyDict_GetItemString(d, funcname);
    if (!cobj) {
        PyErr_Format(PyExc_ImportError,
            "%s does not export expected C function %s",
                PyModule_GetName(module), funcname);
        goto bad;
    }
    desc = (char *)PyCObject_GetDesc(cobj);
    if (!desc)
        goto bad;
    if (strcmp(desc, sig) != 0) {
        PyErr_Format(PyExc_TypeError,
            "C function %s.%s has wrong signature (expected %s, got %s)",
                PyModule_GetName(module), funcname, sig, desc);
        goto bad;
    }
    *f = PyCObject_AsVoidPtr(cobj);
    Py_DECREF(d);
    return 0;
bad:
    Py_XDECREF(d);
    return -1;
}
#endif


#ifndef __PYX_HAVE_RT_ImportType
#define __PYX_HAVE_RT_ImportType
static PyTypeObject *__Pyx_ImportType(char *module_name, char *class_name, 
    long size) 
{
    PyObject *py_module = 0;
    PyObject *result = 0;
    
    py_module = __Pyx_ImportModule(module_name);
    if (!py_module)
        goto bad;
    result = PyObject_GetAttrString(py_module, class_name);
    if (!result)
        goto bad;
    if (!PyType_Check(result)) {
        PyErr_Format(PyExc_TypeError, 
            "%s.%s is not a type object",
            module_name, class_name);
        goto bad;
    }
    if (((PyTypeObject *)result)->tp_basicsize != size) {
        PyErr_Format(PyExc_ValueError, 
            "%s.%s does not appear to be the correct type object",
            module_name, class_name);
        goto bad;
    }
    return (PyTypeObject *)result;
bad:
    Py_XDECREF(result);
    return 0;
}
#endif

static int import_bzrlib___simple_set_pyx(void) {
  PyObject *module = 0;
  module = __Pyx_ImportModule("bzrlib._simple_set_pyx");
  if (!module) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_New", (void**)&SimpleSet_New, "struct SimpleSetObject *(void)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Add", (void**)&SimpleSet_Add, "PyObject *(PyObject *,PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Contains", (void**)&SimpleSet_Contains, "int (PyObject *,PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Discard", (void**)&SimpleSet_Discard, "int (PyObject *,PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Get", (void**)&SimpleSet_Get, "PyObject *(struct SimpleSetObject *,PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Size", (void**)&SimpleSet_Size, "Py_ssize_t (PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Next", (void**)&SimpleSet_Next, "int (PyObject *,Py_ssize_t *,PyObject **)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "_SimpleSet_Lookup", (void**)&_SimpleSet_Lookup, "PyObject **(PyObject *,PyObject *)") < 0) goto bad;
  Py_DECREF(module); module = 0;
  __pyx_ptype_6bzrlib_15_simple_set_pyx_SimpleSet = __Pyx_ImportType("bzrlib._simple_set_pyx", "SimpleSet", sizeof(struct SimpleSetObject)); if (!__pyx_ptype_6bzrlib_15_simple_set_pyx_SimpleSet) goto bad;
  return 0;
  bad:
  Py_XDECREF(module);
  return -1;
}

#endif
