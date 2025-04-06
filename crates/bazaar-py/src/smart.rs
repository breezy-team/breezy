use bazaar::smart::protocol::{
    MESSAGE_VERSION_THREE, REQUEST_VERSION_THREE, REQUEST_VERSION_TWO, RESPONSE_VERSION_THREE,
    RESPONSE_VERSION_TWO,
};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

pub(crate) fn _smart_rs(py: Python) -> PyResult<Bound<PyModule>> {
    let m = PyModule::new_bound(py, "smart")?;
    m.add(
        "REQUEST_VERSION_TWO",
        PyBytes::new_bound(py, REQUEST_VERSION_TWO),
    )?;
    m.add(
        "REQUEST_VERSION_THREE",
        PyBytes::new_bound(py, REQUEST_VERSION_THREE),
    )?;
    m.add(
        "RESPONSE_VERSION_TWO",
        PyBytes::new_bound(py, RESPONSE_VERSION_TWO),
    )?;
    m.add(
        "RESPONSE_VERSION_THREE",
        PyBytes::new_bound(py, RESPONSE_VERSION_THREE),
    )?;
    m.add(
        "MESSAGE_VERSION_THREE",
        PyBytes::new_bound(py, MESSAGE_VERSION_THREE),
    )?;

    Ok(m)
}
