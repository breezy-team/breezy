use crate::repository::Repository;
use pyo3::prelude::*;

pub struct PyRepository(PyObject);

impl Repository for PyRepository {}
