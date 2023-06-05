use crate::tree::{MutableTree, RevisionTree, Tree, WorkingTree};
use bazaar::RevisionId;
use pyo3::prelude::*;

pub struct PyTree(PyObject);

impl Tree for PyTree {
    fn supports_rename_tracking(&self) -> bool {
        Python::with_gil(|py| {
            let pytree = self.0.as_ref(py);
            pytree
                .call_method0("supports_rename_tracking")
                .unwrap()
                .extract()
                .unwrap()
        })
    }
}

impl MutableTree for PyTree {}

impl WorkingTree for PyTree {
    fn abspath(&self, path: &str) -> std::path::PathBuf {
        Python::with_gil(|py| {
            let pytree = self.0.as_ref(py);
            pytree
                .call_method1("abspath", (path,))
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn last_revision(&self) -> RevisionId {
        let revid: Vec<u8> = Python::with_gil(|py| {
            let pytree = self.0.as_ref(py);
            pytree
                .call_method0("last_revision")
                .unwrap()
                .extract()
                .unwrap()
        });
        RevisionId::from(revid)
    }
}

impl RevisionTree for PyTree {
    fn get_revision_id(&self) -> RevisionId {
        let revid: Vec<u8> = Python::with_gil(|py| {
            let pytree = self.0.as_ref(py);
            pytree
                .call_method0("get_revision_id")
                .unwrap()
                .extract()
                .unwrap()
        });
        RevisionId::from(revid)
    }
}
