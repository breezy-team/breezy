use crate::controldir::ControlDir;
use crate::graph::Graph;
use pyo3::prelude::*;

#[derive(Clone)]
pub struct RepositoryFormat(pub(crate) PyObject);

impl RepositoryFormat {
    pub fn supports_chks(&self) -> bool {
        Python::with_gil(|py| {
            self.0
                .getattr(py, "supports_chks")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }
}

#[derive(Clone)]
pub struct Repository(pub(crate) PyObject);

impl Repository {
    pub fn get_graph(&self) -> Graph {
        Python::with_gil(|py| Graph(self.0.call_method0(py, "get_graph").unwrap()))
    }

    pub fn controldir(&self) -> ControlDir {
        Python::with_gil(|py| ControlDir(self.0.getattr(py, "controldir").unwrap()))
    }

    pub fn format(&self) -> RepositoryFormat {
        Python::with_gil(|py| RepositoryFormat(self.0.getattr(py, "_format").unwrap()))
    }
}
