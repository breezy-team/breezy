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
