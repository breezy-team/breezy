use std::path::Path;
use unicode_normalization::UnicodeNormalization;

// Maybe use ef80escape here?

pub fn inaccessible_normalized_filename(path: &Path) -> Option<(String, bool)> {
    path.to_str().map(|path_str| {
        (path_str.nfc().collect::<String>(), true)
    })
}

pub fn accessible_normalized_filename(path: &Path) -> Option<(String, bool)> {
    path.to_str().map(|path_str| {
        let normalized_path = path_str.nfc().collect::<String>();
        let accessible = normalized_path == path_str;
        (normalized_path, accessible)
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
pub fn normalized_filename(path: &Path) -> (String, bool) {
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
pub fn normalized_filename(path: &Path) -> Option<(String, bool)> {
    inaccessible_normalized_filename(path)
}

pub fn normalizes_filenames() -> bool {
    #[cfg(target_os = "macos")]
    return true;

    #[cfg(not(target_os = "macos"))]
    return false;
}
