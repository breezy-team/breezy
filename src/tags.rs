use bazaar::RevisionId;
use std::collections::HashMap;
use std::collections::HashSet;

/// Errors that can occur when working with tags.
#[derive(Debug)]
pub enum Error {
    /// The requested tag does not exist in the repository.
    NoSuchTag(String),
    /// An attempt was made to create a tag that already exists.
    TagAlreadyExists(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::NoSuchTag(tag) => write!(f, "No such tag: {}", tag),
            Error::TagAlreadyExists(tag) => write!(f, "Tag already exists: {}", tag),
        }
    }
}

impl std::error::Error for Error {}

/// A trait for managing tags in a version control repository.
///
/// Tags are named references to specific revisions in the repository's history.
/// This trait provides methods for querying and manipulating tags.
pub trait Tags {
    /// Retrieves a mapping of tag names to their associated revision IDs.
    ///
    /// # Returns
    ///
    /// A HashMap where keys are tag names and values are the corresponding revision IDs.
    fn get_tag_dict(&self) -> HashMap<String, RevisionId>;

    /// Retrieves a mapping of revision IDs to their associated tag names.
    ///
    /// This is the inverse of `get_tag_dict`, allowing lookup of all tags
    /// associated with a particular revision.
    ///
    /// # Returns
    ///
    /// A HashMap where keys are revision IDs and values are sets of tag names.
    fn get_reverse_tag_dict(&self) -> HashMap<RevisionId, HashSet<String>> {
        let mut reverse_tag_dict = HashMap::new();
        for (tag, rev_id) in self.get_tag_dict() {
            reverse_tag_dict
                .entry(rev_id)
                .or_insert_with(HashSet::new)
                .insert(tag);
        }
        reverse_tag_dict
    }

    /// Deletes a tag from the repository.
    ///
    /// # Arguments
    ///
    /// * `tag` - The name of the tag to delete.
    ///
    /// # Returns
    ///
    /// Returns `Ok(())` if the tag was successfully deleted, or an `Error` if
    /// the tag doesn't exist.
    fn delete_tag(&mut self, tag: &str) -> Result<(), Error>;
}
