//! Persistent maps from tuple_of_strings->string using CHK stores.
//!
//! Overview and current status:
//!
//! The CHKMap class implements a dict from tuple_of_strings->string by using a trie
//! with internal nodes of 8-bit fan out; The key tuples are mapped to strings by
//! joining them by \x00, and \x00 padding shorter keys out to the length of the
//! longest key. Leaf nodes are packed as densely as possible, and internal nodes
//! are all an additional 8-bits wide leading to a sparse upper tree.
//!
//! Updates to a CHKMap are done preferentially via the apply_delta method, to
//! allow optimisation of the update operation; but individual map/unmap calls are
//! possible and supported. Individual changes via map/unmap are buffered in memory
//! until the _save method is called to force serialisation of the tree.
//! apply_delta records its changes immediately by performing an implicit _save.
//!
//! # Todo
//!
//! Densely packed upper nodes.

use crc32fast::Hasher;

use std::fmt::Write;
use std::collections::{HashMap, HashSet};
use std::hash::Hash;
use std::iter::zip;
use std::io::Write as _;

fn crc32(bit: &[u8]) -> u32 {
    let mut hasher = Hasher::new();
    hasher.update(bit);
    hasher.finalize()
}

/// Serialized version of a key
pub type SerialisedKey = Vec<u8>;

/// Function to map a key into a search string
pub type SearchKeyFn = fn(&Key) -> SerialisedKey;

/// List of keys to include
pub type KeyFilter = Vec<Key>;

pub enum SearchPrefix {
    Unknown,
    Known(Vec<u8>),
}

/// Map the key tuple into a search string that just uses the key bytes.
pub fn search_key_plain(key: &Key) -> SerialisedKey {
    key.0.join(&b'\x00')
}

pub fn search_key_16(key: &Key) -> SerialisedKey {
    let mut result = String::new();
    for bit in key.iter() {
        write!(&mut result, "{:08X}\x00", crc32(bit)).unwrap();
    }
    result.pop();
    result.as_bytes().to_vec()
}

pub fn search_key_255(key: &Key) -> SerialisedKey {
    let mut result = vec![];
    for bit in key.iter() {
        let crc = crc32(bit);
        let crc_bytes = crc.to_be_bytes();
        result.extend(crc_bytes);
        result.push(0x00);
    }
    result.pop();
    result
        .iter()
        .map(|b| if *b == 0x0A { b'_' } else { *b })
        .collect()
}

/// If a ChildNode falls below this many bytes, we check for a remap
pub const INTERESTING_NEW_SIZE: usize = 50;

/// If a ChildNode shrinks by more than this amount, we check for a remap
pub const INTERESTING_SHRINKAGE_LIMIT: usize = 20;


pub fn bytes_to_text_key(data: &[u8]) -> Result<(&[u8], &[u8]), String> {
    let sections: Vec<&[u8]> = data.split(|&byte| byte == b'\n').collect();

    let delimiter_position = sections[0].windows(2).position(|window| window == b": ");

    if delimiter_position.is_none() {
        return Err("Invalid key file".to_string());
    }

    let (_kind, file_id) = sections[0].split_at(delimiter_position.unwrap() + 2);

    Ok((file_id, sections[3]))
}

#[derive(Debug, Hash, PartialEq, Eq, Clone)]
pub struct Key(Vec<Vec<u8>>);

impl From<Vec<Vec<u8>>> for Key {
    fn from(v: Vec<Vec<u8>>) -> Self {
        Key(v)
    }
}

impl Key {
    pub fn serialize(&self) -> SerialisedKey {
        let mut result = vec![];
        for bit in self.0.iter() {
            result.extend(bit);
            result.push(0x00);
        }
        result.pop();
        result
    }

    #[allow(clippy::len_without_is_empty)]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn iter(&self) -> impl Iterator<Item = &[u8]> {
        self.0.iter().map(|v| v.as_slice())
    }
}

impl From<(&[u8], )> for Key {
    fn from(v: (&[u8], )) -> Self {
        Key(vec![v.0.to_vec()])
    }
}

