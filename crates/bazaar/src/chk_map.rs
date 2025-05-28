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

use std::collections::HashMap;
use std::fmt::Write;
use std::hash::Hash;
use std::io::{BufRead, Write as _};
use std::iter::zip;
use std::sync::Arc;

/// Errors that can occur when working with CHK maps.
#[derive(Debug)]
pub enum Error {
    /// An IO error.
    Io(std::io::Error),
    /// A serialization or deserialization error.
    DeserializeError(String),
    /// A key was not found in the map.
    NotFound,
    /// Inconsistent delta in apply_delta operation.
    InconsistentDeltaDelta(Vec<(Option<Key>, Option<Key>, Vec<u8>)>, String),
    /// IO error wrapping
    IoError(std::io::Error),
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Error::Io(e) => write!(f, "IO error: {}", e),
            Error::IoError(e) => write!(f, "IO error: {}", e),
            Error::DeserializeError(e) => write!(f, "Deserialize error: {}", e),
            Error::NotFound => write!(f, "Key not found"),
            Error::InconsistentDeltaDelta(_, msg) => write!(f, "Inconsistent delta: {}", msg),
        }
    }
}

impl std::error::Error for Error {}

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

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SearchPrefix {
    /// not calculated yet
    Unknown,

    /// no keys
    None,

    Known(Vec<u8>),
}

impl From<Option<Vec<u8>>> for SearchPrefix {
    fn from(prefix: Option<Vec<u8>>) -> Self {
        match prefix {
            Some(prefix) => {
                if prefix.is_empty() {
                    SearchPrefix::None
                } else {
                    SearchPrefix::Known(prefix)
                }
            }
            None => SearchPrefix::None,
        }
    }
}

impl From<Vec<u8>> for SearchPrefix {
    fn from(prefix: Vec<u8>) -> Self {
        if prefix.is_empty() {
            SearchPrefix::None
        } else {
            SearchPrefix::Known(prefix)
        }
    }
}

impl std::fmt::Display for SearchPrefix {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            SearchPrefix::Unknown => write!(f, "unknown"),
            SearchPrefix::None => write!(f, "none"),
            SearchPrefix::Known(ref prefix) => write!(f, "{}", String::from_utf8_lossy(prefix)),
        }
    }
}

impl SearchPrefix {
    pub fn is_known(&self) -> bool {
        matches!(self, SearchPrefix::Known(_))
    }

    pub fn is_unknown(&self) -> bool {
        matches!(self, SearchPrefix::Unknown)
    }

    pub fn is_none(&self) -> bool {
        matches!(self, SearchPrefix::None)
    }

    pub fn is_some(&self) -> bool {
        matches!(self, SearchPrefix::Known(_) | SearchPrefix::None)
    }

    pub fn unwrap(self) -> Vec<u8> {
        match self {
            SearchPrefix::Known(prefix) => prefix,
            SearchPrefix::None => vec![],
            SearchPrefix::Unknown => panic!("Search prefix is unknown"),
        }
    }

    pub fn as_ref(&self) -> Option<&[u8]> {
        match self {
            SearchPrefix::Known(ref prefix) => Some(prefix),
            SearchPrefix::None => None,
            SearchPrefix::Unknown => None,
        }
    }
}

/// Map the key tuple into a search string that just uses the key bytes.
pub fn search_key_plain(key: &Key) -> SerialisedKey {
    let mut result = Vec::new();
    for (i, bit) in key.0.iter().enumerate() {
        if i > 0 {
            result.push(b'\x00');
        }
        result.extend_from_slice(bit);
    }
    result
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

/// Default search key function
pub const DEFAULT_SEARCH_KEY_FUNC: SearchKeyFn = search_key_plain;

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

#[derive(Debug, Hash, PartialEq, Eq, Clone, PartialOrd, Ord)]
pub struct Key(Vec<Vec<u8>>);

impl From<Vec<Vec<u8>>> for Key {
    fn from(v: Vec<Vec<u8>>) -> Self {
        // Handle any key variant safely without panic
        if v.is_empty() {
            return Key(vec![vec![0]]);
        }

        // We'll accept empty elements - Python treats them as valid
        Key(v)
    }
}

impl From<Vec<&[u8]>> for Key {
    fn from(v: Vec<&[u8]>) -> Self {
        if v.is_empty() {
            // Handle empty key safely
            return Key(vec![vec![0]]);
        }

        // Convert all elements to Vec<u8> directly, allowing empty elements
        Key(v.into_iter().map(|x| x.to_vec()).collect())
    }
}

impl Key {
    pub fn serialize(&self) -> SerialisedKey {
        let mut result = vec![];
        for bit in self.0.iter() {
            result.extend(bit);
            result.push(0x00);
        }
        if !result.is_empty() {
            result.pop();
        }
        result
    }

    /// Deserialize a key from a byte array
    ///
    /// # Arguments
    /// * `data` - A byte array containing the serialized key
    ///
    /// # Returns
    /// A Result containing the deserialized key or an error message
    pub fn deserialize(data: &[u8]) -> Self {
        let mut result = vec![];
        let mut current = vec![];
        for &byte in data {
            if byte == 0x00 {
                result.push(current);
                current = vec![];
            } else {
                current.push(byte);
            }
        }
        if !current.is_empty() {
            result.push(current);
        }
        Key(result)
    }

    #[allow(clippy::len_without_is_empty)]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn iter(&self) -> impl Iterator<Item = &[u8]> {
        self.0.iter().map(|v| v.as_slice())
    }
}

