use pyo3::exceptions::PyTypeError;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use std::collections::HashMap;
use std::path::PathBuf;

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
        breezy_urlutils::Error::UnsafeCharacters(c) => {
            InvalidURL::new_err(("Unsafe characters", c))
        }
        breezy_urlutils::Error::IoError(err) => err.into(),
        breezy_urlutils::Error::SegmentParameterKeyContainsEquals(url, segment) =>
            InvalidURLJoin::new_err(("Segment parameter contains equals (=)", url, segment)),
        breezy_urlutils::Error::SegmentParameterContainsComma(url, segments) =>
            InvalidURLJoin::new_err(("Segment parameter contains comma (,)", url, segments)),
        breezy_urlutils::Error::NotLocalUrl(url) =>
            InvalidURL::new_err(("Not a local url", url)),
        breezy_urlutils::Error::UrlNotAscii(url) => InvalidURL::new_err(("URL not ascii", url)),
        breezy_urlutils::Error::InvalidUNCUrl(url) => InvalidURL::new_err(("Invalid UNC URL", url)),
        breezy_urlutils::Error::InvalidWin32LocalUrl(url) =>
            InvalidURL::new_err(("Invalid Win32 local URL", url)),
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

#[pyfunction]
fn combine_paths(base_path: &str, relpath: &str) -> String {
    breezy_urlutils::combine_paths(base_path, relpath)
}

#[pyfunction]
fn escape(py: Python, text: PyObject, safe: Option<&str>) -> PyResult<String> {
    let text = if let Ok(text) = text.extract::<&str>(py) {
        text.as_bytes()
    } else if let Ok(text) = text.extract::<&[u8]>(py) {
        text
    } else {
        return Err(PyTypeError::new_err("text must be a string or bytes"));
    };
    Ok(breezy_urlutils::escape(text, safe))
}

#[pyfunction]
fn normalize_url(url: &str) -> PyResult<String> {
    breezy_urlutils::normalize_url(url)
        .map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn local_path_to_url(path: &str) -> PyResult<String> {
    breezy_urlutils::local_path_to_url(path)
        .map_err(|e| e.into())
}

#[pyfunction(name = "local_path_to_url")]
fn win32_local_path_to_url(path: &str) -> PyResult<String> {
    breezy_urlutils::win32::local_path_to_url(path)
        .map_err(|e| e.into())
}

#[pyfunction(name = "local_path_to_url")]
fn posix_local_path_to_url(path: &str) -> PyResult<String> {
    breezy_urlutils::posix::local_path_to_url(path)
        .map_err(|e| e.into())
}

#[pyfunction]
#[pyo3(signature = (url, *args))]
fn join_segment_parameters_raw(url: &str, args: &PyTuple) -> PyResult<String> {
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
    breezy_urlutils::join_segment_parameters_raw(url, path.as_slice()).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn join_segment_parameters(url: &str, parameters: HashMap<&str, &str>) -> PyResult<String> {
    breezy_urlutils::join_segment_parameters(url, &parameters)
        .map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn local_path_from_url(url: &str) -> PyResult<PathBuf> {
    breezy_urlutils::local_path_from_url(url)
        .map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction(name="local_path_from_url")]
fn win32_local_path_from_url(url: &str) -> PyResult<PathBuf> {
    breezy_urlutils::win32::local_path_from_url(url)
        .map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction(name="local_path_from_url")]
fn posix_local_path_from_url(url: &str) -> PyResult<PathBuf> {
    breezy_urlutils::posix::local_path_from_url(url)
        .map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn unescape(text: &str) -> PyResult<String> {
    breezy_urlutils::unescape(text).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn derive_to_location(base: &str) -> String {
    breezy_urlutils::derive_to_location(base)
}

#[pymodule]
fn _urlutils_rs(py: Python, m: &PyModule) -> PyResult<()> {
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
    m.add_function(wrap_pyfunction!(join_segment_parameters_raw, m)?)?;
    m.add_function(wrap_pyfunction!(join_segment_parameters, m)?)?;
    m.add_function(wrap_pyfunction!(relative_url, m)?)?;
    m.add_function(wrap_pyfunction!(combine_paths, m)?)?;
    m.add_function(wrap_pyfunction!(escape, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_url, m)?)?;
    m.add_function(wrap_pyfunction!(local_path_to_url, m)?)?;
    m.add_function(wrap_pyfunction!(local_path_from_url, m)?)?;
    m.add_function(wrap_pyfunction!(unescape, m)?)?;
    m.add_function(wrap_pyfunction!(derive_to_location, m)?)?;
    let win32m = PyModule::new(py, "win32")?;
    win32m.add_function(wrap_pyfunction!(win32_local_path_to_url, win32m)?)?;
    win32m.add_function(wrap_pyfunction!(win32_local_path_from_url, win32m)?)?;
    m.add_submodule(win32m)?;
    let posixm = PyModule::new(py, "posix")?;
    posixm.add_function(wrap_pyfunction!(posix_local_path_to_url, posixm)?)?;
    posixm.add_function(wrap_pyfunction!(posix_local_path_from_url, posixm)?)?;
    m.add_submodule(posixm)?;
    Ok(())
}
