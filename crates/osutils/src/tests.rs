use crate::chunks_to_lines;
use crate::path::{accessible_normalized_filename, inaccessible_normalized_filename};
use std::path::{Path, PathBuf};

fn assert_chunks_to_lines(input: Vec<&str>, expected: Vec<&str>) {
    let iter = input.iter().map(|l| Ok::<&[u8], String>(l.as_bytes()));
    let got = chunks_to_lines(iter);
    let got = got
        .map(|l| String::from_utf8_lossy(l.unwrap().as_ref()).to_string())
        .collect::<Vec<_>>();
    assert_eq!(got, expected);
}

#[test]
fn test_chunks_to_lines() {
    assert_chunks_to_lines(vec!["a"], vec!["a"]);
    assert_chunks_to_lines(vec!["a\n"], vec!["a\n"]);
    assert_chunks_to_lines(vec!["a\nb\n"], vec!["a\n", "b\n"]);
    assert_chunks_to_lines(vec!["a\n", "b\n"], vec!["a\n", "b\n"]);
    assert_chunks_to_lines(vec!["a", "\n", "b", "\n"], vec!["a\n", "b\n"]);
    assert_chunks_to_lines(vec!["a", "a", "\n", "b", "\n"], vec!["aa\n", "b\n"]);
    assert_chunks_to_lines(vec![""], vec![]);
}

#[test]
fn test_is_inside() {
    fn is_inside(path: &str, dir: &str) -> bool {
        crate::path::is_inside(Path::new(path), Path::new(dir))
    }
    assert!(is_inside("a", "a"));
    assert!(!is_inside("a", "b"));
    assert!(is_inside("a", "a/b"));
    assert!(!is_inside("b", "a/b"));
    assert!(is_inside("a/b", "a/b"));
    assert!(!is_inside("a/b", "a/c"));
    assert!(is_inside("a/b", "a/b/c"));
    assert!(!is_inside("a/b/c", "a/b"));
    assert!(is_inside("", "a"));
    assert!(!is_inside("a", ""));
}

#[test]
fn test_is_inside_any() {
    fn is_inside_any(path: &str, dirs: &[&str]) -> bool {
        let dirs = dirs.iter().map(Path::new).collect::<Vec<&Path>>();
        crate::path::is_inside_any(dirs.as_slice(), Path::new(path))
    }
    assert!(is_inside_any("a", &["a"]));
    assert!(!is_inside_any("a", &["b"]));
    assert!(is_inside_any("a/b", &["a"]));
    assert!(!is_inside_any("a/b", &["b"]));
    assert!(is_inside_any("a/b", &["a/b"]));
    assert!(!is_inside_any("a/b", &["a/c"]));
    assert!(!is_inside_any("a/b", &["a/b/c"]));
    assert!(is_inside_any("a/b/c", &["a/b"]));
    assert!(!is_inside_any("", &["a"]));
    assert!(is_inside_any("a", &[""]));
    assert!(is_inside_any("a", &["a", "b"]));
    assert!(is_inside_any("a", &["b", "a"]));
    assert!(!is_inside_any("a", &["b", "c"]));
}

#[test]
fn test_is_inside_or_parent_of_any() {
    fn is_inside_or_parent_of_any(path: &str, dirs: &[&str]) -> bool {
        let dirs = dirs.iter().map(Path::new).collect::<Vec<&Path>>();
        crate::path::is_inside_or_parent_of_any(dirs.as_slice(), Path::new(path))
    }
    assert!(is_inside_or_parent_of_any("a", &["a"]));
    assert!(!is_inside_or_parent_of_any("a", &["b"]));
    assert!(is_inside_or_parent_of_any("a/b", &["a"]));
    assert!(!is_inside_or_parent_of_any("a/b", &["b"]));
    assert!(is_inside_or_parent_of_any("a/b", &["a/b"]));
    assert!(!is_inside_or_parent_of_any("a/b", &["a/c"]));
    assert!(is_inside_or_parent_of_any("a/b", &["a/b/c"]));
    assert!(is_inside_or_parent_of_any("a/b/c", &["a/b"]));
    assert!(is_inside_or_parent_of_any("", &["a"]));
    assert!(is_inside_or_parent_of_any("a", &[""]));
    assert!(is_inside_or_parent_of_any("a", &["a", "b"]));
    assert!(is_inside_or_parent_of_any("a", &["b", "a"]));
    assert!(!is_inside_or_parent_of_any("a", &["b", "c"]));
    assert!(is_inside_or_parent_of_any("a/b", &["a", "b"]));
    assert!(is_inside_or_parent_of_any("a/b", &["b", "a"]));
}

#[test]
fn test_inaccessible_normalized_filename() {
    assert_eq!(
        inaccessible_normalized_filename(Path::new("a/b")),
        Some((PathBuf::from("a/b"), true))
    );
    assert_eq!(
        inaccessible_normalized_filename(Path::new("a/µ")),
        Some((PathBuf::from("a/µ"), true))
    );
}

#[test]
fn test_access_normalized_filename() {
    assert_eq!(
        accessible_normalized_filename(Path::new("a/b")),
        Some((PathBuf::from("a/b"), true))
    );
    assert_eq!(
        accessible_normalized_filename(Path::new("a/µ")),
        Some((PathBuf::from("a/µ"), true))
    );
}
