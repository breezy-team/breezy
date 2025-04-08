use crate::inventory_delta::{InventoryDelta, InventoryDeltaEntry, InventoryDeltaInconsistency};
use crate::{FileId, RevisionId};
use breezy_osutils::Kind;
use std::collections::HashMap;
use std::collections::HashSet;
use std::collections::VecDeque;
use std::hash::Hash;

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

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Entry {
    Root {
        file_id: FileId,
        revision: Option<RevisionId>,
    },
    Directory {
        file_id: FileId,
        revision: Option<RevisionId>,
        parent_id: FileId,
        name: String,
    },
    File {
        file_id: FileId,
        revision: Option<RevisionId>,
        parent_id: FileId,
        name: String,
        text_sha1: Option<Vec<u8>>,
        text_size: Option<u64>,
        text_id: Option<Vec<u8>>,
        executable: bool,
    },
    Link {
        file_id: FileId,
        name: String,
        parent_id: FileId,
        symlink_target: Option<String>,
        revision: Option<RevisionId>,
    },
    TreeReference {
        file_id: FileId,
        revision: Option<RevisionId>,
        reference_revision: Option<RevisionId>,
        name: String,
        parent_id: FileId,
    },
}

#[derive(Debug)]
pub enum Error {
    InvalidEntryName(String),
    DuplicateFileId(FileId, String),
    ParentNotDirectory(String, FileId),
    FileIdCycle(FileId, String, String),
    NoSuchId(FileId),
    ParentMissing(FileId),
    PathAlreadyVersioned(String, String),
    ParentNotVersioned(String),
    InvalidNormalization(std::path::PathBuf, String),
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
            Entry::Root { .. } => false,
        }
    }

    pub fn kind(&self) -> Kind {
        match self {
            Entry::Directory { .. } => Kind::Directory,
            Entry::File { .. } => Kind::File,
            Entry::Link { .. } => Kind::Symlink,
            Entry::TreeReference { .. } => Kind::TreeReference,
            Entry::Root { .. } => Kind::Directory,
        }
    }

    pub fn directory(
        file_id: FileId,
        name: String,
        parent_id: FileId,
        revision: Option<RevisionId>,
    ) -> Self {
        Self::Directory {
            file_id,
            revision,
            parent_id,
            name,
        }
    }

    pub fn root(file_id: FileId, revision: Option<RevisionId>) -> Self {
        Entry::Root { file_id, revision }
    }

    pub fn file(
        file_id: FileId,
        name: String,
        parent_id: FileId,
        revision: Option<RevisionId>,
        text_sha1: Option<Vec<u8>>,
        text_size: Option<u64>,
        executable: Option<bool>,
        text_id: Option<Vec<u8>>,
    ) -> Self {
        let executable = executable.unwrap_or(false);
        Entry::File {
            file_id,
            name,
            parent_id,
            revision,
            text_sha1,
            text_size,
            text_id,
            executable,
        }
    }

    pub fn tree_reference(
        file_id: FileId,
        name: String,
        parent_id: FileId,
        revision: Option<RevisionId>,
        reference_revision: Option<RevisionId>,
    ) -> Self {
        Entry::TreeReference {
            file_id,
            revision,
            reference_revision,
            name,
            parent_id,
        }
    }

    pub fn link(
        file_id: FileId,
        name: String,
        parent_id: FileId,
        revision: Option<RevisionId>,
        symlink_target: Option<String>,
    ) -> Self {
        Entry::Link {
            file_id,
            name,
            parent_id,
            symlink_target,
            revision,
        }
    }

    pub fn file_id(&self) -> &FileId {
        match self {
            Entry::Directory { file_id, .. } => file_id,
            Entry::File { file_id, .. } => file_id,
            Entry::Link { file_id, .. } => file_id,
            Entry::TreeReference { file_id, .. } => file_id,
            Entry::Root { file_id, .. } => file_id,
        }
    }

    pub fn set_file_id(&mut self, new_file_id: FileId) {
        match self {
            Entry::Directory { file_id, .. } => {
                *file_id = new_file_id;
            }
            Entry::File { file_id, .. } => {
                *file_id = new_file_id;
            }
            Entry::Link { file_id, .. } => {
                *file_id = new_file_id;
            }
            Entry::TreeReference { file_id, .. } => {
                *file_id = new_file_id;
            }
            Entry::Root { file_id, .. } => {
                *file_id = new_file_id;
            }
        }
    }

    pub fn parent_id(&self) -> Option<&FileId> {
        match self {
            Entry::Directory { parent_id, .. } => Some(parent_id),
            Entry::File { parent_id, .. } => Some(parent_id),
            Entry::Link { parent_id, .. } => Some(parent_id),
            Entry::TreeReference { parent_id, .. } => Some(parent_id),
            Entry::Root { .. } => None,
        }
    }

    pub fn set_parent_id(&mut self, new_parent_id: Option<FileId>) {
        match self {
            Entry::Root { .. } => {
                if new_parent_id.is_some() {
                    panic!("Cannot set parent_id on root");
                }
            }
            Entry::Directory { parent_id, .. } => {
                *parent_id = new_parent_id.unwrap();
            }
            Entry::File { parent_id, .. } => {
                *parent_id = new_parent_id.unwrap();
            }
            Entry::Link { parent_id, .. } => {
                *parent_id = new_parent_id.unwrap();
            }
            Entry::TreeReference { parent_id, .. } => {
                *parent_id = new_parent_id.unwrap();
            }
        }
    }

    pub fn name(&self) -> &str {
        match self {
            Entry::Directory { name, .. } => name,
            Entry::File { name, .. } => name,
            Entry::Link { name, .. } => name,
            Entry::TreeReference { name, .. } => name,
            Entry::Root { .. } => "",
        }
    }

    pub fn set_name(&mut self, new_name: String) {
        match self {
            Entry::Directory { name, .. } => {
                *name = new_name;
            }
            Entry::File { name, .. } => {
                *name = new_name;
            }
            Entry::Link { name, .. } => {
                *name = new_name;
            }
            Entry::TreeReference { name, .. } => {
                *name = new_name;
            }
            Entry::Root { .. } => {
                panic!("Cannot set name on root");
            }
        }
    }

    pub fn revision(&self) -> Option<&RevisionId> {
        match self {
            Entry::Directory { revision, .. } => revision.as_ref(),
            Entry::File { revision, .. } => revision.as_ref(),
            Entry::Link { revision, .. } => revision.as_ref(),
            Entry::TreeReference { revision, .. } => revision.as_ref(),
            Entry::Root { revision, .. } => revision.as_ref(),
        }
    }

    pub fn symlink_target(&self) -> Option<&str> {
        match self {
            Entry::Directory { .. } => None,
            Entry::File { .. } => None,
            Entry::Link { symlink_target, .. } => symlink_target.as_ref().map(|s| s.as_str()),
            Entry::TreeReference { .. } => None,
            Entry::Root { .. } => None,
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
        Entry::Directory { .. } | Entry::Root { .. } | Entry::TreeReference { .. } => {
            (false, false)
        }
    }
}

