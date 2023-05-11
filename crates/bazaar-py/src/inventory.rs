use bazaar::inventory::Entry;
use bazaar::FileId;
use breezy_osutils::Kind;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

fn kind_from_str(kind: &str) -> Option<Kind> {
    match kind {
        "file" => Some(Kind::File),
        "directory" => Some(Kind::Directory),
        "tree-reference" => Some(Kind::TreeReference),
        "link" => Some(Kind::Symlink),
        _ => None,
    }
}

#[pyclass(subclass)]
pub struct InventoryEntry(Entry);

#[pymethods]
impl InventoryEntry {
    fn has_text(&self) -> bool {
        matches!(&self.0, Entry::File { .. })
    }

    fn kind_character(&self) -> &'static str {
        self.0.kind().marker()
    }

    #[getter]
    fn get_name(&self) -> &str {
        match &self.0 {
            Entry::File { name, .. } => name,
            Entry::Directory { name, .. } => name,
            Entry::TreeReference { name, .. } => name,
            Entry::Link { name, .. } => name,
        }
    }

    #[getter]
    fn get_file_id(&self, py: Python) -> PyObject {
        let file_id = match &self.0 {
            Entry::File { file_id, .. } => file_id,
            Entry::Directory { file_id, .. } => file_id,
            Entry::TreeReference { file_id, .. } => file_id,
            Entry::Link { file_id, .. } => file_id,
        };

        PyBytes::new(py, file_id.bytes()).into()
    }

    #[getter]
    fn get_parent_id(&self, py: Python) -> PyObject {
        let parent_id = match &self.0 {
            Entry::File { parent_id, .. } => parent_id,
            Entry::Directory { parent_id, .. } => parent_id,
            Entry::TreeReference { parent_id, .. } => parent_id,
            Entry::Link { parent_id, .. } => parent_id,
        };

        PyBytes::new(py, parent_id.bytes()).into()
    }

    #[getter]
    fn get_revision(&self, py: Python) -> Option<PyObject> {
        let revision = match &self.0 {
            Entry::File { revision, .. } => revision,
            Entry::Directory { revision, .. } => revision,
            Entry::TreeReference { revision, .. } => revision,
            Entry::Link { revision, .. } => revision,
        };

        revision
            .as_ref()
            .map(|revision| PyBytes::new(py, revision.bytes()).into())
    }

    #[staticmethod]
    fn versionable_kind(kind: &str) -> bool {
        if let Some(kind) = kind_from_str(kind) {
            bazaar::inventory::versionable_kind(kind)
        } else {
            false
        }
    }
}

#[pyclass(subclass,extends=InventoryEntry)]
struct InventoryFile();

#[pymethods]
impl InventoryFile {
    #[new]
    fn new(file_id: Vec<u8>, name: String, parent_id: Vec<u8>) -> (Self, InventoryEntry) {
        let entry = Entry::File {
            file_id: FileId::from(file_id),
            name,
            parent_id: FileId::from(parent_id),
            revision: None,
            text_sha1: None,
            text_size: None,
            text_id: None,
            executable: false,
        };
        (Self(), InventoryEntry(entry))
    }

    #[getter]
    fn get_executable(slf: PyRef<Self>) -> bool {
        let s = slf.into_super();
        match &s.0 {
            Entry::File { executable, .. } => *executable,
            _ => panic!("Not a file"),
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
}

#[pyclass(subclass,extends=InventoryEntry)]
struct InventoryDirectory();

#[pymethods]
impl InventoryDirectory {
    #[new]
    fn new(file_id: Vec<u8>, name: String, parent_id: Vec<u8>) -> (Self, InventoryEntry) {
        let entry = Entry::Directory {
            file_id: FileId::from(file_id),
            name,
            parent_id: FileId::from(parent_id),
            children: None,
            revision: None,
        };
        (Self(), InventoryEntry(entry))
    }
}

#[pyclass(subclass,extends=InventoryEntry)]
struct TreeReference();

#[pymethods]
impl TreeReference {
    #[new]
    fn new(file_id: Vec<u8>, name: String, parent_id: Vec<u8>) -> (Self, InventoryEntry) {
        let entry = Entry::TreeReference {
            file_id: FileId::from(file_id),
            name,
            parent_id: FileId::from(parent_id),
            revision: None,
            reference_revision: None,
        };
        (Self(), InventoryEntry(entry))
    }

    #[getter]
    fn get_reference_revision(slf: PyRef<Self>, py: Python) -> Option<PyObject> {
        let s = slf.into_super();
        match &s.0 {
            Entry::TreeReference {
                reference_revision, ..
            } => reference_revision
                .as_ref()
                .map(|reference_revision| PyBytes::new(py, reference_revision.bytes()).into()),
            _ => panic!("Not a tree reference"),
        }
    }
}

#[pyclass(subclass,extends=InventoryEntry)]
struct InventoryLink();

#[pymethods]
impl InventoryLink {
    #[new]
    fn new(file_id: Vec<u8>, name: String, parent_id: Vec<u8>) -> (Self, InventoryEntry) {
        let entry = Entry::Link {
            file_id: FileId::from(file_id),
            name,
            parent_id: FileId::from(parent_id),
            symlink_target: None,
            revision: None,
        };
        (Self(), InventoryEntry(entry))
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
}

pub fn _inventory_rs(py: Python) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "inventory")?;

    m.add_class::<InventoryEntry>()?;
    m.add_class::<InventoryFile>()?;
    m.add_class::<InventoryLink>()?;
    m.add_class::<InventoryDirectory>()?;
    m.add_class::<TreeReference>()?;

    Ok(m)
}
