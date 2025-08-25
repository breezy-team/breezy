use crate::revision::Revision;
use std::io::Read;

#[derive(Debug)]
pub enum Error {
    DecodeError(String),
    EncodeError(String),
    IOError(std::io::Error),
}

impl From<std::io::Error> for Error {
    fn from(error: std::io::Error) -> Self {
        Error::IOError(error)
    }
}

pub trait RevisionSerializer: Send + Sync {
    fn format_name(&self) -> &'static str;

    fn squashes_xml_invalid_characters(&self) -> bool;

    fn read_revision(&self, file: &mut dyn Read) -> Result<Revision, Error>;

    fn write_revision_to_string(&self, revision: &Revision) -> Result<Vec<u8>, Error>;

    fn write_revision_to_lines(
        &self,
        revision: &Revision,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>>>;

    fn read_revision_from_string(&self, string: &[u8]) -> Result<Revision, Error>;
}
