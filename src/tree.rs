use bazaar::RevisionId;

/// Errors that can occur when working with version control trees.
#[derive(Debug)]
pub enum Error {
    /// A path is not under version control.
    NotVersioned(String),
    /// A generic error occurred.
    Other(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::NotVersioned(path) => write!(f, "Not versioned: {}", path),
            Error::Other(msg) => write!(f, "{}", msg),
        }
    }
}

impl std::error::Error for Error {}

/// A trait representing a version control tree.
///
/// A tree represents a snapshot of the working directory at a particular point
/// in time, including all files and directories under version control.
pub trait Tree {
    /// Whether this tree supports rename tracking.
    ///
    /// This defaults to True, but some implementations may want to override
    /// it.
    fn supports_rename_tracking(&self) -> bool;

    /// Unlocks the tree, allowing other processes to modify it.
    ///
    /// # Returns
    ///
    /// Returns `Ok(())` if the tree was successfully unlocked, or an error
    /// message if the unlock operation failed.
    fn unlock(&mut self) -> Result<(), String>;
}

/// A trait for trees that can be modified.
///
/// This trait extends `Tree` with methods for making changes to the working
/// directory, such as adding files, creating directories, and committing changes.
pub trait MutableTree: Tree {
    /// Versions a list of files, optionally recursing into directories.
    ///
    /// This method is designed for user convenience rather than API clarity.
    /// For specific behavior, see the help documentation.
    ///
    /// # Arguments
    ///
    /// * `file_list` - List of paths to add. These are interpreted relative to
    ///   the process's current working directory, not relative to the tree.
    /// * `recurse` - Whether to recursively add files in directories.
    /// * `save` - Whether to save the changes after adding files. If false,
    ///   this provides dry-run functionality.
    ///
    /// # Returns
    ///
    /// A tuple containing:
    /// - A vector of paths that were added
    /// - A vector of paths that were ignored
    fn smart_add(
        &mut self,
        file_list: Vec<&str>,
        recurse: Option<bool>,
        save: Option<bool>,
    ) -> (Vec<String>, Vec<String>);

    /// Commits the current state of the tree to the repository.
    ///
    /// # Arguments
    ///
    /// * `message` - An optional commit message describing the changes.
    ///
    /// # Returns
    ///
    /// The `RevisionId` of the new commit.
    fn commit(&mut self, message: Option<&str>) -> RevisionId;

    /// Creates a directory in the tree.
    ///
    /// # Arguments
    ///
    /// * `path` - The path where the directory should be created.
    ///
    /// # Returns
    ///
    /// Returns `Ok(())` if the directory was created successfully, or an `Error`
    /// if the operation failed.
    fn mkdir(&mut self, path: &str) -> Result<(), Error>;

    /// Updates the content of a file in the tree.
    ///
    /// Note that the file is written in-place rather than being written to a
    /// temporary location and renamed. As a consequence, readers can potentially
    /// see the file half-written.
    ///
    /// # Arguments
    ///
    /// * `path` - The path of the file to update.
    /// * `bytes` - The new content of the file.
    ///
    /// # Returns
    ///
    /// Returns `Ok(())` if the file was updated successfully, or an `Error` if
    /// the operation failed.
    fn put_file_bytes_non_atomic(&mut self, path: &str, bytes: &[u8]) -> Result<(), Error>;

    /// Adds paths to the set of versioned paths.
    ///
    /// Note that the command line normally calls `smart_add` instead, which can
    /// automatically recurse.
    ///
    /// This adds the files to the tree, so that they will be recorded by the
    /// next commit.
    ///
    /// # Arguments
    ///
    /// * `paths` - List of paths to add, relative to the base of the tree.
    ///
    /// # Returns
    ///
    /// Returns `Ok(())` if the paths were added successfully, or an `Error` if
    /// the operation failed.
    fn add(&mut self, paths: &[&str]) -> Result<(), Error>;

    /// Locks the working tree for write, and the branch for read.
    ///
    /// This is useful for operations which only need to mutate the working tree.
    /// Taking out branch write locks is a relatively expensive process and may
    /// fail if the branch is on read-only media. So branch write locks should
    /// only be taken out when we are modifying branch data - such as in
    /// operations like commit, pull, uncommit and update.
    ///
    /// # Returns
    ///
    /// Returns `Ok(())` if the lock was acquired successfully, or an error
    /// message if the operation failed.
    fn lock_tree_write(&mut self) -> Result<(), String>;
}

/// A trait for trees that represent a specific revision.
///
/// This trait extends `Tree` with methods for accessing revision-specific
/// information.
pub trait RevisionTree: Tree {
    /// Gets the revision ID of this tree.
    ///
    /// # Returns
    ///
    /// The `RevisionId` of the revision this tree represents.
    fn get_revision_id(&self) -> RevisionId;
}

/// A trait for working trees.
///
/// A working tree represents the current state of the working directory,
/// including both versioned and unversioned files.
pub trait WorkingTree: MutableTree {
    /// Gets the absolute path for a file or directory in the tree.
    ///
    /// # Arguments
    ///
    /// * `path` - The path relative to the tree root.
    ///
    /// # Returns
    ///
    /// The absolute path of the file or directory.
    fn abspath(&self, path: &str) -> std::path::PathBuf;

    /// Gets the revision ID of the last commit in this tree.
    ///
    /// # Returns
    ///
    /// The `RevisionId` of the last commit.
    fn last_revision(&self) -> RevisionId;
}
