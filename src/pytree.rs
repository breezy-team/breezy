use crate::tree::{Error, MutableTree, RevisionTree, Tree, WorkingTree};
use bazaar::RevisionId;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// A wrapper around a Python tree object.
///
/// This struct provides a Rust interface to Python tree objects, implementing
/// the various tree traits (`Tree`, `MutableTree`, `WorkingTree`, `RevisionTree`).
/// It allows Rust code to interact with Python tree implementations.
pub struct PyTree(Py<PyAny>);

impl PyTree {
    /// Creates a new `PyTree` wrapper around a Python tree object.
    ///
    /// # Arguments
    ///
    /// * `obj` - The Python tree object to wrap.
    pub fn new(obj: Py<PyAny>) -> Self {
        PyTree(obj)
    }
}

import_exception!(breezy.errors, NotVersionedError);

fn map_py_err_to_err(py: Python<'_>, py_err: PyErr) -> Error {
    if py_err.is_instance_of::<NotVersionedError>(py) {
        Error::NotVersioned(py_err.value(py).getattr("path").unwrap().to_string())
    } else {
        Error::Other(py_err.to_string())
    }
}

impl Tree for PyTree {
    fn supports_rename_tracking(&self) -> bool {
        Python::attach(|py| {
            let pytree = self.0.bind(py);
            pytree
                .call_method0("supports_rename_tracking")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn unlock(&mut self) -> Result<(), String> {
        Python::attach(|py| {
            let pytree = self.0.bind(py);
            pytree
                .call_method0("unlock")
                .map_err(|e| e.to_string())
                .map(|_| ())
        })
    }
}

impl MutableTree for PyTree {
    fn smart_add(
        &mut self,
        file_list: Vec<&str>,
        recurse: Option<bool>,
        save: Option<bool>,
    ) -> (Vec<String>, Vec<String>) {
        Python::attach(|py| {
            let pytree = self.0.bind(py);
            let (added, removed) = pytree
                .call_method1(
                    "smart_add",
                    (
                        file_list,
                        recurse.unwrap_or(true),
                        py.None(),
                        save.unwrap_or(true),
                    ),
                )
                .unwrap()
                .extract()
                .unwrap();
            (added, removed)
        })
    }

    fn commit(&mut self, message: Option<&str>) -> RevisionId {
        let revid: Vec<u8> = Python::attach(|py| {
            let pytree = self.0.bind(py);
            pytree
                .call_method1("commit", (message,))
                .unwrap()
                .extract()
                .unwrap()
        });
        RevisionId::from(revid)
    }

    fn mkdir(&mut self, path: &str) -> Result<(), Error> {
        Python::attach(|py| {
            let pytree = self.0.bind(py);
            pytree
                .call_method1("mkdir", (path,))
                .map_err(|e| map_py_err_to_err(py, e))
                .map(|_| ())
        })
    }

    fn put_file_bytes_non_atomic(
        &mut self,
        path: &str,
        data: &[u8],
    ) -> std::result::Result<(), Error> {
        Python::attach(|py| {
            let pytree = self.0.bind(py);
            let data = PyBytes::new(py, data);
            pytree
                .call_method1("put_file_bytes_non_atomic", (path, data))
                .map_err(|e| map_py_err_to_err(py, e))
                .map(|_| ())
        })
    }

    fn add(&mut self, paths: &[&str]) -> std::result::Result<(), Error> {
        Python::attach(|py| {
            let pytree = self.0.bind(py);
            pytree
                .call_method1("add", (paths.to_vec(),))
                .map_err(|e| map_py_err_to_err(py, e))
                .map(|_| ())
        })
    }

    fn lock_tree_write(&mut self) -> Result<(), String> {
        Python::attach(|py| {
            let pytree = self.0.bind(py);
            pytree
                .call_method0("lock_tree_write")
                .map_err(|e| e.to_string())
                .map(|_| ())
        })
    }
}

impl WorkingTree for PyTree {
    fn abspath(&self, path: &str) -> std::path::PathBuf {
        Python::attach(|py| {
            let pytree = self.0.bind(py);
            pytree
                .call_method1("abspath", (path,))
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn last_revision(&self) -> RevisionId {
        let revid: Vec<u8> = Python::attach(|py| {
            let pytree = self.0.bind(py);
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
        let revid: Vec<u8> = Python::attach(|py| {
            let pytree = self.0.bind(py);
            pytree
                .call_method0("get_revision_id")
                .unwrap()
                .extract()
                .unwrap()
        });
        RevisionId::from(revid)
    }
}
