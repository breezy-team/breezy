//! Body encoding selection and RFC2047 header encoding.

use base64::engine::general_purpose::STANDARD;
use base64::Engine;

/// The charset a body is sent with.
///
/// These are the three labels `EmailMessage.string_with_encoding` may return.
/// `8-bit` is not a real charset; it is what Bazaar has always emitted for
/// bodies that are neither ASCII nor UTF-8, and is kept for compatibility.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BodyEncoding {
    /// Pure ASCII, sent verbatim as 7bit.
    Ascii,
    /// Valid UTF-8, sent base64-encoded.
    Utf8,
    /// Neither ASCII nor UTF-8, sent base64-encoded.
    EightBit,
}

impl BodyEncoding {
    /// The name used by `string_with_encoding`, e.g. `"utf-8"`.
    pub fn name(self) -> &'static str {
        match self {
            BodyEncoding::Ascii => "ascii",
            BodyEncoding::Utf8 => "utf-8",
            BodyEncoding::EightBit => "8-bit",
        }
    }

    /// The name used in a Content-Type charset parameter.
    ///
    /// Only ASCII differs: Python's email package maps it to its preferred
    /// MIME name, `us-ascii`.
    pub fn charset_name(self) -> &'static str {
        match self {
            BodyEncoding::Ascii => "us-ascii",
            BodyEncoding::Utf8 => "utf-8",
            BodyEncoding::EightBit => "8-bit",
        }
    }

    /// The Content-Transfer-Encoding used for a body in this charset.
    pub fn transfer_encoding(self) -> &'static str {
        match self {
            BodyEncoding::Ascii => "7bit",
            BodyEncoding::Utf8 | BodyEncoding::EightBit => "base64",
        }
    }
}

/// Pick the encoding for an already-encoded body.
///
/// Preference order is ascii, utf-8, then 8-bit. Bodies are passed through
/// unchanged; only the label is chosen.
pub fn detect_encoding(body: &[u8]) -> BodyEncoding {
    if body.is_ascii() {
        BodyEncoding::Ascii
    } else if std::str::from_utf8(body).is_ok() {
        BodyEncoding::Utf8
    } else {
        BodyEncoding::EightBit
    }
}

/// Pick the encoding for a text body, returning the encoded bytes.
///
/// Text is always representable, so this never yields 8-bit.
pub fn encode_str(body: &str) -> (Vec<u8>, BodyEncoding) {
    let encoding = if body.is_ascii() {
        BodyEncoding::Ascii
    } else {
        BodyEncoding::Utf8
    };
    (body.as_bytes().to_vec(), encoding)
}

/// Encode a payload the way Python's email package would for this charset.
///
/// ASCII bodies are emitted verbatim; anything else is base64 in 76-column
/// lines, each terminated by a newline.
pub fn encode_payload(body: &[u8], encoding: BodyEncoding) -> Vec<u8> {
    if encoding == BodyEncoding::Ascii {
        return normalize_line_endings(body);
    }
    let encoded = STANDARD.encode(body);
    let mut out = Vec::with_capacity(encoded.len() + encoded.len() / 76 + 1);
    for chunk in encoded.as_bytes().chunks(76) {
        out.extend_from_slice(chunk);
        out.push(b'\n');
    }
    out
}

/// Rewrite CRLF and lone CR as LF, as Python's generator does.
///
/// Only unencoded payloads need this; base64 output carries the original bytes
/// through untouched.
fn normalize_line_endings(body: &[u8]) -> Vec<u8> {
    if !body.contains(&b'\r') {
        return body.to_vec();
    }
    let mut out = Vec::with_capacity(body.len());
    let mut i = 0;
    while i < body.len() {
        if body[i] == b'\r' {
            out.push(b'\n');
            // Consume the LF of a CRLF pair so it does not double up.
            if body.get(i + 1) == Some(&b'\n') {
                i += 1;
            }
        } else {
            out.push(body[i]);
        }
        i += 1;
    }
    out
}

/// True if `b` needs no escaping inside an RFC2047 quoted-printable word.
///
/// Matches `email.quoprimime.header_check`. Note that space is not in this set;
/// it is encoded separately as `_`.
fn is_plain_q_char(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'!' | b'*' | b'+' | b'-' | b'/')
}