pub fn is_valid_name(name: &str) -> bool {
    !(name.contains('/') || name == "." || name == "..")
}

pub fn find_interesting_parents<'a>(
    inv: &'a MutableInventory,
    file_ids: &HashSet<&'a FileId>,
) -> HashSet<&'a FileId> {
    let mut parents: HashSet<&'a FileId> = HashSet::new();
    let mut todo = file_ids.iter().cloned().collect::<Vec<_>>();
    while let Some(file_id) = todo.pop() {
        let ie = inv.get_entry(file_id).unwrap();
        if let Some(parent_id) = ie.parent_id() {
            if !parents.contains(parent_id) {
                todo.push(parent_id);
                parents.insert(parent_id);
            }
        }
    }
    parents
}

pub trait Inventory {
    fn has_filename(&self, filename: &str) -> bool;

    fn iter_all_ids<'a>(&'a self) -> Box<dyn Iterator<Item = &'a FileId> + 'a>;

    fn id2path(&self, file_id: &FileId) -> Result<String, Error>;

    fn get_entry(&self, id: &FileId) -> Option<&Entry>;

    fn has_id(&self, id: &FileId) -> bool;
}

#[derive(Clone)]
pub struct MutableInventory {
    by_id: HashMap<FileId, Entry>,
    root_id: Option<FileId>,
    pub revision_id: Option<RevisionId>,
    children: HashMap<FileId, HashMap<String, FileId>>,
}

impl Inventory for MutableInventory {
    fn has_filename(&self, filename: &str) -> bool {
        self.path2id(filename).is_some()
    }

    fn iter_all_ids<'a>(&'a self) -> Box<dyn Iterator<Item = &'a FileId> + 'a> {
        Box::new(self.by_id.keys())
    }

    fn id2path(&self, file_id: &FileId) -> Result<String, Error> {
        let mut segments = self
            .iter_file_id_parents(file_id)?
            .map(|p| p.name())
            .collect::<Vec<_>>();
        segments.pop();
        segments.reverse();
        Ok(segments.join("/"))
    }

    fn get_entry(&self, id: &FileId) -> Option<&Entry> {
        self.by_id.get(id)
    }
    fn has_id(&self, id: &FileId) -> bool {
        self.by_id.contains_key(id)
    }
}

impl MutableInventory {
    pub fn new() -> MutableInventory {
        Self {
            by_id: HashMap::new(),
            root_id: None,
            revision_id: None,
            children: HashMap::new(),
        }
    }

    pub fn get_children(&self, file_id: &FileId) -> Option<HashMap<&str, &Entry>> {
        Some(
            self.children
                .get(file_id)?
                .iter()
                .map(|(k, v)| (k.as_str(), self.get_entry(v).expect("child not found")))
                .collect(),
        )
    }

