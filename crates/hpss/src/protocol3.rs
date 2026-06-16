//! Wire framing for smart protocol version 3.
//!
//! Ports the byte-construction half of `_ProtocolThreeEncoder` from
//! `breezy/bzr/smart/protocol.py`. The streaming / write_func orchestration
//! stays in Python; these functions build the bytes for each message part.
//!
//! bencode is provided by the `bendy` crate, which enforces the same canonical
//! form (sorted dict keys, no leading zeros) as fastbencode.

use bendy::encoding::Encoder;
use bendy::value::Value;
use std::borrow::Cow;

/// Maximum bencode nesting depth. `Value` reports a static depth of 0, so the
/// encoder needs an explicit cap; the v3 structures breezy sends are shallow,
/// and this bound is far above anything they reach.
const MAX_DEPTH: usize = 256;

/// Encode a bencode `Value` to bytes in canonical form.
pub fn bencode(value: &Value) -> Vec<u8> {
    let mut encoder = Encoder::new().with_max_depth(MAX_DEPTH);
    // A plain Value tree within MAX_DEPTH is always encodable.
    encoder
        .emit(value)
        .expect("bencode of a Value tree cannot fail");
    encoder.get_output().expect("bencode output is well-formed")
}

/// A list of byte strings, as used for v3 structures.
pub fn bytes_list(items: &[Vec<u8>]) -> Value<'static> {
    Value::List(
        items
            .iter()
            .map(|b| Value::Bytes(Cow::Owned(b.clone())))
            .collect(),
    )
}

/// Prefix `payload` with its length as a big-endian u32 (`struct.pack("!L")`).
fn length_prefixed(payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(4 + payload.len());
    out.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    out.extend_from_slice(payload);
    out
}

/// `_write_prefixed_bencode`: a length-prefixed bencode blob.
pub fn prefixed_bencode(value: &Value) -> Vec<u8> {
    length_prefixed(&bencode(value))
}

/// `_write_headers`: headers are a length-prefixed bencode dict.
///
/// `headers` are (key, value) byte-string pairs; bendy sorts the keys.
pub fn headers(headers: &[(Vec<u8>, Vec<u8>)]) -> Vec<u8> {
    let dict = Value::Dict(
        headers
            .iter()
            .map(|(k, v)| (Cow::Owned(k.clone()), Value::Bytes(Cow::Owned(v.clone()))))
            .collect(),
    );
    prefixed_bencode(&dict)
}

/// `_write_structure`: a `s` marker followed by a length-prefixed bencode list
/// of the (already utf8-encoded) arguments.
pub fn structure(args: &[Vec<u8>]) -> Vec<u8> {
    let mut out = vec![b's'];
    out.extend_from_slice(&prefixed_bencode(&bytes_list(args)));
    out
}

/// `_write_prefixed_body`: a `b` marker followed by length-prefixed raw bytes.
pub fn prefixed_body(body: &[u8]) -> Vec<u8> {
    let mut out = vec![b'b'];
    out.extend_from_slice(&length_prefixed(body));
    out
}

/// `_write_end`: the message terminator.
pub const END: &[u8] = b"e";
/// `_write_chunked_body_start`.
pub const CHUNKED_BODY_START: &[u8] = b"oC";
/// `_write_error_status`.
pub const ERROR_STATUS: &[u8] = b"oE";
/// `_write_success_status`.
pub const SUCCESS_STATUS: &[u8] = b"oS";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bencode_list_and_dict() {
        assert_eq!(
            bencode(&bytes_list(&[b"error".to_vec(), b"msg".to_vec()])),
            b"l5:error3:msge"
        );
        let dict = Value::Dict(
            [(
                Cow::Owned(b"Software version".to_vec()),
                Value::Bytes(Cow::Owned(b"3.4".to_vec())),
            )]
            .into_iter()
            .collect(),
        );
        assert_eq!(bencode(&dict), b"d16:Software version3:3.4e");
    }

    #[test]
    fn dict_keys_are_sorted() {
        let dict = Value::Dict(
            [
                (
                    Cow::Owned(b"b".to_vec()),
                    Value::Bytes(Cow::Owned(b"2".to_vec())),
                ),
                (
                    Cow::Owned(b"a".to_vec()),
                    Value::Bytes(Cow::Owned(b"1".to_vec())),
                ),
            ]
            .into_iter()
            .collect(),
        );
        assert_eq!(bencode(&dict), b"d1:a1:11:b1:2e");
    }

    #[test]
    fn structure_framing() {
        // "s" + struct.pack("!L", len(bencode)) + bencode(["error", "msg"])
        let s = structure(&[b"error".to_vec(), b"msg".to_vec()]);
        assert_eq!(&s[..1], b"s");
        let len = u32::from_be_bytes(s[1..5].try_into().unwrap()) as usize;
        assert_eq!(&s[5..], b"l5:error3:msge");
        assert_eq!(len, s.len() - 5);
    }

    #[test]
    fn body_framing() {
        let b = prefixed_body(b"hello");
        assert_eq!(b[0], b'b');
        assert_eq!(u32::from_be_bytes(b[1..5].try_into().unwrap()), 5);
        assert_eq!(&b[5..], b"hello");
    }

    #[test]
    fn headers_framing() {
        let h = headers(&[(b"Software version".to_vec(), b"3.4".to_vec())]);
        let len = u32::from_be_bytes(h[..4].try_into().unwrap()) as usize;
        assert_eq!(&h[4..], b"d16:Software version3:3.4e");
        assert_eq!(len, h.len() - 4);
    }
}
