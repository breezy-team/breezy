//! Parsing and formatting of hg-git `--HG--` commit-message metadata.

use percent_encoding::percent_decode;
use std::collections::HashMap;

/// Whether a byte is left unescaped by Python's `quote_from_bytes` with the
/// default `safe='/'`: the unreserved set (`A-Za-z0-9-._~`) plus `/`.
fn is_quote_safe(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'-' | b'.' | b'_' | b'~' | b'/')
}

/// Extra keys that are never emitted into the trailer.
const RESERVED_EXTRA_KEYS: &[&str] = &[
    "author",
    "committer",
    "encoding",
    "message",
    "branch",
    "hg-git",
];

/// Metadata extracted from an hg-git `--HG--` trailer.
#[derive(Debug, PartialEq, Eq)]
pub struct HgMetadata {
    /// The commit message with the trailer removed.
    pub message: Vec<u8>,
    /// File renames, keyed by the new path.
    pub renames: HashMap<Vec<u8>, Vec<u8>>,
    /// Branch name, if a `branch` line was present.
    pub branch: Option<String>,
    /// Extra key/value pairs, with values percent-decoded.
    pub extra: HashMap<String, Vec<u8>>,
}

/// Extract Mercurial metadata from a commit message.
///
/// Returns the message with the trailer stripped plus the parsed renames,
/// branch and extra data. Errors on a malformed line or unknown command.
pub fn extract_hg_metadata(message: &[u8]) -> Result<HgMetadata, ParseError> {
    let mut renames = HashMap::new();
    let mut extra = HashMap::new();
    let mut branch = None;

    let Some((head, meta)) = split_once(message, b"\n--HG--\n") else {
        return Ok(HgMetadata {
            message: message.to_vec(),
            renames,
            branch,
            extra,
        });
    };

    for line in meta.split(|b| *b == b'\n') {
        if line.is_empty() {
            continue;
        }
        let (command, data) =
            split_once(line, b" : ").ok_or_else(|| ParseError::MalformedLine(line.to_vec()))?;
        match command {
            b"rename" => {
                let (before, after) = split_once(data, b" => ")
                    .ok_or_else(|| ParseError::MalformedRename(data.to_vec()))?;
                renames.insert(after.to_vec(), before.to_vec());
            }
            b"branch" => branch = Some(decode_utf8(data)?),
            b"extra" => {
                let (before, after) = split_once(data, b" : ")
                    .ok_or_else(|| ParseError::MalformedExtra(data.to_vec()))?;
                extra.insert(decode_utf8(before)?, unquote(after));
            }
            other => return Err(ParseError::UnknownCommand(other.to_vec())),
        }
    }

    Ok(HgMetadata {
        message: head.to_vec(),
        renames,
        branch,
        extra,
    })
}

/// Construct a commit-message tail carrying hg-git metadata.
///
/// `renames` is a list of `(oldpath, newpath)` byte pairs, `branch` a
/// branch name, and `extra` a map of extra key/value pairs. Returns the
/// tail, or an empty vector if there is nothing to record.
pub fn format_hg_metadata(
    renames: &[(Vec<u8>, Vec<u8>)],
    branch: &str,
    extra: &[(String, Vec<u8>)],
) -> Vec<u8> {
    let mut body: Vec<u8> = Vec::new();
    if branch != "default" {
        body.extend_from_slice(b"branch : ");
        body.extend_from_slice(branch.as_bytes());
        body.push(b'\n');
    }
    for (oldfile, newfile) in renames {
        body.extend_from_slice(b"rename : ");
        body.extend_from_slice(oldfile);
        body.extend_from_slice(b" => ");
        body.extend_from_slice(newfile);
        body.push(b'\n');
    }
    for (key, value) in extra {
        if RESERVED_EXTRA_KEYS.contains(&key.as_str()) {
            continue;
        }
        body.extend_from_slice(b"extra : ");
        body.extend_from_slice(key.as_bytes());
        body.extend_from_slice(b" : ");
        body.extend_from_slice(quote(value).as_bytes());
        body.push(b'\n');
    }
    if body.is_empty() {
        return Vec::new();
    }
    let mut out = b"\n--HG--\n".to_vec();
    out.extend_from_slice(&body);
    out
}

fn split_once<'a>(haystack: &'a [u8], sep: &[u8]) -> Option<(&'a [u8], &'a [u8])> {
    haystack
        .windows(sep.len())
        .position(|w| w == sep)
        .map(|pos| (&haystack[..pos], &haystack[pos + sep.len()..]))
}

fn decode_utf8(value: &[u8]) -> Result<String, ParseError> {
    String::from_utf8(value.to_vec()).map_err(|_| ParseError::InvalidUtf8(value.to_vec()))
}

/// Percent-decode like Python's `urllib.parse.unquote_to_bytes`: decode
/// valid `%XX` escapes, pass invalid sequences through literally.
fn unquote(value: &[u8]) -> Vec<u8> {
    percent_decode(value).collect()
}

/// Percent-encode like `urllib.parse.quote_from_bytes` with `safe='/'`.
fn quote(value: &[u8]) -> String {
    // Encode byte-wise: hg extra values are arbitrary bytes, not text.
    let mut out = String::with_capacity(value.len());
    for &b in value {
        if is_quote_safe(b) {
            out.push(b as char);
        } else {
            out.push('%');
            out.push_str(&format!("{b:02X}"));
        }
    }
    out
}

