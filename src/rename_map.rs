//! Rename detection by content similarity.
//!
//! A port of the hashing and matching core of `breezy.rename_map`. Every file
//! is fingerprinted by hashing each pair of adjacent lines (an "edge"). A
//! missing versioned file and an unversioned candidate that share many rare
//! edges are probably the same file, renamed outside version control. Once
//! files are paired, missing directories are matched to unversioned ones by
//! comparing their children.
//!
//! Files are identified by an opaque tag type `T`, so the same code serves
//! any tree implementation whatever it uses to identify files.
//!
//! Walking the tree, reporting progress and applying the resulting inventory
//! delta stay in Python; see `breezy.rename_map.RenameMap`.

use std::collections::{HashMap, HashSet};
use std::convert::Infallible;
use std::hash::{DefaultHasher, Hash, Hasher};

/// Edge hashes are reduced modulo this value to bound the size of the hash
/// table, and with it the memory used by [`RenameMap::hitcounts`].
pub const HASH_MODULUS: u64 = 1024 * 1024 * 10;

/// Hash one edge: a line together with the line following it. The last line
/// of a file has no successor and hashes to a distinct value.
pub fn edge_hash(line: &[u8], next: Option<&[u8]>) -> u32 {
    let mut hasher = DefaultHasher::new();
    line.hash(&mut hasher);
    next.hash(&mut hasher);
    (hasher.finish() % HASH_MODULUS) as u32
}

/// Iterate over the edge hashes of `lines`, one per line.
pub fn iter_edge_hashes<L: AsRef<[u8]>>(lines: &[L]) -> impl Iterator<Item = u32> + '_ {
    lines
        .iter()
        .enumerate()
        .map(move |(n, line)| edge_hash(line.as_ref(), lines.get(n + 1).map(AsRef::as_ref)))
}

/// A table of edge hashes, each associated with the tags (file ids) of the
/// files that contain that edge.
#[derive(Debug)]
pub struct RenameMap<T> {
    edge_hashes: HashMap<u32, HashSet<T>>,
}

impl<T> Default for RenameMap<T> {
    fn default() -> Self {
        RenameMap {
            edge_hashes: HashMap::new(),
        }
    }
}

impl<T: Hash + Eq + Clone> RenameMap<T> {
    /// Create an empty map.
    pub fn new() -> Self {
        Self::default()
    }

    /// Record that every edge of `lines` occurs in the file tagged `tag`.
    pub fn add_edge_hashes<L: AsRef<[u8]>>(&mut self, lines: &[L], tag: T) {
        for hash in iter_edge_hashes(lines) {
            self.edge_hashes
                .entry(hash)
                .or_default()
                .insert(tag.clone());
        }
    }

    /// The tags recorded for an edge hash, if any.
    pub fn edge_hash_tags(&self, hash: u32) -> Option<&HashSet<T>> {
        self.edge_hashes.get(&hash)
    }

    /// Count the hash hits of `lines` against each tag.
    ///
    /// A hit is weighted by the number of tags that share the hash, so an
    /// edge that occurs in many files counts for little.
    pub fn hitcounts<L: AsRef<[u8]>>(&self, lines: &[L]) -> HashMap<T, f64> {
        let mut hits: HashMap<&T, f64> = HashMap::new();
        for hash in iter_edge_hashes(lines) {
            let Some(tags) = self.edge_hashes.get(&hash) else {
                continue;
            };
            let weight = 1.0 / tags.len() as f64;
            for tag in tags {
                *hits.entry(tag).or_insert(0.0) += weight;
            }
        }
        hits.into_iter().map(|(t, c)| (t.clone(), c)).collect()
    }
}

/// Turn a list of `(count, path, tag)` hits into a one-to-one path-to-tag map,
/// greedily taking the strongest hits first.
///
/// Hits are ordered by count and then path, descending. Hits that tie on
/// both are ordered by tag through `sort_tags_descending`, which sorts a
/// slice of tags from largest to smallest; it is only called for ties, so
/// tags need no total order and the callback may fail.
pub fn match_hits<P, T, E>(
    mut hits: Vec<(f64, P, T)>,
    mut sort_tags_descending: impl FnMut(&mut [T]) -> Result<(), E>,
) -> Result<HashMap<P, T>, E>
where
    P: Ord + Hash + Clone,
    T: Hash + Eq + Clone,
{
    hits.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| b.1.cmp(&a.1)));
    for run in hits.chunk_by_mut(|a, b| a.0 == b.0 && a.1 == b.1) {
        if run.len() < 2 {
            continue;
        }
        let mut tags: Vec<T> = run.iter().map(|hit| hit.2.clone()).collect();
        sort_tags_descending(&mut tags)?;
        for (hit, tag) in run.iter_mut().zip(tags) {
            hit.2 = tag;
        }
    }
    let mut seen_tags = HashSet::new();
    let mut path_map = HashMap::new();
    for (_count, path, tag) in hits {
        if path_map.contains_key(&path) || seen_tags.contains(&tag) {
            continue;
        }
        path_map.insert(path, tag.clone());
        seen_tags.insert(tag);
    }
    Ok(path_map)
}

