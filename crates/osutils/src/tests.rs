use crate::chunks_to_lines;
use crate::path::{accessible_normalized_filename, inaccessible_normalized_filename};
use std::path::{Path, PathBuf};

fn assert_chunks_to_lines(input: Vec<&str>, expected: Vec<&str>) {
    let iter = input.iter().map(|l| Ok::<&[u8], String>(l.as_bytes()));
    let got = chunks_to_lines(iter);
    let got = got.map(|l| String::from_utf8(l.unwrap())).collect::<Result<Vec<_>, _>>().unwrap();
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
    assert_eq!(is_inside("a", "a"), true);
    assert_eq!(is_inside("a", "b"), false);
    assert_eq!(is_inside("a", "a/b"), true);
    assert_eq!(is_inside("b", "a/b"), false);
    assert_eq!(is_inside("a/b", "a/b"), true);
    assert_eq!(is_inside("a/b", "a/c"), false);
    assert_eq!(is_inside("a/b", "a/b/c"), true);
    assert_eq!(is_inside("a/b/c", "a/b"), false);
    assert_eq!(is_inside("", "a"), true);
    assert_eq!(is_inside("a", ""), false);
}

#[test]
fn test_is_inside_any() {
    fn is_inside_any(path: &str, dirs: &[&str]) -> bool {
        let dirs = dirs.iter().map(Path::new).collect::<Vec<&Path>>();
        crate::path::is_inside_any(dirs.as_slice(), Path::new(path))
    }
    assert_eq!(is_inside_any("a", &["a"]), true);
    assert_eq!(is_inside_any("a", &["b"]), false);
    assert_eq!(is_inside_any("a/b", &["a"]), true);
    assert_eq!(is_inside_any("a/b", &["b"]), false);
    assert_eq!(is_inside_any("a/b", &["a/b"]), true);
    assert_eq!(is_inside_any("a/b", &["a/c"]), false);
    assert_eq!(is_inside_any("a/b", &["a/b/c"]), false);
    assert_eq!(is_inside_any("a/b/c", &["a/b"]), true);
    assert_eq!(is_inside_any("", &["a"]), false);
    assert_eq!(is_inside_any("a", &[""]), true);
    assert_eq!(is_inside_any("a", &["a", "b"]), true);
    assert_eq!(is_inside_any("a", &["b", "a"]), true);
    assert_eq!(is_inside_any("a", &["b", "c"]), false);
}

#[test]
fn test_is_inside_or_parent_of_any() {
    fn is_inside_or_parent_of_any(path: &str, dirs: &[&str]) -> bool {
        let dirs = dirs.iter().map(Path::new).collect::<Vec<&Path>>();
        crate::path::is_inside_or_parent_of_any(dirs.as_slice(), Path::new(path))
    }
    assert_eq!(is_inside_or_parent_of_any("a", &["a"]), true);
    assert_eq!(is_inside_or_parent_of_any("a", &["b"]), false);
    assert_eq!(is_inside_or_parent_of_any("a/b", &["a"]), true);
    assert_eq!(is_inside_or_parent_of_any("a/b", &["b"]), false);
    assert_eq!(is_inside_or_parent_of_any("a/b", &["a/b"]), true);
    assert_eq!(is_inside_or_parent_of_any("a/b", &["a/c"]), false);
    assert_eq!(is_inside_or_parent_of_any("a/b", &["a/b/c"]), true);
    assert_eq!(is_inside_or_parent_of_any("a/b/c", &["a/b"]), true);
    assert_eq!(is_inside_or_parent_of_any("", &["a"]), true);
    assert_eq!(is_inside_or_parent_of_any("a", &[""]), true);
    assert_eq!(is_inside_or_parent_of_any("a", &["a", "b"]), true);
    assert_eq!(is_inside_or_parent_of_any("a", &["b", "a"]), true);
    assert_eq!(is_inside_or_parent_of_any("a", &["b", "c"]), false);
    assert_eq!(is_inside_or_parent_of_any("a/b", &["a", "b"]), true);
    assert_eq!(is_inside_or_parent_of_any("a/b", &["b", "a"]), true);
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
