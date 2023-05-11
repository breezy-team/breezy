use breezy_osutils::Kind;
use std::collections::HashMap;

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

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Entry {
    Directory {
        file_id: crate::FileId,
        revision: Option<crate::RevisionId>,
        parent_id: crate::FileId,
        name: String,
        children: Option<HashMap<String, Vec<Entry>>>,
    },
    File {
        file_id: crate::FileId,
        revision: Option<crate::RevisionId>,
        parent_id: crate::FileId,
        name: String,
        text_sha1: Option<Vec<u8>>,
        text_size: Option<u64>,
        text_id: Option<Vec<u8>>,
        executable: bool,
    },
    Link {
        file_id: crate::FileId,
        name: String,
        parent_id: crate::FileId,
        symlink_target: Option<String>,
        revision: Option<crate::RevisionId>,
    },
    TreeReference {
        file_id: crate::FileId,
        revision: Option<crate::RevisionId>,
        reference_revision: Option<crate::RevisionId>,
        name: String,
        parent_id: crate::FileId,
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
        file_id: crate::FileId,
        revision: Option<crate::RevisionId>,
        parent_id: crate::FileId,
        name: String,
    ) -> Self {
        Self::Directory {
            file_id,
            revision,
            parent_id,
            name,
            children: Some(HashMap::new()),
        }
    }

    pub fn file(file_id: crate::FileId, name: String, parent_id: crate::FileId) -> Self {
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

    pub fn tree_reference(file_id: crate::FileId, name: String, parent_id: crate::FileId) -> Self {
        Entry::TreeReference {
            file_id,
            revision: None,
            reference_revision: None,
            name,
            parent_id,
        }
    }

    pub fn link(file_id: crate::FileId, name: String, parent_id: crate::FileId) -> Self {
        Entry::Link {
            file_id,
            name,
            parent_id,
            symlink_target: None,
            revision: None,
        }
    }
}
