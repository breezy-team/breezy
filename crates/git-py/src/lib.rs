use pyo3::prelude::*;

#[pyfunction]
fn bzr_url_to_git_url(location: &str) -> PyResult<(String, Option<String>, Option<String>)> {
    let (url, revno, branch) = breezy_git::bzr_url_to_git_url(location)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(("Invalid URL",)))?;
    Ok((url, revno, branch))
}

#[pymodule]
pub fn _git_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(bzr_url_to_git_url))?;
    Ok(())
}