#[derive(Debug, PartialEq, Eq)]
pub enum ParseError {
    MalformedLine(Vec<u8>),
    MalformedRename(Vec<u8>),
    MalformedExtra(Vec<u8>),
    UnknownCommand(Vec<u8>),
    InvalidUtf8(Vec<u8>),
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ParseError::MalformedLine(l) => {
                write!(
                    f,
                    "malformed hg metadata line: {}",
                    String::from_utf8_lossy(l)
                )
            }
            ParseError::MalformedRename(d) => {
                write!(f, "malformed hg rename: {}", String::from_utf8_lossy(d))
            }
            ParseError::MalformedExtra(d) => {
                write!(f, "malformed hg extra: {}", String::from_utf8_lossy(d))
            }
            ParseError::UnknownCommand(c) => write!(
                f,
                "unknown hg-git metadata command {}",
                String::from_utf8_lossy(c)
            ),
            ParseError::InvalidUtf8(v) => {
                write!(
                    f,
                    "invalid utf-8 in hg metadata: {}",
                    String::from_utf8_lossy(v)
                )
            }
        }
    }
}

impl std::error::Error for ParseError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_trailer() {
        let md = extract_hg_metadata(b"just a message").unwrap();
        assert_eq!(b"just a message".to_vec(), md.message);
        assert!(md.renames.is_empty());
        assert_eq!(None, md.branch);
        assert!(md.extra.is_empty());
    }

    #[test]
    fn branch() {
        let md = extract_hg_metadata(b"msg\n--HG--\nbranch : featurex\n").unwrap();
        assert_eq!(b"msg".to_vec(), md.message);
        assert_eq!(Some("featurex".to_string()), md.branch);
    }

    #[test]
    fn rename_keyed_by_after() {
        let md = extract_hg_metadata(b"msg\n--HG--\nrename : a => b\n").unwrap();
        assert_eq!(HashMap::from([(b"b".to_vec(), b"a".to_vec())]), md.renames);
    }

    #[test]
    fn extra_percent_decoded() {
        let md = extract_hg_metadata(b"msg\n--HG--\nextra : k : hello%20world\n").unwrap();
        assert_eq!(
            HashMap::from([("k".to_string(), b"hello world".to_vec())]),
            md.extra
        );
    }

    #[test]
    fn empty_lines_skipped() {
        let md = extract_hg_metadata(b"m\n--HG--\n\nbranch : x\n\n").unwrap();
        assert_eq!(Some("x".to_string()), md.branch);
    }

    #[test]
    fn unknown_command() {
        assert_eq!(
            Err(ParseError::UnknownCommand(b"bogus".to_vec())),
            extract_hg_metadata(b"m\n--HG--\nbogus : x\n")
        );
    }

    #[test]
    fn malformed_line() {
        assert_eq!(
            Err(ParseError::MalformedLine(b"nocolon".to_vec())),
            extract_hg_metadata(b"m\n--HG--\nnocolon\n")
        );
    }

    #[test]
    fn format_empty() {
        assert_eq!(Vec::<u8>::new(), format_hg_metadata(&[], "default", &[]));
    }

    #[test]
    fn format_branch() {
        assert_eq!(
            b"\n--HG--\nbranch : featurex\n".to_vec(),
            format_hg_metadata(&[], "featurex", &[])
        );
    }

    #[test]
    fn format_rename() {
        assert_eq!(
            b"\n--HG--\nrename : a => b\n".to_vec(),
            format_hg_metadata(&[(b"a".to_vec(), b"b".to_vec())], "default", &[])
        );
    }

    #[test]
    fn format_extra() {
        assert_eq!(
            b"\n--HG--\nextra : k : hello%20world\n".to_vec(),
            format_hg_metadata(
                &[],
                "default",
                &[("k".to_string(), b"hello world".to_vec())]
            )
        );
    }

    #[test]
    fn format_reserved_keys_skipped() {
        assert_eq!(
            Vec::<u8>::new(),
            format_hg_metadata(
                &[],
                "default",
                &[
                    ("branch".to_string(), b"x".to_vec()),
                    ("message".to_string(), b"y".to_vec()),
                ]
            )
        );
    }

    #[test]
    fn round_trip() {
        let tail = format_hg_metadata(
            &[(b"old".to_vec(), b"new".to_vec())],
            "featurex",
            &[("k".to_string(), b"v w".to_vec())],
        );
        let mut input = b"msg".to_vec();
        input.extend_from_slice(&tail);
        let md = extract_hg_metadata(&input).unwrap();
        assert_eq!(b"msg".to_vec(), md.message);
        assert_eq!(
            HashMap::from([(b"new".to_vec(), b"old".to_vec())]),
            md.renames
        );
        assert_eq!(Some("featurex".to_string()), md.branch);
        assert_eq!(
            HashMap::from([("k".to_string(), b"v w".to_vec())]),
            md.extra
        );
    }

    #[test]
    fn quote_matches_python() {
        assert_eq!("hello%20world", quote(b"hello world"));
        assert_eq!("a/b%3Ac%3Fd%26e", quote(b"a/b:c?d&e"));
        assert_eq!("%00%FF", quote(b"\x00\xff"));
        assert_eq!("a_b.c-d~e", quote(b"a_b.c-d~e"));
    }

    #[test]
    fn unquote_invalid_passthrough() {
        assert_eq!(b"50%discount".to_vec(), unquote(b"50%discount"));
        assert_eq!(b"a%2".to_vec(), unquote(b"a%2"));
        assert_eq!("café".as_bytes().to_vec(), unquote(b"caf%C3%A9"));
    }
}
