//! Bindings for patchkit's unified-diff parser.
//!
//! Python's patch code models a hunk line as three classes sharing a `HunkLine`
//! base, and both `breezy.colordiff` and the test suite construct them directly
//! and test them with `isinstance`. Rust models the same thing as one enum, so
//! the classes here are a subclass trio that converts to and from that enum at
//! the boundary.

use patchkit::unified::{self, Hunk as RsHunk, HunkLine as RsHunkLine};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList};

// These stay Python-side: they are BzrError subclasses whose `_fmt` strings
// produce the messages callers such as breezy.colordiff and breezy.shelf_ui
// already catch and display.
import_exception!(breezy.patches, MalformedLine);
import_exception!(breezy.patches, MalformedHunkHeader);
import_exception!(breezy.patches, PatchConflict);

/// Map a patchkit parse error onto the corresponding breezy exception, so that
/// existing `except` clauses and error text keep working.
pub(crate) fn parse_error_to_py(err: unified::Error) -> PyErr {
    match err {
        unified::Error::BinaryFiles(orig, modified) => crate::BinaryFiles::new_err((
            String::from_utf8_lossy(&orig).into_owned(),
            String::from_utf8_lossy(&modified).into_owned(),
        )),
        unified::Error::PatchSyntax(msg, line) => crate::PatchSyntax::new_err((msg, line.to_vec())),
        unified::Error::MalformedPatchHeader(msg, line) => {
            crate::MalformedPatchHeader::new_err((msg, line.to_vec()))
        }
        unified::Error::MalformedHunkHeader(msg, line) => {
            MalformedHunkHeader::new_err((msg, line.to_vec()))
        }
    }
}

#[pyclass(subclass, skip_from_py_object, module = "breezy._patch_rs")]
#[derive(Clone)]
pub struct HunkLine {
    contents: Vec<u8>,
}

#[pymethods]
impl HunkLine {
    #[new]
    fn new(contents: Vec<u8>) -> Self {
        HunkLine { contents }
    }

    #[getter]
    fn contents<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.contents)
    }

    fn get_str<'py>(&self, py: Python<'py>, leadchar: &[u8]) -> Bound<'py, PyBytes> {
        let mut out = leadchar.to_vec();
        out.extend_from_slice(&self.contents);
        if !self.contents.ends_with(b"\n") {
            out.push(b'\n');
            out.extend_from_slice(unified::NO_NL);
        }
        PyBytes::new(py, &out)
    }

    fn as_bytes(&self) -> PyResult<Py<PyAny>> {
        Err(pyo3::exceptions::PyNotImplementedError::new_err(()))
    }
}

macro_rules! hunk_line_subclass {
    ($name:ident, $lead:expr) => {
        #[pyclass(extends=HunkLine, subclass, module = "breezy._patch_rs")]
        pub struct $name;

        #[pymethods]
        impl $name {
            #[new]
            fn new(contents: Vec<u8>) -> (Self, HunkLine) {
                ($name, HunkLine { contents })
            }

            fn as_bytes<'py>(self_: PyRef<'py, Self>, py: Python<'py>) -> Bound<'py, PyBytes> {
                self_.as_super().get_str(py, $lead)
            }
        }
    };
}

hunk_line_subclass!(ContextLine, b" ");
hunk_line_subclass!(InsertLine, b"+");
hunk_line_subclass!(RemoveLine, b"-");

/// Build the Python wrapper for a hunk line.
fn hunk_line_to_py(py: Python<'_>, line: &RsHunkLine) -> PyResult<Py<PyAny>> {
    let contents = line.contents().to_vec();
    Ok(match line {
        RsHunkLine::ContextLine(_) => Py::new(py, ContextLine::new(contents))?.into_any(),
        RsHunkLine::InsertLine(_) => Py::new(py, InsertLine::new(contents))?.into_any(),
        RsHunkLine::RemoveLine(_) => Py::new(py, RemoveLine::new(contents))?.into_any(),
    })
}

