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
}
