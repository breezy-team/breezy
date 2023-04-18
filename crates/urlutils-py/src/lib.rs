use pyo3::exceptions::PyTypeError;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use std::collections::HashMap;

import_exception!(breezy.urlutils, InvalidURLJoin);
import_exception!(breezy.urlutils, InvalidURL);

#[pyfunction]
fn is_url(url: &str) -> bool {
    breezy_urlutils::is_url(url)
}

#[pyfunction]
fn split(url: &str, exclude_trailing_slash: Option<bool>) -> (String, String) {
    breezy_urlutils::split(url, exclude_trailing_slash.unwrap_or(true))
}

#[pyfunction]
fn _find_scheme_and_separator(url: &str) -> (Option<usize>, Option<usize>) {
    breezy_urlutils::find_scheme_and_separator(url)
}

#[pyfunction]
fn strip_trailing_slash(url: &str) -> &str {
    breezy_urlutils::strip_trailing_slash(url)
}

#[pyfunction]
fn dirname(url: &str, exclude_trailing_slash: Option<bool>) -> String {
    breezy_urlutils::dirname(url, exclude_trailing_slash.unwrap_or(true))
}

#[pyfunction]
fn basename(url: &str, exclude_trailing_slash: Option<bool>) -> String {
    breezy_urlutils::basename(url, exclude_trailing_slash.unwrap_or(true))
}

fn map_urlutils_error_to_pyerr(e: breezy_urlutils::Error) -> PyErr {
    match e {
        breezy_urlutils::Error::AboveRoot(base, path) => {
            InvalidURLJoin::new_err(("Above root", base, path))
        }
        breezy_urlutils::Error::SubsegmentMissesEquals(segment) => {
            InvalidURL::new_err(("Subsegment misses equals", segment))
        }
    }
}

#[pyfunction]
#[pyo3(signature = (url, *args))]
fn joinpath(url: &str, args: &PyTuple) -> PyResult<String> {
    let mut path = Vec::new();
    for arg in args.iter() {
        if let Ok(arg) = arg.extract::<&str>() {
            path.push(arg);
        } else {
            return Err(PyTypeError::new_err(
                "path must be a string or a list of strings",
            ));
        }
    }
    breezy_urlutils::joinpath(url, path.as_slice()).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
#[pyo3(signature = (url, *args))]
fn join(url: &str, args: &PyTuple) -> PyResult<String> {
    let mut path = Vec::new();
    for arg in args.iter() {
        if let Ok(arg) = arg.extract::<&str>() {
            path.push(arg);
        } else {
            return Err(PyTypeError::new_err(
                "path must be a string or a list of strings",
            ));
        }
    }
    breezy_urlutils::join(url, path.as_slice()).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn split_segment_parameters(url: &str) -> PyResult<(&str, HashMap<&str, &str>)> {
    breezy_urlutils::split_segment_parameters(url).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn split_segment_parameters_raw(url: &str) -> (&str, Vec<&str>) {
    breezy_urlutils::split_segment_parameters_raw(url)
}

#[pyfunction]
fn strip_segment_parameters(url: &str) -> &str {
    breezy_urlutils::strip_segment_parameters(url)
}

#[pyfunction]
fn relative_url(base: &str, url: &str) -> String {
    breezy_urlutils::relative_url(base, url)
}

#[pymodule]
fn _urlutils_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(is_url, m)?)?;
    m.add_function(wrap_pyfunction!(split, m)?)?;
    m.add_function(wrap_pyfunction!(_find_scheme_and_separator, m)?)?;
    m.add_function(wrap_pyfunction!(strip_trailing_slash, m)?)?;
    m.add_function(wrap_pyfunction!(dirname, m)?)?;
    m.add_function(wrap_pyfunction!(basename, m)?)?;
    m.add_function(wrap_pyfunction!(joinpath, m)?)?;
    m.add_function(wrap_pyfunction!(join, m)?)?;
    m.add_function(wrap_pyfunction!(split_segment_parameters, m)?)?;
    m.add_function(wrap_pyfunction!(split_segment_parameters_raw, m)?)?;
    m.add_function(wrap_pyfunction!(strip_segment_parameters, m)?)?;
    m.add_function(wrap_pyfunction!(relative_url, m)?)?;
    Ok(())
}
