use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::PyBytes;

use bazaar_chk_map;

#[pyfunction]
fn _search_key_16(py: Python, key: Vec<Vec<u8>>) -> Py<PyBytes>{
    let key = key.iter().map(|v| v.as_slice()).collect::<Vec<&[u8]>>();
    let ret = bazaar_chk_map::search_key_16(key.as_slice());
    PyBytes::new(py, &ret).into_py(py)
}

#[pyfunction]
fn _search_key_255(py: Python, key: Vec<Vec<u8>>) -> Py<PyBytes> {
    let key = key.iter().map(|v| v.as_slice()).collect::<Vec<&[u8]>>();
    let ret = bazaar_chk_map::search_key_255(key.as_slice());
    PyBytes::new(py, &ret).into_py(py)
}

#[pyfunction]
fn _bytes_to_text_key(py: Python, key: Vec<u8>) -> PyResult<(&PyBytes, &PyBytes)> {
    let ret = bazaar_chk_map::bytes_to_text_key(key.as_slice());
    if ret.is_err() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>("Invalid key"));
    }
    let ret = ret.unwrap();
    Ok((PyBytes::new(py, &ret.0), PyBytes::new(py, &ret.1)))
}

#[pymodule]
fn _chk_map_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(_search_key_16))?;
    m.add_wrapped(wrap_pyfunction!(_search_key_255))?;
    m.add_wrapped(wrap_pyfunction!(_bytes_to_text_key))?;
    Ok(())
}
