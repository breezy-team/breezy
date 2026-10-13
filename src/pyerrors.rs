//! breezy's Python exceptions for errors that started in Rust.

use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Build an instance of `module.class` the way ``BzrError.__init__`` does,
/// bypassing the class's own constructor, whose arguments a Rust error
/// does not have.
fn build(
    py: Python<'_>,
    module: &str,
    class: &str,
    init: impl FnOnce(&Bound<'_, PyAny>, &Bound<'_, PyAny>) -> PyResult<()>,
) -> PyErr {
    let result = (|| -> PyResult<PyErr> {
        let class = py.import(module)?.getattr(class)?;
        let exc = class.call_method1("__new__", (&class,))?;
        init(&py.import("breezy.errors")?.getattr("BzrError")?, &exc)?;
        Ok(PyErr::from_value(exc))
    })();
    // A failure to build the exception is raised in its place.
    result.unwrap_or_else(|e| e)
}

/// The breezy exception `module.class` with `message` as its text.
pub fn bzr_error(py: Python<'_>, module: &str, class: &str, message: &str) -> PyErr {
    build(py, module, class, |bzr_error, exc| {
        bzr_error.call_method1("__init__", (exc, message))?;
        Ok(())
    })
}

/// The breezy exception `module.class` with the attributes `fields`, which
/// its format string expands.
pub fn bzr_error_with(py: Python<'_>, module: &str, class: &str, fields: &[(&str, &str)]) -> PyErr {
    build(py, module, class, |bzr_error, exc| {
        let kwargs = PyDict::new(py);
        for (key, value) in fields {
            kwargs.set_item(*key, *value)?;
        }
        bzr_error.call_method("__init__", (exc,), Some(&kwargs))?;
        Ok(())
    })
}

/// ``breezy.errors.UnsupportedOperation`` for an operation a Rust
/// implementation does not support.
pub fn unsupported_operation(py: Python<'_>, message: &str) -> PyErr {
    bzr_error(
        py,
        "breezy.errors",
        "UnsupportedOperation",
        &format!("Unsupported operation: {message}"),
    )
}