    pub fn change_root_id(&mut self, new_root_id: FileId) {
        let mut children = self
            .children
            .remove(self.root_id.as_ref().unwrap())
            .unwrap();
        self.by_id.remove(self.root_id.as_ref().unwrap());
        self.root_id = Some(new_root_id.clone());
        self.by_id.insert(
            new_root_id.clone(),
            Entry::Root {
                file_id: new_root_id.clone(),
                revision: None,
            },
        );
        for (_n, child) in children.iter_mut() {
            self.by_id
                .get_mut(child)
                .unwrap()
                .set_parent_id(Some(new_root_id.clone()));
        }

        self.children.insert(new_root_id, children);
    }

    pub fn iter_sorted_children(
        &self,
        file_id: &FileId,
    ) -> Option<impl DoubleEndedIterator<Item = (&str, &Entry)>> {
        let children = self.get_children(file_id)?;
        // Sort the children by name and then return them
        let mut children = children.into_iter().collect::<Vec<_>>();
        children.sort_by(|(a, _), (b, _)| a.cmp(b));
        Some(children.into_iter())
    }

    pub fn entries(&self) -> Vec<(String, &Entry)> {
        let mut accum = Vec::new();

        let mut todo = Vec::new();
        if let Some(ref root_id) = self.root_id {
            todo.push((root_id, "".to_string()));
        }

        while !todo.is_empty() {
            if let Some((dir_id, dir_path)) = todo.pop() {
                for (name, ie) in self.iter_sorted_children(dir_id).unwrap() {
                    let child_path = if dir_path.is_empty() {
                        name.to_string()
                    } else {
                        format!("{}/{}", dir_path, name)
                    };
                    accum.push((child_path.clone(), ie));
                    if ie.kind() == Kind::Directory {
                        todo.push(((ie.file_id()), child_path));
                    }
                }
            }
        }

        accum
    }

    pub fn rename_id(&mut self, old_file_id: &FileId, new_file_id: &FileId) -> Result<(), Error> {
        if old_file_id == new_file_id {
            return Ok(());
        }
        if self.by_id.contains_key(new_file_id) {
            return Err(Error::DuplicateFileId(
                new_file_id.clone(),
                self.id2path(new_file_id).unwrap(),
            ));
        }
        let mut ie = self
            .by_id
            .remove(old_file_id)
            .ok_or_else(|| Error::NoSuchId(old_file_id.clone()))?;
        if let Some(children) = self.children.remove(old_file_id) {
            for child_id in children.values() {
                let child = self.by_id.get_mut(child_id).unwrap();
                assert_eq!(child.parent_id(), Some(old_file_id));
                child.set_parent_id(Some(new_file_id.clone()));
            }
            self.children.insert(new_file_id.clone(), children);
        }
        ie.set_file_id(new_file_id.clone());
        self.by_id.insert(new_file_id.clone(), ie);
        if self.root_id == Some(old_file_id.clone()) {
            self.root_id = Some(new_file_id.clone());
        }
        Ok(())
    }

    pub fn path2id(&self, relpath: &str) -> Option<&FileId> {
        if let Some(ie) = self.get_entry_by_path(relpath) {
            Some(ie.file_id())
        } else {
            None
        }
    }

    pub fn path2id_segments(&self, names: &[&str]) -> Option<&FileId> {
        if let Some(ie) = self.get_entry_by_path_segments(names) {
            Some(ie.file_id())
        } else {
            None
        }
    }

    /// Get an inventory view filtered against a set of file-ids.
    ///
    /// Children of directories and parents are included.
    ///
    /// The result may or may not reference the underlying inventory
    /// so it should be treated as immutable.
    pub fn filter(&self, specific_fileids: &HashSet<&FileId>) -> Result<Self, Error> {
        let mut interesting_parents = HashSet::new();
        for file_id in specific_fileids {
            match self.get_idpath(file_id) {
                Ok(parents) => {
                    interesting_parents.extend(parents);
                }
                Err(Error::NoSuchId(_)) => {}
                Err(e) => {
                    return Err(e);
                }
            }
        }

        let mut entries = self.iter_entries(None);
        let root = entries.next();
        let mut other = Self::new();
        if root.is_none() {
            return Ok(other);
        }

        other.set_root(root.unwrap().1.clone());
        let mut directories_to_expand = HashSet::new();
        for (_path, entry) in entries {
            let file_id = entry.file_id();
            if specific_fileids.contains(file_id)
                || (entry.parent_id().is_some()
                    && directories_to_expand.contains(entry.parent_id().unwrap()))
            {
                if entry.kind() == Kind::Directory {
                    directories_to_expand.insert(file_id);
                }
            } else if !interesting_parents.contains(file_id) {
                continue;
            }
            other.add(entry.clone()).unwrap();
        }
        Ok(other)
    }

    /// Return a list of file_ids for the path to an entry.
    ///
    /// The list contains one element for each directory followed by
    /// the id of the file itself.  So the length of the returned list
    /// is equal to the depth of the file in the tree, counting the
    /// root directory as depth 1.
    pub fn get_idpath<'a>(&'a self, file_id: &'a FileId) -> Result<Vec<&'a FileId>, Error> {
        Ok(self
            .iter_file_id_parents(file_id)?
            .map(|e| e.file_id())
            .collect())
    }

