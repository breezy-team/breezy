use std::fmt::{Debug, Error, Formatter};

pub mod bencode_serializer;
pub mod filters;
pub mod gen_ids;
pub mod globbing;
pub mod inventory;
pub mod revision;
pub mod serializer;
pub mod xml_serializer;

#[derive(Clone, PartialEq, Eq, Hash)]
pub struct FileId(Vec<u8>);

impl Debug for FileId {
    fn fmt(&self, f: &mut Formatter) -> Result<(), Error> {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl From<Vec<u8>> for FileId {
    fn from(v: Vec<u8>) -> Self {
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
        FileId(v.to_vec())
    }
}

impl FileId {
    pub fn generate(name: &str) -> Self {
        Self::from(gen_ids::gen_file_id(name))
    }

    pub fn bytes(&self) -> &[u8] {
        &self.0
    }
}

#[derive(Clone, PartialEq, Eq, Hash)]
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
        RevisionId(v)
    }
}

impl From<&[u8]> for RevisionId {
    fn from(v: &[u8]) -> Self {
        RevisionId(v.to_vec())
    }
}

impl From<RevisionId> for Vec<u8> {
    fn from(v: RevisionId) -> Self {
        v.0
    }
}

pub const NULL_REVISION: &[u8] = b"null:";
pub const CURRENT_REVISION: &[u8] = b"current:";

impl RevisionId {
    pub fn is_null(&self) -> bool {
        self.0 == NULL_REVISION
    }

    pub fn generate(username: &str, timestamp: Option<u64>) -> Self {
        Self::from(gen_ids::gen_revision_id(username, timestamp))
    }

    pub fn bytes(&self) -> &[u8] {
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
