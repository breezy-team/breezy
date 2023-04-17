use base64;
use std::cmp::Ordering;
use std::path::Path;
use breezy_osutils::sha::{sha_file_by_name,sha_file};
use std::fs::File;
use std::fs::Metadata;
use std::os::unix::fs::MetadataExt;

pub trait SHA1Provider : Send + Sync {
    fn sha1(&self, path: &Path) -> std::io::Result<String>;

    fn stat_and_sha1(&self, path: &Path) -> std::io::Result<(Metadata, String)>;
}

/// A SHA1Provider that reads directly from the filesystem."""
pub struct DefaultSHA1Provider;

impl DefaultSHA1Provider {
    pub fn new() -> DefaultSHA1Provider {
        DefaultSHA1Provider {}
    }
}

impl SHA1Provider for DefaultSHA1Provider {
    /// Return the sha1 of a file given its absolute path.
    fn sha1(&self, path: &Path) -> std::io::Result<String> {
        sha_file_by_name(path)
    }

    /// Return the stat and sha1 of a file given its absolute path.
    fn stat_and_sha1(&self, path: &Path) -> std::io::Result<(Metadata, String)> {
        let mut f = File::open(path)?;
        let stat = f.metadata()?;
        let sha1 = sha_file(&mut f)?;
        Ok((stat, sha1))
    }
}

pub fn lt_by_dirs(path1: &Path, path2: &Path) -> bool {
    let path1_parts = path1.components();
    let path2_parts = path2.components();
    let mut path1_parts_iter = path1_parts.into_iter();
    let mut path2_parts_iter = path2_parts.into_iter();

    loop {
        match (path1_parts_iter.next(), path2_parts_iter.next()) {
            (None, None) => return false,
            (None, Some(_)) => return true,
            (Some(_), None) => return false,
            (Some(part1), Some(part2)) => {
                match part1.cmp(&part2) {
                    Ordering::Equal => continue,
                    Ordering::Less => return true,
                    Ordering::Greater => return false,
                }
            }
        }
    }
}

pub fn lt_path_by_dirblock(path1: &Path, path2: &Path) -> bool {
    let key1 = (path1.parent(), path1.file_name());
    let key2 = (path2.parent(), path2.file_name());

    key1 < key2
}

pub fn bisect_path_left(paths: &[&Path], path: &Path) -> usize {
    let mut hi = paths.len();
    let mut lo = 0;
    while lo < hi {
        let mid = (lo + hi) / 2;
        // Grab the dirname for the current dirblock
        let cur = paths[mid];
        if lt_path_by_dirblock(cur, path) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    lo
}

pub fn bisect_path_right(paths: &[&Path], path: &Path) -> usize {
    let mut hi = paths.len();
    let mut lo = 0;
    while lo < hi {
        let mid = (lo + hi) / 2;
        // Grab the dirname for the current dirblock
        let cur = paths[mid];
        if lt_path_by_dirblock(path, cur) {
            hi = mid;
        } else {
            lo = mid + 1;
        }
    }
    lo
}

pub fn pack_stat_metadata(metadata: &Metadata) -> String {
    pack_stat(
        metadata.len(),
        metadata.modified().unwrap().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs(),
        metadata.created().unwrap().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs(),
        metadata.dev(),
        metadata.ino(),
        metadata.mode()
    )
}

pub fn pack_stat(size: u64, mtime: u64, ctime: u64, dev: u64, ino: u64, mode: u32) -> String {
    let size = size & 0xFFFFFFFF;
    let mtime = mtime & 0xFFFFFFFF;
    let ctime = ctime & 0xFFFFFFFF;
    let dev = dev & 0xFFFFFFFF;
    let ino = ino & 0xFFFFFFFF;
    let mode = mode & 0xFFFFFFFF;

    let packed_data = [
        (size >> 24) as u8,
        (size >> 16) as u8,
        (size >> 8) as u8,
        size as u8,
        (mtime >> 24) as u8,
        (mtime >> 16) as u8,
        (mtime >> 8) as u8,
        mtime as u8,
        (ctime >> 24) as u8,
        (ctime >> 16) as u8,
        (ctime >> 8) as u8,
        ctime as u8,
        (dev >> 24) as u8,
        (dev >> 16) as u8,
        (dev >> 8) as u8,
        dev as u8,
        (ino >> 24) as u8,
        (ino >> 16) as u8,
        (ino >> 8) as u8,
        ino as u8,
        (mode >> 24) as u8,
        (mode >> 16) as u8,
        (mode >> 8) as u8,
        mode as u8,
    ];

    base64::encode(&packed_data)
}

pub fn stat_to_minikind(metadata: &Metadata) -> char {
    let file_type = metadata.file_type();
    if file_type.is_dir() {
        'd'
    } else if file_type.is_file() {
        'f'
    } else if file_type.is_symlink() {
        'l'
    } else {
        panic!("Unsupported file type");
    }
}

pub const HEADER_FORMAT_2: &[u8] = b"#bazaar dirstate flat format 2\n";
pub const HEADER_FORMAT_3: &[u8] = b"#bazaar dirstate flat format 3\n";

#[derive(PartialEq, Eq, Debug)]
pub enum Kind {
    Absent,
    File,
    Directory,
    Relocated,
    Symlink,
    TreeReference,
}

impl Kind {
    pub fn to_char(&self) -> char {
        match self {
            Kind::Absent => 'a',
            Kind::File => 'f',
            Kind::Directory => 'd',
            Kind::Relocated => 'r',
            Kind::Symlink => 'l',
            Kind::TreeReference => 't',
        }
    }

    pub fn to_str(&self) -> &str {
        match self {
            Kind::Absent => "absent",
            Kind::File => "file",
            Kind::Directory => "directory",
            Kind::Relocated => "relocated",
            Kind::Symlink => "symlink",
            Kind::TreeReference => "tree-reference",
        }
    }
}

impl ToString for Kind {
    fn to_string(&self) -> String {
        self.to_str().to_string()
    }
}

impl From<String> for Kind {
    fn from(s: String) -> Self {
        match s.as_str() {
            "absent" => Kind::Absent,
            "file" => Kind::File,
            "directory" => Kind::Directory,
            "relocated" => Kind::Relocated,
            "symlink" => Kind::Symlink,
            "tree-reference" => Kind::TreeReference,
            _ => panic!("Unknown kind: {}", s),
        }
    }
}

impl From<char> for Kind {
    fn from(c: char) -> Self {
        match c {
            'a' => Kind::Absent,
            'f' => Kind::File,
            'd' => Kind::Directory,
            'r' => Kind::Relocated,
            'l' => Kind::Symlink,
            't' => Kind::TreeReference,
            _ => panic!("Unknown kind: {}", c),
        }
    }
}

pub enum YesNo {
    Yes,
    No,
}

/// _header_state and _dirblock_state represent the current state
/// of the dirstate metadata and the per-row data respectiely.
/// In future we will add more granularity, for instance _dirblock_state
/// will probably support partially-in-memory as a separate variable,
/// allowing for partially-in-memory unmodified and partially-in-memory
/// modified states.
#[derive(PartialEq, Eq, Debug)]
pub enum MemoryState {
    /// indicates that no data is in memory
    NotInMemory,

    /// indicates that what we have in memory is the same as is on disk
    InMemoryUnmodified,

    /// indicates that we have a modified version of what is on disk.
    InMemoryModified,
    InMemoryHashModified,
}
