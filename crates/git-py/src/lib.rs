use breezy_git::roundtrip::CommitSupplement;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Parse Bazaar roundtripping metadata into its component parts.
///
/// Returns `(revision_id, parent_ids, properties, testament3_sha1)`; the
/// caller assembles these into a `CommitSupplement`.
#[pyfunction]
fn parse_roundtripping_metadata(py: Python, text: &[u8]) -> PyResult<Py<PyAny>> {
    let md = breezy_git::roundtrip::parse_roundtripping_metadata(text)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>((e.to_string(),)))?;
    parsed_to_py(py, md)
}

fn parsed_to_py(py: Python, md: CommitSupplement) -> PyResult<Py<PyAny>> {
    let revision_id = md.revision_id.map(|v| PyBytes::new(py, &v).unbind());
    let parent_ids = md.explicit_parent_ids.map(|ids| {
        ids.into_iter()
            .map(|v| PyBytes::new(py, &v).unbind())
            .collect::<Vec<_>>()
    });
    let properties: Vec<(Py<PyBytes>, Py<PyBytes>)> = md
        .properties
        .into_iter()
        .map(|(k, v)| (PyBytes::new(py, &k).unbind(), PyBytes::new(py, &v).unbind()))
        .collect();
    let testament3 = md
        .verifiers
        .get(b"testament3-sha1".as_slice())
        .map(|v| PyBytes::new(py, v).unbind());
    Ok((revision_id, parent_ids, properties, testament3)
        .into_pyobject(py)?
        .unbind()
        .into())
}

/// Serialize roundtripping metadata from its component parts.
#[pyfunction]
#[pyo3(signature = (revision_id, explicit_parent_ids, properties, testament3_sha1))]
fn generate_roundtripping_metadata(
    py: Python,
    revision_id: Option<Vec<u8>>,
    explicit_parent_ids: Option<Vec<Vec<u8>>>,
    properties: Vec<(Vec<u8>, Vec<u8>)>,
    testament3_sha1: Option<Vec<u8>>,
) -> Py<PyBytes> {
    let mut md = CommitSupplement {
        revision_id,
        explicit_parent_ids,
        properties,
        ..Default::default()
    };
    if let Some(sha1) = testament3_sha1 {
        md.verifiers.insert(b"testament3-sha1".to_vec(), sha1);
    }
    let out = breezy_git::roundtrip::generate_roundtripping_metadata(&md);
    PyBytes::new(py, &out).unbind()
}

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
    m.add_wrapped(wrap_pyfunction!(parse_roundtripping_metadata))?;
    m.add_wrapped(wrap_pyfunction!(generate_roundtripping_metadata))?;
    Ok(())
}
