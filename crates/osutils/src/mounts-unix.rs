use lazy_static::lazy_static;
use log::{debug, warn};
use std::ffi::OsString;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::os::unix::ffi::OsStringExt;
use std::path::{Path, PathBuf};

pub struct MountEntry {
    pub path: PathBuf,
    pub fs_type: String,
    pub options: String,
}

// Read a mtab-style file
pub fn read_mtab<P: AsRef<Path>>(path: P) -> impl Iterator<Item = MountEntry> {
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
                let options = String::from_utf8_lossy(&cols[3]).to_string();
                Some(MountEntry {
                    path,
                    fs_type,
                    options,
                })
            } else {
                None
            }
        })
}

fn load_mounts() -> Vec<MountEntry> {
    let mut mounts: Vec<MountEntry> = read_mtab("/proc/mounts").collect();
    mounts.sort_by(|a, b| a.path.as_os_str().len().cmp(&b.path.as_os_str().len()));
    mounts
}

#[cfg(target_os = "linux")]
#[test]
fn test_load_mounts() {
    let mounts = load_mounts();
    assert!(!mounts.is_empty());
    assert!(mounts[0].path == PathBuf::from("/"));
}

pub fn find_mount_entry<P: AsRef<Path>>(entries: &[MountEntry], path: P) -> Option<&MountEntry> {
    entries
        .iter()
        .find(|&entry| super::path::is_inside(entry.path.as_path(), path.as_ref()))
}

lazy_static! {
    static ref MOUNTS: Vec<MountEntry> = load_mounts();
}

fn extract_option<'a>(options: &'a str, name: &str) -> Option<&'a str> {
    for option in options.split(',') {
        let parts: Vec<&str> = option.split('=').collect();
        if parts.len() == 2 && parts[0] == name {
            return Some(parts[1]);
        }
    }

    warn!("Could not find upperdir in overlay options {:?}", options);

    None
}

pub fn get_fs_type<P: AsRef<Path>>(path: P) -> Option<String> {
    let entry = find_mount_entry(&MOUNTS, path);
    if let Some(entry) = entry {
        if entry.fs_type == "overlay" {
            get_fs_type(PathBuf::from(extract_option(&entry.options, "upperdir")?))
        } else {
            Some(entry.fs_type.clone())
        }
    } else {
        None
    }
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
