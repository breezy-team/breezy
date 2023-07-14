use pyo3::prelude::*;

pub struct Lock(pub(crate) PyObject);

impl Drop for Lock {
    fn drop(&mut self) {
        Python::with_gil(|py| {
            self.0.call_method0(py, "unlock").unwrap();
        });
    }
}
