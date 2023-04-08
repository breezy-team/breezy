use std::fs::File;
use std::io::Read;
use std::path::Path;
use sha1::{Digest, Sha1};

pub fn sha_file(f: &mut dyn Read) -> Result<String, std::io::Error> {
    let mut s = Sha1::new();
    std::io::copy(f, &mut s)?;
    Ok(format!("{:x}", s.finalize()))
}

pub fn size_sha_file(f: &mut dyn Read) -> Result<(usize, String), std::io::Error> {
    let mut s = Sha1::new();
    const BUFSIZE: usize = 128 << 10;
    let mut buffer = [0; BUFSIZE];
    let mut size: usize = 0;
    loop {
        let bytes_read = f.read(&mut buffer)?;
        if bytes_read == 0 {
            break;
        }
        s.update(&buffer[..bytes_read]);
        size += bytes_read as usize;
    }
    Ok((size, format!("{:x}", s.finalize())))
}

pub fn sha_file_by_name<P: AsRef<Path>>(path: P) -> Result<String, std::io::Error> {
    let mut f = File::open(path)?;
    sha_file(&mut f)
}

pub fn sha_strings<I, S>(strings: I) -> String
where
    I: IntoIterator<Item = S>,
    S: AsRef<[u8]>,
{
    let mut s = Sha1::new();
    for string in strings {
        s.update(string.as_ref());
    }
    format!("{:x}", s.finalize())
}

pub fn sha_string(string: &[u8]) -> String {
    let mut s = Sha1::new();
    s.update(string);

    format!("{:x}", s.finalize())
}
