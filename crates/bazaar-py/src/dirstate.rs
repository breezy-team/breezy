#![allow(non_snake_case)]

use bazaar::FileId;
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyString, PyTuple};
use pyo3::wrap_pyfunction;
use std::ffi::OsString;
use std::os::unix::ffi::OsStringExt;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};

// TODO(jelmer): Shared pyo3 utils?
fn extract_path(object: &PyAny) -> PyResult<PathBuf> {
    if let Ok(path) = object.extract::<Vec<u8>>() {
        Ok(PathBuf::from(OsString::from_vec(path)))
    } else if let Ok(path) = object.extract::<PathBuf>() {
        Ok(path)
    } else {
        Err(PyTypeError::new_err("path must be a string or bytes"))
    }
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
    Ok(bazaar::dirstate::lt_by_dirs(&path1, &path2))
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
    let paths = paths
        .iter()
        .map(|x| extract_path(x).unwrap())
        .collect::<Vec<PathBuf>>();
    let offset = bazaar::dirstate::bisect_path_left(
        paths
            .iter()
            .map(|x| x.as_path())
            .collect::<Vec<&Path>>()
            .as_slice(),
        &path,
    );
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
    let paths = paths
        .iter()
        .map(|x| extract_path(x).unwrap())
        .collect::<Vec<PathBuf>>();
    let offset = bazaar::dirstate::bisect_path_right(
        paths
            .iter()
            .map(|x| x.as_path())
            .collect::<Vec<&Path>>()
            .as_slice(),
        &path,
    );
    Ok(offset)
}

