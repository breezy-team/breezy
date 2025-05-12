use crate::tags::Tags;
use bazaar::RevisionId;

/// Trait representing a version control branch.
pub trait Branch {
    /// Returns the last revision ID in the branch.
    fn last_revision(&self) -> RevisionId;

    /// Returns the name of the branch.
    fn name(&self) -> String;

    /// Returns the tags associated with the branch.
    fn tags(&self) -> Box<dyn Tags>;
}
