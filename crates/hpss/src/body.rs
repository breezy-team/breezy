//! Streaming decoders and encoders for smart protocol body data.
//!
//! Ports `LengthPrefixedBodyDecoder` and `ChunkedBodyDecoder` (and the
//! `_send_chunks`/`_send_stream` helpers) from `breezy/bzr/smart/protocol.py`.
//! These are pure byte-level state machines with no I/O.

use crate::protocol::ProtocolError;

/// Parse a chunk length the way Python's `int(s, 16)` does: ASCII hex digits
/// with an optional `0x`/`0X` prefix (the senders emit `hex(n)`).
fn parse_hex_len(prefix: &[u8]) -> Option<i64> {
    let s = std::str::from_utf8(prefix).ok()?.trim();
    let s = s
        .strip_prefix("0x")
        .or_else(|| s.strip_prefix("0X"))
        .unwrap_or(s);
    i64::from_str_radix(s, 16).ok()
}

/// Decoder for length-prefixed bulk data (smart protocol v1 and v2).
///
/// Format: decimal length + `\n`, then that many body bytes, then `done\n`.
/// Anything after the trailer is exposed as `unused_data`.
#[derive(Debug)]
pub struct LengthPrefixedBodyDecoder {
    state: LengthState,
    finished_reading: bool,
    unused_data: Vec<u8>,
    in_buffer: Vec<u8>,
    bytes_left: Option<i64>,
    body: Vec<u8>,
    trailer_buffer: Vec<u8>,
    /// True once a length prefix has been parsed; until then `read_pending_data`
    /// yields nothing (mirrors the Python `state_read` switch).
    reading_body: bool,
}

#[derive(Debug, PartialEq, Eq)]
enum LengthState {
    ExpectingLength,
    ReadingBody,
    ReadingTrailer,
    ReadingUnused,
}

impl Default for LengthPrefixedBodyDecoder {
    fn default() -> Self {
        Self::new()
    }
}

impl LengthPrefixedBodyDecoder {
    pub fn new() -> Self {
        LengthPrefixedBodyDecoder {
            state: LengthState::ExpectingLength,
            finished_reading: false,
            unused_data: Vec::new(),
            in_buffer: Vec::new(),
            bytes_left: None,
            body: Vec::new(),
            trailer_buffer: Vec::new(),
            reading_body: false,
        }
    }

    pub fn finished_reading(&self) -> bool {
        self.finished_reading
    }

    pub fn unused_data(&self) -> &[u8] {
        &self.unused_data
    }

    /// Suggested number of bytes to read next, mirroring `next_read_size`.
    pub fn next_read_size(&self) -> usize {
        if let Some(left) = self.bytes_left {
            // Body remainder plus the trailer ("done\n").
            (left + 5).max(0) as usize
        } else {
            match self.state {
                LengthState::ReadingTrailer => 5usize.saturating_sub(self.trailer_buffer.len()),
                LengthState::ExpectingLength => 6,
                _ => 1,
            }
        }
    }

    /// Return and clear any decoded body bytes ready for consumption.
    pub fn read_pending_data(&mut self) -> Vec<u8> {
        if self.reading_body {
            std::mem::take(&mut self.body)
        } else {
            Vec::new()
        }
    }

    pub fn accept_bytes(&mut self, new_buf: &[u8]) -> Result<(), ProtocolError> {
        self.in_buffer.extend_from_slice(new_buf);
        loop {
            let prev = std::mem::discriminant(&self.state);
            self.step()?;
            if std::mem::discriminant(&self.state) == prev {
                break;
            }
        }
        Ok(())
    }

