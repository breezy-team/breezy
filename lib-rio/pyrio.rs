#[macro_use]
extern crate lazy_static;

use pyo3::prelude::*;

pub mod rio;

#[pyfunction]
fn _valid_tag(tag: &str) -> bool {
    return rio::valid_tag(tag);
}

#[pymodule]
fn _rio_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(_valid_tag)).unwrap();

    Ok(())
}
