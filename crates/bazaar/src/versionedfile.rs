use byteorder::{BigEndian, WriteBytesExt};

use pyo3::prelude::PyAnyMethods;
use pyo3::types::{PyBytes, PyTuple};
use std::borrow::Cow;
use std::collections::HashMap;
use std::convert::TryInto;

#[derive(Debug)]
pub enum Error {
    ExistingContent(Key),
    VersionNotPresent(VersionId),
    Io(std::io::Error),
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Error {
        Error::Io(e)
    }
}

#[cfg(feature = "pyo3")]
impl From<Error> for pyo3::PyErr {
    fn from(e: Error) -> pyo3::PyErr {
        pyo3::import_exception!(breezy.errors, RevisionNotPresent);
        pyo3::import_exception!(breezy.bzr.versionedfile, ExistingContent);
        match e {
            Error::VersionNotPresent(key) => {
                RevisionNotPresent::new_err(format!("Version not present: {:?}", key))
            }
            Error::ExistingContent(key) => {
                ExistingContent::new_err(format!("Existing content: {:?}", key))
            }
            Error::Io(e) => e.into(),
        }
    }
}

#[cfg(feature = "pyo3")]
impl From<pyo3::PyErr> for Error {
    fn from(e: pyo3::PyErr) -> Error {
        pyo3::import_exception!(breezy.errors, RevisionNotPresent);
        pyo3::import_exception!(breezy.bzr.versionedfile, ExistingContent);
        pyo3::Python::attach(|py| {
            if e.is_instance_of::<RevisionNotPresent>(py) {
                Error::VersionNotPresent(
                    e.value(py)
                        .getattr("args")
                        .unwrap()
                        .get_item(0)
                        .unwrap()
                        .extract()
                        .unwrap(),
                )
            } else if e.is_instance_of::<ExistingContent>(py) {
                Error::ExistingContent(
                    e.value(py)
                        .getattr("args")
                        .unwrap()
                        .get_item(0)
                        .unwrap()
                        .extract()
                        .unwrap(),
                )
            } else {
                panic!("Unexpected error: {:?}", e)
            }
        })
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Error::ExistingContent(key) => write!(f, "Existing content: {:?}", key),
            Error::VersionNotPresent(version) => write!(f, "Version not present: {:?}", version),
            Error::Io(e) => write!(f, "IO error: {}", e),
        }
    }
}

impl std::error::Error for Error {}

pub enum Ordering {
    Unordered,
    Topological,
}

impl ToString for Ordering {
    fn to_string(&self) -> String {
        match self {
            Ordering::Unordered => "unordered".to_string(),
            Ordering::Topological => "topological".to_string(),
        }
    }
}

#[cfg(feature = "pyo3")]
impl<'py> pyo3::IntoPyObject<'py> for Ordering {
    type Target = pyo3::types::PyString;

    type Output = pyo3::Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: pyo3::Python<'py>) -> Result<Self::Output, Self::Error> {
        Ok(self.to_string().into_pyobject(py)?)
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::FromPyObject<'_> for Ordering {
    fn extract_bound(ob: &pyo3::Bound<pyo3::PyAny>) -> pyo3::PyResult<Self> {
        use pyo3::prelude::*;
        let s = ob.extract::<String>()?;
        match s.as_str() {
            "unordered" => Ok(Ordering::Unordered),
            "topological" => Ok(Ordering::Topological),
            _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Expected 'unordered' or 'topological', got '{}'",
                s
            ))),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct VersionId(Vec<u8>);

#[cfg(feature = "pyo3")]
impl<'py> pyo3::IntoPyObject<'py> for &VersionId {
    type Target = pyo3::types::PyBytes;

    type Output = pyo3::Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: pyo3::Python<'py>) -> Result<Self::Output, Self::Error> {
        let bytes = PyBytes::new(py, &self.0);
        Ok(bytes.into_pyobject(py)?)
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::FromPyObject<'_> for VersionId {
    fn extract_bound(ob: &pyo3::Bound<pyo3::PyAny>) -> pyo3::PyResult<Self> {
        use pyo3::prelude::*;
        let bytes = ob.extract::<Vec<u8>>()?;
        Ok(VersionId(bytes))
    }
}

impl std::fmt::Display for VersionId {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "VersionId({:?})", self.0)?;
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Key {
    Fixed(Vec<Vec<u8>>),
    ContentAddressed(Vec<Vec<u8>>),
}

