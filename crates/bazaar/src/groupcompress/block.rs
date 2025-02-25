use crate::groupcompress::delta::{apply_delta, read_base128_int, read_instruction, Instruction};
use byteorder::ReadBytesExt;
use std::borrow::Cow;
use std::io::BufRead;
use std::io::{Read, Write};

/// Group Compress Block v1 Zlib
const GCB_HEADER: &[u8] = b"gcb1z\n";

/// Group Compress Block v1 Lzma
const GCB_LZ_HEADER: &[u8] = b"gcb1l\n";

#[derive(PartialEq, Eq, Default, Clone, Copy)]
pub enum CompressorKind {
    #[default]
    Zlib,
    Lzma,
}

#[cfg(feature = "pyo3")]
impl pyo3::FromPyObject<'_> for CompressorKind {
    fn extract(ob: &pyo3::PyAny) -> pyo3::PyResult<Self> {
        let s: Cow<str> = ob.extract()?;
        match s.as_ref() {
            "zlib" => Ok(CompressorKind::Zlib),
            "lzma" => Ok(CompressorKind::Lzma),
            _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Unknown compressor: {}",
                s
            ))),
        }
    }
}

impl CompressorKind {
    fn header(&self) -> &'static [u8] {
        match self {
            CompressorKind::Zlib => GCB_HEADER,
            CompressorKind::Lzma => GCB_LZ_HEADER,
        }
    }

    fn from_header(header: &[u8]) -> Option<Self> {
        if header == GCB_HEADER {
            Some(CompressorKind::Zlib)
        } else if header == GCB_LZ_HEADER {
            Some(CompressorKind::Lzma)
        } else {
            None
        }
    }
}

#[derive(Debug)]
pub enum Error {
    InvalidData(String),
    Io(std::io::Error),
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match *self {
            Error::InvalidData(ref s) => write!(f, "Invalid data: {}", s),
            Error::Io(ref e) => write!(f, "IO error: {}", e),
        }
    }
}

impl std::error::Error for Error {}

pub enum GroupCompressItem {
    Fulltext(Vec<u8>),
    Delta(Vec<u8>),
}

pub fn read_item<R: Read>(r: &mut R) -> Result<GroupCompressItem, Error> {
    // The bytes are 'f' or 'd' for the type, then a variable-length
    // base128 integer for the content size, then the actual content
    // We know that the variable-length integer won't be longer than 5
    // bytes (it takes 5 bytes to encode 2^32)
    let c = r.read_u8()?;
    let content_len = read_base128_int(r).map_err(|e| Error::InvalidData(e.to_string()))?;

    let mut text = vec![0; content_len as usize];
    r.read_exact(&mut text)?;
    match c {
        b'f' => {
            // Fulltext
            Ok(GroupCompressItem::Fulltext(text))
        }
        b'd' => {
            // Must be type delta as checked above
            Ok(GroupCompressItem::Delta(text))
        }
        c => Err(Error::InvalidData(format!(
            "Unknown content control code: {:?}",
            c
        ))),
    }
}

/// An object which maintains the internal structure of the compressed data.
///
/// This tracks the meta info (start of text, length, type, etc.)
pub struct GroupCompressBlock {
    /// The name of the compressor used to compress the content
    compressor: Option<CompressorKind>,
    /// The compressed content
    z_content_chunks: Option<Vec<Vec<u8>>>,
    /// The decompressor object
    z_content_decompressor: Option<Box<dyn std::io::Read>>,
    /// The length of the compressed content
    z_content_length: Option<usize>,
    /// The length of the uncompressed content
    content_length: Option<usize>,
    /// The uncompressed content
    content: Option<Vec<u8>>,
    /// The uncompressed content, split into chunks
    content_chunks: Option<Vec<Vec<u8>>>,
}

impl Default for GroupCompressBlock {
    fn default() -> Self {
        Self::new()
    }
}

