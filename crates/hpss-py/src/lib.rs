//! Python bindings for breezy-hpss.
//!
//! Exposed to Python as `breezy._hpss_rs`. Functions are added here as the
//! smart protocol is ported from `breezy/bzr/smart/` into the `breezy-hpss`
//! crate.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyTuple};

use breezy_hpss::protocol;

/// Decode a smart-protocol tuple line into a tuple of byte strings.
///
/// Returns `None` for an empty or missing line.
#[pyfunction]
#[pyo3(name = "_decode_tuple")]
fn decode_tuple<'py>(
    py: Python<'py>,
    req_line: Option<&[u8]>,
) -> PyResult<Option<Bound<'py, PyTuple>>> {
    match protocol::decode_tuple(req_line) {
        Ok(None) => Ok(None),
        Ok(Some(fields)) => {
            let items: Vec<Bound<'py, PyBytes>> =
                fields.iter().map(|f| PyBytes::new(py, f)).collect();
            Ok(Some(PyTuple::new(py, items)?))
        }
        Err(protocol::ProtocolError::NotTerminated(line)) => Err(PyValueError::new_err(format!(
            "request {line:?} not terminated"
        ))),
    }
}

/// Encode a sequence of byte fields into a smart-protocol tuple line.
#[pyfunction]
#[pyo3(name = "_encode_tuple")]
fn encode_tuple<'py>(py: Python<'py>, args: Vec<Vec<u8>>) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &protocol::encode_tuple(args))
}

#[pymodule]
fn _hpss_rs(_py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(decode_tuple, m)?)?;
    m.add_function(wrap_pyfunction!(encode_tuple, m)?)?;
    Ok(())
}
