use std::path::{Path, PathBuf};
use std::collections::HashSet;
use std::os::unix::fs::PermissionsExt;
use unicode_normalization::{UnicodeNormalization,is_nfc};

pub fn is_inside(dir: &Path, fname: &Path) -> bool {
    fname.starts_with(&dir)
}

pub fn is_inside_any(dir_list: &[&Path], fname: &Path) -> bool {
    for dirname in dir_list {
        if is_inside(dirname, fname) {
            return true;
        }
    }
    false
}

pub fn is_inside_or_parent_of_any(dir_list: &[&Path], fname: &Path) -> bool {
    for dirname in dir_list {
        if is_inside(dirname, fname) || is_inside(fname, dirname) {
            return true;
        }
    }
    false
}

pub fn minimum_path_selection(paths: HashSet<&Path>) -> HashSet<&Path> {
    if paths.len() < 2 {
        return paths.clone();
    }

    let mut sorted_paths: Vec<&Path> = paths.iter().copied().collect();
    sorted_paths.sort_by_key(|&path| path.components().collect::<Vec<_>>());

    let mut search_paths = vec![sorted_paths[0]];
    for &path in &sorted_paths[1..] {
        if !is_inside(search_paths.last().unwrap(), path) {
            search_paths.push(path);
        }
    }

    search_paths.into_iter().collect()
}

#[cfg(target_os = "windows")]
pub fn find_executable_on_path(name: &str) -> Option<String> {
    use std::env;
    use winreg::enums::{HKEY_LOCAL_MACHINE, KEY_QUERY_VALUE};
    use winreg::RegKey;

    let exts = env::var("PATHEXT").unwrap_or_default();
    let exts = exts.split(';').map(|ext| ext.to_lowercase()).collect::<Vec<_>>();
    let (name, exts) = {
        let mut path = PathBuf::from(name);
        let ext = path.extension().and_then(|ext| ext.to_str()).unwrap_or_default().to_lowercase();
        if !exts.is_empty() && !exts.contains(&ext) {
            (path.file_stem().unwrap_or_default().to_str().unwrap_or_default(), vec![ext])
        } else {
            (path.file_stem().unwrap_or_default().to_str().unwrap_or_default(), exts)
        }
    };
    let paths = env::var("PATH").unwrap_or_default();
    let paths = paths.split(';').collect::<Vec<_>>();
    for ext in &exts {
        for path in &paths {
            let exe_path = PathBuf::from(path).join(format!("{}{}", name, ext));
            if exe_path.is_file() {
                return Some(exe_path.to_str().unwrap_or_default().to_owned());
            }
        }
    }
    if let Ok(reg_key) = RegKey::predef(HKEY_LOCAL_MACHINE).open_subkey(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") {
        if let Ok(value) = reg_key.get_value(name) {
            if let Some(value) = value.as_string() {
                return Some(value);
            }
        }
    }
    None
}

#[cfg(not(target_os = "windows"))]
pub fn find_executable_on_path(name: &str) -> Option<String> {
    use std::env;

    let paths = env::var("PATH").unwrap_or_default();
    let paths = paths.split(':').collect::<Vec<_>>();
    for path in &paths {
        let exe_path = PathBuf::from(path).join(name);
        if let Ok(md) = exe_path.metadata() {
            if md.permissions().mode() & 0o111 != 0 {
                return Some(exe_path.to_str().unwrap_or_default().to_owned());
            }
        }
    }
    None
}

pub fn accessible_normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    path.to_str().map(|path_str| {
        if is_nfc(path_str) {
            (path.to_path_buf(), true)
        } else {
            (PathBuf::from(path_str.nfc().collect::<String>()), true)
        }
    })
}

pub fn inaccessible_normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    path.to_str().map(|path_str| {
        if is_nfc(path_str) {
            (path.to_path_buf(), true)
        } else {
            let normalized_path = path_str.nfc().collect::<String>();
            let accessible = normalized_path == path_str;
            (PathBuf::from(normalized_path), accessible)
        }
    })
}

/// Get the unicode normalized path, and if you can access the file.
///
/// On platforms where the system normalizes filenames (Mac OSX),
/// you can access a file by any path which will normalize correctly.
/// On platforms where the system does not normalize filenames
/// (everything else), you have to access a file by its exact path.
///
/// Internally, bzr only supports NFC normalization, since that is
/// the standard for XML documents.
///
/// So return the normalized path, and a flag indicating if the file
/// can be accessed by that path.
#[cfg(target_os = "macos")]
pub fn normalized_filename(path: &Path) -> (PathBuf, bool) {
    accessible_normalized_filename(path)
}

/// Get the unicode normalized path, and if you can access the file.
///
/// On platforms where the system normalizes filenames (Mac OSX),
/// you can access a file by any path which will normalize correctly.
/// On platforms where the system does not normalize filenames
/// (everything else), you have to access a file by its exact path.
///
/// Internally, bzr only supports NFC normalization, since that is
/// the standard for XML documents.
///
/// So return the normalized path, and a flag indicating if the file
/// can be accessed by that path.

#[cfg(not(target_os = "macos"))]
pub fn normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    inaccessible_normalized_filename(path)
}

pub fn normalizes_filenames() -> bool {
    #[cfg(target_os = "macos")]
    return true;

    #[cfg(not(target_os = "macos"))]
    return false;
}

// Check whether the supplied path is legal.
// This is only required on Windows, so we don't test on other platforms
// right now.
//
#[cfg(not(windows))]
pub fn legal_path(_path: &Path) -> bool {
    true
}

#[cfg(windows)]
use lazy_static::lazy_static;
#[cfg(windows)]
lazy_static! {
use regex::Regex;
static ref VALID_WIN32_PATH_RE: Regex = Regex::new(r#"^([A-Za-z]:[/\\])?[^:<>*"?\|]*$"#).unwrap();
}

#[cfg(windows)]
pub fn legal_path(path: &Path) -> bool {
    VALID_WIN32_PATH_RE.is_match(path)
}