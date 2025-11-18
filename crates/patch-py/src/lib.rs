use pyo3::create_exception;
use pyo3::exceptions::PyValueError;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyIterator, PyList};
use pyo3::wrap_pyfunction;
use pyo3_filelike::PyBinaryFile;
use std::ffi::OsString;
use std::io::Write;
use std::os::unix::ffi::OsStringExt;
use std::path::PathBuf;

create_exception!(_patch_rs, PatchInvokeError, pyo3::exceptions::PyException);
create_exception!(_patch_rs, PatchFailed, pyo3::exceptions::PyException);
create_exception!(_patch_rs, BinaryFiles, pyo3::exceptions::PyException);
create_exception!(_patch_rs, PatchSyntax, pyo3::exceptions::PyException);
create_exception!(
    _patch_rs,
    MalformedPatchHeader,
    pyo3::exceptions::PyException
);
import_exception!(breezy.errors, BinaryFile);

#[pyfunction]
#[pyo3(signature = (patch_contents, filename, output_filename = None, reverse = None))]
fn patch(
    patch_contents: Vec<Vec<u8>>,
    filename: PathBuf,
    output_filename: Option<PathBuf>,
    reverse: Option<bool>,
) -> PyResult<i32> {
    let output_path = output_filename.as_deref();
    breezy_patch::invoke::patch(
        patch_contents.iter().map(|x| x.as_slice()),
        filename.as_path(),
        output_path,
        reverse.unwrap_or(false),
    )
    .map_err(invoke_err_to_py_err)
}

#[pyfunction]
fn diff3(
    out_file: PathBuf,
    mine_path: PathBuf,
    older_path: PathBuf,
    yours_path: PathBuf,
) -> PyResult<i32> {
    breezy_patch::invoke::diff3(
        out_file.as_path(),
        mine_path.as_path(),
        older_path.as_path(),
        yours_path.as_path(),
    )
    .map_err(invoke_err_to_py_err)
}

#[pyfunction]
#[pyo3(signature = (directory, patches, strip = None, reverse = None, dry_run = None, quiet = None, target_file = None, out = None, _patch_cmd = None))]
#[allow(clippy::too_many_arguments)]
fn run_patch(
    directory: PathBuf,
    patches: Vec<Vec<u8>>,
    strip: Option<u32>,
    reverse: Option<bool>,
    dry_run: Option<bool>,
    quiet: Option<bool>,
    target_file: Option<&str>,
    out: Option<Py<PyAny>>,
    _patch_cmd: Option<&str>,
) -> PyResult<()> {
    let mut out: Box<dyn Write> = if let Some(obj) = out {
        Box::new(PyBinaryFile::from(obj))
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
        target_file,
        &mut out,
        _patch_cmd,
    )
    .map_err(invoke_err_to_py_err)
}

fn invoke_err_to_py_err(err: breezy_patch::invoke::Error) -> PyErr {
    match err {
        breezy_patch::invoke::Error::Io(err) => err.into(),
        breezy_patch::invoke::Error::BinaryFile(path) => BinaryFile::new_err(path),
        breezy_patch::invoke::Error::PatchInvokeError(errstr, stderr, inner) => {
            PatchInvokeError::new_err((errstr, stderr, inner.map(|x| x.to_string())))
        }
        breezy_patch::invoke::Error::PatchFailed(exitcode, stderr) => {
            PatchFailed::new_err((exitcode, stderr))
        }
    }
}

#[pyfunction]
fn iter_patched_from_hunks(
    py: Python,
    orig_lines: Py<PyAny>,
    hunks: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let orig_lines = orig_lines.extract::<Vec<Vec<u8>>>(py)?;
    let hunks = hunks.extract::<Vec<Vec<u8>>>(py)?;
    let patched_lines = breezy_patch::invoke::iter_patched_from_hunks(
        orig_lines.iter().map(|x| x.as_slice()),
        hunks.iter().map(|x| x.as_slice()),
    )
    .map_err(invoke_err_to_py_err)?;

    let pl = vec![PyBytes::new(py, &patched_lines)];
    Ok(PyList::new(py, &pl)?.into())
}

fn parse_err_to_py_err(err: breezy_patch::parse::Error) -> PyErr {
    match err {
        breezy_patch::parse::Error::BinaryFiles(path1, path2) => BinaryFiles::new_err((
            PathBuf::from(OsString::from_vec(path1))
                .to_string_lossy()
                .to_string(),
            PathBuf::from(OsString::from_vec(path2))
                .to_string_lossy()
                .to_string(),
        )),
        breezy_patch::parse::Error::PatchSyntax(err, _line) => PatchSyntax::new_err(err),
        breezy_patch::parse::Error::MalformedPatchHeader(err, _line) => {
            MalformedPatchHeader::new_err(err)
        }
    }
}

