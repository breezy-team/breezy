use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::path::{Path,PathBuf};
use pyo3::types::{PyBytes, PyUnicode};
use std::os::unix::fs::PermissionsExt;

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

// TODO(jelmer): Move this into a more central place?
#[pyclass]
struct StatResult {
    metadata: std::fs::Metadata,
}

#[pymethods]
impl StatResult {
    #[getter]
    fn st_size(&self) -> PyResult<u64> {
        Ok(self.metadata.len())
    }

    #[getter]
    fn st_mtime(&self) -> PyResult<u64> {
        let modified = self.metadata.modified().map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e))?;
        let since_epoch = modified.duration_since(std::time::UNIX_EPOCH).map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;
        Ok(since_epoch.as_secs())
    }

    #[getter]
    fn st_ctime(&self) -> PyResult<u64> {
        let created = self.metadata.created().map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e))?;
        let since_epoch = created.duration_since(std::time::UNIX_EPOCH).map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;
        Ok(since_epoch.as_secs())
    }

    #[getter]
    fn st_mode(&self) -> PyResult<u32> {
        Ok(self.metadata.permissions().mode())
    }
}

#[pyclass]
struct SHA1Provider {
    provider: Box<dyn bazaar_dirstate::SHA1Provider>,
}

#[pymethods]
impl SHA1Provider {
    fn sha1(&mut self, py: Python, path: &PyAny) -> PyResult<PyObject> {
        let path = extract_path(path)?;
        let sha1 = self.provider.sha1(&path).map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e))?;
        Ok(PyBytes::new(py, sha1.as_bytes()).to_object(py))
    }

    fn stat_and_sha1(&mut self, py: Python, path: &PyAny) -> PyResult<(PyObject, PyObject)> {
        let path = extract_path(path)?;
        let (md, sha1) = self.provider.stat_and_sha1(&path)?;
        let pmd = StatResult { metadata: md };
        Ok((pmd.into_py(py), PyBytes::new(py, sha1.as_bytes()).to_object(py)))
    }
}

#[pyfunction]
fn DefaultSHA1Provider() -> PyResult<SHA1Provider> {
    Ok(SHA1Provider {
        provider: Box::new(bazaar_dirstate::DefaultSHA1Provider::new()),
    })
}

/// Helpers for the dirstate module.
#[pymodule]
fn _dirstate_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(lt_by_dirs))?;
    m.add_wrapped(wrap_pyfunction!(bisect_path_left))?;
    m.add_wrapped(wrap_pyfunction!(bisect_path_right))?;
    m.add_wrapped(wrap_pyfunction!(lt_path_by_dirblock))?;
    m.add_wrapped(wrap_pyfunction!(DefaultSHA1Provider))?;

    Ok(())
}
