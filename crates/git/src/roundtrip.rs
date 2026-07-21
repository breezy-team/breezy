//! Roundtripping metadata parsing and generation.
//!
//! Bazaar stores more data than Git, so pushing a Bazaar revision into Git
//! stashes the extra metadata in a `--BZR--` trailer on the commit message.
//! This module ports the byte-level parsing and generation of that trailer.

use std::collections::HashMap;

/// The only verifier that is serialized into the roundtripping trailer.
const TESTAMENT3_SHA1: &[u8] = b"testament3-sha1";

/// The plain decomposed form of a [`CommitSupplement`], mirroring the
/// attributes the Python wrapper carries.
pub struct SupplementParts {
    pub revision_id: Option<Vec<u8>>,
    pub explicit_parent_ids: Option<Vec<Vec<u8>>>,
    pub properties: Vec<(Vec<u8>, Vec<u8>)>,
    pub testament3_sha1: Option<Vec<u8>>,
}

/// Metadata for a Bazaar revision roundtripped into Git.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct CommitSupplement {
    pub revision_id: Option<Vec<u8>>,
    pub explicit_parent_ids: Option<Vec<Vec<u8>>>,
    /// Revision properties, in insertion order.
    pub properties: Vec<(Vec<u8>, Vec<u8>)>,
    pub verifiers: HashMap<Vec<u8>, Vec<u8>>,
}

impl CommitSupplement {
    pub fn is_empty(&self) -> bool {
        self.revision_id.is_none()
            && self.properties.is_empty()
            && self.explicit_parent_ids.is_none()
    }

    /// The testament3-sha1 verifier, the only one round-tripped.
    pub fn testament3_sha1(&self) -> Option<&[u8]> {
        self.verifiers.get(TESTAMENT3_SHA1).map(|v| v.as_slice())
    }

    pub fn set_testament3_sha1(&mut self, sha1: Vec<u8>) {
        self.verifiers.insert(TESTAMENT3_SHA1.to_vec(), sha1);
    }

    /// Decompose into the plain parts the Python `CommitSupplement`
    /// wrapper mirrors: `(revision_id, parent_ids, properties,
    /// testament3_sha1)`. Only the round-tripped verifier is exposed.
    pub fn into_parts(self) -> SupplementParts {
        let testament3 = self.testament3_sha1().map(|v| v.to_vec());
        SupplementParts {
            revision_id: self.revision_id,
            explicit_parent_ids: self.explicit_parent_ids,
            properties: self.properties,
            testament3_sha1: testament3,
        }
    }

    /// Rebuild from the plain parts produced by [`into_parts`].
    pub fn from_parts(parts: SupplementParts) -> Self {
        let mut ret = CommitSupplement {
            revision_id: parts.revision_id,
            explicit_parent_ids: parts.explicit_parent_ids,
            properties: parts.properties,
            ..Default::default()
        };
        if let Some(sha1) = parts.testament3_sha1 {
            ret.set_testament3_sha1(sha1);
        }
        ret
    }

    fn set_property(&mut self, name: Vec<u8>, value: Vec<u8>) {
        for (k, v) in self.properties.iter_mut() {
            if *k == name {
                v.push(b'\n');
                v.extend_from_slice(&value);
                return;
            }
        }
        self.properties.push((name, value));
    }
}

fn strip(value: &[u8]) -> &[u8] {
    let start = value.iter().position(|b| !b.is_ascii_whitespace());
    match start {
        None => &[],
        Some(start) => {
            let end = value
                .iter()
                .rposition(|b| !b.is_ascii_whitespace())
                .unwrap();
            &value[start..=end]
        }
    }
}

fn rstrip_newlines(value: &[u8]) -> &[u8] {
    let end = value.iter().rposition(|b| *b != b'\n');
    match end {
        None => &[],
        Some(end) => &value[..=end],
    }
}

