//! Python bindings for `breezy-readdir`.
//!
//! Exposes `UTF8DirReader` and `_Stat` matching the legacy
//! `breezy._readdir_pyx` Cython module.

#![cfg(unix)]

use breezy_readdir::{read_dir, Entry, Kind};
use nix::sys::stat::FileStat;
use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyTuple};

fn read_dir_error_to_pyerr(e: breezy_readdir::Error) -> PyErr {
    Python::attach(|py| {
        let filename = PyBytes::new(py, &e.path);
        PyOSError::new_err((e.errno as i32, e.errno.desc(), filename.unbind()))
    })
}

#[pyclass(name = "_Stat", module = "breezy._readdir_pyx")]
struct PyStat {
    inner: FileStat,
}

#[pymethods]
impl PyStat {
    // FileStat field widths differ across Unix platforms — the casts below
    // are no-ops on some targets (e.g. Linux x86_64) but real conversions on
    // others (32-bit Linux, macOS).
    #[allow(clippy::unnecessary_cast)]
    #[getter]
    fn st_dev(&self) -> u64 {
        self.inner.st_dev as u64
    }

    #[allow(clippy::unnecessary_cast)]
    #[getter]
    fn st_ino(&self) -> u64 {
        self.inner.st_ino as u64
    }

    #[allow(clippy::unnecessary_cast)]
    #[getter]
    fn st_mode(&self) -> u32 {
        self.inner.st_mode as u32
    }

    #[allow(clippy::unnecessary_cast)]
    #[getter]
    fn st_ctime(&self) -> i64 {
        self.inner.st_ctime as i64
    }

    #[allow(clippy::unnecessary_cast)]
    #[getter]
    fn st_mtime(&self) -> i64 {
        self.inner.st_mtime as i64
    }

    #[allow(clippy::unnecessary_cast)]
    #[getter]
    fn st_size(&self) -> i64 {
        self.inner.st_size as i64
    }

    fn __repr__(&self) -> String {
        // Matches legacy _readdir_pyx: repr of a 10-tuple shaped like os.stat
        // results, with most fields zeroed and atime as None.
        format!(
            "({}, 0, 0, 0, 0, 0, {}, None, {}, {})",
            self.st_mode(),
            self.st_size(),
            self.st_mtime(),
            self.st_ctime(),
        )
    }
}

#[pyclass(module = "breezy._readdir_pyx")]
struct UTF8DirReader;

#[pymethods]
impl UTF8DirReader {
    #[new]
    fn new() -> Self {
        UTF8DirReader
    }

    fn kind_from_mode(&self, mode: u32) -> &'static str {
        Kind::from_mode(mode as libc::mode_t).as_str()
    }

    #[pyo3(signature = (top, prefix=None))]
    fn top_prefix_to_starting_dir<'py>(
        &self,
        py: Python<'py>,
        top: Bound<'py, PyAny>,
        prefix: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyTuple>> {
        let osutils = py.import("breezy.osutils")?;
        let safe_utf8 = osutils.getattr("safe_utf8")?;

        let prefix_arg = prefix.unwrap_or_else(|| PyBytes::new(py, b"").into_any());
        let prefix_utf8 = safe_utf8.call1((prefix_arg,))?;
        let top_utf8 = safe_utf8.call1((top,))?;
        PyTuple::new(
            py,
            [
                prefix_utf8,
                py.None().into_bound(py),
                py.None().into_bound(py),
                py.None().into_bound(py),
                top_utf8,
            ],
        )
    }

    fn read_dir<'py>(
        &self,
        py: Python<'py>,
        prefix: &Bound<'py, PyBytes>,
        top: &Bound<'py, PyBytes>,
    ) -> PyResult<Vec<Bound<'py, PyTuple>>> {
        let prefix_bytes = prefix.as_bytes();
        let top_bytes = top.as_bytes();

        let entries: Vec<Entry> = py
            .detach(|| read_dir(top_bytes))
            .map_err(read_dir_error_to_pyerr)?;

        let relprefix: Vec<u8> = if prefix_bytes.is_empty() {
            Vec::new()
        } else {
            let mut v = Vec::with_capacity(prefix_bytes.len() + 1);
            v.extend_from_slice(prefix_bytes);
            v.push(b'/');
            v
        };

        let mut top_slash = Vec::with_capacity(top_bytes.len() + 1);
        top_slash.extend_from_slice(top_bytes);
        top_slash.push(b'/');

        let mut out = Vec::with_capacity(entries.len());
        for entry in entries {
            let mut path_from_top = Vec::with_capacity(relprefix.len() + entry.name.len());
            path_from_top.extend_from_slice(&relprefix);
            path_from_top.extend_from_slice(&entry.name);

            let mut abspath = Vec::with_capacity(top_slash.len() + entry.name.len());
            abspath.extend_from_slice(&top_slash);
            abspath.extend_from_slice(&entry.name);

            let kind = Kind::from_mode(entry.stat.st_mode as libc::mode_t).as_str();
            let stat = Py::new(py, PyStat { inner: entry.stat })?;

            let tuple = PyTuple::new(
                py,
                [
                    PyBytes::new(py, &path_from_top).into_any(),
                    PyBytes::new(py, &entry.name).into_any(),
                    kind.into_pyobject(py)?.into_any(),
                    stat.into_pyobject(py)?.into_any(),
                    PyBytes::new(py, &abspath).into_any(),
                ],
            )?;
            out.push(tuple);
        }
        Ok(out)
    }
}

#[pymodule]
fn _readdir_pyx(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyStat>()?;
    m.add_class::<UTF8DirReader>()?;
    Ok(())
}
