use pyo3::exceptions::PyTypeError;
use pyo3::exceptions::PyValueError;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use std::collections::HashMap;
use std::path::PathBuf;

import_exception!(dromedary.urlutils, InvalidURLJoin);
import_exception!(dromedary.urlutils, InvalidURL);
import_exception!(dromedary.errors, PathNotChild);

#[pyfunction]
fn is_url(url: &str) -> bool {
    dromedary_urlutils::is_url(url)
}

#[pyfunction]
#[pyo3(signature = (url, exclude_trailing_slash = true))]
fn split(url: &str, exclude_trailing_slash: Option<bool>) -> (String, String) {
    dromedary_urlutils::split(url, exclude_trailing_slash.unwrap_or(true))
}

#[pyfunction]
fn _find_scheme_and_separator(url: &str) -> (Option<usize>, Option<usize>) {
    dromedary_urlutils::find_scheme_and_separator(url)
}

#[pyfunction]
fn strip_trailing_slash(url: &str) -> &str {
    dromedary_urlutils::strip_trailing_slash(url)
}

#[pyfunction]
#[pyo3(signature = (url, exclude_trailing_slash = true))]
fn dirname(url: &str, exclude_trailing_slash: Option<bool>) -> String {
    dromedary_urlutils::dirname(url, exclude_trailing_slash.unwrap_or(true))
}

#[pyfunction]
#[pyo3(signature = (url, exclude_trailing_slash = true))]
fn basename(url: &str, exclude_trailing_slash: Option<bool>) -> String {
    dromedary_urlutils::basename(url, exclude_trailing_slash.unwrap_or(true))
}

fn map_urlutils_error_to_pyerr(e: dromedary_urlutils::Error) -> PyErr {
    match e {
        dromedary_urlutils::Error::AboveRoot(base, path) => {
            InvalidURLJoin::new_err(("Above root", base, path))
        }
        dromedary_urlutils::Error::SubsegmentMissesEquals(segment) => {
            InvalidURL::new_err(("Subsegment misses equals", segment))
        }
        dromedary_urlutils::Error::UnsafeCharacters(c) => {
            InvalidURL::new_err(("Unsafe characters", c))
        }
        dromedary_urlutils::Error::IoError(err) => err.into(),
        dromedary_urlutils::Error::SegmentParameterKeyContainsEquals(url, segment) => {
            InvalidURLJoin::new_err(("Segment parameter contains equals (=)", url, segment))
        }
        dromedary_urlutils::Error::SegmentParameterContainsComma(url, segments) => {
            InvalidURLJoin::new_err(("Segment parameter contains comma (,)", url, segments))
        }
        dromedary_urlutils::Error::NotLocalUrl(url) => InvalidURL::new_err(("Not a local url", url)),
        dromedary_urlutils::Error::UrlNotAscii(url) => InvalidURL::new_err(("URL not ascii", url)),
        dromedary_urlutils::Error::InvalidUNCUrl(url) => InvalidURL::new_err(("Invalid UNC URL", url)),
        dromedary_urlutils::Error::InvalidWin32LocalUrl(url) => {
            InvalidURL::new_err(("Invalid Win32 local URL", url))
        }
        dromedary_urlutils::Error::InvalidWin32Path(path) => {
            InvalidURL::new_err(("Invalid Win32 path", path))
        }
        dromedary_urlutils::Error::PathNotChild(path, start) => PathNotChild::new_err((path, start)),
        dromedary_urlutils::Error::UrlTooShort(url) => PyValueError::new_err(("URL too short", url)),
    }
}

#[pyfunction(signature = (url, *args))]
fn joinpath(url: &str, args: &Bound<PyTuple>) -> PyResult<String> {
    let mut path = Vec::new();
    for arg in args.iter() {
        if let Ok(arg) = arg.extract::<String>() {
            path.push(arg);
        } else {
            return Err(PyTypeError::new_err(
                "path must be a string or a list of strings",
            ));
        }
    }
    let path_ref = path.iter().map(|s| s.as_str()).collect::<Vec<&str>>();
    dromedary_urlutils::joinpath(url, path_ref.as_slice()).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction(signature = (url, *args))]
