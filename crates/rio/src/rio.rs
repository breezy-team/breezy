
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
use std::io::{BufRead,Write,BufReader};
use std::iter::Iterator;
use std::collections::HashMap;
use std::result::Result;
use std::str;
use std::borrow::Cow;

/// Verify whether a tag is validly formatted
pub fn valid_tag(tag: &str) -> bool {
    lazy_static! {
        static ref RE: Regex = Regex::new(r"^[-a-zA-Z0-9_]+$").unwrap();
    }
    RE.is_match(tag)
}

pub struct RioWriter<'a, W: Write> {
    soft_nl: bool,
    to_file: &'a mut W,
}

impl<'a, W: Write> RioWriter<'a, W> {
    pub fn new(to_file: &'a mut W) -> Self {
        RioWriter {
            soft_nl: false,
            to_file,
        }
    }

    pub fn write_stanza(&mut self, stanza: &Stanza) -> Result<(), std::io::Error> {
        if self.soft_nl {
            self.to_file.write_all(b"\n")?;
        }
        stanza.write(self.to_file)?;
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
}

impl<R: BufRead> Iterator for RioReader<R> {
    type Item = Result<Option<Stanza>, std::io::Error>;

    fn next(&mut self) -> Option<Self::Item> {
        match read_stanza(&mut self.from_file) {
            Ok(stanza) => {
                if let Some(s) = stanza {
                    Some(Ok(Some(s)))
                } else {
                    None
                }
            }
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

    pub fn add(&mut self, tag: String, value: StanzaValue) {
        if !valid_tag(&tag) {
            panic!("invalid tag {}", tag);
        }
        self.items.push((tag, value));
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

    pub fn iter_pairs(&self) -> impl Iterator<Item = (&str, &StanzaValue)> {
        self.items
            .iter()
            .map(|(tag, value)| (tag.as_str(), value))
    }

    pub fn to_bytes_lines(&self) -> Vec<Vec<u8>> {
        self.to_lines().iter().map(|s| s.as_bytes().to_vec()).collect()
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
                result.push(format!(
                    "{}: {}\n",
                    String::from_utf8_lossy(tag),
                    value
                ));
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
        self.items.iter()
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

pub fn read_stanza(line_iter: &mut dyn BufRead) -> Result<Option<Stanza>, std::io::Error> {
    let mut stanza = Stanza::new();
    let mut tag: Option<String> = None;
    let mut accum_value: Option<Vec<String>> = None;

    for bline in line_iter.lines() {
        let line = bline?;
        if line.is_empty() {
            break; // end of file
        } else if line == "\n" {
            break; // end of stanza
        } else if line.starts_with("\t") {
            // continues previous value
            if tag.is_none() {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "continuation line without tag",
                ));
            }
            if let Some(accum_value) = accum_value.as_mut() {
                accum_value.push("\n".to_owned() + &line[1..line.len() - 1]);
            }
        } else {
            // new tag:value line
            if let Some(tag) = tag.take() {
                let value = accum_value.take().map_or_else(String::new, |v| v.join(""));
                stanza.add(tag, StanzaValue::String(value));
            }
            let colon_index = match line.find(": ") {
                Some(index) => index,
                None => panic!("tag/value separator not found in line {:?}", line),
            };
            let tag = line[0..colon_index].to_owned();
            if !valid_tag(&tag) {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    format!("invalid tag {}", tag),
                ));
            }
            let value = line[colon_index + 2..line.len() - 1].to_owned();
            accum_value = Some(vec![value]);
        }
    }
    if let Some(tag) = tag {
        let value = accum_value.take().map_or_else(String::new, |v| v.join(""));
        stanza.add(tag, StanzaValue::String(value));
        Ok(Some(stanza))
    } else {
        // didn't see any content
        Ok(None)
    }
}

pub fn read_stanzas(line_iter: &mut dyn BufRead) -> Result<Vec<Stanza>, std::io::Error> {
    let mut stanzas = vec![];
    loop {
        if let Some(s) = read_stanza(line_iter)? {
            stanzas.push(s);
        } else {
            break;
        }
    }
    Ok(stanzas)
}

pub const MAX_RIO_WIDTH: usize = 72;

pub fn to_patch_lines(stanza: &Stanza, max_width: usize) -> Result<Vec<Vec<u8>>, std::io::Error> {
    if max_width <= 6 {
        return Err(std::io::Error::new(std::io::ErrorKind::InvalidInput, "max_width must be greater than 6"));
    }
    let max_rio_width = max_width - 4;
    let mut lines = Vec::new();
    let re = regex::bytes::Regex::new(r"\\").unwrap();
    for pline in stanza.to_bytes_lines() {
        let pline = pline.as_slice();
        for line in pline.split(|c| *c == b'\n').take_while(|c| !c.is_empty()) {
            let line: Cow<[u8]> = re.replace_all(line, |_caps: &regex::bytes::Captures| b"\\\\r");
            let partline = line;
            while !partline.is_empty() {
                let (chunk, rest) = partline.split_at(max_rio_width);
                let (break_index, _break_char) = find_break_index(chunk);
                let (partline_chunk, line_chunk) = chunk.split_at(break_index);
                let partline = partline_chunk;
                let line = if !line_chunk.is_empty() {
                    let mut line_chunk = line_chunk.to_vec();
                    line_chunk.insert(0, b' ');
                    line_chunk
                } else {
                    Vec::new()
                };
                let partline = re.replace_all(partline, |_caps: &regex::bytes::Captures| b"\\\\r").to_vec();
                let mut partline = if !line.is_empty() {
                    [&b"  "[..], partline.as_slice(), &b"\\"[..]].concat()
                } else if partline.ends_with(b" ") {
                    [&partline[..partline.len() - 1], &b"\\ "[..]].concat()
                } else {
                    partline.to_vec()
                };
                partline.insert(0, b'#');
                partline.push(b'\n');
                lines.push(partline.to_vec());
                if line.is_empty() && partline.ends_with(b"\n") && partline.len() < max_width {
                    lines.push(b"#   \n".to_vec());
                }
                if !line.is_empty() {
                    let line = [&line[..1], &partline[3..], &line.as_slice()[1..]].concat();
                    let line = re.replace_all(&line, |_caps: &regex::bytes::Captures| b"\\\\r");
                    let line = [&b"#  "[..], &line[..], &b"\n"[..]].concat();
                    lines.push(line);
                }
                partline = rest.to_vec();
            }
        }
    }
    Ok(lines)
}

fn find_break_index(line: &[u8]) -> (usize, u8) {
    let mut break_index = line.len();
    let mut break_char = b' ';
    if break_index >= 3 && break_char == b' ' {
        break_index = line[..break_index-3].iter().rposition(|&c| c == b' ' || c == b'-')
            .map(|i| i + 1)
            .unwrap_or(break_index);
        break_char = line[break_index-1];
    }
    if break_index >= 3 && break_char == b'-' {
        break_index -= 1;
        break_char = line[break_index-1];
    }
    if break_index >= 3 && break_char == b'/' {
        break_char = line[break_index-1];
    }
    (break_index, break_char)
}


fn patch_stanza_iter(line_iter: &mut dyn BufRead) -> Vec<String> {
    let map = vec![
        (r"\\", r"\"),
        (r"\r", "\r"),
        (r"\\\n", ""),
    ];
    let re = regex::Regex::new(r"\\\S|\r").unwrap();

    let mut last_line: Option<String> = None;
    let mut result = vec![];

    for bline in line_iter.lines() {
        let line = match bline {
            Ok(v) => v,
            Err(_) => return result,
        };
        let mut line = if line.starts_with("# ") {
            line[2..].to_string()
        } else if line.starts_with('#') {
            line[1..].to_string()
        } else {
            continue;
        };
        if let Some(ref mut last) = last_line {
            if line.len() > 2 {
                line = line[2..].to_string();
            }
            last.push_str(&line);
            line = last.clone();
            last_line = None;
        }
        if line.ends_with('\n') {
            let replaced = re.replace_all(&line, |caps: &regex::Captures| {
                for &(ref from, ref to) in &map {
                    if caps[0].as_bytes() == from.as_bytes() {
                        return to.to_string();
                    }
                }
                caps[0].to_string()
            });
            result.push(replaced.to_string());
        } else {
            last_line = Some(line);
        }
    }
    result
}

pub fn read_patch_stanza(line_iter: &mut dyn BufRead) -> Result<Option<Stanza>, std::io::Error> {
    let lines = patch_stanza_iter(line_iter).join("\n").as_bytes().to_vec();
    let mut buffer = BufReader::new(lines.as_slice());
    read_stanza(&mut buffer)
}

pub fn rio_iter(
    stanzas: impl IntoIterator<Item = Stanza>,
    header: Option<Vec<u8>>,
) -> impl Iterator<Item = Vec<u8>> {
    let mut lines = Vec::new();
    if let Some(header) = header {
        let mut header = header.clone();
        header.push(b'\n');
        lines.push(header);
    }
    let first_stanza = true;
    for stanza in stanzas {
        if !first_stanza {
            lines.push(b"\n".to_vec());
        }
        lines.push(stanza.to_bytes());
    }
    lines.into_iter()
}