fn read_header<R: Read>(r: &mut R) -> Result<CompressorKind, Error> {
    let mut header = [0; 6];
    r.read_exact(&mut header).map_err(|e| {
        Error::InvalidData(format!(
            "Failed to read header from GroupCompressBlock: {}",
            e
        ))
    })?;
    CompressorKind::from_header(&header).ok_or_else(|| {
        Error::InvalidData(format!(
            "Invalid header in GroupCompressBlock: {:?}",
            header
        ))
    })
}

impl GroupCompressBlock {
    pub fn new() -> Self {
        // map by key? or just order in file?
        Self {
            compressor: None,
            z_content_chunks: None,
            z_content_decompressor: None,
            z_content_length: None,
            content_length: None,
            content: None,
            content_chunks: None,
        }
    }

    pub fn content(&self) -> Option<&[u8]> {
        self.content.as_deref()
    }

    pub fn content_length(&self) -> Option<usize> {
        self.content_length
    }

    /// Make sure that content has been expanded enough.
    ///
    /// # Arguments
    /// * `num_bytes` - Ensure that we have extracted at least num_bytes of content. If None, consume everything
    pub fn ensure_content(&mut self, num_bytes: Option<usize>) {
        assert!(
            self.content_length.is_some(),
            "self.content_length should never be None"
        );
        let mut num_bytes = match num_bytes {
            None => self.content_length.unwrap(),
            Some(num_bytes) => {
                assert!(
                    num_bytes <= self.content_length.unwrap(),
                    "requested num_bytes ({}) > content length ({})",
                    num_bytes,
                    self.content_length.unwrap()
                );
                num_bytes
            }
        };

        // Expand the content if required
        if self.content.is_none() {
            if let Some(content_chunks) = self.content_chunks.as_ref() {
                self.content = Some(content_chunks.concat());
                self.content_chunks = None;
            }
        }
        if self.content.is_none() {
            // We join self.z_content_chunks here, because if we are
            // decompressing, then it is *very* likely that we have a single
            // chunk
            if self.z_content_length == Some(0) {
                self.content = Some(b"".to_vec());
            } else {
                let c = breezy_osutils::chunkreader::ChunksReader::new(Box::new(
                    self.z_content_chunks.clone().unwrap().into_iter(),
                ));
                self.z_content_decompressor = Some(match self.compressor.unwrap() {
                    CompressorKind::Lzma => {
                        Box::new(xz2::read::XzDecoder::new(c)) as Box<dyn std::io::Read>
                    }
                    CompressorKind::Zlib => {
                        Box::new(flate2::read::ZlibDecoder::new(c)) as Box<dyn std::io::Read>
                    }
                });
                self.content = Some(Vec::new());
            }
        }

        if self.content.as_ref().unwrap().len() >= num_bytes {
            return;
        }

        num_bytes -= self.content.as_ref().unwrap().len();

        let mut buf = vec![0; num_bytes];
        self.z_content_decompressor
            .as_mut()
            .unwrap()
            .read_exact(&mut buf)
            .unwrap();
        self.content.as_mut().unwrap().extend(buf);
    }

    #[allow(clippy::len_without_is_empty)]
    pub fn len(&self) -> usize {
        // This is the maximum number of bytes this object will reference if
        // everything is decompressed. However, if we decompress less than
        // everything... (this would cause some problems for LRUSizeCache)
        self.content_length.unwrap() + self.z_content_length.unwrap()
    }

    pub fn parse_bytes(&mut self, mut data: &[u8]) -> Result<(), Error> {
        self.read_bytes(&mut data)
    }

    /// Read the various lengths from the header.
    ///
    /// This also populates the various 'compressed' buffers.
    fn read_bytes<R: Read>(&mut self, r: &mut R) -> Result<(), Error> {
        // At present, we have 2 integers for the compressed and uncompressed
        // content. In base10 (ascii) 14 bytes can represent > 1TB, so to avoid
        // checking too far, cap the search to 14 bytes.
        let mut buf = std::io::BufReader::new(r);
        let mut z_content_length_buf = Vec::new();
        buf.read_until(b'\n', &mut z_content_length_buf)?;
        // Chop off the '\n'
        z_content_length_buf.pop();
        self.z_content_length = Some(
            String::from_utf8(z_content_length_buf)
                .unwrap()
                .parse()
                .unwrap(),
        );
        let mut content_length_buf = Vec::new();
        buf.read_until(b'\n', &mut content_length_buf)?;
        content_length_buf.pop();
        self.content_length = Some(
            String::from_utf8(content_length_buf)
                .unwrap()
                .parse()
                .unwrap(),
        );
        let mut data = Vec::new();
        buf.read_to_end(&mut data)?;
        // XXX: Define some GCCorrupt error ?
        assert_eq!(
            data.len(),
            self.z_content_length.unwrap(),
            "Invalid bytes: ({}) != {}",
            data.len(),
            self.z_content_length.unwrap()
        );
        self.z_content_chunks = Some(vec![data.to_vec()]);
        Ok(())
    }

