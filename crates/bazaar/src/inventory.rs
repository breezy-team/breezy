use crate::{FileId, RevisionId};
use breezy_osutils::Kind;
use std::collections::HashMap;
use std::collections::HashSet;

// This should really be an id randomly assigned when the tree is
// created, but it's not for now.
pub const ROOT_ID: &[u8] = b"TREE_ROOT";

pub fn versionable_kind(kind: Kind) -> bool {
    // Check if a kind is versionable
    matches!(
        kind,
        Kind::File | Kind::Directory | Kind::Symlink | Kind::TreeReference
    )
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum Entry {
    Directory {
        file_id: FileId,
        revision: Option<RevisionId>,
        parent_id: Option<FileId>,
        name: String,
    },
    File {
        file_id: FileId,
        revision: Option<RevisionId>,
        parent_id: Option<FileId>,
        name: String,
        text_sha1: Option<Vec<u8>>,
        text_size: Option<u64>,
        text_id: Option<Vec<u8>>,
        executable: bool,
    },
    Link {
        file_id: FileId,
        name: String,
        parent_id: Option<FileId>,
        symlink_target: Option<String>,
        revision: Option<RevisionId>,
    },
    TreeReference {
        file_id: FileId,
        revision: Option<RevisionId>,
        reference_revision: Option<RevisionId>,
        name: String,
        parent_id: Option<FileId>,
    },
}

/// Description of a versioned file.
///
/// An InventoryEntry has the following fields, which are also
/// present in the XML inventory-entry element:
///
/// file_id
///
/// name
///     (within the parent directory)
///
/// parent_id
///     file_id of the parent directory, or ROOT_ID
///
/// revision
///     the revision_id in which this variation of this file was
///     introduced.
///
/// executable
///     Indicates that this file should be executable on systems
///     that support it.
///
/// text_sha1
///     sha-1 of the text of the file
///
/// text_size
///     size in bytes of the text of the file
///
/// (reading a version 4 tree created a text_id field.)

impl Entry {
    pub fn new(kind: Kind, name: String, file_id: FileId, parent_id: Option<FileId>) -> Self {
        if !is_valid_name(&name) {
            panic!("Invalid name: {}", name);
        }
        match kind {
            Kind::File => Entry::file(file_id, name, parent_id),
            Kind::Directory => Entry::directory(file_id, None, parent_id, name),
            Kind::Symlink => Entry::link(file_id, name, parent_id),
            Kind::TreeReference => Entry::tree_reference(file_id, name, parent_id),
        }
    }

    /// Return true if the object this entry represents has textual data.
    ///
    /// Note that textual data includes binary content.
    ///
    /// Also note that all entries get weave files created for them.
    /// This attribute is primarily used when upgrading from old trees that
    /// did not have the weave index for all inventory entries.
    pub fn has_text(&self) -> bool {
        match self {
            Entry::Directory { .. } => false,
            Entry::File { .. } => true,
            Entry::Link { .. } => false,
            Entry::TreeReference { .. } => false,
        }
    }

    pub fn kind(&self) -> Kind {
        match self {
            Entry::Directory { .. } => Kind::Directory,
            Entry::File { .. } => Kind::File,
            Entry::Link { .. } => Kind::Symlink,
            Entry::TreeReference { .. } => Kind::TreeReference,
        }
    }

    pub fn directory(
        file_id: FileId,
        revision: Option<RevisionId>,
        parent_id: Option<FileId>,
        name: String,
    ) -> Self {
        Self::Directory {
            file_id,
            revision,
            parent_id,
            name,
        }
    }

    pub fn file(file_id: FileId, name: String, parent_id: Option<FileId>) -> Self {
        Entry::File {
            file_id,
            name,
            parent_id,
            revision: None,
            text_sha1: None,
            text_size: None,
            text_id: None,
            executable: false,
        }
    }

    pub fn tree_reference(file_id: FileId, name: String, parent_id: Option<FileId>) -> Self {
        Entry::TreeReference {
            file_id,
            revision: None,
            reference_revision: None,
            name,
            parent_id,
        }
    }

    pub fn link(file_id: FileId, name: String, parent_id: Option<FileId>) -> Self {
        Entry::Link {
            file_id,
            name,
            parent_id,
            symlink_target: None,
            revision: None,
        }
    }

    pub fn file_id(&self) -> &FileId {
        match self {
            Entry::Directory { file_id, .. } => file_id,
            Entry::File { file_id, .. } => file_id,
            Entry::Link { file_id, .. } => file_id,
            Entry::TreeReference { file_id, .. } => file_id,
        }
    }

    pub fn parent_id(&self) -> Option<&FileId> {
        match self {
            Entry::Directory { parent_id, .. } => parent_id.as_ref(),
            Entry::File { parent_id, .. } => parent_id.as_ref(),
            Entry::Link { parent_id, .. } => parent_id.as_ref(),
            Entry::TreeReference { parent_id, .. } => parent_id.as_ref(),
        }
    }

    pub fn name(&self) -> &str {
        match self {
            Entry::Directory { name, .. } => name,
            Entry::File { name, .. } => name,
            Entry::Link { name, .. } => name,
            Entry::TreeReference { name, .. } => name,
        }
    }

    pub fn revision(&self) -> Option<&RevisionId> {
        match self {
            Entry::Directory { revision, .. } => revision.as_ref(),
            Entry::File { revision, .. } => revision.as_ref(),
            Entry::Link { revision, .. } => revision.as_ref(),
            Entry::TreeReference { revision, .. } => revision.as_ref(),
        }
    }

    pub fn symlink_target(&self) -> Option<&str> {
        match self {
            Entry::Directory { .. } => None,
            Entry::File { .. } => None,
            Entry::Link { symlink_target, .. } => symlink_target.as_ref().map(|s| s.as_str()),
            Entry::TreeReference { .. } => None,
        }
    }

    pub fn is_unmodified(&self, other: &Entry) -> bool {
        let other_revision = other.revision();

        if other_revision.is_none() {
            return false;
        }

        self.revision() == other_revision
    }

    pub fn unchanged(&self, other: &Entry) -> bool {
        let mut compatible = true;
        // different inv parent
        if self.parent_id() != other.parent_id()
            || self.name() != other.name()
            || self.kind() != other.kind()
        {
            compatible = false;
        }
        match (self, other) {
            (
                Entry::File {
                    text_sha1: this_text_sha1,
                    text_size: this_text_size,
                    executable: this_executable,
                    ..
                },
                Entry::File {
                    text_sha1: other_text_sha1,
                    text_size: other_text_size,
                    executable: other_executable,
                    ..
                },
            ) => {
                if this_text_sha1 != other_text_sha1 {
                    compatible = false;
                }
                if this_text_size != other_text_size {
                    compatible = false;
                }
                if this_executable != other_executable {
                    compatible = false;
                }
            }
            (
                Entry::Link {
                    symlink_target: this_symlink_target,
                    ..
                },
                Entry::Link {
                    symlink_target: other_symlink_target,
                    ..
                },
            ) => {
                if this_symlink_target != other_symlink_target {
                    compatible = false;
                }
            }
            (
                Entry::TreeReference {
                    reference_revision: this_reference_revision,
                    ..
                },
                Entry::TreeReference {
                    reference_revision: other_reference_revision,
                    ..
                },
            ) => {
                if this_reference_revision != other_reference_revision {
                    compatible = false;
                }
            }
            _ => {}
        }
        compatible
    }
}

pub enum EntryChange {
    Unchanged,
    Added,
    Removed,
    Renamed,
    Modified,
    ModifiedAndRenamed,
}

impl ToString for EntryChange {
    fn to_string(&self) -> String {
        match self {
            EntryChange::Unchanged => "unchanged".to_string(),
            EntryChange::Added => "added".to_string(),
            EntryChange::Removed => "removed".to_string(),
            EntryChange::Renamed => "renamed".to_string(),
            EntryChange::Modified => "modified".to_string(),
            EntryChange::ModifiedAndRenamed => "modified and renamed".to_string(),
        }
    }
}

/// Describe the change between old_entry and this.
///
/// This smells of being an InterInventoryEntry situation, but as its
/// the first one, we're making it a static method for now.
///
/// An entry with a different parent, or different name is considered
/// to be renamed. Reparenting is an internal detail.
/// Note that renaming the parent does not trigger a rename for the
/// child entry itself.
pub fn describe_change(old_entry: Option<&Entry>, new_entry: Option<&Entry>) -> EntryChange {
    if old_entry == new_entry {
        return EntryChange::Unchanged;
    } else if old_entry.is_none() {
        return EntryChange::Added;
    } else if new_entry.is_none() {
        return EntryChange::Removed;
    }
    let old_entry = old_entry.unwrap();
    let new_entry = new_entry.unwrap();
    if old_entry.kind() != new_entry.kind() {
        return EntryChange::Modified;
    }
    let (text_modified, meta_modified) = detect_changes(old_entry, new_entry);
    let modified = text_modified || meta_modified;
    // TODO 20060511 (mbp, rbc) factor out 'detect_rename' here.
    let renamed = if old_entry.parent_id() != new_entry.parent_id() {
        true
    } else {
        old_entry.name() != new_entry.name()
    };
    if renamed && !modified {
        return EntryChange::Renamed;
    }
    if modified && !renamed {
        return EntryChange::Modified;
    }
    if modified && renamed {
        return EntryChange::ModifiedAndRenamed;
    }
    EntryChange::Unchanged
}

pub fn detect_changes(old_entry: &Entry, new_entry: &Entry) -> (bool, bool) {
    match new_entry {
        Entry::Link {
            symlink_target: new_symlink_target,
            ..
        } => match old_entry {
            Entry::Link {
                symlink_target: old_symlink_target,
                ..
            } => (old_symlink_target != new_symlink_target, false),
            _ => panic!("old_entry is not a link"),
        },
        Entry::File {
            text_sha1: new_text_sha1,
            executable: new_executable,
            ..
        } => match old_entry {
            Entry::File {
                text_sha1: old_text_sha1,
                executable: old_executable,
                ..
            } => {
                let text_modified = old_text_sha1 != new_text_sha1;
                let meta_modified = old_executable != new_executable;
                (text_modified, meta_modified)
            }
            _ => panic!("old_entry is not a file"),
        },
        Entry::Directory { .. } | Entry::TreeReference { .. } => (false, false),
    }
}

pub fn is_valid_name(name: &str) -> bool {
    !(name.contains('/') || name == "." || name == "..")
}

// Normalize name
pub fn ensure_normalized_name(name: &std::path::Path) -> Result<std::path::PathBuf, String> {
    let (norm_name, can_access) = breezy_osutils::path::normalized_filename(name)
        .ok_or_else(|| format!("name '{}' is not normalized", name.display()))?;

    if norm_name != name {
        if can_access {
            return Ok(norm_name);
        } else {
            return Err(format!(
                "name '{}' is not normalized and cannot be accessed",
                name.display()
            ));
        }
    }

    Ok(name.to_path_buf())
}
