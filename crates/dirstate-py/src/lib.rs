use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::path::{Path,PathBuf};
use pyo3::types::{PyBytes, PyUnicode, PyDict, PyList, PyTuple, PyString};
use pyo3::exceptions::PyTypeError;
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

#[pyfunction]
fn bisect_dirblock(
    py: Python,
    dirblocks: &PyList,
    dirname: PyObject,
    lo: Option<usize>,
    hi: Option<usize>,
    cache: Option<&PyDict>,
) -> PyResult<usize> {
    fn split_object(py: Python, obj: Py<PyAny>) -> PyResult<Vec<PathBuf>> {
        if let Ok(py_str) = obj.extract::<&PyString>(py) {
            Ok(py_str
                .to_str()?
                .split('/')
                .map(PathBuf::from)
                .collect::<Vec<_>>())
        } else if let Ok(py_bytes) = obj.extract::<&PyBytes>(py) {
            Ok(py_bytes
                .as_bytes()
                .split(|&byte| byte == b'/')
                .map(|s| PathBuf::from(String::from_utf8_lossy(s).to_string()))
                .collect::<Vec<_>>())
        } else {
            Err(PyTypeError::new_err("Not a PyBytes or PyString"))
        }
    }

    let hi = hi.unwrap_or(dirblocks.len());
    let cache = cache.unwrap_or_else(|| PyDict::new(py));

    let dirname_split = match cache.get_item(&dirname) {
        Some(item) => item.extract::<Vec<PathBuf>>()?,
        None => {
            let split = split_object(py, dirname.to_object(py))?;
            cache.set_item(dirname.clone(), split.clone())?;
            split
        }
    };

    let mut lo = lo.unwrap_or(0);
    let mut hi = hi;

    while lo < hi {
        let mid = (lo + hi) / 2;
        let dirblock = dirblocks.get_item(mid)?.downcast::<PyTuple>()?;
        let cur = dirblock.get_item(0)?;

        let cur_split = match cache.get_item(&cur) {
            Some(item) => item.extract::<Vec<PathBuf>>()?,
            None => {
                let split = split_object(py, cur.into_py(py))?;
                cache.set_item(cur.clone(), split.clone())?;
                split
            }
        };

        if cur_split < dirname_split {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    Ok(lo)
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

#[pyfunction]
fn pack_stat(stat_result: &PyAny) -> PyBytes {
    let size = stat_result.getattr("st_size")?.extract::<u64>().unwrap();
    let mtime = stat_result.getattr("st_mtime")?.extract::<u64>().unwrap();
    let ctime = stat_result.getattr("st_ctime")?.extract::<u64>().unwrap();
    let dev = stat_result.getattr("st_dev")?.extract::<u64>().unwrap();
    let ino = stat_result.getattr("st_ino")?.extract::<u64>().unwrap();
    let mode = stat_result.getattr("st_mode")?.extract::<u32>().unwrap();
    PyBytes::new(stat_result.py(), &bazaar_dirstate::pack_stat(size, mtime, ctime, dev, ino, mode))
}

/// Helpers for the dirstate module.
#[pymodule]
fn _dirstate_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(lt_by_dirs))?;
    m.add_wrapped(wrap_pyfunction!(bisect_path_left))?;
    m.add_wrapped(wrap_pyfunction!(bisect_path_right))?;
    m.add_wrapped(wrap_pyfunction!(lt_path_by_dirblock))?;
    m.add_wrapped(wrap_pyfunction!(bisect_dirblock))?;
    m.add_wrapped(wrap_pyfunction!(DefaultSHA1Provider))?;

    Ok(())
}