#[pyfunction]
fn lt_path_by_dirblock(path1: &PyAny, path2: &PyAny) -> PyResult<bool> {
    let path1 = extract_path(path1)?;
    let path2 = extract_path(path2)?;
    Ok(bazaar::dirstate::lt_path_by_dirblock(&path1, &path2))
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

    let dirname_split = match cache.get_item(&dirname)? {
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

        let cur_split = match cache.get_item(cur)? {
            Some(item) => item.extract::<Vec<PathBuf>>()?,
            None => {
                let split = split_object(py, cur.into_py(py))?;
                cache.set_item(cur, split.clone())?;
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
        let modified = self
            .metadata
            .modified()
            .map_err(PyErr::new::<pyo3::exceptions::PyOSError, _>)?;
        let since_epoch = modified
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;
        Ok(since_epoch.as_secs())
    }

    #[getter]
    fn st_ctime(&self) -> PyResult<u64> {
        let created = self
            .metadata
            .created()
            .map_err(PyErr::new::<pyo3::exceptions::PyOSError, _>)?;
        let since_epoch = created
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;
        Ok(since_epoch.as_secs())
    }

    #[getter]
    fn st_mode(&self) -> PyResult<u32> {
        Ok(self.metadata.permissions().mode())
    }

    #[cfg(unix)]
    #[getter]
    fn st_dev(&self) -> PyResult<u64> {
        Ok(self.metadata.dev())
    }

    #[cfg(unix)]
    #[getter]
    fn st_ino(&self) -> PyResult<u64> {
        Ok(self.metadata.ino())
    }
}

#[pyclass]
struct SHA1Provider {
    provider: Box<dyn bazaar::dirstate::SHA1Provider>,
}

#[pymethods]
impl SHA1Provider {
    fn sha1(&mut self, py: Python, path: &PyAny) -> PyResult<PyObject> {
        let path = extract_path(path)?;
        let sha1 = self
            .provider
            .sha1(&path)
            .map_err(PyErr::new::<pyo3::exceptions::PyOSError, _>)?;
        Ok(PyBytes::new(py, sha1.as_bytes()).to_object(py))
    }

    fn stat_and_sha1(&mut self, py: Python, path: &PyAny) -> PyResult<(PyObject, PyObject)> {
        let path = extract_path(path)?;
        let (md, sha1) = self.provider.stat_and_sha1(&path)?;
        let pmd = StatResult { metadata: md };
        Ok((
            pmd.into_py(py),
            PyBytes::new(py, sha1.as_bytes()).to_object(py),
        ))
    }
}

#[pyfunction]
fn DefaultSHA1Provider() -> PyResult<SHA1Provider> {
    Ok(SHA1Provider {
        provider: Box::new(bazaar::dirstate::DefaultSHA1Provider::new()),
    })
}

fn extract_fs_time(obj: &PyAny) -> PyResult<u64> {
    if let Ok(u) = obj.extract::<u64>() {
        Ok(u)
    } else if let Ok(u) = obj.extract::<f64>() {
        Ok(u as u64)
    } else {
        Err(PyTypeError::new_err("Not a float or int"))
    }
}

#[pyfunction]
fn pack_stat(stat_result: &PyAny) -> PyResult<PyObject> {
    let size = stat_result.getattr("st_size")?.extract::<u64>()?;
    let mtime = extract_fs_time(stat_result.getattr("st_mtime")?)?;
    let ctime = extract_fs_time(stat_result.getattr("st_ctime")?)?;
    let dev = stat_result.getattr("st_dev")?.extract::<u64>()?;
    let ino = stat_result.getattr("st_ino")?.extract::<u64>()?;
    let mode = stat_result.getattr("st_mode")?.extract::<u32>()?;
    let s = bazaar::dirstate::pack_stat(size, mtime, ctime, dev, ino, mode);
    Ok(PyBytes::new(stat_result.py(), s.as_bytes()).to_object(stat_result.py()))
}

#[pyfunction]
fn fields_per_entry(num_present_parents: usize) -> usize {
    bazaar::dirstate::fields_per_entry(num_present_parents)
}

#[pyfunction]
fn get_ghosts_line(py: Python, ghost_ids: Vec<&[u8]>) -> PyResult<PyObject> {
    let bs = bazaar::dirstate::get_ghosts_line(ghost_ids.as_slice());
    Ok(PyBytes::new(py, bs.as_slice()).to_object(py))
}

#[pyfunction]
fn get_parents_line(py: Python, parent_ids: Vec<&[u8]>) -> PyResult<PyObject> {
    let bs = bazaar::dirstate::get_parents_line(parent_ids.as_slice());
    Ok(PyBytes::new(py, bs.as_slice()).to_object(py))
}

#[pyclass]
struct IdIndex(bazaar::dirstate::IdIndex);

#[pymethods]
impl IdIndex {
    #[new]
    fn new() -> Self {
        IdIndex(bazaar::dirstate::IdIndex::new())
    }

    fn add(&mut self, py: Python, entry: PyObject) -> PyResult<()> {
        if entry.as_ref(py).len()? != 3 {
            return Err(PyTypeError::new_err("Not a tuple of 3 items"));
        }
        let entry = (
            entry.as_ref(py).get_item(0)?.extract::<&[u8]>()?,
            entry.as_ref(py).get_item(1)?.extract::<&[u8]>()?,
            entry.as_ref(py).get_item(2)?.extract::<FileId>()?,
        );

        self.0.add((entry.0, entry.1, &entry.2));
        Ok(())
    }

    fn remove(&mut self, py: Python, entry: PyObject) -> PyResult<()> {
        if entry.as_ref(py).len()? != 3 {
            return Err(PyTypeError::new_err("Not a tuple of 3 items"));
        }
        let entry = (
            entry.as_ref(py).get_item(0)?.extract::<&[u8]>()?,
            entry.as_ref(py).get_item(1)?.extract::<&[u8]>()?,
            entry.as_ref(py).get_item(2)?.extract::<FileId>()?,
        );
        self.0.remove((entry.0, entry.1, &entry.2));
        Ok(())
    }

    fn get(&self, py: Python, file_id: FileId) -> PyResult<Vec<(PyObject, PyObject, PyObject)>> {
        let ret = self.0.get(&file_id);
        Ok(ret
            .iter()
            .map(|(a, b, c)| {
                (
                    PyBytes::new(py, a).to_object(py),
                    PyBytes::new(py, b).to_object(py),
                    c.to_object(py),
                )
            })
            .collect())
    }

    fn iter_all(&self, py: Python) -> PyResult<Vec<(PyObject, PyObject, PyObject)>> {
        let ret = self.0.iter_all();
        Ok(ret
            .map(|(a, b, c)| {
                (
                    PyBytes::new(py, a).to_object(py),
                    PyBytes::new(py, b).to_object(py),
                    c.to_object(py),
                )
            })
            .collect())
    }

    fn file_ids(&self, py: Python) -> Vec<PyObject> {
        self.0.file_ids().map(|x| x.to_object(py)).collect()
    }
}

#[pyfunction]
fn inv_entry_to_details(
    py: Python,
    e: &crate::inventory::InventoryEntry,
) -> (PyObject, PyObject, u64, bool, PyObject) {
    let ret = bazaar::dirstate::inv_entry_to_details(&e.0);

    (
        PyBytes::new(py, &[ret.0]).to_object(py),
        PyBytes::new(py, ret.1.as_slice()).to_object(py),
        ret.2,
        ret.3,
        PyBytes::new(py, ret.4.as_slice()).to_object(py),
    )
}

#[pyfunction]
fn get_output_lines(py: Python, lines: Vec<&[u8]>) -> Vec<PyObject> {
    bazaar::dirstate::get_output_lines(lines)
        .into_iter()
        .map(|x| PyBytes::new(py, x.as_slice()).to_object(py))
        .collect()
}

/// Helpers for the dirstate module.
pub fn _dirstate_rs(py: Python) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "dirstate")?;
    m.add_wrapped(wrap_pyfunction!(lt_by_dirs))?;
    m.add_wrapped(wrap_pyfunction!(bisect_path_left))?;
    m.add_wrapped(wrap_pyfunction!(bisect_path_right))?;
    m.add_wrapped(wrap_pyfunction!(lt_path_by_dirblock))?;
    m.add_wrapped(wrap_pyfunction!(bisect_dirblock))?;
    m.add_wrapped(wrap_pyfunction!(DefaultSHA1Provider))?;
    m.add_wrapped(wrap_pyfunction!(pack_stat))?;
    m.add_wrapped(wrap_pyfunction!(fields_per_entry))?;
    m.add_wrapped(wrap_pyfunction!(get_ghosts_line))?;
    m.add_wrapped(wrap_pyfunction!(get_parents_line))?;
    m.add_class::<IdIndex>()?;
    m.add_wrapped(wrap_pyfunction!(inv_entry_to_details))?;
    m.add_wrapped(wrap_pyfunction!(get_output_lines))?;

    Ok(m)
}
