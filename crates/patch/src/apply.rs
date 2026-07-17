//! Applying patches to a working tree without invoking patch(1).

use patchkit::apply::{apply_fuzzy, ApplyOptions};
use patchkit::unified::{parse_patches, PlainOrBinaryPatch, UnifiedPatch};
use std::io::Write;
use std::path::{Path, PathBuf};

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

/// Strip `strip` leading segments from a patch path.
///
/// `/dev/null` names no file and is returned as-is for the caller to recognise.
fn strip_path(name: &[u8], strip: u32) -> PathBuf {
    let name = String::from_utf8_lossy(name);
    let name = name.split('\t').next().unwrap_or(&name);
    if name == "/dev/null" {
        return PathBuf::from(name);
    }
    PathBuf::from(name.splitn(strip as usize + 1, '/').last().unwrap_or(name))
}

fn is_dev_null(name: &[u8]) -> bool {
    let name = String::from_utf8_lossy(name);
    name.split('\t').next().unwrap_or(&name) == "/dev/null"
}

/// Which file on disk a patch reads from and writes to.
fn target_of(patch: &UnifiedPatch, strip: u32) -> (Option<PathBuf>, Option<PathBuf>) {
    let orig = (!is_dev_null(&patch.orig_name)).then(|| strip_path(&patch.orig_name, strip));
    let modified = (!is_dev_null(&patch.mod_name)).then(|| strip_path(&patch.mod_name, strip));
    (orig, modified)
}

/// Apply one file's worth of patch, returning whether every hunk matched.
///
/// Mirrors patch(1): on failure the target keeps its original content and a
/// `.orig` backup is left beside it, and a file patched to nothing is removed
/// when `remove_empty_files` is set.
fn apply_one(
    directory: &Path,
    patch: &UnifiedPatch,
    strip: u32,
    dry_run: bool,
    remove_empty_files: bool,
    out: &mut dyn Write,
    quiet: bool,
) -> Result<bool, Error> {
    let (orig, modified) = target_of(patch, strip);

    let read_from = orig.as_ref().or(modified.as_ref());
    let Some(read_from) = read_from else {
        return Err(Error::Malformed(
            "patch names /dev/null on both sides".to_string(),
        ));
    };
    let path = directory.join(read_from);

    let original = match std::fs::read(&path) {
        Ok(content) => content,
        // A patch that creates a file has nothing to read.
        Err(e) if e.kind() == std::io::ErrorKind::NotFound && orig.is_none() => Vec::new(),
        Err(e) => return Err(e.into()),
    };

    if !quiet {
        writeln!(out, "patching file {}", read_from.display())?;
    }

    let result = apply_fuzzy(
        &original,
        &patch.hunks,
        &ApplyOptions {
            fuzz: DEFAULT_FUZZ,
            max_offset: None,
        },
    );

    // patch(1) hedges whenever it did not match exactly: any hunk applied at an
    // offset or with fuzz, or any that failed, leaves the original beside the
    // target as a backup.
    let inexact = result
        .hunks
        .iter()
        .any(|h| !h.applied() || h.offset != 0 || h.fuzz != 0);
    if inexact && !dry_run {
        std::fs::write(path.with_extension_appended(BACKUP_SUFFIX), &original)?;
    }

    let applied_cleanly = result.patched.is_some();
    if !applied_cleanly {
        let failed = result.rejected().count();
        if !quiet {
            for hunk in result.rejected() {
                writeln!(out, "Hunk #{} FAILED.", hunk.index + 1)?;
            }
        }
        writeln!(
            out,
            "{} out of {} hunk{} FAILED",
            failed,
            patch.hunks.len(),
            if patch.hunks.len() == 1 { "" } else { "s" }
        )?;
    }

    if dry_run {
        return Ok(applied_cleanly);
    }

    // Each hunk stands on its own, as in patch(1): the ones that matched are
    // written out even when a sibling failed.
    let patched = result
        .partial
        .expect("apply_fuzzy yields content outside a dry run");

    // The patch may rename, in which case the original goes away.
    let write_to = modified.as_ref().unwrap_or(read_from);
    let dest = directory.join(write_to);

    // A file only goes away if the patch that empties it actually applied.
    if applied_cleanly && (modified.is_none() || (remove_empty_files && patched.is_empty())) {
        std::fs::remove_file(&path)?;
        return Ok(true);
    }

    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&dest, &patched)?;
    if dest != path && orig.is_some() {
        std::fs::remove_file(&path)?;
    }
    Ok(applied_cleanly)
}

/// Extend a path's file name, rather than replacing its extension.
trait AppendExtension {
    fn with_extension_appended(&self, suffix: &str) -> PathBuf;
}

impl AppendExtension for Path {
    fn with_extension_appended(&self, suffix: &str) -> PathBuf {
        let mut name = self.as_os_str().to_os_string();
        name.push(suffix);
        PathBuf::from(name)
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
    let mut failures = Vec::new();

    let lines = content
        .split_inclusive(|&b| b == b'\n')
        .map(|l| l.to_vec())
        .collect::<Vec<_>>();
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
        let patch = if reverse { patch.reverse() } else { patch };
        let mut captured = Vec::new();
        let applied = apply_one(
            directory,
            &patch,
            strip,
            dry_run,
            remove_empty_files,
            &mut captured,
            quiet,
        )?;
        if applied {
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
