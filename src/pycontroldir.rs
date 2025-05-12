use crate::controldir::{ControlDir, Prober};
use pyo3::prelude::*;

/// A wrapper around a Python control directory object.
///
/// This struct provides a Rust interface to Python control directory objects,
/// implementing the `ControlDir` trait. It allows Rust code to interact with
/// Python control directory implementations.
pub struct PyControlDir(PyObject);

/// A wrapper around a Python control directory prober object.
///
/// This struct provides a Rust interface to Python control directory prober
/// objects, implementing the `Prober` trait. It allows Rust code to interact
/// with Python control directory detection implementations.
pub struct PyProber(PyObject);

impl ControlDir for PyControlDir {}

impl Prober for PyProber {}
