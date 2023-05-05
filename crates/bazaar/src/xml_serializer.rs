use std::str;

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
    eprintln!("m: {:?}", cap);
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

pub fn encode_and_escape_string(text: &str) -> Vec<u8> {
    UNICODE_RE
        .replace_all(text, unicode_escape_replace)
        .as_bytes()
        .to_vec()
}

pub fn encode_and_escape_bytes(data: &[u8]) -> Vec<u8> {
    UTF8_RE.replace_all(data, utf8_escape_replace).to_vec()
}

pub fn escape_invalid_chars(message: Option<&str>) -> (Option<String>, usize) {
    if let Some(msg) = message {
        let escaped = msg
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
            .join("");

        (Some(escaped), msg.len())
    } else {
        (None, 0)
    }
}
