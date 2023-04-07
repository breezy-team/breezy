use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::{PyList, PyBytes};

#[pyfunction]
fn chunks_to_lines(py_chunks: &PyAny) -> PyResult<PyObject> {
    let py_iter = py_chunks.iter()?;
    let mut chunks: Vec<Vec<u8>> = Vec::new();
    for py_chunk in py_iter {
        chunks.push(py_chunk?.extract::<Vec<u8>>()?);
    }
    let lines = breezy_osutils::chunks_to_lines(chunks.iter().map(|x| Ok::<&[u8], PyErr>(x.as_slice())));
    let py_lines = PyList::empty(py_iter.py());
    for line in lines {
        let line = line?;
        py_lines.append(PyBytes::new(py_iter.py(), &line))?;
    }
    Ok(py_lines.into_py(py_iter.py()))
}

#[pymodule]
fn _osutils_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines))?;
    Ok(())
}