    pub fn get_entry_by_path_partial(
        &self,
        relpath: &str,
    ) -> Option<(&Entry, Vec<String>, Vec<String>)> {
        let names = breezy_osutils::path::splitpath(relpath).unwrap();
        self.get_entry_by_path_segments_partial(&names)
    }

    pub fn get_entry_by_path_segments_partial(
        &self,
        names: &[&str],
    ) -> Option<(&Entry, Vec<String>, Vec<String>)> {
        self.root_id.as_ref()?;

        let mut parent = self.by_id.get(self.root_id.as_ref().unwrap()).unwrap();

        for (i, f) in names.iter().enumerate() {
            if let Some(cie) = self.get_child(parent.file_id(), f) {
                parent = cie;
                if cie.kind() == Kind::TreeReference {
                    let (before, after) = names.split_at(i + 1);
                    return Some((
                        cie,
                        before.iter().map(|s| s.to_string()).collect(),
                        after.iter().map(|s| s.to_string()).collect(),
                    ));
                }
            } else {
                return None;
            }
        }

        Some((
            parent,
            names.iter().map(|s| s.to_string()).collect(),
            Vec::new(),
        ))
    }

    pub fn get_entry_by_path(&self, relpath: &str) -> Option<&Entry> {
        self.get_entry_by_path_segments(
            breezy_osutils::path::splitpath(relpath).unwrap().as_slice(),
        )
    }

    pub fn get_entry_by_path_segments(&self, names: &[&str]) -> Option<&Entry> {
        self.root_id.as_ref()?;

        let mut parent = self.by_id.get(self.root_id.as_ref().unwrap()).unwrap();

        for f in names {
            if let Some(cie) = self.get_child(parent.file_id(), f) {
                parent = cie;
            } else {
                return None;
            }
        }

        Some(parent)
    }

