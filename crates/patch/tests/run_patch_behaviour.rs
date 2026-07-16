//! Characterisation tests for `run_patch`, pinning the behaviour breezy gets
//! from patch(1) today so a native implementation can be checked against it.

use breezy_patch::invoke::{run_patch, Error};
use std::path::Path;

/// These tests describe patch(1)'s behaviour, so they are meaningless without it.
fn require_patch() {
    let found = std::process::Command::new("patch")
        .arg("--version")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .is_ok();
    assert!(found, "patch(1) is needed to characterise its behaviour");
}

/// Run a patch in a fresh temporary directory, returning the stdout it produced.
fn apply(
    files: &[(&str, &[u8])],
    patch: &[u8],
    dry_run: bool,
) -> (Result<(), Error>, Vec<u8>, tempfile::TempDir) {
    let dir = tempfile::tempdir().unwrap();
    for (name, content) in files {
        let path = dir.path().join(name);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(path, content).unwrap();
    }
    let mut out = Vec::new();
    let r = run_patch(
        dir.path(),
        std::iter::once(patch),
        1,
        false,
        dry_run,
        true,
        None,
        &mut out,
        None,
    );
    (r, out, dir)
}

fn read(dir: &Path, name: &str) -> Option<Vec<u8>> {
    std::fs::read(dir.join(name)).ok()
}

const GOOD: &[u8] = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n";

#[test]
fn applies_a_clean_hunk() {
    require_patch();
    let (r, _out, dir) = apply(&[("f.txt", b"a\nb\nc\n")], GOOD, false);
    assert!(r.is_ok());
    assert_eq!(read(dir.path(), "f.txt").unwrap(), b"a\nB\nc\n");
}

/// patch(1) fuzzes by default: a hunk whose context does not match is still
/// applied, and one whose position is stale slides to where it does match.
#[test]
fn fuzzes_context_and_slides_hunks() {
    require_patch();
    let (r, _out, dir) = apply(&[("f.txt", b"X\nY\nZ\na\nb\nc\n")], GOOD, false);
    assert!(r.is_ok());
    assert_eq!(read(dir.path(), "f.txt").unwrap(), b"X\nY\nZ\na\nB\nc\n");

    let fuzzy = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n DIFFERENT\n-b\n+B\n ALSODIFF\n";
    let (r, _out, dir) = apply(&[("f.txt", b"ctx1\nb\nctx2\n")], fuzzy, false);
    assert!(r.is_ok());
    assert_eq!(read(dir.path(), "f.txt").unwrap(), b"ctx1\nB\nctx2\n");
}

/// Beyond a fuzz of 2, patch(1) gives up and reports the failure on stdout.
#[test]
fn reports_failure_beyond_fuzz_limit() {
    require_patch();
    let too_fuzzy = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,5 +1,5 @@\n X1\n X2\n X3\n-b\n+B\n c4\n";
    let (r, _out, dir) = apply(&[("f.txt", b"c1\nc2\nc3\nb\nc4\n")], too_fuzzy, false);
    match r {
        Err(Error::PatchFailed(code, output)) => {
            assert_eq!(code, 1);
            assert_eq!(output, "1 out of 1 hunk FAILED\n");
        }
        _ => panic!("expected PatchFailed"),
    }
    // The original is left untouched, with a backup alongside it.
    assert_eq!(read(dir.path(), "f.txt").unwrap(), b"c1\nc2\nc3\nb\nc4\n");
    assert_eq!(
        read(dir.path(), "f.txt.orig").unwrap(),
        b"c1\nc2\nc3\nb\nc4\n"
    );
}

/// The backup is a failure fallback only; a clean apply leaves no `.orig`.
#[test]
fn no_backup_when_the_patch_applies() {
    require_patch();
    let (r, _out, dir) = apply(&[("f.txt", b"a\nb\nc\n")], GOOD, false);
    assert!(r.is_ok());
    assert_eq!(read(dir.path(), "f.txt.orig"), None);
}

#[test]
fn creates_a_file_from_dev_null() {
    require_patch();
    let patch = b"--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+one\n+two\n";
    let (r, _out, dir) = apply(&[], patch, false);
    assert!(r.is_ok());
    assert_eq!(read(dir.path(), "new.txt").unwrap(), b"one\ntwo\n");
}

/// `--remove-empty-files`: a file patched down to nothing is deleted.
#[test]
fn removes_a_file_patched_to_empty() {
    require_patch();
    let patch = b"--- a/e.txt\n+++ b/e.txt\n@@ -1 +0,0 @@\n-gone\n";
    let (r, _out, dir) = apply(&[("e.txt", b"gone\n")], patch, false);
    assert!(r.is_ok());
    assert_eq!(read(dir.path(), "e.txt"), None);
}

#[test]
fn dry_run_leaves_the_tree_alone() {
    require_patch();
    let (r, out, dir) = apply(&[("f.txt", b"a\nb\nc\n")], GOOD, true);
    assert!(r.is_ok());
    assert_eq!(read(dir.path(), "f.txt").unwrap(), b"a\nb\nc\n");
    assert_eq!(out, b"");
}

/// A dry run still reports whether the patch would fail.
#[test]
fn dry_run_reports_failure_without_touching_the_tree() {
    require_patch();
    let bad = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,5 +1,5 @@\n X1\n X2\n X3\n-b\n+B\n c4\n";
    let (r, _out, dir) = apply(&[("f.txt", b"c1\nc2\nc3\nb\nc4\n")], bad, true);
    assert!(matches!(r, Err(Error::PatchFailed(1, _))));
    assert_eq!(read(dir.path(), "f.txt").unwrap(), b"c1\nc2\nc3\nb\nc4\n");
    assert_eq!(read(dir.path(), "f.txt.orig"), None);
}

#[test]
fn strips_leading_path_segments() {
    require_patch();
    let patch = b"--- a/sub/f.txt\n+++ b/sub/f.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n";
    let (r, _out, dir) = apply(&[("sub/f.txt", b"a\nb\nc\n")], patch, false);
    assert!(r.is_ok());
    assert_eq!(read(dir.path(), "sub/f.txt").unwrap(), b"a\nB\nc\n");
}

#[test]
fn missing_patch_binary_is_an_invoke_error() {
    let dir = tempfile::tempdir().unwrap();
    let mut out = Vec::new();
    let r = run_patch(
        dir.path(),
        std::iter::empty(),
        0,
        false,
        false,
        true,
        None,
        &mut out,
        Some("/unlikely/to/exist"),
    );
    assert!(matches!(r, Err(Error::PatchInvokeError(_, _, _))));
}

/// Application is not atomic: a file whose hunk fails is left alone, but files
/// patched before it keep their changes, so a failed run can leave the tree
/// partially patched.
#[test]
fn a_failing_file_does_not_roll_back_the_others() {
    require_patch();
    let patch = b"--- a/ok.txt\n+++ b/ok.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n\
                  --- a/bad.txt\n+++ b/bad.txt\n@@ -1,5 +1,5 @@\n Z1\n Z2\n Z3\n-q\n+Q\n r\n";
    let (r, _out, dir) = apply(
        &[("ok.txt", b"a\nb\nc\n"), ("bad.txt", b"p\nq\nr\n")],
        patch,
        false,
    );
    assert!(matches!(r, Err(Error::PatchFailed(1, _))));
    assert_eq!(read(dir.path(), "ok.txt").unwrap(), b"a\nB\nc\n");
    assert_eq!(read(dir.path(), "bad.txt").unwrap(), b"p\nq\nr\n");
}
