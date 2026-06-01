use crate::repository::Repository;
use pyo3::prelude::*;

pub struct PyRepository(Py<PyAny>);

impl Repository for PyRepository {}