    /// Return (path, entry) pairs, in order by name.
    ///
    /// Args:
    ///   from_dir: if None, start from the root,
    ///     otherwise start from this directory (either file-id or entry)
    pub fn iter_entries<'a>(
        &'a self,
        from_dir: Option<&FileId>,
    ) -> impl Iterator<Item = (String, &'a Entry)> {
        let mut stack = VecDeque::new();
        let mut from_dir = if from_dir.is_none() {
            self.root_id.clone()
        } else {
            from_dir.cloned()
        };
        if let Some(from_dir) = from_dir.as_ref() {
            let children = self
                .iter_sorted_children(from_dir)
                .unwrap()
                .collect::<VecDeque<_>>();
            stack.push_back((String::new(), children));
        }

        std::iter::from_fn(move || -> Option<(String, &Entry)> {
            if let Some(from_dir) = from_dir.take() {
                let entry = self.by_id.get(&from_dir)?;
                return Some((String::new(), entry));
            }
            loop {
                if let Some((base, children)) = stack.back_mut() {
                    if let Some((name, ie)) = children.pop_front() {
                        let path = if base.is_empty() {
                            name.to_string()
                        } else {
                            format!("{}/{}", base, name)
                        };
                        if ie.kind() == Kind::Directory {
                            let children = self
                                .iter_sorted_children(ie.file_id())
                                .unwrap()
                                .collect::<VecDeque<_>>();
                            stack.push_back((path.clone(), children));
                        }
                        return Some((path, ie));
                    } else {
                        stack.pop_back();
                    }
                } else {
                    return None;
                }
            }
        })
    }

    /// Iterate over the entries in a directory first order.
    ///
    /// This returns all entries for a directory before returning
    /// the entries for children of a directory. This is not
    /// lexicographically sorted order, and is a hybrid between
    /// depth-first and breadth-first.
    ///
    /// This yields (path, entry) pairs
    pub fn iter_entries_by_dir<'a>(
        &'a self,
        from_dir: Option<&'a FileId>,
        specific_file_ids: Option<&'a HashSet<&FileId>>,
    ) -> impl Iterator<Item = (String, &'a Entry)> + 'a {
        let parents = specific_file_ids
            .map(|specific_file_ids| find_interesting_parents(self, specific_file_ids));

        let mut stack: Vec<(String, &FileId)> = vec![];

        let from_dir = if from_dir.is_none() {
            self.root_id.as_ref()
        } else {
            from_dir
        };
        let mut children = VecDeque::new();
        if let Some(from_dir) = from_dir {
            stack.push(("".to_string(), from_dir));
            children.extend(
                self.iter_sorted_children(from_dir)
                    .unwrap()
                    .map(|(p, ie)| (p.to_string(), ie)),
            );
        }

        std::iter::from_fn(move || -> Option<(String, &'a Entry)> {
            loop {
                if let Some(e) = children.pop_front() {
                    return Some(e);
                }

                if let Some((cur_relpath, cur_dir)) = stack.pop() {
                    let mut child_dirs = Vec::new();
                    for (child_name, child_ie) in self.iter_sorted_children(cur_dir).unwrap() {
                        let child_relpath = cur_relpath.to_string() + child_name;

                        if specific_file_ids.is_none()
                            || specific_file_ids.unwrap().contains(child_ie.file_id())
                        {
                            children.push_back((child_relpath.clone(), child_ie));
                        }

                        if child_ie.kind() == Kind::Directory
                            && (parents.is_none()
                                || parents.as_ref().unwrap().contains(child_ie.file_id()))
                        {
                            child_dirs.push((child_relpath + "/", child_ie.file_id()))
                        }
                    }
                    stack.extend(child_dirs.into_iter().rev());
                } else {
                    return None;
                }
            }
        })
    }

    /// Apply a delta to this inventory.
    ///
    /// See the inventory developers documentation for the theory behind
    /// inventory deltas.
    ///
    /// If delta application fails the inventory is left in an indeterminate
    /// state and must not be used.
    ///
    /// # Arguments
    ///  * `delta`: A list of changes to apply. After all the changes are
    ///      applied the final inventory must be internally consistent, but it
    ///      is ok to supply changes which, if only half-applied would have an
    ///      invalid result - such as supplying two changes which rename two
    ///      files, 'A' and 'B' with each other : [('A', 'B', b'A-id', a_entry),
    ///      ('B', 'A', b'B-id', b_entry)].
    ///
    ///      Each change is a tuple, of the form (old_path, new_path, file_id,
    ///      new_entry).
    ///
    ///      When new_path is None, the change indicates the removal of an entry
    ///      from the inventory and new_entry will be ignored (using None is
    ///      appropriate). If new_path is not None, then new_entry must be an
    ///      InventoryEntry instance, which will be incorporated into the
    ///      inventory (and replace any existing entry with the same file id).
    ///
    ///      When old_path is None, the change indicates the addition of
    ///      a new entry to the inventory.
    ///
    ///      When neither new_path nor old_path are None, the change is a
    ///      modification to an entry, such as a rename, reparent, kind change
    ///      etc.
    ///
    ///      The children attribute of new_entry is ignored. This is because
    ///      this method preserves children automatically across alterations to
    ///      the parent of the children, and cases where the parent id of a
    ///      child is changing require the child to be passed in as a separate
    ///      change regardless. E.g. in the recursive deletion of a directory -
    ///      the directory's children must be included in the delta, or the
    ///      final inventory will be invalid.
    ///
    ///      Note that a file_id must only appear once within a given delta.
    ///      An AssertionError is raised otherwise.
    pub fn apply_delta(
        &mut self,
        delta: &InventoryDelta,
    ) -> std::result::Result<(), InventoryDeltaInconsistency> {
        // Check that the delta is legal. It would be nice if this could be
        // done within the loops below but it's safer to validate the delta
        // before starting to mutate the inventory, as there isn't a rollback
        // facility.
        delta.check()?;

        let mut children = HashMap::new();
        // Remove all affected items which were in the original inventory,
        // starting with the longest paths, thus ensuring parents are examined
        // after their children, which means that everything we examine has no
        // modified children remaining by the time we examine it.
        let mut old = delta
            .iter()
            .filter_map(|d| {
                d.old_path
                    .as_ref()
                    .map(|old_path| (old_path, d.file_id.clone()))
            })
            .collect::<Vec<_>>();
        old.sort();
        old.reverse();
        for (old_path, file_id) in old {
            if &self.id2path(&file_id).unwrap() != old_path {
                return Err(InventoryDeltaInconsistency::PathMismatch(
                    file_id.clone(),
                    old_path.clone(),
                    self.id2path(&file_id).unwrap(),
                ));
            }
            // Remove file_id and the unaltered children. If file_id is not being deleted it will
            // be reinserted later.
            let ie = self.by_id.remove(&file_id).unwrap();
            if let Some(parent_id) = ie.parent_id() {
                self.children.get_mut(parent_id).unwrap().remove(ie.name());
            }
            // Preserve unaltered children of file_id for later reinsertion.
            if let Some(file_id_children) = self.children.remove(&file_id) {
                if !file_id_children.is_empty() {
                    children.insert(file_id, file_id_children);
                }
            }
        }

        // Insert all affected which should be in the new inventory, reattaching
        // their children if they had any. This is done from shortest path to
        // longest, ensuring that items which were modified and whose parents in
        // the resulting inventory were also modified, are inserted after their
        // parents.
        let mut new = delta
            .iter()
            .filter_map(|de| {
                de.new_path
                    .as_ref()
                    .map(|new_path| (new_path, &de.file_id, &de.new_entry))
            })
            .collect::<Vec<_>>();
        new.sort();
        for (new_path, _fid, new_entry) in new {
            let new_entry = new_entry.as_ref().unwrap();
            self.add(new_entry.clone()).map_err(|e| match e {
                Error::DuplicateFileId(fid, _path) => {
                    InventoryDeltaInconsistency::DuplicateFileId(new_path.clone(), fid)
                }
                Error::ParentNotDirectory(_path, fid) => {
                    InventoryDeltaInconsistency::ParentNotDirectory(new_path.clone(), fid)
                }
                Error::NoSuchId(fid) => InventoryDeltaInconsistency::NoSuchId(fid),
                Error::InvalidEntryName(name) => {
                    InventoryDeltaInconsistency::InvalidEntryName(name)
                }
                Error::FileIdCycle(fid, path, parent) => {
                    InventoryDeltaInconsistency::FileIdCycle(fid, path, parent)
                }
                Error::ParentMissing(fid) => InventoryDeltaInconsistency::ParentMissing(fid),
                Error::PathAlreadyVersioned(new_name, parent_path) => {
                    InventoryDeltaInconsistency::PathAlreadyVersioned(new_name, parent_path)
                }
                Error::ParentNotVersioned(_parent_path) => {
                    unreachable!();
                }
                Error::InvalidNormalization(_path, _msg) => unreachable!(),
            })?;
            if &self.id2path(new_entry.file_id()).unwrap() != new_path {
                return Err(InventoryDeltaInconsistency::PathMismatch(
                    new_entry.file_id().clone(),
                    new_path.clone(),
                    self.id2path(new_entry.file_id()).unwrap(),
                ));
            }
            if let Some(children) = children.remove(new_entry.file_id()) {
                self.children.insert(new_entry.file_id().clone(), children);
            }
        }
        if !children.is_empty() {
            // Get the parent id that was deleted
            let (parent_id, _children) = children.drain().next().unwrap();
            return Err(InventoryDeltaInconsistency::OrphanedChild(parent_id));
        }
        Ok(())
    }

    pub fn create_by_apply_delta(
        &self,
        inventory_delta: &InventoryDelta,
        new_revision_id: RevisionId,
    ) -> Result<Self, InventoryDeltaInconsistency> {
        let mut new_inv = self.clone();
        new_inv.apply_delta(inventory_delta)?;
        new_inv.revision_id = Some(new_revision_id);
        Ok(new_inv)
    }

    fn clear(&mut self) {
        self.root_id = None;
        self.by_id = HashMap::new();
        self.children = HashMap::new();
    }

    fn set_root(&mut self, mut ie: Entry) {
        ie.set_parent_id(None);
        self.clear();
        self.root_id = Some(ie.file_id().clone());
        self.by_id.insert(ie.file_id().clone(), ie.clone());
        self.children
            .insert(self.root_id.clone().unwrap(), HashMap::new());
    }

    pub fn len(&self) -> usize {
        self.by_id.len()
    }

    pub fn is_empty(&self) -> bool {
        self.by_id.is_empty()
    }

    pub fn get_file_kind(&self, id: &FileId) -> Option<Kind> {
        self.by_id.get(id).map(|e| e.kind())
    }

    /// Returns the entries leading up to the given file_id, including the entry
    fn iter_file_id_parents<'a>(
        &'a self,
        id: &'a FileId,
    ) -> Result<impl Iterator<Item = &'a Entry> + 'a, Error> {
        let mut entry: Option<&'a Entry> = self.by_id.get(id);
        if entry.is_none() {
            return Err(Error::NoSuchId(id.clone()));
        }
        Ok(std::iter::from_fn(move || {
            if let Some(e) = entry {
                if let Some(parent_id) = e.parent_id() {
                    entry = Some(self.by_id.get(parent_id).unwrap());
                } else {
                    entry = None;
                }
                Some(e)
            } else {
                None
            }
        }))
    }

    pub fn root(&self) -> Option<&Entry> {
        self.get_entry(self.root_id.as_ref()?)
    }

    pub fn is_root(&self, id: FileId) -> bool {
        self.root_id == Some(id)
    }

    /// Iterate over all entries.
    ///
    /// Unlike iter_entries(), just the entries are returned (not (path, ie))
    /// and the order of entries is undefined.
    pub fn iter_just_entries(&self) -> impl Iterator<Item = &Entry> + '_ {
        self.by_id.values()
    }

    pub fn get_child(&self, parent_id: &FileId, filename: &str) -> Option<&Entry> {
        if let Some(siblings) = self.children.get(parent_id) {
            if let Some(child_id) = siblings.get(filename) {
                self.by_id.get(child_id)
            } else {
                None
            }
        } else {
            None
        }
    }

    pub fn add(&mut self, ie: Entry) -> Result<(), Error> {
        if self.by_id.contains_key(ie.file_id()) {
            return Err(Error::DuplicateFileId(
                ie.file_id().clone(),
                self.id2path(ie.file_id()).unwrap(),
            ));
        }
        if let Some(parent_id) = ie.parent_id() {
            let parent = self
                .by_id
                .get(parent_id)
                .ok_or_else(|| Error::ParentMissing(parent_id.clone()))?;
            match parent {
                Entry::Directory { .. } | Entry::Root { .. } => {}
                _ => {
                    return Err(Error::ParentNotDirectory(
                        self.id2path(parent_id).unwrap(),
                        ie.file_id().clone(),
                    ));
                }
            }
            let siblings = self.children.get_mut(parent.file_id()).unwrap();
            match siblings.entry(ie.name().to_string()) {
                std::collections::hash_map::Entry::Vacant(entry) => {
                    entry.insert(ie.file_id().clone());
                }
                std::collections::hash_map::Entry::Occupied(entry) => {
                    let fid = entry.get().clone();
                    return Err(Error::PathAlreadyVersioned(
                        self.id2path(&fid).unwrap(),
                        self.id2path(parent.file_id()).unwrap(),
                    ));
                }
            }
        } else {
            assert!(matches!(ie, Entry::Root { .. }));
            self.root_id = Some(ie.file_id().clone());
        }

        match ie {
            Entry::Directory { ref file_id, .. } | Entry::Root { ref file_id, .. } => {
                self.children.insert(file_id.clone(), HashMap::new());
            }
            _ => {}
        }
        self.by_id.insert(ie.file_id().clone(), ie);
        Ok(())
    }

    pub fn add_path(
        &mut self,
        relpath: &str,
        kind: Kind,
        file_id: Option<FileId>,
        revision: Option<RevisionId>,
        text_sha1: Option<Vec<u8>>,
        text_size: Option<u64>,
        executable: Option<bool>,
        text_id: Option<Vec<u8>>,
        symlink_target: Option<String>,
        reference_revision: Option<RevisionId>,
    ) -> Result<FileId, Error> {
        let parts = breezy_osutils::path::splitpath(relpath).unwrap();

        if parts.is_empty() {
            self.clear();
            let file_id = Some(file_id.unwrap_or_else(FileId::generate_root_id));
            let root = Entry::root(file_id.as_ref().unwrap().clone(), revision);
            self.add(root)?;
            Ok(self.root_id.as_ref().unwrap().clone())
        } else {
            let (basename, parent_path) = parts.split_last().unwrap();
            let parent_id = self.path2id_segments(parent_path);
            if parent_id.is_none() {
                return Err(Error::ParentNotVersioned(parent_path.join("/")));
            }
            let ie = make_entry(
                kind,
                basename.to_string(),
                parent_id.cloned(),
                file_id,
                revision,
                text_sha1,
                text_size,
                executable,
                text_id,
                symlink_target,
                reference_revision,
            )?;
            let file_id = ie.file_id().clone();
            self.add(ie)?;
            Ok(file_id)
        }
    }

    pub fn delete(&mut self, file_id: &FileId) -> Result<(), Error> {
        let ie = self
            .by_id
            .remove(file_id)
            .ok_or_else(|| Error::NoSuchId(file_id.clone()))?;
        if let Some(parent_id) = ie.parent_id() {
            let siblings = self.children.get_mut(parent_id).unwrap();
            siblings.remove(ie.name());
        } else {
            assert_eq!(file_id, self.root_id.as_ref().unwrap());
            self.root_id = None;
        }
        Ok(())
    }

    pub fn make_delta(&self, old: &dyn Inventory) -> InventoryDelta {
        let old_ids = old.iter_all_ids().collect::<HashSet<_>>();
        let new_ids = self.iter_all_ids().collect::<HashSet<_>>();
        let adds = new_ids.difference(&old_ids).collect::<HashSet<_>>();
        let deletes = old_ids.difference(&new_ids).collect::<HashSet<_>>();
        let common = if adds.is_empty() && deletes.is_empty() {
            new_ids.clone()
        } else {
            old_ids
                .intersection(&new_ids)
                .cloned()
                .collect::<HashSet<_>>()
        };
        let mut delta = Vec::new();
        for file_id in deletes {
            delta.push(InventoryDeltaEntry {
                old_path: Some(old.id2path(file_id).unwrap()),
                new_path: None,
                file_id: (*file_id).clone(),
                new_entry: None,
            });
        }
        for file_id in adds {
            delta.push(InventoryDeltaEntry {
                old_path: None,
                new_path: Some(self.id2path(file_id).unwrap()),
                file_id: (*file_id).clone(),
                new_entry: self.get_entry(file_id).cloned(),
            });
        }
        for file_id in common {
            let new_ie = self.get_entry(file_id);
            let old_ie = old.get_entry(file_id);

            // If xml_serializer returns the cached InventoryEntries (rather
            // than always doing .copy()), inlining the 'is' check saves 2.7M
            // calls to __eq__.  Under lsprof this saves 20s => 6s.
            // It is a minor improvement without lsprof.
            if old_ie == new_ie {
                continue;
            }
            delta.push(InventoryDeltaEntry {
                old_path: Some(old.id2path(file_id).unwrap()),
                new_path: Some(self.id2path(file_id).unwrap()),
                file_id: file_id.clone(),
                new_entry: new_ie.cloned(),
            });
        }

        InventoryDelta(delta)
    }

    pub fn remove_recursive_id(&mut self, file_id: &FileId) -> Vec<Entry> {
        let start_ie = self.by_id.get(file_id).unwrap().clone();
        let mut to_find_delete = vec![start_ie];
        let mut to_delete = Vec::new();

        while let Some(ie) = to_find_delete.pop() {
            if ie.kind() == Kind::Directory {
                to_find_delete.extend(
                    self.get_children(ie.file_id())
                        .unwrap()
                        .values()
                        .cloned()
                        .cloned(),
                );
            }
            to_delete.push(ie);
        }
        let mut deleted = Vec::new();
        to_delete.reverse();
        for ie in to_delete {
            deleted.push(self.by_id.remove(ie.file_id()).unwrap());
            if ie.kind() == Kind::Directory {
                let children = self.children.remove(ie.file_id()).unwrap();
                assert!(children.is_empty());
            } else {
                assert!(!self.children.contains_key(ie.file_id()));
            }
            if let Some(parent_id) = ie.parent_id() {
                let siblings = self.children.get_mut(parent_id).unwrap();
                siblings.remove(ie.name());
            } else {
                self.root_id = None;
            }
        }

        deleted.reverse();
        deleted
    }

    pub fn rename(
        &mut self,
        file_id: &FileId,
        new_parent_id: &FileId,
        new_name: &str,
    ) -> Result<(), Error> {
        let new_name = std::path::PathBuf::from(new_name);
        let new_name = ensure_normalized_name(new_name.as_path())?;
        let new_name = new_name.to_str().unwrap();
        if !is_valid_name(new_name) {
            return Err(Error::InvalidEntryName(new_name.to_string()));
        }

        let new_siblings = self.children.get_mut(new_parent_id).unwrap();
        if new_siblings.contains_key(new_name) {
            return Err(Error::PathAlreadyVersioned(
                new_name.to_string(),
                self.id2path(new_parent_id).unwrap(),
            ));
        }

        let new_parent_idpath = self.get_idpath(new_parent_id).unwrap();
        if new_parent_idpath.contains(&file_id) {
            return Err(Error::FileIdCycle(
                file_id.clone(),
                self.id2path(file_id).unwrap(),
                self.id2path(new_parent_id).unwrap(),
            ));
        }

        let file_ie = self.by_id.get(file_id).unwrap();
        let old_parent = self.by_id.get(file_ie.parent_id().unwrap()).unwrap();
        let new_parent = self.by_id.get(new_parent_id).unwrap();

        // TODO: Don't leave things messed up if this fails
        self.children
            .get_mut(old_parent.file_id())
            .unwrap()
            .remove(file_ie.name());
        self.children
            .get_mut(new_parent.file_id())
            .unwrap()
            .insert(new_name.to_string(), file_id.clone());

        let file_ie = self.by_id.get_mut(file_id).unwrap();
        file_ie.set_name(new_name.to_string());
        file_ie.set_parent_id(Some(new_parent_id.clone()));
        Ok(())
    }
}

