use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::{PyBytes, PyList, PyIterator};
use pyo3::exceptions::PyValueError;
use pyo3::create_exception;
use pyo3::import_exception;
use pyo3_file::PyFileLikeObject;
use std::path::PathBuf;
use std::io::Write;
use std::ffi::OsString;
use std::os::unix::ffi::OsStringExt;

create_exception!(_patch_rs, PatchInvokeError, pyo3::exceptions::PyException);
create_exception!(_patch_rs, PatchFailed, pyo3::exceptions::PyException);
create_exception!(_patch_rs, BinaryFiles, pyo3::exceptions::PyException);
create_exception!(_patch_rs, PatchSyntax, pyo3::exceptions::PyException);
create_exception!(_patch_rs, MalformedPatchHeader, pyo3::exceptions::PyException);
import_exception!(breezy.errors, BinaryFile);

#[pyfunction]
fn patch(patch_contents: Vec<Vec<u8>>, filename: PathBuf, output_filename: Option<PathBuf>, reverse: Option<bool>) -> PyResult<i32> {
    let output_path = output_filename.as_ref().map(|x| x.as_path());
    breezy_patch::invoke::patch(patch_contents.iter().map(|x| x.as_slice()), filename.as_path(), output_path, reverse.unwrap_or(false))
        .map_err(invoke_err_to_py_err)
}

#[pyfunction]
fn diff3(out_file: PathBuf, mine_path: PathBuf, older_path: PathBuf, yours_path: PathBuf) -> PyResult<i32> {
    breezy_patch::invoke::diff3(out_file.as_path(), mine_path.as_path(), older_path.as_path(), yours_path.as_path())
        .map_err(invoke_err_to_py_err)
}

#[pyfunction]
fn run_patch(directory: PathBuf, patches: Vec<Vec<u8>>, strip: Option<u32>, reverse: Option<bool>, dry_run: Option<bool>, quiet: Option<bool>, target_file: Option<&str>, out: Option<PyObject>, _patch_cmd: Option<&str>) -> PyResult<()> {
    let mut out: Box<dyn Write> = if let Some(obj) = out {
       Box::new(PyFileLikeObject::with_requirements(obj, false, true, false)?)
    } else {
        Box::new(std::io::stdout())
    };

    breezy_patch::invoke::run_patch(
            directory.as_path(),
            patches.iter().map(|x| x.as_slice()),
            strip.unwrap_or(0),
            reverse.unwrap_or(false),
            dry_run.unwrap_or(false),
            quiet.unwrap_or(true),
            target_file, &mut out,
            _patch_cmd)
        .map_err(invoke_err_to_py_err)
}

fn invoke_err_to_py_err(err: breezy_patch::invoke::Error) -> PyErr {
    match err {
        breezy_patch::invoke::Error::Io(err) => err.into(),
        breezy_patch::invoke::Error::BinaryFile(path) => BinaryFile::new_err(path),
        breezy_patch::invoke::Error::PatchInvokeError(errstr, stderr, inner) => {
            PatchInvokeError::new_err((errstr, stderr, inner.map(|x| x.to_string())))
        },
        breezy_patch::invoke::Error::PatchFailed(exitcode, stderr) => PatchFailed::new_err((exitcode, stderr)),
    }
}

#[pyfunction]
fn iter_patched_from_hunks(py: Python, orig_lines: PyObject, hunks: PyObject) -> PyResult<PyObject> {
    let orig_lines = orig_lines.extract::<Vec<Vec<u8>>>(py)?;
    let hunks = hunks.extract::<Vec<Vec<u8>>>(py)?;
    let patched_lines = breezy_patch::invoke::iter_patched_from_hunks(
        orig_lines.iter().map(|x| x.as_slice()),
        hunks.iter().map(|x| x.as_slice())).map_err(invoke_err_to_py_err)?;

    let pl = vec![PyBytes::new(py, &patched_lines)];
    Ok(PyList::new(py, &pl).into())
}

fn parse_err_to_py_err(err: breezy_patch::parse::Error) -> PyErr {
    match err {
        breezy_patch::parse::Error::BinaryFiles(path1, path2) => BinaryFiles::new_err((PathBuf::from(OsString::from_vec(path1)), PathBuf::from(OsString::from_vec(path2)))),
        breezy_patch::parse::Error::PatchSyntax(err, _line) => PatchSyntax::new_err(err),
        breezy_patch::parse::Error::MalformedPatchHeader(err, line) => MalformedPatchHeader::new_err(err),
    }
}

#[pyfunction]
fn get_patch_names(py: Python, patch_contents: PyObject) -> PyResult<((PyObject, Option<PyObject>), (PyObject, Option<PyObject>))> {
    let names = breezy_patch::parse::get_patch_names(
        patch_contents.downcast::<PyIterator>(py)?.map(|x| x.unwrap().extract::<Vec<u8>>().unwrap())).map_err(parse_err_to_py_err)?;

    let py_orig = (PyBytes::new(py, &names.0.0).to_object(py), names.0.1.map(|x| PyBytes::new(py, &x).to_object(py)));
    let py_mod = (PyBytes::new(py, &names.1.0).to_object(py), names.1.1.map(|x| PyBytes::new(py, &x).to_object(py)));
    Ok((py_orig, py_mod))
}

#[pyfunction]
fn iter_lines_handle_nl(py: Python, iter_lines: PyObject) -> PyResult<PyObject> {
    let py_iter = iter_lines.as_ref(py).iter()?;
    let lines = breezy_patch::parse::iter_lines_handle_nl(py_iter.map(|x| x.unwrap().extract::<Vec<u8>>().unwrap()));
    let pl = lines.map(|x| PyBytes::new(py, &x)).collect::<Vec<_>>();
    Ok(PyList::new(py, &pl).as_ref().iter()?.to_object(py))
}

#[pyfunction]
fn parse_range(textrange: &str) -> PyResult<(i32, i32)> {
    breezy_patch::parse::parse_range(textrange).map_err(
        |err| PyValueError::new_err(format!("Invalid range: {}", err)))
}

#[pyfunction]
fn difference_index(atext: &[u8], btext: &[u8]) -> PyResult<Option<usize>> {
    Ok(breezy_patch::parse::difference_index(atext, btext))
}

#[pymodule]
fn _patch_rs(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(patch))?;
    m.add_wrapped(wrap_pyfunction!(diff3))?;
    m.add_wrapped(wrap_pyfunction!(run_patch))?;
    m.add_wrapped(wrap_pyfunction!(iter_patched_from_hunks))?;
    m.add_wrapped(wrap_pyfunction!(get_patch_names))?;
    m.add_wrapped(wrap_pyfunction!(iter_lines_handle_nl))?;
    m.add_wrapped(wrap_pyfunction!(parse_range))?;
    m.add_wrapped(wrap_pyfunction!(difference_index))?;
    m.add("PatchInvokeError", py.get_type::<PatchInvokeError>())?;
    m.add("PatchFailed", py.get_type::<PatchFailed>())?;
    m.add("PatchSyntax", py.get_type::<PatchSyntax>())?;
    m.add("MalformedPatchHeader", py.get_type::<MalformedPatchHeader>())?;
    m.add("BinaryFiles", py.get_type::<BinaryFiles>())?;
    Ok(())
}
