#[macro_use]
extern crate lazy_static;

use pyo3::prelude::*;
use regex::Regex;

#[pyfunction]
fn _valid_tag(tag: &str) -> bool {
    lazy_static! {
        static ref RE: Regex = Regex::new(r"^[-a-zA-Z0-9_]+$").unwrap();
    }
    RE.is_match(tag)
}

#[pymodule]
fn _rio_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(_valid_tag)).unwrap();

    Ok(())
}
