//! Inventory delta serialisation.
//!
//! See doc/developers/inventory.txt for the description of the format.
//!
//! In this module the interesting classes are:
//!  - InventoryDeltaSerializer - object to read/write inventory deltas.

use crate::inventory::Entry;
use crate::{FileId, RevisionId, NULL_REVISION};
use std::collections::HashSet;
use std::iter::FromIterator;

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct InventoryDeltaEntry {
    pub old_path: Option<String>,
    pub new_path: Option<String>,
    pub file_id: FileId,
    pub new_entry: Option<Entry>,
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct InventoryDelta(pub Vec<InventoryDeltaEntry>);

impl FromIterator<InventoryDeltaEntry> for InventoryDelta {
    fn from_iter<T: IntoIterator<Item = InventoryDeltaEntry>>(iter: T) -> Self {
        InventoryDelta(iter.into_iter().collect())
    }
}

impl From<Vec<InventoryDeltaEntry>> for InventoryDelta {
    fn from(v: Vec<InventoryDeltaEntry>) -> Self {
        InventoryDelta(v)
    }
}

impl std::ops::Deref for InventoryDelta {
    type Target = Vec<InventoryDeltaEntry>;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl std::ops::DerefMut for InventoryDelta {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

pub enum InventoryDeltaInconsistency {
    DuplicateFileId(String, FileId),
    DuplicateOldPath(String, FileId),
    DuplicateNewPath(String, FileId),
    NoPath,
    MismatchedId(String, FileId, FileId),
    EntryWithoutPath(String, FileId),
    PathWithoutEntry(String, FileId),
    PathMismatch(FileId, String, String),
    OrphanedChild(FileId),
    ParentNotDirectory(String, FileId),
    ParentMissing(FileId),
    NoSuchId(FileId),
    InvalidEntryName(String),
    FileIdCycle(FileId, String, String),
    PathAlreadyVersioned(String, String),
}

impl InventoryDelta {
    pub fn check(&self) -> Result<(), InventoryDeltaInconsistency> {
        let mut ids = HashSet::new();
        let mut old_paths = HashSet::new();
        let mut new_paths = HashSet::new();
        for entry in self.iter() {
            let path = if let Some(old_path) = &entry.old_path {
                old_path
            } else if let Some(new_path) = &entry.new_path {
                new_path
            } else {
                return Err(InventoryDeltaInconsistency::NoPath);
            };

            if !ids.insert(&entry.file_id) {
                return Err(InventoryDeltaInconsistency::DuplicateFileId(
                    path.clone(),
                    entry.file_id.clone(),
                ));
            }

            if entry.old_path.is_some() {
                let old_path = entry.old_path.as_ref().unwrap();
                if !old_paths.insert(old_path) {
                    return Err(InventoryDeltaInconsistency::DuplicateOldPath(
                        old_path.clone(),
                        entry.file_id.clone(),
                    ));
                }
            }

            if entry.new_path.is_some() {
                let new_path = entry.new_path.as_ref().unwrap();
                if !new_paths.insert(new_path) {
                    return Err(InventoryDeltaInconsistency::DuplicateNewPath(
                        new_path.clone(),
                        entry.file_id.clone(),
                    ));
                }
            }

            if let Some(ref new_entry) = entry.new_entry {
                if &entry.file_id != new_entry.file_id() {
                    return Err(InventoryDeltaInconsistency::MismatchedId(
                        path.clone(),
                        entry.file_id.clone(),
                        new_entry.file_id().clone(),
                    ));
                }
            }

            if entry.new_entry.is_some() && entry.new_path.is_none() {
                return Err(InventoryDeltaInconsistency::EntryWithoutPath(
                    path.clone(),
                    entry.file_id.clone(),
                ));
            }

            if entry.new_entry.is_none() && entry.new_path.is_some() {
                return Err(InventoryDeltaInconsistency::PathWithoutEntry(
                    path.clone(),
                    entry.file_id.clone(),
                ));
            }
        }
        Ok(())
    }

    pub fn sort(&mut self) {
        fn key(entry: &InventoryDeltaEntry) -> (&str, &str, &FileId, Option<&Entry>) {
            (
                entry.old_path.as_deref().unwrap_or(""),
                entry.new_path.as_deref().unwrap_or(""),
                &entry.file_id,
                entry.new_entry.as_ref(),
            )
        }
        self.sort_by(|x, y| key(y).cmp(&key(x)));
    }
}

#[derive(Debug)]
pub enum InventoryDeltaSerializeError {
    Invalid(String),
    UnsupportedKind(String),
}

const FORMAT_1: &str = "bzr inventory delta v1 (bzr 1.14)";

pub fn serialize_inventory_entry(e: &Entry) -> Result<Vec<u8>, InventoryDeltaSerializeError> {
    Ok(match e {
        Entry::Directory { .. } | Entry::Root { .. } => b"dir".to_vec(),
        Entry::File {
            executable,
            text_size,
            ref text_sha1,
            ..
        } => {
            let mut v = b"file".to_vec();
            v.push(b'\x00');
            if text_size.is_none() {
                return Err(InventoryDeltaSerializeError::Invalid(
                    "text_size is None".to_string(),
                ));
            }
            v.extend_from_slice(text_size.unwrap().to_string().as_bytes());
            v.push(b'\x00');
            if *executable {
                v.push(b'Y');
            }
            v.push(b'\x00');
            let text_sha1 = text_sha1.as_ref();
            if text_sha1.is_none() {
                return Err(InventoryDeltaSerializeError::Invalid(
                    "text_sha1 is None".to_string(),
                ));
            }
            v.extend_from_slice(text_sha1.unwrap().as_slice());
            v
        }
        Entry::Link { symlink_target, .. } => {
            let mut v = b"link".to_vec();
            v.push(b'\x00');
            if symlink_target.is_none() {
                return Err(InventoryDeltaSerializeError::Invalid(
                    "symlink_target is None".to_string(),
                ));
            }
            v.extend_from_slice(symlink_target.as_ref().unwrap().as_bytes());
            v
        }
        Entry::TreeReference {
            reference_revision, ..
        } => {
            let mut v = b"tree".to_vec();
            v.push(b'\x00');
            if reference_revision.is_none() {
                return Err(InventoryDeltaSerializeError::Invalid(
                    "reference_revision is None".to_string(),
                ));
            }
            v.extend_from_slice(reference_revision.as_ref().unwrap().as_bytes());
            v
        }
    })
}

pub fn serialize_inventory_delta(
    old_name: &RevisionId,
    new_name: &RevisionId,
    delta_to_new: &InventoryDelta,
    versioned_root: bool,
    tree_references: bool,
) -> Result<Vec<Vec<u8>>, InventoryDeltaSerializeError> {
    let mut lines = vec![
        format!("format: {}\n", FORMAT_1).into_bytes(),
        [&b"parent: "[..], old_name.as_bytes(), &b"\n"[..]].concat(),
        [&b"version: "[..], new_name.as_bytes(), &b"\n"[..]].concat(),
        format!("versioned_root: {}\n", serialize_bool(versioned_root)).into_bytes(),
        format!("tree_references: {}\n", serialize_bool(tree_references)).into_bytes(),
    ];

    let mut extra_lines = delta_to_new
        .iter()
        .map(|entry| {
            if let Some(entry) = entry.new_entry.as_ref() {
                if !tree_references && entry.kind() == breezy_osutils::Kind::TreeReference {
                    return Err(InventoryDeltaSerializeError::UnsupportedKind(
                        "tree-reference".to_string(),
                    ));
                }
            }

            delta_entry_to_line(entry, new_name, Some(versioned_root))
        })
        .collect::<Result<Vec<_>, _>>()?;
    extra_lines.sort();
    lines.extend(extra_lines);
    Ok(lines)
}

/// Return a line sequence for delta_to_new.
///
/// :param old_name: A UTF8 revision id for the old inventory.  May be
///    NULL_REVISION if there is no older inventory and delta_to_new
///    includes the entire inventory contents.
/// :param new_name: The version name of the inventory we create with this
///     delta.
/// :param delta_to_new: An inventory delta such as Inventory.apply_delta
///    takes.
/// :return: The serialized delta as lines.
fn delta_entry_to_line(
    delta_item: &InventoryDeltaEntry,
    new_version: &RevisionId,
    versioned_root: Option<bool>,
) -> Result<Vec<u8>, InventoryDeltaSerializeError> {
    let versioned_root = versioned_root.unwrap_or(true);
    let last_modified;
    let parent_id;
    let oldpath_utf8;
    let newpath_utf8;
    let content;
    if delta_item.new_path.is_none() {
        // delete
        if delta_item.old_path.is_none() {
            return Err(InventoryDeltaSerializeError::Invalid(format!(
                "Bad inventory delta: old_path is None in delta item {:?}",
                delta_item
            )));
        }
        oldpath_utf8 = format!("/{}", delta_item.old_path.as_ref().unwrap());
        newpath_utf8 = "None".to_string();
        parent_id = &b""[..];
        last_modified = RevisionId::from(NULL_REVISION);
        content = b"deleted\x00\x00".to_vec();
    } else {
        oldpath_utf8 = if let Some(ref old_path) = delta_item.old_path {
            format!("/{}", old_path)
        } else {
            "None".to_string()
        };
        if delta_item.new_entry.is_none() {
            return Err(InventoryDeltaSerializeError::Invalid(format!(
                "Bad inventory delta: new_entry is None in delta item {:?}",
                delta_item
            )));
        }
        let new_entry = delta_item.new_entry.as_ref().unwrap();
        if delta_item.new_path == Some("/".to_string()) {
            return Err(InventoryDeltaSerializeError::Invalid(format!(
                "Bad inventory delta: '/' is not a valid newpath (should be '') in delta item {:?}",
                delta_item
            )));
        }
        newpath_utf8 = format!(
            "/{}",
            delta_item.new_path.as_ref().unwrap_or(&"".to_string())
        );
        // Serialize None as ''
        parent_id = new_entry
            .parent_id()
            .as_ref()
            .map_or(&b""[..], |x| x.as_bytes());
        // Serialize unknown revisions as NULL_REVISION
        if new_entry.revision().is_none() {
            return Err(InventoryDeltaSerializeError::Invalid(format!(
                "no version for fileid {:?}",
                delta_item.file_id
            )));
        }
        last_modified = new_entry.revision().unwrap().clone();

        // special cases for /
        if newpath_utf8 == "/" && !versioned_root {
            // This is an entry for the root, this inventory does not
            // support versioned roots.  So this must be an unversioned
            // root, i.e. last_modified == new revision.  Otherwise, this
            // delta is invalid.
            // Note: the non-rich-root repositories *can* have roots with
            // file-ids other than TREE_ROOT, e.g. repo formats that use the
            // xml5 serializer.
            if &last_modified != new_version {
                return Err(InventoryDeltaSerializeError::Invalid(format!(
                    "Version present for / in {:?} ({:?} != {:?})",
                    new_entry.file_id(),
                    last_modified,
                    new_version
                )));
            }
        }
        content = serialize_inventory_entry(new_entry)?;
    }
    let entries = [oldpath_utf8.as_bytes(),
        newpath_utf8.as_bytes(),
        delta_item.file_id.as_bytes(),
        parent_id,
        last_modified.as_bytes(),
        content.as_slice()];
    let mut line = entries.join(&b"\x00"[..]);
    line.push(b'\n');
    Ok(line)
}

pub fn parse_inventory_entry(
    file_id: FileId,
    name: String,
    parent_id: Option<FileId>,
    revision: Option<RevisionId>,
    data: &[u8],
) -> Entry {
    let mut parts = data.split(|&c| c == b'\x00');
    let entry_type = parts.next().unwrap();
    match entry_type {
        b"dir" => {
            if parent_id.is_none() {
                Entry::Root { file_id, revision }
            } else {
                Entry::Directory {
                    file_id,
                    name,
                    parent_id: parent_id.unwrap(),
                    revision,
                }
            }
        }
        b"file" => {
            let text_size = parts.next().unwrap();
            let executable = parts.next().unwrap();
            let text_sha1 = parts.next().unwrap();
            Entry::File {
                file_id,
                name,
                parent_id: parent_id.unwrap(),
                executable: executable == b"Y",
                text_id: None,
                text_size: Some(
                    String::from_utf8(text_size.to_vec())
                        .unwrap()
                        .parse()
                        .unwrap(),
                ),
                text_sha1: Some(text_sha1.to_vec()),
                revision,
            }
        }
        b"link" => {
            let symlink_target = parts.next().unwrap();
            Entry::Link {
                file_id,
                name,
                parent_id: parent_id.unwrap(),
                symlink_target: Some(String::from_utf8(symlink_target.to_vec()).unwrap()),
                revision,
            }
        }
        b"tree" => {
            let reference_revision = parts.next().unwrap();
            Entry::TreeReference {
                file_id,
                name,
                parent_id: parent_id.unwrap(),
                reference_revision: Some(RevisionId::from(reference_revision)),
                revision,
            }
        }
        _ => panic!("Invalid entry type: {:?}", entry_type),
    }
}

fn serialize_bool(value: bool) -> &'static str {
    if value {
        "true"
    } else {
        "false"
    }
}

fn parse_bool(value: &[u8]) -> Result<bool, String> {
    match value {
        b"true" => Ok(true),
        b"false" => Ok(false),
        _ => Err(format!("Invalid boolean value: {:?}", value)),
    }
}

pub fn parse_inventory_delta_item(
    line: &[u8],
    versioned_root: bool,
    tree_references: bool,
    delta_version_id: &RevisionId,
) -> Result<InventoryDeltaEntry, InventoryDeltaParseError> {
    let parts = line.splitn(6, |&c| c == b'\x00').collect::<Vec<_>>();

    let oldpath_utf8 = parts[0];
    let newpath_utf8 = parts[1];
    let file_id = FileId::from(parts[2]);
    let parent_id = if parts[3].is_empty() {
        None
    } else {
        Some(FileId::from(parts[3]))
    };
    let last_modified = RevisionId::from(parts[4]);
    let content = parts[5];

    if newpath_utf8 == b"/" && !versioned_root && &last_modified != delta_version_id {
        return Err(InventoryDeltaParseError::Invalid(
            "Versioned root found".to_string(),
        ));
    } else if newpath_utf8 != b"None" && last_modified.is_reserved() {
        return Err(InventoryDeltaParseError::Invalid(format!(
            "special revisionid found: {:?}",
            last_modified
        )));
    }

    if content.starts_with(b"tree\x00") && !tree_references {
        return Err(InventoryDeltaParseError::Invalid(
            "Tree reference found (but header said tree_references: false)".to_string(),
        ));
    }

    fn parse_path(kind: &str, path: &[u8]) -> Result<Option<String>, InventoryDeltaParseError> {
        if path == b"None" {
            Ok(None)
        } else if !path.starts_with(b"/") {
            Err(InventoryDeltaParseError::Invalid(format!(
                "{} invalid: {} (does not start with /)",
                kind,
                String::from_utf8_lossy(path)
            )))
        } else {
            Ok(Some(String::from_utf8(path[1..].to_vec()).map_err(
                |x| {
                    InventoryDeltaParseError::Invalid(format!(
                        "{} invalid: {} (invalid utf8: {})",
                        kind,
                        String::from_utf8_lossy(path),
                        x
                    ))
                },
            )?))
        }
    }

    let old_path = parse_path("oldpath", oldpath_utf8)?;
    let new_path = parse_path("newpath", newpath_utf8)?;

    let new_entry = if content.starts_with(b"deleted\x00") {
        None
    } else {
        let name = new_path.as_ref().unwrap().rsplit_once('/').map_or_else(
            || new_path.as_ref().unwrap().clone(),
            |(_, name)| name.to_string(),
        );
        Some(parse_inventory_entry(
            file_id.clone(),
            name,
            parent_id,
            Some(last_modified),
            content,
        ))
    };
    Ok(InventoryDeltaEntry {
        old_path,
        new_path,
        file_id,
        new_entry,
    })
}

#[derive(Debug)]
pub enum InventoryDeltaParseError {
    Incompatible(String),
    Invalid(String),
}

pub fn parse_inventory_delta(
    lines: &[&[u8]],
    allow_versioned_root: Option<bool>,
    allow_tree_references: Option<bool>,
) -> Result<(RevisionId, RevisionId, bool, bool, InventoryDelta), InventoryDeltaParseError> {
    let allow_versioned_root = allow_versioned_root.unwrap_or(true);
    let allow_tree_references = allow_tree_references.unwrap_or(true);

    if lines.is_empty() {
        return Err(InventoryDeltaParseError::Invalid(
            "Invalid inventory delta is empty".to_string(),
        ));
    }

    if !lines[lines.len() - 1].ends_with(b"\n") {
        return Err(InventoryDeltaParseError::Invalid(
            "last line not empty".to_string(),
        ));
    }

    let lines = lines
        .iter()
        .map(|x| x.strip_suffix(b"\n").unwrap())
        .collect::<Vec<_>>();

    if lines.is_empty() || lines[0] != [&b"format: "[..], FORMAT_1.as_bytes()].concat() {
        return Err(InventoryDeltaParseError::Invalid(format!(
            "unknown format: {}",
            String::from_utf8_lossy(&lines[0][8..])
        )));
    }

    if lines.len() < 2 || !lines[1].starts_with(b"parent: ") {
        return Err(InventoryDeltaParseError::Invalid(
            "missing parent: marker".to_string(),
        ));
    }

    let delta_parent_id = RevisionId::from(lines[1][8..].to_vec());

    if lines.len() < 3 || !lines[2].starts_with(b"version: ") {
        return Err(InventoryDeltaParseError::Invalid(
            "missing version: marker".to_string(),
        ));
    }

    let delta_version = RevisionId::from(lines[2][9..].to_vec());

    if lines.len() < 4 || !lines[3].starts_with(b"versioned_root: ") {
        return Err(InventoryDeltaParseError::Invalid(
            "missing versioned_root: marker".to_string(),
        ));
    }

    let delta_versioned_root = parse_bool(&lines[3][16..]).unwrap();

    if !allow_versioned_root && delta_versioned_root {
        return Err(InventoryDeltaParseError::Incompatible(
            "versioned_root not allowed".to_string(),
        ));
    }

    if lines.len() < 5 || !lines[4].starts_with(b"tree_references: ") {
        return Err(InventoryDeltaParseError::Invalid(
            "missing tree_references: marker".to_string(),
        ));
    }

    let delta_tree_references = parse_bool(&lines[4][17..]).unwrap();

    let mut result = Vec::new();

    let mut ids = HashSet::new();

    for line in lines.iter().skip(5) {
        let item = parse_inventory_delta_item(
            line,
            delta_versioned_root,
            delta_tree_references,
            &delta_version,
        )?;
        if !allow_tree_references
            && item.new_entry.is_some()
            && item.new_entry.as_ref().unwrap().kind() == breezy_osutils::Kind::TreeReference
        {
            return Err(InventoryDeltaParseError::Incompatible(
                "Tree reference not allowed".to_string(),
            ));
        }
        if !ids.insert(item.file_id.clone()) {
            return Err(InventoryDeltaParseError::Invalid(format!(
                "duplicate file id: {:?}",
                item.file_id
            )));
        }
        result.push(item);
    }

    Ok((
        delta_parent_id,
        delta_version,
        delta_versioned_root,
        delta_tree_references,
        InventoryDelta(result),
    ))
}