impl std::ops::Index<usize> for Key {
    type Output = Vec<u8>;

    fn index(&self, index: usize) -> &Self::Output {
        &self.0[index]
    }
}

impl std::fmt::Display for Key {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        let mut first = true;
        for bit in &self.0 {
            if !first {
                write!(f, "/")?;
            }
            first = false;
            write!(f, "{}", String::from_utf8_lossy(bit))?;
        }
        Ok(())
    }
}

pub type Value = Vec<u8>;

pub enum Error {
    InconsistentDeltaDelta(Vec<(Option<Key>, Option<Key>, Value)>, String),
    DeserializeError(String),
}

impl From<std::num::ParseIntError> for Error {
    fn from(e: std::num::ParseIntError) -> Self {
        Error::DeserializeError(format!("Failed to parse int: {}", e))
    }
}

/// Given 2 strings, return the longest prefix common to both.
///
/// # Arguments
/// * `prefix` - This has been the common prefix for other keys, so it is more likely to be the common prefix in this case as well.
/// * `key` - Another string to compare to.
pub fn common_prefix_pair<'b>(prefix: &[u8], key: &'b [u8]) -> &'b [u8] {
    if key.starts_with(prefix) {
        return &key[..prefix.len()];
    }
    let mut p = 0;
    // Is there a better way to do this?
    for (left, right) in zip(prefix, key) {
        if left != right {
            break;
        }
        p += 1;
    }

    let p = p as usize;
    &key[..p]
}

#[test]
fn test_common_prefix_pair() {
    assert_eq!(common_prefix_pair(b"abc", b"abc"), b"abc");
    assert_eq!(common_prefix_pair(b"abc", b"abcd"), b"abc");
    assert_eq!(common_prefix_pair(b"abc", b"ab"), b"ab");
    assert_eq!(common_prefix_pair(b"abc", b"bbd"), b"");
    assert_eq!(common_prefix_pair(b"", b"bbc"), b"");
    assert_eq!(common_prefix_pair(b"abc", b""), b"");
}

/// Given a list of keys, find their common prefix.
///
/// # Arguments
/// * `keys`: An iterable of strings.
///
/// # Returns
/// The longest common prefix of all keys.
pub fn common_prefix_many<'a>(mut keys: impl Iterator<Item = &'a [u8]> + 'a) -> Option<&'a [u8]> {
    let mut cp = keys.next()?;
    for key in keys {
        cp = common_prefix_pair(cp, key);
        if cp.is_empty() {
            // if common_prefix is the empty string, then we know it won't
            // change further
            break;
        }
    }
    Some(cp)
}

/// Reference to the child of a node
///
/// Can either be just a key (if the node is unresolved) or a node
enum NodeChild {
    /// A child node that is a tuple of key and value.
    Tuple(Key),

    /// A child node that is another node.
    Node(Node),
}

impl NodeChild {
    fn is_node(&self) -> bool {
        matches!(self, NodeChild::Node(_))
    }

    fn is_tuple(&self) -> bool {
        matches!(self, NodeChild::Tuple(_))
    }

    fn as_node(&self) -> Option<&Node> {
        if let NodeChild::Node(ref node) = self {
            Some(node)
        } else {
            None
        }
    }

    fn into_node(self) -> Option<Node> {
        if let NodeChild::Node(node) = self {
            Some(node)
        } else {
            None
        }
    }

    fn key(&self) -> Option<&Key> {
        match self {
            NodeChild::Tuple(ref key) => Some(key),
            NodeChild::Node(n) => n.key()
        }
    }
}

#[cfg(test)]
#[test]
fn test_node_child() {
    let key = Key(vec![b"test".to_vec()]);
    let node_child = NodeChild::Tuple(key.clone());
    assert!(node_child.is_tuple());
    assert!(!node_child.is_node());
    assert_eq!(node_child.key(), Some(&key));

    let node = Node::leaf(None);
    let node_child = NodeChild::Node(node);
    assert!(!node_child.is_tuple());
    assert!(node_child.is_node());
    assert_eq!(node_child.key(), None);
}