impl Key {
    pub fn add_prefix(&mut self, prefix: &[&[u8]]) {
        let v = match self {
            Key::Fixed(ref mut v) => v,
            Key::ContentAddressed(ref mut v) => v,
        };
        for p in prefix.iter().rev() {
            v.insert(0, p.to_vec());
        }
    }
}

impl std::fmt::Display for Key {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Key::Fixed(v) => {
                write!(f, "(")?;
                for (i, v) in v.iter().enumerate() {
                    if i > 0 {
                        write!(f, ", ")?;
                    }
                    write!(f, "{:?}", v)?;
                }
                write!(f, ")")
            }
            Key::ContentAddressed(v) => {
                write!(f, "(")?;
                for v in v.iter() {
                    write!(f, "{:?}", v)?;
                    write!(f, ", ")?;
                }
                write!(f, "<ContentAddressed>")?;
                write!(f, ")")
            }
        }
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::FromPyObject<'_> for Key {
    fn extract_bound(ob: &pyo3::Bound<pyo3::PyAny>) -> pyo3::PyResult<Self> {
        use pyo3::prelude::*;
        // Look at the type name, stripping out the module name.
        match ob
            .get_type()
            .name()
            .unwrap()
            .to_string()
            .split('.')
            .next_back()
            .unwrap()
        {
            "tuple" | "StaticTuple" => {}
            _ => {
                return Err(pyo3::exceptions::PyTypeError::new_err(format!(
                    "Expected tuple or StaticTuple, got {}",
                    ob.get_type().name().unwrap()
                )));
            }
        }
        let mut v = Vec::with_capacity(ob.len()?);
        for i in 0..ob.len()? - 1 {
            let b = ob.get_item(i)?.extract::<Bound<PyBytes>>()?;
            v.push(b.as_bytes().to_vec());
        }
        if let Some(b) = ob
            .get_item(ob.len()? - 1)?
            .extract::<Option<Bound<PyBytes>>>()?
        {
            v.push(b.as_bytes().to_vec());
            Ok(Key::Fixed(v))
        } else {
            Ok(Key::ContentAddressed(v))
        }
    }
}

#[cfg(feature = "pyo3")]
impl<'py> pyo3::IntoPyObject<'py> for Key {
    type Target = pyo3::types::PyTuple;

    type Output = pyo3::Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: pyo3::Python<'py>) -> Result<Self::Output, Self::Error> {
        match self {
            Key::Fixed(v) => {
                let t = PyTuple::new(
                    py,
                    v.into_iter()
                        .map(|v| pyo3::types::PyBytes::new(py, v.as_slice())),
                );
                t
            }
            Key::ContentAddressed(v) => {
                let mut entries = v
                    .into_iter()
                    .map(|v| pyo3::types::PyBytes::new(py, v.as_slice()).into_any())
                    .collect::<Vec<_>>();
                entries.push(py.None().into_bound(py).into_any());
                PyTuple::new(py, entries)
            }
        }
    }
}

impl bendy::encoding::ToBencode for Key {
    const MAX_DEPTH: usize = 10;

    fn encode(
        &self,
        encoder: bendy::encoding::SingleItemEncoder<'_>,
    ) -> Result<(), bendy::encoding::Error> {
        match self {
            Key::Fixed(v) => encoder.emit_list(|e| {
                for v in v.iter() {
                    e.emit_bytes(v)?;
                }
                Ok(())
            }),
            Key::ContentAddressed(_v) => {
                panic!("ContentAddressed keys are not supported in bencode")
            }
        }
    }
}

#[test]
fn test_key_bencode() {
    let x = Key::Fixed(vec![b"foo".to_vec(), b"bar".to_vec()]);
    let z = bendy::encoding::ToBencode::to_bencode(&x).unwrap();
    assert_eq!(z, b"l3:foo3:bare".to_vec());
}

pub trait ContentFactory {
    /// None, or the sha1 of the content fulltext
    fn sha1(&self) -> Option<Vec<u8>>;

    /// None, or the size of the content fulltext.
    fn size(&self) -> Option<usize>;

    /// The key of this content. Each key is a tuple with a single string in it.
    fn key(&self) -> Key;

    /// A tuple of parent keys for self.key. If the object has no parent information, None (as
    /// opposed to () for an empty list of parents).
    fn parents(&self) -> Option<Vec<Key>>;

