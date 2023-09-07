use crate::branch::Branch;
use crate::graph::Graph;
use crate::transform::TreeTransform;
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
    pub fn new(branch: &dyn Branch, tree: &dyn Tree, revision_graph: &Graph) -> Self {
        Python::with_gil(|py| {
            let m = py.import("breezy.merge").unwrap();
            let cls = m.getattr("Merger").unwrap();
            let merger = cls
                .call1((
                    branch.to_object(py),
                    tree.to_object(py),
                    revision_graph.to_object(py),
                ))
                .unwrap();
            Merger(merger.into())
        })
    }

    pub fn find_base(&self) -> PyResult<Option<RevisionId>> {
        Python::with_gil(|py| match self.0.call_method0(py, "find_base") {
            Ok(py_obj) => Ok(Some(py_obj.extract(py)?)),
            Err(err) => {
                if err.is_instance_of::<UnrelatedBranches>(py) {
                    Ok(None)
                } else {
                    Err(err)
                }
            }
        })
    }

    pub fn set_other_revision(
        &mut self,
        other_revision: &RevisionId,
        other_branch: &dyn Branch,
    ) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method1(
                py,
                "set_other_revision",
                (other_revision.clone(), other_branch.to_object(py)),
            )?;
            Ok(())
        })
    }

    pub fn set_base_revision(
        &mut self,
        base_revision: &RevisionId,
        base_branch: &dyn Branch,
    ) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method1(
                py,
                "set_base_revision",
                (base_revision.clone(), base_branch.to_object(py)),
            )?;
            Ok(())
        })
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

    pub fn make_merger(&self) -> PyResult<Submerger> {
        Python::with_gil(|py| {
            let merger = self.0.call_method0(py, "make_merger")?;
            Ok(Submerger(merger))
        })
    }
}

pub struct Submerger(PyObject);

impl Submerger {
    pub fn make_preview_transform(&self) -> PyResult<TreeTransform> {
        Python::with_gil(|py| {
            let transform = self
                .0
                .call_method0(py, "make_preview_transform")?
                .to_object(py);
            Ok(TreeTransform::from(transform))
        })
    }
}