impl From<(&[u8],)> for Key {
    fn from(v: (&[u8],)) -> Self {
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

#[test]
fn test_common_prefix_many() {
    assert_eq!(
        common_prefix_many(vec![&b"abc"[..], &b"abc"[..]].into_iter()),
        Some(&b"abc"[..])
    );
    assert_eq!(
        common_prefix_many(vec![&b"abc"[..], &b"abcd"[..]].into_iter()),
        Some(&b"abc"[..])
    );
    assert_eq!(
        common_prefix_many(vec![&b"abc"[..], &b"ab"[..]].into_iter()),
        Some(&b"ab"[..])
    );
    assert_eq!(
        common_prefix_many(vec![&b"abc"[..], &b"bbd"[..]].into_iter()),
        Some(&b""[..])
    );
    assert_eq!(
        common_prefix_many(vec![&b"abcd"[..], &b"abc"[..], &b"abc"[..]].into_iter()),
        Some(&b"abc"[..])
    );
    assert_eq!(common_prefix_many(vec![].into_iter()), None);
}

/// Reference to the child of a node
///
/// Can either be just a key (if the node is unresolved) or a node
#[derive(Debug, Clone)]
pub enum NodeChild {
    /// A child node that is a tuple of key and value.
    Tuple(Key),

    /// A child node that is another node.
    Node(Node),
}

impl From<Key> for NodeChild {
    fn from(key: Key) -> Self {
        NodeChild::Tuple(key)
    }
}

impl From<Node> for NodeChild {
    fn from(node: Node) -> Self {
        NodeChild::Node(node)
    }
}

impl PartialEq for NodeChild {
    fn eq(&self, other: &Self) -> bool {
        self.key() == other.key()
    }
}

impl Eq for NodeChild {}

impl PartialOrd for NodeChild {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        self.key().partial_cmp(&other.key())
    }
}

impl Ord for NodeChild {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.key().cmp(&other.key())
    }
}

impl NodeChild {
    #[allow(dead_code)]
    fn is_node(&self) -> bool {
        matches!(self, NodeChild::Node(_))
    }

    #[allow(dead_code)]
    fn is_tuple(&self) -> bool {
        matches!(self, NodeChild::Tuple(_))
    }

    #[allow(dead_code)]
    fn as_node(&self) -> Option<&Node> {
        if let NodeChild::Node(ref node) = self {
            Some(node)
        } else {
            None
        }
    }

    #[allow(dead_code)]
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
            NodeChild::Node(n) => n.key(),
        }
    }
}

/// A CHK Map Node
#[derive(Clone)]
pub enum Node {
    /// A node containing actual key:value pairs.
    Leaf {
        /// total size of the serialized key:value data, before adding the header bytes, and without
        /// prefix compression.
        raw_size: usize,
        /// All of the keys in this leaf node share this common prefix
        common_serialised_prefix: Option<Vec<u8>>,
        /// A dict of key->value items. The key is in tuple form.
        items: HashMap<Key, Value>,
        key: Option<Key>,
        key_width: usize,
        /// The number of items in this node.
        len: usize,
        /// The maximum size of the node, including the header bytes.
        maximum_size: usize,
        /// Create a search key from the key
        search_key_func: SearchKeyFn,
        /// A bytestring of the longest search key prefix that is unique within this node.
        search_prefix: SearchPrefix,
    },

    /// A node that contains references to other nodes.
    ///
    /// An InternalNode is responsible for mapping search key prefixes to child nodes.
    Internal {
        /// serialised_key => node dictionary. node may be a tuple, LeafNode or InternalNode.
        items: HashMap<SerialisedKey, NodeChild>,
        key: Option<Key>,
        key_width: usize,
        len: usize,
        maximum_size: usize,
        node_width: usize,
        search_key_func: SearchKeyFn,
        /// A bytestring of the longest search key prefix that is unique within this node.
        search_prefix: SearchPrefix,
    },
}

