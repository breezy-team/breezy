use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::path::{PathBuf, Path};
use pyo3_file::PyFileLikeObject;
use pyo3::types::{PyBytes, PyIterator, PyList};
use pyo3::exceptions::PyTypeError;
use std::iter::Iterator;
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
    let pathbuf: PathBuf;
    // Convert object to PathBuf, allowing it to either be PyString or PyBytes
    if let Ok(path) = object.extract::<&PyBytes>() {
        pathbuf = PathBuf::from(path.to_string());
    } else if let Ok(path) = object.extract::<PathBuf>() {
        pathbuf = path;
    } else {
        return Err(PyTypeError::new_err("path must be a string or bytes"));
    }
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

#[pymodule]
fn _osutils_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines))?;
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines_iter))?;
    m.add_wrapped(wrap_pyfunction!(sha_file_by_name))?;
    m.add_wrapped(wrap_pyfunction!(sha_string))?;
    m.add_wrapped(wrap_pyfunction!(sha_strings))?;
    m.add_wrapped(wrap_pyfunction!(sha_file))?;
    m.add_wrapped(wrap_pyfunction!(size_sha_file))?;
    Ok(())
}