#[pyfunction]
pub fn parse_line(py: Python<'_>, line: &[u8]) -> PyResult<Py<PyAny>> {
    match RsHunkLine::parse_line(line) {
        Ok(l) => hunk_line_to_py(py, &l),
        Err(_) => Err(MalformedLine::new_err((
            "Unknown line type",
            PyBytes::new(py, line).unbind(),
        ))),
    }
}

#[pyclass(from_py_object, module = "breezy._patch_rs")]
#[derive(Clone)]
pub struct Hunk {
    inner: RsHunk,
}

#[pymethods]
impl Hunk {
    #[new]
    #[pyo3(signature = (orig_pos, orig_range, mod_pos, mod_range, tail = None))]
    fn new(
        orig_pos: usize,
        orig_range: usize,
        mod_pos: usize,
        mod_range: usize,
        tail: Option<Vec<u8>>,
    ) -> Self {
        Hunk {
            inner: RsHunk::new(orig_pos, orig_range, mod_pos, mod_range, tail),
        }
    }

    #[getter]
    fn orig_pos(&self) -> usize {
        self.inner.orig_pos
    }

    #[setter]
    fn set_orig_pos(&mut self, value: usize) {
        self.inner.orig_pos = value;
    }

    #[getter]
    fn orig_range(&self) -> usize {
        self.inner.orig_range
    }

    #[setter]
    fn set_orig_range(&mut self, value: usize) {
        self.inner.orig_range = value;
    }

    #[getter]
    fn mod_pos(&self) -> usize {
        self.inner.mod_pos
    }

    #[setter]
    fn set_mod_pos(&mut self, value: usize) {
        self.inner.mod_pos = value;
    }

    #[getter]
    fn mod_range(&self) -> usize {
        self.inner.mod_range
    }

    #[setter]
    fn set_mod_range(&mut self, value: usize) {
        self.inner.mod_range = value;
    }

    #[getter]
    fn tail<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyBytes>> {
        self.inner.tail.as_ref().map(|t| PyBytes::new(py, t))
    }

    /// The hunk's lines, as Python line objects.
    #[getter]
    fn lines<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let lines = self
            .inner
            .lines
            .iter()
            .map(|l| hunk_line_to_py(py, l))
            .collect::<PyResult<Vec<_>>>()?;
        PyList::new(py, lines)
    }

    fn get_header<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.inner.get_header())
    }

    fn as_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.inner.as_bytes())
    }

    fn __bytes__<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        self.as_bytes(py)
    }

    fn shift_to_mod(&self, pos: usize) -> Option<isize> {
        self.inner.shift_to_mod(pos)
    }
}

#[pyfunction]
pub fn hunk_from_header(line: &[u8]) -> PyResult<Hunk> {
    match RsHunk::from_header(line) {
        Ok(h) => Ok(Hunk { inner: h }),
        Err(e) => Err(MalformedHunkHeader::new_err((e.to_string(), line.to_vec()))),
    }
}

/// Two binary files that differ. Carries no hunks.
#[pyclass(subclass, module = "breezy._patch_rs")]
pub struct BinaryPatch {
    #[pyo3(get)]
    oldname: Py<PyBytes>,
    #[pyo3(get)]
    newname: Py<PyBytes>,
}

#[pymethods]
impl BinaryPatch {
    #[new]
    fn new(oldname: Py<PyBytes>, newname: Py<PyBytes>) -> Self {
        BinaryPatch { oldname, newname }
    }

    fn as_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        let mut out = b"Binary files ".to_vec();
        out.extend_from_slice(self.oldname.as_bytes(py));
        out.extend_from_slice(b" and ");
        out.extend_from_slice(self.newname.as_bytes(py));
        out.extend_from_slice(b" differ\n");
        PyBytes::new(py, &out)
    }
}

/// A unified diff for a single file.
#[pyclass(extends=BinaryPatch, module = "breezy._patch_rs")]
pub struct Patch {
    inner: unified::UnifiedPatch,
}

impl Patch {
    fn build(py: Python<'_>, p: unified::UnifiedPatch) -> PyResult<Py<PyAny>> {
        let base = BinaryPatch {
            oldname: PyBytes::new(py, &p.orig_name).unbind(),
            newname: PyBytes::new(py, &p.mod_name).unbind(),
        };
        Ok(Py::new(py, (Patch { inner: p }, base))?.into_any())
    }
}