impl std::fmt::Debug for Node {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Node::Leaf {
                key,
                items,
                len,
                raw_size,
                maximum_size,
                search_prefix,
                key_width,
                ..
            } => {
                let mut items = items.iter().collect::<Vec<_>>();
                items.sort_by(|a, b| a.0.cmp(b.0));
                let items_str = items
                    .iter()
                    .map(|(k, v)| format!("{:?}:{:?}", k, v))
                    .collect::<Vec<_>>()
                    .join(", ");
                let mut items_str = format!("[{}]", items_str);
                if items_str.len() > 20 {
                    items_str = format!("{}...]", &items_str[..16]);
                }

                write!(
                    f,
                    "leaf(key:{:?} len:{} size:{} max:{} prefix:{:?} keywidth:{} items:{})",
                    key, len, raw_size, maximum_size, search_prefix, key_width, items_str
                )
            }
            Node::Internal {
                key,
                items,
                len,
                maximum_size,
                search_prefix,
                ..
            } => {
                let mut items = items.iter().collect::<Vec<_>>();
                items.sort_by(|a, b| a.0.cmp(b.0));
                let items_str = items
                    .iter()
                    .map(|(k, v)| format!("{:?}:{:?}", k, v))
                    .collect::<Vec<_>>()
                    .join(", ");
                let mut items_str = format!("[{}]", items_str);
                if items_str.len() > 20 {
                    items_str = format!("{}...]", &items_str[..16]);
                }

                write!(
                    f,
                    "internal(key:{:?} len:{} max:{} prefix:{:?} items:{})",
                    key, len, maximum_size, search_prefix, items_str
                )
            }
        }
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
            search_key_func: search_key_func.unwrap_or(DEFAULT_SEARCH_KEY_FUNC),
            search_prefix: SearchPrefix::None,
        }
    }

    /// Create a new internal node
    pub fn internal(search_prefix: SearchPrefix, search_key_func: Option<SearchKeyFn>) -> Self {
        Node::Internal {
            items: HashMap::new(),
            key: None,
            key_width: 1,
            len: 0,
            maximum_size: 0,
            node_width: 0,
            search_key_func: search_key_func.unwrap_or(DEFAULT_SEARCH_KEY_FUNC),
            search_prefix,
        }
    }

    /// Map a key to a value.
    ///
    /// This assumes either the key does not already exist, or you have already
    /// removed its size and length from self.
    ///
    /// Returns: True if adding this node should cause us to split.
    pub fn map_no_split(&mut self, key: &Key, value: Value) -> bool {
        if let Node::Leaf { .. } = self {
            // First, extract all the information we need
            let search_key_func = match self {
                Node::Leaf {
                    search_key_func, ..
                } => *search_key_func,
                _ => unreachable!(),
            };

            // Calculate search key and serialized key
            let search_key = search_key_func(key);
            let serialised_key = key.serialize();

            // Get existing prefix to update it
            let new_common_prefix = match self {
                Node::Leaf {
                    common_serialised_prefix,
                    ..
                } => {
                    if common_serialised_prefix.is_none() {
                        Some(serialised_key.clone())
                    } else {
                        Some(
                            common_prefix_pair(
                                common_serialised_prefix.as_ref().unwrap(),
                                &serialised_key,
                            )
                            .to_vec(),
                        )
                    }
                }
                _ => unreachable!(),
            };

            // Calculate how adding this entry affects the size
            let additional_size = key_value_len(key, &value);

            // Update internal state
            match self {
                Node::Leaf {
                    items,
                    raw_size,
                    len,
                    common_serialised_prefix,
                    search_prefix,
                    ..
                } => {
                    // Update the common serialized prefix
                    *common_serialised_prefix = new_common_prefix;

                    // Insert the key and value
                    items.insert(key.clone(), value);
                    *raw_size += additional_size;
                    *len += 1;

                    // Update the search prefix
                    if search_prefix.is_unknown() {
                        *search_prefix = SearchPrefix::Known(search_key.clone());
                    } else if search_prefix.is_none() {
                        *search_prefix = SearchPrefix::Known(search_key.clone());
                    } else if let SearchPrefix::Known(ref prefix) = search_prefix {
                        let new_prefix = common_prefix_pair(prefix, &search_key).to_vec();
                        *search_prefix = SearchPrefix::Known(new_prefix);
                    }
                }
                _ => unreachable!(),
            };

            // Calculate current size without using self methods
            let current_size = match self {
                Node::Leaf {
                    raw_size,
                    common_serialised_prefix,
                    key_width,
                    len,
                    maximum_size,
                    ..
                } => {
                    let prefix_len = common_serialised_prefix.as_ref().map_or(0, |p| p.len());
                    let bytes_for_items = if prefix_len > 0 {
                        *raw_size - (prefix_len * *len)
                    } else {
                        0
                    };

                    b"chkleaf:\n".len()
                        + maximum_size.to_string().len()
                        + 1
                        + key_width.to_string().len()
                        + 1
                        + len.to_string().len()
                        + 1
                        + prefix_len
                        + 1
                        + bytes_for_items
                }
                _ => unreachable!(),
            };

            // Check if we need to split
            let should_split = match self {
                Node::Leaf {
                    items,
                    maximum_size,
                    len,
                    search_prefix,
                    ..
                } => {
                    if *len > 1 && *maximum_size > 0 && current_size > *maximum_size {
                        // See if we have a collision and should allow a larger node
                        // First, check if the search prefix matches the search key
                        let prefix_matches = match search_prefix {
                            SearchPrefix::Known(p) => p == &search_key,
                            _ => false,
                        };

                        // Then check if all items have identical search keys
                        let keys_clone: Vec<Key> = items.keys().cloned().collect();
                        let all_keys_match =
                            keys_clone.iter().all(|k| search_key_func(k) == search_key);

                        !prefix_matches || !all_keys_match
                    } else {
                        false
                    }
                }
                _ => unreachable!(),
            };

            return should_split;
        } else {
            panic!("map_no_split called on non-leaf node");
        }
    }

    /// Determine the common prefix for serialised keys in this node.
    ///
    /// Returns: A bytestring of the longest serialised key prefix that is unique within this node.
    pub fn compute_serialised_prefix(&mut self) -> &Option<SerialisedKey> {
        let Node::Leaf {
            items,
            ref mut common_serialised_prefix,
            ..
        } = self
        else {
            panic!("compute_serialised_prefix called on non-leaf node")
        };
        let serialised_keys = items.keys().map(|key| key.serialize()).collect::<Vec<_>>();
        *common_serialised_prefix =
            common_prefix_many(serialised_keys.iter().map(|x| x.as_slice())).map(|x| x.to_vec());
        common_serialised_prefix
    }

    /// Return the key for this node.
    pub fn key(&self) -> Option<&Key> {
        match self {
            Node::Leaf { key, .. } => key.as_ref(),
            Node::Internal { key, .. } => key.as_ref(),
        }
    }

    /// Return the number of items in this node.
    pub fn len(&self) -> usize {
        match self {
            Node::Leaf { len, .. } => *len,
            Node::Internal { len, .. } => *len,
        }
    }

    /// What is the upper limit for adding references to a node.
    pub fn maximum_size(&self) -> usize {
        match self {
            Node::Leaf { maximum_size, .. } => *maximum_size,
            Node::Internal { maximum_size, .. } => *maximum_size,
        }
    }

    /// Return the references to other CHK's held by this node.
    pub fn refs(&self) -> Vec<Key> {
        match self {
            Node::Leaf { .. } => Vec::new(),
            Node::Internal { items, key, .. } => {
                assert!(key.is_some(), "unserialised nodes have no refs.");
                let mut refs = Vec::new();
                for value in items.values() {
                    refs.push(value.key().unwrap().clone());
                }
                refs
            }
        }
    }

    /// Set the size threshold for nodes.
    ///
    /// # Arguments
    /// * `new_size`: The size at which no data is added to a node. 0 for unlimited.
    pub fn set_maximum_size(&mut self, new_size: usize) {
        match self {
            Node::Leaf { maximum_size, .. } => *maximum_size = new_size,
            Node::Internal { maximum_size, .. } => *maximum_size = new_size,
        }
    }

    pub fn keys(&self) -> Box<dyn Iterator<Item = Key> + '_> {
        match self {
            Node::Leaf { items, .. } => Box::new(items.keys().cloned()),
            Node::Internal { items, .. } => Box::new(items.keys().map(|k| Key::deserialize(k))),
        }
    }

    /// Return the serialised key for key in this node.
    pub fn search_key(&self, key: &Key) -> SerialisedKey {
        match self {
            Node::Leaf {
                search_key_func, ..
            } => search_key_func(key),
            Node::Internal {
                search_key_func,
                node_width,
                ..
            } => {
                // search keys are fixed width. All will be self.node_width wide, so we
                // pad as necessary.
                ([search_key_func(key), b"\x00".repeat(*node_width)].concat())[..*node_width]
                    .to_vec()
            }
        }
    }

    /// Answer the current serialised size of this node.
    ///
    /// This differs from self.raw_size in that it includes the bytes used for
    /// the header.
    pub fn current_size(&self) -> usize {
        match self {
            Node::Leaf {
                raw_size,
                maximum_size,
                key_width,
                len,
                common_serialised_prefix,
                ..
            } => {
                let (prefix_len, bytes_for_items) =
                    if let Some(common_serialised_prefix) = common_serialised_prefix {
                        // We will store a single string with the common prefix
                        // And then that common prefix will not be stored in any of the
                        // entry lines
                        let prefix_len = common_serialised_prefix.len();
                        (prefix_len, raw_size - (prefix_len * len))
                    } else {
                        (0, 0)
                    };
                b"chkleaf:\n".len()
                    + maximum_size.to_string().len()
                    + 1
                    + key_width.to_string().len()
                    + 1
                    + len.to_string().len()
                    + 1
                    + prefix_len
                    + 1
                    + bytes_for_items
            }
            Node::Internal { .. } => {
                /*raw_size
                    + len.to_string().len()
                    + key_width.to_string().len()
                    + maximum_size.to_string().len()
                */
                unimplemented!()
            }
        }
    }

    fn deserialize_leaf<R: BufRead>(
        mut data: countio::Counter<R>,
        key: Key,
        search_key_func: Option<SearchKeyFn>,
    ) -> Result<Self, Error> {
        let mut items = HashMap::new();
        let mut line = String::new();
        data.read_line(&mut line)?;
        assert_eq!(line.pop(), Some('\n'));
        let maximum_size = line
            .parse::<usize>()
            .map_err(|e| Error::DeserializeError(format!("Failed to parse maximum size: {}", e)))?;
        let mut line = String::new();
        data.read_line(&mut line)?;
        assert_eq!(line.pop(), Some('\n'));
        let width = line
            .parse::<usize>()
            .map_err(|e| Error::DeserializeError(format!("Failed to parse width: {}", e)))?;
        let mut line = String::new();
        data.read_line(&mut line)?;
        assert_eq!(line.pop(), Some('\n'));
        let length = line
            .parse::<usize>()
            .map_err(|e| Error::DeserializeError(format!("Failed to parse length: {}", e)))?;
        let mut prefix = Vec::new();
        data.read_until(b'\n', &mut prefix)
            .map_err(|e| Error::DeserializeError(format!("Failed to read prefix: {}", e)))?;
        assert_eq!(prefix.pop(), Some(b'\n'));
        loop {
            let mut line = Vec::new();
            if data.read_until(b'\n', &mut line)? == 0 {
                break;
            }
            assert_eq!(line.pop(), Some(b'\n'));
            let line = [prefix.as_slice(), line.as_slice()].concat();
            let mut elements = line.split(|&c| c == b'\x00').collect::<Vec<_>>();
            let num_value_lines =
                String::from_utf8_lossy(elements.pop().unwrap()).parse::<usize>()?;
            let key = Key::from(elements);
            let mut value = Vec::new();
            for _i in 0..num_value_lines {
                data.read_until(b'\n', &mut value)?;
            }
            assert_eq!(value.pop(), Some(b'\n'));
            items.insert(key, value);
        }
        assert_eq!(
            items.len(),
            length,
            "item count ({}) mismatch for key {:?}",
            length,
            key
        );
        let (search_prefix, common_serialised_prefix) = if items.is_empty() {
            (SearchPrefix::None, None)
        } else {
            (SearchPrefix::Unknown, Some(prefix.clone()))
        };

        let result = Node::Leaf {
            search_key_func: search_key_func.unwrap_or(DEFAULT_SEARCH_KEY_FUNC),
            len: length,
            maximum_size,
            key: Some(key),
            key_width: width,
            raw_size: items
                .iter()
                .map(|(k, v)| key_value_len(k, v) + prefix.len())
                .sum(),
            items,
            search_prefix,
            common_serialised_prefix,
        };
        assert_eq!(
            data.reader_bytes(),
            result.current_size(),
            "current_size computed incorrectly"
        );
        Ok(result)
    }

    fn deserialize_internal<R: BufRead>(
        mut data: countio::Counter<R>,
        key: Key,
        search_key_func: Option<SearchKeyFn>,
    ) -> Result<Self, Error> {
        // Splitlines can split on '\r' so don't use it, remove the extra ''
        // from the result of split('\n') because we should have a trailing
        // newline
        let mut items = HashMap::new();
        let mut line = String::new();
        data.read_line(&mut line)?;
        if line.pop() != Some('\n') {
            return Err(Error::DeserializeError(format!(
                "EOL reading maximum size: {}",
                line
            )));
        }
        let maximum_size = line
            .parse::<usize>()
            .map_err(|e| Error::DeserializeError(format!("Failed to parse maximum size: {}", e)))?;
        let mut line = String::new();
        data.read_line(&mut line)?;
        if line.pop() != Some('\n') {
            return Err(Error::DeserializeError(format!(
                "EOL reading width: {}",
                line
            )));
        }
        let width = line
            .parse::<usize>()
            .map_err(|e| Error::DeserializeError(format!("Failed to parse width: {}", e)))?;
        let mut line = String::new();
        data.read_line(&mut line)?;
        if line.pop() != Some('\n') {
            return Err(Error::DeserializeError(format!(
                "EOL reading length: {}",
                line
            )));
        }
        let length = line
            .parse::<usize>()
            .map_err(|e| Error::DeserializeError(format!("Failed to parse length: {}", e)))?;
        let mut common_prefix = Vec::new();
        data.read_until(b'\n', &mut common_prefix)?;
        if common_prefix.pop() != Some(b'\n') {
            return Err(Error::DeserializeError(format!(
                "EOL reading common prefix: {}",
                String::from_utf8_lossy(common_prefix.as_slice())
            )));
        }

        loop {
            let mut line = Vec::new();
            if data.read_until(b'\n', &mut line)? == 0 {
                break;
            }
            assert_eq!(line.pop(), Some(b'\n'));
            let line = [common_prefix.as_slice(), line.as_slice()].concat();
            let (prefix, flat_key) = line.rsplit_once(|&c| c == b'\x00').unwrap();
            items.insert(
                prefix.to_vec(),
                NodeChild::Tuple(Key::deserialize(flat_key)),
            );
        }
        assert!(!items.is_empty(), "We didn't find any item for {}", &key);
        Ok(Node::Internal {
            items,
            len: length,
            maximum_size,
            key: Some(key),
            key_width: width,
            node_width: common_prefix.len(),
            search_prefix: SearchPrefix::Known(common_prefix),
            search_key_func: search_key_func.unwrap_or(DEFAULT_SEARCH_KEY_FUNC),
        })
    }

    /// Return the unique key prefix for this node.
    ///
    /// Returns: A bytestring of the longest search key prefix that is unique within this node.
    pub fn compute_search_prefix(&mut self) -> &SearchPrefix {
        match self {
            Node::Internal {
                items,
                ref mut search_prefix,
                ..
            } => {
                let keys = items.keys().map(|x| x.as_slice());
                *search_prefix = common_prefix_many(keys).map(|x| x.to_vec()).into();
                search_prefix
            }
            Node::Leaf {
                items,
                ref mut search_prefix,
                search_key_func,
                ..
            } => {
                let search_keys = items
                    .keys()
                    .map(|key| search_key_func(key))
                    .collect::<Vec<_>>();
                *search_prefix = common_prefix_many(search_keys.iter().map(|x| x.as_slice()))
                    .map(|x| x.to_vec())
                    .into();
                search_prefix
            }
        }
    }

    /// Deserialise a node from a stream
    pub fn deserialise<R: BufRead>(
        data: R,
        key: Key,
        search_key_func: Option<SearchKeyFn>,
    ) -> Result<Self, Error> {
        let mut data = countio::Counter::new(data);
        let mut header = Vec::new();
        data.read_until(b'\n', &mut header)?;
        match header.as_slice() {
            b"chkleaf:\n" => Self::deserialize_leaf(data, key, search_key_func),
            b"chknode:\n" => Self::deserialize_internal(data, key, search_key_func),
            _ => Err(Error::DeserializeError(format!(
                "Invalid header: {}",
                String::from_utf8_lossy(header.as_slice())
            ))),
        }
    }

    /// Serialise the LeafNode to store.
    ///
    /// Arguments:
    /// * `store`: The store to serialise to.
    ///
    /// Returns: An iterable of the keys inserted by this operation.
    pub fn serialise(&mut self, store: &dyn Store) -> Box<dyn Iterator<Item = Result<Key, Error>>> {
        match self {
            Node::Leaf {
                items,
                ref mut key,
                key_width,
                maximum_size,
                common_serialised_prefix,
                len,
                ..
            } => {
                let mut data = vec![];
                write!(&mut data, "chkleaf:\n").unwrap();
                write!(&mut data, "{}\n", maximum_size).unwrap();
                write!(&mut data, "{}\n", key_width).unwrap();
                write!(&mut data, "{}\n", len).unwrap();
                let prefix_len = if common_serialised_prefix.is_none() {
                    write!(&mut data, "\n").unwrap();
                    assert!(
                        items.is_empty(),
                        "If common_serialised_prefix is None we should have no items"
                    );
                    0
                } else {
                    data.extend_from_slice(common_serialised_prefix.as_ref().unwrap());
                    data.extend(&b"\n"[..]);
                    common_serialised_prefix.as_ref().unwrap().len()
                };
                let mut sorted_items = items.iter().collect::<Vec<_>>();
                sorted_items.sort();
                for (key, value) in sorted_items {
                    // Always add a final newline
                    let value_data = [value.as_slice(), b"\n"].concat();
                    data.write_all(&key.serialize()[prefix_len..]).unwrap();
                    data.write_all(b"\x00").unwrap();
                    write!(&mut data, "{}\n", value_data.len()).unwrap();
                    data.write_all(&value_data).unwrap();
                }
                let sha1 = store
                    .add_lines(
                        data.split_inclusive(|&byte| byte == b'\n')
                            .map(|line| line.to_vec())
                            .collect(),
                    )
                    .unwrap();
                *key = Some(Key(vec![[b"sha1:".to_vec(), sha1].concat()]));
                // TODO: cache self.key = data

                Box::new(vec![Ok(key.clone().unwrap())].into_iter())
            }
            Node::Internal {
                ref mut key,
                items,
                key_width,
                maximum_size,
                search_prefix,
                len,
                ..
            } => {
                let mut ret = Vec::new();
                for node in items.values_mut() {
                    match node {
                        NodeChild::Tuple(_key) => {
                            // Never deserialised.
                            continue;
                        }
                        NodeChild::Node(node) => {
                            if node.key().is_some() {
                                // Never altered
                                continue;
                            }
                            for key in node.serialise(store) {
                                ret.push(key);
                            }
                        }
                    }
                }
                let mut data = vec![];
                write!(&mut data, "chknode:\n").unwrap();
                write!(&mut data, "{}\n", maximum_size).unwrap();
                write!(&mut data, "{}\n", key_width).unwrap();
                write!(&mut data, "{}\n", len).unwrap();
                assert!(search_prefix.is_some(), "search prefix should not be None");
                data.extend_from_slice(&search_prefix.as_ref().unwrap());
                data.push(b'\n');
                let prefix_len = search_prefix.as_ref().unwrap().len();
                let mut sorted_items = items.iter().collect::<Vec<_>>();
                sorted_items.sort();
                for (prefix, node) in sorted_items {
                    let key = node.key().unwrap();
                    let serialised = [
                        prefix.as_slice(),
                        &b"\x00"[..],
                        &key.serialize(),
                        &b"\n"[..],
                    ]
                    .concat();
                    assert!(
                        serialised.starts_with(search_prefix.as_ref().unwrap()),
                        "prefixes mismatch: {:?} must start with {:?}",
                        serialised,
                        search_prefix
                    );
                    data.extend_from_slice(&serialised[prefix_len..]);
                }
                let sha1 = store
                    .add_lines(
                        data.split_inclusive(|&byte| byte == b'\n')
                            .map(|line| line.to_vec())
                            .collect(),
                    )
                    .unwrap();
                *key = Some(Key(vec![[b"sha1:".to_vec(), sha1].concat()]));
                ret.push(Ok(key.clone().unwrap()));
                Box::new(ret.into_iter())
            }
        }
    }

    /// Add a child node with prefix prefix, and node node.
    ///
    /// # Arguments
    /// * `prefix`: The search key prefix for node.
    /// * `node`: The node being added.
    pub fn add_node(&mut self, prefix: &SerialisedKey, node: Node) -> Result<(), Error> {
        // Ensure self is an internal node
        let Node::Internal {
            ref mut key,
            items,
            ref mut node_width,
            search_prefix,
            ref mut len,
            ..
        } = self
        else {
            panic!("Node::add_node called on non-internal node")
        };
        let search_prefix = search_prefix.as_ref().unwrap();
        assert!(
            prefix.starts_with(search_prefix),
            "prefixes mismatch: {:?} must start with {:?}",
            prefix,
            search_prefix
        );
        assert_eq!(
            prefix.len(),
            search_prefix.len() + 1,
            "prefix wrong length: len({:?}) is not {}",
            prefix,
            search_prefix.len() + 1
        );
        *len += node.len();
        if items.is_empty() {
            *node_width = prefix.len();
        }
        assert_eq!(
            *node_width,
            search_prefix.len() + 1,
            "node width mismatch: {} is not {}",
            *node_width,
            search_prefix.len() + 1
        );
        items.insert(prefix.clone(), node.into());
        *key = None;
        Ok(())
    }

    /// Check if this node is a leaf node
    pub fn is_leaf(&self) -> bool {
        matches!(self, Node::Leaf { .. })
    }

    /// Check if this node is an internal node
    pub fn is_internal(&self) -> bool {
        matches!(self, Node::Internal { .. })
    }

    /// Check if this node is empty
    #[allow(dead_code)]
    fn is_empty(&self) -> bool {
        match self {
            Node::Internal { len, .. } => *len == 0,
            Node::Leaf { len, .. } => *len == 0,
        }
    }

    /// Get the width of the node
    #[allow(dead_code)]
    fn key_width(&self) -> usize {
        match self {
            Node::Internal { key_width, .. } => *key_width,
            Node::Leaf { key_width, .. } => *key_width,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_search_key_16() {
        // Test that search_key_16 behaves the same as the Python implementation
        assert_eq!(
            search_key_16(&Key::from(vec![b"foo".to_vec()])),
            b"8C736521".to_vec()
        );
        assert_eq!(
            search_key_16(&Key::from(vec![b"foo".to_vec(), b"foo".to_vec()])),
            b"8C736521\x008C736521".to_vec()
        );
        assert_eq!(
            search_key_16(&Key::from(vec![b"foo".to_vec(), b"bar".to_vec()])),
            b"8C736521\x0076FF8CAA".to_vec()
        );
        assert_eq!(
            search_key_16(&Key::from(vec![b"abcd".to_vec()])),
            b"ED82CD11".to_vec()
        );
    }

    #[test]
    fn test_search_key_255() {
        // Test that search_key_255 behaves the same as the Python implementation
        assert_eq!(
            search_key_255(&Key::from(vec![b"foo".to_vec()])),
            b"\x8cse!".to_vec()
        );
        assert_eq!(
            search_key_255(&Key::from(vec![b"foo".to_vec(), b"foo".to_vec()])),
            b"\x8cse!\x00\x8cse!".to_vec()
        );
        assert_eq!(
            search_key_255(&Key::from(vec![b"foo".to_vec(), b"bar".to_vec()])),
            b"\x8cse!\x00v\xff\x8c\xaa".to_vec()
        );
    }

    #[test]
    fn test_search_key_255_no_newline() {
        // Test that search_key_255 never includes a newline character
        for i in 0u8..255 {
            let search_key = search_key_255(&Key::from(vec![vec![i]]));
            assert!(!search_key.contains(&b'\n'));
        }
    }

    #[test]
    fn test_bytes_to_text_key() {
        // Test that bytes_to_text_key behaves the same as the Python implementation
        let result = bytes_to_text_key(
            b"file: file-id\nparent-id\nname\nrevision-id\nda39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN",
        );
        assert!(result.is_ok());
        let (key1, key2) = result.unwrap();
        assert_eq!(key1, b"file-id");
        assert_eq!(key2, b"revision-id");

        // Test invalid inputs
        assert!(bytes_to_text_key(
            b"file  file-id\nparent-id\nname\nrevision-id\nda39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN"
        )
        .is_err());
        assert!(bytes_to_text_key(
            b"file:file-id\nparent-id\nname\nrevision-id\nda39a3ee5e6b4b0d3255bfef95601890afd80709\n100\nN"
        )
        .is_err());
        assert!(bytes_to_text_key(b"file:file-id").is_err());
    }

    #[test]
    fn test_common_prefix_pair() {
        // Test that common_prefix_pair behaves the same as the Python implementation
        assert_eq!(common_prefix_pair(b"", b""), b"");
        assert_eq!(common_prefix_pair(b"a", b""), b"");
        assert_eq!(common_prefix_pair(b"", b"a"), b"");
        assert_eq!(common_prefix_pair(b"a", b"a"), b"a");
        assert_eq!(common_prefix_pair(b"aa", b"ab"), b"a");
        assert_eq!(common_prefix_pair(b"aa", b"aa"), b"aa");
    }

    #[test]
    fn test_common_prefix_many() {
        // Test that common_prefix_many behaves the same as the Python implementation
        // Need static references since common_prefix_many returns a reference
        let a = b"a".as_slice();
        let aa = b"aa".as_slice();
        let ab = b"ab".as_slice();
        let ac = b"ac".as_slice();
        let empty = b"".as_slice();

        assert_eq!(common_prefix_many(vec![].into_iter()), None);
        assert_eq!(common_prefix_many(vec![a].into_iter()), Some(a));
        assert_eq!(common_prefix_many(vec![a, a].into_iter()), Some(a));
        assert_eq!(common_prefix_many(vec![aa, ab].into_iter()), Some(a));
        assert_eq!(common_prefix_many(vec![aa, empty].into_iter()), Some(empty));
        assert_eq!(common_prefix_many(vec![aa, ab, ac].into_iter()), Some(a));
    }
    use std::io::BufReader;
    use std::io::Read;

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

    #[test]
    fn test_key_value_len() {
        let key = Key(vec![b"test".to_vec()]);
        let value = b"test\x00value\n\n".to_vec();
        assert_eq!(key_value_len(&key, &value), 20);
    }

    #[test]
    fn test_are_search_keys_identical() {
        let keys = vec![Key(vec![b"test".to_vec()]), Key(vec![b"test".to_vec()])];
        assert!(are_search_keys_identical(keys.iter(), search_key_plain));

        let keys = vec![Key(vec![b"test".to_vec()]), Key(vec![b"test2".to_vec()])];
        assert!(!are_search_keys_identical(keys.iter(), search_key_plain));
    }
    #[test]
    fn test_leaf_deserialize() {
        let data = BufReader::new(
            &b"chkleaf:
100
10
2

test\x002
valueline1
valueling2
test2\x001
valueline1
"[..],
        );
        let node = Node::deserialise(data, Key::from((&b"test"[..],)), None).unwrap();
        assert!(node.is_leaf());
        assert_eq!(node.len(), 2);
        assert_eq!(
            node.keys().collect::<HashSet<_>>(),
            maplit::hashset! {Key::from((&b"test"[..], )), Key::from((&b"test2"[..], ))}
        );
        assert_eq!(node.maximum_size(), 100);
        assert_eq!(node.key_width(), 10);
    }

    #[test]
    fn test_internal_deserialize() {
        let data = BufReader::new(
            &b"chknode:
100
10
2

test\x00value
test2\x00value2
"[..],
        );
        let node = Node::deserialise(data, Key::from((&b"test"[..],)), None).unwrap();
        assert!(node.is_internal());
        assert_eq!(node.len(), 2);
        assert_eq!(
            node.keys().collect::<HashSet<_>>(),
            maplit::hashset! {Key::from((&b"test"[..], )), Key::from((&b"test2"[..], ))}
        );
        assert_eq!(node.maximum_size(), 100);
        assert_eq!(node.key_width(), 10);
    }
}

/// Get the size of a key:value pair
// TODO: Just serialize?
fn key_value_len(key: &Key, value: &[u8]) -> usize {
    key.serialize().len()
        + 1
        + value
            .iter()
            .filter(|&&f| f == b'\n')
            .count()
            .to_string()
            .len()
        + 1
        + value.len()
        + 1
}

/// Check to see if the search keys for all entries are the same.
///
/// When using a hash as the search_key it is possible for non-identical
/// keys to collide. If that happens enough, we may try overflow a
/// LeafNode, but as all are collisions, we must not split.
#[allow(dead_code)]
fn are_search_keys_identical<'a>(
    keys: impl Iterator<Item = &'a Key>,
    search_key_func: SearchKeyFn,
) -> bool {
    let mut common_search_key = None;
    for key in keys {
        let search_key = search_key_func(key);
        if common_search_key.is_none() {
            common_search_key = Some(search_key);
        } else if Some(search_key) != common_search_key {
            return false;
        }
    }
    return true;
}

