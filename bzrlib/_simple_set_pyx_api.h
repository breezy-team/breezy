#ifndef __PYX_HAVE_API__bzrlib___simple_set_pyx
#define __PYX_HAVE_API__bzrlib___simple_set_pyx
#include "Python.h"
#include "_simple_set_pyx.h"

static PyTypeObject *__pyx_ptype_6bzrlib_15_simple_set_pyx_SimpleSet;
#define SimpleSet_Type (*__pyx_ptype_6bzrlib_15_simple_set_pyx_SimpleSet)

static struct SimpleSetObject *(*SimpleSet_New)(void);
static PyObject *(*SimpleSet_Add)(PyObject *, PyObject *);
static int (*SimpleSet_Contains)(PyObject *, PyObject *);
static int (*SimpleSet_Discard)(PyObject *, PyObject *);
static PyObject *(*SimpleSet_Get)(struct SimpleSetObject *, PyObject *);
static Py_ssize_t (*SimpleSet_Size)(PyObject *);
static int (*SimpleSet_Next)(PyObject *, Py_ssize_t *, PyObject **);
static PyObject **(*_SimpleSet_Lookup)(PyObject *, PyObject *);

#ifndef __PYX_HAVE_API_FUNC_import_module
#define __PYX_HAVE_API_FUNC_import_module

#ifndef __PYX_HAVE_RT_ImportModule
#define __PYX_HAVE_RT_ImportModule
static PyObject *__Pyx_ImportModule(const char *name) {
    PyObject *py_name = 0;
    PyObject *py_module = 0;

    #if PY_MAJOR_VERSION < 3
    py_name = PyString_FromString(name);
    #else
    py_name = PyUnicode_FromString(name);
    #endif
    if (!py_name)
        goto bad;
    py_module = PyImport_Import(py_name);
    Py_DECREF(py_name);
    return py_module;
bad:
    Py_XDECREF(py_name);
    return 0;
}
#endif

#endif


#ifndef __PYX_HAVE_RT_ImportFunction
#define __PYX_HAVE_RT_ImportFunction
static int __Pyx_ImportFunction(PyObject *module, const char *funcname, void (**f)(void), const char *sig) {
    PyObject *d = 0;
    PyObject *cobj = 0;
    union {
        void (*fp)(void);
        void *p;
    } tmp;

    d = PyObject_GetAttrString(module, (char *)"__pyx_capi__");
    if (!d)
        goto bad;
    cobj = PyDict_GetItemString(d, funcname);
    if (!cobj) {
        PyErr_Format(PyExc_ImportError,
            "%s does not export expected C function %s",
                PyModule_GetName(module), funcname);
        goto bad;
    }
#if PY_VERSION_HEX >= 0x02070000 && !(PY_MAJOR_VERSION==3&&PY_MINOR_VERSION==0)
    if (!PyCapsule_IsValid(cobj, sig)) {
        PyErr_Format(PyExc_TypeError,
            "C function %s.%s has wrong signature (expected %s, got %s)",
             PyModule_GetName(module), funcname, sig, PyCapsule_GetName(cobj));
        goto bad;
    }
    tmp.p = PyCapsule_GetPointer(cobj, sig);
#else
    {const char *desc, *s1, *s2;
    desc = (const char *)PyCObject_GetDesc(cobj);
    if (!desc)
        goto bad;
    s1 = desc; s2 = sig;
    while (*s1 != '\0' && *s1 == *s2) { s1++; s2++; }
    if (*s1 != *s2) {
        PyErr_Format(PyExc_TypeError,
            "C function %s.%s has wrong signature (expected %s, got %s)",
             PyModule_GetName(module), funcname, sig, desc);
        goto bad;
    }
    tmp.p = PyCObject_AsVoidPtr(cobj);}
#endif
    *f = tmp.fp;
    if (!(*f))
        goto bad;
    Py_DECREF(d);
    return 0;
bad:
    Py_XDECREF(d);
    return -1;
}
#endif


#ifndef __PYX_HAVE_RT_ImportType
#define __PYX_HAVE_RT_ImportType
static PyTypeObject *__Pyx_ImportType(const char *module_name, const char *class_name,
    long size, int strict)
{
    PyObject *py_module = 0;
    PyObject *result = 0;
    PyObject *py_name = 0;
    char warning[200];

    py_module = __Pyx_ImportModule(module_name);
    if (!py_module)
        goto bad;
    #if PY_MAJOR_VERSION < 3
    py_name = PyString_FromString(class_name);
    #else
    py_name = PyUnicode_FromString(class_name);
    #endif
    if (!py_name)
        goto bad;
    result = PyObject_GetAttr(py_module, py_name);
    Py_DECREF(py_name);
    py_name = 0;
    Py_DECREF(py_module);
    py_module = 0;
    if (!result)
        goto bad;
    if (!PyType_Check(result)) {
        PyErr_Format(PyExc_TypeError, 
            "%s.%s is not a type object",
            module_name, class_name);
        goto bad;
    }
    if (!strict && ((PyTypeObject *)result)->tp_basicsize > size) {
        PyOS_snprintf(warning, sizeof(warning), 
            "%s.%s size changed, may indicate binary incompatibility",
            module_name, class_name);
        #if PY_VERSION_HEX < 0x02050000
        PyErr_Warn(NULL, warning);
        #else
        PyErr_WarnEx(NULL, warning, 0);
        #endif
    }
    else if (((PyTypeObject *)result)->tp_basicsize != size) {
        PyErr_Format(PyExc_ValueError, 
            "%s.%s has the wrong size, try recompiling",
            module_name, class_name);
        goto bad;
    }
    return (PyTypeObject *)result;
bad:
    Py_XDECREF(py_module);
    Py_XDECREF(result);
    return 0;
}
#endif

static int import_bzrlib___simple_set_pyx(void) {
  PyObject *module = 0;
  module = __Pyx_ImportModule("bzrlib._simple_set_pyx");
  if (!module) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_New", (void (**)(void))&SimpleSet_New, "struct SimpleSetObject *(void)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Add", (void (**)(void))&SimpleSet_Add, "PyObject *(PyObject *, PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Contains", (void (**)(void))&SimpleSet_Contains, "int (PyObject *, PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Discard", (void (**)(void))&SimpleSet_Discard, "int (PyObject *, PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Get", (void (**)(void))&SimpleSet_Get, "PyObject *(struct SimpleSetObject *, PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Size", (void (**)(void))&SimpleSet_Size, "Py_ssize_t (PyObject *)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "SimpleSet_Next", (void (**)(void))&SimpleSet_Next, "int (PyObject *, Py_ssize_t *, PyObject **)") < 0) goto bad;
  if (__Pyx_ImportFunction(module, "_SimpleSet_Lookup", (void (**)(void))&_SimpleSet_Lookup, "PyObject **(PyObject *, PyObject *)") < 0) goto bad;
  Py_DECREF(module); module = 0;
  __pyx_ptype_6bzrlib_15_simple_set_pyx_SimpleSet = __Pyx_ImportType("bzrlib._simple_set_pyx", "SimpleSet", sizeof(struct SimpleSetObject), 1); if (!__pyx_ptype_6bzrlib_15_simple_set_pyx_SimpleSet) goto bad;
  return 0;
  bad:
  Py_XDECREF(module);
  return -1;
}

#endif
