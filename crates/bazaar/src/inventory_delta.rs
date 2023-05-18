//! Inventory delta serialisation.
//!
//! See doc/developers/inventory.txt for the description of the format.
//!
//! In this module the interesting classes are:
//!  - InventoryDeltaSerializer - object to read/write inventory deltas.

use crate::inventory::Entry;
use crate::{FileId, RevisionId, NULL_REVISION};
use std::collections::HashSet;

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct InventoryDeltaEntry {
    pub old_path: Option<String>,
    pub new_path: Option<String>,
    pub file_id: FileId,
    pub new_entry: Option<Entry>,
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct InventoryDelta(Vec<InventoryDeltaEntry>);

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
