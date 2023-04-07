use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
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

#[pymodule]
fn _osutils_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines))?;
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines_iter))?;
    Ok(())
}
