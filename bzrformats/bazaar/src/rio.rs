/// The RIO file format
///
/// Copyright (C) 2023 Jelmer Vernooij <jelmer@jelmer.uk>
///
/// Based on the Python implementation:
/// Copyright (C) 2005 Canonical Ltd.
///
/// \subsection{\emph{rio} - simple text metaformat}
///
/// \emph{r} stands for `restricted', `reproducible', or `rfc822-like'.
///
/// The stored data consists of a series of \emph{stanzas}, each of which contains
/// \emph{fields} identified by an ascii name, with Unicode or string contents.
/// The field tag is constrained to alphanumeric characters.
/// There may be more than one field in a stanza with the same name.
///
/// The format itself does not deal with character encoding issues, though
/// the result will normally be written in Unicode.
///
/// The format is intended to be simple enough that there is exactly one character
/// stream representation of an object and vice versa, and that this relation
/// will continue to hold for future versions of bzr.
use regex::Regex;
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::iter::Iterator;
use std::result::Result;
use std::str;

#[derive(Debug)]
pub enum Error {
    Io(std::io::Error),
    InvalidTag(String),
    ContinuationLineWithoutTag,
    TagValueSeparatorNotFound(Vec<u8>),
    Other(String),
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}

/// Verify whether a tag is validly formatted
pub fn valid_tag(tag: &str) -> bool {
    lazy_static::lazy_static! {
        static ref RE: Regex = Regex::new(r"^[-a-zA-Z0-9_]+$").unwrap();
    }
    RE.is_match(tag)
}

pub struct RioWriter<W: Write> {
    soft_nl: bool,
    to_file: W,
}

impl<W: Write> RioWriter<W> {
    pub fn new(to_file: W) -> Self {
        RioWriter {
            soft_nl: false,
            to_file,
        }
    }

    pub fn write_stanza(&mut self, stanza: &Stanza) -> Result<(), std::io::Error> {
        if self.soft_nl {
            self.to_file.write_all(b"\n")?;
        }
        stanza.write(&mut self.to_file)?;
        self.soft_nl = true;
        Ok(())
    }
}

pub struct RioReader<R: BufRead> {
    from_file: R,
}

impl<R: BufRead> RioReader<R> {
    pub fn new(from_file: R) -> Self {
        RioReader { from_file }
    }

    fn read_stanza(&mut self) -> Result<Option<Stanza>, Error> {
        read_stanza_file(&mut self.from_file)
    }

    pub fn iter(&mut self) -> RioReaderIter<R> {
        RioReaderIter { reader: self }
    }
}

pub struct RioReaderIter<'a, R: BufRead> {
    reader: &'a mut RioReader<R>,
}

impl<R: BufRead> Iterator for RioReaderIter<'_, R> {
    type Item = Result<Option<Stanza>, Error>;

    fn next(&mut self) -> Option<Self::Item> {
        match self.reader.read_stanza() {
            Ok(stanza) => stanza.map(|s| Ok(Some(s))),
            Err(e) => Some(Err(e)),
        }
    }
}

#[derive(Debug, Clone)]
pub struct Stanza {
    items: Vec<(String, StanzaValue)>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum StanzaValue {
    String(String),
    Stanza(Box<Stanza>),
}

impl PartialEq for Stanza {
    fn eq(&self, other: &Self) -> bool {
        if self.len() != other.len() {
            return false;
        }
        for (self_item, other_item) in self.items.iter().zip(other.items.iter()) {
            let (self_tag, self_value) = self_item;
            let (other_tag, other_value) = other_item;
            if self_tag != other_tag {
                return false;
            }
            if self_value != other_value {
                return false;
            }
        }
        true
    }
}

impl Stanza {
    pub fn new() -> Stanza {
        Stanza { items: vec![] }
    }

    pub fn from_pairs(pairs: Vec<(String, StanzaValue)>) -> Stanza {
        Stanza { items: pairs }
    }

    pub fn add(&mut self, tag: String, value: StanzaValue) -> Result<(), Error> {
        if !valid_tag(&tag) {
            return Err(Error::InvalidTag(tag));
        }
        self.items.push((tag, value));
        Ok(())
    }

