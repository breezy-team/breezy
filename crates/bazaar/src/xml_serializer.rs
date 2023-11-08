#![allow(dead_code)]
use crate::revision::Revision;
use crate::serializer::{Error, RevisionSerializer};
use crate::RevisionId;
use lazy_regex::regex_replace_all;
use std::collections::HashMap;
use std::io::{BufRead, Read, Write};
use std::str;
use xmltree::Element;

fn escape_low(c: u8) -> Option<&'static str> {
    match c {
        b'&' => Some("&amp;"),
        b'\'' => Some("&apos;"),
        b'"' => Some("&quot;"),
        b'<' => Some("&lt;"),
        b'>' => Some("&gt;"),
        _ => None,
    }
}

fn unicode_escape_replace(cap: &regex::Captures) -> String {
    let m = cap.get(0).unwrap();
    assert_eq!(m.as_str().chars().count(), 1,);
    let c = m.as_str().chars().next().unwrap();
    if m.as_str().len() == 1 {
        if let Some(ret) = escape_low(m.as_str().as_bytes()[0]) {
            return ret.to_string();
        }
    }
    format!("&#{};", c as u32)
}

fn utf8_escape_replace(cap: &regex::bytes::Captures) -> Vec<u8> {
    let m = cap.get(0).unwrap().as_bytes();
    if m.len() == 1 {
        if let Some(ret) = escape_low(m[0]) {
            return ret.as_bytes().to_vec();
        }
    }
    let utf8 = str::from_utf8(m).unwrap();
    utf8.chars()
        .map(|c| format!("&#{};", c as u64).into_bytes())
        .collect::<Vec<Vec<u8>>>()
        .concat()
}

