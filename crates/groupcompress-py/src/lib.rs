use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::PyBytes;

use bazaar_groupcompress;

#[pyfunction]
fn encode_base128_int(py: Python, value: u128) -> PyResult<&PyBytes> {
    let ret = bazaar_groupcompress::encode_base128_int(value);
    Ok(PyBytes::new(py, &ret))
}

#[pyfunction]
fn decode_base128_int(value: Vec<u8>) -> PyResult<(u128, usize)> {
    Ok(bazaar_groupcompress::decode_base128_int(&value))
}

#[pymodule]
fn _groupcompress_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(encode_base128_int))?;
    m.add_wrapped(wrap_pyfunction!(decode_base128_int))?;
    Ok(())
}