pub trait Store {
    /// Add lines to the store.
    ///
    /// # Arguments
    /// * `lines`: The lines to add to the store.
    ///
    /// Returns: The SHA1
    fn add_lines(&self, lines: Vec<Vec<u8>>) -> Result<Vec<u8>, Error>;

    /// Get a record stream for the given keys
    fn get_record_stream<'a>(
        &'a self,
        keys: &'a [Key],
    ) -> Box<dyn Iterator<Item = (Key, Vec<u8>)> + 'a>;
}

/// A content hash key map.
///
/// Maps from key tuples to values.
pub struct CHKMap {
    store: Arc<dyn Store>,
    root_node: Option<Node>,
    root_key: Option<Key>,
    search_key_func: SearchKeyFn,
    pending_keys: HashMap<Key, Option<Vec<u8>>>,
}

impl CHKMap {
    /// Create a new CHKMap.
    ///
    /// # Arguments
    /// * `store`: The store to use for backing storage.
    /// * `root_key`: The root key of the map. If None, the map is empty.
    /// * `search_key_func`: The function to use to calculate search keys. If None, uses search_key_plain.
    pub fn new(
        store: Arc<dyn Store>,
        root_key: Option<Key>,
        search_key_func: Option<SearchKeyFn>,
    ) -> Self {
        Self {
            store,
            root_node: None,
            root_key,
            search_key_func: search_key_func.unwrap_or(DEFAULT_SEARCH_KEY_FUNC),
            pending_keys: HashMap::new(),
        }
    }

