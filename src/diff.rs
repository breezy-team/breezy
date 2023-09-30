use crate::tree::Tree;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::io::Write;

#[pyclass]
struct PyOut(Box<dyn Write + Send>);

pub fn show_diff_trees(
    tree1: &dyn Tree,
    tree2: &dyn Tree,
    o: Box<dyn Write + Send>,
    old_label: Option<&str>,
    new_label: Option<&str>,
) -> PyResult<()> {
    Python::with_gil(|py| -> PyResult<()> {
        let m = py.import("breezy.diff")?;
        let f = m.getattr("show_diff_trees")?;

        let o = PyOut(o);

        let kwargs = PyDict::new(py);
        if let Some(old_label) = old_label {
            kwargs.set_item("old_label", old_label)?;
        }

        if let Some(new_label) = new_label {
            kwargs.set_item("new_label", new_label)?;
        }

        f.call((tree1.to_object(py), tree2.to_object(py), o), Some(kwargs))?;

        Ok(())
    })?;

    Ok(())
}
