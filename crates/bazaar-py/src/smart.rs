use bazaar::smart::protocol::{
    MESSAGE_VERSION_THREE, REQUEST_VERSION_THREE, REQUEST_VERSION_TWO, RESPONSE_VERSION_THREE,
    RESPONSE_VERSION_TWO,
};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

pub(crate) fn _smart_rs(py: Python) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "smart")?;
    m.add("REQUEST_VERSION_TWO", PyBytes::new(py, REQUEST_VERSION_TWO))?;
    m.add(
        "REQUEST_VERSION_THREE",
        PyBytes::new(py, REQUEST_VERSION_THREE),
    )?;
    m.add(
        "RESPONSE_VERSION_TWO",
        PyBytes::new(py, RESPONSE_VERSION_TWO),
    )?;
    m.add(
        "RESPONSE_VERSION_THREE",
        PyBytes::new(py, RESPONSE_VERSION_THREE),
    )?;
    m.add(
        "MESSAGE_VERSION_THREE",
        PyBytes::new(py, MESSAGE_VERSION_THREE),
    )?;

    Ok(m)
}