#[pymethods]
impl Patch {
    #[new]
    #[pyo3(signature = (oldname, newname, oldts = None, newts = None))]
    fn new(
        oldname: Vec<u8>,
        newname: Vec<u8>,
        oldts: Option<Vec<u8>>,
        newts: Option<Vec<u8>>,
        py: Python<'_>,
    ) -> (Self, BinaryPatch) {
        let base = BinaryPatch {
            oldname: PyBytes::new(py, &oldname).unbind(),
            newname: PyBytes::new(py, &newname).unbind(),
        };
        (
            Patch {
                inner: unified::UnifiedPatch::new(oldname, oldts, newname, newts),
            },
            base,
        )
    }

    #[getter]
    fn oldts<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyBytes>> {
        self.inner.orig_ts.as_ref().map(|t| PyBytes::new(py, t))
    }

    #[getter]
    fn newts<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyBytes>> {
        self.inner.mod_ts.as_ref().map(|t| PyBytes::new(py, t))
    }

    #[getter]
    fn hunks<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        PyList::new(
            py,
            self.inner
                .hunks
                .iter()
                .map(|h| Hunk { inner: h.clone() })
                .collect::<Vec<_>>(),
        )
    }

    fn get_header<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        let hunkless = unified::UnifiedPatch::new(
            self.inner.orig_name.clone(),
            self.inner.orig_ts.clone(),
            self.inner.mod_name.clone(),
            self.inner.mod_ts.clone(),
        );
        PyBytes::new(py, &hunkless.as_bytes())
    }

    fn as_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.inner.as_bytes())
    }

    /// (inserts, removes, hunk count)
    fn stats_values(&self) -> (usize, usize, usize) {
        let mut inserts = 0;
        let mut removes = 0;
        for hunk in &self.inner.hunks {
            for line in &hunk.lines {
                match line {
                    RsHunkLine::InsertLine(_) => inserts += 1,
                    RsHunkLine::RemoveLine(_) => removes += 1,
                    RsHunkLine::ContextLine(_) => {}
                }
            }
        }
        (inserts, removes, self.inner.hunks.len())
    }

    fn stats_str(&self) -> String {
        let (inserts, removes, hunks) = self.stats_values();
        format!("{inserts} inserts, {removes} removes in {hunks} hunks")
    }

    /// Where `position` in the original file ends up in the modified file, or
    /// None if the line was removed.
    fn pos_in_mod(&self, position: usize) -> Option<usize> {
        let mut newpos = position as isize;
        for hunk in &self.inner.hunks {
            newpos += hunk.shift_to_mod(position)?;
        }
        Some(newpos as usize)
    }

    fn iter_inserted<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let mut out: Vec<Py<PyAny>> = Vec::new();
        for hunk in &self.inner.hunks {
            let mut pos = hunk.mod_pos - 1;
            for line in &hunk.lines {
                match line {
                    RsHunkLine::InsertLine(_) => {
                        let item = (pos, hunk_line_to_py(py, line)?);
                        out.push(item.into_pyobject(py)?.into_any().unbind());
                        pos += 1;
                    }
                    RsHunkLine::ContextLine(_) => pos += 1,
                    RsHunkLine::RemoveLine(_) => {}
                }
            }
        }
        PyList::new(py, out)
    }
}

/// Wrap a parsed patch, which may be either a text or a binary patch.
fn patch_to_py(py: Python<'_>, p: unified::PlainOrBinaryPatch) -> PyResult<Py<PyAny>> {
    match p {
        unified::PlainOrBinaryPatch::Plain(p) => Patch::build(py, p),
        unified::PlainOrBinaryPatch::Binary(b) => Ok(Py::new(
            py,
            BinaryPatch {
                oldname: PyBytes::new(py, &b.0).unbind(),
                newname: PyBytes::new(py, &b.1).unbind(),
            },
        )?
        .into_any()),
    }
}

