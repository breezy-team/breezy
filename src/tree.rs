use bazaar::RevisionId;

pub trait Tree {
    /// Whether this tree supports rename tracking.
    ///
    /// This defaults to True, but some implementations may want to override
    /// it.
    fn supports_rename_tracking(&self) -> bool;
}

pub trait MutableTree {}

pub trait WorkingTree {
    fn abspath(&self, path: &str) -> std::path::PathBuf;

    fn last_revision(&self) -> RevisionId;
}
