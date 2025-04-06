#[cfg(feature = "pyo3")]
use pyo3::{prelude::*, types::PyBytes};
use std::fmt::{Debug, Error, Formatter};

pub const DEFAULT_CHUNK_SIZE: usize = 4096;

pub mod bencode_serializer;
pub mod chk_inventory;
pub mod chk_map;
pub mod dirstate;
pub mod filters;
pub mod gen_ids;
pub mod globbing;
pub mod groupcompress;
pub mod hashcache;
pub mod inventory;
pub mod inventory_delta;
pub mod repository;
pub mod revision;
pub mod rio;
pub mod serializer;
pub mod smart;
pub mod versionedfile;
pub mod xml_serializer;

#[cfg(feature = "pyo3")]
pub mod pyversionedfile;

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

    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }
}

#[cfg(feature = "pyo3")]
impl FromPyObject<'_> for FileId {
    fn extract_bound(ob: &Bound<PyAny>) -> PyResult<Self> {
        let s: Vec<u8> = ob.extract()?;
        Ok(FileId::from(s))
    }
}

#[cfg(feature = "pyo3")]
impl<'py> IntoPyObject<'py> for &FileId {
    type Target = pyo3::types::PyBytes;

    type Output = Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        Ok(PyBytes::new(py, &self.0))
    }
}

#[cfg(feature = "pyo3")]
impl<'py> IntoPyObject<'py> for FileId {
    type Target = pyo3::types::PyBytes;

    type Output = Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        (&self).into_pyobject(py)
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
    fn extract_bound(ob: &Bound<PyAny>) -> PyResult<Self> {
        let s: Vec<u8> = ob.extract()?;
        if !is_valid(&s) {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Invalid revision id: {:?}",
                s
            )));
        }
        Ok(RevisionId::from(s))
    }
}

#[cfg(feature = "pyo3")]
impl<'py> IntoPyObject<'py> for &RevisionId {
    type Target = pyo3::types::PyBytes;

    type Output = Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        let obj = PyBytes::new(py, &self.0);
        Ok(obj)
    }
}

#[cfg(feature = "pyo3")]
impl<'py> IntoPyObject<'py> for RevisionId {
    type Target = pyo3::types::PyBytes;

    type Output = Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        (&self).into_pyobject(py)
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
