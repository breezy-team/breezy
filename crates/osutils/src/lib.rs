use log::{debug, warn};
use memchr::memchr;
use rand::Rng;
use std::borrow::Cow;

pub fn is_well_formed_line(line: &[u8]) -> bool {
    if line.is_empty() {
        return false;
    }
    memchr(b'\n', line) == Some(line.len() - 1)
}

pub trait AsCow<'a, T: ToOwned + ?Sized> {
    fn as_cow(self) -> Cow<'a, T>;
}

impl<'a> AsCow<'a, [u8]> for &'a [u8] {
    fn as_cow(self) -> Cow<'a, [u8]> {
        Cow::Borrowed(self)
    }
}

impl<'a> AsCow<'a, [u8]> for Cow<'a, [u8]> {
    fn as_cow(self) -> Cow<'a, [u8]> {
        self
    }
}

impl<'a> AsCow<'a, [u8]> for Vec<u8> {
    fn as_cow(self) -> Cow<'a, [u8]> {
        Cow::Owned(self)
    }
}

impl<'a> AsCow<'a, [u8]> for &'a Vec<u8> {
    fn as_cow(self) -> Cow<'a, [u8]> {
        Cow::Borrowed(self.as_slice())
    }
}

pub fn chunks_to_lines<'a, C, I, E>(chunks: I) -> impl Iterator<Item = Result<Cow<'a, [u8]>, E>>
where
    I: Iterator<Item = Result<C, E>> + 'a,
    C: AsCow<'a, [u8]> + 'a,
    E: std::fmt::Debug,
{
    pub struct ChunksToLines<'a, C, E>
    where
        C: AsCow<'a, [u8]>,
        E: std::fmt::Debug,
    {
        chunks: Box<dyn Iterator<Item = Result<C, E>> + 'a>,
        tail: Vec<u8>,
    }

    impl<'a, C, E: std::fmt::Debug> Iterator for ChunksToLines<'a, C, E>
    where
        C: AsCow<'a, [u8]>,
    {
        type Item = Result<Cow<'a, [u8]>, E>;

        fn next(&mut self) -> Option<Self::Item> {
            loop {
                // See if we can find a line in tail
                if let Some(newline) = memchr(b'\n', &self.tail) {
                    // The chunk contains multiple lines, so split it into lines
                    let line = Cow::Owned(self.tail[..=newline].to_vec());
                    self.tail.drain(..=newline);
                    return Some(Ok(line));
                } else {
                    // We couldn't find a newline
                    if let Some(next_chunk) = self.chunks.next() {
                        match next_chunk {
                            Err(e) => {
                                return Some(Err(e));
                            }
                            Ok(next_chunk) => {
                                let next_chunk = next_chunk.as_cow();
                                // If the chunk is well-formed, return it
                                if self.tail.is_empty() && is_well_formed_line(next_chunk.as_ref())
                                {
                                    return Some(Ok(next_chunk));
                                } else {
                                    self.tail.extend_from_slice(next_chunk.as_ref());
                                }
                            }
                        }
                    } else {
                        // We've reached the end of the chunks, so return the last chunk
                        if self.tail.is_empty() {
                            return None;
                        }
                        let line = Cow::Owned(self.tail.to_vec());
                        self.tail.clear();
                        return Some(Ok(line));
                    }
                }
            }
        }
    }

    ChunksToLines {
        chunks: Box::new(chunks),
        tail: Vec::new(),
    }
}

#[test]
fn test_chunks_to_lines() {
    assert_eq!(
        chunks_to_lines(vec![Ok::<_, std::io::Error>("foo\nbar".as_bytes().as_cow())].into_iter())
            .map(|x| x.unwrap())
            .collect::<Vec<_>>(),
        vec!["foo\n".as_bytes().as_cow(), "bar".as_bytes().as_cow()]
    );
}