pub fn encode_and_escape_string(text: &str) -> String {
    regex_replace_all!(r#"[&<>'"\u{007f}-\u{ffff}]"#, text, unicode_escape_replace).into_owned()
}

pub fn encode_and_escape_bytes(data: &[u8]) -> String {
    let bytes =
        regex_replace_all!(r#"(?-u)[&<>'"]|[\x7f-\xff]+"#B, data, utf8_escape_replace).into_owned();
    String::from_utf8_lossy(bytes.as_slice()).to_string()
}

fn escape_invalid_char(c: char) -> String {
    if c == '\t' || c == '\n' || c == '\r' || c == '\x7f' {
        c.to_string()
    } else if c.is_ascii_control()
        || (c as u32) > 0xD7FF && (c as u32) < 0xE000
        || (c as u32) > 0xFFFD && (c as u32) < 0x10000
    {
        format!("\\x{:02x}", c as u32)
    } else {
        c.to_string()
    }
}

pub fn escape_invalid_chars(message: &str) -> String {
    message
        .chars()
        .map(escape_invalid_char)
        .collect::<Vec<String>>()
        .join("")
}

fn unpack_revision_properties(elt: &xmltree::Element) -> Result<HashMap<String, Vec<u8>>, Error> {
    if let Some(props_elt) = elt.get_child("properties") {
        let mut properties = HashMap::new();
        for child in props_elt.children.iter() {
            let child = child.as_element().ok_or_else(|| {
                Error::DecodeError(format!("bad tag under properties list: {:?}", child))
            })?;
            if child.name != "property" {
                return Err(Error::DecodeError(format!(
                    "bad tag under properties list: {:?}",
                    child
                )));
            }
            let name = child.attributes.get("name").ok_or_else(|| {
                Error::DecodeError("property element missing name attribute".to_owned())
            })?;
            let value = child
                .get_text()
                .map_or_else(Vec::new, |s| s.as_bytes().to_vec());
            properties.insert(name.clone(), value);
        }
        Ok(properties)
    } else {
        Ok(HashMap::new())
    }
}

// TODO(jelmer): Move this to somewhere more central?
fn surrogate_escape(b: u8) -> Vec<u8> {
    let hi = 0xDC80 + ((b >> 4) as u32);
    let lo = 0xDC00 + ((b & 0x0F) as u32);
    let mut result = Vec::new();
    result.extend_from_slice(&hi.to_be_bytes());
    result.extend_from_slice(&lo.to_be_bytes());
    result
}

fn utf8_encode_surrogate(codepoint: u32) -> Vec<u8> {
    let mut result = Vec::new();
    if codepoint < 0x80 {
        result.push(codepoint as u8);
    } else if codepoint < 0x800 {
        result.push(((codepoint >> 6) & 0x1F) as u8 | 0xC0);
        result.push((codepoint & 0x3F) as u8 | 0x80);
    } else if codepoint < 0x10000 {
        result.push(((codepoint >> 12) & 0x0F) as u8 | 0xE0);
        result.push(((codepoint >> 6) & 0x3F) as u8 | 0x80);
        result.push((codepoint & 0x3F) as u8 | 0x80);
    } else if codepoint < 0x110000 {
        result.push(((codepoint >> 18) & 0x07) as u8 | 0xF0);
        result.push(((codepoint >> 12) & 0x3F) as u8 | 0x80);
        result.push(((codepoint >> 6) & 0x3F) as u8 | 0x80);
        result.push((codepoint & 0x3F) as u8 | 0x80);
    } else {
        panic!("Invalid codepoint: {}", codepoint);
    }
    result
}

fn decode_pep838<F, G>(bytes: &[u8], surrogate_fn: F, other_fn: G) -> String
where
    F: Fn(u32) -> String,
    G: Fn(char) -> String,
{
    let mut result = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        let byte = bytes[i];
        if byte & 0x80 == 0 {
            // single-byte character
            result.push(other_fn(byte as char));
            i += 1;
        } else if byte & 0xE0 == 0xC0 {
            // two-byte character
            if i + 1 < bytes.len() {
                let c = (((byte & 0x1F) as u32) << 6) | ((bytes[i + 1] & 0x3F) as u32);
                result.push(other_fn(char::from_u32(c).unwrap()));
            } else {
                result.push(other_fn('\u{FFFD}'));
            }
            i += 2;
        } else if byte & 0xF0 == 0xE0 {
            // three-byte character
            if i + 2 < bytes.len() {
                let c = (((byte & 0x0F) as u32) << 12)
                    | (((bytes[i + 1] & 0x3F) as u32) << 6)
                    | ((bytes[i + 2] & 0x3F) as u32);
                result.push(other_fn(char::from_u32(c).unwrap()));
            } else {
                result.push(other_fn('\u{FFFD}'));
            }
            i += 3;
        } else if byte & 0xF8 == 0xF0 {
            // four-byte character
            if i + 3 < bytes.len() {
                let high = ((byte & 0x07) as u16) << 2 | ((bytes[i + 1] & 0x30) >> 4) as u16;
                let low = ((bytes[i + 1] & 0x0F) as u16) << 6 | (bytes[i + 2] & 0x3F) as u16;
                result.push(surrogate_fn(((high as u32) << 16) | (low as u32)));
                i += 4;
            } else {
                result.push(other_fn('\u{FFFD}'));
                i += 1;
            }
        } else {
            // invalid character
            result.push(other_fn('\u{FFFD}'));
            i += 1;
        }
    }
    result.concat()
}

impl<T: XMLRevisionSerializer> RevisionSerializer for T {
    fn format_name(&self) -> &'static str {
        self.format_num()
    }

    fn squashes_xml_invalid_characters(&self) -> bool {
        true
    }

    fn read_revision(&self, file: &mut dyn Read) -> Result<Revision, Error> {
        let element = Element::parse(file)
            .map_err(|e| Error::DecodeError(format!("XML parse error: {}", e)))?;
        self.unpack_revision(element)
    }

    fn read_revision_from_string(&self, text: &[u8]) -> Result<Revision, Error> {
        let mut cursor = std::io::Cursor::new(text);
        self.read_revision(&mut cursor)
    }

    fn write_revision_to_lines(
        &self,
        rev: &Revision,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>>> {
        let buf = self.write_revision_to_string(rev);

        if let Ok(buf) = buf {
            let cursor = std::io::Cursor::new(buf);
            let mut reader = std::io::BufReader::new(cursor);
            Box::new(std::iter::from_fn(move || {
                let mut line = Vec::new();
                match reader.read_until(b'\n', &mut line) {
                    Ok(0) => None,
                    Ok(_) => Some(Ok(line)),
                    Err(e) => Some(Err(Error::IOError(e))),
                }
            }))
        } else {
            Box::new(std::iter::once(Err(Error::EncodeError(
                "Failed to write revision to string".to_string(),
            ))))
        }
    }

    fn write_revision_to_string(&self, rev: &Revision) -> Result<Vec<u8>, Error> {
        let mut buf = Vec::new();
        buf.write_all(b"<revision ")?;

        if let Some(ref committer) = rev.committer {
            buf.write_all(
                format!(
                    "committer=\"{}\" ",
                    encode_and_escape_string(committer.as_str())
                )
                .as_bytes(),
            )?;
        }

        buf.write_all(format!("format=\"{}\" ", self.format_name()).as_bytes())?;

        if let Some(ref inventory_sha1) = rev.inventory_sha1 {
            buf.write_all(
                format!(
                    "inventory_sha1=\"{}\" ",
                    encode_and_escape_bytes(inventory_sha1.as_slice())
                )
                .as_bytes(),
            )?;
        }

        buf.write_all(
            format!(
                "revision_id=\"{}\" timestamp=\"{:.3}\"",
                encode_and_escape_bytes(rev.revision_id.as_bytes()),
                rev.timestamp,
            )
            .as_bytes(),
        )?;

        if let Some(timezone) = rev.timezone {
            buf.write_all(format!(" timezone=\"{}\"", timezone).as_bytes())?;
        }

        buf.write_all(b">\n")?;

        let message = encode_and_escape_string(escape_invalid_chars(rev.message.as_str()).as_str());
        buf.write_all(format!("<message>{}</message>\n", message).as_bytes())?;

        if !rev.parent_ids.is_empty() {
            buf.write_all(b"<parents>\n")?;
            for parent_id in &rev.parent_ids {
                if parent_id.is_reserved() {
                    panic!("reserved revision id used as parent: {}", parent_id);
                }
                buf.write_all(
                    format!(
                        "<revision_ref revision_id=\"{}\" />\n",
                        encode_and_escape_bytes(parent_id.as_bytes())
                    )
                    .as_bytes(),
                )?;
            }
            buf.write_all(b"</parents>\n")?;
        }

        if !rev.properties.is_empty() {
            buf.write_all(b"<properties>")?;
            let mut sorted_keys: Vec<_> = rev.properties.keys().collect();
            sorted_keys.sort();
            for prop_name in sorted_keys {
                let prop_value = rev.properties.get(prop_name).unwrap();
                if !prop_value.is_empty() {
                    buf.write_all(
                        format!(
                            "<property name=\"{}\">",
                            encode_and_escape_string(prop_name)
                        )
                        .as_bytes(),
                    )?;
                    let prop_value = decode_pep838(
                        prop_value,
                        |c| {
                            utf8_encode_surrogate(c)
                                .iter()
                                .map(|x| format!("\\x{:02x}", *x as u32))
                                .collect()
                        },
                        escape_invalid_char,
                    );
                    buf.write_all(encode_and_escape_string(prop_value.as_str()).as_bytes())?;
                    buf.write_all(b"</property>\n")?;
                } else {
                    buf.write_all(
                        format!(
                            "<property name=\"{}\" />\n",
                            encode_and_escape_string(prop_name)
                        )
                        .as_bytes(),
                    )?;
                }
            }
            buf.write_all(b"</properties>\n")?;
        }

        buf.write_all(b"</revision>\n")?;

        Ok(buf)
    }
}

pub trait XMLRevisionSerializer: RevisionSerializer {
    fn format_num(&self) -> &'static str;

    fn unpack_revision(&self, document: xmltree::Element) -> Result<Revision, Error> {
        if document.name != "revision" {
            return Err(Error::DecodeError(format!(
                "expected revision element, got {}",
                document.name
            )));
        }
        if let Some(format) = document.attributes.get("format") {
            if format != self.format_num() {
                return Err(Error::DecodeError(format!(
                    "invalid format version {} on revision",
                    format
                )));
            }
        }

        let parents_ids = document
            .get_child("parents")
            .map_or_else(std::vec::Vec::new, |e| {
                e.children
                    .iter()
                    .filter_map(|n| n.as_element())
                    .map(|c| RevisionId::from(c.attributes.get("revision_id").unwrap().as_bytes()))
                    .collect()
            });

        let timezone = document
            .attributes
            .get("timezone")
            .map_or_else(|| None, |v| Some(v.parse::<i32>().unwrap()));

        let message = document.get_child("message").map_or_else(
            || "".to_string(),
            |e| {
                e.get_text()
                    .map_or_else(|| "".to_owned(), |t| t.to_string())
            },
        );

        let revision_id = RevisionId::from(
            document
                .attributes
                .get("revision_id")
                .ok_or_else(|| {
                    Error::EncodeError("revision element missing revision_id attribute".to_owned())
                })?
                .as_bytes(),
        );

        let committer = document.attributes.get("committer").map(|s| s.to_owned());

        let properties = unpack_revision_properties(&document)?;

        let inventory_sha1 = document
            .attributes
            .get("inventory_sha1")
            .map(|s| s.as_bytes().to_vec());

        let timestamp = document
            .attributes
            .get("timestamp")
            .ok_or_else(|| {
                Error::EncodeError("revision element missing timestamp attribute".to_owned())
            })?
            .parse::<f64>()
            .unwrap();

        Ok(Revision::new(
            revision_id,
            parents_ids,
            committer,
            message,
            properties,
            inventory_sha1,
            timestamp,
            timezone,
        ))
    }
}

pub struct XMLRevisionSerializer8;

impl XMLRevisionSerializer for XMLRevisionSerializer8 {
    fn format_num(&self) -> &'static str {
        "8"
    }
}

pub struct XMLRevisionSerializer5;

impl XMLRevisionSerializer for XMLRevisionSerializer5 {
    fn format_num(&self) -> &'static str {
        "5"
    }
}
