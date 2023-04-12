use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::path::{Path,PathBuf};
use pyo3_file::PyFileLikeObject;
use pyo3::types::{PyBytes, PyIterator, PyList};
use pyo3::exceptions::{PyTypeError, PyUnicodeDecodeError};
use std::collections::HashSet;
use std::iter::Iterator;
use std::ffi::OsString;
use std::os::unix::ffi::OsStringExt;
use memchr;

#[pyclass]
struct PyChunksToLinesIterator {
    chunk_iter: PyObject,
    tail: Option<Vec<u8>>,
}

#[pymethods]
impl PyChunksToLinesIterator {
    #[new]
    fn new(chunk_iter: PyObject) -> PyResult<Self> {
        Ok(PyChunksToLinesIterator { chunk_iter, tail: None })
    }

    fn __iter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __next__(&mut self) -> PyResult<Option<Py<PyAny>>> {
        Python::with_gil(move |py| {

            loop {
                if let Some(mut chunk) = self.tail.take() {
                    if let Some(newline) = memchr::memchr(b'\n', &chunk) {
                        if newline == chunk.len() - 1 {
                            assert!(!chunk.is_empty());
                            return Ok(Some(PyBytes::new(py, chunk.as_slice()).to_object(py)));
                        } else {
                            assert!(!chunk.is_empty());
                            self.tail = Some(chunk[newline + 1..].to_vec());
                            let bytes = PyBytes::new(py, &chunk[..=newline]);
                            return Ok(Some(bytes.to_object(py)));
                        }
                    } else {
                        if let Some(next_chunk) = self.chunk_iter.downcast::<PyIterator>(py)?.next() {
                            if let Err(e) = next_chunk {
                                return Err(e);
                            }
                            let next_chunk = next_chunk.unwrap();
                            let next_chunk = next_chunk.extract::<&[u8]>()?;
                            chunk.extend_from_slice(next_chunk);
                        } else {
                            assert!(!chunk.is_empty());
                            return Ok(Some(PyBytes::new(py, &chunk).to_object(py)));
                        }
                        if !chunk.is_empty() {
                            self.tail = Some(chunk);
                        }
                    }
                } else {
                    if let Some(next_chunk) = self.chunk_iter.downcast::<PyIterator>(py)?.next() {
                        if let Err(e) = next_chunk {
                            return Err(e);
                        }
                        let next_chunk_py = next_chunk.unwrap();
                        let next_chunk = next_chunk_py.extract::<&[u8]>()?;
                        if let Some(newline) = memchr::memchr(b'\n', &next_chunk) {
                            if newline == next_chunk.len() - 1 {
                                let line = next_chunk_py.downcast::<PyBytes>()?;
                                return Ok(Some(line.to_object(py)));
                            }
                        }

                        if !next_chunk.is_empty() {
                            self.tail = Some(next_chunk.to_vec());
                        }
                    } else {
                        return Ok(None);
                    }
                }
            }
        })
    }
}

fn extract_path(object: &PyAny) -> PyResult<PathBuf> {
    if let Ok(path) = object.extract::<Vec<u8>>() {
        Ok(PathBuf::from(OsString::from_vec(path)))
    } else if let Ok(path) = object.extract::<PathBuf>() {
        Ok(path)
    } else {
        Err(PyTypeError::new_err("path must be a string or bytes"))
    }
}

#[pyfunction]
fn chunks_to_lines(chunks: PyObject) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        let ret = PyList::empty(py);
        let chunk_iter = chunks.call_method0(py, "__iter__");
        if chunk_iter.is_err() {
            return Err(PyTypeError::new_err("chunks must be iterable"));
        }
        let iter = PyChunksToLinesIterator::new(chunk_iter?)?;
        let iter = iter.into_py(py);
        ret.call_method1("extend", (iter,))?;
        Ok(ret.into_py(py))
    })
}

#[pyfunction]
fn chunks_to_lines_iter(chunk_iter: PyObject) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        let iter = PyChunksToLinesIterator::new(chunk_iter)?;
        Ok(iter.into_py(py))
    })
}

#[pyfunction]
fn sha_file_by_name(object: &PyAny) -> PyResult<String> {
    let pathbuf = extract_path(object)?;
    let digest = breezy_osutils::sha::sha_file_by_name(pathbuf.as_path()).map_err(PyErr::from)?;
    Ok(digest)
}

#[pyfunction]
fn sha_string(string: &[u8]) -> PyResult<String> {
    Ok(breezy_osutils::sha::sha_string(string))
}

#[pyfunction]
fn sha_strings(strings: &PyAny) -> PyResult<String> {
    let iter = strings.iter()?;
    Ok(breezy_osutils::sha::sha_strings(iter.map(|x| x.unwrap().extract::<Vec<u8>>().unwrap())))
}

#[pyfunction]
fn sha_file(file: PyObject) -> PyResult<String> {
    let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
    let digest = breezy_osutils::sha::sha_file(&mut file).map_err(PyErr::from)?;
    Ok(digest)
}

#[pyfunction]
fn size_sha_file(file: PyObject) -> PyResult<(usize, String)> {
    let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
    let (size, digest) = breezy_osutils::sha::size_sha_file(&mut file).map_err(PyErr::from)?;
    Ok((size, digest))
}

#[pyfunction]
fn normalized_filename(py: Python, filename: &PyAny) -> PyResult<(PathBuf, bool)> {
    let filename = extract_path(&filename)?;
    if let Some(filename) = breezy_osutils::path::normalized_filename(filename.as_path()) {
        Ok(filename)
    } else {
        let raw = PyBytes::new(py, &filename.as_os_str().to_os_string().into_vec());
        Err(PyUnicodeDecodeError::new_err(("utf-8", raw.to_object(py), 0, 0, "Invalid filename")))
    }
}

