use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Create a new file id suffix that is reasonably unique.
///
/// On the first call we combine the current time with 64 bits of randomness to
/// give a highly probably globally unique number. Then each call in the same
/// process adds 1 to a serial number we append to that unique value.
#[pyfunction]
fn _next_id_suffix(py: Python, suffix: Option<&str>) -> PyObject {
    PyBytes::new(py, &bazaar::gen_ids::next_id_suffix(suffix)).into_py(py)
}

/// Return new file id for the basename 'name'.
///
/// The uniqueness is supplied from _next_id_suffix.
#[pyfunction]
fn gen_file_id(py: Python, name: &str) -> PyObject {
    PyBytes::new(py, &bazaar::gen_ids::gen_file_id(name)).into_py(py)
}

/// Return a new tree-root file id.
#[pyfunction]
fn gen_root_id(py: Python) -> PyObject {
    PyBytes::new(py, &bazaar::gen_ids::gen_root_id()).into_py(py)
}

/// Return new revision-id.
///
/// Args:
///   username: The username of the committer, in the format returned by
///      config.username().  This is typically a real name, followed by an
///      email address. If found, we will use just the email address portion.
///      Otherwise we flatten the real name, and use that.
/// Returns: A new revision id.
#[pyfunction]
fn gen_revision_id(py: Python, username: &str, timestamp: Option<PyObject>) -> PyResult<PyObject> {
    let timestamp = match timestamp {
        Some(timestamp) => {
            if let Ok(timestamp) = timestamp.extract::<f64>(py) {
                Some(timestamp as u64)
            } else if let Ok(timestamp) = timestamp.extract::<u64>(py) {
                Some(timestamp)
            } else {
                return Err(PyTypeError::new_err(format!(
                    "timestamp must be a float or an int",
                )));
            }
        }
        None => None,
    };
    Ok(PyBytes::new(py, &bazaar::gen_ids::gen_revision_id(username, timestamp)).into_py(py))
}

#[pymodule]
fn _bzr_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(_next_id_suffix))?;
    m.add_wrapped(wrap_pyfunction!(gen_file_id))?;
    m.add_wrapped(wrap_pyfunction!(gen_root_id))?;
    m.add_wrapped(wrap_pyfunction!(gen_revision_id))?;
    Ok(())
}
