use regex::Regex;
use std::io::Write;
use std::iter::Iterator;
use std::collections::HashMap;
use std::result::Result;
use std::str;
use std::io::BufRead;


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

pub struct RioReader<'a, R: Iterator<Item = Result<Vec<u8>, std::io::Error>>> {
    from_file: &'a mut R,
}

impl<'a, R: Iterator<Item = Result<Vec<u8>, std::io::Error>>> RioReader<'a, R> {
    pub fn new(from_file: &'a mut R) -> Self {
        RioReader { from_file }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Stanza {
    items: Vec<(String, StanzaValue)>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum StanzaValue {
    String(String),
    Stanza(Box<Stanza>),
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

    pub fn eq(&self, other: &Stanza) -> bool {
        if self.len() != other.len() {
            return false;
        }
        for (tag, value) in &self.items {
            let other_value = other.get(tag);
            if other_value.is_none() {
                return false;
            }
            if value != other_value.unwrap() {
                return false;
            }
        }
        true
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn iter_pairs(&self) -> impl Iterator<Item = (&str, &StanzaValue)> {
        self.items
            .iter()
            .map(|(tag, value)| (tag.as_str(), value))
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
            to_file.write_all(b"\n")?;
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

pub fn read_stanza<T: BufRead>(line_iter: &mut std::io::Lines<T>) -> Option<Stanza> {
    let mut stanza = Stanza::new();
    let mut tag: Option<String> = None;
    let mut accum_value: Option<String> = None;

    for line in line_iter {
        let line_str = line.unwrap();
        if line_str.is_empty() {
            break;
        }
        if line_str == "\n" {
            break;
        }
        let real_l = line_str.to_string();
        if line_str.chars().next().unwrap() == '\t' {
            if tag.is_none() {
                panic!("invalid continuation line {:?}", real_l);
            }
            let mut value = String::new();
            value.push_str("\n");
            value.push_str(&line_str[1..line_str.len()-1]);
            if let Some(x) = &mut accum_value {
                x.push_str(&value);
            } else {
                accum_value = Some(value);
            }
        } else {
            if let Some(x) = &tag {
                stanza.add(x.to_string(), StanzaValue::String(accum_value.unwrap_or_default()));
            }
            let parts: Vec<&str> = line_str.splitn(2, ": ").collect();
            let tag_str = parts[0].to_string();
            if !valid_tag(&tag_str) {
                panic!("invalid rio tag {:?}", tag_str);
            }
            tag = Some(tag_str);
            accum_value = Some(parts[1].to_string());
        }
    }

    if let Some(x) = &tag {
        stanza.add(x.to_string(), StanzaValue::String(accum_value.unwrap_or_default()));
        return Some(stanza);
    } else {
        return None;
    }
}

pub fn read_stanzas<T: BufRead>(line_iter: &mut std::io::Lines<T>) -> Vec<Stanza> {
    let mut stanzas = vec![];
    loop {
        if let Some(s) = read_stanza(line_iter) {
            stanzas.push(s);
        } else {
            break;
        }
    }
    stanzas
}