    fn to_fulltext<'a, 'b>(&'a self) -> Cow<'b, [u8]>
    where
        'a: 'b;

    fn to_chunks<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>> + 'b>
    where
        'a: 'b;

    fn to_lines<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>> + 'b>
    where
        'a: 'b;

    fn into_fulltext(self) -> Vec<u8>;

    fn into_chunks(self) -> Box<dyn Iterator<Item = Vec<u8>>>;

    fn into_lines(self) -> Box<dyn Iterator<Item = Vec<u8>>>
    where
        Self: Sized,
    {
        Box::new(
            breezy_osutils::chunks_to_lines(self.into_chunks().map(Ok::<_, std::io::Error>))
                .map(|v| v.unwrap().into_owned()),
        )
    }

    fn storage_kind(&self) -> String;

    fn map_key(&mut self, f: &dyn Fn(Key) -> Key);
}

pub struct FulltextContentFactory {
    sha1: Option<Vec<u8>>,
    size: usize,
    key: Key,
    parents: Option<Vec<Key>>,
    fulltext: Vec<u8>,
}

impl ContentFactory for FulltextContentFactory {
    fn sha1(&self) -> Option<Vec<u8>> {
        self.sha1.clone()
    }

    fn size(&self) -> Option<usize> {
        Some(self.size)
    }

    fn key(&self) -> Key {
        self.key.clone()
    }

    fn parents(&self) -> Option<Vec<Key>> {
        self.parents.clone()
    }

    fn to_fulltext<'a, 'b>(&'a self) -> Cow<'b, [u8]>
    where
        'a: 'b,
    {
        Cow::Borrowed(&self.fulltext)
    }

    fn to_chunks<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>> + 'b>
    where
        'a: 'b,
    {
        Box::new(
            self.fulltext
                .as_slice()
                .chunks(crate::DEFAULT_CHUNK_SIZE)
                .map(|v| v.into()),
        )
    }

    fn to_lines<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>> + 'b>
    where
        'a: 'b,
    {
        Box::new(
            breezy_osutils::chunks_to_lines(std::iter::once(Ok::<_, std::io::Error>(
                &self.fulltext,
            )))
            .map(|v| v.unwrap()),
        )
    }

    fn into_fulltext(self) -> Vec<u8> {
        self.fulltext
    }

    fn into_chunks(self) -> Box<dyn Iterator<Item = Vec<u8>>> {
        let mut fulltext = self.fulltext;
        Box::new(std::iter::from_fn(move || {
            if fulltext.is_empty() {
                None
            } else {
                let chunk = fulltext
                    .drain(..std::cmp::min(crate::DEFAULT_CHUNK_SIZE, fulltext.len()))
                    .collect::<Vec<_>>();
                Some(chunk)
            }
        }))
    }

    fn storage_kind(&self) -> String {
        "fulltext".into()
    }

    fn map_key(&mut self, f: &dyn Fn(Key) -> Key) {
        self.key = f(self.key.clone());
        self.parents = self.parents.take().map(|v| v.into_iter().map(f).collect());
    }
}

impl FulltextContentFactory {
    pub fn new(
        sha1: Option<Vec<u8>>,
        key: Key,
        parents: Option<Vec<Key>>,
        fulltext: Vec<u8>,
    ) -> Self {
        Self {
            sha1,
            size: fulltext.len(),
            key,
            parents,
            fulltext,
        }
    }
}

pub struct ChunkedContentFactory {
    sha1: Option<Vec<u8>>,
    size: usize,
    key: Key,
    parents: Option<Vec<Key>>,
    chunks: Vec<Vec<u8>>,
}

impl ChunkedContentFactory {
    pub fn new(
        sha1: Option<Vec<u8>>,
        key: Key,
        parents: Option<Vec<Key>>,
        chunks: Vec<Vec<u8>>,
    ) -> Self {
        Self {
            sha1,
            size: chunks.iter().map(|v| v.len()).sum(),
            key,
            parents,
            chunks,
        }
    }
}

impl ContentFactory for ChunkedContentFactory {
    fn sha1(&self) -> Option<Vec<u8>> {
        self.sha1.clone()
    }

    fn size(&self) -> Option<usize> {
        Some(self.size)
    }

    fn key(&self) -> Key {
        self.key.clone()
    }

    fn parents(&self) -> Option<Vec<Key>> {
        self.parents.clone()
    }

