use std::borrow::Borrow;
use std::io::Read;

pub struct ChunksReader<T: Borrow<[u8]>> {
    chunks: Box<dyn Iterator<Item = T>>,
    current_chunk: Option<T>,
    position: usize,
}

impl<T: Borrow<[u8]>> ChunksReader<T> {
    pub fn new(chunks: Box<dyn Iterator<Item = T>>) -> Self {
        ChunksReader {
            chunks,
            position: 0,
            current_chunk: None,
        }
    }
}

impl<T: Borrow<[u8]>> Read for ChunksReader<T> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let mut bytes_read = 0;

        while bytes_read < buf.len() {
            if let Some(chunk) = self.current_chunk.as_ref() {
                let bytes_to_copy =
                    (buf.len() - bytes_read).min(chunk.borrow().len() - self.position);
                buf[bytes_read..bytes_read + bytes_to_copy]
                    .copy_from_slice(&chunk.borrow()[self.position..self.position + bytes_to_copy]);
                self.position += bytes_to_copy;
                bytes_read += bytes_to_copy;
                if self.position == chunk.borrow().len() {
                    self.current_chunk = None;
                }
            } else if let Some(chunk) = self.chunks.next() {
                self.current_chunk = Some(chunk);
                self.position = 0;
            } else {
                break;
            }
        }

        Ok(bytes_read)
    }
}

#[test]
fn test_chunks_reader_vec() {
    let chunks = vec![vec![1, 2, 3], vec![4, 5, 6], vec![7, 8, 9]];
    let mut reader = ChunksReader::new(Box::new(chunks.into_iter()));

    let mut buf = [0; 4];
    assert_eq!(reader.read(&mut buf).unwrap(), 4);
    assert_eq!(buf, [1, 2, 3, 4]);

    assert_eq!(reader.read(&mut buf).unwrap(), 4);
    assert_eq!(buf, [5, 6, 7, 8]);

    assert_eq!(reader.read(&mut buf).unwrap(), 1);
    assert_eq!(buf[0], 9);

    assert_eq!(reader.read(&mut buf).unwrap(), 0);
}

#[test]
fn test_chunks_reader_slice() {
    let chunks = [[1, 2, 3], [4, 5, 6], [7, 8, 9]];
    let mut reader = ChunksReader::new(Box::new(chunks.into_iter()));

    let mut buf = [0; 4];
    assert_eq!(reader.read(&mut buf).unwrap(), 4);
    assert_eq!(buf, [1, 2, 3, 4]);

    assert_eq!(reader.read(&mut buf).unwrap(), 4);
    assert_eq!(buf, [5, 6, 7, 8]);

    assert_eq!(reader.read(&mut buf).unwrap(), 1);
    assert_eq!(buf[0], 9);

    assert_eq!(reader.read(&mut buf).unwrap(), 0);
}
