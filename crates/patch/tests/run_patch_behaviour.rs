//! Characterisation tests for `run_patch`.
//!
//! Every case runs against both patch(1) and the native implementation and
//! requires them to agree, so the two stay interchangeable.

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

/// What a run did, in terms both implementations can be compared on.
#[derive(Debug, PartialEq, Eq)]
struct Outcome {
    /// Err holds the failure text; patch(1) reports it on stdout.
    result: Result<(), String>,
    stdout: Vec<u8>,
}

fn populate(dir: &Path, files: &[(&str, &[u8])]) {
    for (name, content) in files {
        let path = dir.join(name);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(path, content).unwrap();
    }
}

fn via_subprocess(dir: &Path, patch: &[u8], dry_run: bool, reverse: bool) -> Outcome {
    let mut stdout = Vec::new();
    let r = breezy_patch::invoke::run_patch(
        dir,
        std::iter::once(patch),
        1,
        reverse,
        dry_run,
        true,
        None,
        &mut stdout,
        None,
    );
    Outcome {
        result: match r {
            Ok(()) => Ok(()),
            Err(breezy_patch::invoke::Error::PatchFailed(_, text)) => Err(text),
            Err(_) => Err("<invoke error>".to_string()),
        },
        stdout,
    }
}

fn via_native(dir: &Path, patch: &[u8], dry_run: bool, reverse: bool) -> Outcome {
    let mut stdout = Vec::new();
    let r = breezy_patch::apply::run_patch(
        dir,
        std::iter::once(patch),
        1,
        reverse,
        dry_run,
        true,
        &mut stdout,
        true,
    );
    Outcome {
        result: match r {
            Ok(()) => Ok(()),
            Err(breezy_patch::apply::Error::Failed(text)) => Err(text),
            Err(breezy_patch::apply::Error::Malformed(text)) => Err(text),
            Err(breezy_patch::apply::Error::Io(e)) => Err(format!("<io: {}>", e)),
        },
        stdout,
    }
}

/// Snapshot a tree as a sorted list of (relative path, content).
fn snapshot(dir: &Path) -> Vec<(String, Vec<u8>)> {
    fn walk(base: &Path, dir: &Path, acc: &mut Vec<(String, Vec<u8>)>) {
        let mut entries: Vec<_> = std::fs::read_dir(dir)
            .unwrap()
            .map(|e| e.unwrap())
            .collect();
        entries.sort_by_key(|e| e.path());
        for entry in entries {
            let path = entry.path();
            if path.is_dir() {
                walk(base, &path, acc);
            } else {
                let rel = path
                    .strip_prefix(base)
                    .unwrap()
                    .to_string_lossy()
                    .to_string();
                acc.push((rel, std::fs::read(&path).unwrap()));
            }
        }
    }
    let mut acc = Vec::new();
    walk(dir, dir, &mut acc);
    acc
}

/// Run `patch` against both implementations and require identical results.
///
/// Returns the resulting tree, which both produced.
fn both(files: &[(&str, &[u8])], patch: &[u8], dry_run: bool) -> (Outcome, Vec<(String, Vec<u8>)>) {
    both_with(files, patch, dry_run, false)
}

fn both_with(
    files: &[(&str, &[u8])],
    patch: &[u8],
    dry_run: bool,
    reverse: bool,
) -> (Outcome, Vec<(String, Vec<u8>)>) {
    require_patch();

    let sub_dir = tempfile::tempdir().unwrap();
    populate(sub_dir.path(), files);
    let sub = via_subprocess(sub_dir.path(), patch, dry_run, reverse);
    let sub_tree = snapshot(sub_dir.path());

    let nat_dir = tempfile::tempdir().unwrap();
    populate(nat_dir.path(), files);
    let nat = via_native(nat_dir.path(), patch, dry_run, reverse);
    let nat_tree = snapshot(nat_dir.path());

    assert_eq!(
        sub.result.is_ok(),
        nat.result.is_ok(),
        "implementations disagree on success:\n  patch(1): {:?}\n  native:   {:?}",
        sub.result,
        nat.result
    );
    assert_eq!(
        sub_tree, nat_tree,
        "implementations produced different trees"
    );
    (sub, sub_tree)
}

