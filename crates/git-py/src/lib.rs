use pyo3::prelude::*;

#[pyfunction]
fn bzr_url_to_git_url(location: &str) -> PyResult<(String, Option<String>, Option<String>)> {
    let (url, revno, branch) = breezy_git::bzr_url_to_git_url(location)
        .map_err(|_e| PyErr::new::<pyo3::exceptions::PyValueError, _>(("Invalid URL",)))?;
    Ok((url, revno, branch))
}

#[pyfunction]
fn get_cache_dir() -> PyResult<String> {
    let path = breezy_git::get_cache_dir().map_err(|e| -> PyErr { e.into() })?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyValueError, _>(("Invalid path",)))
}

#[pymodule]
pub fn _git_rs(_py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(bzr_url_to_git_url))?;
    m.add_wrapped(wrap_pyfunction!(get_cache_dir))?;
    Ok(())
}
