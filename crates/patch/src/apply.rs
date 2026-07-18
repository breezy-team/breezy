//! Applying patches to a working tree without invoking patch(1).
//!
//! The heavy lifting lives in [`patchkit::apply_tree`]; this drives it over a
//! parsed patch stream and shapes the result into the errors breezy expects.

use patchkit::apply::ApplyOptions;
use patchkit::apply_tree::{apply_to_tree, ApplyToTreeOptions};
use patchkit::unified::{parse_patches, PlainOrBinaryPatch};
use std::io::Write;
use std::path::Path;

/// The fuzz patch(1) allows by default: up to this many context lines at either
/// end of a hunk may be ignored to make it match.
const DEFAULT_FUZZ: usize = 2;

/// Suffix patch(1) gives the backup it leaves behind when a hunk fails.
const BACKUP_SUFFIX: &str = ".orig";

pub enum Error {
    /// A patch could not be parsed. patch(1) exits 2 for this.
    Malformed(String),
    /// Some hunk did not apply. patch(1) exits 1 for this.
    Failed(String),
    Io(std::io::Error),
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}

impl From<patchkit::apply_tree::Error> for Error {
    fn from(e: patchkit::apply_tree::Error) -> Self {
        match e {
            patchkit::apply_tree::Error::Io(e) => Error::Io(e),
            patchkit::apply_tree::Error::Malformed(m) => Error::Malformed(m),
        }
    }
}

/// Apply `patches` to the tree at `directory`.
///
/// Application is not atomic: as with patch(1), a file whose hunks fail is left
/// untouched but the files patched before it keep their changes.
#[allow(clippy::too_many_arguments)]
pub fn run_patch<'a, I>(
    directory: &Path,
    patches: I,
    strip: u32,
    reverse: bool,
    dry_run: bool,
    quiet: bool,
    out: &mut dyn Write,
    remove_empty_files: bool,
) -> Result<(), Error>
where
    I: Iterator<Item = &'a [u8]>,
{
    let content: Vec<u8> = patches.flatten().copied().collect();
    let lines = content
        .split_inclusive(|&b| b == b'\n')
        .map(|l| l.to_vec())
        .collect::<Vec<_>>();

    let options = ApplyToTreeOptions {
        apply: ApplyOptions {
            fuzz: DEFAULT_FUZZ,
            max_offset: None,
        },
        strip,
        reverse,
        dry_run,
        backup_suffix: Some(BACKUP_SUFFIX.to_string()),
        remove_empty_files,
    };

    let mut failures = Vec::new();
    // One patch at a time, so a failing file's output goes to the error while
    // the rest is written to `out`, as patch(1) reports them.
    for patch in parse_patches(lines.into_iter()) {
        let patch = patch.map_err(|e| Error::Malformed(format!("{:?}", e)))?;
        let patch = match patch {
            PlainOrBinaryPatch::Plain(p) => p,
            PlainOrBinaryPatch::Binary(_) => {
                return Err(Error::Malformed(
                    "binary patches are not supported".to_string(),
                ))
            }
        };

        let mut captured = Vec::new();
        let sink = (!quiet).then_some(&mut captured as &mut dyn Write);
        let report = apply_to_tree(directory, std::slice::from_ref(&patch), &options, sink)?;

        // patch(1) exits 0 for a fuzzy or offset match; only a rejected hunk is
        // a failure. `applied` allows fuzz where `is_success` would not.
        if report.applied() {
            out.write_all(&captured)?;
        } else {
            failures.push(String::from_utf8_lossy(&captured).to_string());
        }
    }

    if !failures.is_empty() {
        return Err(Error::Failed(failures.concat()));
    }
    Ok(())
}