    /// Return z_content_chunks as a simple string.
    ///
    /// Meant only to be used by the test suite.
    pub fn z_content(&mut self) -> Vec<u8> {
        self.z_content_chunks.as_ref().unwrap().concat()
    }

    pub fn z_content_chunks(&mut self) -> &mut Vec<Vec<u8>> {
        self.z_content_chunks.as_mut().unwrap()
    }

    pub fn from_bytes<R: Read>(mut r: R) -> Result<Self, Error> {
        let compressor = read_header(&mut r)?;
        let mut out = Self {
            compressor: Some(compressor),
            z_content_chunks: None,
            content: None,
            content_chunks: None,
            z_content_length: None,
            content_length: None,
            z_content_decompressor: None,
        };
        out.read_bytes(&mut r)?;
        Ok(out)
    }

    /// Extract the text for a specific key.
    ///
    /// # Arguments
    /// * `key` - The label used for this content
    /// * `sha1` - TODO (should we validate only when sha1 is supplied?)
    ///
    /// # Returns
    /// The bytes for the content
    pub fn extract(&mut self, start: usize, end: usize) -> Result<Vec<Vec<u8>>, Error> {
        if start == 0 && end == 0 {
            return Ok(vec![]);
        }
        self.ensure_content(Some(end));

        let mut content = self.content.as_ref().unwrap().as_slice();

        match read_item(&mut content)? {
            GroupCompressItem::Fulltext(data) => Ok(vec![data]),
            GroupCompressItem::Delta(text) => Ok(vec![apply_delta(
                self.content.as_ref().unwrap(),
                text.as_slice(),
            )
            .unwrap()]),
        }
    }

    /// Set the content of this block to the given chunks.
    pub fn set_chunked_content(&mut self, content_chunks: &[Vec<u8>], length: usize) {
        // If we have lots of short lines, it is may be more efficient to join
        // the content ahead of time. If the content is <10MiB, we don't really
        // care about the extra memory consumption, so we can just pack it and
        // be done. However, timing showed 18s => 17.9s for repacking 1k revs of
        // mysql, which is below the noise margin
        self.content_length = Some(length);
        self.content_chunks = Some(content_chunks.to_vec());
        self.content = None;
        self.z_content_chunks = None;
    }

    /// Set the content of this block.
    pub fn set_content(&mut self, content: &[u8]) {
        self.content_length = Some(content.len());
        self.content = Some(content.to_vec());
        self.z_content_chunks = None;
    }