    fn step(&mut self) -> Result<(), ProtocolError> {
        match self.state {
            LengthState::ExpectingLength => {
                if let Some(pos) = self.in_buffer.iter().position(|&b| b == b'\n') {
                    let digits = &self.in_buffer[..pos];
                    let n: i64 = std::str::from_utf8(digits)
                        .ok()
                        .and_then(|s| s.parse().ok())
                        .ok_or_else(|| ProtocolError::BadChunkLength(digits.to_vec()))?;
                    self.bytes_left = Some(n);
                    self.in_buffer.drain(..=pos);
                    self.reading_body = true;
                    self.state = LengthState::ReadingBody;
                }
            }
            LengthState::ReadingBody => {
                let in_buf = std::mem::take(&mut self.in_buffer);
                let len = in_buf.len() as i64;
                self.body.extend_from_slice(&in_buf);
                let left = self.bytes_left.unwrap() - len;
                self.bytes_left = Some(left);
                if left <= 0 {
                    if left != 0 {
                        // body is `left` bytes too long; split the excess into the trailer.
                        let split = (self.body.len() as i64 + left) as usize;
                        self.trailer_buffer = self.body[split..].to_vec();
                        self.body.truncate(split);
                    }
                    self.bytes_left = None;
                    self.state = LengthState::ReadingTrailer;
                }
            }
            LengthState::ReadingTrailer => {
                self.trailer_buffer
                    .append(&mut std::mem::take(&mut self.in_buffer));
                if self.trailer_buffer.starts_with(b"done\n") {
                    self.unused_data = self.trailer_buffer[b"done\n".len()..].to_vec();
                    self.state = LengthState::ReadingUnused;
                    self.finished_reading = true;
                }
            }
            LengthState::ReadingUnused => {
                self.unused_data
                    .append(&mut std::mem::take(&mut self.in_buffer));
            }
        }
        Ok(())
    }
}

/// A chunk produced by [`ChunkedBodyDecoder`].
#[derive(Debug, PartialEq, Eq)]
pub enum Chunk {
    /// A normal data chunk.
    Data(Vec<u8>),
    /// An error response: the collected error argument chunks.
    Error(Vec<Vec<u8>>),
}

/// Decoder for HTTP-style chunked transfer encoding (smart protocol v2+).
///
/// Format: `chunked\n` header, then chunks each as a hex length + `\n` + data,
/// terminated by `END\n`. An `ERR\n` marker switches following chunks into a
/// single error response.
#[derive(Debug)]
pub struct ChunkedBodyDecoder {
    state: ChunkState,
    finished_reading: bool,
    unused_data: Vec<u8>,
    in_buffer: Vec<u8>,
    bytes_left: Option<i64>,
    chunk_in_progress: Vec<u8>,
    chunks: std::collections::VecDeque<Chunk>,
    error: bool,
    error_in_progress: Vec<Vec<u8>>,
}

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
enum ChunkState {
    ExpectingHeader,
    ExpectingLength,
    ReadingChunk,
    ReadingUnused,
}

impl Default for ChunkedBodyDecoder {
    fn default() -> Self {
        Self::new()
    }
}

impl ChunkedBodyDecoder {
    pub fn new() -> Self {
        ChunkedBodyDecoder {
            state: ChunkState::ExpectingHeader,
            finished_reading: false,
            unused_data: Vec::new(),
            in_buffer: Vec::new(),
            bytes_left: None,
            chunk_in_progress: Vec::new(),
            chunks: std::collections::VecDeque::new(),
            error: false,
            error_in_progress: Vec::new(),
        }
    }

    pub fn finished_reading(&self) -> bool {
        self.finished_reading
    }

    pub fn unused_data(&self) -> &[u8] {
        &self.unused_data
    }

    /// Pop the next completed chunk, or `None` if none is ready.
    pub fn read_next_chunk(&mut self) -> Option<Chunk> {
        self.chunks.pop_front()
    }

    /// Suggested number of bytes to read next, mirroring `next_read_size`.
    pub fn next_read_size(&self) -> usize {
        match self.state {
            ChunkState::ReadingChunk => (self.bytes_left.unwrap_or(0) + 4).max(0) as usize,
            ChunkState::ExpectingLength => {
                if self.in_buffer.is_empty() {
                    2
                } else {
                    1
                }
            }
            ChunkState::ReadingUnused => 1,
            ChunkState::ExpectingHeader => "chunked\n".len().saturating_sub(self.in_buffer.len()),
        }
    }

