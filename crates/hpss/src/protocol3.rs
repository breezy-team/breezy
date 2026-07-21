//! Wire framing for smart protocol version 3.
//!
//! Ports the byte-construction half of `_ProtocolThreeEncoder` from
//! `breezy/bzr/smart/protocol.py`. The streaming / write_func orchestration
//! stays in Python; these functions build the bytes for each message part.
//!
//! bencode is provided by the `bendy` crate, which enforces the same canonical
//! form (sorted dict keys, no leading zeros) as fastbencode.

use bendy::decoding::{Decoder, Object};
use bendy::encoding::Encoder;
pub use bendy::value::Value;
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
    structure_value(&bytes_list(args))
}

/// `_write_structure` for an arbitrary list `Value`. Response args are usually
/// byte strings but may contain integers or nested structures, so the encoder
/// must accept any bencode-able list (matching the original `bencode(args)`).
pub fn structure_value(args: &Value) -> Vec<u8> {
    let mut out = vec![b's'];
    out.extend_from_slice(&prefixed_bencode(args));
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

/// A decoded bencode value.
///
/// Lists are kept distinct from dicts so the binding can map lists to Python
/// tuples (matching `fastbencode.bdecode_as_tuple`). Integers are kept as their
/// textual token to preserve arbitrary precision, since Python ints are
/// unbounded but `bendy`'s own integer type is not.
#[derive(Debug, PartialEq, Eq)]
pub enum Decoded {
    Bytes(Vec<u8>),
    /// The integer's decimal text (e.g. `-7`, `123...`).
    Integer(String),
    List(Vec<Decoded>),
    Dict(Vec<(Vec<u8>, Decoded)>),
}

/// Failure to decode bencoded bytes. Carries a message mirroring the
/// `ValueError` text that `fastbencode.bdecode_as_tuple` would raise.
#[derive(Debug, PartialEq, Eq)]
pub struct BdecodeError(pub String);

/// Decode bencoded bytes, rejecting trailing junk (like `bdecode_as_tuple`).
///
/// `bendy` enforces canonical form: sorted dict keys, no leading zeros, no
/// negative zero. These match fastbencode's checks.
pub fn bdecode(bytes: &[u8]) -> Result<Decoded, BdecodeError> {
    let mut decoder = Decoder::new(bytes).with_max_depth(MAX_DEPTH);
    let obj = decoder
        .next_object()
        .map_err(|e| BdecodeError(e.to_string()))?
        .ok_or_else(|| BdecodeError("stream underflow".into()))?;
    let decoded = decode_object(obj)?;
    // Reject trailing data after a complete object.
    let trailing = decoder
        .next_object()
        .map_err(|e| BdecodeError(e.to_string()))?
        .is_some();
    if trailing {
        return Err(BdecodeError("junk in stream".into()));
    }
    Ok(decoded)
}

fn decode_object(obj: Object<'_, '_>) -> Result<Decoded, BdecodeError> {
    match obj {
        Object::Bytes(b) => Ok(Decoded::Bytes(b.to_vec())),
        Object::Integer(text) => Ok(Decoded::Integer(text.to_string())),
        Object::List(mut list) => {
            let mut items = Vec::new();
            while let Some(item) = list
                .next_object()
                .map_err(|e| BdecodeError(e.to_string()))?
            {
                items.push(decode_object(item)?);
            }
            Ok(Decoded::List(items))
        }
        Object::Dict(mut dict) => {
            let mut pairs = Vec::new();
            while let Some((key, value)) =
                dict.next_pair().map_err(|e| BdecodeError(e.to_string()))?
            {
                pairs.push((key.to_vec(), decode_object(value)?));
            }
            Ok(Decoded::Dict(pairs))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn b(s: &[u8]) -> Decoded {
        Decoded::Bytes(s.to_vec())
    }
    fn i(s: &str) -> Decoded {
        Decoded::Integer(s.to_string())
    }

    #[test]
    fn bdecode_scalars() {
        assert_eq!(bdecode(b"5:hello"), Ok(b(b"hello")));
        assert_eq!(bdecode(b"0:"), Ok(b(b"")));
        assert_eq!(bdecode(b"i42e"), Ok(i("42")));
        assert_eq!(bdecode(b"i-7e"), Ok(i("-7")));
    }

    #[test]
    fn bdecode_big_int_preserved() {
        let big = "123456789012345678901234567890";
        assert_eq!(bdecode(format!("i{big}e").as_bytes()), Ok(i(big)));
    }

    #[test]
    fn bdecode_list_and_nesting() {
        assert_eq!(bdecode(b"le"), Ok(Decoded::List(vec![])));
        assert_eq!(
            bdecode(b"l1:a1:be"),
            Ok(Decoded::List(vec![b(b"a"), b(b"b")]))
        );
        assert_eq!(
            bdecode(b"l1:ali1ei2eee"),
            Ok(Decoded::List(vec![
                b(b"a"),
                Decoded::List(vec![i("1"), i("2")])
            ]))
        );
    }

    #[test]
    fn bdecode_dict() {
        assert_eq!(bdecode(b"de"), Ok(Decoded::Dict(vec![])));
        assert_eq!(
            bdecode(b"d1:a1:be"),
            Ok(Decoded::Dict(vec![(b"a".to_vec(), b(b"b"))]))
        );
        assert_eq!(
            bdecode(b"d1:al1:xee"),
            Ok(Decoded::Dict(vec![(
                b"a".to_vec(),
                Decoded::List(vec![b(b"x")])
            )]))
        );
    }

    #[test]
    fn bdecode_rejects_trailing_junk() {
        assert_eq!(
            bdecode(b"i1ei2e"),
            Err(BdecodeError("junk in stream".into()))
        );
    }

    #[test]
    fn bdecode_rejects_malformed() {
        // Empty, leading zeros, unsorted/duplicate keys, truncation all error.
        assert!(bdecode(b"").is_err());
        assert!(bdecode(b"i03e").is_err());
        assert!(bdecode(b"d1:b1:21:a1:1e").is_err());
        assert!(bdecode(b"5:ab").is_err());
        assert!(bdecode(b"x").is_err());
    }

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
    fn structure_value_with_nested_and_int() {
        // Response args are not always flat byte lists: they may carry integers
        // or nested structures. "s" + prefix + bencode([b"ok", [b"a"], 3]).
        let value = Value::List(vec![
            Value::Bytes(Cow::Owned(b"ok".to_vec())),
            Value::List(vec![Value::Bytes(Cow::Owned(b"a".to_vec()))]),
            Value::Integer(3),
        ]);
        let s = structure_value(&value);
        assert_eq!(&s[..1], b"s");
        assert_eq!(&s[5..], b"l2:okl1:aei3ee");
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
