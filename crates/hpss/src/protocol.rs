//! Wire-level encoding and decoding helpers for the smart protocol.

/// Error decoding a smart protocol message.
#[derive(Debug, PartialEq, Eq)]
pub enum ProtocolError {
    /// A request line was not newline-terminated.
    NotTerminated(Vec<u8>),
    /// A chunked body had a header other than "chunked".
    BadChunkedHeader(Vec<u8>),
    /// A chunk length prefix was not valid hexadecimal.
    BadChunkLength(Vec<u8>),
    /// A serialised readv offset line was malformed.
    BadOffset(Vec<u8>),
}

/// Decode a byte string into a tuple of fields.
///
/// Fields are joined with `0x01` and the line is terminated with a newline.
/// Returns `None` for an empty or missing line, mirroring the Python
/// `_decode_tuple`.
pub fn decode_tuple(req_line: Option<&[u8]>) -> Result<Option<Vec<Vec<u8>>>, ProtocolError> {
    let line = match req_line {
        None | Some([]) => return Ok(None),
        Some(b) => b,
    };
    if line.last() != Some(&b'\n') {
        return Err(ProtocolError::NotTerminated(line.to_vec()));
    }
    let body = &line[..line.len() - 1];
    Ok(Some(
        body.split(|&b| b == 0x01).map(|s| s.to_vec()).collect(),
    ))
}

/// Encode a sequence of byte fields into a smart-protocol line.
///
/// Fields are joined with `0x01` and the result is newline-terminated.
pub fn encode_tuple<I, T>(args: I) -> Vec<u8>
where
    I: IntoIterator<Item = T>,
    T: AsRef<[u8]>,
{
    let mut out = Vec::new();
    for (i, arg) in args.into_iter().enumerate() {
        if i > 0 {
            out.push(0x01);
        }
        out.extend_from_slice(arg.as_ref());
    }
    out.push(b'\n');
    out
}

/// Encode bulk data as a length-prefixed chunk: decimal length + `\n`, the
/// data, then `done\n`. Mirrors `SmartProtocolBase._encode_bulk_data`.
pub fn encode_bulk_data(body: &[u8]) -> Vec<u8> {
    let mut out = format!("{}\n", body.len()).into_bytes();
    out.extend_from_slice(body);
    out.extend_from_slice(b"done\n");
    out
}

/// Serialise readv `(start, length)` offsets as newline-separated
/// `start,length` lines. Mirrors `SmartProtocolBase._serialise_offsets`.
pub fn serialise_offsets(offsets: &[(u64, u64)]) -> Vec<u8> {
    let lines: Vec<String> = offsets
        .iter()
        .map(|(start, length)| format!("{start},{length}"))
        .collect();
    lines.join("\n").into_bytes()
}

/// Parse readv offsets serialised by [`serialise_offsets`]. Blank lines are
/// skipped. Mirrors `vfs._deserialise_offsets`.
pub fn deserialise_offsets(text: &[u8]) -> Result<Vec<(u64, u64)>, ProtocolError> {
    let mut offsets = Vec::new();
    for line in text.split(|&b| b == b'\n') {
        if line.is_empty() {
            continue;
        }
        let comma = line
            .iter()
            .position(|&b| b == b',')
            .ok_or_else(|| ProtocolError::BadOffset(line.to_vec()))?;
        let start = parse_u64(&line[..comma]).ok_or_else(|| ProtocolError::BadOffset(line.to_vec()))?;
        let length =
            parse_u64(&line[comma + 1..]).ok_or_else(|| ProtocolError::BadOffset(line.to_vec()))?;
        offsets.push((start, length));
    }
    Ok(offsets)
}

fn parse_u64(bytes: &[u8]) -> Option<u64> {
    std::str::from_utf8(bytes).ok()?.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decode_none_and_empty() {
        assert_eq!(decode_tuple(None), Ok(None));
        assert_eq!(decode_tuple(Some(b"")), Ok(None));
    }

    #[test]
    fn decode_single_field() {
        assert_eq!(
            decode_tuple(Some(b"hello\n")),
            Ok(Some(vec![b"hello".to_vec()]))
        );
    }

    #[test]
    fn decode_multiple_fields() {
        assert_eq!(
            decode_tuple(Some(b"a\x01b\x01c\n")),
            Ok(Some(vec![b"a".to_vec(), b"b".to_vec(), b"c".to_vec()]))
        );
    }

    #[test]
    fn decode_unterminated() {
        assert_eq!(
            decode_tuple(Some(b"oops")),
            Err(ProtocolError::NotTerminated(b"oops".to_vec()))
        );
    }

    #[test]
    fn encode_roundtrip() {
        assert_eq!(encode_tuple([b"a".as_ref(), b"b", b"c"]), b"a\x01b\x01c\n");
        assert_eq!(encode_tuple(Vec::<&[u8]>::new()), b"\n");
    }

    #[test]
    fn encode_then_decode() {
        let encoded = encode_tuple([b"foo".as_ref(), b"bar"]);
        assert_eq!(
            decode_tuple(Some(&encoded)),
            Ok(Some(vec![b"foo".to_vec(), b"bar".to_vec()]))
        );
    }

    #[test]
    fn bulk_data() {
        assert_eq!(encode_bulk_data(b"hello"), b"5\nhellodone\n");
        assert_eq!(encode_bulk_data(b""), b"0\ndone\n");
    }

    #[test]
    fn offsets_roundtrip() {
        let offsets = [(1u64, 2u64), (30, 40)];
        let encoded = serialise_offsets(&offsets);
        assert_eq!(encoded, b"1,2\n30,40");
        assert_eq!(deserialise_offsets(&encoded), Ok(offsets.to_vec()));
    }

    #[test]
    fn offsets_empty() {
        assert_eq!(serialise_offsets(&[]), b"");
        assert_eq!(deserialise_offsets(b""), Ok(vec![]));
        // Trailing/blank lines are skipped.
        assert_eq!(deserialise_offsets(b"1,2\n\n"), Ok(vec![(1, 2)]));
    }

    #[test]
    fn offsets_malformed() {
        assert_eq!(
            deserialise_offsets(b"oops"),
            Err(ProtocolError::BadOffset(b"oops".to_vec()))
        );
    }
}
