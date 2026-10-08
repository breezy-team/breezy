//! Lock handles as Python lock results.

use pyo3::prelude::*;

/// The Python lock result for a lock `owner` took: the Python object's own
/// result if it is Python-backed, otherwise an instance of `class` (with
/// `token` for the write lock results) whose ``unlock`` is `owner.unlock`.
///
/// The Rust handle is detached: Python releases the lock through `owner`.
pub(crate) fn lock_result_to_py(
    py: Python<'_>,
    lock: Box<dyn breezy::lock::Lock>,
    owner: &Bound<'_, PyAny>,
    class: (&str, &str),
    token: Option<Option<&[u8]>>,
) -> PyResult<Py<PyAny>> {
    if let Some(result) = lock.python_object() {
        let result = result.clone_ref(py);
        lock.detach();
        return Ok(result);
    }
    lock.detach();
    let unlock = owner.getattr("unlock")?;
    let class = py.import(class.0)?.getattr(class.1)?;
    let result = match token {
        None => class.call1((unlock,))?,
        Some(token) => class.call1((unlock, token.map(|t| pyo3::types::PyBytes::new(py, t))))?,
    };
    Ok(result.unbind())
}
