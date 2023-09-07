use crate::graph::Graph;
use crate::repository::Repository;
use crate::tree::Tree;
use crate::RevisionId;
use pyo3::import_exception;
use pyo3::prelude::*;

import_exception!(breezy.errors, UnrelatedBranches);

pub struct Merger(PyObject);

pub enum MergeType {
    Merge3,
}

impl From<PyObject> for Merger {
    fn from(obj: PyObject) -> Self {
        Merger(obj)
    }
}

impl Merger {
    pub fn new(repository: &Repository, tree: &dyn Tree, revision_graph: &Graph) -> Self {
        Python::with_gil(|py| {
            let m = py.import("breezy.merge").unwrap();
            let cls = m.getattr("Merger").unwrap();
            let merger = cls
                .call1((
                    repository.to_object(py),
                    tree.to_object(py),
                    revision_graph.to_object(py),
                ))
                .unwrap();
            Merger(merger.into())
        })
    }

    pub fn find_base(&self, py: Python) -> PyResult<Option<RevisionId>> {
        match self.0.call_method0(py, "find_base") {
            Ok(py_obj) => Ok(Some(py_obj.extract(py)?)),
            Err(err) => {
                if err.is_instance_of::<UnrelatedBranches>(py) {
                    Ok(None)
                } else {
                    Err(err)
                }
            }
        }
    }

    pub fn set_merge_type(&mut self, merge_type: MergeType) {
        Python::with_gil(|py| {
            let m = py.import("breezy.merge").unwrap();
            let merge_type = match merge_type {
                MergeType::Merge3 => m.getattr("Merge3Merger").unwrap(),
            };
            self.0.setattr(py, "merge_type", merge_type).unwrap();
        })
    }
}
