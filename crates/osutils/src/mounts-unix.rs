use lazy_static::lazy_static;
use log::{debug, warn};
use std::collections::HashSet;
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

fn sort_mounts(mounts: &mut [MountEntry]) {
    mounts.sort_by(|a, b| b.path.as_os_str().len().cmp(&a.path.as_os_str().len()));
}

#[cfg(target_os = "linux")]
#[test]
fn test_sort_mounts() {
    let mut mounts = vec![
        MountEntry {
            path: PathBuf::from("/"),
            fs_type: "ext4".to_string(),
            options: "rw,relatime,errors=remount-ro".to_string(),
        },
        MountEntry {
            path: PathBuf::from("/var"),
            fs_type: "ext4".to_string(),
            options: "rw,relatime,errors=remount-ro".to_string(),
        },
        MountEntry {
            path: PathBuf::from("/var/blah"),
            fs_type: "ext4".to_string(),
            options: "rw,relatime,errors=remount-ro".to_string(),
        },
    ];
    sort_mounts(&mut mounts);
    assert_eq!(
        vec!["/var/blah", "/var", "/"],
        mounts
            .iter()
            .map(|m| m.path.to_str().unwrap())
            .collect::<Vec<_>>()
    );
}

#[cfg(target_os = "linux")]
fn load_mounts() -> Vec<MountEntry> {
    let mut mounts: Vec<MountEntry> = read_mtab("/proc/mounts").collect();
    sort_mounts(&mut mounts);
    mounts
}

#[cfg(target_os = "macos")]
fn parse_mount_line(line: &str) -> Option<MountEntry> {
    if line.is_empty() {
        return None;
    }
    if line.starts_with("#") {
        return None;
    }
    let parts: Vec<&str> = line.split_whitespace().collect();
    if parts.len() < 3 {
        return None;
    }
    let path = PathBuf::from(parts[2]);
    let fs_type = parts[0].to_string();
    let options = parts[3..].join(" ");
    Some(MountEntry {
        path,
        fs_type,
        options,
    })
}

#[cfg(target_os = "macos")]
#[test]
fn test_parse_mount_line() {
    let line = "devfs on /dev (devfs, local, nobrowse)";
    let mount_entry = parse_mount_line(line).unwrap();
    assert_eq!(mount_entry.path, PathBuf::from("/dev"));
    assert_eq!(mount_entry.fs_type, "devfs");
    assert_eq!(mount_entry.options, "local, nobrowse");
}

#[cfg(target_os = "macos")]
fn load_mounts() -> Vec<MountEntry> {
    // macOS does not have a /proc/mounts equivalent, so we use the output of
    // `mount` command
    //
    // TODO: find a more robust and efficient way to get mount information
    let output = std::process::Command::new("mount")
        .output()
        .expect("Failed to execute mount command");

    let stdout = String::from_utf8_lossy(&output.stdout);

    let mut mounts = Vec::new();
    for line in stdout.lines() {
        if let Some(mount_entry) = parse_mount_line(line) {
            mounts.push(mount_entry);
        }
    }

    sort_mounts(&mut mounts);
    mounts
}

#[cfg(target_os = "linux")]
#[test]
fn test_load_mounts() {
    let mounts = load_mounts();
    assert!(!mounts.is_empty());
    assert!(mounts[mounts.len() - 1].path == PathBuf::from("/"));
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

fn get_fs_type_ext<P: AsRef<Path>>(entries: &[MountEntry], path: P) -> Option<&str> {
    let mut seen = HashSet::new();
    let mut path = path.as_ref().to_path_buf();
    loop {
        let entry = find_mount_entry(entries, path)?;
        if entry.fs_type == "overlay" {
            path = extract_option(&entry.options, "upperdir").map(PathBuf::from)?;
            if !seen.insert(path.clone()) {
                warn!("Loop in overlayfs mounts {:?}", seen);
                return None;
            }
        } else {
            return Some(entry.fs_type.as_str());
        }
    }
}

#[cfg(target_os = "linux")]
#[test]
fn test_get_fs_type() {
    let mounts = vec![MountEntry {
        path: PathBuf::from("/"),
        fs_type: "ext4".to_string(),
        options: "rw,relatime,errors=remount-ro".to_string(),
    }];
    assert!(get_fs_type_ext(&mounts, "/") == Some("ext4"));
    assert!(get_fs_type_ext(&mounts, "/etc/passwd") == Some("ext4"));
}

#[cfg(target_os = "linux")]
#[test]
fn test_get_fs_type_overlay() {
    let mut mounts = vec![
        MountEntry {
            path: PathBuf::from("/var/blah"),
            fs_type: "ext4".to_string(),
            options: "rw,relatime,errors=remount-ro".to_string(),
        },
        MountEntry {
            path: PathBuf::from("/"),
            fs_type: "overlay".to_string(),
            options: "rw,relatime,errors=remount-ro,upperdir=/var/blah".to_string(),
        },
    ];
    sort_mounts(&mut mounts);
    assert_eq!(get_fs_type_ext(&mounts, "/var/blah"), Some("ext4"));
    assert_eq!(get_fs_type_ext(&mounts, "/"), Some("ext4"));
    assert_eq!(get_fs_type_ext(&mounts, "/etc/passwd"), Some("ext4"));
    let mounts = vec![MountEntry {
        path: PathBuf::from("/"),
        fs_type: "overlay".to_string(),
        options: "rw,relatime,errors=remount-ro".to_string(),
    }];
    assert!(get_fs_type_ext(&mounts, "/").is_none());
    let mounts = vec![MountEntry {
        path: PathBuf::from("/"),
        fs_type: "overlay".to_string(),
        options: "rw,relatime,errors=remount-ro,upperdir=/foo".to_string(),
    }];
    assert!(get_fs_type_ext(&mounts, "/").is_none());
}

pub fn get_fs_type<P: AsRef<Path>>(path: P) -> Option<String> {
    get_fs_type_ext(&MOUNTS, path.as_ref()).map(|s| s.to_string())
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
