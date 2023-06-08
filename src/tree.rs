use bazaar::RevisionId;

#[derive(Debug)]
pub enum Error {
    NotVersioned(String),
    Other(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Error::NotVersioned(path) => write!(f, "Not versioned: {}", path),
            Error::Other(msg) => write!(f, "{}", msg),
        }
    }
}

impl std::error::Error for Error {}

pub trait Tree {
    /// Whether this tree supports rename tracking.
    ///
    /// This defaults to True, but some implementations may want to override
    /// it.
    fn supports_rename_tracking(&self) -> bool;

    fn unlock(&mut self) -> Result<(), String>;
}

pub trait MutableTree: Tree {
    /// Version file_list, optionally recursing into directories.
    ///
    /// This is designed more towards DWIM for humans than API clarity.
    /// For the specific behaviour see the help for cmd_add().
    ///
    /// :param file_list: List of zero or more paths.  *NB: these are
    ///     interpreted relative to the process cwd, not relative to the
    ///     tree.*  (Add and most other tree methods use tree-relative
    ///     paths.)
    /// :param action: A reporter to be called with the working tree, parent_ie,
    ///     path and kind of the path being added. It may return a file_id if
    ///     a specific one should be used.
    /// :param save: Save the changes after completing the adds. If False
    ///     this provides dry-run functionality by doing the add and not saving
    ///     the changes.
    /// :return: A tuple - files_added, ignored_files. files_added is the count
    ///     of added files, and ignored_files is a dict mapping files that were
    ///     ignored to the rule that caused them to be ignored.
    fn smart_add(
        &mut self,
        file_list: Vec<&str>,
        recurse: Option<bool>,
        save: Option<bool>,
    ) -> (Vec<String>, Vec<String>);

    fn commit(&mut self, message: Option<&str>) -> RevisionId;

    /// Create a directory in the tree.
    fn mkdir(&mut self, path: &str) -> Result<(), Error>;

    /// Update the content of a file in the tree.
    ///
    /// Note that the file is written in-place rather than being
    /// written to a temporary location and renamed. As a consequence,
    /// readers can potentially see the file half-written.
    fn put_file_bytes_non_atomic(&mut self, path: &str, bytes: &[u8]) -> Result<(), Error>;

    /// Add paths to the set of versioned paths.
    ///
    /// Note that the command line normally calls smart_add instead,
    /// which can automatically recurse.
    ///
    /// This adds the files to the tree, so that they will be
    /// recorded by the next commit.
    ///
    /// Args:
    ///   files: List of paths to add, relative to the base of the tree.
    fn add(&mut self, paths: &[&str]) -> Result<(), Error>;

    /// Lock the working tree for write, and the branch for read.
    ///
    /// This is useful for operations which only need to mutate the working
    /// tree. Taking out branch write locks is a relatively expensive process
    /// and may fail if the branch is on read only media. So branch write locks
    /// should only be taken out when we are modifying branch data - such as in
    /// operations like commit, pull, uncommit and update.
    fn lock_tree_write(&mut self) -> Result<(), String>;
}

pub trait RevisionTree: Tree {
    fn get_revision_id(&self) -> RevisionId;
}

pub trait WorkingTree: MutableTree {
    fn abspath(&self, path: &str) -> std::path::PathBuf;

    fn last_revision(&self) -> RevisionId;
}