/// Look a file up in a tree snapshot.
fn file<'a>(tree: &'a [(String, Vec<u8>)], name: &str) -> Option<&'a [u8]> {
    tree.iter()
        .find(|(n, _)| n == name)
        .map(|(_, c)| c.as_slice())
}

const GOOD: &[u8] = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n";

#[test]
fn applies_a_clean_hunk() {
    let (o, tree) = both(&[("f.txt", b"a\nb\nc\n")], GOOD, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "f.txt").unwrap(), b"a\nB\nc\n");
}

/// patch(1) fuzzes by default: a hunk whose context does not match is still
/// applied, and one whose position is stale slides to where it does match.
#[test]
fn fuzzes_context_and_slides_hunks() {
    let (o, tree) = both(&[("f.txt", b"X\nY\nZ\na\nb\nc\n")], GOOD, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "f.txt").unwrap(), b"X\nY\nZ\na\nB\nc\n");

    let fuzzy = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n DIFFERENT\n-b\n+B\n ALSODIFF\n";
    let (o, tree) = both(&[("f.txt", b"ctx1\nb\nctx2\n")], fuzzy, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "f.txt").unwrap(), b"ctx1\nB\nctx2\n");
}

/// Beyond a fuzz of 2, patch(1) gives up and reports the failure on stdout.
#[test]
fn reports_failure_beyond_fuzz_limit() {
    let too_fuzzy = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,5 +1,5 @@\n X1\n X2\n X3\n-b\n+B\n c4\n";
    let (o, tree) = both(&[("f.txt", b"c1\nc2\nc3\nb\nc4\n")], too_fuzzy, false);
    assert_eq!(o.result, Err("1 out of 1 hunk FAILED\n".to_string()));
    // The original is left untouched, with a backup alongside it.
    assert_eq!(file(&tree, "f.txt").unwrap(), b"c1\nc2\nc3\nb\nc4\n");
    assert_eq!(file(&tree, "f.txt.orig").unwrap(), b"c1\nc2\nc3\nb\nc4\n");
}

/// A backup is left whenever the match was not exact, even on success: only a
/// hunk that applied at its stated position with all context intact skips it.
#[test]
fn backs_up_the_original_unless_the_match_was_exact() {
    let (o, tree) = both(&[("f.txt", b"a\nb\nc\n")], GOOD, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "f.txt.orig"), None);

    // Applied, but at an offset.
    let (o, tree) = both(&[("f.txt", b"X\nY\nZ\na\nb\nc\n")], GOOD, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "f.txt.orig").unwrap(), b"X\nY\nZ\na\nb\nc\n");

    // Applied, but with context fuzzed away.
    let fuzzy = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n DIFFERENT\n-b\n+B\n ALSODIFF\n";
    let (o, tree) = both(&[("f.txt", b"ctx1\nb\nctx2\n")], fuzzy, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "f.txt.orig").unwrap(), b"ctx1\nb\nctx2\n");
}

#[test]
fn creates_a_file_from_dev_null() {
    let patch = b"--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+one\n+two\n";
    let (o, tree) = both(&[], patch, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "new.txt").unwrap(), b"one\ntwo\n");
}

/// `--remove-empty-files`: a file patched down to nothing is deleted.
#[test]
fn removes_a_file_patched_to_empty() {
    let patch = b"--- a/e.txt\n+++ b/e.txt\n@@ -1 +0,0 @@\n-gone\n";
    let (o, tree) = both(&[("e.txt", b"gone\n")], patch, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "e.txt"), None);
}

