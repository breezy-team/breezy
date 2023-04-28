use lazy_static::lazy_static;
use log::debug;
use std::ffi::OsString;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::os::unix::ffi::OsStringExt;
use std::path::{Path, PathBuf};

// Read a mtab-style file
pub fn read_mtab<P: AsRef<Path>>(path: P) -> impl Iterator<Item = (PathBuf, String)> {
    let file = File::open(path).unwrap();
    let reader = BufReader::new(file);
    reader
        .lines()
        .filter_map(|line| line.ok())
        .filter(|line| !line.starts_with('#'))
        .filter_map(|line| {
            let cols: Vec<Vec<u8>> = line
                .split_whitespace()
                .map(|s| s.as_bytes().to_vec())
                .collect();
            if cols.len() >= 3 {
                let path = PathBuf::from(OsString::from_vec(cols[1].clone()));
                let fs_type = String::from_utf8_lossy(&cols[2]).to_string();
                Some((path, fs_type))
            } else {
                None
            }
        })
}

fn load_mounts() -> Vec<(PathBuf, String)> {
    let mut mounts: Vec<(PathBuf, String)> = read_mtab("/proc/mounts").collect();
    mounts.sort_by(|a, b| a.0.as_os_str().len().cmp(&b.0.as_os_str().len()));
    mounts
}

#[cfg(target_os = "linux")]
#[test]
fn test_load_mounts() {
    let mounts = load_mounts();
    assert!(!mounts.is_empty());
    assert!(mounts[0].0 == PathBuf::from("/"));
}

pub fn get_fs_type<P: AsRef<Path>>(path: P) -> Option<String> {
    lazy_static! {
        static ref MOUNTS: Vec<(PathBuf, String)> = load_mounts();
    }
    let path = path.as_ref();

    for (mount_path, fs_type) in MOUNTS.iter() {
        if super::path::is_inside(mount_path, path) {
            return Some(fs_type.clone());
        }
    }
    None
}

pub fn supports_hardlinks<P: AsRef<Path>>(path: P) -> Option<bool> {
    let fs_type = get_fs_type(path.as_ref())?;
    match fs_type.as_str() {
        "ext2" | "ext3" | "ext4" | "btrfs" | "xfs" | "jfs" | "reiserfs" | "zfs" => Some(true),
        "vfat" | "ntfs" => Some(false),
        _ => {
            debug!("Unknown fs type: {}", fs_type);
            Some(false)
        }
    }
}

pub fn supports_executable<P: AsRef<Path>>(path: P) -> Option<bool> {
    let fs_type = get_fs_type(path.as_ref())?;
    match fs_type.as_str() {
        "vfat" | "ntfs" => Some(false),
        "ext2" | "ext3" | "ext4" | "btrfs" | "xfs" | "jfs" | "reiserfs" | "zfs" => Some(true),
        _ => {
            debug!("Unknown fs type: {}", fs_type);
            Some(true)
        }
    }
}

pub fn supports_symlinks<P: AsRef<Path>>(path: P) -> Option<bool> {
    let fs_type = get_fs_type(path.as_ref())?;
    match fs_type.as_str() {
        "vfat" | "ntfs" => Some(false), // Maybe?
        "ext2" | "ext3" | "ext4" | "btrfs" | "xfs" | "jfs" | "reiserfs" | "zfs" => Some(true),
        _ => {
            debug!("Unknown fs type: {}", fs_type);
            Some(true)
        }
    }
}

/// Return True if 'readonly' has POSIX semantics, False otherwise.
///
/// Notably, a win32 readonly file cannot be deleted, unlike POSIX where the
/// directory controls creation/deletion, etc.
///
/// And under win32, readonly means that the directory itself cannot be
/// deleted.  The contents of a readonly directory can be changed, unlike POSIX
/// where files in readonly directories cannot be added, deleted or renamed.
pub fn supports_posix_readonly() -> bool {
    true
}
