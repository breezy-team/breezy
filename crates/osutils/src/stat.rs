//! Portable access to stat-like fields from `std::fs::Metadata`.
//!
//! Windows metadata does not expose Unix-style `dev`/`ino`/`mode`, so this
//! module provides a best-effort mapping. The values returned on Windows are
//! stable enough to detect file replacement (mtime, ctime, size) but do not
//! uniquely identify a file across renames or mounts.

use std::fs::Metadata;

// File-type bits from POSIX <sys/stat.h>. Defined here so callers on Windows
// don't need to depend on `nix` or `libc`.
pub const S_IFMT: u32 = 0o170000;
pub const S_IFREG: u32 = 0o100000;
pub const S_IFDIR: u32 = 0o040000;
pub const S_IFLNK: u32 = 0o120000;

#[cfg(unix)]
pub fn dev(meta: &Metadata) -> u64 {
    use std::os::unix::fs::MetadataExt;
    meta.dev()
}

#[cfg(unix)]
pub fn ino(meta: &Metadata) -> u64 {
    use std::os::unix::fs::MetadataExt;
    meta.ino()
}

#[cfg(unix)]
pub fn mode(meta: &Metadata) -> u32 {
    use std::os::unix::fs::MetadataExt;
    meta.mode()
}

#[cfg(unix)]
pub fn mtime(meta: &Metadata) -> i64 {
    use std::os::unix::fs::MetadataExt;
    meta.mtime()
}

#[cfg(unix)]
pub fn ctime(meta: &Metadata) -> i64 {
    use std::os::unix::fs::MetadataExt;
    meta.ctime()
}

#[cfg(unix)]
pub fn size(meta: &Metadata) -> u64 {
    use std::os::unix::fs::MetadataExt;
    meta.size()
}

#[cfg(windows)]
pub fn dev(_meta: &Metadata) -> u64 {
    // BY_HANDLE_FILE_INFORMATION.dwVolumeSerialNumber would give the real
    // value, but that requires opening the file again. Zero is sufficient for
    // the on-disk hashcache / dirstate formats, which only compare fingerprints
    // for equality.
    0
}

#[cfg(windows)]
pub fn ino(_meta: &Metadata) -> u64 {
    0
}

#[cfg(windows)]
pub fn mode(meta: &Metadata) -> u32 {
    // Synthesize a POSIX-style mode from Windows attributes, matching what
    // CPython does in `os.stat()` on Windows.
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_DIRECTORY: u32 = 0x10;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    const FILE_ATTRIBUTE_READONLY: u32 = 0x1;

    let attrs = meta.file_attributes();
    let perm = if attrs & FILE_ATTRIBUTE_READONLY != 0 {
        0o444
    } else {
        0o666
    };
    let type_ = if meta.file_type().is_symlink() || attrs & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        S_IFLNK
    } else if attrs & FILE_ATTRIBUTE_DIRECTORY != 0 {
        S_IFDIR | 0o111
    } else {
        S_IFREG
    };
    type_ | perm
}

#[cfg(windows)]
fn win_filetime_to_unix_secs(ft_100ns: u64) -> i64 {
    // Windows FILETIME counts 100-nanosecond intervals since 1601-01-01 UTC.
    // Unix epoch starts at 1970-01-01 UTC; the offset is 11644473600 seconds.
    const WINDOWS_TO_UNIX_EPOCH_SECS: i64 = 11_644_473_600;
    (ft_100ns / 10_000_000) as i64 - WINDOWS_TO_UNIX_EPOCH_SECS
}

#[cfg(windows)]
pub fn mtime(meta: &Metadata) -> i64 {
    use std::os::windows::fs::MetadataExt;
    win_filetime_to_unix_secs(meta.last_write_time())
}

#[cfg(windows)]
pub fn ctime(meta: &Metadata) -> i64 {
    use std::os::windows::fs::MetadataExt;
    win_filetime_to_unix_secs(meta.creation_time())
}

#[cfg(windows)]
pub fn size(meta: &Metadata) -> u64 {
    meta.len()
}

pub fn is_regular_file(mode: u32) -> bool {
    mode & S_IFMT == S_IFREG
}

pub fn is_symlink(mode: u32) -> bool {
    mode & S_IFMT == S_IFLNK
}