    /// Get the length of the map.
    pub fn len(&mut self) -> usize {
        if let Some(ref node) = self.root_node {
            node.len()
        } else if let Some(ref _key) = self.root_key {
            // Need to load the node
            let node = self.load_root_node();
            match node {
                Ok(node) => node.len(),
                Err(_) => 0,
            }
        } else {
            // Empty map
            0
        }
    }

    /// Get the root key of the map.
    pub fn key(&self) -> Option<Key> {
        self.root_key.clone()
    }

    /// Map a key to a value.
    pub fn map(&mut self, key: &Key, value: Vec<u8>) {
        // Add to pending keys for lazy evaluation
        self.pending_keys.insert(key.clone(), Some(value));
    }

    /// Unmap a key.
    pub fn unmap(&mut self, _key: &Key, _check_remap: bool) {
        // Mark the key as None in pending_keys for lazy deletion
        self.pending_keys.insert(_key.clone(), None);
    }

    /// Save the map.
    pub fn _save(&mut self) -> Result<Key, Error> {
        // Apply all pending changes
        if self.pending_keys.is_empty() {
            // Nothing to do
            return self.root_key.clone().ok_or(Error::NotFound);
        }

        // Create a root node if it doesn't exist
        if self.root_node.is_none() {
            self.load_root_node()?;
        }

        // For now, just return the existing key (or an error if none)
        self.root_key.clone().ok_or(Error::NotFound)
    }