    fn to_fulltext<'a, 'b>(&'a self) -> Cow<'b, [u8]>
    where
        'a: 'b,
    {
        self.chunks.concat().into()
    }

    fn to_chunks<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>> + 'b>
    where
        'a: 'b,
    {
        Box::new(self.chunks.iter().map(|v| v.into()))
    }

    fn to_lines<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>> + 'b>
    where
        'a: 'b,
    {
        Box::new(
            breezy_osutils::chunks_to_lines(self.chunks.iter().map(Ok::<_, std::io::Error>))
                .map(|l| l.unwrap()),
        )
    }

    fn into_fulltext(self) -> Vec<u8> {
        self.chunks.into_iter().flatten().collect()
    }

    fn into_chunks(self) -> Box<dyn Iterator<Item = Vec<u8>>> {
        Box::new(self.chunks.into_iter())
    }

    fn storage_kind(&self) -> String {
        "chunked".into()
    }

    fn map_key(&mut self, f: &dyn Fn(Key) -> Key) {
        self.key = f(self.key.clone());
        self.parents = self.parents.take().map(|v| v.into_iter().map(f).collect());
    }
}

pub struct AbsentContentFactory {
    key: Key,
}

impl AbsentContentFactory {
    pub fn new(key: Key) -> Self {
        Self { key }
    }
}

impl ContentFactory for AbsentContentFactory {
    fn sha1(&self) -> Option<Vec<u8>> {
        None
    }

    fn size(&self) -> Option<usize> {
        None
    }

    fn key(&self) -> Key {
        self.key.clone()
    }

    fn parents(&self) -> Option<Vec<Key>> {
        None
    }

    fn to_fulltext<'a, 'b>(&'a self) -> Cow<'b, [u8]>
    where
        'a: 'b,
    {
        panic!("A request was made for key: {}, but that content is not available, and the calling code does not handle if it is missing.", self.key);
    }

    fn to_chunks<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>> + 'b>
    where
        'a: 'b,
    {
        panic!("A request was made for key: {}, but that content is not available, and the calling code does not handle if it is missing.", self.key);
    }

    fn to_lines<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>> + 'b>
    where
        'a: 'b,
    {
        panic!("A request was made for key: {}, but that content is not available, and the calling code does not handle if it is missing.", self.key);
    }

    fn into_fulltext(self) -> Vec<u8> {
        panic!("A request was made for key: {}, but that content is not available, and the calling code does not handle if it is missing.", self.key);
    }

    fn into_chunks(self) -> Box<dyn Iterator<Item = Vec<u8>>> {
        panic!("A request was made for key: {}, but that content is not available, and the calling code does not handle if it is missing.", self.key);
    }

    fn storage_kind(&self) -> String {
        "absent".into()
    }

    fn map_key(&mut self, f: &dyn Fn(Key) -> Key) {
        self.key = f(self.key.clone());
    }
}

pub trait VersionedFile<CF: ContentFactory, I> {
    fn check_not_reserved_id(id: &VersionId) -> bool;

    fn get_record_stream(
        &self,
        keys: &[&VersionId],
        ordering: Ordering,
        include_delta_closure: bool,
    ) -> Box<dyn Iterator<Item = CF>>;

    fn add_lines<'a>(
        &mut self,
        version_id: &VersionId,
        parent_texts: Option<HashMap<VersionId, I>>,
        lines: impl Iterator<Item = &'a [u8]>,
        nostore_sha: Option<bool>,
        random_id: bool,
    ) -> Result<(Vec<u8>, usize, I), Error>;

    fn has_version(&self, version_id: &VersionId) -> bool;

    fn insert_record_stream(
        &mut self,
        stream: impl Iterator<Item = Box<dyn ContentFactory>>,
    ) -> Result<(), Error>;

    fn get_format_signature(&self) -> String;

    fn get_lines(
        &self,
        version_id: &VersionId,
    ) -> Result<Box<dyn Iterator<Item = Vec<u8>>>, Error> {
        let record_stream = self.get_record_stream(&[version_id], Ordering::Unordered, false);
        if let Some(record) = record_stream.into_iter().next() {
            Ok(record.into_lines())
        } else {
            Err(Error::VersionNotPresent(version_id.clone()))
        }
    }

    fn get_text(&self, version_id: &VersionId) -> Result<Vec<u8>, Error> {
        let record_stream = self.get_record_stream(&[version_id], Ordering::Unordered, false);
        if let Some(record) = record_stream.into_iter().next() {
            Ok(record.into_fulltext())
        } else {
            Err(Error::VersionNotPresent(version_id.clone()))
        }
    }

