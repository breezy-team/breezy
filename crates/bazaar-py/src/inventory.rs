use bazaar::inventory::{describe_change, detect_changes, Entry, Error, Inventory as _};
use bazaar::inventory_delta::{
    InventoryDeltaEntry, InventoryDeltaInconsistency, InventoryDeltaParseError,
    InventoryDeltaSerializeError,
};
use bazaar::{FileId, RevisionId};
use breezy_osutils::Kind;
use pyo3::class::basic::CompareOp;
use pyo3::exceptions::{
    PyIndexError, PyKeyError, PyNotImplementedError, PyTypeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::pyclass_init::PyClassInitializer;
use pyo3::types::{PyBytes, PyDict, PyString};
use pyo3::wrap_pyfunction;
use pyo3::{create_exception, import_exception};
use std::collections::HashMap;
use std::collections::HashSet;
use std::collections::VecDeque;

use std::iter::FromIterator;

import_exception!(breezy.bzr.inventory, InvalidEntryName);
import_exception!(breezy.bzr.inventory, DuplicateFileId);
import_exception!(breezy.errors, NoSuchId);
import_exception!(breezy.errors, BzrCheckError);
import_exception!(breezy.errors, InvalidNormalization);
import_exception!(breezy.errors, InconsistentDelta);
import_exception!(breezy.errors, AlreadyVersionedError);
import_exception!(breezy.errors, BzrError);
import_exception!(breezy.errors, NotADirectory);
import_exception!(breezy.errors, NotVersionedError);
create_exception!(breezy.inventory_delta, IncompatibleInventoryDelta, BzrError);
create_exception!(breezy.inventory_delta, InventoryDeltaError, BzrError);

fn kind_from_str(kind: &str) -> Option<Kind> {
    match kind {
        "file" => Some(Kind::File),
        "directory" => Some(Kind::Directory),
        "tree-reference" => Some(Kind::TreeReference),
        "symlink" => Some(Kind::Symlink),
        _ => None,
    }
}

fn check_name(name: &str) -> PyResult<()> {
    if !is_valid_name(name) {
        Err(InvalidEntryName::new_err((name.to_string(),)))
    } else {
        Ok(())
    }
}

fn common_ie_check(
    slf: PyObject,
    ie: &Entry,
    py: Python,
    checker: &PyObject,
    rev_id: &RevisionId,
    inv: PyObject,
) -> PyResult<()> {
    if let Some(parent_id) = ie.parent_id() {
        let present = inv
            .call_method1(py, "has_id", (parent_id.to_object(py),))?
            .extract::<bool>(py)?;
        if !present {
            return Err(BzrCheckError::new_err(format!(
                "missing parent {{{}}} in inventory for revision {{{}}}",
                parent_id, rev_id
            )));
        }
    }

    checker.call_method1(py, "_add_entry_to_text_key_references", (inv, slf))?;

    Ok(())
}

#[pyclass(subclass)]
pub struct InventoryEntry(pub Entry);

#[pymethods]
impl InventoryEntry {
    fn has_text(&self) -> bool {
        matches!(&self.0, Entry::File { .. })
    }

    fn kind_character(&self) -> &'static str {
        self.0.kind().marker()
    }

    #[getter]
    fn kind(&self) -> &'static str {
        self.0.kind().to_string()
    }

    #[getter]
    fn get_name(&self) -> &str {
        match &self.0 {
            Entry::File { name, .. } => name,
            Entry::Directory { name, .. } => name,
            Entry::TreeReference { name, .. } => name,
            Entry::Link { name, .. } => name,
            Entry::Root { .. } => "",
        }
    }

    #[getter]
    fn get_file_id(&self, py: Python) -> PyObject {
        let file_id = &self.0.file_id();

        file_id.to_object(py)
    }

    #[getter]
    fn get_parent_id(&self, py: Python) -> Option<PyObject> {
        let parent_id = &self.0.parent_id();

        parent_id.map(|parent_id| parent_id.to_object(py))
    }

    #[getter]
    fn get_revision(&self, py: Python) -> Option<PyObject> {
        let revision = &self.0.revision();

        revision.as_ref().map(|revision| revision.to_object(py))
    }

    #[staticmethod]
    fn versionable_kind(kind: &str) -> bool {
        if let Some(kind) = kind_from_str(kind) {
            bazaar::inventory::versionable_kind(kind)
        } else {
            false
        }
    }

    #[getter]
    fn get_executable(&self) -> bool {
        match &self.0 {
            Entry::File { executable, .. } => *executable,
            _ => false,
        }
    }

    fn is_unmodified(&self, other: &InventoryEntry) -> bool {
        self.0.is_unmodified(&other.0)
    }

    fn detect_changes(&self, other: &InventoryEntry) -> (bool, bool) {
        detect_changes(&self.0, &other.0)
    }

    #[staticmethod]
    fn describe_change(slf: Option<&InventoryEntry>, other: Option<&InventoryEntry>) -> String {
        describe_change(slf.map(|s| &s.0), other.map(|o| &o.0)).to_string()
    }

    fn __richcmp__(&self, other: &InventoryEntry, op: CompareOp) -> PyResult<bool> {
        match op {
            CompareOp::Eq => Ok(self.0 == other.0),
            CompareOp::Ne => Ok(self.0 != other.0),
            _ => Err(PyNotImplementedError::new_err("")),
        }
    }

    fn _unchanged(&self, other: &InventoryEntry) -> bool {
        self.0.unchanged(&other.0)
    }

    fn derive(
        &self,
        revision: Option<RevisionId>,
        name: Option<String>,
        parent_id: Option<FileId>,
    ) -> InventoryEntry {
        let mut entry = self.0.clone();
        let revision = revision.or_else(|| entry.revision().cloned());
        let name = name.unwrap_or_else(|| entry.name().to_string());
        let parent_id = parent_id.or_else(|| entry.parent_id().cloned());
        match &mut entry {
            Entry::File {
                revision: r,
                name: n,
                parent_id: p,
                ..
            } => {
                *r = revision;
                *n = name;
                *p = parent_id.unwrap();
            }
            Entry::Directory {
                revision: r,
                name: n,
                parent_id: p,
                ..
            } => {
                *r = revision;
                *n = name;
                *p = parent_id.unwrap();
            }
            Entry::TreeReference {
                revision: r,
                name: n,
                parent_id: p,
                ..
            } => {
                *r = revision;
                *n = name;
                *p = parent_id.unwrap();
            }
            Entry::Link {
                revision: r,
                name: n,
                parent_id: p,
                ..
            } => {
                *r = revision;
                *n = name;
                *p = parent_id.unwrap();
            }
            Entry::Root { revision: r, .. } => {
                *r = revision;
            }
        }
        InventoryEntry(entry)
    }

    /// Find possible per-file graph parents.
    ///
    /// This is currently defined by:
    /// Select the last changed revision in the parent inventory.
    /// Do deal with a short lived bug in bzr 0.8's development two entries
    /// that have the same last changed but different 'x' bit settings are
    /// changed in-place.
    fn parent_candidates(
        &self,
        py: Python,
        previous_inventories: Vec<PyObject>,
    ) -> PyResult<PyObject> {
        // revision:ie mapping for each ie found in previous_inventories
        let mut candidates: HashMap<&RevisionId, PyObject> = HashMap::new();
        // identify candidate head revision ids
        for inv in previous_inventories {
            match inv.call_method1(py, "get_entry", (self.get_file_id(py),)) {
                Ok(py_entry) => {
                    if let Ok(mut entry) = py_entry.extract::<PyRefMut<InventoryEntry>>(py) {
                        if let Some(revision) = entry.0.revision() {
                            if let Some(candidate) = candidates.get_mut(revision) {
                                // same revision value in two different inventories:
                                // correct possible inconsistencies:
                                //  * there was a bug in revision updates with executable bit support
                                let mut candidate =
                                    candidate.extract::<PyRefMut<InventoryEntry>>(py)?;
                                match (&mut candidate.0, &mut entry.0) {
                                    (
                                        Entry::File {
                                            executable: candidate_executable,
                                            ..
                                        },
                                        Entry::File {
                                            executable: entry_executable,
                                            ..
                                        },
                                    ) => {
                                        if candidate_executable != entry_executable {
                                            *entry_executable = false;
                                            *candidate_executable = false;
                                        }
                                    }
                                    _ => {}
                                }
                            } else {
                                // add this revision as a candidate.
                                //candidates.insert(revision, py_entry);
                            }
                        }
                    }
                }
                Err(e) if e.is_instance_of::<NoSuchId>(py) => {}
                Err(e) => {
                    return Err(e);
                }
            }
        }
        let ret = PyDict::new(py);
        for (revision, entry) in candidates.iter() {
            ret.set_item(revision.to_object(py), entry)?;
        }
        Ok(ret.into_py(py))
    }
}

