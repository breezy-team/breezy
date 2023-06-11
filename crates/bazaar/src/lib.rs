#[cfg(feature = "pyo3")]
use pyo3::{prelude::*, types::PyBytes, ToPyObject};
use std::fmt::{Debug, Error, Formatter};

pub mod bencode_serializer;
pub mod chk_inventory;
pub mod filters;
pub mod gen_ids;
pub mod globbing;
pub mod hashcache;
pub mod inventory;
pub mod inventory_delta;
pub mod revision;
pub mod rio;
pub mod serializer;
pub mod xml_serializer;

#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct FileId(Vec<u8>);

impl Debug for FileId {
    fn fmt(&self, f: &mut Formatter) -> Result<(), Error> {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl From<Vec<u8>> for FileId {
    fn from(v: Vec<u8>) -> Self {
        check_valid(&v);
        FileId(v)
    }
}

impl From<FileId> for Vec<u8> {
    fn from(v: FileId) -> Self {
        v.0
    }
}

impl From<&[u8]> for FileId {
    fn from(v: &[u8]) -> Self {
        check_valid(v);
        FileId(v.to_vec())
    }
}

impl From<&Vec<u8>> for FileId {
    fn from(v: &Vec<u8>) -> Self {
        FileId::from(v.as_slice())
    }
}

impl FileId {
    pub fn generate(name: &str) -> Self {
        Self::from(gen_ids::gen_file_id(name))
    }

    pub fn generate_root_id() -> Self {
        Self::from(gen_ids::gen_root_id())
    }

    #[deprecated]
    pub fn bytes(&self) -> &[u8] {
        &self.0
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }
}

#[cfg(feature = "pyo3")]
impl FromPyObject<'_> for FileId {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        let s: Vec<u8> = ob.extract()?;
        Ok(FileId::from(s))
    }
}

#[cfg(feature = "pyo3")]
impl ToPyObject for FileId {
    fn to_object(&self, py: Python) -> PyObject {
        PyBytes::new(py, &self.0).to_object(py)
    }
}

impl std::fmt::Display for FileId {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct RevisionId(Vec<u8>);

impl Debug for RevisionId {
    fn fmt(&self, f: &mut Formatter) -> Result<(), Error> {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl std::fmt::Display for RevisionId {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl From<Vec<u8>> for RevisionId {
    fn from(v: Vec<u8>) -> Self {
        check_valid(&v);
        RevisionId(v)
    }
}

impl From<&[u8]> for RevisionId {
    fn from(v: &[u8]) -> Self {
        check_valid(v);
        RevisionId(v.to_vec())
    }
}

impl From<RevisionId> for Vec<u8> {
    fn from(v: RevisionId) -> Self {
        v.0
    }
}

#[cfg(feature = "pyo3")]
impl FromPyObject<'_> for RevisionId {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        let s: Vec<u8> = ob.extract()?;
        Ok(RevisionId::from(s))
    }
}

#[cfg(feature = "pyo3")]
impl ToPyObject for RevisionId {
    fn to_object(&self, py: Python) -> PyObject {
        PyBytes::new(py, &self.0).to_object(py)
    }
}

pub const NULL_REVISION: &[u8] = b"null:";
pub const CURRENT_REVISION: &[u8] = b"current:";

pub fn is_valid(id: &[u8]) -> bool {
    if id.contains(&b' ') || id.contains(&b'\t') || id.contains(&b'\n') || id.contains(&b'\r') {
        return false;
    }

    if id.is_empty() {
        return false;
    }

    true
}

pub fn check_valid(id: &[u8]) {
    if !is_valid(id) {
        if let Ok(id) = String::from_utf8(id.to_vec()) {
            panic!("Invalid id: {:?}", id);
        } else {
            panic!("Invalid id: {:?}", id);
        }
    }
}

impl RevisionId {
    pub fn is_null(&self) -> bool {
        self.0 == NULL_REVISION
    }

    pub fn generate(username: &str, timestamp: Option<u64>) -> Self {
        Self::from(gen_ids::gen_revision_id(username, timestamp))
    }

    #[deprecated]
    pub fn bytes(&self) -> &[u8] {
        &self.0
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }

    pub fn is_reserved(&self) -> bool {
        self.0.ends_with(b":")
    }

    pub fn expect_not_reserved(&self) {
        if self.is_reserved() {
            panic!("Expected non-reserved revision id, got {:?}", self);
        }
    }
}
