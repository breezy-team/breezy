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

use std::collections::{HashMap, HashSet};
use std::fmt::Write;
use std::hash::Hash;
use std::io::{BufRead, Write as _};
use std::iter::zip;

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
    /// not calculated yet
    Unknown,

    /// no keys
    None,

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

#[derive(Debug, Hash, PartialEq, Eq, Clone)]
pub struct Key(Vec<Vec<u8>>);

impl From<Vec<Vec<u8>>> for Key {
    fn from(v: Vec<Vec<u8>>) -> Self {
        assert!(!v.is_empty(), "Key cannot be empty");
        assert!(
            v.iter().all(|v| !v.is_empty()),
            "Key cannot contain empty elements: {:?}",
            v
        );
        Key(v)
    }
}

impl From<Vec<&[u8]>> for Key {
    fn from(v: Vec<&[u8]>) -> Self {
        assert!(!v.is_empty(), "Key cannot be empty");
        assert!(
            v.iter().all(|v| !v.is_empty()),
            "Key cannot contain empty elements: {:?}",
            v
        );
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
        result.pop();
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

#[derive(Debug)]
pub enum Error {
    InconsistentDeltaDelta(Vec<(Option<Key>, Option<Key>, Value)>, String),
    DeserializeError(String),
    IoError(std::io::Error),
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::IoError(e)
    }
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
            NodeChild::Node(n) => n.key(),
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

    pub fn keys(&self) -> Box<dyn Iterator<Item = Key> + '_> {
        match self {
            Node::Leaf { items, .. } => Box::new(items.keys().cloned()),
            Node::Internal { items, .. } => Box::new(items.keys().map(|k| Key::deserialize(k))),
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

    /// Get the key
    pub fn key(&self) -> Option<&Key> {
        match self {
            Node::Leaf { key, .. } => key.as_ref(),
            Node::Internal { key, .. } => key.as_ref(),
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

    /// Get the maximum size of this node
    fn maximum_size(&self) -> usize {
        match self {
            Node::Leaf { maximum_size, .. } => *maximum_size,
            Node::Internal { maximum_size, .. } => *maximum_size,
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

    /// Check if this node is a leaf node
    pub fn is_leaf(&self) -> bool {
        matches!(self, Node::Leaf { .. })
    }

    /// Check if this node is an internal node
    pub fn is_internal(&self) -> bool {
        matches!(self, Node::Internal { .. })
    }

    /// Return the number of items in this node
    pub fn len(&self) -> usize {
        match self {
            Node::Internal { len, .. } => *len,
            Node::Leaf { len, .. } => *len,
        }
    }

    /// Check if this node is empty
    fn is_empty(&self) -> bool {
        match self {
            Node::Internal { len, .. } => *len == 0,
            Node::Leaf { len, .. } => *len == 0,
        }
    }

    /// Get the width of the node
    fn key_width(&self) -> usize {
        match self {
            Node::Internal { key_width, .. } => *key_width,
            Node::Leaf { key_width, .. } => *key_width,
        }
    }
}

#[cfg(test)]
mod node_tests {
    use super::*;
    use std::io::BufReader;
    use std::io::Read;
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
fn key_value_len(key: &Key, value: &Value) -> usize {
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

#[cfg(test)]
#[test]
fn test_are_search_keys_identical() {
    let keys = vec![Key(vec![b"test".to_vec()]), Key(vec![b"test".to_vec()])];
    assert!(are_search_keys_identical(keys.iter(), search_key_plain));

    let keys = vec![Key(vec![b"test".to_vec()]), Key(vec![b"test2".to_vec()])];
    assert!(!are_search_keys_identical(keys.iter(), search_key_plain));
}
