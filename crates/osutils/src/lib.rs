use memchr::memchr;
use rand::Rng;
use std::fs::File;
use std::io::Write;

pub fn chunks_to_lines<'a, I, E>(mut chunks: I) -> impl Iterator<Item = Result<Vec<u8>, E>>
where
    I: Iterator<Item = Result<&'a [u8], E>> + 'a,
    E: std::fmt::Debug,
{
    let mut tail: Option<Vec<u8>> = None;

    std::iter::from_fn(move || -> Option<Result<Vec<u8>, E>> {
        loop {
            // See if we can find a line in tail
            if let Some(mut chunk) = tail.take() {
                if let Some(newline) = memchr(b'\n', &chunk) {
                    if newline == chunk.len() - 1 {
                        assert!(!chunk.is_empty());
                        // The chunk ends with a newline, so it contains a single line
                        return Some(Ok(chunk));
                    } else {
                        // The chunk contains multiple lines, so split it into lines
                        let line = chunk[..=newline].to_vec();
                        assert!(!chunk.is_empty());
                        tail = Some(chunk[newline + 1..].to_vec());
                        return Some(Ok(line));
                    }
                } else {
                    if let Some(next_chunk) = chunks.next() {
                        if let Err(e) = next_chunk {
                            return Some(Err(e));
                        }
                        chunk.extend_from_slice(next_chunk.unwrap());
                    } else {
                        assert!(!chunk.is_empty());
                        // We've reached the end of the chunks, so return the last chunk
                        return Some(Ok(chunk));
                    }
                    if !chunk.is_empty() {
                        tail = Some(chunk);
                    }
                }
            } else if let Some(next_chunk) = chunks.next() {
                if let Err(e) = next_chunk {
                    return Some(Err(e));
                }
                let next_chunk = next_chunk.unwrap();
                if !next_chunk.is_empty() {
                    tail = Some(next_chunk.to_vec());
                }
            } else {
                // We've reached the end of the chunks, so return None
                return None;
            }
        }
    })
}

pub fn set_or_unset_env(
    env_variable: &str,
    value: Option<&str>,
) -> Result<Option<String>, std::env::VarError> {
    let orig_val = std::env::var(env_variable);
    let ret: Option<String>;
    if let Err(std::env::VarError::NotPresent) = orig_val {
        ret = None;
        if let Some(value) = value {
            std::env::set_var(env_variable, value);
        }
    } else if let Err(e) = orig_val {
        return Err(e);
    } else {
        assert!(orig_val.is_ok());
        ret = Some(orig_val.unwrap());
        match value {
            None => std::env::remove_var(env_variable),
            Some(val) => std::env::set_var(env_variable, val),
        }
    }
    Ok(ret)
}

const ALNUM: &str = "0123456789abcdefghijklmnopqrstuvwxyz";

pub fn rand_chars(num: usize) -> String {
    let mut rng = rand::thread_rng();
    let mut s = String::new();
    for _ in 0..num {
        let raw_byte = rng.gen_range(0..256);
        s.push(ALNUM.chars().nth(raw_byte % 36).unwrap());
    }
    s
}

#[cfg(unix)]
use nix::sys::stat::{umask, Mode};

#[cfg(unix)]
pub fn get_umask() -> Mode {
    // Assume that people aren't messing with the umask while running
    // XXX: This is not thread safe, but there is no way to get the
    //      umask without setting it
    let mask = umask(Mode::empty());
    umask(mask);
    mask
}

pub enum Kind {
    File,
    Directory,
    Symlink,
    TreeReference,
}

pub fn kind_marker(kind: Kind) -> &'static str {
    match kind {
        Kind::File => "",
        Kind::Directory => "/",
        Kind::Symlink => "@",
        Kind::TreeReference => "+",
    }
}

pub fn get_host_name() -> std::io::Result<String> {
    hostname::get().map(|h| h.to_string_lossy().to_string())
}

pub fn local_concurrency(use_cache: bool) -> usize {
    unsafe {
        static mut _CACHED_LOCAL_CONCURRENCY: Option<usize> = None;

        if use_cache {
            if let Some(concurrency) = _CACHED_LOCAL_CONCURRENCY {
                return concurrency;
            }
        }

        let concurrency = std::env::var("BRZ_CONCURRENCY")
            .map(|s| s.parse::<usize>().unwrap_or(1))
            .unwrap_or_else(|_| num_cpus::get());

        if use_cache {
            _CACHED_LOCAL_CONCURRENCY = Some(concurrency);
        }

        concurrency
    }
}

pub fn pumpfile(
    mut reader: impl std::io::Read,
    mut writer: impl std::io::Write,
    num_bytes: Option<u64>,
) -> std::io::Result<u64> {
    Ok(if let Some(num_bytes) = num_bytes {
        std::io::copy(&mut reader.take(num_bytes), &mut writer)?
    } else {
        std::io::copy(&mut reader, &mut writer)?
    })
}

pub fn pump_string_file(
    data: &[u8],
    mut file_handle: impl std::io::Write,
    segment_size: Option<usize>,
) -> std::io::Result<()> {
    // Write data in chunks rather than all at once, because very large
    // writes fail on some platforms (e.g. Windows with SMB mounted
    // drives).
    let segment_size = segment_size.unwrap_or(5_242_880); // 5MB
    let chunks = data.chunks(segment_size);

    for chunk in chunks {
        file_handle.write_all(chunk)?;
    }

    Ok(())
}

pub fn contains_whitespace(s: &str) -> bool {
    let ws = " \t\n\r\u{000B}\u{000C}";
    for ch in ws.chars() {
        if s.contains(ch) {
            return true;
        }
    }
    false
}

pub fn contains_whitespace_bytes(s: &[u8]) -> bool {
    let ws = b" \t\n\r\x0C\x0B";
    for ch in ws {
        if s.contains(ch) {
            return true;
        }
    }
    false
}

pub fn contains_linebreaks(s: &str) -> bool {
    for ch in "\n\r\x0C".chars() {
        if s.contains(ch) {
            return true;
        }
    }
    false
}

pub mod file;
pub mod iterablefile;
pub mod path;
pub mod sha;
pub mod textfile;
pub mod time;

#[cfg(unix)]
#[path = "mounts-unix.rs"]
pub mod mounts;

#[cfg(windows)]
#[path = "mounts-win32.rs"]
pub mod mounts;

#[cfg(test)]
mod tests;

pub mod terminal;
