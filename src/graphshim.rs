use bazaar::RevisionId;
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use std::collections::HashSet;

pub struct Graph(PyObject);

impl Graph {
    pub fn new(o: PyObject) -> Self {
        Graph(o)
    }

    pub fn find_unique_ancestors(
        &self,
        old_tip: RevisionId,
        parents: &[RevisionId],
    ) -> HashSet<RevisionId> {
        Python::with_gil(|py| {
            let parents = PyTuple::new(py, parents).unwrap();
            let result = self
                .0
                .call_method1(py, "find_unique_ancestors", (old_tip, parents))
                .unwrap();

            result.extract::<HashSet<RevisionId>>(py).unwrap()
        })
    }
}
