use crate::forge::Forge;
use pyo3::prelude::*;

pub struct PyForge(PyObject);

impl Forge for PyForge {}
