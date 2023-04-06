use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::path::{Path,PathBuf};
use pyo3::types::{PyBytes, PyUnicode};

use bazaar_dirstate;

fn extract_path(pyo: &PyAny) -> PyResult<PathBuf> {
    let stro: String;
    if pyo.is_instance_of::<PyBytes>()? {
        stro = String::from_utf8(pyo.extract::<&[u8]>().unwrap().to_vec())?;
    } else if pyo.is_instance_of::<PyUnicode>()? {
        stro = pyo.extract::<String>().unwrap();
    } else {
        return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>("path must be either bytes or str"));
    }
    Ok(PathBuf::from(stro))
}

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
    let path1 = extract_path(path1)?;
    let path2 = extract_path(path2)?;
    Ok(bazaar_dirstate::lt_by_dirs(&path1, &path2))
}

/// Return the index where to insert path into paths.
///
/// This uses the dirblock sorting. So all children in a directory come before
/// the children of children. For example::
///
///     a/
///       b/
///         c
///       d/
///         e
///       b-c
///       d-e
///     a-a
///     a=c
///
/// Will be sorted as::
///
///     a
///     a-a
///     a=c
///     a/b
///     a/b-c
///     a/d
///     a/d-e
///     a/b/c
///     a/d/e
///
/// Args:
///   paths: A list of paths to search through
///   path: A single path to insert
/// Returns: An offset where 'path' can be inserted.
/// See also: bisect.bisect_left

#[pyfunction]
fn bisect_path_left(paths: Vec<&PyAny>, path: &PyAny) -> PyResult<usize> {
    let path = extract_path(path)?;
    let paths = paths.iter().map(|x| extract_path(x).unwrap()).collect::<Vec<PathBuf>>();
    let offset = bazaar_dirstate::bisect_path_left(
        paths.iter().map(|x| x.as_path()).collect::<Vec<&Path>>().as_slice(),
        &path);
    Ok(offset)
}

/// Return the index where to insert path into paths.
///
/// This uses a path-wise comparison so we get::
///     a
///     a-b
///     a=b
///     a/b
/// Rather than::
///     a
///     a-b
///     a/b
///     a=b
///
/// Args:
///   paths: A list of paths to search through
///   path: A single path to insert
/// Returns: An offset where 'path' can be inserted.
/// See also: bisect.bisect_right
#[pyfunction]
fn bisect_path_right(paths: Vec<&PyAny>, path: &PyAny) -> PyResult<usize> {
    let path = extract_path(path)?;
    let paths = paths.iter().map(|x| extract_path(x).unwrap()).collect::<Vec<PathBuf>>();
    let offset = bazaar_dirstate::bisect_path_right(
        paths.iter().map(|x| x.as_path()).collect::<Vec<&Path>>().as_slice(),
        &path);
    Ok(offset)
}

#[pyfunction]
fn lt_path_by_dirblock(path1: &PyAny, path2: &PyAny) -> PyResult<bool> {
    let path1 = extract_path(path1)?;
    let path2 = extract_path(path2)?;
    Ok(bazaar_dirstate::lt_path_by_dirblock(&path1, &path2))
}

/// Helpers for the dirstate module.
#[pymodule]
fn _dirstate_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(lt_by_dirs))?;
    m.add_wrapped(wrap_pyfunction!(bisect_path_left))?;
    m.add_wrapped(wrap_pyfunction!(bisect_path_right))?;
    m.add_wrapped(wrap_pyfunction!(lt_path_by_dirblock))?;

    Ok(())
}