    fn create_z_content_from_chunks(
        &mut self,
        chunks: Vec<Vec<u8>>,
        compressor_kind: CompressorKind,
    ) {
        let chunks = match compressor_kind {
            CompressorKind::Zlib => {
                let mut encoder =
                    flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
                for chunk in chunks {
                    encoder.write_all(&chunk).unwrap();
                }
                encoder.finish().unwrap()
            }
            CompressorKind::Lzma => {
                let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 6);
                for chunk in chunks {
                    encoder.write_all(&chunk).unwrap();
                }
                encoder.finish().unwrap()
            }
        };
        self.z_content_length = Some(chunks.len());
        self.z_content_chunks = Some(vec![chunks]);
    }

    fn create_z_content(&mut self, compressor_kind: CompressorKind) {
        if self.z_content_chunks.is_some() && self.compressor == Some(compressor_kind) {
            return;
        }
        let chunks = if let Some(content_chunks) = self.content_chunks.as_ref() {
            content_chunks.to_vec()
        } else {
            vec![self.content.as_ref().unwrap().clone()]
        };
        self.create_z_content_from_chunks(chunks, compressor_kind);
    }

    /// Create the byte stream as a series of 'chunks'.
    pub fn to_chunks(
        &mut self,
        compressor_kind: Option<CompressorKind>,
    ) -> (usize, Vec<Cow<'_, [u8]>>) {
        let compressor_kind = compressor_kind.unwrap_or_default();
        self.create_z_content(compressor_kind);

        let lengths = format!(
            "{}\n{}\n",
            self.z_content_length.unwrap(),
            self.content_length.unwrap()
        );

        let mut chunks = vec![
            Cow::Borrowed(compressor_kind.header()),
            Cow::Owned(lengths.as_bytes().to_vec()),
        ];
        chunks.extend(
            self.z_content_chunks
                .as_ref()
                .unwrap()
                .iter()
                .map(|x| Cow::Borrowed(x.as_slice())),
        );
        let total_len = chunks.iter().map(|x| x.len()).sum();
        (total_len, chunks)
    }

    /// Encode the information into a byte stream.
    pub fn to_bytes(&mut self) -> Vec<u8> {
        let (_total_len, chunks) = self.to_chunks(None);
        chunks.concat()
    }

    /// Take this block, and spit out a human-readable structure.
    ///
    /// # Arguments
    /// * `include_text`: Inserts also include text bits, chose whether you want this displayed in
    /// the dump or not.
    ///
    /// # Returns
    /// A dump of the given block. The layout is something like: [('f', length), ('d',
    /// delta_length, text_length, [delta_info])]
    /// delta_info := [('i', num_bytes, text), ('c', offset, num_bytes), ...]
    pub fn dump(&mut self, include_text: Option<bool>) -> Result<Vec<DumpInfo>, Error> {
        let include_text = include_text.unwrap_or(false);
        self.ensure_content(None);
        let mut result = vec![];
        let mut content = self.content.as_ref().unwrap().as_slice();
        while !content.is_empty() {
            match read_item(&mut content)? {
                GroupCompressItem::Fulltext(text) => {
                    // Fulltext
                    if include_text {
                        result.push(DumpInfo::Fulltext(Some(text)));
                    } else {
                        result.push(DumpInfo::Fulltext(None));
                    }
                }
                GroupCompressItem::Delta(delta_content) => {
                    let mut delta_info = vec![];
                    // The first entry in a delta is the decompressed length
                    let mut delta_slice = delta_content.as_slice();
                    let decomp_len = read_base128_int(&mut delta_slice).unwrap();
                    let mut measured_len = 0;
                    while !delta_slice.is_empty() {
                        match read_instruction(&mut delta_slice)? {
                            Instruction::Insert(text) => {
                                measured_len += text.len();
                                delta_info.push(DeltaInfo::Insert(
                                    text.len(),
                                    if include_text { Some(text) } else { None },
                                ));
                            }
                            Instruction::r#Copy { offset, length } => {
                                delta_info.push(DeltaInfo::Copy(
                                    offset,
                                    length,
                                    if include_text {
                                        Some(
                                            self.content.as_ref().unwrap()[offset..offset + length]
                                                .to_vec(),
                                        )
                                    } else {
                                        None
                                    },
                                ));
                                measured_len += length;
                            }
                        }
                    }
                    if measured_len != decomp_len as usize {
                        return Err(Error::InvalidData(format!(
                            "Delta claimed fulltext was {} bytes, but extraction resulted in {}",
                            decomp_len, measured_len
                        )));
                    }
                    result.push(DumpInfo::Delta(decomp_len as usize, delta_info));
                }
            }
        }

        Ok(result)
    }
}

pub enum DeltaInfo {
    Insert(usize, Option<Vec<u8>>),
    Copy(usize, usize, Option<Vec<u8>>),
}

pub enum DumpInfo {
    Fulltext(Option<Vec<u8>>),
    Delta(usize, Vec<DeltaInfo>),
}
