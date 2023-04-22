use pyo3::exceptions::{PyTypeError, PyValueError};
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
                return Err(PyTypeError::new_err(
                    "timestamp must be a float or an int".to_string(),
                ));
            }
        }
        None => None,
    };
    Ok(PyBytes::new(py, &bazaar::gen_ids::gen_revision_id(username, timestamp)).into_py(py))
}

#[pyfunction]
fn normalize_pattern(pattern: &str) -> String {
    bazaar::globbing::normalize_pattern(pattern)
}

#[pyclass]
struct Replacer {
    replacer: bazaar::globbing::Replacer,
}

#[pymethods]
impl Replacer {
    #[new]
    fn new(source: Option<&Self>) -> Self {
        Self {
            replacer: bazaar::globbing::Replacer::new(source.map(|p| &p.replacer)),
        }
    }

    /// Add a pattern and replacement.
    ///
    /// The pattern must not contain capturing groups.
    /// The replacement might be either a string template in which \& will be
    /// replaced with the match, or a function that will get the matching text
    /// as argument. It does not get match object, because capturing is
    /// forbidden anyway.
    fn add(&mut self, py: Python, pattern: &str, func: PyObject) -> PyResult<()> {
        if let Ok(func) = func.extract::<String>(py) {
            self.replacer
                .add(pattern, bazaar::globbing::Replacement::String(func));
            Ok(())
        } else {
            let callable = Box::new(move |t: String| -> String {
                Python::with_gil(|py| match func.call1(py, (t,)) {
                    Ok(result) => result.extract::<String>(py).unwrap(),
                    Err(e) => {
                        e.restore(py);
                        String::new()
                    }
                })
            });
            self.replacer
                .add(pattern, bazaar::globbing::Replacement::Closure(callable));
            Ok(())
        }
    }

    /// Add all patterns from another replacer.
    ///
    /// All patterns and replacements from replacer are appended to the ones
    /// already defined.
    fn add_replacer(&mut self, replacer: &Self) {
        self.replacer.add_replacer(&replacer.replacer)
    }

    fn __call__(&mut self, py: Python, text: &str) -> PyResult<String> {
        let ret = self
            .replacer
            .replace(text)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        if PyErr::occurred(py) {
            Err(PyErr::fetch(py))
        } else {
            Ok(ret)
        }
    }
}

#[pymodule]
fn _bzr_rs(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(_next_id_suffix))?;
    m.add_wrapped(wrap_pyfunction!(gen_file_id))?;
    m.add_wrapped(wrap_pyfunction!(gen_root_id))?;
    m.add_wrapped(wrap_pyfunction!(gen_revision_id))?;
    let m_globbing = PyModule::new(py, "globbing")?;
    m_globbing.add_wrapped(wrap_pyfunction!(normalize_pattern))?;
    m_globbing.add_class::<Replacer>()?;
    m.add_submodule(m_globbing)?;
    Ok(())
}