    pub fn accept_bytes(&mut self, new_buf: &[u8]) -> Result<(), ProtocolError> {
        self.in_buffer.extend_from_slice(new_buf);
        loop {
            let prev = self.state;
            self.step()?;
            if self.state == prev {
                break;
            }
        }
        Ok(())
    }

    /// Extract a line up to (not including) the next `\n`, consuming the `\n`.
    fn extract_line(&mut self) -> Option<Vec<u8>> {
        let pos = self.in_buffer.iter().position(|&b| b == b'\n')?;
        let line = self.in_buffer[..pos].to_vec();
        self.in_buffer.drain(..=pos);
        Some(line)
    }

    fn step(&mut self) -> Result<(), ProtocolError> {
        match self.state {
            ChunkState::ExpectingHeader => {
                if let Some(prefix) = self.extract_line() {
                    if prefix == b"chunked" {
                        self.state = ChunkState::ExpectingLength;
                    } else {
                        return Err(ProtocolError::BadChunkedHeader(prefix));
                    }
                }
            }
            ChunkState::ExpectingLength => {
                // Loop here because a single accept_bytes may contain ERR then
                // the next length, and Python recurses within one state call.
                while self.state == ChunkState::ExpectingLength {
                    let Some(prefix) = self.extract_line() else {
                        break;
                    };
                    if prefix == b"ERR" {
                        self.error = true;
                        self.error_in_progress = Vec::new();
                        continue;
                    } else if prefix == b"END" {
                        self.finish();
                        break;
                    } else {
                        let s = parse_hex_len(&prefix)
                            .ok_or_else(|| ProtocolError::BadChunkLength(prefix.clone()))?;
                        self.bytes_left = Some(s);
                        self.chunk_in_progress = Vec::new();
                        self.state = ChunkState::ReadingChunk;
                    }
                }
            }
            ChunkState::ReadingChunk => {
                let in_buffer_len = self.in_buffer.len() as i64;
                let take = (self.bytes_left.unwrap()).min(in_buffer_len).max(0) as usize;
                let rest = self.in_buffer.split_off(take);
                self.chunk_in_progress.extend_from_slice(&self.in_buffer);
                self.in_buffer = rest;
                self.bytes_left = Some(self.bytes_left.unwrap() - in_buffer_len);
                if self.bytes_left.unwrap() <= 0 {
                    self.bytes_left = None;
                    let chunk = std::mem::take(&mut self.chunk_in_progress);
                    if self.error {
                        self.error_in_progress.push(chunk);
                    } else {
                        self.chunks.push_back(Chunk::Data(chunk));
                    }
                    self.state = ChunkState::ExpectingLength;
                }
            }
            ChunkState::ReadingUnused => {
                self.unused_data
                    .append(&mut std::mem::take(&mut self.in_buffer));
            }
        }
        Ok(())
    }

    fn finish(&mut self) {
        self.unused_data = std::mem::take(&mut self.in_buffer);
        self.state = ChunkState::ReadingUnused;
        if self.error {
            let args = std::mem::take(&mut self.error_in_progress);
            self.chunks.push_back(Chunk::Error(args));
        }
        self.finished_reading = true;
    }
}

/// Encode a sequence of chunks with hex length prefixes (`_send_chunks`).
///
/// A `Chunk::Error` emits `ERR\n` followed by its argument chunks and stops,
/// matching the Python early return.
pub fn encode_chunks<I>(stream: I) -> Vec<u8>
where
    I: IntoIterator<Item = Chunk>,
{
    let mut out = Vec::new();
    encode_chunks_into(&mut out, stream);
    out
}

