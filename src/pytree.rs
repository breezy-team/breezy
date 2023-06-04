use crate::tree::Tree;
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
