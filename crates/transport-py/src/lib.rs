use pyo3::exceptions::PyValueError;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3_file::PyFileLikeObject;
use std::io::{Read, Seek};

import_exception!(breezy.errors, ShortReadvError);

#[pyfunction]
fn coalesce_offsets(
    offsets: Vec<(usize, usize)>,
    mut limit: Option<usize>,
    mut fudge_factor: Option<usize>,
    mut max_size: Option<usize>,
) -> PyResult<Vec<(usize, usize, Vec<(usize, usize)>)>> {
    if limit == Some(0) {
        limit = None;
    }
    if fudge_factor == Some(0) {
        fudge_factor = None;
    }
    if max_size == Some(0) {
        max_size = None;
    }
    breezy_transport::readv::coalesce_offsets(offsets.as_slice(), limit, fudge_factor, max_size)
        .map_err(|e| PyValueError::new_err(format!("{}", e)))
}

const DEFAULT_MAX_READV_COMBINE: usize = 50;
const DEFAULT_BYTES_TO_READ_BEFORE_SEEK: usize = 0;

#[pyfunction]
fn seek_and_read(
    py: Python,
    file: PyObject,
    offsets: Vec<(usize, usize)>,
    max_readv_combine: Option<usize>,
    bytes_to_read_before_seek: Option<usize>,
    path: Option<&str>,
) -> PyResult<Vec<(usize, PyObject)>> {
    let f = PyFileLikeObject::with_requirements(file, true, false, true)?;
    let data = breezy_transport::readv::seek_and_read(
        f,
        offsets,
        max_readv_combine.unwrap_or(DEFAULT_MAX_READV_COMBINE),
        bytes_to_read_before_seek.unwrap_or(DEFAULT_BYTES_TO_READ_BEFORE_SEEK),
    )
    .map_err(|e| -> PyErr { e.into() })?;

    data.into_iter()
        .map(|e| {
            e.map(|(offset, data)| (offset, PyBytes::new(py, data.as_slice()).into()))
                .map_err(|(e, offset, length, actual)| match e.kind() {
                    std::io::ErrorKind::UnexpectedEof => ShortReadvError::new_err((
                        path.map(|p| p.to_string()),
                        offset,
                        length,
                        actual,
                    )),
                    _ => e.into(),
                })
        })
        .collect::<Result<Vec<_>, _>>()
}

#[pyfunction]
fn sort_expand_and_combine(
    offsets: Vec<(u64, usize)>,
    upper_limit: Option<u64>,
    recommended_page_size: Option<usize>,
) -> Vec<(u64, usize)> {
    breezy_transport::readv::sort_expand_and_combine(
        offsets,
        upper_limit,
        recommended_page_size.unwrap_or(4 * 1024),
    )
}

#[pymodule]
fn _transport_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(seek_and_read))?;
    m.add_wrapped(wrap_pyfunction!(coalesce_offsets))?;
    m.add_wrapped(wrap_pyfunction!(sort_expand_and_combine))?;
    Ok(())
}