#[pyclass(subclass,extends=InventoryEntry)]
struct InventoryFile();

#[pymethods]
impl InventoryFile {
    #[new]
    fn new(
        file_id: FileId,
        name: String,
        parent_id: FileId,
        revision: Option<RevisionId>,
        text_sha1: Option<Vec<u8>>,
        text_size: Option<u64>,
        executable: Option<bool>,
        text_id: Option<Vec<u8>>,
    ) -> PyResult<(Self, InventoryEntry)> {
        let executable = executable.unwrap_or(false);
        check_name(name.as_str())?;
        let entry = Entry::File {
            file_id,
            name,
            parent_id,
            revision,
            text_sha1,
            text_size,
            text_id,
            executable,
        };
        Ok((Self(), InventoryEntry(entry)))
    }

    #[getter]
    fn get_executable(slf: PyRef<Self>) -> bool {
        match slf.into_super().0 {
            Entry::File { executable, .. } => executable,
            _ => false,
        }
    }

    #[getter]
    fn get_text_sha1(slf: PyRef<Self>, py: Python) -> Option<PyObject> {
        let s = slf.into_super();
        match &s.0 {
            Entry::File { text_sha1, .. } => text_sha1
                .as_ref()
                .map(|text_sha1| PyBytes::new(py, text_sha1.as_ref()).into()),
            _ => panic!("Not a file"),
        }
    }

    #[getter]
    fn get_text_size(slf: PyRef<Self>) -> Option<u64> {
        let s = slf.into_super();
        match &s.0 {
            Entry::File { text_size, .. } => *text_size,
            _ => panic!("Not a file"),
        }
    }

    #[getter]
    fn get_text_id(slf: PyRef<Self>, py: Python) -> Option<PyObject> {
        let s = slf.into_super();
        match &s.0 {
            Entry::File { text_id, .. } => text_id
                .as_ref()
                .map(|text_id| PyBytes::new(py, text_id).into()),
            _ => panic!("Not a file"),
        }
    }

    #[getter]
    fn get_reference_revision(_slf: PyRef<Self>, py: Python) -> PyObject {
        py.None()
    }

    fn copy(slf: PyRef<Self>, py: Python) -> PyResult<PyObject> {
        let s = slf.into_super();
        let init = PyClassInitializer::from(InventoryEntry(s.0.clone()));
        let init = init.add_subclass(Self());
        Ok(PyCell::new(py, init)?.to_object(py))
    }

    fn __repr__(slf: PyRef<Self>, py: Python) -> PyResult<String> {
        let s = slf.into_super();
        Ok(match &s.0 {
            Entry::File {
                name,
                file_id,
                parent_id,
                text_sha1,
                text_size,
                revision,
                ..
            } => format!(
                "InventoryFile({}, {}, parent_id={}, sha1={}, len={}, revision={})",
                file_id.to_object(py).as_ref(py).repr()?,
                name.to_object(py).as_ref(py).repr()?,
                parent_id.to_object(py).as_ref(py).repr()?,
                text_sha1
                    .as_ref()
                    .map(|s| PyBytes::new(py, s.as_slice()).repr())
                    .unwrap_or_else(|| Ok(PyString::new(py, "None")))?,
                text_size.to_object(py).as_ref(py).repr()?,
                revision
                    .as_ref()
                    .map(|r| r.to_object(py))
                    .to_object(py)
                    .as_ref(py)
                    .repr()?,
            ),
            _ => panic!("Not a file"),
        })
    }

    fn check(
        slf: &PyCell<Self>,
        py: Python,
        checker: PyObject,
        rev_id: RevisionId,
        inv: PyObject,
    ) -> PyResult<()> {
        let spr = slf.borrow().into_super();
        common_ie_check(slf.to_object(py), &spr.0, py, &checker, &rev_id, inv)?;

        let (file_id, revision, text_sha1, text_size) = match spr.0 {
            Entry::File {
                ref text_sha1,
                ref file_id,
                ref revision,
                text_size,
                ..
            } => (file_id, revision, text_sha1, text_size),
            _ => panic!("Not a file"),
        };

        checker.call_method1(
            py,
            "add_pending_item",
            (
                rev_id.to_object(py),
                (
                    "texts",
                    file_id.to_object(py),
                    revision.as_ref().map(|p| p.to_object(py)),
                ),
                PyBytes::new(py, b"text").to_object(py),
                PyBytes::new(py, text_sha1.as_ref().unwrap()).to_object(py),
            ),
        )?;

        if text_size.is_none() {
            checker.getattr(py, "_report_items")?.call_method1(
                py,
                "append",
                (format!(
                    "fileid {{{}}} in {{{}}} has None for text_size",
                    file_id, rev_id
                ),),
            )?;
        }

        Ok(())
    }
}

#[pyclass(subclass,extends=InventoryEntry)]
struct InventoryDirectory();

#[pymethods]
impl InventoryDirectory {
    #[new]
    fn new(
        file_id: FileId,
        name: String,
        parent_id: Option<FileId>,
        revision: Option<RevisionId>,
    ) -> PyResult<(Self, InventoryEntry)> {
        check_name(name.as_str())?;
        let entry = if let Some(parent_id) = parent_id {
            Entry::Directory {
                file_id,
                name,
                parent_id,
                revision,
            }
        } else {
            Entry::Root { file_id, revision }
        };
        Ok((Self(), InventoryEntry(entry)))
    }

    fn copy(slf: PyRef<Self>, py: Python) -> PyResult<PyObject> {
        let s = slf.into_super();
        let init = PyClassInitializer::from(InventoryEntry(s.0.clone()));
        let init = init.add_subclass(Self());
        Ok(PyCell::new(py, init)?.to_object(py))
    }

