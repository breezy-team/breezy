use crate::revisionid::RevisionId;
use pyo3::prelude::*;

pub struct Graph(pub(crate) PyObject);

impl Graph {
    pub fn is_ancestor(&self, rev1: RevisionId, rev2: RevisionId) -> bool {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "is_ancestor", (rev1, rev2))
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }
}