    pub fn contains(&self, find_tag: &str) -> bool {
        for (tag, _) in &self.items {
            if tag == find_tag {
                return true;
            }
        }
        false
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    pub fn iter_pairs(&self) -> impl Iterator<Item = (&str, &StanzaValue)> {
        self.items.iter().map(|(tag, value)| (tag.as_str(), value))
    }

    pub fn to_bytes_lines(&self) -> Vec<Vec<u8>> {
        self.to_lines()
            .iter()
            .map(|s| s.as_bytes().to_vec())
            .collect()
    }

    pub fn to_lines(&self) -> Vec<String> {
        let mut result = Vec::new();
        for (text_tag, text_value) in &self.items {
            let tag = text_tag.as_bytes();
            let value = match text_value {
                StanzaValue::String(val) => val.to_string(),
                StanzaValue::Stanza(val) => val.to_string(),
            };
            if value.is_empty() {
                result.push(format!("{}: \n", String::from_utf8_lossy(tag)));
            } else if value.contains('\n') {
                let mut val_lines = value.split('\n');
                if let Some(first_line) = val_lines.next() {
                    result.push(format!(
                        "{}: {}\n",
                        String::from_utf8_lossy(tag),
                        first_line
                    ));
                }
                for line in val_lines {
                    result.push(format!("\t{}\n", line));
                }
            } else {
                result.push(format!("{}: {}\n", String::from_utf8_lossy(tag), value));
            }
        }
        result
    }

    pub fn to_string(&self) -> String {
        self.to_lines().join("")
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        self.to_string().into_bytes()
    }

    pub fn write<T: Write>(&self, to_file: &mut T) -> std::io::Result<()> {
        for line in self.to_lines() {
            to_file.write_all(line.as_bytes())?;
        }
        Ok(())
    }

    pub fn get(&self, tag: &str) -> Option<&StanzaValue> {
        for (t, v) in &self.items {
            if t == tag {
                return Some(v);
            }
        }

        None
    }

    pub fn get_all(&self, tag: &str) -> Vec<&StanzaValue> {
        self.items
            .iter()
            .filter(|(t, _)| t == tag)
            .map(|(_, v)| v)
            .collect()
    }

    pub fn as_dict(&self) -> HashMap<String, StanzaValue> {
        let mut d = HashMap::new();
        for (tag, value) in &self.items {
            d.insert(tag.clone(), value.clone());
        }
        d
    }
}

impl std::default::Default for Stanza {
    fn default() -> Self {
        Stanza::new()
    }
}

pub fn read_stanza_file(line_iter: &mut dyn BufRead) -> Result<Option<Stanza>, Error> {
    read_stanza(line_iter.split(b'\n').map(|l| {
        let mut vec: Vec<u8> = l?;
        vec.push(b'\n');
        Ok(vec)
    }))
}

fn trim_newline(vec: &mut Vec<u8>) {
    if let Some(last_non_newline) = vec.iter().rposition(|&b| b != b'\n' && b != b'\r') {
        vec.truncate(last_non_newline + 1);
    } else {
        vec.clear();
    }
}

pub fn read_stanza<I>(lines: I) -> Result<Option<Stanza>, Error>
where
    I: Iterator<Item = Result<Vec<u8>, Error>>,
{
    let mut stanza = Stanza::new();
    let mut tag: Option<String> = None;
    let mut accum_value: Option<Vec<String>> = None;

    for bline in lines {
        let mut line = bline?;
        trim_newline(&mut line);
        if line.is_empty() {
            break; // end of stanza
        } else if line.starts_with(b"\t") {
            // continues previous value
            if tag.is_none() {
                return Err(Error::ContinuationLineWithoutTag);
            }
            if let Some(accum_value) = accum_value.as_mut() {
                let extra = String::from_utf8(line[1..line.len()].to_owned()).unwrap();
                accum_value.push("\n".to_string() + &extra);
            }
        } else {
            // new tag:value line
            if let Some(tag) = tag.take() {
                let value = accum_value.take().map_or_else(String::new, |v| v.join(""));
                stanza.add(tag, StanzaValue::String(value))?;
            }
            let colon_index = match line.windows(2).position(|window| window.eq(b": ")) {
                Some(index) => index,
                None => return Err(Error::TagValueSeparatorNotFound(line)),
            };
            let tagname = String::from_utf8(line[0..colon_index].to_owned()).unwrap();
            if !valid_tag(&tagname) {
                return Err(Error::InvalidTag(tagname));
            }
            tag = Some(tagname);
            let value = String::from_utf8(line[colon_index + 2..line.len()].to_owned()).unwrap();
            accum_value = Some(vec![value]);
        }
    }
    if let Some(tag) = tag {
        let value = accum_value.take().map_or_else(String::new, |v| v.join(""));
        stanza.add(tag, StanzaValue::String(value))?;
        Ok(Some(stanza))
    } else {
        // didn't see any content
        Ok(None)
    }
}

pub fn read_stanzas(line_iter: &mut dyn BufRead) -> Result<Vec<Stanza>, Error> {
    let mut stanzas = vec![];
    while let Some(s) = read_stanza_file(line_iter)? {
        stanzas.push(s);
    }
    Ok(stanzas)
}

pub fn rio_iter(
    stanzas: impl IntoIterator<Item = Stanza>,
    header: Option<Vec<u8>>,
) -> impl Iterator<Item = Vec<u8>> {
    let mut lines = Vec::new();
    if let Some(header) = header {
        let mut header = header;
        header.push(b'\n');
        lines.push(header);
    }
    let mut first_stanza = true;
    for stanza in stanzas {
        if !first_stanza {
            lines.push(b"\n".to_vec());
        }
        lines.push(stanza.to_bytes());
        first_stanza = false;
    }
    lines.into_iter()
}

#[cfg(test)]
mod tests {
    use super::valid_tag;
    use super::{read_stanza, Stanza, StanzaValue};