    #[getter]
    fn get_text_size(&self, py: Python) -> PyObject {
        py.None()
    }

    #[getter]
    fn get_text_sha1(&self, py: Python) -> PyObject {
        py.None()
    }

    fn __repr__(slf: PyRef<Self>, py: Python) -> PyResult<String> {
        let s = slf.into_super();
        Ok(match &s.0 {
            Entry::Directory {
                name,
                file_id,
                parent_id,
                revision,
                ..
            } => format!(
                "InventoryDirectory({}, {}, parent_id={}, revision={})",
                file_id.to_object(py).as_ref(py).repr()?,
                name.to_object(py).as_ref(py).repr()?,
                parent_id.to_object(py).as_ref(py).repr()?,
                revision.to_object(py).as_ref(py).repr()?,
            ),
            Entry::Root {
                file_id, revision, ..
            } => format!(
                "InventoryDirectory({}, \"\", parent_id=None, revision={})",
                file_id.to_object(py).as_ref(py).repr()?,
                revision.to_object(py).as_ref(py).repr()?,
            ),
            _ => panic!("Not a directory"),
        })
    }

    fn check(
        slf: &PyCell<Self>,
        py: Python,
        checker: PyObject,
        rev_id: RevisionId,
        inv: PyObject,
    ) -> PyResult<()> {
        let spr = slf.borrow().into_super();
        common_ie_check(slf.to_object(py), &spr.0, py, &checker, &rev_id, inv)?;

        // In non rich root repositories we do not expect a file graph for the
        // root.
        if spr.0.name().is_empty() && !checker.getattr(py, "rich_roots")?.extract::<bool>(py)? {
            return Ok(());
        }
        // Directories are stored as an empty file, but the file should exist
        // to provide a per-fileid log. The hash of every directory content is
        // "da..." below (the sha1sum of '').
        checker.call_method1(
            py,
            "add_pending_item",
            (
                rev_id.to_object(py),
                (
                    "texts",
                    spr.0.file_id().to_object(py),
                    spr.0.revision().to_object(py),
                ),
                PyBytes::new(py, b"text").to_object(py),
                PyBytes::new(py, b"da39a3ee5e6b4b0d3255bfef95601890afd80709").to_object(py),
            ),
        )?;

        Ok(())
    }
}

#[pyclass(subclass,extends=InventoryEntry)]
struct TreeReference();

#[pymethods]
impl TreeReference {
    #[new]
    fn new(
        file_id: FileId,
        name: String,
        parent_id: FileId,
        revision: Option<RevisionId>,
        reference_revision: Option<RevisionId>,
    ) -> PyResult<(Self, InventoryEntry)> {
        check_name(name.as_str())?;
        let entry = Entry::TreeReference {
            file_id,
            name,
            parent_id,
            revision,
            reference_revision,
        };
        Ok((Self(), InventoryEntry(entry)))
    }

    #[getter]
    fn get_reference_revision(slf: PyRef<Self>, py: Python) -> Option<PyObject> {
        let s = slf.into_super();
        match &s.0 {
            Entry::TreeReference {
                reference_revision, ..
            } => reference_revision
                .as_ref()
                .map(|reference_revision| reference_revision.to_object(py)),
            _ => panic!("Not a tree reference"),
        }
    }

    fn copy(slf: PyRef<Self>, py: Python) -> PyResult<PyObject> {
        let s = slf.into_super();
        let init = PyClassInitializer::from(InventoryEntry(s.0.clone()));
        let init = init.add_subclass(Self());
        Ok(PyCell::new(py, init)?.to_object(py))
    }
}

#[pyclass(subclass,extends=InventoryEntry)]
struct InventoryLink();

#[pymethods]
impl InventoryLink {
    #[new]
    fn new(
        file_id: FileId,
        name: String,
        parent_id: FileId,
        revision: Option<RevisionId>,
        symlink_target: Option<String>,
    ) -> PyResult<(Self, InventoryEntry)> {
        check_name(name.as_str())?;
        let entry = Entry::Link {
            file_id,
            name,
            parent_id,
            symlink_target,
            revision,
        };
        Ok((Self(), InventoryEntry(entry)))
    }

    #[getter]
    fn get_symlink_target(slf: PyRef<Self>) -> Option<String> {
        let s = slf.into_super();
        match s.0 {
            Entry::Link {
                ref symlink_target, ..
            } => symlink_target.clone(),
            _ => panic!("Not a link"),
        }
    }

    fn copy(slf: PyRef<Self>, py: Python) -> PyResult<PyObject> {
        let s = slf.into_super();
        let init = PyClassInitializer::from(InventoryEntry(s.0.clone()));
        let init = init.add_subclass(Self());
        Ok(PyCell::new(py, init)?.to_object(py))
    }

    #[getter]
    fn get_text_size(&self, py: Python) -> PyObject {
        py.None()
    }

    #[getter]
    fn get_text_sha1(&self, py: Python) -> PyObject {
        py.None()
    }

    fn check(
        slf: &PyCell<Self>,
        py: Python,
        checker: PyObject,
        rev_id: RevisionId,
        inv: PyObject,
    ) -> PyResult<()> {
        let spr = slf.borrow().into_super();
        common_ie_check(slf.to_object(py), &spr.0, py, &checker, &rev_id, inv)?;

        if spr.0.symlink_target().is_none() {
            let report_items = checker.getattr(py, "_report_items")?;
            report_items.call_method1(
                py,
                "append",
                (format!(
                    "symlink {} has no target in revision {}",
                    spr.0.file_id(),
                    spr.0
                        .revision()
                        .map_or_else(|| String::from("None"), |p| p.to_string())
                ),),
            )?;
        }

        // Symlinks are stored as ''
        checker.call_method1(
            py,
            "add_pending_item",
            (
                rev_id.to_object(py),
                (
                    "texts",
                    spr.0.file_id().to_object(py),
                    spr.0.revision().to_object(py),
                ),
                PyBytes::new(py, b"text").to_object(py),
                PyBytes::new(py, b"da39a3ee5e6b4b0d3255bfef95601890afd80709").to_object(py),
            ),
        )?;
        Ok(())
    }
}

fn entry_to_py(py: Python, e: Entry) -> PyResult<PyObject> {
    let kind = e.kind();
    let init = PyClassInitializer::from(InventoryEntry(e));
    match kind {
        Kind::File => {
            let init = init.add_subclass(InventoryFile());
            Ok(PyCell::new(py, init)?.to_object(py))
        }
        Kind::Directory => {
            let init = init.add_subclass(InventoryDirectory());
            Ok(PyCell::new(py, init)?.to_object(py))
        }
        Kind::TreeReference => {
            let init = init.add_subclass(TreeReference());
            Ok(PyCell::new(py, init)?.to_object(py))
        }
        Kind::Symlink => {
            let init = init.add_subclass(InventoryLink());
            Ok(PyCell::new(py, init)?.to_object(py))
        }
    }
}