/// Parse Bazaar roundtripping metadata.
///
/// Returns an error for unknown keys or lines lacking a `:` separator,
/// matching the Python implementation's `ValueError`.
pub fn parse_roundtripping_metadata(text: &[u8]) -> Result<CommitSupplement, ParseError> {
    let mut ret = CommitSupplement::default();
    for line in split_lines(text) {
        let colon = line
            .iter()
            .position(|b| *b == b':')
            .ok_or(ParseError::MissingSeparator)?;
        let key = &line[..colon];
        let value = &line[colon + 1..];
        if key == b"revision-id" {
            ret.revision_id = Some(strip(value).to_vec());
        } else if key == b"parent-ids" {
            ret.explicit_parent_ids = Some(
                strip(value)
                    .split(|b| *b == b' ')
                    .map(|s| s.to_vec())
                    .collect(),
            );
        } else if key == TESTAMENT3_SHA1 {
            ret.set_testament3_sha1(strip(value).to_vec());
        } else if let Some(name) = key.strip_prefix(b"property-") {
            // Drop the single leading space after the colon, then strip
            // trailing newlines.
            let value = rstrip_newlines(&value[1..]);
            ret.set_property(name.to_vec(), value.to_vec());
        } else {
            return Err(ParseError::UnknownKey);
        }
    }
    Ok(ret)
}

/// Serialize the roundtripping metadata.
pub fn generate_roundtripping_metadata(metadata: &CommitSupplement) -> Vec<u8> {
    let mut lines: Vec<u8> = Vec::new();
    if let Some(revision_id) = &metadata.revision_id {
        if !revision_id.is_empty() {
            lines.extend_from_slice(b"revision-id: ");
            lines.extend_from_slice(revision_id);
            lines.push(b'\n');
        }
    }
    if let Some(parent_ids) = &metadata.explicit_parent_ids {
        if !parent_ids.is_empty() {
            lines.extend_from_slice(b"parent-ids: ");
            for (i, pid) in parent_ids.iter().enumerate() {
                if i > 0 {
                    lines.push(b' ');
                }
                lines.extend_from_slice(pid);
            }
            lines.push(b'\n');
        }
    }
    let mut props: Vec<&(Vec<u8>, Vec<u8>)> = metadata.properties.iter().collect();
    props.sort_by(|a, b| a.0.cmp(&b.0));
    for (key, value) in props {
        for fragment in value.split(|b| *b == b'\n') {
            lines.extend_from_slice(b"property-");
            lines.extend_from_slice(key);
            lines.extend_from_slice(b": ");
            lines.extend_from_slice(fragment);
            lines.push(b'\n');
        }
    }
    if let Some(sha1) = metadata.testament3_sha1() {
        lines.extend_from_slice(TESTAMENT3_SHA1);
        lines.extend_from_slice(b": ");
        lines.extend_from_slice(sha1);
        lines.push(b'\n');
    }
    lines
}

/// Extract Bazaar metadata from a commit message.
///
/// Returns the original message and, if present, the parsed metadata.
pub fn extract_bzr_metadata(
    message: &[u8],
) -> Result<(Vec<u8>, Option<CommitSupplement>), ParseError> {
    match find_subsequence(message, b"\n--BZR--\n") {
        None => Ok((message.to_vec(), None)),
        Some(pos) => {
            let head = &message[..pos];
            let tail = &message[pos + b"\n--BZR--\n".len()..];
            Ok((head.to_vec(), Some(parse_roundtripping_metadata(tail)?)))
        }
    }
}

/// Inject Bazaar metadata into a commit message.
pub fn inject_bzr_metadata(message: &[u8], commit_supplement: &CommitSupplement) -> Vec<u8> {
    if commit_supplement.is_empty() {
        return message.to_vec();
    }
    let rt_data = generate_roundtripping_metadata(commit_supplement);
    if rt_data.is_empty() {
        return message.to_vec();
    }
    let mut out = message.to_vec();
    out.extend_from_slice(b"\n--BZR--\n");
    out.extend_from_slice(&rt_data);
    out
}

/// Split into lines, keeping the trailing newline on each, matching
/// Python's `BytesIO.readlines`.
fn split_lines(text: &[u8]) -> Vec<&[u8]> {
    let mut lines = Vec::new();
    let mut start = 0;
    for (i, b) in text.iter().enumerate() {
        if *b == b'\n' {
            lines.push(&text[start..=i]);
            start = i + 1;
        }
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}

fn find_subsequence(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() {
        return Some(0);
    }
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

#[derive(Debug, PartialEq, Eq)]
pub enum ParseError {
    MissingSeparator,
    UnknownKey,
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ParseError::MissingSeparator => write!(f, "line without separator"),
            ParseError::UnknownKey => write!(f, "unknown roundtripping key"),
        }
    }
}

