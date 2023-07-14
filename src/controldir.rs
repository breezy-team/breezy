use crate::branch::{py_tag_selector, Branch};
use crate::transport::Transport;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub struct Prober(PyObject);

impl Prober {
    pub fn new(obj: PyObject) -> Self {
        Prober(obj)
    }
}

pub struct ControlDir(PyObject);

impl ControlDir {
    pub fn new(obj: PyObject) -> PyResult<Self> {
        Ok(Self(obj))
    }

    pub fn open_containing_from_transport(
        transport: &Transport,
        probers: Option<&[Prober]>,
    ) -> PyResult<(ControlDir, String)> {
        Python::with_gil(|py| {
            let m = py.import("breezy.controldir")?;
            let cd = m.getattr("ControlDir")?;
            let kwargs = PyDict::new(py);
            if let Some(probers) = probers {
                kwargs.set_item("probers", probers.iter().map(|p| &p.0).collect::<Vec<_>>())?;
            }
            let (controldir, subpath): (PyObject, String) = cd
                .call_method(
                    "open_containing_from_transport",
                    (&transport.0,),
                    Some(kwargs),
                )?
                .extract()?;
            Ok((ControlDir(controldir.to_object(py)), subpath))
        })
    }

    pub fn open_from_transport(
        transport: &Transport,
        probers: Option<&[Prober]>,
    ) -> PyResult<ControlDir> {
        Python::with_gil(|py| {
            let m = py.import("breezy.controldir")?;
            let cd = m.getattr("ControlDir")?;
            let kwargs = PyDict::new(py);
            if let Some(probers) = probers {
                kwargs.set_item("probers", probers.iter().map(|p| &p.0).collect::<Vec<_>>())?;
            }
            let controldir =
                cd.call_method("open_from_transport", (&transport.0,), Some(kwargs))?;
            Ok(ControlDir(controldir.to_object(py)))
        })
    }

    pub fn open_branch(&self, branch_name: Option<&str>) -> PyResult<Branch> {
        Python::with_gil(|py| {
            let branch = self
                .0
                .call_method(py, "open_branch", (branch_name,), None)?
                .extract(py)?;
            Ok(Branch(branch))
        })
    }

    pub fn push_branch(
        &self,
        source_branch: &Branch,
        to_branch_name: Option<&str>,
        overwrite: Option<bool>,
        tag_selector: Option<Box<dyn Fn(String) -> bool>>,
    ) -> PyResult<Branch> {
        Python::with_gil(|py| {
            let kwargs = PyDict::new(py);
            if let Some(to_branch_name) = to_branch_name {
                kwargs.set_item("name", to_branch_name)?;
            }
            if let Some(tag_selector) = tag_selector {
                kwargs.set_item("tag_selector", py_tag_selector(py, tag_selector)?)?;
            }
            if let Some(overwrite) = overwrite {
                kwargs.set_item("overwrite", overwrite)?;
            }
            let result =
                self.0
                    .call_method(py, "push_branch", (&source_branch.0,), Some(kwargs))?;
            Ok(Branch(result.getattr(py, "target_branch")?))
        })
    }
}