fn entry_from_py(py: Python, obj: PyObject) -> PyResult<Entry> {
    let kind = obj.getattr(py, "kind")?.extract::<String>(py)?;
    let kind = match kind.as_str() {
        "file" => Kind::File,
        "directory" => Kind::Directory,
        "tree-reference" => Kind::TreeReference,
        "symlink" => Kind::Symlink,
        _ => panic!("Unknown kind"),
    };

    let file_id = obj.getattr(py, "file_id")?.extract::<Option<FileId>>(py)?;
    let name = obj.getattr(py, "name")?.extract::<String>(py)?;
    let parent_id = obj
        .getattr(py, "parent_id")?
        .extract::<Option<FileId>>(py)?;
    let revision = obj
        .getattr(py, "revision")?
        .extract::<Option<RevisionId>>(py)?;
    let executable = obj.getattr(py, "executable")?.extract::<Option<bool>>(py)?;
    let text_id = obj.getattr(py, "text_id")?.extract::<Option<Vec<u8>>>(py)?;
    let text_sha1 = obj
        .getattr(py, "text_sha1")?
        .extract::<Option<Vec<u8>>>(py)?;
    let text_size = obj.getattr(py, "text_size")?.extract::<Option<u64>>(py)?;
    let symlink_target = obj
        .getattr(py, "symlink_target")?
        .extract::<Option<String>>(py)?;
    let reference_revision = obj
        .getattr(py, "reference_revision")?
        .extract::<Option<RevisionId>>(py)?;

    let entry = bazaar::inventory::make_entry(
        kind,
        name,
        parent_id,
        file_id,
        revision,
        text_sha1,
        text_size,
        executable,
        text_id,
        symlink_target,
        reference_revision,
    )
    .map_err(|e| inventory_err_to_py_err(e, py))?;

    Ok(entry)
}

#[pyfunction]
fn make_entry(
    py: Python,
    kind: &str,
    name: &str,
    parent_id: Option<FileId>,
    revision: Option<RevisionId>,
    file_id: Option<FileId>,
    text_sha1: Option<Vec<u8>>,
    text_size: Option<u64>,
    executable: Option<bool>,
    text_id: Option<Vec<u8>>,
    symlink_target: Option<String>,
    reference_revision: Option<RevisionId>,
) -> PyResult<PyObject> {
    let kind = match kind {
        "file" => Kind::File,
        "directory" => Kind::Directory,
        "tree-reference" => Kind::TreeReference,
        "symlink" => Kind::Symlink,
        _ => panic!("Unknown kind"),
    };
    entry_to_py(
        py,
        bazaar::inventory::make_entry(
            kind,
            name.to_string(),
            file_id,
            parent_id,
            revision,
            text_sha1,
            text_size,
            executable,
            text_id,
            symlink_target,
            reference_revision,
        )
        .map_err(|e| inventory_err_to_py_err(e, py))?,
    )
}

#[pyfunction]
fn is_valid_name(name: &str) -> bool {
    bazaar::inventory::is_valid_name(name)
}

#[pyfunction]
fn ensure_normalized_name(name: std::path::PathBuf) -> PyResult<std::path::PathBuf> {
    bazaar::inventory::ensure_normalized_name(name.as_path())
        .map_err(|_e| InvalidNormalization::new_err(name))
}

fn delta_err_to_py_err(py: Python, e: InventoryDeltaInconsistency) -> PyErr {
    match e {
        InventoryDeltaInconsistency::NoPath => {
            InconsistentDelta::new_err(("", "", "No path in entry"))
        }
        InventoryDeltaInconsistency::DuplicateFileId(ref path, ref fid) => {
            InconsistentDelta::new_err((path.clone(), fid.to_object(py), "repeated file_id"))
        }
        InventoryDeltaInconsistency::DuplicateOldPath(path, fid) => {
            InconsistentDelta::new_err((path, fid.to_object(py), "repeated path"))
        }
        InventoryDeltaInconsistency::DuplicateNewPath(path, fid) => {
            InconsistentDelta::new_err((path, fid.to_object(py), "repeated path"))
        }
        InventoryDeltaInconsistency::MismatchedId(path, fid1, fid2) => {
            InconsistentDelta::new_err((
                path,
                fid1.to_object(py),
                format!("mismatched id with entry {}", fid2),
            ))
        }
        InventoryDeltaInconsistency::EntryWithoutPath(path, fid) => {
            InconsistentDelta::new_err((path, fid.to_object(py), "Entry with no new_path"))
        }
        InventoryDeltaInconsistency::PathWithoutEntry(path, fid) => {
            InconsistentDelta::new_err((path, fid.to_object(py), "new_path with no entry"))
        }
        InventoryDeltaInconsistency::OrphanedChild(fid) => {
            InconsistentDelta::new_err(("<deleted>", fid.to_object(py), "orphaned child"))
        }
        InventoryDeltaInconsistency::NoSuchId(fid) => {
            NoSuchId::new_err((py.None(), fid.to_object(py)))
        }
        InventoryDeltaInconsistency::PathMismatch(fid, path1, path2) => {
            InconsistentDelta::new_err((
                path1,
                fid.to_object(py),
                format!("path mismatch != {}", path2),
            ))
        }
        InventoryDeltaInconsistency::ParentMissing(fid) => {
            InconsistentDelta::new_err(("", fid.to_object(py), "parent missing"))
        }
        InventoryDeltaInconsistency::InvalidEntryName(name) => InvalidEntryName::new_err((name,)),
        InventoryDeltaInconsistency::FileIdCycle(fid, path, parent_path) => {
            InconsistentDelta::new_err((
                path,
                fid.to_object(py),
                format!("file_id cycle with {}", parent_path),
            ))
        }
        InventoryDeltaInconsistency::ParentNotDirectory(path, fid) => {
            InconsistentDelta::new_err((path, fid.to_object(py), "parent is not a directory"))
        }
        InventoryDeltaInconsistency::PathAlreadyVersioned(name, parent_path) => {
            InconsistentDelta::new_err((name, parent_path, "path already versioned"))
        }
    }
}

#[pyclass]
struct InventoryDelta(bazaar::inventory_delta::InventoryDelta);

#[pymethods]
impl InventoryDelta {
    #[new]
    fn new(
        _py: Python,
        delta: Option<
            Vec<(
                Option<String>,
                Option<String>,
                FileId,
                Option<PyRef<InventoryEntry>>,
            )>,
        >,
    ) -> PyResult<Self> {
        let delta = delta.unwrap_or_default();
        let delta = delta
            .into_iter()
            .map(|(old_name, new_name, file_id, entry)| {
                let old_name = old_name.as_deref();
                let new_name = new_name.as_deref();
                let entry = entry.as_ref().map(|e| e.0.clone());
                InventoryDeltaEntry {
                    old_path: old_name.map(|s| s.to_string()),
                    new_path: new_name.map(|s| s.to_string()),
                    file_id,
                    new_entry: entry,
                }
            })
            .collect::<Vec<_>>();
        Ok(Self(bazaar::inventory_delta::InventoryDelta::from(delta)))
    }

    fn __nonzero__(slf: PyRef<Self>) -> bool {
        !slf.0.is_empty()
    }

    fn sort(&mut self) {
        self.0.sort();
    }

    fn __len__(&self) -> usize {
        self.0.len()
    }

    fn __richcmp__(&self, other: PyRef<InventoryDelta>, op: CompareOp) -> PyResult<Option<bool>> {
        match op {
            CompareOp::Eq => Ok(Some(self.0 == other.0)),
            CompareOp::Ne => Ok(Some(self.0 != other.0)),
            _ => Err(PyNotImplementedError::new_err(
                "Only == and != are supported",
            )),
        }
    }