impl Default for MutableInventory {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Debug for MutableInventory {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        const MAX_LEN: usize = 2048;
        const CLOSING: &str = "...}";
        let mut contents = format!("{:?}", self.by_id);
        if contents.len() > MAX_LEN {
            contents = contents[0..MAX_LEN - CLOSING.len()].to_string() + CLOSING;
        }
        write!(
            f,
            "<Inventory object at {:p} with {} entries: {}>",
            self,
            self.by_id.len(),
            contents,
        )
    }
}

impl PartialEq for MutableInventory {
    fn eq(&self, other: &Self) -> bool {
        self.by_id == other.by_id
    }
}

impl Eq for MutableInventory {}

// Normalize name
pub fn ensure_normalized_name(name: &std::path::Path) -> Result<std::path::PathBuf, Error> {
    let (norm_name, can_access) =
        breezy_osutils::path::normalized_filename(name).ok_or_else(|| {
            Error::InvalidNormalization(name.to_path_buf(), "name is not normalized".to_string())
        })?;

    if norm_name != name {
        if can_access {
            return Ok(norm_name);
        } else {
            return Err(Error::InvalidNormalization(
                name.to_path_buf(),
                "name '{}' is not normalized and cannot be accessed".to_string(),
            ));
        }
    }

    Ok(name.to_path_buf())
}

