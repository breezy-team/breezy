use breezy_osutils::sha::sha_chunks;
use std::fs::File;
use std::io::Error;
use std::io::Read;
use std::path::Path;

pub type ContentFilterProvider = dyn Fn(&Path, u64) -> Box<dyn ContentFilter> + Send + Sync;

pub trait ContentFilter {
    fn reader(
        &self,
        input: Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send + Sync>,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send + Sync>;

    fn writer(
        &self,
        input: Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send + Sync>,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send + Sync>;

    fn sha1_file(&self, path: &Path) -> Result<String, std::io::Error> {
        let mut file = File::open(path)?;
        let chunk_iter = std::iter::from_fn(move || {
            let mut buf = vec![0; 128 << 10];
            let bytes_read = file.read(&mut buf);
            if let Err(e) = bytes_read {
                return Some(Err(e));
            }
            let bytes_read = bytes_read.unwrap();
            if bytes_read == 0 {
                None
            } else {
                buf.truncate(bytes_read);
                Some(Ok(buf))
            }
        });
        let chunk_iter = self.reader(Box::new(chunk_iter));
        let mut err = None;
        let sha1 = sha_chunks(chunk_iter.filter_map(|r| {
            if let Err(e) = r {
                err = Some(e);
                None
            } else {
                Some(r.unwrap())
            }
        }));
        if let Some(err) = err {
            Err(err)
        } else {
            Ok(sha1)
        }
    }
}

pub struct ContentFilterStack {
    filters: Vec<Box<dyn ContentFilter>>,
}

impl From<Vec<Box<dyn ContentFilter>>> for ContentFilterStack {
    fn from(filters: Vec<Box<dyn ContentFilter>>) -> Self {
        Self { filters }
    }
}

impl ContentFilterStack {
    pub fn new() -> Self {
        Self {
            filters: Vec::new(),
        }
    }

    pub fn add_filter(&mut self, filter: Box<dyn ContentFilter>) {
        self.filters.push(filter);
    }
}

impl std::default::Default for ContentFilterStack {
    fn default() -> Self {
        Self::new()
    }
}

impl ContentFilter for ContentFilterStack {
    fn reader(
        &self,
        input: Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send + Sync>,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send + Sync> {
        self.filters
            .iter()
            .fold(input, |input, filter| filter.reader(input))
    }

    fn writer(
        &self,
        input: Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send + Sync>,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send + Sync> {
        self.filters
            .iter()
            .fold(input, |input, filter| filter.writer(input))
    }
}
