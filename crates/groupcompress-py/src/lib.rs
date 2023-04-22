use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3::wrap_pyfunction;

#[pyfunction]
fn encode_base128_int(py: Python, value: u128) -> PyResult<&PyBytes> {
    let ret = bazaar_groupcompress::encode_base128_int(value);
    Ok(PyBytes::new(py, &ret))
}

#[pyfunction]
fn decode_base128_int(value: Vec<u8>) -> PyResult<(u128, usize)> {
    Ok(bazaar_groupcompress::decode_base128_int(&value))
}

#[pyfunction]
fn apply_delta(py: Python, basis: Vec<u8>, delta: Vec<u8>) -> PyResult<&PyBytes> {
    let ret = bazaar_groupcompress::apply_delta(&basis, &delta);
    if ret.is_err() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "Invalid delta",
        ));
    }
    Ok(PyBytes::new(py, &ret.unwrap()))
}

#[pyfunction]
fn decode_copy_instruction(data: Vec<u8>, cmd: u8, pos: usize) -> PyResult<(usize, usize, usize)> {
    let ret = bazaar_groupcompress::decode_copy_instruction(&data, cmd, pos);
    if ret.is_err() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "Invalid copy instruction",
        ));
    }
    let ret = ret.unwrap();

    Ok((ret.0, ret.1, ret.2))
}

#[pyfunction]
fn apply_delta_to_source(
    py: Python,
    source: &[u8],
    delta_start: usize,
    delta_end: usize,
) -> PyResult<PyObject> {
    let ret = bazaar_groupcompress::apply_delta_to_source(source, delta_start, delta_end);
    if ret.is_err() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "Invalid delta",
        ));
    }
    let ret = ret.unwrap();
    Ok(PyBytes::new(py, &ret).to_object(py))
}

#[pyfunction]
fn encode_copy_instruction(py: Python, offset: usize, length: usize) -> PyResult<PyObject> {
    let ret = bazaar_groupcompress::encode_copy_instruction(offset, length);
    if ret.is_err() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "Invalid copy instruction",
        ));
    }
    let ret = ret.unwrap();
    Ok(PyBytes::new(py, &ret).to_object(py))
}

#[pymodule]
fn _groupcompress_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(encode_base128_int))?;
    m.add_wrapped(wrap_pyfunction!(decode_base128_int))?;
    m.add_wrapped(wrap_pyfunction!(apply_delta))?;
    m.add_wrapped(wrap_pyfunction!(decode_copy_instruction))?;
    m.add_wrapped(wrap_pyfunction!(encode_copy_instruction))?;
    m.add_wrapped(wrap_pyfunction!(apply_delta_to_source))?;
    Ok(())
}
