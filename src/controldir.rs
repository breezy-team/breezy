use crate::branch::{py_tag_selector, Branch, BranchOpenError};
use crate::transport::Transport;
use crate::tree::WorkingTree;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub struct Prober(PyObject);

impl Prober {
    pub fn new(obj: PyObject) -> Self {
        Prober(obj)
    }
}

pub struct ControlDir(pub(crate) PyObject);

impl ControlDir {
    pub fn new(obj: PyObject) -> PyResult<Self> {
        Ok(Self(obj))
    }

    pub fn create_branch_convenience(base: &url::Url) -> PyResult<Branch> {
        Python::with_gil(|py| {
            let m = py.import("breezy.controldir")?;
            let cd = m.getattr("ControlDir")?;
            let branch = cd.call_method("create_branch_convenience", (base.to_string(),), None)?;
            Ok(Branch(branch.to_object(py)))
        })
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

    pub fn create_branch(&self, name: Option<&str>) -> PyResult<Branch> {
        Python::with_gil(|py| {
            let branch = self
                .0
                .call_method(py, "create_branch", (name,), None)?
                .extract(py)?;
            Ok(Branch(branch))
        })
    }

    pub fn open_branch(&self, branch_name: Option<&str>) -> Result<Branch, BranchOpenError> {
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

    pub fn sprout(
        &self,
        target: url::Url,
        source_branch: Option<&Branch>,
        create_tree_if_local: Option<bool>,
        stacked: Option<bool>,
    ) -> ControlDir {
        Python::with_gil(|py| {
            let kwargs = PyDict::new(py);
            if let Some(create_tree_if_local) = create_tree_if_local {
                kwargs
                    .set_item("create_tree_if_local", create_tree_if_local)
                    .unwrap();
            }
            if let Some(stacked) = stacked {
                kwargs.set_item("stacked", stacked).unwrap();
            }
            if let Some(source_branch) = source_branch {
                kwargs.set_item("source_branch", &source_branch.0).unwrap();
            }

            let cd = self
                .0
                .call_method(py, "sprout", (target.to_string(),), Some(kwargs))
                .unwrap();
            ControlDir(cd)
        })
    }

    pub fn open_workingtree(&self) -> PyResult<WorkingTree> {
        Python::with_gil(|py| {
            let wt = self.0.call_method0(py, "open_workingtree")?.extract(py)?;
            Ok(WorkingTree(wt))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_create_branch_convenience() {
        Python::with_gil(|py| {
            py.import("breezy.bzr").unwrap();
        });
        let td = tempfile::tempdir().unwrap();
        let b = ControlDir::create_branch_convenience(&url::Url::from_directory_path(td).unwrap())
            .unwrap();
        assert!(b.name().is_none());
        let cd = b.controldir();
        let branch = cd.create_branch(Some("foo")).unwrap();
        assert_eq!(branch.name().unwrap(), "foo");
        let same_branch = cd.open_branch(Some("foo")).unwrap();
        assert_eq!(branch.name().unwrap(), same_branch.name().unwrap());
    }
}