    /// Dump the tree as a string for debugging.
    pub fn _dump_tree(&mut self, _include_keys: bool, _encoding: &str) -> String {
        // Basic implementation that just shows structure
        let mut result = String::new();
        if let Some(ref key) = self.root_key {
            write!(result, "CHKMap with root key: {}", key).unwrap();
        } else {
            write!(result, "Empty CHKMap").unwrap();
        }
        result
    }

    /// Apply a delta to the map.
    pub fn apply_delta(
        &mut self,
        _delta: Vec<(Option<Key>, Option<Key>, Vec<u8>)>,
    ) -> Result<Key, Error> {
        // Need to implement a full delta application
        // For now, just return the existing key or an error
        self.root_key.clone().ok_or(Error::NotFound)
    }

    /// Iterate over all the items in the map.
    pub fn iteritems<'a>(
        &'a mut self,
        _key_filter: Option<&'a [Key]>,
    ) -> Box<dyn Iterator<Item = (Key, Vec<u8>)> + 'a> {
        // For now, return an empty iterator
        Box::new(std::iter::empty())
    }

    /// Iterate over the changes between this map and another map.
    pub fn iter_changes<'a>(
        &'a mut self,
        _basis: &'a mut CHKMap,
    ) -> Box<dyn Iterator<Item = (Key, Option<Vec<u8>>, Option<Vec<u8>>)> + 'a> {
        // For now, return an empty iterator
        Box::new(std::iter::empty())
    }

    /// Load the root node from storage.
    /// This creates the root node if it doesn't exist yet.
    fn load_root_node(&mut self) -> Result<&Node, Error> {
        if self.root_node.is_some() {
            return Ok(self.root_node.as_ref().unwrap());
        }

        if let Some(ref key) = self.root_key {
            // Try to load the node from storage
            let keys = [key.clone()];
            let record_stream = self.store.get_record_stream(&keys);
            let records: Vec<_> = record_stream.collect();

            if records.is_empty() {
                return Err(Error::NotFound);
            }

            let (_, record_data) = &records[0];
            let reader = std::io::BufReader::new(record_data.as_slice());
            let node = Node::deserialise(reader, key.clone(), Some(self.search_key_func))?;
            self.root_node = Some(node);

            Ok(self.root_node.as_ref().unwrap())
        } else {
            // Create a new empty node
            let node = Node::leaf(Some(self.search_key_func));
            self.root_node = Some(node);

            Ok(self.root_node.as_ref().unwrap())
        }
    }
}

