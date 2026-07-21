use breezy_git::roundtrip::{CommitSupplement, SupplementParts};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

type PyParts = (
    Option<Py<PyBytes>>,
    Option<Vec<Py<PyBytes>>>,
    Vec<(Py<PyBytes>, Py<PyBytes>)>,
    Option<Py<PyBytes>>,
);

/// Convert the decomposed metadata parts to plain Python bytes objects.
fn parts_to_py(py: Python<'_>, parts: SupplementParts) -> PyParts {
    let revision_id = parts.revision_id.map(|v| PyBytes::new(py, &v).unbind());
    let parent_ids = parts.explicit_parent_ids.map(|ids| {
        ids.into_iter()
            .map(|v| PyBytes::new(py, &v).unbind())
            .collect()
    });
    let properties = parts
        .properties
        .into_iter()
        .map(|(k, v)| (PyBytes::new(py, &k).unbind(), PyBytes::new(py, &v).unbind()))
        .collect();
    let testament3 = parts.testament3_sha1.map(|v| PyBytes::new(py, &v).unbind());
    (revision_id, parent_ids, properties, testament3)
}

/// Parse Bazaar roundtripping metadata into its component parts.
///
/// Returns `(revision_id, parent_ids, properties, testament3_sha1)`; the
/// caller assembles these into a `CommitSupplement`.
#[pyfunction]
fn parse_roundtripping_metadata(py: Python<'_>, text: &[u8]) -> PyResult<PyParts> {
    let md = breezy_git::roundtrip::parse_roundtripping_metadata(text)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>((e.to_string(),)))?;
    Ok(parts_to_py(py, md.into_parts()))
}

/// Serialize roundtripping metadata from its component parts.
#[pyfunction]
#[pyo3(signature = (revision_id, explicit_parent_ids, properties, testament3_sha1))]
fn generate_roundtripping_metadata(
    py: Python<'_>,
    revision_id: Option<Vec<u8>>,
    explicit_parent_ids: Option<Vec<Vec<u8>>>,
    properties: Vec<(Vec<u8>, Vec<u8>)>,
    testament3_sha1: Option<Vec<u8>>,
) -> Py<PyBytes> {
    let md = CommitSupplement::from_parts(SupplementParts {
        revision_id,
        explicit_parent_ids,
        properties,
        testament3_sha1,
    });
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
