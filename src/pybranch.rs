use crate::branch::Branch;
use bazaar::RevisionId;
use pyo3::prelude::*;

/// A wrapper around a Python branch object.
///
/// This struct provides a Rust interface to Python branch objects, implementing
/// the `Branch` trait. It allows Rust code to interact with Python branch
/// implementations.
pub struct PyBranch(PyObject);

impl PyBranch {
    /// Creates a new `PyBranch` wrapper around a Python branch object.
    ///
    /// # Arguments
    ///
    /// * `o` - The Python branch object to wrap.
    pub fn new(o: PyObject) -> Self {
        PyBranch(o)
    }
}

impl Branch for PyBranch {
    fn last_revision(&self) -> RevisionId {
        Python::with_gil(|py| {
            let py_branch = self.0.bind(py);
            let py_revision_id = py_branch.call_method0("last_revision_id").unwrap();
            let revision_id = py_revision_id.extract::<Vec<u8>>().unwrap();
            bazaar::RevisionId::from(revision_id)
        })
    }

    fn name(&self) -> String {
        Python::with_gil(|py| {
            let py_branch = self.0.bind(py);
            let py_name = py_branch.getattr("name").unwrap();
            py_name.extract::<String>().unwrap()
        })
    }

    fn tags(&self) -> Box<dyn crate::tags::Tags> {
        Python::with_gil(|py| {
            let py_branch = self.0.bind(py);
            let py_tags = py_branch.getattr("tags").unwrap();
            let tags = crate::pytags::PyTags(py_tags.unbind());
            Box::new(tags)
        })
    }
}