impl std::error::Error for ParseError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_revid() {
        let md = parse_roundtripping_metadata(b"revision-id: foo\n").unwrap();
        assert_eq!(Some(b"foo".to_vec()), md.revision_id);
    }

    #[test]
    fn parts_round_trip_testament3() {
        let md = parse_roundtripping_metadata(b"testament3-sha1: deadbeef\n").unwrap();
        let parts = md.clone().into_parts();
        assert_eq!(Some(b"deadbeef".to_vec()), parts.testament3_sha1);
        assert_eq!(md, CommitSupplement::from_parts(parts));
    }

    #[test]
    fn parse_parent_ids() {
        let md = parse_roundtripping_metadata(b"parent-ids: foo bar\n").unwrap();
        assert_eq!(
            Some(vec![b"foo".to_vec(), b"bar".to_vec()]),
            md.explicit_parent_ids
        );
    }

    #[test]
    fn parse_properties() {
        let md = parse_roundtripping_metadata(b"property-foop: blar\n").unwrap();
        assert_eq!(vec![(b"foop".to_vec(), b"blar".to_vec())], md.properties);
    }

    #[test]
    fn parse_unknown_key() {
        assert_eq!(
            Err(ParseError::UnknownKey),
            parse_roundtripping_metadata(b"bogus: value\n")
        );
    }

    #[test]
    fn parse_multiline_property() {
        let md = parse_roundtripping_metadata(b"property-foo: bar\nproperty-foo: baz\n").unwrap();
        assert_eq!(vec![(b"foo".to_vec(), b"bar\nbaz".to_vec())], md.properties);
    }

    #[test]
    fn generate_revid() {
        let mut md = CommitSupplement::default();
        md.revision_id = Some(b"bla".to_vec());
        assert_eq!(
            b"revision-id: bla\n".to_vec(),
            generate_roundtripping_metadata(&md)
        );
    }

    #[test]
    fn generate_parent_ids() {
        let mut md = CommitSupplement::default();
        md.explicit_parent_ids = Some(vec![b"foo".to_vec(), b"bar".to_vec()]);
        assert_eq!(
            b"parent-ids: foo bar\n".to_vec(),
            generate_roundtripping_metadata(&md)
        );
    }

    #[test]
    fn generate_properties() {
        let mut md = CommitSupplement::default();
        md.properties = vec![(b"foo".to_vec(), b"bar".to_vec())];
        assert_eq!(
            b"property-foo: bar\n".to_vec(),
            generate_roundtripping_metadata(&md)
        );
    }

    #[test]
    fn generate_empty() {
        let md = CommitSupplement::default();
        assert_eq!(Vec::<u8>::new(), generate_roundtripping_metadata(&md));
    }

    #[test]
    fn extract_roundtrip() {
        let (msg, metadata) = extract_bzr_metadata(b"Foo\n--BZR--\nrevision-id: foo\n").unwrap();
        assert_eq!(b"Foo".to_vec(), msg);
        assert_eq!(Some(b"foo".to_vec()), metadata.unwrap().revision_id);
    }

    #[test]
    fn extract_no_metadata() {
        let (msg, metadata) = extract_bzr_metadata(b"Foo").unwrap();
        assert_eq!(b"Foo".to_vec(), msg);
        assert_eq!(None, metadata);
    }

    #[test]
    fn inject_roundtrip() {
        let mut md = CommitSupplement::default();
        md.revision_id = Some(b"myrevid".to_vec());
        assert_eq!(
            b"Foo\n--BZR--\nrevision-id: myrevid\n".to_vec(),
            inject_bzr_metadata(b"Foo", &md)
        );
    }

    #[test]
    fn inject_no_metadata() {
        let md = CommitSupplement::default();
        assert_eq!(b"Foo".to_vec(), inject_bzr_metadata(b"Foo", &md));
    }
}
