use crate::tree::WorkingTree;
use pyo3::prelude::*;

pub fn show_tree_status(wt: &WorkingTree) -> PyResult<()> {
    Python::with_gil(|py| {
        let m = py.import("breezy.status")?;
        let f = m.getattr("show_tree_status")?;
        f.call1((&wt.0,))?;
        Ok(())
    })
}
