use crate::filters::{ContentFilter, ContentFilterProvider, ContentFilterStack};
use breezy_osutils::sha::sha_string;
use log::{debug, info};
use nix::sys::stat::SFlag;
use std::collections::HashMap;
use std::fs;
use std::fs::{File, Metadata, Permissions};
use std::io;
use std::io::prelude::*;
use std::io::BufReader;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tempfile::NamedTempFile;

/// TODO: Up-front, stat all files in order and remove those which are deleted or
/// out-of-date.  Don't actually re-read them until they're needed.  That ought
/// to bring all the inodes into core so that future stats to them are fast, and
/// it preserves the nice property that any caller will always get up-to-date
/// data except in unavoidable cases.

/// TODO: Perhaps return more details on the file to avoid statting it
/// again: nonexistent, file type, size, etc

const CACHE_HEADER: &[u8] = b"### bzr hashcache v5\n";

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

#[derive(Debug, PartialEq, Default, Clone)]
pub struct Fingerprint {
    pub size: u64,
    pub mtime: i64,
    pub ctime: i64,
    pub ino: u64,
    pub dev: u64,
    pub mode: u32,
}

impl From<Metadata> for Fingerprint {
    fn from(meta: Metadata) -> Fingerprint {
        Fingerprint {
            size: meta.size(),
            mtime: meta.mtime(),
            ctime: meta.ctime(),
            ino: meta.ino(),
            dev: meta.dev(),
            mode: meta.mode(),
        }
    }
}

const DEFAULT_CUTOFF_OFFSET: i64 = -3;

pub struct HashCache {
    root: PathBuf,
    hit_count: u32,
    miss_count: u32,
    stat_count: u32,
    danger_count: u32,
    removed_count: u32,
    update_count: u32,
    cache: HashMap<PathBuf, (String, Fingerprint)>,
    needs_write: bool,
    permissions: Option<Permissions>,
    cache_file_name: PathBuf,
    filter_provider: Option<Box<ContentFilterProvider>>,
    cutoff_offset: i64,
}

impl HashCache {
    /// Create a hash cache in base dir, and set the file mode to mode.
    ///
    /// Args:
    ///    content_filter_provider: a function that takes a
    ///       path (relative to the top of the tree) and a file-id as
    ///       parameters and returns a stack of ContentFilters.
    ///       If None, no content filtering is performed.
    pub fn new(
        root: &Path,
        cache_file_name: &Path,
        permissions: Option<Permissions>,
        content_filter_provider: Option<Box<ContentFilterProvider>>,
    ) -> Self {
        HashCache {
            root: root.to_path_buf(),
            hit_count: 0,
            miss_count: 0,
            stat_count: 0,
            danger_count: 0,
            removed_count: 0,
            update_count: 0,
            cache: HashMap::new(),
            needs_write: false,
            permissions,
            cache_file_name: cache_file_name.to_path_buf(),
            filter_provider: content_filter_provider,
            cutoff_offset: DEFAULT_CUTOFF_OFFSET,
        }
    }

    pub fn cache_file_name(&self) -> &Path {
        self.cache_file_name.as_path()
    }

    pub fn hit_count(&self) -> u32 {
        self.hit_count
    }

    pub fn miss_count(&self) -> u32 {
        self.miss_count
    }

    pub fn set_cutoff_offset(&mut self, offset: i64) {
        self.cutoff_offset = offset;
    }

    /// Discard all cached information.
    ///
    /// This does not reset the counters.
    pub fn clear(&mut self) {
        if !self.cache.is_empty() {
            self.needs_write = true;
            self.cache.clear();
        }
    }

    /// Scan all files and remove entries where the cache entry is obsolete.
    ///
    /// Obsolete entries are those where the file has been modified or deleted
    /// since the entry was inserted.
    pub fn scan(&mut self) {
        let mut keys_to_remove = Vec::new();
        let mut by_inode = self
            .cache
            .iter()
            .map(|(k, v)| (v.1.ino, k, v))
            .collect::<Vec<_>>();
        by_inode.sort_by_key(|x| x.0);
        for (_inode, path, cache_val) in by_inode {
            let abspath = self.root.join(path);
            let fp = self.fingerprint(abspath.as_ref(), None);
            self.stat_count += 1;

            if fp.is_none() || cache_val.1 != fp.unwrap() {
                // not here or not a regular file anymore
                self.removed_count += 1;
                self.needs_write = true;
                keys_to_remove.push(path.clone());
            }
        }
        for path in keys_to_remove {
            self.cache.remove(&path);
        }
    }

