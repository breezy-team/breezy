use bazaar::RevisionId;

pub trait Tree {
    /// Whether this tree supports rename tracking.
    ///
    /// This defaults to True, but some implementations may want to override
    /// it.
    fn supports_rename_tracking(&self) -> bool;
}

pub trait MutableTree: Tree {}

pub trait RevisionTree: Tree {
    fn get_revision_id(&self) -> RevisionId;
}

pub trait WorkingTree: MutableTree {
    fn abspath(&self, path: &str) -> std::path::PathBuf;

    fn last_revision(&self) -> RevisionId;
}
