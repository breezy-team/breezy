use crate::dirty_tracker::DirtyTracker;
use crate::tree::{Tree, WorkingTree};
use pyo3::import_exception;
use pyo3::prelude::*;

import_exception!(breezy.workspace, WorkspaceDirty);

pub fn reset_tree(
    local_tree: &WorkingTree,
    basis_tree: Option<&dyn Tree>,
    subpath: Option<&std::path::Path>,
    dirty_tracker: Option<&DirtyTracker>,
) -> PyResult<()> {
    Python::with_gil(|py| {
        let workspace_m = py.import("breezy.workspace")?;
        let reset_tree = workspace_m.getattr("reset_tree")?;
        let local_tree: PyObject = local_tree.to_object(py);
        let basis_tree: Option<PyObject> = basis_tree.map(|o| o.to_object(py));
        let dirty_tracker: Option<PyObject> = dirty_tracker.map(|dt| dt.to_object(py));
        reset_tree.call1((local_tree, basis_tree, subpath, dirty_tracker))?;
        Ok(())
    })
}

#[derive(Debug)]
pub enum CheckCleanTreeError {
    WorkspaceDirty(std::path::PathBuf),
    Python(PyErr),
}

impl std::fmt::Display for CheckCleanTreeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CheckCleanTreeError::WorkspaceDirty(path) => {
                write!(f, "Workspace dirty at {}", path.display())
            }
            CheckCleanTreeError::Python(e) => write!(f, "{}", e),
        }
    }
}

impl std::error::Error for CheckCleanTreeError {}

impl From<CheckCleanTreeError> for PyErr {
    fn from(e: CheckCleanTreeError) -> Self {
        match e {
            CheckCleanTreeError::WorkspaceDirty(path) => {
                WorkspaceDirty::new_err(path.to_string_lossy().to_string())
            }
            CheckCleanTreeError::Python(e) => e,
        }
    }
}

impl From<PyErr> for CheckCleanTreeError {
    fn from(e: PyErr) -> Self {
        Python::with_gil(|py| {
            if e.is_instance_of::<WorkspaceDirty>(py) {
                let tree = e.value(py).getattr("tree").unwrap();
                let path = e.value(py).getattr("path").unwrap();
                let path = tree
                    .call_method1("abspath", (path,))
                    .unwrap()
                    .extract::<String>()
                    .unwrap();
                CheckCleanTreeError::WorkspaceDirty(std::path::PathBuf::from(path))
            } else {
                CheckCleanTreeError::Python(e)
            }
        })
    }
}

pub fn check_clean_tree(
    local_tree: &WorkingTree,
    basis_tree: &dyn Tree,
    subpath: &std::path::Path,
) -> Result<(), CheckCleanTreeError> {
    Python::with_gil(|py| {
        let workspace_m = py.import("breezy.workspace")?;
        let check_clean_tree = workspace_m.getattr("check_clean_tree")?;
        let local_tree: PyObject = local_tree.to_object(py).clone_ref(py);
        let basis_tree: PyObject = basis_tree.to_object(py).clone_ref(py);
        check_clean_tree.call1((local_tree, basis_tree, subpath.to_path_buf()))?;
        Ok(())
    })
}