#[pyfunction]
#[pyo3(signature = (iter_lines, allow_dirty = false))]
pub fn parse_patch(
    py: Python<'_>,
    iter_lines: &Bound<'_, PyAny>,
    allow_dirty: bool,
) -> PyResult<Py<PyAny>> {
    let lines: Vec<Vec<u8>> = iter_lines
        .try_iter()?
        .map(|l| l?.extract::<Vec<u8>>())
        .collect::<PyResult<_>>()?;

    let patch = unified::parse_patch_dirty(lines.iter().map(|l| l.as_slice()), allow_dirty)
        .map_err(parse_error_to_py)?;
    patch_to_py(py, patch)
}

#[pyfunction]
#[pyo3(signature = (iter_lines, allow_dirty = false, keep_dirty = false))]
pub fn parse_patches<'py>(
    py: Python<'py>,
    iter_lines: &Bound<'_, PyAny>,
    allow_dirty: bool,
    keep_dirty: bool,
) -> PyResult<Bound<'py, PyList>> {
    let lines: Vec<Vec<u8>> = iter_lines
        .try_iter()?
        .map(|l| l?.extract::<Vec<u8>>())
        .collect::<PyResult<_>>()?;

    let mut out: Vec<Py<PyAny>> = Vec::new();
    for result in unified::parse_patches_dirty(lines.into_iter(), allow_dirty, keep_dirty) {
        let dirty = result.map_err(parse_error_to_py)?;
        let patch = patch_to_py(py, dirty.patch)?;
        if keep_dirty {
            // Callers distinguish the two shapes with `"dirty_head" in patch`.
            let d = pyo3::types::PyDict::new(py);
            d.set_item("patch", patch)?;
            d.set_item(
                "dirty_head",
                PyList::new(
                    py,
                    dirty
                        .dirty_head
                        .iter()
                        .map(|l| PyBytes::new(py, l))
                        .collect::<Vec<_>>(),
                )?,
            )?;
            out.push(d.into_any().unbind());
        } else {
            out.push(patch);
        }
    }
    PyList::new(py, out)
}

#[pyfunction]
#[pyo3(signature = (iter_lines, allow_dirty = false))]
pub fn iter_hunks<'py>(
    py: Python<'py>,
    iter_lines: &Bound<'_, PyAny>,
    allow_dirty: bool,
) -> PyResult<Bound<'py, PyList>> {
    let lines: Vec<Vec<u8>> = iter_lines
        .try_iter()?
        .map(|l| l?.extract::<Vec<u8>>())
        .collect::<PyResult<_>>()?;

    let mut iter = lines.iter().map(|l| l.as_slice());
    let mut out: Vec<Hunk> = Vec::new();
    for hunk in unified::iter_hunks_dirty(&mut iter, allow_dirty) {
        out.push(Hunk {
            inner: hunk.map_err(parse_error_to_py)?,
        });
    }
    PyList::new(py, out)
}

/// Apply hunks to `orig_lines` exactly, raising PatchConflict on mismatch.
///
/// `orig_lines` may be None, meaning there is no original content, as when a
/// patch creates a file.
#[pyfunction]
pub fn iter_patched_from_hunks<'py>(
    py: Python<'py>,
    orig_lines: Option<&Bound<'py, PyAny>>,
    hunks: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyList>> {
    let orig: Vec<Vec<u8>> = match orig_lines {
        Some(lines) if !lines.is_none() => lines
            .try_iter()?
            .map(|l| l?.extract::<Vec<u8>>())
            .collect::<PyResult<_>>()?,
        _ => Vec::new(),
    };

    let mut rs_hunks: Vec<RsHunk> = Vec::new();
    for h in hunks.try_iter()? {
        let h = h?;
        let hunk: PyRef<'_, Hunk> = h.extract()?;
        rs_hunks.push(hunk.inner.clone());
    }

    let mut out: Vec<Py<PyBytes>> = Vec::new();
    for line in unified::iter_exact_patched_from_hunks(orig.into_iter(), rs_hunks.into_iter()) {
        let line = line.map_err(|e| {
            PatchConflict::new_err((
                e.line_no(),
                PyBytes::new(py, e.orig_line()).unbind(),
                PyBytes::new(py, e.patch_line()).unbind(),
            ))
        })?;
        out.push(PyBytes::new(py, &line).unbind());
    }
    PyList::new(py, out)
}