/// Sort tags descending by their natural order, for use with [`match_hits`]
/// when the tag type is `Ord`.
pub fn sort_ord_descending<T: Ord>(tags: &mut [T]) -> Result<(), Infallible> {
    tags.sort_by(|a, b| b.cmp(a));
    Ok(())
}

/// The directory part of a posix path, as `posixpath.dirname` computes it.
pub fn dirname(path: &str) -> &str {
    let head = match path.rfind('/') {
        Some(i) => &path[..=i],
        None => "",
    };
    if head.bytes().all(|b| b == b'/') {
        head
    } else {
        head.trim_end_matches('/')
    }
}

/// Find the unversioned parent directories that the matched paths need.
///
/// `is_versioned` is asked about each ancestor of each matched path, walking
/// up until a versioned directory is found. The result maps each unversioned
/// ancestor to the tags of its matched direct children. Walking stops at the
/// tree root whatever `is_versioned` says about it.
pub fn required_parents<T, E>(
    matches: &HashMap<String, T>,
    mut is_versioned: impl FnMut(&str) -> Result<bool, E>,
) -> Result<HashMap<String, HashSet<T>>, E>
where
    T: Hash + Eq + Clone,
{
    let mut children_of: HashMap<&str, Vec<&str>> = HashMap::new();
    for mut path in matches.keys().map(String::as_str) {
        loop {
            let child = path;
            path = dirname(path);
            if is_versioned(path)? {
                break;
            }
            children_of.entry(path).or_default().push(child);
            if path.is_empty() {
                break;
            }
        }
    }
    Ok(children_of
        .into_iter()
        .map(|(parent, children)| {
            let tags = children
                .into_iter()
                .filter_map(|child| matches.get(child).cloned())
                .collect();
            (parent.to_string(), tags)
        })
        .collect())
}

/// Pair missing directories with the unversioned directories that need
/// versioning, by how many matched children they have in common.
///
/// `required_parents` maps a path to the tags of its children (see
/// [`required_parents`]); `missing_parents` maps a missing directory's tag to
/// the tags of its children. Ties are broken as in [`match_hits`].
pub fn match_parents<T, E>(
    required_parents: &HashMap<String, HashSet<T>>,
    missing_parents: &HashMap<T, HashSet<T>>,
    sort_tags_descending: impl FnMut(&mut [T]) -> Result<(), E>,
) -> Result<HashMap<String, T>, E>
where
    T: Hash + Eq + Clone,
{
    let mut hits = Vec::new();
    for (tag, tag_children) in missing_parents {
        for (path, path_children) in required_parents {
            let common = path_children.intersection(tag_children).count();
            if common > 0 {
                hits.push((common as f64, path.clone(), tag.clone()));
            }
        }
    }
    match_hits(hits, sort_tags_descending)
}

#[cfg(test)]
mod tests {
    use super::*;

    const A_LINES: [&[u8]; 3] = [b"a\n", b"b\n", b"c\n"];
    const B_LINES: [&[u8]; 3] = [b"b\n", b"c\n", b"d\n"];

    fn set<T: Hash + Eq + Clone>(items: &[T]) -> HashSet<T> {
        items.iter().cloned().collect()
    }

    #[test]
    fn test_add_edge_hashes() {
        let mut rn = RenameMap::new();
        rn.add_edge_hashes(&A_LINES, "a");
        assert_eq!(
            Some(&set(&["a"])),
            rn.edge_hash_tags(edge_hash(b"a\n", Some(b"b\n")))
        );
        assert_eq!(
            Some(&set(&["a"])),
            rn.edge_hash_tags(edge_hash(b"b\n", Some(b"c\n")))
        );
        assert_eq!(
            Some(&set(&["a"])),
            rn.edge_hash_tags(edge_hash(b"c\n", None))
        );
        assert_eq!(None, rn.edge_hash_tags(edge_hash(b"c\n", Some(b"d\n"))));
    }