    fn __getitem__(
        &self,
        py: Python,
        index: isize,
    ) -> PyResult<(Option<String>, Option<String>, PyObject, PyObject)> {
        let index: usize = if index < 0 {
            (self.0.len() as isize + index) as usize
        } else {
            index as usize
        };
        let entry = self
            .0
            .get(index)
            .ok_or(PyIndexError::new_err("Index out of bounds"))?;
        Ok((
            entry.old_path.clone(),
            entry.new_path.clone(),
            entry.file_id.to_object(py),
            entry
                .new_entry
                .as_ref()
                .map_or_else(|| Ok(py.None()), |e| entry_to_py(py, e.clone()))?,
        ))
    }

    fn check(&self, py: Python) -> PyResult<()> {
        self.0.check().map_err(|e| match e {
            InventoryDeltaInconsistency::NoPath => {
                InconsistentDelta::new_err(("", "", "No path in entry"))
            }
            InventoryDeltaInconsistency::DuplicateFileId(ref path, ref fid) => {
                InconsistentDelta::new_err((path.clone(), fid.to_object(py), "repeated file_id"))
            }
            InventoryDeltaInconsistency::DuplicateOldPath(path, fid) => {
                InconsistentDelta::new_err((path, fid.to_object(py), "repeated path"))
            }
            InventoryDeltaInconsistency::DuplicateNewPath(path, fid) => {
                InconsistentDelta::new_err((path, fid.to_object(py), "repeated path"))
            }
            InventoryDeltaInconsistency::MismatchedId(path, fid1, fid2) => {
                InconsistentDelta::new_err((
                    path,
                    fid1.to_object(py),
                    format!("mismatched id with entry {}", fid2),
                ))
            }
            InventoryDeltaInconsistency::PathMismatch(fid, path1, path2) => {
                InconsistentDelta::new_err((
                    path1,
                    fid.to_object(py),
                    format!("mismatched path with entry {}", path2),
                ))
            }
            InventoryDeltaInconsistency::OrphanedChild(fid) => {
                InconsistentDelta::new_err(("", fid.to_object(py), "orphaned child"))
            }
            InventoryDeltaInconsistency::ParentNotDirectory(path, fid) => {
                InconsistentDelta::new_err((path, fid.to_object(py), "parent not directory"))
            }
            InventoryDeltaInconsistency::ParentMissing(fid) => {
                InconsistentDelta::new_err(("", fid.to_object(py), "parent missing"))
            }
            InventoryDeltaInconsistency::NoSuchId(fid) => {
                NoSuchId::new_err((py.None(), fid.to_object(py)))
            }
            InventoryDeltaInconsistency::InvalidEntryName(n) => InvalidEntryName::new_err((n,)),
            InventoryDeltaInconsistency::FileIdCycle(fid, path, parent_path) => {
                InconsistentDelta::new_err((
                    path,
                    fid.to_object(py),
                    format!("file_id cycle with {}", parent_path),
                ))
            }
            InventoryDeltaInconsistency::PathAlreadyVersioned(path, fid) => {
                InconsistentDelta::new_err((path, fid.to_object(py), "path already versioned"))
            }
            InventoryDeltaInconsistency::EntryWithoutPath(path, fid) => {
                InconsistentDelta::new_err((path, fid.to_object(py), "Entry with no new_path"))
            }
            InventoryDeltaInconsistency::PathWithoutEntry(path, fid) => {
                InconsistentDelta::new_err((path, fid.to_object(py), "new_path with no entry"))
            }
        })
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.0)
    }
}

fn inventory_err_to_py_err(e: Error, py: Python) -> PyErr {
    match e {
        Error::InvalidEntryName(name) => InvalidEntryName::new_err((name,)),
        Error::InvalidNormalization(n, _) => InvalidNormalization::new_err((n,)),
        Error::DuplicateFileId(fid, path) => DuplicateFileId::new_err((fid.to_object(py), path)),
        Error::NoSuchId(fid) => NoSuchId::new_err((py.None(), fid.to_object(py))),
        Error::ParentNotDirectory(path, fid) => {
            InconsistentDelta::new_err((path, fid.to_object(py), "parent not directory"))
        }
        Error::FileIdCycle(fid, path, parent_path) => InconsistentDelta::new_err((
            path,
            fid.to_object(py),
            format!("file_id cycle with {}", parent_path),
        )),
        Error::ParentMissing(fid) => {
            InconsistentDelta::new_err(("", fid.to_object(py), "parent missing"))
        }
        Error::PathAlreadyVersioned(name, parent_path) => {
            AlreadyVersionedError::new_err(format!("{}/{}", parent_path, name))
        }
        Error::ParentNotVersioned(path) => {
            NotVersionedError::new_err(format!("parent not versioned: {}", path))
        }
    }
}

#[pyclass]
struct Inventory(bazaar::inventory::MutableInventory);

#[pymethods]
impl Inventory {
    #[new]
    #[pyo3(signature = (root_id=b"TREE_ROOT".to_vec(), revision_id=None, root_revision=None))]
    fn new(
        root_id: Option<Vec<u8>>,
        revision_id: Option<RevisionId>,
        root_revision: Option<RevisionId>,
    ) -> PyResult<Self> {
        let root_id = root_id.map(bazaar::FileId::from);
        let mut inv = Inventory(bazaar::inventory::MutableInventory::new());

        if let Some(root_id) = root_id {
            let root = bazaar::inventory::Entry::root(root_id, root_revision);
            inv.0.add(root).unwrap();
        } else if root_revision.is_some() {
            return Err(PyTypeError::new_err("root_revision requires root_id"));
        }
        inv.0.revision_id = revision_id;
        Ok(inv)
    }

    #[getter]
    fn root(&self, py: Python) -> PyResult<PyObject> {
        if let Some(root) = self.0.root() {
            entry_to_py(py, root.clone())
        } else {
            Ok(py.None())
        }
    }

    fn add(&mut self, py: Python, entry: &InventoryEntry) -> PyResult<()> {
        self.0
            .add(entry.0.clone())
            .map_err(|e| inventory_err_to_py_err(e, py))?;
        Ok(())
    }

    fn add_path(
        &mut self,
        py: Python,
        relpath: &str,
        kind: breezy_osutils::Kind,
        file_id: Option<FileId>,
        revision: Option<RevisionId>,
        text_sha1: Option<Vec<u8>>,
        text_size: Option<u64>,
        executable: Option<bool>,
        text_id: Option<Vec<u8>>,
        symlink_target: Option<String>,
        reference_revision: Option<RevisionId>,
    ) -> PyResult<PyObject> {
        let file_id = self
            .0
            .add_path(
                relpath,
                kind,
                file_id,
                revision,
                text_sha1,
                text_size,
                executable,
                text_id,
                symlink_target,
                reference_revision,
            )
            .map_err(|e| inventory_err_to_py_err(e, py))?;
        Ok(self.get_entry(py, file_id).unwrap())
    }

    #[getter]
    fn get_revision_id(&self) -> Option<RevisionId> {
        self.0.revision_id.as_ref().cloned()
    }

    #[setter]
    fn set_revision_id(&mut self, revision_id: Option<RevisionId>) {
        self.0.revision_id = revision_id;
    }