    pub fn get_sha1_by_fingerprint(
        &mut self,
        path: &Path,
        file_fp: &Fingerprint,
    ) -> io::Result<String> {
        let abspath = self.root.join(path);

        let (cache_sha1, cache_fp) = self
            .cache
            .get(path)
            .cloned()
            .unwrap_or((Default::default(), Default::default()));

        if cache_fp == *file_fp {
            self.hit_count += 1;
            Ok(cache_sha1)
        } else {
            self.miss_count += 1;

            match SFlag::from_bits_truncate(file_fp.mode as nix::libc::mode_t) {
                SFlag::S_IFREG => {
                    let filters: Box<dyn ContentFilter> =
                        if let Some(filter_provider) = self.filter_provider.as_ref() {
                            filter_provider(path, file_fp.ctime as u64)
                        } else {
                            Box::new(ContentFilterStack::new())
                        };
                    let digest = filters.sha1_file(&abspath)?;

                    // window of 3 seconds to allow for 2s resolution on windows,
                    // unsynchronized file servers, etc.
                    let cutoff = self.cutoff_time();
                    if file_fp.mtime >= cutoff || file_fp.ctime >= cutoff {
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
                        if self.cache.remove(path).is_some() {
                            self.removed_count += 1;
                            self.needs_write = true;
                        }
                    } else {
                        self.update_count += 1;
                        self.needs_write = true;
                        self.cache
                            .insert(path.to_owned(), (digest.clone(), file_fp.clone()));
                    }

                    Ok(digest)
                }
                SFlag::S_IFLNK => {
                    let target = fs::read_link(&abspath)?;
                    let digest = sha_string(target.to_string_lossy().as_bytes());
                    self.cache
                        .insert(path.to_owned(), (digest.clone(), file_fp.clone()));
                    self.update_count += 1;
                    self.needs_write = true;
                    Ok(digest)
                }
                _ => Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("unknown file stat mode: {:o}", file_fp.mode),
                )),
            }
        }
    }

    /// Return the SHA-1 of the file at path.
    pub fn get_sha1(
        &mut self,
        path: &Path,
        stat_value: Option<Metadata>,
    ) -> io::Result<Option<String>> {
        let abspath = self.root.join(path);
        self.stat_count += 1;
        let file_fp = self.fingerprint(abspath.as_ref(), stat_value);

        if file_fp.is_none() {
            // not a regular file or not existing
            if self.cache.remove(path).is_some() {
                self.removed_count += 1;
                self.needs_write = true;
            }

            Ok(None)
        } else {
            Ok(Some(self.get_sha1_by_fingerprint(path, &file_fp.unwrap())?))
        }
    }

    /// Write contents of cache to file.
    pub fn write(&mut self) -> Result<(), std::io::Error> {
        let mut outf = NamedTempFile::new_in(self.cache_file_name.parent().unwrap())?;
        if let Some(permissions) = self.permissions.clone() {
            outf.as_file().set_permissions(permissions)?;
        }
        outf.write_all(CACHE_HEADER)?;
        for (path, c) in &self.cache {
            let mut line_info: Vec<u8> = Vec::new();
            line_info.extend_from_slice(path.to_str().unwrap().as_bytes());
            line_info.extend_from_slice(b"// ");
            line_info.extend_from_slice(c.0.as_bytes());
            line_info.push(b' ');
            let fp = &c.1;
            write!(
                &mut line_info,
                "{} {} {} {} {} {}",
                fp.size, fp.mtime, fp.ctime, fp.ino, fp.dev, fp.mode
            )?;
            line_info.push(b'\n');
            outf.write_all(&line_info)?;
        }
        outf.persist(self.cache_file_name())?;
        self.needs_write = false;
        debug!(
            "write hash cache: {} hits={} misses={} stat={} recent={} updates={}",
            self.cache_file_name().display(),
            self.hit_count,
            self.miss_count,
            self.stat_count,
            self.danger_count,
            self.update_count
        );
        Ok(())
    }

    /// Reinstate cache from file.
    ///
    /// Overwrites existing cache.
    ///
    /// If the cache file has the wrong version marker, this just clears
    /// the cache.
    pub fn read(&mut self) -> Result<(), std::io::Error> {
        self.cache = HashMap::new();
        let file = File::open(self.cache_file_name());
        if file.is_err() {
            debug!(
                "failed to open {}: {}",
                self.cache_file_name().display(),
                file.err().unwrap()
            );
            self.needs_write = true;
            return Ok(());
        }
        let file = file.unwrap();
        let reader = BufReader::with_capacity(65000, file);
        let mut lines = reader.lines();
        if let Some(header) = lines.next() {
            if header?.as_bytes().eq(CACHE_HEADER) {
                self.needs_write = true;
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    format!(
                        "cache header marker not found at top of {}; discarding cache",
                        self.cache_file_name().display()
                    ),
                ));
            }
        } else {
            self.needs_write = true;
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "error reading cache file header".to_string(),
            ));
        }
        for line in lines {
            let line = line?;
            let pos = line.find("// ").unwrap();
            let path = PathBuf::from(&line[..pos]);
            if self.cache.contains_key(&path) {
                info!("duplicated path {} in cache", path.display());
                continue;
            }
            let pos = pos + 3;
            let fields = line[pos..].split(' ').collect::<Vec<_>>();
            if fields.len() != 7 {
                info!("bad line in hashcache: {}", line);
                continue;
            }
            let sha1 = fields[0].to_owned();
            if sha1.len() != 40 {
                info!("bad sha1 in hashcache: {}", sha1);
                continue;
            }
            let fp = Fingerprint {
                size: fields[1].parse::<u64>().unwrap(),
                mtime: fields[2].parse::<i64>().unwrap(),
                ctime: fields[3].parse::<i64>().unwrap(),
                ino: fields[4].parse::<u64>().unwrap(),
                dev: fields[5].parse::<u64>().unwrap(),
                mode: fields[6].parse::<u32>().unwrap(),
            };
            self.cache.insert(path, (sha1, fp));
        }
        self.needs_write = false;
        Ok(())
    }

    pub fn needs_write(&self) -> bool {
        self.needs_write
    }

    /// Return cutoff time.
    ///
    /// Files modified more recently than this time are at risk of being
    /// undetectably modified and so can't be cached.
    pub fn cutoff_time(&self) -> i64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64
            + self.cutoff_offset
    }

    pub fn fingerprint(&self, abspath: &Path, stat_value: Option<Metadata>) -> Option<Fingerprint> {
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
        Some(stat_value.into())
    }
}