#[pyfunction]
fn _inaccessible_normalized_filename(py: Python, filename: &PyAny) -> PyResult<(PathBuf, bool)> {
    eprintln!("filename: {:?}", filename);
    let filename = extract_path(&filename)?;
    eprintln!("filename: {:?}", filename);
    if let Some(filename) = breezy_osutils::path::inaccessible_normalized_filename(filename.as_path()) {
        Ok(filename)
    } else {
        let raw = PyBytes::new(py, &filename.as_os_str().to_os_string().into_vec());
        Err(PyUnicodeDecodeError::new_err(("utf-8", raw.to_object(py), 0, 0, "Invalid filename")))
    }
}

#[pyfunction]
fn _accessible_normalized_filename(py: Python, filename: &PyAny) -> PyResult<(PathBuf, bool)> {
    let filename= extract_path(&filename)?;
    if let Some(filename) = breezy_osutils::path::accessible_normalized_filename(filename.as_path()) {
        Ok(filename)
    } else {
        let raw = PyBytes::new(py, &filename.as_os_str().to_os_string().into_vec());
        Err(PyUnicodeDecodeError::new_err(("utf-8", raw.to_object(py), 0, 0, "Invalid filename")))
    }
}

#[pyfunction]
fn normalizes_filenames() -> bool {
    breezy_osutils::path::normalizes_filenames()
}

#[pyfunction]
fn is_inside(path: &PyAny, parent: &PyAny) -> PyResult<bool> {
    let path = extract_path(path)?;
    let parent = extract_path(parent)?;
    Ok(breezy_osutils::path::is_inside(path.as_path(), parent.as_path()))
}

#[pyfunction]
fn is_inside_any(dir_list: &PyAny, path: &PyAny) -> PyResult<bool> {
    let path = extract_path(path)?;
    let mut c_dir_list: Vec<PathBuf> = Vec::new();
    for dir in dir_list.iter()? {
        c_dir_list.push(extract_path(dir?)?);
    }
    Ok(breezy_osutils::path::is_inside_any(&c_dir_list.iter().map(|p| p.as_path()).collect::<Vec<&Path>>(), path.as_path()))
}

#[pyfunction]
fn is_inside_or_parent_of_any(dir_list: &PyAny, path: &PyAny) -> PyResult<bool> {
    let path = extract_path(path)?;
    let mut c_dir_list: Vec<PathBuf> = Vec::new();
    for dir in dir_list.iter()? {
        c_dir_list.push(extract_path(dir?)?);
    }
    Ok(breezy_osutils::path::is_inside_or_parent_of_any(&c_dir_list.iter().map(|p| p.as_path()).collect::<Vec<&Path>>(), path.as_path()))
}

#[pyfunction]
pub fn minimum_path_selection(paths: &PyAny) -> PyResult<HashSet<String>> {
    let mut path_set: HashSet<PathBuf> = HashSet::new();
    for path in paths.iter()? {
        path_set.insert(extract_path(path?)?);
    }
    let paths = breezy_osutils::path::minimum_path_selection(path_set.iter().map(|p| p.as_path()).collect::<HashSet<&Path>>());
    Ok(paths.iter().map(|x| x.to_string_lossy().to_string()).collect())
}

#[pyfunction]
fn set_or_unset_env(key: &str, value: Option<&str>) -> PyResult<Py<PyAny>> {
    // Note that we're not calling out to breey_osutils::set_or_unset_env here, because it doesn't
    // change the environment in Python.
    Python::with_gil(|py| {
        let os = py.import("os")?;
        let environ = os.getattr("environ")?;
        let old = environ.call_method1("get", (key, py.None()))?;
        if let Some(value) = value {
            environ.set_item(key, value)?;
        } else {
            if old.is_none() {
                return Ok(py.None());
            }
            environ.del_item(key)?;
        }
        Ok(old.into_py(py))
    })
}

#[pyfunction]
fn legal_path(path: &PyAny) -> PyResult<bool> {
    let path = extract_path(path)?;
    Ok(breezy_osutils::path::legal_path(path.as_path()))
}

#[pymodule]
fn _osutils_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines))?;
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines_iter))?;
    m.add_wrapped(wrap_pyfunction!(sha_file_by_name))?;
    m.add_wrapped(wrap_pyfunction!(sha_string))?;
    m.add_wrapped(wrap_pyfunction!(sha_strings))?;
    m.add_wrapped(wrap_pyfunction!(sha_file))?;
    m.add_wrapped(wrap_pyfunction!(size_sha_file))?;
    m.add_wrapped(wrap_pyfunction!(normalized_filename))?;
    m.add_wrapped(wrap_pyfunction!(_inaccessible_normalized_filename))?;
    m.add_wrapped(wrap_pyfunction!(_accessible_normalized_filename))?;
    m.add_wrapped(wrap_pyfunction!(normalizes_filenames))?;
    m.add_wrapped(wrap_pyfunction!(is_inside))?;
    m.add_wrapped(wrap_pyfunction!(is_inside_any))?;
    m.add_wrapped(wrap_pyfunction!(is_inside_or_parent_of_any))?;
    m.add_wrapped(wrap_pyfunction!(minimum_path_selection))?;
    m.add_wrapped(wrap_pyfunction!(set_or_unset_env))?;
    m.add_wrapped(wrap_pyfunction!(legal_path))?;
    Ok(())
}
