use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::{PyBytes,PyUnicode};

use bazaar_dirstate;

/// Compare two paths directory by directory.
///
///  This is equivalent to doing::
///
///     operator.lt(path1.split('/'), path2.split('/'))
///
///  The idea is that you should compare path components separately. This
///  differs from plain ``path1 < path2`` for paths like ``'a-b'`` and ``a/b``.
///  "a-b" comes after "a" but would come before "a/b" lexically.
///
/// Args:
///  path1: first path
///  path2: second path
/// Returns: True if path1 comes first, otherwise False
#[pyfunction]
fn lt_by_dirs(path1: &PyAny, path2: &PyAny) -> PyResult<bool> {
    let pathstr1: String;
    let pathstr2: String;
    if path1.is_instance_of::<PyBytes>()? && path2.is_instance_of::<PyBytes>()? {
        pathstr1 = String::from_utf8(path1.extract::<&[u8]>().unwrap().to_vec())?;
        pathstr2 = String::from_utf8(path2.extract::<&[u8]>().unwrap().to_vec())?;
    } else if path1.is_instance_of::<PyUnicode>()? && path2.is_instance_of::<PyUnicode>()? {
        pathstr1 = path1.extract::<String>().unwrap();
        pathstr2 = path2.extract::<String>().unwrap();
    } else {
        return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>("path1 and path2 must be either bytes or str"));
    }
    Ok(bazaar_dirstate::lt_by_dirs(&pathstr1, &pathstr2))
}

/// Helpers for the dirstate module.
#[pymodule]
fn _dirstate_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(lt_by_dirs)).unwrap();

    Ok(())
}
