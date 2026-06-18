use lazy_static::lazy_static;
use regex::bytes::Regex;
use std::num::ParseIntError;

pub enum Error {
    BinaryFiles(Vec<u8>, Vec<u8>),
    PatchSyntax(&'static str, Vec<u8>),
    MalformedPatchHeader(&'static str, Vec<u8>),
}

pub fn get_patch_names<T: Iterator<Item = Vec<u8>>>(
    mut iter_lines: T,
) -> Result<((Vec<u8>, Option<Vec<u8>>), (Vec<u8>, Option<Vec<u8>>)), Error> {
    lazy_static! {
        static ref BINARY_FILES_RE: Regex =
            Regex::new(r"^Binary files (.+) and (.+) differ").unwrap();
    }

    let line = iter_lines
        .next()
        .ok_or_else(|| Error::PatchSyntax("No input", vec![]))?;

    let (orig_name, orig_ts) = match BINARY_FILES_RE.captures(&line) {
        Some(captures) => {
            let orig_name = captures.get(1).unwrap().as_bytes().to_vec();
            let orig_ts = captures.get(2).unwrap().as_bytes().to_vec();
            return Err(Error::BinaryFiles(orig_name, orig_ts));
        }
        None => {
            let orig_name = line
                .strip_prefix(b"--- ")
                .ok_or_else(|| Error::MalformedPatchHeader("No orig name", line.to_vec()))?
                .strip_suffix(b"\n")
                .ok_or_else(|| Error::PatchSyntax("missing newline", line.to_vec()))?;
            let (orig_name, orig_ts) = match orig_name.split(|&c| c == b'\t').collect::<Vec<_>>()[..]
            {
                [name, ts] => (name.to_vec(), Some(ts.to_vec())),
                [name] => (name.to_vec(), None),
                _ => return Err(Error::MalformedPatchHeader("No orig line", line.to_vec())),
            };
            (orig_name, orig_ts)
        }
    };

    let line = iter_lines
        .next()
        .ok_or_else(|| Error::PatchSyntax("No input", vec![]))?;

    let (mod_name, mod_ts) = match line.strip_prefix(b"+++ ") {
        Some(line) => {
            let mod_name = line
                .strip_suffix(b"\n")
                .ok_or_else(|| Error::PatchSyntax("missing newline", line.to_vec()))?;
            let (mod_name, mod_ts) = match mod_name.split(|&c| c == b'\t').collect::<Vec<_>>()[..] {
                [name, ts] => (name.to_vec(), Some(ts.to_vec())),
                [name] => (name.to_vec(), None),
                _ => return Err(Error::PatchSyntax("Invalid mod name", line.to_vec())),
            };
            (mod_name, mod_ts)
        }
        None => return Err(Error::MalformedPatchHeader("No mod line", line.to_vec())),
    };

    Ok(((orig_name, orig_ts), (mod_name, mod_ts)))
}

pub const NO_NL: &[u8] = b"\\ No newline at end of file\n";

pub fn iter_lines_handle_nl<I>(mut iter_lines: I) -> impl Iterator<Item = Vec<u8>>
where
    I: Iterator<Item = Vec<u8>>,
{
    let mut last_line: Option<Vec<u8>> = None;
    std::iter::from_fn(move || {
        for line in iter_lines.by_ref() {
            if line == NO_NL {
                if let Some(last) = last_line.as_mut() {
                    assert!(last.ends_with(b"\n"));
                    last.truncate(last.len() - 1);
                } else {
                    panic!("No newline indicator without previous line");
                }
            } else {
                if let Some(last) = last_line.take() {
                    last_line = Some(line);
                    return Some(last);
                }
                last_line = Some(line);
            }
        }
        last_line.take()
    })
}

/// Parse a patch range, handling the "1" special-case
pub fn parse_range(textrange: &str) -> Result<(i32, i32), ParseIntError> {
    let tmp: Vec<&str> = textrange.split(',').collect();
    let (pos, brange) = if tmp.len() == 1 {
        (tmp[0], "1")
    } else {
        (tmp[0], tmp[1])
    };
    let pos = pos.parse::<i32>()?;
    let range = brange.parse::<i32>()?;
    Ok((pos, range))
}

/// Find the index of the first character that differs between two texts
pub fn difference_index(atext: &[u8], btext: &[u8]) -> Option<usize> {
    let length = atext.len().min(btext.len());
    (0..length).find(|&i| atext[i] != btext[i])
}
