use std::fs::File;
use std::io::{Error, Read};
use std::path::Path;

/// Return false if the supplied lines contain NULs.
///
/// Only the first 1024 characters are checked.
pub fn check_text_lines<I>(lines: I) -> bool
where
    I: IntoIterator<Item = Vec<u8>>,
{
    let mut buffer = [0u8; 1024];
    let mut offset = 0;
    for line in lines.into_iter() {
        if line.iter().any(|&c| c == 0) {
            return false;
        }
        if offset + line.len() > 1024 {
            break;
        }
        buffer[offset..offset + line.len()].copy_from_slice(&line);
        offset += line.len();
    }
    if buffer[..offset].iter().any(|&c| c == 0) {
        return false;
    }
    true
}

/// Check whether the supplied path is a text, not binary file.
///
/// Raise BinaryFile if a NUL occurs in the first 1024 bytes.
pub fn check_text_path<P: AsRef<Path>>(path: P) -> Result<bool, Error> {
    let file = File::open(path)?;
    let mut buffer = Vec::new();
    let mut handle = file.take(1024);
    handle.read_to_end(&mut buffer)?;

    Ok(buffer.iter().all(|&byte| byte != 0))
}
