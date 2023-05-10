use crate::revision::Revision;
use crate::serializer::{Error, RevisionSerializer};
use crate::RevisionId;
use std::collections::HashMap;
use std::io::Read;
use std::str;
use xmltree::Element;

lazy_static::lazy_static! {
    static ref UTF8_RE: regex::bytes::Regex = regex::bytes::Regex::new(r#"(?-u)[&<>'"]|[\x80-\xff]+"#).unwrap();
    static ref UNICODE_RE: regex::Regex = regex::Regex::new(r#"[&<>'"\u{0080}-\u{ffff}]"#).unwrap();

}

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
    if m.len() == 1 {
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
    UNICODE_RE
        .replace_all(text, unicode_escape_replace)
        .into_owned()
}

pub fn encode_and_escape_bytes(data: &[u8]) -> String {
    let bytes = UTF8_RE.replace_all(data, utf8_escape_replace).into_owned();
    String::from_utf8_lossy(bytes.as_slice()).to_string()
}

pub fn escape_invalid_chars(message: &str) -> String {
    message
        .chars()
        .map(|c| {
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
        })
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

    fn write_revision_to_string(&self, revision: &Revision) -> Result<Vec<u8>, Error> {
        let mut lines = Vec::new();
        for line in self.write_revision_to_lines(revision) {
            lines.push(line?);
        }
        Ok(lines.concat())
    }

    fn write_revision_to_lines(
        &self,
        rev: &Revision,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>>> {
        let mut lines = Vec::new();
        // For the XML format, we need to write them as Unicode rather than as
        // utf-8 strings. So that cElementTree can handle properly escaping
        // them.
        let mut el = "<revision ".to_string();

        if let Some(ref committer) = rev.committer {
            el += &format!(
                "committer=\"{}\" ",
                encode_and_escape_string(committer.as_str())
            );
        }

        el += &format!("format=\"{}\" ", self.format_name());

        if let Some(ref inventory_sha1) = rev.inventory_sha1 {
            el += &format!(
                "inventory_sha1=\"{}\" ",
                encode_and_escape_bytes(inventory_sha1.as_slice())
            );
        }

        el += &format!(
            "revision_id=\"{}\" timestamp=\"{:.3}\"",
            encode_and_escape_bytes(rev.revision_id.bytes()),
            rev.timestamp,
        );

        if let Some(timezone) = rev.timezone {
            el += &format!(" timezone=\"{}\"", timezone);
        }

        lines.push((el + ">\n").as_bytes().to_vec());

        let message = encode_and_escape_string(escape_invalid_chars(rev.message.as_str()).as_str());
        lines.extend(
            (format!("<message>{}</message>\n", message))
                .as_bytes()
                .split_inclusive(|&c| c == b'\n')
                .map(|s| s.to_vec()),
        );

        if !rev.parent_ids.is_empty() {
            lines.push(b"<parents>\n".to_vec());
            for parent_id in &rev.parent_ids {
                if parent_id.is_reserved() {
                    panic!("reserved revision id used as parent: {}", parent_id);
                }
                lines.push(
                    format!(
                        "<revision_ref revision_id=\"{}\" />\n",
                        encode_and_escape_bytes(parent_id.bytes())
                    )
                    .as_bytes()
                    .to_vec(),
                );
            }
            lines.push(b"</parents>\n".to_vec());
        }

        if !rev.properties.is_empty() {
            lines.push(b"<properties>".to_vec());
            let mut sorted_keys: Vec<_> = rev.properties.keys().collect();
            sorted_keys.sort();
            for prop_name in sorted_keys {
                let prop_value = rev.properties.get(prop_name).unwrap();
                if !prop_value.is_empty() {
                    let prop_value_utf8 = String::from_utf8(prop_value.clone()).unwrap();
                    let proplines: Vec<Vec<u8>> = format!(
                        "<property name=\"{}\">{}</property>\n",
                        encode_and_escape_string(prop_name),
                        encode_and_escape_string(
                            escape_invalid_chars(prop_value_utf8.as_str()).as_str()
                        )
                    )
                    .as_bytes()
                    .split(|&c| c == b'\n')
                    .map(|s| s.to_vec())
                    .collect();
                    lines.extend(proplines);
                } else {
                    let proplines = [format!(
                        "<property name=\"{}\" />\n",
                        encode_and_escape_string(prop_name)
                    )
                    .as_bytes()
                    .to_vec()];
                    lines.extend(proplines);
                }
            }
            lines.push(b"</properties>\n".to_vec());
        }

        lines.push(b"</revision>\n".to_vec());

        Box::new(lines.into_iter().map(Ok))
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
            || Ok("".to_owned()),
            |e| {
                e.get_text()
                    .map(|s| s.to_string())
                    .ok_or_else(|| Error::DecodeError("message element missing text".to_owned()))
            },
        )?;

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