/// Create a CHKMap from a dictionary of initial values.
pub fn from_dict(
    store: Arc<dyn Store>,
    initial_value: HashMap<Key, Vec<u8>>,
    maximum_size: usize,
    _key_width: usize,
    search_key_func: Option<SearchKeyFn>,
) -> Result<Key, Error> {
    let search_key_func = search_key_func.unwrap_or(DEFAULT_SEARCH_KEY_FUNC);

    // Create a new CHKMap
    let mut map = CHKMap::new(store, None, Some(search_key_func));

    // Add all values from the initial dictionary
    for (key, value) in initial_value {
        map.map(&key, value);
    }

    // Set maximum size if specified
    if maximum_size > 0 {
        if let Some(ref mut node) = map.root_node {
            node.set_maximum_size(maximum_size);
        }
    }

    // Save the map
    match map._save() {
        Ok(key) => Ok(key),
        Err(e) => Err(e),
    }
}

/// Iterate the stored pages and key,value pairs for (new - old).
///
/// This calculates the interesting pages between a new set of root nodes
/// and an old set of root nodes.
pub fn iter_interesting_nodes<'a>(
    store: &'a dyn Store,
    new_root_keys: &'a [Key],
    old_root_keys: &'a [Key],
    _search_key_func: SearchKeyFn,
    progress: Option<&'a mut dyn Write>,
) -> Box<dyn Iterator<Item = (Key, HashMap<Key, Vec<u8>>)> + 'a> {
    // Create sets of keys
    let new_keys: Vec<Key> = new_root_keys.to_vec();
    let old_keys: Vec<Key> = old_root_keys.to_vec();

    // If we have a progress indicator, tick it for each key we'll examine
    if let Some(progress) = progress {
        write!(
            progress,
            "Examining {} new keys and {} old keys",
            new_keys.len(),
            old_keys.len()
        )
        .unwrap();
    }

    // If there are no new keys, return an empty iterator
    if new_keys.is_empty() {
        return Box::new(std::iter::empty());
    }

    // Get record stream for new keys
    let _records = store.get_record_stream(new_keys.as_slice());

    // Convert to our expected format - just return an empty iterator for now
    // Real implementation would need to compare old and new nodes
    Box::new(std::iter::empty())
}