    fn get_chunks(
        &self,
        version_id: &VersionId,
    ) -> Result<Box<dyn Iterator<Item = Vec<u8>>>, Error> {
        let record_stream = self.get_record_stream(&[version_id], Ordering::Unordered, false);
        if let Some(record) = record_stream.into_iter().next() {
            Ok(record.into_chunks())
        } else {
            Err(Error::VersionNotPresent(version_id.clone()))
        }
    }
}

/// Storage for many versioned files.
///
/// This object allows a single keyspace for accessing the history graph and
/// contents of named bytestrings.
///
/// Currently no implementation allows the graph of different key prefixes to
/// intersect, but the API does allow such implementations in the future.
///
/// The keyspace is expressed via simple tuples. Any instance of VersionedFiles
/// may have a different length key-size, but that size will be constant for
/// all texts added to or retrieved from it. For instance, breezy uses
/// instances with a key-size of 2 for storing user files in a repository, with
/// the first element the fileid, and the second the version of that file.
///
/// The use of tuples allows a single code base to support several different
/// uses with only the mapping logic changing from instance to instance.
///
/// :ivar _immediate_fallback_vfs: For subclasses that support stacking,
///     this is a list of other VersionedFiles immediately underneath this
///     one.  They may in turn each have further fallbacks.
pub trait VersionedFiles<CF: ContentFactory, I> {
    fn check_not_reserved_id(id: &VersionId) -> bool;

    fn get_record_stream(
        &self,
        keys: &[&Key],
        ordering: Ordering,
        include_delta_closure: bool,
    ) -> Box<dyn Iterator<Item = CF>>;
}

pub fn record_to_fulltext_bytes<R: ContentFactory, W: std::io::Write>(
    record: R,
    w: &mut W,
) -> std::io::Result<()> {
    let mut record_meta = bendy::encoding::Encoder::new();

    record_meta
        .emit_list(|e| {
            e.emit(record.key())?;
            if let Some(parents) = record.parents() {
                e.emit_list(|e| {
                    for parent in parents {
                        e.emit(parent)?;
                    }
                    Ok(())
                })?;
            } else {
                e.emit_bytes(&b"nil"[..])?; // default to a single byte vector containing "nil"
            }
            Ok(())
        })
        .unwrap();

    let record_meta = record_meta.get_output().unwrap();

    w.write_all(b"fulltext\n")?;
    w.write_all(&length_prefix(&record_meta))?;
    w.write_all(&record_meta)?;
    w.write_all(&record.into_fulltext())?;

    Ok(())
}

fn length_prefix(data: &[u8]) -> Vec<u8> {
    let length = data.len() as u32;
    let mut length_bytes = vec![];

    // Write the length as a 4-byte big-endian representation
    length_bytes
        .write_u32::<BigEndian>(length)
        .expect("Failed to write length bytes");

    length_bytes
}

pub fn fulltext_network_to_record(bytes: &[u8], line_end: usize) -> FulltextContentFactory {
    // Extract meta_len from the network fulltext record
    let meta_len_bytes: [u8; 4] = bytes[line_end..line_end + 4]
        .try_into()
        .expect("Expected 4 bytes for meta_len");
    let meta_len = u32::from_be_bytes(meta_len_bytes) as usize;

    // Extract record_meta using meta_len
    let record_meta = &bytes[line_end + 4..line_end + 4 + meta_len];

    // Decode record_meta using Bencode
    let mut decoder = bendy::decoding::Decoder::new(record_meta);

    let mut tuple = decoder
        .next_object()
        .expect("Failed to decode record_meta using Bencode")
        .expect("Failed to decode tuple using Bencode")
        .try_into_list()
        .unwrap();

    fn decode_key(o: bendy::decoding::Object) -> Key {
        let mut ret = vec![];

        let mut l = o.try_into_list().unwrap();

        while let Some(b) = l.next_object().unwrap() {
            ret.push(b.try_into_bytes().unwrap().to_vec());
        }

        Key::Fixed(ret)
    }

    let key = decode_key(
        tuple
            .next_object()
            .expect("Failed to decode record_meta using Bencode")
            .expect("Failed to decode key using Bencode"),
    );

    let parents = tuple
        .next_object()
        .expect("Failed to decode record_meta using Bencode")
        .expect("Failed to decode parents using Bencode");

    // Convert parents from "nil" to None
    let parents = match parents {
        bendy::decoding::Object::Bytes(bytes) => {
            if bytes == b"nil" {
                None
            } else {
                panic!("Expected parents to be a list or nil");
            }
        }
        bendy::decoding::Object::List(mut l) => {
            let mut parents = vec![];
            while let Some(parent) = l.next_object().unwrap() {
                parents.push(decode_key(parent));
            }
            Some(parents)
        }
        _ => panic!("Expected parents to be a list or nil"),
    };

    // Extract fulltext from the remaining bytes
    let fulltext = &bytes[line_end + 4 + meta_len..];

    FulltextContentFactory::new(None, key, parents, fulltext.to_vec())
}