#[test]
fn dry_run_leaves_the_tree_alone() {
    let (o, tree) = both(&[("f.txt", b"a\nb\nc\n")], GOOD, true);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "f.txt").unwrap(), b"a\nb\nc\n");
    assert_eq!(o.stdout, b"");
}

/// A dry run still reports whether the patch would fail.
#[test]
fn dry_run_reports_failure_without_touching_the_tree() {
    let bad = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,5 +1,5 @@\n X1\n X2\n X3\n-b\n+B\n c4\n";
    let (o, tree) = both(&[("f.txt", b"c1\nc2\nc3\nb\nc4\n")], bad, true);
    assert!(o.result.is_err());
    assert_eq!(file(&tree, "f.txt").unwrap(), b"c1\nc2\nc3\nb\nc4\n");
    assert_eq!(file(&tree, "f.txt.orig"), None);
}

#[test]
fn strips_leading_path_segments() {
    let patch = b"--- a/sub/f.txt\n+++ b/sub/f.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n";
    let (o, tree) = both(&[("sub/f.txt", b"a\nb\nc\n")], patch, false);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "sub/f.txt").unwrap(), b"a\nB\nc\n");
}

/// Hunks are independent: one that fails does not hold back its siblings, so a
/// file can be left with some of a patch applied to it.
#[test]
fn a_failing_hunk_does_not_hold_back_the_others() {
    let patch = b"--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n-line0\n+CHANGED0\n line1\n\
                  @@ -3,1 +3,1 @@\n-line3\n+CHANGED3\n";
    let (o, tree) = both(
        &[("f.txt", b"perturbed\nline1\nline2\nline3\n")],
        patch,
        false,
    );
    assert!(o.result.is_err());
    // Hunk 1 failed, but hunk 2 still applied.
    assert_eq!(
        file(&tree, "f.txt").unwrap(),
        b"perturbed\nline1\nline2\nCHANGED3\n"
    );
    assert_eq!(
        file(&tree, "f.txt.orig").unwrap(),
        b"perturbed\nline1\nline2\nline3\n"
    );
}

/// Application is not atomic: a file whose hunk fails is left alone, but files
/// patched before it keep their changes, so a failed run can leave the tree
/// partially patched.
#[test]
fn a_failing_file_does_not_roll_back_the_others() {
    let patch = b"--- a/ok.txt\n+++ b/ok.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n\
                  --- a/bad.txt\n+++ b/bad.txt\n@@ -1,5 +1,5 @@\n Z1\n Z2\n Z3\n-q\n+Q\n r\n";
    let (o, tree) = both(
        &[("ok.txt", b"a\nb\nc\n"), ("bad.txt", b"p\nq\nr\n")],
        patch,
        false,
    );
    assert!(o.result.is_err());
    assert_eq!(file(&tree, "ok.txt").unwrap(), b"a\nB\nc\n");
    assert_eq!(file(&tree, "bad.txt").unwrap(), b"p\nq\nr\n");
}

#[test]
fn missing_patch_binary_is_an_invoke_error() {
    let dir = tempfile::tempdir().unwrap();
    let mut out = Vec::new();
    let r = breezy_patch::invoke::run_patch(
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
    assert!(matches!(
        r,
        Err(breezy_patch::invoke::Error::PatchInvokeError(_, _, _))
    ));
}

/// A reverse run undoes a patch, and both implementations agree on the result.
#[test]
fn reverse_undoes_a_patch() {
    let (o, tree) = both_with(&[("f.txt", b"a\nB\nc\n")], GOOD, false, true);
    assert_eq!(o.result, Ok(()));
    assert_eq!(file(&tree, "f.txt").unwrap(), b"a\nb\nc\n");
}

/// Reversing a patch that was never applied fails rather than corrupting.
#[test]
fn reverse_of_an_unapplied_patch_fails() {
    let (o, _tree) = both_with(&[("f.txt", b"q\nr\ns\n")], GOOD, false, true);
    assert!(o.result.is_err());
}