pub fn split_lines(text: &[u8]) -> impl Iterator<Item = Cow<'_, [u8]>> {
    pub struct SplitLines<'a> {
        text: &'a [u8],
    }

    impl<'a> Iterator for SplitLines<'a> {
        type Item = Cow<'a, [u8]>;

        fn next(&mut self) -> Option<Self::Item> {
            if self.text.is_empty() {
                return None;
            }
            if let Some(newline) = memchr(b'\n', self.text) {
                let line = Cow::Borrowed(&self.text[..=newline]);
                self.text = &self.text[newline + 1..];
                Some(line)
            } else {
                // No newline found, so return the rest of the text
                let line = Cow::Borrowed(self.text);
                self.text = &self.text[self.text.len()..];
                Some(line)
            }
        }
    }

    SplitLines { text }
}

#[test]
fn test_split_lines() {
    assert_eq!(
        split_lines("foo\nbar".as_bytes())
            .map(|x| x.to_vec())
            .collect::<Vec<_>>(),
        vec!["foo\n".as_bytes().to_vec(), "bar".as_bytes().to_vec()]
    );
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
    let mut rng = rand::rng();
    let mut s = String::new();
    for _ in 0..num {
        let raw_byte = rng.random_range(0..256);
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

#[derive(Debug, PartialEq)]
pub enum Kind {
    File,
    Directory,
    Symlink,
    TreeReference,
}

impl Kind {
    pub fn marker(&self) -> &'static str {
        match self {
            Kind::File => "",
            Kind::Directory => "/",
            Kind::Symlink => "@",
            Kind::TreeReference => "+",
        }
    }

    pub fn to_string(&self) -> &'static str {
        match self {
            Kind::File => "file",
            Kind::Directory => "directory",
            Kind::Symlink => "symlink",
            Kind::TreeReference => "tree-reference",
        }
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::ToPyObject for Kind {
    fn to_object(&self, py: pyo3::Python) -> pyo3::PyObject {
        match self {
            Kind::File => "file".to_object(py),
            Kind::Directory => "directory".to_object(py),
            Kind::Symlink => "symlink".to_object(py),
            Kind::TreeReference => "tree-reference".to_object(py),
        }
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::FromPyObject<'_> for Kind {
    fn extract(ob: &pyo3::PyAny) -> pyo3::PyResult<Self> {
        let s: String = ob.extract()?;
        match s.as_str() {
            "file" => Ok(Kind::File),
            "directory" => Ok(Kind::Directory),
            "symlink" => Ok(Kind::Symlink),
            "tree-reference" => Ok(Kind::TreeReference),
            _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Invalid kind: {}",
                s
            ))),
        }
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

pub fn get_home_dir() -> Option<std::path::PathBuf> {
    dirs::home_dir()
}

fn _get_user_encoding() -> Option<String> {
    unsafe {
        let codeset = nix::libc::nl_langinfo(nix::libc::CODESET);
        if codeset.is_null() {
            return None;
        }
        let codeset_str = std::ffi::CStr::from_ptr(codeset);
        Some(codeset_str.to_string_lossy().to_string())
    }
}

pub fn get_user_encoding() -> Option<String> {
    let encoding = _get_user_encoding()?;

    match encoding_rs::Encoding::for_label(encoding.as_bytes()) {
        Some(enc) => Some(enc.name().to_string()),
        _ => {
            warn!(
                "brz: warning: unknown encoding {}. Defaulting to ASCII.",
                encoding
            );
            Some("ASCII".to_string())
        }
    }
}

pub mod chunkreader;
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

#[cfg(unix)]
pub fn is_local_pid_dead(pid: nix::unistd::Pid) -> bool {
    use nix::sys::signal::kill;

    match kill(pid, None) {
        Ok(_) => false,                  // Process exists and is ours: not dead.
        Err(nix::Error::ESRCH) => true,  // Not found: as sure as we can be that it's dead.
        Err(nix::Error::EPERM) => false, // Exists, though not ours.
        Err(err) => {
            debug!("kill({:?}, 0) failed: {}", pid, err);
            false // Don't really know.
        }
    }
}

pub fn get_user_name() -> String {
    for name in &["LOGNAME", "USER", "LNAME", "USERNAME"] {
        if let Ok(user) = std::env::var(name) {
            return user;
        }
    }

    whoami::username()
}
