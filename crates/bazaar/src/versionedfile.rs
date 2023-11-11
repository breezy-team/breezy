use byteorder::{BigEndian, WriteBytesExt};
use pyo3::types::{PyBytes, PyTuple};
use std::borrow::Cow;
use std::collections::HashMap;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Error {
    VersionNotPresent(Key),
}

#[cfg(feature = "pyo3")]
impl From<Error> for pyo3::PyErr {
    fn from(e: Error) -> pyo3::PyErr {
        pyo3::import_exception!(breezy.errors, RevisionNotPresent);
        match e {
            Error::VersionNotPresent(key) => {
                RevisionNotPresent::new_err(format!("Version not present: {:?}", key))
            }
        }
    }
}

#[cfg(feature = "pyo3")]
impl From<pyo3::PyErr> for Error {
    fn from(e: pyo3::PyErr) -> Error {
        pyo3::import_exception!(breezy.errors, RevisionNotPresent);
        pyo3::Python::with_gil(|py| {
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
            } else {
                panic!("Unexpected error: {:?}", e)
            }
        })
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Error::VersionNotPresent(key) => write!(f, "Version not present: {:?}", key),
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
impl pyo3::IntoPy<pyo3::PyObject> for Ordering {
    fn into_py(self, py: pyo3::Python) -> pyo3::PyObject {
        self.to_string().into_py(py)
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::FromPyObject<'_> for Ordering {
    fn extract(ob: &pyo3::PyAny) -> pyo3::PyResult<Self> {
        let s = ob.extract::<String>()?;
        match s.as_str() {
            "unordered" => Ok(Ordering::Unordered),
            "topological" => Ok(Ordering::Topological),
            _ => Err(pyo3::exceptions::PyValueError::new_err(
                "Expected 'unordered' or 'topological'".to_string(),
            )),
        }
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
impl pyo3::ToPyObject for Key {
    fn to_object(&self, py: pyo3::Python) -> pyo3::PyObject {
        match self {
            Key::Fixed(ref v) => {
                let t = PyTuple::new(
                    py,
                    v.iter()
                        .map(|v| pyo3::types::PyBytes::new(py, v.as_slice())),
                );
                t.to_object(py)
            }
            Key::ContentAddressed(ref v) => {
                let mut entries = v
                    .iter()
                    .map(|v| pyo3::types::PyBytes::new(py, v.as_slice()).to_object(py))
                    .collect::<Vec<_>>();
                entries.push(py.None());
                PyTuple::new(py, entries).to_object(py)
            }
        }
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::FromPyObject<'_> for Key {
    fn extract(ob: &pyo3::PyAny) -> pyo3::PyResult<Self> {
        match ob.get_type().name().unwrap() {
            "tuple" | "StaticTuple" => {}
            _ => {
                return Err(pyo3::exceptions::PyTypeError::new_err(
                    "Expected tuple or StaticTuple".to_string(),
                ));
            }
        }
        let mut v = Vec::with_capacity(ob.len()?);
        for i in 0..ob.len()? - 1 {
            let b = ob.get_item(i)?.extract::<&PyBytes>()?;
            v.push(b.as_bytes().to_vec());
        }
        if let Some(b) = ob.get_item(ob.len()? - 1)?.extract::<Option<&PyBytes>>()? {
            v.push(b.as_bytes().to_vec());
            Ok(Key::Fixed(v))
        } else {
            Ok(Key::ContentAddressed(v))
        }
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::IntoPy<pyo3::PyObject> for Key {
    fn into_py(self, py: pyo3::Python) -> pyo3::PyObject {
        match self {
            Key::Fixed(v) => {
                let t = PyTuple::new(
                    py,
                    v.into_iter()
                        .map(|v| pyo3::types::PyBytes::new(py, v.as_slice())),
                );
                t.into_py(py)
            }
            Key::ContentAddressed(v) => {
                let mut entries = v
                    .into_iter()
                    .map(|v| pyo3::types::PyBytes::new(py, v.as_slice()).into_py(py))
                    .collect::<Vec<_>>();
                entries.push(py.None());
                PyTuple::new(py, entries).into_py(py)
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

    fn add_key_prefix(&mut self, prefix: &[&[u8]]);
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

    fn add_key_prefix(&mut self, prefix: &[&[u8]]) {
        self.key.add_prefix(prefix);
        if let Some(parents) = self.parents.as_mut() {
            for parent in parents {
                parent.add_prefix(prefix);
            }
        }
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

    fn add_key_prefix(&mut self, prefix: &[&[u8]]) {
        self.key.add_prefix(prefix);
        if let Some(parents) = self.parents.as_mut() {
            for parent in parents {
                parent.add_prefix(prefix);
            }
        }
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

    fn add_key_prefix(&mut self, prefix: &[&[u8]]) {
        self.key.add_prefix(prefix);
    }
}

pub trait VersionedFile<CF: ContentFactory, I> {
    fn get_record_stream(
        &self,
        keys: &[&Key],
        ordering: Ordering,
        include_delta_closure: bool,
    ) -> Box<dyn Iterator<Item = CF>>;

    fn add_lines<'a>(
        &mut self,
        version_id: &Key,
        parent_texts: Option<HashMap<Key, I>>,
        lines: impl Iterator<Item = &'a [u8]>,
        nostore_sha: Option<bool>,
        random_id: bool,
    ) -> Result<(Vec<u8>, usize, I), Error>;

    fn has_version(&self, version_id: &Key) -> bool;

    fn insert_record_stream(
        &mut self,
        stream: impl Iterator<Item = Box<dyn ContentFactory>>,
    ) -> Result<(), Error>;

    fn get_format_signature(&self) -> String;

    fn get_lines(&self, version_id: &Key) -> Result<Box<dyn Iterator<Item = Vec<u8>>>, Error> {
        let record_stream = self.get_record_stream(&[version_id], Ordering::Unordered, false);
        if let Some(record) = record_stream.into_iter().next() {
            Ok(record.into_lines())
        } else {
            Err(Error::VersionNotPresent(version_id.clone()))
        }
    }

    fn get_text(&self, version_id: &Key) -> Result<Vec<u8>, Error> {
        let record_stream = self.get_record_stream(&[version_id], Ordering::Unordered, false);
        if let Some(record) = record_stream.into_iter().next() {
            Ok(record.into_fulltext())
        } else {
            Err(Error::VersionNotPresent(version_id.clone()))
        }
    }

    fn get_chunks(&self, version_id: &Key) -> Result<Box<dyn Iterator<Item = Vec<u8>>>, Error> {
        let record_stream = self.get_record_stream(&[version_id], Ordering::Unordered, false);
        if let Some(record) = record_stream.into_iter().next() {
            Ok(record.into_chunks())
        } else {
            Err(Error::VersionNotPresent(version_id.clone()))
        }
    }
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
