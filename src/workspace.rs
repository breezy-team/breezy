use crate::dirty_tracker::DirtyTracker;
use crate::tree::{Tree, WorkingTree};
use pyo3::prelude::*;

pub fn reset_tree(
    local_tree: &WorkingTree,
    basis_tree: Option<&Box<dyn Tree>>,
    subpath: Option<&std::path::Path>,
    dirty_tracker: Option<&DirtyTracker>,
) {
    Python::with_gil(|py| {
        local_tree
            .0
            .call_method1(
                py,
                "reset_tree",
                (
                    &local_tree.0,
                    basis_tree.map(|o| o.obj()),
                    subpath,
                    &dirty_tracker.map(|dt| dt.0.clone()),
                ),
            )
            .unwrap();
    })
}
