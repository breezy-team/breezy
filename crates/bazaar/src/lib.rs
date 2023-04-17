pub mod filters;
use std::fmt::{Debug, Error, Formatter};

pub mod gen_ids;

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

impl FileId {
    pub fn generate(name: &str) -> Self {
        Self::from(gen_ids::gen_file_id(name))
    }
}

#[derive(Clone, PartialEq, Eq, Hash)]
pub struct RevisionId(Vec<u8>);

impl Debug for RevisionId {
    fn fmt(&self, f: &mut Formatter) -> Result<(), Error> {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl From<Vec<u8>> for RevisionId {
    fn from(v: Vec<u8>) -> Self {
        RevisionId(v)
    }
}

impl From<RevisionId> for Vec<u8> {
    fn from(v: RevisionId) -> Self {
        v.0
    }
}

const NULL_REVISION: &[u8] = b"null:";

impl RevisionId {
    pub fn is_null(&self) -> bool {
        self.0 == NULL_REVISION
    }

    pub fn generate(username: &str, timestamp: Option<u64>) -> Self {
        Self::from(gen_ids::gen_revision_id(username, timestamp))
    }
}