fn encode_chunks_into<I>(out: &mut Vec<u8>, stream: I)
where
    I: IntoIterator<Item = Chunk>,
{
    for chunk in stream {
        match chunk {
            Chunk::Data(data) => {
                out.extend_from_slice(format!("{:x}\n", data.len()).as_bytes());
                out.extend_from_slice(&data);
            }
            Chunk::Error(args) => {
                out.extend_from_slice(b"ERR\n");
                encode_chunks_into(out, args.into_iter().map(Chunk::Data));
                return;
            }
        }
    }
}

/// Wrap a chunk stream with the `chunked\n` header and `END\n` trailer
/// (`_send_stream`).
pub fn encode_stream<I>(stream: I) -> Vec<u8>
where
    I: IntoIterator<Item = Chunk>,
{
    let mut out = Vec::from(&b"chunked\n"[..]);
    encode_chunks_into(&mut out, stream);
    out.extend_from_slice(b"END\n");
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decode_length(input: &[u8]) -> (Vec<u8>, Vec<u8>, bool) {
        let mut d = LengthPrefixedBodyDecoder::new();
        d.accept_bytes(input).unwrap();
        let body = d.read_pending_data();
        (body, d.unused_data().to_vec(), d.finished_reading())
    }

    #[test]
    fn length_construct() {
        let d = LengthPrefixedBodyDecoder::new();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 6);
        assert_eq!(d.unused_data(), b"");
    }

    #[test]
    fn length_incremental() {
        // Mirrors test_accept_bytes in test_smart_transport.py.
        let mut d = LengthPrefixedBodyDecoder::new();
        d.accept_bytes(b"").unwrap();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 6);
        assert_eq!(d.read_pending_data(), b"");

        d.accept_bytes(b"7").unwrap();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 6);
        assert_eq!(d.read_pending_data(), b"");

        d.accept_bytes(b"\na").unwrap();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 11);
        assert_eq!(d.read_pending_data(), b"a");

        d.accept_bytes(b"bcdefgd").unwrap();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 4);
        assert_eq!(d.read_pending_data(), b"bcdefg");

        d.accept_bytes(b"one").unwrap();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 1);
        assert_eq!(d.read_pending_data(), b"");

        d.accept_bytes(b"\nblarg").unwrap();
        assert!(d.finished_reading());
        assert_eq!(d.next_read_size(), 1);
        assert_eq!(d.read_pending_data(), b"");
        assert_eq!(d.unused_data(), b"blarg");
    }

    #[test]
    fn length_all_at_once_with_excess() {
        let (body, unused, finished) = decode_length(b"1\nadone\nunused");
        assert_eq!(body, b"a");
        assert_eq!(unused, b"unused");
        assert!(finished);
    }

    #[test]
    fn length_exact_end_of_body() {
        let mut d = LengthPrefixedBodyDecoder::new();
        d.accept_bytes(b"1\na").unwrap();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 5);
        assert_eq!(d.read_pending_data(), b"a");
        assert_eq!(d.unused_data(), b"");

        d.accept_bytes(b"done\n").unwrap();
        assert!(d.finished_reading());
        assert_eq!(d.next_read_size(), 1);
        assert_eq!(d.read_pending_data(), b"");
        assert_eq!(d.unused_data(), b"");
    }

    #[test]
    fn chunked_construct() {
        let d = ChunkedBodyDecoder::new();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 8);
        assert_eq!(d.unused_data(), b"");
    }

    #[test]
    fn chunked_empty_content() {
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        d.accept_bytes(b"END\n").unwrap();
        assert!(d.finished_reading());
        assert_eq!(d.read_next_chunk(), None);
        assert_eq!(d.unused_data(), b"");
    }

    #[test]
    fn chunked_one_chunk() {
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        d.accept_bytes(b"f\n123456789abcdefEND\n").unwrap();
        assert!(d.finished_reading());
        assert_eq!(
            d.read_next_chunk(),
            Some(Chunk::Data(b"123456789abcdef".to_vec()))
        );
        assert_eq!(d.unused_data(), b"");
    }

    #[test]
    fn chunked_incomplete_chunk_read_size() {
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        d.accept_bytes(b"8\n123").unwrap();
        assert!(!d.finished_reading());
        assert_eq!(d.next_read_size(), 5 + 4);
        assert_eq!(d.read_next_chunk(), None);
    }

    #[test]
    fn chunked_incomplete_length_read_size() {
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        d.accept_bytes(b"9").unwrap();
        assert_eq!(d.next_read_size(), 1);
        d.accept_bytes(b"\n").unwrap();
        assert_eq!(d.next_read_size(), 9 + 4);
        assert!(!d.finished_reading());
    }

    #[test]
    fn chunked_two_chunks() {
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        d.accept_bytes(b"3\naaa5\nbbbbbEND\n").unwrap();
        assert!(d.finished_reading());
        assert_eq!(d.read_next_chunk(), Some(Chunk::Data(b"aaa".to_vec())));
        assert_eq!(d.read_next_chunk(), Some(Chunk::Data(b"bbbbb".to_vec())));
        assert_eq!(d.read_next_chunk(), None);
        assert_eq!(d.unused_data(), b"");
    }

    #[test]
    fn chunked_excess_bytes() {
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        d.accept_bytes(b"5\naaaaaEND\nexcess bytes").unwrap();
        assert!(d.finished_reading());
        assert_eq!(d.read_next_chunk(), Some(Chunk::Data(b"aaaaa".to_vec())));
        assert_eq!(d.unused_data(), b"excess bytes");
        assert_eq!(d.next_read_size(), 1);
    }

    #[test]
    fn chunked_byte_at_a_time() {
        let combined = b"f\n123456789abcdefEND\n";
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        for b in combined {
            d.accept_bytes(&[*b]).unwrap();
        }
        assert!(d.finished_reading());
        assert_eq!(
            d.read_next_chunk(),
            Some(Chunk::Data(b"123456789abcdef".to_vec()))
        );
        assert_eq!(d.unused_data(), b"");
    }

    #[test]
    fn chunked_decode_error() {
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        d.accept_bytes(b"b\nfirst chunkERR\n5\npart15\npart2END\n")
            .unwrap();
        assert!(d.finished_reading());
        assert_eq!(
            d.read_next_chunk(),
            Some(Chunk::Data(b"first chunk".to_vec()))
        );
        assert_eq!(
            d.read_next_chunk(),
            Some(Chunk::Error(vec![b"part1".to_vec(), b"part2".to_vec()]))
        );
    }

    #[test]
    fn chunked_multidigit_length() {
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(b"chunked\n").unwrap();
        let body = vec![b'z'; 0x123];
        // The sender emits hex(n), which includes the "0x" prefix.
        let mut input = b"0x123\n".to_vec();
        input.extend_from_slice(&body);
        input.extend_from_slice(b"END\n");
        d.accept_bytes(&input).unwrap();
        assert!(d.finished_reading());
        assert_eq!(d.read_next_chunk(), Some(Chunk::Data(body)));
    }

    #[test]
    fn encode_stream_roundtrip() {
        let encoded = encode_stream(vec![Chunk::Data(b"hello".to_vec())]);
        assert_eq!(encoded, b"chunked\n5\nhelloEND\n");
        let mut d = ChunkedBodyDecoder::new();
        d.accept_bytes(&encoded).unwrap();
        assert!(d.finished_reading());
        assert_eq!(d.read_next_chunk(), Some(Chunk::Data(b"hello".to_vec())));
    }

    #[test]
    fn encode_chunks_error_stops() {
        let encoded = encode_chunks(vec![
            Chunk::Error(vec![b"oops".to_vec()]),
            Chunk::Data(b"unreached".to_vec()),
        ]);
        assert_eq!(encoded, b"ERR\n4\noops");
    }
}
