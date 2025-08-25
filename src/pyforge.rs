use crate::forge::Forge;
use pyo3::prelude::*;

/// A wrapper around a Python forge object.
///
/// This struct provides a Rust interface to Python forge objects, implementing
/// the `Forge` trait. It allows Rust code to interact with Python forge
/// implementations.
pub struct PyForge(PyObject);

impl Forge for PyForge {}
