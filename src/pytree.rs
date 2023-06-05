use crate::tree::{Tree, WorkingTree};
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

impl WorkingTree for PyTree {
    fn local_abspath(&self, path: &str) -> std::path::PathBuf {
        Python::with_gil(|py| {
            let pytree = self.0.as_ref(py);
            pytree
                .call_method1("local_abspath", (path,))
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