    fn id2path(&self, py: Python, file_id: FileId) -> PyResult<String> {
        self.0
            .id2path(&file_id)
            .map_err(|e| inventory_err_to_py_err(e, py))
    }

    fn path2id(&self, path: &str) -> Option<FileId> {
        self.0.path2id(path).cloned()
    }

    fn is_root(&self, file_id: FileId) -> PyResult<bool> {
        Ok(self.0.is_root(file_id))
    }

    fn has_filename(&self, name: &str) -> PyResult<bool> {
        Ok(self.0.has_filename(name))
    }

    fn get_children(&self, py: Python, file_id: FileId) -> PyResult<HashMap<String, PyObject>> {
        let children = self.0.get_children(&file_id);
        if children.is_none() {
            return Err(NoSuchId::new_err((py.None(), file_id.to_object(py))));
        }
        let children = children.unwrap();
        let mut result = HashMap::with_capacity(children.len());
        for (name, child) in children {
            result.insert(name.to_string(), entry_to_py(py, child.clone())?);
        }
        Ok(result)
    }

    fn entries(&self, py: Python) -> PyResult<Vec<(String, PyObject)>> {
        let entries = self.0.entries();
        let mut result = Vec::with_capacity(entries.len());
        for (name, entry) in entries {
            result.push((name, entry_to_py(py, entry.clone())?));
        }
        Ok(result)
    }

    fn rename_id(&mut self, py: Python, old_file_id: FileId, new_file_id: FileId) -> PyResult<()> {
        self.0
            .rename_id(&old_file_id, &new_file_id)
            .map_err(|e| inventory_err_to_py_err(e, py))
    }

    fn path2id_segments(&self, names: Vec<&str>) -> Option<FileId> {
        self.0.path2id_segments(names.as_slice()).cloned()
    }

    fn filter(&self, py: Python, specific_fileids: HashSet<FileId>) -> PyResult<Self> {
        let result = self
            .0
            .filter(&specific_fileids.iter().collect())
            .map_err(|e| inventory_err_to_py_err(e, py))?;
        Ok(Self(result))
    }

    fn get_entry_by_path_partial(
        &self,
        py: Python,
        relpath: PyObject,
    ) -> PyResult<(Option<PyObject>, Option<Vec<String>>, Option<Vec<String>>)> {
        let ret = if let Ok(relpath) = relpath.extract::<&str>(py) {
            self.0.get_entry_by_path_partial(relpath)
        } else if let Ok(segments) = relpath.extract::<Vec<&str>>(py) {
            self.0
                .get_entry_by_path_segments_partial(segments.as_slice())
        } else {
            return Err(PyTypeError::new_err("expected str or list of str"));
        };

        if let Some((e, segments, missing)) = ret {
            Ok((
                Some(entry_to_py(py, e.clone())?),
                Some(segments),
                Some(missing),
            ))
        } else {
            Ok((None, None, None))
        }
    }

    fn get_entry_by_path(&self, py: Python, relpath: PyObject) -> PyResult<Option<PyObject>> {
        if let Ok(relpath) = relpath.extract::<&str>(py) {
            Ok(self
                .0
                .get_entry_by_path(relpath)
                .map(|entry| entry_to_py(py, entry.clone()).unwrap()))
        } else if let Ok(segments) = relpath.extract::<Vec<&str>>(py) {
            Ok(self
                .0
                .get_entry_by_path_segments(segments.as_slice())
                .map(|entry| entry_to_py(py, entry.clone()).unwrap()))
        } else {
            Err(PyTypeError::new_err("expected str or list of str"))
        }
    }

    fn apply_delta(
        &mut self,
        py: Python,
        delta: Vec<(
            Option<String>,
            Option<String>,
            FileId,
            Option<PyRef<InventoryEntry>>,
        )>,
    ) -> PyResult<()> {
        let delta = bazaar::inventory_delta::InventoryDelta::from_iter(delta.into_iter().map(
            |(old_name, new_name, file_id, entry)| InventoryDeltaEntry {
                old_path: old_name,
                new_path: new_name,
                file_id,
                new_entry: entry.map(|entry| entry.0.clone()),
            },
        ));
        self.0
            .apply_delta(&delta)
            .map_err(|e| delta_err_to_py_err(py, e))
    }

    fn create_by_apply_delta(
        &self,
        py: Python,
        delta: Vec<(
            Option<String>,
            Option<String>,
            FileId,
            Option<PyRef<InventoryEntry>>,
        )>,
        new_revision_id: RevisionId,
    ) -> PyResult<Self> {
        let delta = bazaar::inventory_delta::InventoryDelta::from_iter(delta.into_iter().map(
            |(old_name, new_name, file_id, entry)| InventoryDeltaEntry {
                old_path: old_name,
                new_path: new_name,
                file_id,
                new_entry: entry.map(|entry| entry.0.clone()),
            },
        ));
        let result = self
            .0
            .create_by_apply_delta(&delta, new_revision_id)
            .map_err(|e| delta_err_to_py_err(py, e))?;
        Ok(Self(result))
    }

    fn __len__(&self) -> usize {
        self.0.len()
    }

    fn get_entry(&self, py: Python, file_id: FileId) -> PyResult<PyObject> {
        self.0
            .get_entry(&file_id)
            .map(|entry| entry_to_py(py, entry.clone()).unwrap())
            .ok_or_else(|| NoSuchId::new_err((py.None(), file_id.to_object(py))))
    }

    fn get_file_kind(&self, file_id: FileId) -> Option<&str> {
        self.0.get_file_kind(&file_id).map(|kind| kind.to_string())
    }

    fn has_id(&self, file_id: FileId) -> bool {
        self.0.has_id(&file_id)
    }

    fn get_child(&self, py: Python, file_id: FileId, name: &str) -> Option<PyObject> {
        self.0
            .get_child(&file_id, name)
            .map(|entry| entry_to_py(py, entry.clone()).unwrap())
    }

    fn delete(&mut self, py: Python, file_id: FileId) -> PyResult<()> {
        self.0
            .delete(&file_id)
            .map_err(|e| inventory_err_to_py_err(e, py))
    }

    fn _make_delta(&self, py: Python, old: &Inventory) -> PyResult<PyObject> {
        let inventory_delta = self.0.make_delta(&old.0);
        Ok(PyCell::new(py, InventoryDelta(inventory_delta))?.to_object(py))
    }

    fn remove_recursive_id(&mut self, py: Python, file_id: FileId) -> PyResult<Vec<PyObject>> {
        self.0
            .remove_recursive_id(&file_id)
            .into_iter()
            .map(|entry| entry_to_py(py, entry))
            .collect::<PyResult<Vec<_>>>()
    }

    fn rename(
        &mut self,
        py: Python,
        file_id: FileId,
        new_parent_id: FileId,
        new_name: &str,
    ) -> PyResult<()> {
        self.0
            .rename(&file_id, &new_parent_id, new_name)
            .map_err(|e| inventory_err_to_py_err(e, py))
    }

    fn iter_sorted_children(&self, py: Python, file_id: FileId) -> PyResult<PyObject> {
        let children = self.0.iter_sorted_children(&file_id);
        if children.is_none() {
            return Err(NoSuchId::new_err((py.None(), file_id.to_object(py))));
        }
        Ok(children
            .unwrap()
            .map(|(_n, e)| entry_to_py(py, e.clone()))
            .collect::<PyResult<Vec<_>>>()?
            .to_object(py))
    }

