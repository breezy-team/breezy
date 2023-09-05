use crate::tree::Tree;
use pyo3::prelude::*;
use std::io::Write;

#[pyclass]
struct PyOut(Box<dyn Write + Send>);

pub fn show_diff_trees(
    tree1: &dyn Tree,
    tree2: &dyn Tree,
    o: Box<dyn Write + Send>,
) -> PyResult<()> {
    Python::with_gil(|py| -> PyResult<()> {
        let m = py.import("breezy.diff")?;
        let f = m.getattr("show_diff_trees")?;

        let o = PyOut(o);

        f.call1((tree1.to_object(py), tree2.to_object(py), o))?;

        Ok(())
    })?;

    Ok(())
}
