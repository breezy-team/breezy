use sha1::{Digest, Sha1};
use std::fs::File;
use std::io::Read;
use std::path::Path;

pub fn sha_file(f: &mut dyn Read) -> Result<String, std::io::Error> {
    let (_, sha) = size_sha_file(f)?;
    Ok(sha)
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
        size += bytes_read;
    }
    Ok((size, hex::encode(s.finalize())))
}

pub fn size_sha_chunks(chunks: impl Iterator<Item = Vec<u8>>) -> (usize, String) {
    let mut s = Sha1::new();
    let mut size: usize = 0;
    for chunk in chunks {
        s.update(&chunk);
        size += chunk.len();
    }
    (size, hex::encode(s.finalize()))
}

pub fn sha_file_by_name<P: AsRef<Path>>(path: P) -> Result<String, std::io::Error> {
    let mut f = File::open(path)?;
    sha_file(&mut f)
}

pub fn sha_chunks<I, S>(strings: I) -> String
where
    I: IntoIterator<Item = S>,
    S: AsRef<[u8]>,
{
    let mut s = Sha1::new();
    for string in strings {
        s.update(string.as_ref());
    }
    hex::encode(s.finalize())
}

pub fn sha_string(string: &[u8]) -> String {
    let mut s = Sha1::new();
    s.update(string);

    hex::encode(s.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_digests() {
        assert_eq!(sha_string(b""), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
        assert_eq!(
            sha_string(b"abc"),
            "a9993e364706816aba3e25717850c26c9cd0d89d"
        );
        assert_eq!(
            sha_chunks([b"ab".as_slice(), b"c".as_slice()]),
            "a9993e364706816aba3e25717850c26c9cd0d89d"
        );

        let mut r = std::io::Cursor::new(b"abc".to_vec());
        assert_eq!(
            size_sha_file(&mut r).unwrap(),
            (3, "a9993e364706816aba3e25717850c26c9cd0d89d".to_string())
        );
    }
}