    fn iter_all_ids(&self, py: Python) -> PyResult<PyObject> {
        let ids = self.0.iter_all_ids();
        ids.into_iter()
            .collect::<Vec<_>>()
            .to_object(py)
            .call_method0(py, "__iter__")
    }

    fn iter_entries(
        slf: Py<Inventory>,
        py: Python,
        from_dir: Option<FileId>,
        recursive: Option<bool>,
    ) -> PyResult<PyObject> {
        let recursive = recursive.unwrap_or(true);

        Ok(PyCell::new(py, IterEntriesIterator::new(py, slf, from_dir, recursive)?)?.to_object(py))
    }

    fn iter_entries_by_dir(
        slf: Py<Inventory>,
        py: Python,
        from_dir: Option<FileId>,
        specific_file_ids: Option<HashSet<FileId>>,
    ) -> PyResult<PyObject> {
        Ok(PyCell::new(
            py,
            IterEntriesByDirIterator::new(py, slf, from_dir, specific_file_ids)?,
        )?
        .to_object(py))
    }

    fn change_root_id(&mut self, new_root_id: FileId) -> PyResult<()> {
        self.0.change_root_id(new_root_id);
        Ok(())
    }

    fn copy(&self) -> Self {
        Self(self.0.clone())
    }

    fn make_entry(
        &self,
        py: Python,
        kind: &str,
        name: &str,
        parent_id: Option<FileId>,
        file_id: Option<FileId>,
        revision: Option<RevisionId>,
        text_sha1: Option<Vec<u8>>,
        text_size: Option<u64>,
        text_id: Option<Vec<u8>>,
        executable: Option<bool>,
        symlink_target: Option<String>,
        reference_revision: Option<RevisionId>,
    ) -> PyResult<PyObject> {
        let kind = match kind {
            "directory" => Kind::Directory,
            "file" => Kind::File,
            "symlink" => Kind::Symlink,
            "tree-reference" => Kind::TreeReference,
            _ => return Err(PyValueError::new_err(format!("Unknown kind: {}", kind))),
        };
        let entry = bazaar::inventory::make_entry(
            kind,
            name.to_string(),
            parent_id,
            file_id,
            revision,
            text_sha1,
            text_size,
            executable,
            text_id,
            symlink_target,
            reference_revision,
        )
        .map_err(|e| inventory_err_to_py_err(e, py))?;
        entry_to_py(py, entry)
    }

    pub fn __richcmp__(
        &self,
        py: Python,
        other: PyRef<Inventory>,
        op: CompareOp,
    ) -> PyResult<PyObject> {
        match op {
            CompareOp::Eq => Ok((self.0 == other.0).to_object(py)),
            CompareOp::Ne => Ok((self.0 != other.0).to_object(py)),
            _ => Err(PyNotImplementedError::new_err(
                "Only == and != are implemented",
            )),
        }
    }
}

#[pyclass]
struct IterEntriesByDirIterator {
    inv: Py<Inventory>,
    parents: Option<HashSet<FileId>>,
    stack: Vec<(String, FileId)>,
    children: VecDeque<(String, Entry)>,
    specific_file_ids: Option<HashSet<FileId>>,
}

impl IterEntriesByDirIterator {
    fn new(
        py: Python,
        inv: Py<Inventory>,
        from_dir: Option<FileId>,
        specific_file_ids: Option<HashSet<FileId>>,
    ) -> PyResult<Self> {
        let parents = specific_file_ids.as_ref().map(|specific_file_ids| {
            bazaar::inventory::find_interesting_parents(
                &inv.borrow(py).0,
                &specific_file_ids.iter().collect(),
            )
            .into_iter()
            .cloned()
            .collect()
        });

        let mut stack: Vec<(String, FileId)> = vec![];
        let from_dir = if let Some(from_dir) = from_dir {
            let inv = &inv.borrow(py).0;
            let e = inv.get_entry(&from_dir);

            if e.is_none() {
                return Err(NoSuchId::new_err((py.None(), from_dir.to_object(py))));
            }

            let e = e.unwrap();

            if e.kind() != Kind::Directory {
                return Err(NotADirectory::new_err(from_dir));
            }
            Some(from_dir)
        } else {
            inv.borrow(py).0.root().map(|e| e.file_id().clone())
        };

        let mut children = VecDeque::new();

        if let Some(from_dir) = from_dir.as_ref() {
            assert!(
                inv.borrow(py).0.get_children(from_dir).is_some(),
                "from_dir {:?} must be a directory",
                from_dir
            );
            stack.push(("".to_string(), from_dir.clone()));
            if specific_file_ids.is_none() || specific_file_ids.as_ref().unwrap().contains(from_dir)
            {
                children.push_front((
                    "".to_string(),
                    inv.borrow(py).0.get_entry(from_dir).unwrap().clone(),
                ));
            }
        }

        Ok(Self {
            inv,
            parents,
            children,
            stack,
            specific_file_ids,
        })
    }
}

#[pymethods]
impl IterEntriesByDirIterator {
    fn __iter__(slf: PyRef<Self>) -> PyResult<Py<IterEntriesByDirIterator>> {
        Ok(slf.into())
    }

    fn __next__(&mut self, py: Python) -> PyResult<Option<(String, PyObject)>> {
        loop {
            if let Some((relpath, ie)) = self.children.pop_front() {
                return Ok(Some((relpath, entry_to_py(py, ie)?)));
            }
            if let Some((cur_relpath, cur_dir)) = self.stack.pop() {
                let mut child_dirs = Vec::new();
                let inv = &self.inv.borrow(py).0;
                for (child_name, child_ie) in inv
                    .iter_sorted_children(&cur_dir)
                    .expect("should be known directory")
                {
                    let child_relpath = cur_relpath.to_string() + child_name;

                    if self.specific_file_ids.is_none()
                        || self
                            .specific_file_ids
                            .as_ref()
                            .unwrap()
                            .contains(child_ie.file_id())
                    {
                        self.children
                            .push_back((child_relpath.clone(), child_ie.clone()));
                    }

                    if child_ie.kind() == Kind::Directory
                        && (self.parents.is_none()
                            || self.parents.as_ref().unwrap().contains(child_ie.file_id()))
                    {
                        assert!(self
                            .inv
                            .borrow(py)
                            .0
                            .get_children(child_ie.file_id())
                            .is_some());
                        child_dirs.push((child_relpath + "/", child_ie.file_id()))
                    }
                }
                self.stack
                    .extend(child_dirs.into_iter().rev().map(|(n, f)| (n, f.clone())));
            } else {
                return Ok(None);
            }
        }
    }
}

#[pyclass]
struct IterEntriesIterator {
    inv: Py<Inventory>,
    stack: VecDeque<(String, VecDeque<(String, Entry)>)>,
    recursive: bool,
    first_entry: Option<Entry>,
}

