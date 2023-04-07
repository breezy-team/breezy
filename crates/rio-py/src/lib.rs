use pyo3::prelude::*;

#[pyfunction]
fn _valid_tag(tag: &str) -> bool {
    return bazaar_rio::rio::valid_tag(tag);
}

#[pymodule]
fn _rio_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(_valid_tag)).unwrap();

    Ok(())
}
