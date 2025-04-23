use crate::groupcompress::block::{read_item, GroupCompressItem};
use crate::groupcompress::delta::{apply_delta, write_base128_int};
use crate::groupcompress::NULL_SHA1;
use crate::versionedfile::{Error, Key};
use std::borrow::Cow;
use std::collections::HashMap;

pub trait GroupCompressor {
    /// Compress lines with label key.
    ///
    /// # Arguments
    /// * `key`: A key tuple. It is stored in the output
    ///     for identification of the text during decompression. If the last
    ///     element is b'None' it is replaced with the sha1 of the text -
    ///     e.g. sha1:xxxxxxx.
    /// * `chunks`: Chunks of bytes to be compressed
    /// * `length`: Length of chunks
    /// * `expected_sha`: If non-None, the sha the lines are believed to
    ///     have. During compression the sha is calculated; a mismatch will
    ///     cause an error.
    /// * `nostore_sha`: If the computed sha1 sum matches, we will raise
    ///     ExistingContent rather than adding the text.
    /// * `soft`: Do a 'soft' compression. This means that we require larger
    ///     ranges to match to be considered for a copy command.
    ///
    /// # Returns
    /// The sha1 of lines, the start and end offsets in the delta, and the type ('fulltext' or
    /// 'delta').
    fn compress(
        &mut self,
        key: &Key,
        chunks: &[&[u8]],
        length: usize,
        expected_sha: Option<String>,
        nostore_sha: Option<String>,
        soft: Option<bool>,
    ) -> Result<(String, usize, usize, &'static str), Error> {
        if length == 0 {
            // empty, like a dir entry, etc
            if nostore_sha == Some(String::from_utf8_lossy(NULL_SHA1.as_slice()).to_string()) {
                return Err(Error::ExistingContent(key.clone()));
            }
            return Ok((
                String::from_utf8_lossy(NULL_SHA1.as_slice()).to_string(),
                0,
                0,
                "fulltext",
            ));
        }
        // we assume someone knew what they were doing when they passed it in
        let sha = expected_sha.unwrap_or_else(|| breezy_osutils::sha::sha_chunks(chunks));
        if let Some(nostore_sha) = nostore_sha {
            if sha == nostore_sha {
                return Err(Error::ExistingContent(key.clone()));
            }
        }

        let key = match key {
            Key::Fixed(key) => key.clone(),
            Key::ContentAddressed(key) => {
                let mut key = key.clone();
                key.push(format!("sha1:{}", sha).as_bytes().to_vec());
                key
            }
        };

        let (start, end, r#type) =
            self.compress_block(&key, chunks, length, (length / 2) as u128, soft)?;
        Ok((sha, start, end, r#type))
    }

    /// Compress chunks with label key.
    ///
    /// :param key: A key tuple. It is stored in the output for identification
    ///     of the text during decompression.
    ///
    /// :param chunks: The chunks of bytes to be compressed
    ///
    /// :param input_len: The length of the chunks
    ///
    /// :param max_delta_size: The size above which we issue a fulltext instead
    ///     of a delta.
    ///
    /// :param soft: Do a 'soft' compression. This means that we require larger
    ///     ranges to match to be considered for a copy command.
    ///
    /// # Returns
    /// The sha1 of lines, the start and end offsets in the delta, and
    ///     the type ('fulltext' or 'delta').
    fn compress_block(
        &mut self,
        key: &[Vec<u8>],
        chunks: &[&[u8]],
        input_len: usize,
        max_delta_size: u128,
        soft: Option<bool>,
    ) -> Result<(usize, usize, &'static str), Error>;

    /// Return the overall compression ratio.
    fn ratio(&self) -> f32;

    /// Finish this group, creating a formatted stream.
    ///
    /// After calling this, the compressor should no longer be used
    fn flush(self) -> (Vec<Vec<u8>>, usize);

    /// Call this if you want to 'revoke' the last compression.
    ///
    /// After this, the data structures will be rolled back, but you cannot do more compression.
    fn flush_without_last(self) -> (Vec<Vec<u8>>, usize);
}

pub struct TraditionalGroupCompressor {
    delta_index: crate::groupcompress::line_delta::LinesDeltaIndex,
    endpoint: usize,
    input_bytes: usize,
    last: Option<(usize, usize)>,
    labels_deltas: HashMap<Vec<Vec<u8>>, (usize, usize, usize, usize)>,
}

impl GroupCompressor for TraditionalGroupCompressor {
    fn ratio(&self) -> f32 {
        self.input_bytes as f32 / self.endpoint as f32
    }

    fn flush(self) -> (Vec<Vec<u8>>, usize) {
        (self.delta_index.lines().to_vec(), self.endpoint)
    }

    fn flush_without_last(self) -> (Vec<Vec<u8>>, usize) {
        let last = self.last.unwrap();
        (self.delta_index.lines()[..last.0].to_vec(), last.1)
    }

    fn compress_block(
        &mut self,
        key: &[Vec<u8>],
        chunks: &[&[u8]],
        input_len: usize,
        max_delta_size: u128,
        soft: Option<bool>,
    ) -> Result<(usize, usize, &'static str), Error> {
        let new_lines =
            breezy_osutils::chunks_to_lines(chunks.iter().map(|x| Ok::<_, std::io::Error>(*x)))
                .collect::<Result<Vec<_>, _>>()
                .unwrap();
        let (mut out_lines, mut index_lines) =
            self.delta_index
                .make_delta(new_lines.as_slice(), input_len, soft);
        let delta_length = out_lines.iter().map(|l| l.len() as u128).sum();
        let (r#type, out_lines) = if delta_length > max_delta_size {
            // The delta is longer than the fulltext, insert a fulltext
            let mut out_lines = vec![
                Cow::Borrowed(&b"f"[..]),
                {
                    let mut data = Vec::new();
                    write_base128_int(&mut data, input_len as u128).unwrap();
                    Cow::Owned(data)
                },
            ];
            index_lines.clear();
            index_lines.extend(vec![false, false]);
            index_lines.extend([true].repeat(new_lines.len()));
            out_lines.extend(new_lines);
            ("fulltext", out_lines)
        } else {
            // this is a worthy delta, output it
            out_lines[0] = Cow::Borrowed(&b"d"[..]);
            // Update the delta_length to include those two encoded integers
            {
                let mut data = Vec::new();
                write_base128_int(&mut data, delta_length).unwrap();
                out_lines[1] = Cow::Owned(data);
            }
            ("delta", out_lines)
        };
        // Before insertion
        let start = self.endpoint;
        let chunk_start = self.delta_index.lines().len();
        self.last = Some((chunk_start, self.endpoint));
        self.delta_index.extend_lines(
            out_lines
                .into_iter()
                .map(|x| x.into_owned())
                .collect::<Vec<_>>()
                .as_slice(),
            &index_lines,
        );
        self.endpoint = self.delta_index.endpoint();
        self.input_bytes += input_len;
        let chunk_end = self.delta_index.lines().len();
        self.labels_deltas
            .insert(key.to_vec(), (start, chunk_start, self.endpoint, chunk_end));
        Ok((start, self.endpoint, r#type))
    }
}

impl Default for TraditionalGroupCompressor {
    fn default() -> Self {
        Self::new()
    }
}

impl TraditionalGroupCompressor {
    pub fn new() -> Self {
        Self {
            delta_index: crate::groupcompress::line_delta::LinesDeltaIndex::new(vec![]),
            endpoint: 0,
            input_bytes: 0,
            last: None,
            labels_deltas: HashMap::new(),
        }
    }

    pub fn chunks(&self) -> &[Vec<u8>] {
        self.delta_index.lines()
    }

    pub fn endpoint(&self) -> usize {
        self.endpoint
    }

    /// Extract a key previously added to the compressor.
    ///
    /// # Arguments
    /// * `key`: The key to extract.
    ///
    /// # Returns
    /// An iterable over chunks and the sha1.
    pub fn extract(&self, key: &Vec<Vec<u8>>) -> Result<(Vec<Vec<u8>>, String), String> {
        let (_start_byte, start_chunk, _end_byte, end_chunk) = self.labels_deltas.get(key).unwrap();
        let delta_chunks = &self.delta_index.lines()[*start_chunk..*end_chunk];
        let stored_bytes = delta_chunks.concat();
        let data = match read_item(&mut stored_bytes.as_slice()).map_err(|e| e.to_string())? {
            GroupCompressItem::Fulltext(data) => vec![data],
            GroupCompressItem::Delta(data) => {
                let source = self.delta_index.lines()[..*start_chunk].concat();
                vec![apply_delta(source.as_slice(), data.as_slice())?]
            }
        };
        let data_sha1 = breezy_osutils::sha::sha_chunks(data.as_slice());
        Ok((data, data_sha1))
    }
}