impl IterEntriesIterator {
    fn new(
        py: Python,
        inv: Py<Inventory>,
        mut from_dir: Option<FileId>,
        recursive: bool,
    ) -> PyResult<Self> {
        let mut stack = VecDeque::new();

        let first_entry = if from_dir.is_none() {
            from_dir = inv.borrow(py).0.root().map(|e| e.file_id().clone());
            inv.borrow(py).0.root().cloned()
        } else {
            None
        };

        if let Some(from_dir) = from_dir.as_ref() {
            let inv = &inv.borrow(py).0;
            let children = inv.iter_sorted_children(from_dir);
            if children.is_none() {
                return Err(NoSuchId::new_err((py.None(), from_dir.to_object(py))));
            }
            stack.push_back((
                String::new(),
                children
                    .unwrap()
                    .map(|(p, ie)| (p.to_string(), ie.clone()))
                    .collect::<VecDeque<_>>(),
            ));
        }

        Ok(Self {
            inv,
            stack,
            recursive,
            first_entry,
        })
    }
}

#[pymethods]
impl IterEntriesIterator {
    fn __iter__(slf: PyRef<Self>) -> PyResult<Py<IterEntriesIterator>> {
        Ok(slf.into())
    }

    fn __next__(&mut self, py: Python) -> PyResult<Option<(String, PyObject)>> {
        if let Some(first_entry) = self.first_entry.take() {
            return Ok(Some((String::new(), entry_to_py(py, first_entry)?)));
        }
        loop {
            if let Some((base, children)) = self.stack.back_mut() {
                if let Some((name, ie)) = children.pop_front() {
                    let path = if base.is_empty() {
                        name
                    } else {
                        format!("{}/{}", base, name)
                    };
                    if ie.kind() == Kind::Directory && self.recursive {
                        let children = self
                            .inv
                            .borrow(py)
                            .0
                            .iter_sorted_children(ie.file_id())
                            .unwrap()
                            .map(|(p, ie)| (p.to_string(), ie.clone()))
                            .collect::<VecDeque<_>>();
                        self.stack.push_back((path.clone(), children));
                    }
                    return Ok(Some((path, entry_to_py(py, ie)?)));
                } else {
                    self.stack.pop_back();
                }
            } else {
                return Ok(None);
            }
        }
    }
}

#[pyfunction]
fn parse_inventory_delta(
    py: Python,
    lines: Vec<Vec<u8>>,
    allow_versioned_root: Option<bool>,
    allow_tree_references: Option<bool>,
) -> PyResult<(PyObject, PyObject, bool, bool, PyObject)> {
    let (parent, version, versioned_root, tree_references, result) =
        bazaar::inventory_delta::parse_inventory_delta(
            lines
                .iter()
                .map(|x| x.as_slice())
                .collect::<Vec<_>>()
                .as_slice(),
            allow_versioned_root,
            allow_tree_references,
        )
        .map_err(|e| match e {
            InventoryDeltaParseError::Invalid(m) => InventoryDeltaError::new_err((m,)),
            InventoryDeltaParseError::Incompatible(m) => IncompatibleInventoryDelta::new_err((m,)),
        })?;

    let parent = parent.to_object(py);
    let version = version.to_object(py);

    let result = PyCell::new(py, InventoryDelta(result))?.to_object(py);

    Ok((parent, version, versioned_root, tree_references, result))
}

#[pyfunction]
fn parse_inventory_entry(
    file_id: FileId,
    name: String,
    parent_id: Option<FileId>,
    revision: Option<RevisionId>,
    lines: &[u8],
) -> InventoryEntry {
    InventoryEntry(bazaar::inventory_delta::parse_inventory_entry(
        file_id, name, parent_id, revision, lines,
    ))
}

#[pyfunction]
fn serialize_inventory_entry(py: Python, entry: &InventoryEntry) -> PyResult<PyObject> {
    Ok(PyBytes::new(
        py,
        bazaar::inventory_delta::serialize_inventory_entry(&entry.0)
            .map_err(|e| match e {
                InventoryDeltaSerializeError::Invalid(m) => InventoryDeltaError::new_err((m,)),
                InventoryDeltaSerializeError::UnsupportedKind(k) => PyKeyError::new_err((k,)),
            })?
            .as_slice(),
    )
    .to_object(py))
}

#[pyfunction]
fn serialize_inventory_delta(
    py: Python,
    old_name: RevisionId,
    new_name: RevisionId,
    delta_to_new: &InventoryDelta,
    versioned_root: bool,
    tree_references: bool,
) -> PyResult<Vec<PyObject>> {
    Ok(bazaar::inventory_delta::serialize_inventory_delta(
        &old_name,
        &new_name,
        &delta_to_new.0,
        versioned_root,
        tree_references,
    )
    .map_err(|e| match e {
        InventoryDeltaSerializeError::Invalid(m) => InventoryDeltaError::new_err((m,)),
        InventoryDeltaSerializeError::UnsupportedKind(m) => PyKeyError::new_err((m,)),
    })?
    .into_iter()
    .map(|x| PyBytes::new(py, x.as_slice()).to_object(py))
    .collect())
}

#[pyfunction]
fn chk_inventory_entry_to_bytes(py: Python, entry: &InventoryEntry) -> PyResult<PyObject> {
    Ok(PyBytes::new(
        py,
        bazaar::chk_inventory::chk_inventory_entry_to_bytes(&entry.0).as_slice(),
    )
    .to_object(py))
}

#[pyfunction]
pub fn chk_inventory_bytes_to_entry(py: Python, data: &[u8]) -> PyResult<PyObject> {
    entry_to_py(
        py,
        bazaar::chk_inventory::chk_inventory_bytes_to_entry(data),
    )
}

#[pyfunction]
fn chk_inventory_bytes_to_utf8name_key(
    py: Python,
    data: &[u8],
) -> PyResult<(PyObject, PyObject, PyObject)> {
    let (name, file_id, revision_id) =
        bazaar::chk_inventory::chk_inventory_bytes_to_utf8_name_key(data);

    Ok((
        PyBytes::new(py, name).to_object(py),
        file_id.to_object(py),
        revision_id.to_object(py),
    ))
}

pub fn _inventory_rs(py: Python) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "inventory")?;

    m.add_class::<InventoryEntry>()?;
    m.add_class::<InventoryFile>()?;
    m.add_class::<InventoryLink>()?;
    m.add_class::<InventoryDirectory>()?;
    m.add_class::<TreeReference>()?;
    m.add_wrapped(wrap_pyfunction!(make_entry))?;
    m.add_wrapped(wrap_pyfunction!(is_valid_name))?;
    m.add_wrapped(wrap_pyfunction!(ensure_normalized_name))?;
    m.add_class::<Inventory>()?;

    m.add_class::<InventoryDelta>()?;
    m.add_wrapped(wrap_pyfunction!(parse_inventory_delta))?;
    m.add_wrapped(wrap_pyfunction!(parse_inventory_entry))?;
    m.add_wrapped(wrap_pyfunction!(serialize_inventory_delta))?;
    m.add_wrapped(wrap_pyfunction!(serialize_inventory_entry))?;
    m.add("InventoryDeltaError", py.get_type::<InventoryDeltaError>())?;
    m.add(
        "IncompatibleInventoryDelta",
        py.get_type::<IncompatibleInventoryDelta>(),
    )?;
    m.add_wrapped(wrap_pyfunction!(chk_inventory_entry_to_bytes))?;
    m.add_wrapped(wrap_pyfunction!(chk_inventory_bytes_to_entry))?;
    m.add_wrapped(wrap_pyfunction!(chk_inventory_bytes_to_utf8name_key))?;

    Ok(m)
}
