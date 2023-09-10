use crate::controldir::ControlDir;
use crate::lock::Lock;
use crate::repository::Repository;
use crate::revisionid::RevisionId;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyDict;

import_exception!(breezy.errors, NotBranchError);
import_exception!(breezy.errors, DependencyNotPresent);
import_exception!(breezy.controldir, NoColocatedBranchSupport);

#[derive(Debug)]
pub enum BranchOpenError {
    NotBranchError(String),
    NoColocatedBranchSupport,
    DependencyNotPresent(String, String),
    Other(PyErr),
}

impl From<PyErr> for BranchOpenError {
    fn from(err: PyErr) -> Self {
        Python::with_gil(|py| {
            if err.is_instance_of::<NotBranchError>(py) {
                let l = err
                    .value(py)
                    .getattr("path")
                    .unwrap()
                    .extract::<String>()
                    .unwrap();
                BranchOpenError::NotBranchError(l)
            } else if err.is_instance_of::<NoColocatedBranchSupport>(py) {
                BranchOpenError::NoColocatedBranchSupport
            } else if err.is_instance_of::<DependencyNotPresent>(py) {
                let l = err
                    .value(py)
                    .getattr("library")
                    .unwrap()
                    .extract::<String>()
                    .unwrap();
                let e = err
                    .value(py)
                    .getattr("error")
                    .unwrap()
                    .extract::<String>()
                    .unwrap();
                BranchOpenError::DependencyNotPresent(l, e)
            } else {
                BranchOpenError::Other(err)
            }
        })
    }
}

impl From<BranchOpenError> for PyErr {
    fn from(err: BranchOpenError) -> Self {
        match err {
            BranchOpenError::NotBranchError(l) => NotBranchError::new_err((l,)),
            BranchOpenError::DependencyNotPresent(d, e) => DependencyNotPresent::new_err((d, e)),
            BranchOpenError::NoColocatedBranchSupport => {
                NoColocatedBranchSupport::new_err("NoColocatedBranchSupport")
            }
            BranchOpenError::Other(err) => err,
        }
    }
}

impl std::fmt::Display for BranchOpenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BranchOpenError::NotBranchError(p) => write!(f, "NotBranchError: {}", p),
            BranchOpenError::DependencyNotPresent(d, e) => {
                write!(f, "DependencyNotPresent({}, {})", d, e)
            }
            BranchOpenError::NoColocatedBranchSupport => write!(f, "NoColocatedBranchSupport"),
            BranchOpenError::Other(err) => write!(f, "Other({})", err),
        }
    }
}

impl std::error::Error for BranchOpenError {}

#[derive(Clone)]
pub struct BranchFormat(PyObject);

impl BranchFormat {
    pub fn supports_stacking(&self) -> bool {
        Python::with_gil(|py| {
            self.0
                .call_method0(py, "supports_stacking")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }
}

pub trait Branch: ToPyObject + Send {
    fn format(&self) -> BranchFormat {
        Python::with_gil(|py| BranchFormat(self.to_object(py).getattr(py, "_format").unwrap()))
    }

    fn lock_read(&self) -> PyResult<Lock> {
        Python::with_gil(|py| {
            Ok(Lock::from(
                self.to_object(py).call_method0(py, "lock_read")?,
            ))
        })
    }

    fn repository(&self) -> Repository {
        Python::with_gil(|py| {
            Repository::new(self.to_object(py).getattr(py, "repository").unwrap())
        })
    }

    fn last_revision(&self) -> RevisionId {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method0(py, "last_revision")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    fn name(&self) -> Option<String> {
        Python::with_gil(|py| {
            self.to_object(py)
                .getattr(py, "name")
                .unwrap()
                .extract::<Option<String>>(py)
                .unwrap()
        })
    }

    fn get_user_url(&self) -> url::Url {
        Python::with_gil(|py| {
            let url = self
                .to_object(py)
                .getattr(py, "get_user_url")
                .unwrap()
                .extract::<String>(py)
                .unwrap();
            url.parse::<url::Url>().unwrap()
        })
    }

    fn controldir(&self) -> ControlDir {
        Python::with_gil(|py| {
            ControlDir::new(self.to_object(py).getattr(py, "controldir").unwrap())
        })
    }

    fn push(
        &self,
        remote_branch: &dyn Branch,
        overwrite: bool,
        stop_revision: Option<&RevisionId>,
        tag_selector: Option<Box<dyn Fn(String) -> bool>>,
    ) -> PyResult<()> {
        Python::with_gil(|py| {
            let kwargs = PyDict::new(py);
            kwargs.set_item("overwrite", overwrite)?;
            if let Some(stop_revision) = stop_revision {
                kwargs.set_item("stop_revision", stop_revision)?;
            }
            if let Some(tag_selector) = tag_selector {
                kwargs.set_item("tag_selector", py_tag_selector(py, tag_selector)?)?;
            }
            self.to_object(py).call_method(
                py,
                "push",
                (&remote_branch.to_object(py),),
                Some(kwargs),
            )?;
            Ok(())
        })
    }
}

#[derive(Clone)]
pub struct RegularBranch(PyObject);

impl Branch for RegularBranch {}

impl ToPyObject for RegularBranch {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl RegularBranch {
    pub fn new(obj: PyObject) -> Self {
        RegularBranch(obj)
    }
}

impl FromPyObject<'_> for RegularBranch {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        Ok(RegularBranch(ob.to_object(ob.py())))
    }
}

#[derive(Clone)]
pub struct MemoryBranch(PyObject);

impl ToPyObject for MemoryBranch {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl Branch for MemoryBranch {}

impl MemoryBranch {
    pub fn new(repository: &Repository, revno: Option<u32>, revid: &RevisionId) -> PyResult<Self> {
        Python::with_gil(|py| {
            let mb_cls = py.import("breezy.memorybranch")?.getattr("MemoryBranch")?;

            let o = mb_cls.call1((repository.to_object(py), (revno, revid.clone())))?;

            Ok(MemoryBranch(o.to_object(py)))
        })
    }
}

pub(crate) fn py_tag_selector(
    py: Python,
    tag_selector: Box<dyn Fn(String) -> bool>,
) -> PyResult<PyObject> {
    #[pyclass(unsendable)]
    struct PyTagSelector(Box<dyn Fn(String) -> bool>);

    #[pymethods]
    impl PyTagSelector {
        fn __call__(&self, tag: String) -> bool {
            (self.0)(tag)
        }
    }
    Ok(PyTagSelector(tag_selector).into_py(py))
}

pub fn open(url: &url::Url) -> Result<Box<dyn Branch>, BranchOpenError> {
    Python::with_gil(|py| {
        let m = py.import("breezy.branch").unwrap();
        let c = m.getattr("Branch").unwrap();
        let r = c.call_method1("open", (url.to_string(),))?;
        Ok(Box::new(RegularBranch(r.to_object(py))) as Box<dyn Branch>)
    })
}

pub fn open_containing(url: &url::Url) -> Result<(Box<dyn Branch>, String), BranchOpenError> {
    Python::with_gil(|py| {
        let m = py.import("breezy.branch").unwrap();
        let c = m.getattr("Branch").unwrap();

        let (b, p): (&PyAny, String) = c
            .call_method1("open_containing", (url.to_string(),))?
            .extract()?;

        Ok((
            Box::new(RegularBranch(b.to_object(py))) as Box<dyn Branch>,
            p,
        ))
    })
}
