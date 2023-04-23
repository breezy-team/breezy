use pyo3::prelude::*;
use pyo3_file::PyFileLikeObject;
use std::io::{Read, Seek};

#[pyfunction]
fn coalesce_offsets(
    offsets: Vec<(usize, usize)>,
    limit: Option<usize>,
    fudge_factor: Option<usize>,
    max_size: Option<usize>,
) -> Vec<(usize, usize, Vec<(usize, usize)>)> {
    breezy_transport::readv::coalesce_offsets(offsets.as_slice(), limit, fudge_factor, max_size)
}

#[pyfunction]
fn seek_and_read(
    file: PyObject,
    offsets: Vec<(usize, usize)>,
    max_readv_combine: usize,
    bytes_to_read_before_seek: usize,
) -> PyResult<Vec<(usize, Vec<u8>)>> {
    let f = PyFileLikeObject::with_requirements(file, true, false, true)?;
    let data = breezy_transport::readv::seek_and_read(
        f,
        offsets.as_slice(),
        max_readv_combine,
        bytes_to_read_before_seek,
    )?;

    Ok(data.collect())
}

#[pymodule]
fn _transport_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(seek_and_read))?;
    m.add_wrapped(wrap_pyfunction!(coalesce_offsets))?;
    Ok(())
}
