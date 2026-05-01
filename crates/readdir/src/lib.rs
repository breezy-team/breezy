//! Inode-ordered directory reader.
//!
//! Lists a directory together with the `lstat` result for each entry, in the
//! order returned by `readdir(3)` — typically inode order on common
//! filesystems, which makes follow-up stat calls cheaper. Mirrors the
//! behaviour of the legacy Cython module ``breezy._readdir_pyx``.

#![cfg(unix)]

use std::os::unix::ffi::OsStrExt;
use std::path::Path;

use nix::dir::Dir;
use nix::errno::Errno;
use nix::fcntl::OFlag;
use nix::sys::stat::{FileStat, Mode};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    File,
    Directory,
    CharDev,
    Block,
    Symlink,
    Fifo,
    Socket,
    Unknown,
}

impl Kind {
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::File => "file",
            Kind::Directory => "directory",
            Kind::CharDev => "chardev",
            Kind::Block => "block",
            Kind::Symlink => "symlink",
            Kind::Fifo => "fifo",
            Kind::Socket => "socket",
            Kind::Unknown => "unknown",
        }
    }

    pub fn from_mode(mode: libc::mode_t) -> Kind {
        match mode & libc::S_IFMT {
            libc::S_IFREG => Kind::File,
            libc::S_IFDIR => Kind::Directory,
            libc::S_IFCHR => Kind::CharDev,
            libc::S_IFBLK => Kind::Block,
            libc::S_IFLNK => Kind::Symlink,
            libc::S_IFIFO => Kind::Fifo,
            libc::S_IFSOCK => Kind::Socket,
            _ => Kind::Unknown,
        }
    }
}

pub struct Entry {
    pub ino: libc::ino_t,
    pub name: Vec<u8>,
    pub stat: FileStat,
}

/// An error from [`read_dir`] together with the path it relates to.
#[derive(Debug)]
pub struct Error {
    pub errno: Errno,
    pub path: Vec<u8>,
}

impl Error {
    fn new(errno: Errno, path: Vec<u8>) -> Self {
        Error { errno, path }
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{}: {}",
            self.errno.desc(),
            String::from_utf8_lossy(&self.path)
        )
    }
}

impl std::error::Error for Error {}

/// Read the contents of a directory.
///
/// Returns an entry per child of `path` (excluding `.` and `..`), in the
/// order produced by `readdir(3)`. Each entry includes the inode reported
/// by readdir and the result of `lstat` on the child.
///
/// Entries that disappear between `readdir` and `lstat` (i.e. `lstat`
/// returns `ENOENT`) are skipped silently — typical for transient temp
/// files, and matches the legacy Cython behaviour.
pub fn read_dir(path: &[u8]) -> Result<Vec<Entry>, Error> {
    let dir_path = Path::new(std::ffi::OsStr::from_bytes(path));
    // O_DIRECTORY ensures non-directories (sockets, fifos, regular files)
    // surface as ENOTDIR rather than the type-specific error from open(2)
    // — e.g. ENXIO for a listening Unix socket on Linux. Callers in breezy
    // (notably breezy.bzr._dirstate_helpers_pyx) treat ENOTDIR as the
    // signal that a path is not a walkable directory.
    let mut dir = Dir::open(
        dir_path,
        OFlag::O_RDONLY | OFlag::O_DIRECTORY,
        Mode::empty(),
    )
    .map_err(|e| Error::new(e, path.to_vec()))?;

    let mut entries = Vec::new();
    for entry in dir.iter() {
        let entry = entry.map_err(|e| Error::new(e, path.to_vec()))?;
        let name = entry.file_name().to_bytes();
        if name == b"." || name == b".." {
            continue;
        }
        let name = name.to_vec();

        let mut full_path = path.to_vec();
        if !full_path.is_empty() && !full_path.ends_with(b"/") {
            full_path.push(b'/');
        }
        full_path.extend_from_slice(&name);
        let full = Path::new(std::ffi::OsStr::from_bytes(&full_path));

        let stat = match nix::sys::stat::lstat(full) {
            Ok(s) => s,
            Err(Errno::ENOENT) => continue,
            Err(e) => return Err(Error::new(e, full_path)),
        };

        entries.push(Entry {
            ino: entry.ino(),
            name,
            stat,
        });
    }

    Ok(entries)
}
