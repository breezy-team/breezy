//! Python bindings for [`Command`].
//!
//! [`PyCommand`] wraps a Python `Command` instance and implements the Rust
//! [`Command`] trait by delegating each method to the underlying Python object.
//! This is how the existing Python command base class and its subclasses are
//! grandfathered into the Rust command infrastructure.

use crate::command::Command;
use pyo3::prelude::*;

/// A wrapper around a Python command object.
///
/// This struct provides a Rust interface to Python `Command` instances,
/// implementing the [`Command`] trait. It allows Rust code to drive command
/// objects that are still implemented in Python.
pub struct PyCommand(Py<PyAny>);

impl PyCommand {
    /// Creates a new `PyCommand` wrapper around a Python command object.
    ///
    /// # Arguments
    ///
    /// * `o` - The Python command object to wrap.
    pub fn new(o: Py<PyAny>) -> Self {
        PyCommand(o)
    }
}

impl Command for PyCommand {
    fn name(&self) -> String {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("name")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn aliases(&self) -> Vec<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("aliases")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn takes_args(&self) -> Vec<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("takes_args")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn hidden(&self) -> bool {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("hidden")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn encoding_type(&self) -> String {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("encoding_type")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn invoked_as(&self) -> Option<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("invoked_as")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn plugin_name(&self) -> Option<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("plugin_name")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn help(&self) -> Option<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("help")
                .unwrap()
                .extract()
                .unwrap()
        })
    }
}