/// Length of the quoted-printable form of `bytes`, excluding RFC2047 chrome.
fn q_encoded_len(bytes: &[u8]) -> usize {
    bytes
        .iter()
        .map(|&b| {
            if is_plain_q_char(b) || b == b' ' {
                1
            } else {
                3
            }
        })
        .sum()
}

/// Length of the base64 form of `bytes`, excluding RFC2047 chrome.
fn b_encoded_len(bytes: &[u8]) -> usize {
    bytes.len().div_ceil(3) * 4
}

/// Quoted-printable encode `bytes` for use in an RFC2047 encoded word.
fn q_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut out = String::with_capacity(bytes.len());
    for &b in bytes {
        if b == b' ' {
            out.push('_');
        } else if is_plain_q_char(b) {
            out.push(b as char);
        } else {
            out.push('=');
            out.push(HEX[(b >> 4) as usize] as char);
            out.push(HEX[(b & 0xf) as usize] as char);
        }
    }
    out
}

/// RFC2047-encode a header value, as `email.charset.Charset('utf-8')` would.
///
/// ASCII values are returned unchanged. Otherwise UTF-8 uses the SHORTEST policy: whichever of base64 and quoted-printable is
/// shorter wins, with quoted-printable breaking ties. The result is a single
/// encoded word; Python only folds long headers when they are attached to a
/// message, which this code never relies on.
pub fn rfc2047_encode(value: &str) -> String {
    if value.is_ascii() {
        return value.to_string();
    }
    let bytes = value.as_bytes();
    if b_encoded_len(bytes) < q_encoded_len(bytes) {
        format!("=?utf-8?b?{}?=", STANDARD.encode(bytes))
    } else {
        format!("=?utf-8?q?{}?=", q_encode(bytes))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_preferred_encoding() {
        assert_eq!(BodyEncoding::Ascii, detect_encoding(b"Pepe"));
        assert_eq!(BodyEncoding::Utf8, detect_encoding(b"P\xc3\xa9rez"));
        assert_eq!(BodyEncoding::EightBit, detect_encoding(b"P\xe8rez"));
    }

    #[test]
    fn text_is_never_eight_bit() {
        assert_eq!((b"Pepe".to_vec(), BodyEncoding::Ascii), encode_str("Pepe"));
        assert_eq!(
            (b"P\xc3\xa9rez".to_vec(), BodyEncoding::Utf8),
            encode_str("P\u{e9}rez")
        );
    }

    #[test]
    fn ascii_payload_is_verbatim() {
        assert_eq!(
            b"body".to_vec(),
            encode_payload(b"body", BodyEncoding::Ascii)
        );
    }

    #[test]
    fn non_ascii_payload_is_base64() {
        assert_eq!(
            b"YsOzZHk=\n".to_vec(),
            encode_payload("b\u{f3}dy".as_bytes(), BodyEncoding::Utf8)
        );
        assert_eq!(
            b"YvRkeQ==\n".to_vec(),
            encode_payload(b"b\xf4dy", BodyEncoding::EightBit)
        );
    }

    #[test]
    fn base64_wraps_at_76_columns() {
        let body = "\u{e9}".repeat(200);
        let encoded = encode_payload(body.as_bytes(), BodyEncoding::Utf8);
        let text = String::from_utf8(encoded).unwrap();
        for line in text.lines() {
            assert!(line.len() <= 76, "line too long: {}", line.len());
        }
        assert!(text.ends_with('\n'));
        assert_eq!(8, text.lines().count());
    }

    #[test]
    fn ascii_headers_are_untouched() {
        assert_eq!("subject", rfc2047_encode("subject"));
        assert_eq!("J. Random Developer", rfc2047_encode("J. Random Developer"));
    }

    #[test]
    fn non_ascii_headers_use_quoted_printable() {
        assert_eq!(
            "=?utf-8?q?Pepe_P=C3=A9rez?=",
            rfc2047_encode("Pepe P\u{e9}rez")
        );
    }

    #[test]
    fn base64_wins_when_shorter() {
        // Mostly-special content costs three characters per byte in
        // quoted-printable, so base64 comes out shorter.
        assert_eq!(
            "=?utf-8?b?w6kiKCksOjs8PkBbXVzDqQ==?=",
            rfc2047_encode("\u{e9}\"(),:;<>@[]\\\u{e9}")
        );
    }
}
