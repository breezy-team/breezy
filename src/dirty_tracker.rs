use pyo3::prelude::*;

pub struct DirtyTracker(pub PyObject);

impl DirtyTracker {
    pub fn is_dirty(&self) -> bool {
        Python::with_gil(|py| {
            self.0
                .call_method0(py, "is_dirty")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    pub fn relpaths(&self) -> impl IntoIterator<Item = std::path::PathBuf> {
        Python::with_gil(|py| {
            self.0
                .call_method0(py, "relpaths")
                .unwrap()
                .extract::<std::collections::HashSet<_>>(py)
                .unwrap()
                .into_iter()
        })
    }
}
