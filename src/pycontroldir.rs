use crate::controldir::{ControlDir, Prober};
use pyo3::prelude::*;

pub struct PyControlDir(PyObject);
pub struct PyProber(PyObject);

impl ControlDir for PyControlDir {}

impl Prober for PyProber {}
