use crate::graph::Graph;
use pyo3::prelude::*;

pub struct Repository(pub(crate) PyObject);

impl Repository {
    pub fn get_graph(&self) -> Graph {
        Python::with_gil(|py| Graph(self.0.call_method0(py, "get_graph").unwrap()))
    }
}