/// A CHK Map Node
enum Node {
    /// A node containing actual key:value pairs.
    Leaf {
        /// total size of the serialized key:value data, before adding the header bytes, and without
        /// prefix compression.
        raw_size: usize,
        /// All of the keys in this leaf node share this common prefix
        common_serialised_prefix: Option<SerialisedKey>,
        /// A dict of key->value items. The key is in tuple form.
        items: HashMap<SerialisedKey, Value>,
        key: Option<Key>,
        key_width: usize,
        len: usize,
        maximum_size: usize,
        search_key_func: SearchKeyFn,
        search_prefix: Option<SerialisedKey>,
    },

    /// A node that contains references to other nodes.
    ///
    /// An InternalNode is responsible for mapping search key prefixes to child nodes.
    Internal {
        /// serialised_key => node dictionary. node may be a tuple, LeafNode or InternalNode.
        items: HashMap<SerialisedKey, Node>,
        key: Option<Key>,
        key_width: usize,
        len: usize,
        maximum_size: usize,
        node_width: usize,
        raw_size: usize,
        search_key_func: SearchKeyFn,
        search_prefix: Option<SerialisedKey>,
    }
}

impl Node {
    /// Create a new leaf node
    pub fn leaf(search_key_func: Option<SearchKeyFn>) -> Self {
        Node::Leaf {
            raw_size: 0,
            common_serialised_prefix: None,
            items: HashMap::new(),
            key: None,
            key_width: 1,
            len: 0,
            maximum_size: 0,
            search_key_func: search_key_func.unwrap_or(search_key_plain),
            search_prefix: None,
        }
    }

    /// Create a new internal node
    pub fn internal(search_prefix: Option<SerialisedKey>, search_key_func: Option<SearchKeyFn>) -> Self {
        Node::Internal {
            items: HashMap::new(),
            key: None,
            key_width: 1,
            len: 0,
            maximum_size: 0,
            node_width: 0,
            raw_size: 0,
            search_key_func: search_key_func.unwrap_or(search_key_plain),
            search_prefix
        }
    }

    pub fn key(&self) -> Option<&Key> {
        match self {
            Node::Leaf { key, .. } => key.as_ref(),
            Node::Internal { key, .. } => key.as_ref(),
        }
    }
}

/// Get the size of a key:value pair
// TODO: Just serialize?
fn key_value_len(key: &Key, value: &Value) -> usize {
    key.serialize().len()
        + 1
        + value.iter().filter(|&&f| f == b'\n').count().to_string().len()
        + 1
        + value.len()
        + 1
}

#[cfg(test)]
#[test]
fn test_key_value_len() {
    let key = Key(vec![b"test".to_vec()]);
    let value = b"test\x00value\n\n".to_vec();
    assert_eq!(key_value_len(&key, &value), 20);
}

/// Check to see if the search keys for all entries are the same.
///
/// When using a hash as the search_key it is possible for non-identical
/// keys to collide. If that happens enough, we may try overflow a
/// LeafNode, but as all are collisions, we must not split.
fn are_search_keys_identical<'a>(keys: impl Iterator<Item = &'a Key>, search_key_func: SearchKeyFn) -> bool {
    let mut common_search_key = None;
    for key in keys {
        let search_key = search_key_func(key);
        if common_search_key.is_none() {
            common_search_key = Some(search_key);
        } else if Some(search_key) != common_search_key {
            return false;
        }
    }
    return true
}

#[cfg(test)]
#[test]
fn test_are_search_keys_identical() {
    let keys = vec![
        Key(vec![b"test".to_vec()]),
        Key(vec![b"test".to_vec()]),
    ];
    assert!(are_search_keys_identical(keys.iter(), search_key_plain));

    let keys = vec![
        Key(vec![b"test".to_vec()]),
        Key(vec![b"test2".to_vec()]),
    ];
    assert!(!are_search_keys_identical(keys.iter(), search_key_plain));
}
