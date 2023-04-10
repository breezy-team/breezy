use std::path::Path;

#[cfg(target_os = "macos")]
use unicode_normalization::UnicodeNormalization;

#[cfg(target_os = "macos")]
pub fn normalized_filename(path: &Path) -> (String, bool) {
    let os_str = path.as_os_str();
    let path_str = os_str.to_str().unwrap();
    let normalized_path = path_str.nfc().collect::<String>();
    let is_accessible = normalized_path == path_str;

    (normalized_path, is_accessible)
}

#[cfg(not(target_os = "macos"))]
pub fn normalized_filename(path: &Path) -> (String, bool) {
    let os_str = path.as_os_str();
    let path_str = os_str.to_str().unwrap();
    let normalized_path = path_str.to_owned();

    (normalized_path, true)
}
