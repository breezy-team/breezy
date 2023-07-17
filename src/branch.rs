use crate::controldir::ControlDir;
use crate::lock::Lock;
use crate::repository::Repository;
use crate::revisionid::RevisionId;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[derive(Clone)]
pub struct BranchFormat(pub PyObject);

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

#[derive(Clone)]
pub struct Branch(pub PyObject);

impl Branch {
    pub fn new(obj: PyObject) -> Self {
        Branch(obj)
    }

    pub fn format(&self) -> BranchFormat {
        Python::with_gil(|py| BranchFormat(self.0.getattr(py, "_format").unwrap()))
    }

    pub fn lock_read(&self) -> PyResult<Lock> {
        Python::with_gil(|py| Ok(Lock(self.0.call_method0(py, "lock_read")?)))
    }

    pub fn repository(&self) -> Repository {
        Python::with_gil(|py| Repository(self.0.getattr(py, "repository").unwrap()))
    }

    pub fn open(&self, url: &url::Url) -> PyResult<Branch> {
        Python::with_gil(|py| {
            Ok(Branch(self.0.call_method(
                py,
                "open",
                (url.to_string(),),
                None,
            )?))
        })
    }

    pub fn last_revision(&self) -> RevisionId {
        Python::with_gil(|py| {
            self.0
                .call_method0(py, "last_revision")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    pub fn name(&self) -> Option<String> {
        Python::with_gil(|py| {
            self.0
                .getattr(py, "name")
                .unwrap()
                .extract::<Option<String>>(py)
                .unwrap()
        })
    }

    pub fn get_user_url(&self) -> url::Url {
        Python::with_gil(|py| {
            let url = self
                .0
                .getattr(py, "get_user_url")
                .unwrap()
                .extract::<String>(py)
                .unwrap();
            url.parse::<url::Url>().unwrap()
        })
    }

    pub fn controldir(&self) -> ControlDir {
        Python::with_gil(|py| ControlDir::new(self.0.getattr(py, "controldir").unwrap()).unwrap())
    }

    pub fn push(
        &self,
        remote_branch: &Branch,
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
            self.0
                .call_method(py, "push", (&remote_branch.0,), Some(kwargs))?;
            Ok(())
        })
    }
}

impl FromPyObject<'_> for Branch {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        Ok(Branch(ob.to_object(ob.py())))
    }
}

impl ToPyObject for Branch {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
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