#[pyfunction]
fn get_patch_names<'a>(
    py: Python<'a>,
    patch_contents: Bound<'a, PyIterator>,
) -> PyResult<(
    (Bound<'a, PyBytes>, Option<Bound<'a, PyBytes>>),
    (Bound<'a, PyBytes>, Option<Bound<'a, PyBytes>>),
)> {
    let names = breezy_patch::parse::get_patch_names(
        patch_contents.map(|x| x.unwrap().extract::<Vec<u8>>().unwrap()),
    )
    .map_err(parse_err_to_py_err)?;

    let py_orig = (
        PyBytes::new(py, &names.0 .0),
        names.0 .1.map(|x| PyBytes::new(py, &x)),
    );
    let py_mod = (
        PyBytes::new(py, &names.1 .0),
        names.1 .1.map(|x| PyBytes::new(py, &x)),
    );
    Ok((py_orig, py_mod))
}

#[pyfunction]
fn iter_lines_handle_nl<'a>(
    py: Python<'a>,
    iter_lines: Bound<'a, PyAny>,
) -> PyResult<Bound<'a, PyIterator>> {
    let py_iter = iter_lines.try_iter()?;
    let lines = breezy_patch::parse::iter_lines_handle_nl(
        py_iter.map(|x| x.unwrap().extract::<Vec<u8>>().unwrap()),
    );
    let pl = lines.map(|x| PyBytes::new(py, &x)).collect::<Vec<_>>();
    PyList::new(py, &pl)?.try_iter()
}

#[pyfunction]
fn parse_range(textrange: &str) -> PyResult<(i32, i32)> {
    breezy_patch::parse::parse_range(textrange)
        .map_err(|err| PyValueError::new_err(format!("Invalid range: {}", err)))
}

#[pyfunction]
fn difference_index(atext: &[u8], btext: &[u8]) -> PyResult<Option<usize>> {
    Ok(breezy_patch::parse::difference_index(atext, btext))
}

#[pyfunction]
fn parse_patch_date(date: &str) -> PyResult<(i64, i64)> {
    breezy_patch::timestamp::parse_patch_date(date).map_err(|err| match err {
        breezy_patch::timestamp::ParsePatchDateError::InvalidDate(d) => {
            PyValueError::new_err(format!("Invalid date: {}", d))
        }
        breezy_patch::timestamp::ParsePatchDateError::InvalidTimezoneOffset(offset) => {
            PyValueError::new_err(format!("Invalid timezone offset: {}", offset))
        }
        breezy_patch::timestamp::ParsePatchDateError::MissingTimezoneOffset(date) => {
            PyValueError::new_err(format!("missing a timezone offset: {}", date))
        }
    })
}

#[pyfunction]
#[pyo3(signature = (secs, offset = None))]
fn format_patch_date(py: Python, secs: Py<PyAny>, offset: Option<Py<PyAny>>) -> PyResult<String> {
    let secs = if let Ok(secs) = secs.extract::<i64>(py) {
        secs
    } else if let Ok(secs) = secs.extract::<f64>(py) {
        secs as i64
    } else {
        return Err(PyValueError::new_err("Invalid secs"));
    };
    let offset = if let Some(offset) = offset {
        if let Ok(offset) = offset.extract::<i64>(py) {
            Some(offset)
        } else if let Ok(offset) = offset.extract::<f64>(py) {
            Some(offset as i64)
        } else {
            return Err(PyValueError::new_err("Invalid offset"));
        }
    } else {
        None
    };
    breezy_patch::timestamp::format_patch_date(secs, offset.unwrap_or(0))
        .map_err(|err| PyValueError::new_err(format!("Invalid date: {:?}", err)))
}

#[pymodule]
fn _patch_rs(py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(patch))?;
    m.add_wrapped(wrap_pyfunction!(diff3))?;
    m.add_wrapped(wrap_pyfunction!(run_patch))?;
    m.add_wrapped(wrap_pyfunction!(iter_patched_from_hunks))?;
    m.add_wrapped(wrap_pyfunction!(get_patch_names))?;
    m.add_wrapped(wrap_pyfunction!(iter_lines_handle_nl))?;
    m.add_wrapped(wrap_pyfunction!(parse_range))?;
    m.add_wrapped(wrap_pyfunction!(difference_index))?;
    m.add_wrapped(wrap_pyfunction!(parse_patch_date))?;
    m.add_wrapped(wrap_pyfunction!(format_patch_date))?;
    m.add("PatchInvokeError", py.get_type::<PatchInvokeError>())?;
    m.add("PatchFailed", py.get_type::<PatchFailed>())?;
    m.add("PatchSyntax", py.get_type::<PatchSyntax>())?;
    m.add(
        "MalformedPatchHeader",
        py.get_type::<MalformedPatchHeader>(),
    )?;
    m.add("BinaryFiles", py.get_type::<BinaryFiles>())?;
    Ok(())
}
