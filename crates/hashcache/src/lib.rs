use std::io::prelude::*;
use std::os::unix::fs::MetadataExt;
use std::path::{Path,PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use std::io;
use std::io::{BufReader,BufWriter};
use std::fs;
use std::fs::File;
use sha1::{Digest, Sha1};
use std::collections::HashMap;

/// TODO: Up-front, stat all files in order and remove those which are deleted or
/// out-of-date.  Don't actually re-read them until they're needed.  That ought
/// to bring all the inodes into core so that future stats to them are fast, and
/// it preserves the nice property that any caller will always get up-to-date
/// data except in unavoidable cases.

/// TODO: Perhaps return more details on the file to avoid statting it
/// again: nonexistent, file type, size, etc

// TODO(jelmer): Move to a more central place.
fn sha_string(input: &[u8]) -> String {
    let mut hasher = Sha1::new();
    hasher.update(input);
    hasher.digest().to_string()
}

const CACHE_HEADER: &[u8] = b"### bzr hashcache v5\n";

const FP_MTIME_COLUMN: usize = 1;
const FP_CTIME_COLUMN: usize = 2;
const FP_MODE_COLUMN: usize = 5;

trait ContentFilter {
    fn filter(&mut self, data: &[u8]) -> Vec<u8>;
}

/// Cache for looking up file SHA-1.
/// 
/// Files are considered to match the cached value if the fingerprint
/// of the file has not changed.  This includes its mtime, ctime,
/// device number, inode number, and size.  This should catch
/// modifications or replacement of the file by a new one.
/// 
/// This may not catch modifications that do not change the file's
/// size and that occur within the resolution window of the
/// timestamps.  To handle this we specifically do not cache files
/// which have changed since the start of the present second, since
/// they could undetectably change again.
/// 
/// This scheme may fail if the machine's clock steps backwards.
/// Don't do that.
/// 
/// This does not canonicalize the paths passed in; that should be
/// done by the caller.
/// 
/// _cache
///     Indexed by path, points to a two-tuple of the SHA-1 of the file.
///     and its fingerprint.
/// 
/// stat_count
///     number of times files have been statted
/// 
/// hit_count
///     number of times files have been retrieved from the cache, avoiding a
///     re-read
/// 
/// miss_count
///     number of misses (times files have been completely re-read)

type Fingerprint = (u64, i64, i64, u64, u64, u32);

pub struct HashCache {
    root: String,
    hit_count: u32,
    miss_count: u32,
    stat_count: u32,
    danger_count: u32,
    removed_count: u32,
    update_count: u32,
    _cache: HashMap<String, (String, Fingerprint)>,
    needs_write: bool,
    _mode: Option<u32>,
    _cache_file_name: String,
    _filter_provider: Option<Box<dyn FnMut(&str) -> Vec<Box<dyn ContentFilter>>>>>,
}

impl HashCache {
    /// Create a hash cache in base dir, and set the file mode to mode.
    /// 
    /// Args:
    ///    content_filter_stack_provider: a function that takes a
    ///       path (relative to the top of the tree) and a file-id as
    ///       parameters and returns a stack of ContentFilters.
    ///       If None, no content filtering is performed.
    pub fn new<P: AsRef<Path>>(
        root: P,
        cache_file_name: P,
        mode: Option<u32>,
        content_filter_stack_provider: Option<
            Box<dyn FnMut(&str) -> Vec<Box<dyn ContentFilter>>>,
        >,
    ) -> Self {
        HashCache {
            root: root
                .as_ref()
                .to_str()
                .expect("Invalid base dir for hashcache")
                .to_string(),
            hit_count: 0,
            miss_count: 0,
            stat_count: 0,
            danger_count: 0,
            removed_count: 0,
            update_count: 0,
            _cache: HashMap::new(),
            needs_write: false,
            _mode: mode,
            _cache_file_name: cache_file_name
                .as_ref()
                .to_str()
                .expect("Invalid cache file name")
                .to_string(),
            _filter_provider: content_filter_stack_provider,
        }
    }

    pub fn cache_file_name(&self) -> &str {
        &self._cache_file_name
    }

    /// Discard all cached information.
    ///
    /// This does not reset the counters.
    pub fn clear(&mut self) {
        if !self._cache.is_empty() {
            self.needs_write = true;
            self._cache.clear();
        }
    }

    /// Scan all files and remove entries where the cache entry is obsolete.
    ///
    /// Obsolete entries are those where the file has been modified or deleted
    /// since the entry was inserted.
    pub fn scan(&mut self) {
        // Stat in inode order as optimization for at least linux.
        fn inode_order(
            path_and_cache: (&String, &(Vec<u8>, Fingerprint)),
        ) -> u64 {
            path_and_cache.1 .1 .3
        }

        let mut keys_to_remove = Vec::new();
        for (path, cache_val) in self._cache.iter().sorted_by(inode_order) {
            let abspath = format!("{}/{}", self.root, path);
            let fp = self.fingerprint(&abspath.as_ref(), None);
            self.stat_count += 1;

            if fp.is_none() || cache_val.1 != fp.unwrap() {
                // not here or not a regular file anymore
                self.removed_count += 1;
                self.needs_write = true;
                keys_to_remove.push(path.clone());
            }
        }
        for path in keys_to_remove {
            self._cache.remove(&path);
        }
    }

    /// Return the SHA-1 of the file at path.
    pub fn get_sha1(
        &mut self,
        path: &Path,
        stat_value: Option<fs::Metadata>,
    ) -> io::Result<[u8; 20]> {
        let abspath = PathBuf::from(self.root).join(path);
        self.stat_count += 1;
        let file_fp = self.fingerprint(&abspath.as_ref(), stat_value);
    
        if file_fp.is_none() {
            // not a regular file or not existing
            if let Some(_) = self._cache.remove(path) {
                self.removed_count += 1;
                self.needs_write = true;
            }
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                format!("file {:?} not found", abspath),
            ));
        }

        let file_fp = file_fp.unwrap();
    
        let (cache_sha1, cache_fp) = self._cache.get(path).cloned().unwrap_or((Default::default(), Default::default()));
    
        if cache_fp == file_fp {
            self.hit_count += 1;
            Ok(cache_sha1)
        } else {
            self.miss_count += 1;
    
            let mode = file_fp[FP_MODE_COLUMN];
            if mode & libc::S_IFMT as u64 == libc::S_IFREG as u64 {
                let filters = if let Some(ref filter_provider) = self._filter_provider {
                    filter_provider(path, file_fp[FP_CTIME_COLUMN] as u64)
                } else {
                    ContentFilterStack::new()
                };
                let digest: String = self.really_sha1_file(&abspath, &filters)?;
    
                // window of 3 seconds to allow for 2s resolution on windows,
                // unsynchronized file servers, etc.
                let cutoff = self.cutoff_time();
                if file_fp[FP_MTIME_COLUMN] >= cutoff || file_fp[FP_CTIME_COLUMN] >= cutoff {
                    // changed too recently; can't be cached. we can
                    // return the result and it could possibly be cached
                    // next time.
                    //
                    // the point is that we only want to cache when we are sure that any
                    // subsequent modifications of the file can be detected. If a
                    // modification neither changes the inode, the device, the size, nor
                    // the mode, then we can only distinguish it by time; therefore we
                    // need to let sufficient time elapse before we may cache this entry
                    // again. If we didn't do this, then, for example, a very quick 1
                    // byte replacement in the file might go undetected.
                    self.danger_count += 1;
                    if let Some(_) = self._cache.remove(path) {
                        self.removed_count += 1;
                        self.needs_write = true;
                    }
                } else {
                    self.update_count += 1;
                    self.needs_write = true;
                    self._cache.insert(path.to_owned(), (digest, file_fp));
                }
    
                Ok(digest)
            } else if mode & libc::S_IFMT as u64 == libc::S_IFLNK as u64 {
                let target = fs::read_link(&abspath)?;
                let digest = sha_string(target.to_string_lossy().as_bytes());
                self._cache.insert(path.to_owned(), (digest, file_fp));
                self.update_count += 1;
                self.needs_write = true;
                Ok(digest)
            } else {
                Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("unknown file stat mode: {:o}", mode),
                ))
            }
        }
    }

    /// Write contents of cache to file.
    pub fn write(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        let mut outf = BufWriter::new(
            atomicfile::AtomicFile::new(&self.cache_file_name(), self._mode).write()?,
        );
        outf.write_all(CACHE_HEADER)?;
        for (path, c) in &self._cache {
            let mut line_info: Vec<u8> = Vec::new();
            line_info.extend_from_slice(path.to_str().unwrap().as_bytes());
            line_info.extend_from_slice(b"// ");
            line_info.extend_from_slice(c.0.as_bytes());
            line_info.push(b' ');
            let (size, mtime, ctime, ino, dev, mode) = c.1;
            write!(
                &mut line_info,
                "{} {} {} {} {} {}",
                size, mtime, ctime, ino, dev, mode
            )?;
            line_info.push(b'\n');
            outf.write_all(&line_info)?;
        }
        self.needs_write = false;
        // mutter("write hash cache: %s hits=%d misses=%d stat=%d recent=%d updates=%d",
        //        self.cache_file_name(), self.hit_count, self.miss_count,
        // self.stat_count,
        // self.danger_count, self.update_count)
        Ok(())
    }

    /// Calculate the SHA1 of a file by reading the full text
    fn really_sha1_file(&self, abspath: &Path, filters: &[Box<dyn ContentFilter>]) -> io::Result<String> {
        _mod_filters::internal_size_sha_file_byname(abspath, filters).map(|(_, sha)| sha)
    }

    /// Reinstate cache from file.
    ///
    /// Overwrites existing cache.
    ///
    /// If the cache file has the wrong version marker, this just clears
    /// the cache.
    pub fn read(&mut self) {
        self._cache = HashMap::new();
        if let Ok(file) = File::open(self.cache_file_name()) {
            let reader = BufReader::new(file);
            if let Some(header) = reader.lines().next() {
                if header.unwrap().as_bytes() != CACHE_HEADER {
                    eprintln!(
                        "cache header marker not found at top of {}; discarding cache",
                        self.cache_file_name()
                    );
                    self.needs_write = true;
                    return;
                }
            } else {
                eprintln!("error reading cache file header");
                self.needs_write = true;
                return;
            }
            for line in reader.lines() {
                let line = line.unwrap();
                let pos = line.find("// ").unwrap();
                let path = line[..pos].to_owned();
                if self._cache.contains_key(&path) {
                    eprintln!("duplicated path {} in cache", path);
                    continue;
                }
                let pos = pos + 3;
                let fields = line[pos..].split(' ').collect::<Vec<_>>();
                if fields.len() != 7 {
                    eprintln!("bad line in hashcache: {}", line);
                    continue;
                }
                let sha1 = fields[0].to_owned();
                if sha1.len() != 40 {
                    eprintln!("bad sha1 in hashcache: {}", sha1);
                    continue;
                }
                let fp = (
                    fields[1].parse::<u64>().unwrap(),
                    fields[2].parse::<i64>().unwrap(),
                    fields[3].parse::<i64>().unwrap(),
                    fields[4].parse::<u64>().unwrap(),
                    fields[5].parse::<u64>().unwrap(),
                    fields[6].parse::<u32>().unwrap(),
                );
                self._cache.insert(path, (sha1, fp));
            }
            self.needs_write = false;
        } else {
            eprintln!("failed to open {}", self.cache_file_name());
            self.needs_write = true;
        }
    }

    /// Return cutoff time.
    ///
    /// Files modified more recently than this time are at risk of being
    /// undetectably modified and so can't be cached.
    fn cutoff_time(&self) -> i64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64
            - 3
    }

    fn fingerprint(&self, abspath: &Path, stat_value: Option<fs::Metadata>) -> Option<Fingerprint> {
        let stat_value = match stat_value {
            Some(s) => s,
            None => match fs::symlink_metadata(abspath) {
                Ok(s) => s,
                Err(_) => return None,
            },
        };
        if stat_value.is_dir() {
            return None;
        }
        Some((
            stat_value.len(),
            stat_value.mtime(),
            stat_value.ctime(),
            stat_value.ino(),
            stat_value.dev(),
            stat_value.mode()
        ))
    }
}