pub fn make_entry(
    kind: Kind,
    name: String,
    parent_id: Option<FileId>,
    file_id: Option<FileId>,
    revision: Option<RevisionId>,
    text_sha1: Option<Vec<u8>>,
    text_size: Option<u64>,
    executable: Option<bool>,
    text_id: Option<Vec<u8>>,
    symlink_target: Option<String>,
    reference_revision: Option<RevisionId>,
) -> Result<Entry, Error> {
    let file_id = file_id.unwrap_or_else(|| FileId::generate(name.as_str()));
    if !is_valid_name(&name) {
        panic!("Invalid name: {}", name);
    }
    let name = ensure_normalized_name(std::path::Path::new(&name))?
        .to_str()
        .unwrap()
        .to_string();
    Ok(match kind {
        Kind::File => Entry::file(
            file_id,
            name,
            parent_id.unwrap(),
            revision,
            text_sha1,
            text_size,
            executable,
            text_id,
        ),
        Kind::Directory => {
            if let Some(parent_id) = parent_id {
                Entry::directory(file_id, name, parent_id, revision)
            } else {
                Entry::root(file_id, revision)
            }
        }
        Kind::Symlink => Entry::link(file_id, name, parent_id.unwrap(), revision, symlink_target),
        Kind::TreeReference => Entry::tree_reference(
            file_id,
            name,
            parent_id.unwrap(),
            revision,
            reference_revision,
        ),
    })
}
