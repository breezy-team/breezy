use pyo3::prelude::*;

pub struct Lock(PyObject);

impl From<PyObject> for Lock {
    fn from(obj: PyObject) -> Self {
        Lock(obj)
    }
}

impl ToPyObject for Lock {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl Drop for Lock {
    fn drop(&mut self) {
        Python::with_gil(|py| {
            self.0.call_method0(py, "unlock").unwrap();
        });
    }
}
