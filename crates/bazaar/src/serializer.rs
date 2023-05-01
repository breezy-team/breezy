use crate::revision::Revision;
use std::collections::HashMap;
use std::io::{Read, Write};

pub struct Error {
    pub message: String,
}

pub trait RevisionSerializer: Send + Sync {
    fn format_name(&self) -> &'static str;

    fn read_revision(&mut self, file: &dyn Read) -> Result<Revision, Error>;

    fn write_revision_to_string(&mut self, revision: &Revision) -> Result<Vec<u8>, Error>;

    fn write_revision_to_lines(
        &mut self,
        revision: &Revision,
    ) -> dyn Iterator<Item = Result<Vec<u8>, Error>>;

    fn read_revision_from_string(&mut self, string: &[u8]) -> Result<Revision, Error>;
}