    #[test]
    fn test_last_line_hashes_differently_from_pair() {
        assert_ne!(edge_hash(b"c\n", None), edge_hash(b"c\n", Some(b"")));
    }

    #[test]
    fn test_hitcounts() {
        let mut rn = RenameMap::new();
        rn.add_edge_hashes(&A_LINES, "a");
        rn.add_edge_hashes(&B_LINES, "b");
        assert_eq!(
            HashMap::from([("a", 2.5), ("b", 0.5)]),
            rn.hitcounts(&A_LINES)
        );
        assert_eq!(HashMap::from([("a", 1.0)]), rn.hitcounts(&A_LINES[..2]));
        assert_eq!(
            HashMap::from([("b", 2.5), ("a", 0.5)]),
            rn.hitcounts(&B_LINES)
        );
        assert_eq!(HashMap::new(), rn.hitcounts::<&[u8]>(&[]));
    }

    #[test]
    fn test_match_hits_takes_strongest_and_avoids_duplicates() {
        let hits = vec![
            (0.5, "b", "aid"),
            (2.5, "a", "aid"),
            (2.5, "b", "bid"),
            (0.5, "a", "bid"),
            (0.5, "c", "bid"),
        ];
        assert_eq!(
            Ok(HashMap::from([("a", "aid"), ("b", "bid")])),
            match_hits(hits, sort_ord_descending)
        );
    }

    #[test]
    fn test_match_hits_breaks_ties_descending() {
        let hits = vec![(1.0, "a", "x"), (1.0, "a", "y"), (1.0, "b", "x")];
        assert_eq!(
            Ok(HashMap::from([("a", "y"), ("b", "x")])),
            match_hits(hits, sort_ord_descending)
        );
    }

    #[test]
    fn test_match_hits_only_sorts_tags_on_ties() {
        let hits = vec![(2.0, "a", "x"), (1.0, "a", "y"), (1.0, "b", "z")];
        let result = match_hits(hits, |_: &mut [&str]| Err("compared"));
        assert_eq!(Ok(HashMap::from([("a", "x"), ("b", "z")])), result);
        let hits = vec![(1.0, "a", "x"), (1.0, "a", "y")];
        let result = match_hits(hits, |_: &mut [&str]| Err("compared"));
        assert_eq!(Err("compared"), result);
    }

    #[test]
    fn test_dirname() {
        assert_eq!("", dirname("path1"));
        assert_eq!("path2", dirname("path2/tr"));
        assert_eq!("path3/path4", dirname("path3/path4/path5"));
        assert_eq!("a/b", dirname("a/b/"));
        assert_eq!("/", dirname("/x"));
        assert_eq!("//", dirname("//x"));
        assert_eq!("", dirname(""));
    }

    #[test]
    fn test_required_parents() {
        let matches = HashMap::from([
            ("path1".to_string(), "a"),
            ("path2/tr".to_string(), "b"),
            ("path3/path4/path5".to_string(), "c"),
        ]);
        let required = required_parents(&matches, |p| Ok::<_, ()>(p.is_empty())).unwrap();
        assert_eq!(
            HashMap::from([
                ("path2".to_string(), set(&["b"])),
                ("path3/path4".to_string(), set(&["c"])),
                ("path3".to_string(), HashSet::new()),
            ]),
            required
        );
    }

    #[test]
    fn test_required_parents_propagates_errors() {
        let matches = HashMap::from([("path1".to_string(), "a")]);
        assert_eq!(
            Err("boom"),
            required_parents(&matches, |_| Err::<bool, _>("boom"))
        );
    }

    #[test]
    fn test_required_parents_stops_at_root() {
        let matches = HashMap::from([("path1".to_string(), "a")]);
        let required = required_parents(&matches, |_| Ok::<_, ()>(false)).unwrap();
        assert_eq!(HashMap::from([("".to_string(), set(&["a"]))]), required);
    }

    #[test]
    fn test_match_parents() {
        let required = HashMap::from([
            ("path2".to_string(), set(&["b"])),
            ("path3/path4".to_string(), set(&["c"])),
            ("path3".to_string(), HashSet::new()),
        ]);
        let missing = HashMap::from([
            ("path2-id", set(&["b"])),
            ("path4-id", set(&["c"])),
            ("path3-id", set(&["path4-id"])),
        ]);
        assert_eq!(
            Ok(HashMap::from([
                ("path3/path4".to_string(), "path4-id"),
                ("path2".to_string(), "path2-id"),
            ])),
            match_parents(&required, &missing, sort_ord_descending)
        );
    }
}
