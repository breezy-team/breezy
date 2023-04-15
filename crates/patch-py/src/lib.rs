use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::{PyBytes, PyList};
use pyo3::create_exception;
use pyo3::import_exception;
use pyo3_file::PyFileLikeObject;
use std::path::PathBuf;
use std::io::Write;

create_exception!(_patch_rs, PatchInvokeError, pyo3::exceptions::PyException);
create_exception!(_patch_rs, PatchFailed, pyo3::exceptions::PyException);
import_exception!(breezy.errors, BinaryFile);

#[pyfunction]
fn patch(patch_contents: Vec<Vec<u8>>, filename: PathBuf, output_filename: Option<PathBuf>, reverse: Option<bool>) -> PyResult<i32> {
    let output_path = output_filename.as_ref().map(|x| x.as_path());
    breezy_patch::patch(patch_contents.iter().map(|x| x.as_slice()), filename.as_path(), output_path, reverse.unwrap_or(false))
        .map_err(patch_err_to_py_err)
}

#[pyfunction]
fn diff3(out_file: PathBuf, mine_path: PathBuf, older_path: PathBuf, yours_path: PathBuf) -> PyResult<i32> {
    breezy_patch::diff3(out_file.as_path(), mine_path.as_path(), older_path.as_path(), yours_path.as_path())
        .map_err(patch_err_to_py_err)
}

#[pyfunction]
fn run_patch(directory: PathBuf, patches: Vec<Vec<u8>>, strip: Option<u32>, reverse: Option<bool>, dry_run: Option<bool>, quiet: Option<bool>, target_file: Option<&str>, out: Option<PyObject>, _patch_cmd: Option<&str>) -> PyResult<()> {
    let mut out: Box<dyn Write> = if let Some(obj) = out {
       Box::new(PyFileLikeObject::with_requirements(obj, false, true, false)?)
    } else {
        Box::new(std::io::stdout())
    };

    breezy_patch::run_patch(
            directory.as_path(),
            patches.iter().map(|x| x.as_slice()),
            strip.unwrap_or(0),
            reverse.unwrap_or(false),
            dry_run.unwrap_or(false),
            quiet.unwrap_or(true),
            target_file, &mut out,
            _patch_cmd)
        .map_err(patch_err_to_py_err)
}

fn patch_err_to_py_err(err: breezy_patch::Error) -> PyErr {
    match err {
        breezy_patch::Error::Io(err) => err.into(),
        breezy_patch::Error::BinaryFile(path) => BinaryFile::new_err(path),
        breezy_patch::Error::PatchInvokeError(errstr, stderr, inner) => {
            PatchInvokeError::new_err((errstr, stderr, inner.map(|x| x.to_string())))
        },
        breezy_patch::Error::PatchFailed(exitcode, stderr) => PatchFailed::new_err((exitcode, stderr)),
    }
}

#[pyfunction]
fn iter_patched_from_hunks(py: Python, orig_lines: PyObject, hunks: PyObject) -> PyResult<PyObject> {
    let orig_lines = orig_lines.extract::<Vec<Vec<u8>>>(py)?;
    let hunks = hunks.extract::<Vec<Vec<u8>>>(py)?;
    let patched_lines = breezy_patch::iter_patched_from_hunks(
        orig_lines.iter().map(|x| x.as_slice()),
        hunks.iter().map(|x| x.as_slice())).map_err(patch_err_to_py_err)?;

    let pl = vec![PyBytes::new(py, &patched_lines)];
    Ok(PyList::new(py, &pl).into())
}

#[pymodule]
fn _patch_rs(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(patch))?;
    m.add_wrapped(wrap_pyfunction!(diff3))?;
    m.add_wrapped(wrap_pyfunction!(run_patch))?;
    m.add_wrapped(wrap_pyfunction!(iter_patched_from_hunks))?;
    m.add("PatchInvokeError", py.get_type::<PatchInvokeError>())?;
    m.add("PatchFailed", py.get_type::<PatchFailed>())?;
    Ok(())
}
