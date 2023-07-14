use crate::dirty_tracker::DirtyTracker;
use crate::tree::{Tree, WorkingTree};
use pyo3::prelude::*;

pub fn reset_tree(
    local_tree: &WorkingTree,
    basis_tree: Option<&Box<dyn Tree>>,
    subpath: Option<&std::path::Path>,
    dirty_tracker: Option<&DirtyTracker>,
) -> PyResult<()> {
    Python::with_gil(|py| {
        let workspace_m = py.import("breezy.workspace")?;
        let reset_tree = workspace_m.getattr("reset_tree")?;
        reset_tree.call1((
            &local_tree.0,
            basis_tree.map(|o| o.obj()),
            subpath,
            &dirty_tracker.map(|dt| dt.0.clone()),
        ))?;
        Ok(())
    })
}
