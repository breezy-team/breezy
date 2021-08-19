#[macro_use]
extern crate lazy_static;

use pyo3::prelude::*;
use regex::Regex;

#[pyclass]
struct RioReader {
}

#[pyclass]
struct RioWriter {
}

#[pyclass]
struct Stanza {
}

#[pyfunction]
fn _valid_tag(tag: &str) -> bool {
    lazy_static! {
        static ref RE: Regex = Regex::new(r"^[-a-zA-Z0-9_]+$").unwrap();
    }
    RE.is_match(tag)
}

#[pymodule]
fn _rio_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<RioReader>()?;
    m.add_class::<RioWriter>()?;
    m.add_class::<Stanza>()?;
    m.add_wrapped(wrap_pyfunction!(_valid_tag)).unwrap();

    Ok(())
}
