use crate::tree::WorkingTree;
use pyo3::import_exception;
use pyo3::prelude::*;

pub struct DirtyTracker {
    obj: PyObject,
    owned: bool,
}

impl ToPyObject for DirtyTracker {
    fn to_object(&self, py: Python) -> PyObject {
        self.obj.clone_ref(py)
    }
}

impl FromPyObject<'_> for DirtyTracker {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        Ok(DirtyTracker {
            obj: ob.to_object(ob.py()),
            owned: false,
        })
    }
}

impl From<PyObject> for DirtyTracker {
    fn from(obj: PyObject) -> Self {
        DirtyTracker { obj, owned: false }
    }
}

import_exception!(breezy.dirty_tracker, TooManyOpenFiles);

#[derive(Debug)]
pub enum Error {
    TooManyOpenFiles,
    Python(PyErr),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match &self {
            Error::TooManyOpenFiles => write!(f, "Too many open files"),
            Error::Python(e) => write!(f, "{}", e),
        }
    }
}

impl std::error::Error for Error {}

impl From<PyErr> for Error {
    fn from(e: PyErr) -> Self {
        Python::with_gil(|py| {
            if e.is_instance_of::<TooManyOpenFiles>(py) {
                Error::TooManyOpenFiles
            } else {
                Error::Python(e)
            }
        })
    }
}

impl DirtyTracker {
    fn new(obj: PyObject) -> Result<Self, Error> {
        Python::with_gil(|py| {
            let dt = DirtyTracker { obj, owned: true };
            dt.to_object(py).call_method0(py, "__enter__")?;
            Ok(dt)
        })
    }

    pub fn is_dirty(&self) -> bool {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method0(py, "is_dirty")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    pub fn relpaths(&self) -> impl IntoIterator<Item = std::path::PathBuf> {
        Python::with_gil(|py| {
            let set = self
                .to_object(py)
                .call_method0(py, "relpaths")
                .unwrap()
                .extract::<std::collections::HashSet<_>>(py)
                .unwrap();
            set.into_iter()
        })
    }

    pub fn mark_clean(&self) {
        Python::with_gil(|py| {
            self.to_object(py).call_method0(py, "mark_clean").unwrap();
        })
    }
}

impl Drop for DirtyTracker {
    fn drop(&mut self) {
        if !self.owned {
            return;
        }
        Python::with_gil(|py| {
            self.to_object(py)
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
) -> Result<Option<DirtyTracker>, Error> {
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
                        return Err(e.into());
                    }
                }
            },
        };
        let o = dt_cls.call1((local_tree.to_object(py), subpath))?;
        Ok(Some(DirtyTracker::new(o.into())?))
    })
}
