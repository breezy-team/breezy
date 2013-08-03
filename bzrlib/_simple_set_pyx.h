#ifndef __PYX_HAVE__bzrlib___simple_set_pyx
#define __PYX_HAVE__bzrlib___simple_set_pyx
#ifdef __cplusplus
#define __PYX_EXTERN_C extern "C"
#else
#define __PYX_EXTERN_C extern
#endif

struct SimpleSetObject {
  PyObject_HEAD
  struct __pyx_vtabstruct_6bzrlib_15_simple_set_pyx_SimpleSet *__pyx_vtab;
  Py_ssize_t _used;
  Py_ssize_t _fill;
  Py_ssize_t _mask;
  PyObject **_table;
};

#ifndef __PYX_HAVE_API__bzrlib___simple_set_pyx

__PYX_EXTERN_C DL_IMPORT(PyTypeObject) SimpleSet_Type;

#endif

PyMODINIT_FUNC init_simple_set_pyx(void);

#endif
