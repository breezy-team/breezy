use pyo3::prelude::*;

#[pyclass]
struct RioReader {
}

#[pyclass]
struct RioWriter {
}

#[pyclass]
struct Stanza {
}

#[pymodule]
fn rio(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<RioReader>()?;
    m.add_class::<RioWriter>()?;
    m.add_class::<Stanza>()?;

    Ok(())
}
