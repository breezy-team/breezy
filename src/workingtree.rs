//! Opening working trees, as ``breezy.workingtree.WorkingTree`` does.
//!
//! The control directory is found through the prober registry in
//! [`crate::controldir`], so the tree that comes back may be native or, when
//! a Python prober claimed the location, backed by a Python tree.

use crate::controldir::{self, Error};
use crate::tree::WorkingTree;

/// Open the working tree at `location`.
pub fn open(location: &str) -> Result<Box<dyn WorkingTree + Send + Sync>, Error> {
    controldir::open(location)?.open_workingtree()
}

/// Open the working tree at `location` even if its format is not
/// supported, as ``WorkingTree.open_downlevel`` does.
pub fn open_downlevel(location: &str) -> Result<Box<dyn WorkingTree + Send + Sync>, Error> {
    controldir::open_unsupported(location)?.open_workingtree()
}

/// Open the working tree containing `file_list` (or `default_directory`
/// when the list is empty) and make the paths tree-relative, as
/// ``WorkingTree.open_containing_paths`` does.
///
/// TODO: with an empty list Python narrows the paths to the current view
/// and tells the user; views are not reachable natively yet, so the empty
/// list is returned as it is.
pub fn open_containing_paths(
    file_list: &[&str],
    default_directory: Option<&str>,
    canonicalize: bool,
    apply_view: bool,
) -> Result<(Box<dyn WorkingTree + Send + Sync>, Vec<String>), Error> {
    let default_directory = default_directory.unwrap_or(".");
    if file_list.is_empty() {
        let (tree, _) = open_containing(Some(default_directory))?;
        return Ok((tree, Vec::new()));
    }
    let joined: Vec<String>;
    let (seed, files): (&str, Vec<&str>) = if default_directory == "." {
        (file_list[0], file_list.to_vec())
    } else {
        joined = file_list
            .iter()
            .map(|f| {
                std::path::Path::new(default_directory)
                    .join(f)
                    .to_string_lossy()
                    .into_owned()
            })
            .collect();
        (
            default_directory,
            joined.iter().map(String::as_str).collect(),
        )
    };
    let (tree, _) = open_containing(Some(seed))?;
    let relpaths = tree.safe_relpath_files(&files, canonicalize, apply_view)?;
    Ok((tree, relpaths))
}

/// Open the working tree containing `location`, searching upwards from it,
/// or containing the current directory when `location` is `None`.
///
/// Returns the tree and the part of `location` below the tree root.
pub fn open_containing(
    location: Option<&str>,
) -> Result<(Box<dyn WorkingTree + Send + Sync>, String), Error> {
    let cwd;
    let location = match location {
        Some(location) => location,
        None => {
            cwd = std::env::current_dir().map_err(|e| Error::Other(e.to_string()))?;
            cwd.to_str().ok_or_else(|| {
                Error::Other(format!(
                    "current directory {} is not valid Unicode",
                    cwd.display()
                ))
            })?
        }
    };
    let (dir, relpath) = controldir::open_containing(location)?;
    Ok((dir.open_workingtree()?, relpath))
}