fn join(url: &str, args: &Bound<PyTuple>) -> PyResult<String> {
    let mut path = Vec::new();
    for arg in args.iter() {
        if let Ok(arg) = arg.extract::<String>() {
            path.push(arg);
        } else {
            return Err(PyTypeError::new_err(
                "path must be a string or a list of strings",
            ));
        }
    }
    let path_ref = path.iter().map(|s| s.as_str()).collect::<Vec<&str>>();
    dromedary_urlutils::join(url, path_ref.as_slice()).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn split_segment_parameters(url: &str) -> PyResult<(&str, HashMap<&str, &str>)> {
    dromedary_urlutils::split_segment_parameters(url).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn split_segment_parameters_raw(url: &str) -> (&str, Vec<&str>) {
    dromedary_urlutils::split_segment_parameters_raw(url)
}

#[pyfunction]
fn strip_segment_parameters(url: &str) -> &str {
    dromedary_urlutils::strip_segment_parameters(url)
}

#[pyfunction]
fn relative_url(base: &str, url: &str) -> String {
    dromedary_urlutils::relative_url(base, url)
}

#[pyfunction]
fn combine_paths(base_path: &str, relpath: &str) -> String {
    dromedary_urlutils::combine_paths(base_path, relpath)
}

#[pyfunction]
#[pyo3(signature = (text, safe = None))]
fn escape(py: Python, text: PyObject, safe: Option<&str>) -> PyResult<String> {
    if let Ok(text) = text.extract::<String>(py) {
        Ok(dromedary_urlutils::escape(text.as_bytes(), safe))
    } else if let Ok(text) = text.extract::<Vec<u8>>(py) {
        Ok(dromedary_urlutils::escape(text.as_slice(), safe))
    } else {
        Err(PyTypeError::new_err("text must be a string or bytes"))
    }
}

#[pyfunction]
fn normalize_url(url: &str) -> PyResult<String> {
    dromedary_urlutils::normalize_url(url).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn local_path_to_url(path: PathBuf) -> PyResult<String> {
    dromedary_urlutils::local_path_to_url(path.as_path()).map_err(|e| e.into())
}

#[pyfunction(name = "local_path_to_url")]
fn win32_local_path_to_url(path: PathBuf) -> PyResult<String> {
    dromedary_urlutils::win32::local_path_to_url(path).map_err(|e| e.into())
}

#[pyfunction(name = "local_path_to_url")]
fn posix_local_path_to_url(path: &str) -> PyResult<String> {
    dromedary_urlutils::posix::local_path_to_url(path).map_err(|e| e.into())
}

#[pyfunction(signature = (url, *args))]
fn join_segment_parameters_raw(url: &str, args: &Bound<PyTuple>) -> PyResult<String> {
    let mut path = Vec::new();
    for arg in args.iter() {
        if let Ok(arg) = arg.extract::<String>() {
            path.push(arg);
        } else {
            return Err(PyTypeError::new_err(
                "path must be a string or a list of strings",
            ));
        }
    }
    let path_ref = path.iter().map(|s| s.as_str()).collect::<Vec<&str>>();
    dromedary_urlutils::join_segment_parameters_raw(url, path_ref.as_slice())
        .map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn join_segment_parameters(url: &str, parameters: HashMap<String, String>) -> PyResult<String> {
    let parameters = parameters
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_str()))
        .collect();
    dromedary_urlutils::join_segment_parameters(url, &parameters).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn local_path_from_url(url: &str) -> PyResult<String> {
    let path = dromedary_urlutils::local_path_from_url(url).map_err(map_urlutils_error_to_pyerr)?;

    match path.to_str() {
        Some(path) => Ok(path.to_string()),
        None => Err(PyValueError::new_err("Path is not valid UTF-8")),
    }
}

#[pyfunction(name = "local_path_from_url")]
fn win32_local_path_from_url(url: &str) -> PyResult<String> {
    let path =
        dromedary_urlutils::win32::local_path_from_url(url).map_err(map_urlutils_error_to_pyerr)?;

    match path.to_str() {
        Some(path) => Ok(path.to_string()),
        None => Err(PyValueError::new_err("Path is not valid UTF-8")),
    }
}

/// On win32 the drive letter needs to be added to the url base.
#[pyfunction(name = "extract_drive_letter")]
fn win32_extract_drive_letter(url_base: &str, path: &str) -> PyResult<(String, String)> {
    dromedary_urlutils::win32::extract_drive_letter(url_base, path)
        .map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction(name = "strip_local_trailing_slash")]
fn win32_strip_local_trailing_slash(url: &str) -> String {
    dromedary_urlutils::win32::strip_local_trailing_slash(url)
}

#[pyfunction(name = "local_path_from_url")]
fn posix_local_path_from_url(url: &str) -> PyResult<String> {
    let path =
        dromedary_urlutils::posix::local_path_from_url(url).map_err(map_urlutils_error_to_pyerr)?;

    match path.to_str() {
        Some(path) => Ok(path.to_string()),
        None => Err(PyValueError::new_err("Path is not valid UTF-8")),
    }
}

#[pyfunction]
fn unescape(text: &str) -> PyResult<String> {
    dromedary_urlutils::unescape(text).map_err(map_urlutils_error_to_pyerr)
}

#[pyfunction]
fn derive_to_location(base: &str) -> String {
    dromedary_urlutils::derive_to_location(base)
}

#[pyfunction]
fn file_relpath(base: &str, path: &str) -> PyResult<String> {
    dromedary_urlutils::file_relpath(base, path).map_err(map_urlutils_error_to_pyerr)
}

#[pymodule]
fn _urlutils_rs(py: Python, m: &Bound<PyModule>) -> PyResult<()> {
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
    m.add_function(wrap_pyfunction!(file_relpath, m)?)?;
    let win32m = PyModule::new(py, "win32")?;
    win32m.add_function(wrap_pyfunction!(win32_local_path_to_url, &win32m)?)?;
    win32m.add_function(wrap_pyfunction!(win32_local_path_from_url, &win32m)?)?;
    win32m.add_function(wrap_pyfunction!(win32_extract_drive_letter, &win32m)?)?;
    win32m.add_function(wrap_pyfunction!(win32_strip_local_trailing_slash, &win32m)?)?;
    m.add_submodule(&win32m)?;
    let posixm = PyModule::new(py, "posix")?;
    posixm.add_function(wrap_pyfunction!(posix_local_path_to_url, &posixm)?)?;
    posixm.add_function(wrap_pyfunction!(posix_local_path_from_url, &posixm)?)?;
    m.add_submodule(&posixm)?;

    // PyO3 submodule hack for proper import support
    let sys = py.import("sys")?;
    let modules = sys.getattr("modules")?;
    let module_name = m.name()?;

    // Register submodules in sys.modules for dotted import support
    modules.set_item(format!("{}.win32", module_name), &win32m)?;
    modules.set_item(format!("{}.posix", module_name), &posixm)?;

    Ok(())
}
