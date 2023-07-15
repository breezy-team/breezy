use crate::tree::{Tree, WorkingTree};
use pyo3::prelude::*;

pub struct DirtyTracker(pub PyObject);

impl DirtyTracker {
    fn new(obj: PyObject) -> PyResult<Self> {
        Python::with_gil(|py| {
            let dt = DirtyTracker(obj);
            dt.0.call_method0(py, "__enter__")?;
            Ok(dt)
        })
    }

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
            let set = self
                .0
                .call_method0(py, "relpaths")
                .unwrap()
                .extract::<std::collections::HashSet<_>>(py)
                .unwrap();
            set.into_iter()
        })
    }

    pub fn mark_clean(&self) {
        Python::with_gil(|py| {
            self.0.call_method0(py, "mark_clean").unwrap();
        })
    }
}

impl Drop for DirtyTracker {
    fn drop(&mut self) {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "__exit__", (py.None(), py.None(), py.None()))
                .unwrap();
        })
    }
}

/// Create a dirty tracker object
pub fn get_dirty_tracker(
    local_tree: &WorkingTree,
    subpath: Option<&std::path::Path>,
    use_inotify: Option<bool>,
) -> PyResult<Option<DirtyTracker>> {
    Python::with_gil(|py| {
        let dt_cls = match use_inotify {
            Some(true) => {
                let m = py.import("breezy.dirty_tracker")?;
                m.getattr("DirtyTracker")?
            }
            Some(false) => return Ok(None),
            None => match py.import("breezy.dirty_tracker") {
                Ok(m) => m.getattr("DirtyTracker")?,
                Err(e) => {
                    if e.is_instance_of::<pyo3::exceptions::PyImportError>(py) {
                        return Ok(None);
                    } else {
                        return Err(e);
                    }
                }
            },
        };
        let o = dt_cls.call1((local_tree.obj().clone_ref(py), subpath))?;
        Ok(Some(DirtyTracker::new(o.into())?))
    })
}