    #[test]
    fn test_valid_tag() {
        assert!(valid_tag("name"));
        assert!(!valid_tag("!name"));
    }

    #[test]
    fn test_stanza() {
        let mut s = Stanza::new();
        s.add("number".to_string(), StanzaValue::String("42".to_string()))
            .unwrap();
        s.add("name".to_string(), StanzaValue::String("fred".to_string()))
            .unwrap();

        assert!(s.contains("number"));
        assert!(!s.contains("color"));
        assert!(!s.contains("42"));

        // Verify that the s.get() function works
        assert_eq!(
            s.get("number"),
            Some(&StanzaValue::String("42".to_string()))
        );
        assert_eq!(
            s.get("name"),
            Some(&StanzaValue::String("fred".to_string()))
        );
        assert_eq!(s.get("color"), None);

        // Verify that iter_pairs() works
        assert_eq!(s.iter_pairs().count(), 2);
    }

    #[test]
    fn test_eq() {
        let mut s = Stanza::new();
        s.add("number".to_string(), StanzaValue::String("42".to_string()))
            .unwrap();
        s.add("name".to_string(), StanzaValue::String("fred".to_string()))
            .unwrap();

        let mut t = Stanza::new();
        t.add("number".to_string(), StanzaValue::String("42".to_string()))
            .unwrap();
        t.add("name".to_string(), StanzaValue::String("fred".to_string()))
            .unwrap();

        assert_eq!(s, s);
        assert_eq!(s, t);
        t.add("color".to_string(), StanzaValue::String("red".to_string()))
            .unwrap();

        assert_ne!(s, t);
    }

    #[test]
    fn test_empty_value() {
        let s = Stanza::from_pairs(vec![(
            "empty".to_string(),
            StanzaValue::String("".to_string()),
        )]);
        assert_eq!(s.to_string(), "empty: \n");
    }

    #[test]
    fn test_to_lines() {
        let s = Stanza::from_pairs(vec![
            ("number".to_string(), StanzaValue::String("42".to_string())),
            ("name".to_string(), StanzaValue::String("fred".to_string())),
            (
                "field-with-newlines".to_string(),
                StanzaValue::String("foo\nbar\nblah".to_string()),
            ),
            (
                "special-characters".to_string(),
                StanzaValue::String(" \t\r\\\n ".to_string()),
            ),
        ]);
        assert_eq!(
            s.to_lines(),
            vec![
                "number: 42\n".to_string(),
                "name: fred\n".to_string(),
                "field-with-newlines: foo\n".to_string(),
                "\tbar\n".to_string(),
                "\tblah\n".to_string(),
                "special-characters:  \t\r\\\n".to_string(),
                "\t \n".to_string()
            ],
        );
    }

    #[test]
    fn test_read_stanza() {
        let lines = b"number: 42
name: fred
field-with-newlines: foo
\tbar
\tblah

"
        .split(|c| *c == b'\n')
        .map(|s| s.to_vec());
        let s = read_stanza(lines.map(Ok)).unwrap().unwrap();
        let expected = Stanza::from_pairs(vec![
            ("number".to_string(), StanzaValue::String("42".to_string())),
            ("name".to_string(), StanzaValue::String("fred".to_string())),
            (
                "field-with-newlines".to_string(),
                StanzaValue::String("foo\nbar\nblah".to_string()),
            ),
        ]);
        assert_eq!(s, expected);
    }
}
