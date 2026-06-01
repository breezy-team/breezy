use std::io::{self, BufRead, Read, Seek, SeekFrom};

pub struct IterableFile<I: Iterator<Item = io::Result<Vec<u8>>> + Send + Sync> {
    iter: I,
    buffer: Vec<u8>,
}

impl<I: Iterator<Item = io::Result<Vec<u8>>> + Send + Sync> IterableFile<I> {
    pub fn new(iter: I) -> Self {
        IterableFile {
            iter,
            buffer: Vec::new(),
        }
    }
}

impl<I: Iterator<Item = io::Result<Vec<u8>>> + Send + Sync> Read for IterableFile<I> {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let n = self.fill_buf()?.read(buf)?;
        self.consume(n);
        Ok(n)
    }
}

impl<I: Iterator<Item = io::Result<Vec<u8>>> + Send + Sync> BufRead for IterableFile<I> {
    fn fill_buf(&mut self) -> io::Result<&[u8]> {
        while self.buffer.is_empty() {
            if let Some(bytes) = self.iter.next() {
                self.buffer = bytes?;
            } else {
                break;
            }
        }
        Ok(&self.buffer)
    }

    fn consume(&mut self, amt: usize) {
        self.buffer.drain(..amt);
    }
}

impl<I: Iterator<Item = io::Result<Vec<u8>>> + Seek + Send + Sync> Seek for IterableFile<I> {
    fn seek(&mut self, pos: SeekFrom) -> io::Result<u64> {
        match pos {
            SeekFrom::Start(n) => {
                self.iter.seek(SeekFrom::Start(n))?;
                self.buffer.clear();
            }
            SeekFrom::Current(n) => {
                if n >= 0 {
                    let mut skip = n as usize;
                    while skip > 0 {
                        let buf = self.fill_buf()?;
                        if buf.is_empty() {
                            break;
                        }
                        let n = std::cmp::min(skip, buf.len());
                        self.consume(n);
                        skip -= n;
                    }
                } else {
                    self.seek(SeekFrom::End(n))?;
                }
            }
            SeekFrom::End(n) => {
                let mut pos = self.iter.seek(SeekFrom::End(0))? as i64;
                pos += n;
                if pos < 0 {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "invalid seek to a negative or overflowing position",
                    ));
                }
                self.iter.seek(SeekFrom::Start(pos as u64))?;
                self.buffer.clear();
            }
        }
        self.iter.stream_position()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_read_all() {
        let content: Vec<Vec<u8>> = vec![
            b"This ".to_vec(),
            b"is ".to_vec(),
            b"a ".to_vec(),
            b"test.".to_vec(),
        ];
        let mut file = IterableFile::new(content.iter().map(|x| Ok(x.to_vec())));
        let mut buf = Vec::new();
        let read = file.read_to_end(&mut buf).unwrap();
        assert_eq!(read, 15);
        assert_eq!(&buf, b"This is a test.");
    }

    #[test]
    fn test_read_n() {
        let content: Vec<Vec<u8>> = vec![
            b"This ".to_vec(),
            b"is ".to_vec(),
            b"a ".to_vec(),
            b"test.".to_vec(),
        ];
        let mut file = IterableFile::new(content.iter().map(|x| Ok(x.to_vec())));
        let mut buf = [0u8; 8];
        file.read_exact(&mut buf).unwrap();
        assert_eq!(&buf, b"This is ");
    }

    #[test]
    fn test_read_to() {
        let content: Vec<Vec<u8>> = vec![
            b"This\n".to_vec(),
            b"is ".to_vec(),
            b"a ".to_vec(),
            b"test.\n".to_vec(),
        ];
        let mut file = IterableFile::new(content.iter().map(|x| Ok(x.to_vec())));
        let mut buf = Vec::new();
        file.read_until(b'\n', &mut buf).unwrap();
        assert_eq!(&buf, b"This\n");
        buf.clear();
        let read = file.read_until(b'\n', &mut buf).unwrap();
        assert_eq!(read, 11);
        assert_eq!(&buf, b"is a test.\n");
    }

    #[test]
    fn test_readline() {
        let content: Vec<Vec<u8>> = vec![
            b"".to_vec(),
            b"This\n".to_vec(),
            b"is ".to_vec(),
            b"a ".to_vec(),
            b"test.\n".to_vec(),
        ];
        let mut file = IterableFile::new(content.iter().map(|x| Ok(x.to_vec())));
        let mut buf = String::new();
        let read = file.read_line(&mut buf).unwrap();
        assert_eq!(read, 5);
        assert_eq!(&buf, "This\n");
    }

    #[test]
    fn test_readlines() {
        let content: Vec<Vec<u8>> = vec![
            b"This\n".to_vec(),
            b"is ".to_vec(),
            b"".to_vec(),
            b"a ".to_vec(),
            b"test.\n".to_vec(),
        ];
        let file = IterableFile::new(content.iter().map(|x| Ok(x.to_vec())));
        let lines: Vec<String> = file.lines().map(|line| line.unwrap()).collect();
        assert_eq!(lines, vec!["This", "is a test."]);
    }

    #[test]
    fn test_fillbuf() {
        let content: Vec<Vec<u8>> = vec![
            b"This ".to_vec(),
            b"".to_vec(),
            b"is ".to_vec(),
            b"a ".to_vec(),
            b"test.".to_vec(),
        ];
        let mut file = IterableFile::new(content.iter().map(|x| Ok(x.to_vec())));
        assert_eq!(file.fill_buf().unwrap(), b"This ");
        file.consume(5);
        assert_eq!(file.fill_buf().unwrap(), b"is ");
        file.consume(3);
        assert_eq!(file.fill_buf().unwrap(), b"a ");
        file.consume(2);
        assert_eq!(file.fill_buf().unwrap(), b"test.");
        file.consume(5);
        assert!(file.fill_buf().unwrap().is_empty());
    }

    #[test]
    fn test_drain() {
        let content: Vec<Vec<u8>> = vec![
            b"This ".to_vec(),
            b"is ".to_vec(),
            b"a ".to_vec(),
            b"test.".to_vec(),
        ];
        let mut file = IterableFile::new(content.iter().map(|x| Ok(x.to_vec())));
        let buf = file.fill_buf().unwrap();
        assert_eq!(buf, b"This ");
        file.consume(5);
        let buf = file.fill_buf().unwrap();
        assert_eq!(buf, b"is ");
        file.consume(1);
        let buf = file.fill_buf().unwrap();
        assert_eq!(buf, b"s ");
    }
}
