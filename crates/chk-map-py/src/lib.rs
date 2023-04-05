use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::PyBytes;

use bazaar_chk_map;

#[pyfunction]
fn _search_key_16(py: Python, key: Vec<Vec<u8>>) -> Py<PyBytes>{
    let key = key.iter().map(|v| v.as_slice()).collect::<Vec<&[u8]>>();
    let ret = bazaar_chk_map::_search_key_16(key.as_slice());
    PyBytes::new(py, &ret).into_py(py)
}

#[pyfunction]
fn _search_key_255(py: Python, key: Vec<Vec<u8>>) -> Py<PyBytes> {
    let key = key.iter().map(|v| v.as_slice()).collect::<Vec<&[u8]>>();
    let ret = bazaar_chk_map::_search_key_255(key.as_slice());
    PyBytes::new(py, &ret).into_py(py)
}

#[pymodule]
fn _chk_map_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(_search_key_16))?;
    m.add_wrapped(wrap_pyfunction!(_search_key_255))?;
    Ok(())
}
