use bazaar::osutils::Kind;
use bazaar::{FileId, RevisionId};

/// A handle to an opaque Python object.
///
/// A number of tree methods return rich domain objects (tree deltas,
/// inventory entries, conflict lists, lock results, transforms, branches,
/// config stacks, transports, ...) that do not yet have native Rust
/// equivalents. Because the only implementor of these traits is `PyTree`,
/// which delegates to a Python tree, such values are represented as a handle
/// to the underlying Python object rather than being converted eagerly.
#[cfg(feature = "pyo3")]
pub type PyObject = pyo3::Py<pyo3::PyAny>;

/// A handle to an opaque Python object.
///
/// This is the non-pyo3 fallback so the traits type-check without the `pyo3`
/// feature; the methods returning it are only ever called through `PyTree`,
/// which requires `pyo3`.
#[cfg(not(feature = "pyo3"))]
pub type PyObject = ();

/// Errors that can occur when working with version control trees.
#[derive(Debug)]
pub enum Error {
    /// A path is not under version control.
    NotVersioned(String),
    /// One or more paths are not under version control.
    PathsNotVersioned(Vec<String>),
    /// A path does not exist in the tree.
    NoSuchFile(String),
    /// A revision could not be found.
    NoSuchRevision(RevisionId),
    /// The operation is not supported by this tree.
    UnsupportedOperation(String),
    /// A generic error occurred.
    Other(String),
    /// A Python exception raised by a Python-backed tree, carried as is so
    /// it reaches Python again with its type intact.
    #[cfg(feature = "pyo3")]
    Python(pyo3::PyErr),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::NotVersioned(path) => write!(f, "Not versioned: {}", path),
            Error::PathsNotVersioned(paths) => write!(f, "Paths not versioned: {:?}", paths),
            Error::NoSuchFile(path) => write!(f, "No such file: {}", path),
            Error::NoSuchRevision(revid) => write!(f, "No such revision: {}", revid),
            Error::UnsupportedOperation(msg) => write!(f, "Unsupported operation: {}", msg),
            Error::Other(msg) => write!(f, "{}", msg),
            #[cfg(feature = "pyo3")]
            Error::Python(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for Error {}

/// A mapping from each ignore pattern to the paths it caused to be ignored.
///
/// This is the `ignored_files` half of the [`MutableTree::smart_add`] result.
pub type IgnoredFiles = std::collections::HashMap<String, Vec<String>>;

/// A summary of the information about a path in a tree.
///
/// Returned by [`Tree::path_content_summary`]. Corresponds to the
/// `(kind, size, executable, sha1-or-link)` tuple in the Python API.
#[derive(Debug, Clone)]
pub struct ContentSummary {
    /// The kind of the file. Always present.
    pub kind: String,
    /// The size of the canonical form, if the path is a file and the size can
    /// be cheaply determined.
    pub size: Option<u64>,
    /// Whether the file is executable, if the path is a file and the platform
    /// supports the executable bit.
    pub executable: Option<bool>,
    /// The link target if the path is a symlink, or the sha1 if it can be
    /// obtained without reading the file.
    pub sha1_or_link: Option<Sha1OrLink>,
}

/// The last field of a [`ContentSummary`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Sha1OrLink {
    /// The hex sha1 of a file's canonical form.
    Sha1(Vec<u8>),
    /// The target of a symlink.
    Link(String),
}

/// A trait representing a version control tree.
///
/// A tree represents a snapshot of the working directory at a particular point
/// in time, including all files and directories under version control.
///
/// This mirrors the Python `breezy.tree.Tree` abstract base class. Methods
/// that have a trivial constant default in Python are provided with a Rust
/// default; all other methods are required.
pub trait Tree {
    /// The Python tree this one wraps, if it wraps one.
    ///
    /// Bindings use this to hand a Python-backed tree back to Python as the
    /// original object rather than as a Rust object proxying to it.
    fn python_object(&self) -> Option<&PyObject> {
        None
    }

    /// Whether this tree supports rename tracking.
    ///
    /// This defaults to `true`, but some implementations may want to override
    /// it.
    fn supports_rename_tracking(&self) -> Result<bool, Error> {
        Ok(true)
    }

    /// Whether this tree can contain explicitly versioned directories.
    ///
    /// This defaults to `true`, but some implementations may want to override
    /// it.
    fn has_versioned_directories(&self) -> Result<bool, Error> {
        Ok(true)
    }

    /// Whether this tree supports tree references.
    fn supports_tree_reference(&self) -> Result<bool, Error>;

    /// Whether this tree supports symbolic links.
    ///
    /// This defaults to `true`.
    fn supports_symlinks(&self) -> Result<bool, Error> {
        Ok(true)
    }

    /// Whether a path is special to the version control system.
    ///
    /// This defaults to `false`.
    fn is_special_path(&self, _path: &str) -> Result<bool, Error> {
        Ok(false)
    }

    /// Whether this tree supports file ids.
    fn supports_file_ids(&self) -> Result<bool, Error>;

    /// Whether this tree supports content filtering.
    ///
    /// This defaults to `false`.
    fn supports_content_filtering(&self) -> Result<bool, Error> {
        Ok(false)
    }

    /// Compute a delta describing the changes from `other` to this tree.
    ///
    /// Returns a Python `TreeDelta` object.
    #[allow(clippy::too_many_arguments)]
    fn changes_from(
        &self,
        other: &PyObject,
        want_unchanged: bool,
        specific_files: Option<&[&str]>,
        extra_trees: Option<&[PyObject]>,
        require_versioned: bool,
        include_root: bool,
        want_unversioned: bool,
    ) -> Result<PyObject, Error>;

    /// Iterate over the changes relative to `from_tree`.
    ///
    /// Returns a Python iterator yielding `TreeChange` objects.
    #[allow(clippy::too_many_arguments)]
    fn iter_changes(
        &self,
        from_tree: &PyObject,
        include_unchanged: bool,
        specific_files: Option<&[&str]>,
        extra_trees: Option<&[PyObject]>,
        require_versioned: bool,
        want_unversioned: bool,
    ) -> Result<PyObject, Error>;

    /// Return the conflicts in this tree.
    ///
    /// Returns a Python `ConflictList`.
    fn conflicts(&self) -> Result<PyObject, Error>;

    /// Return the paths of unversioned files in this tree.
    fn extras(&self) -> Result<Vec<String>, Error>;

    /// Return the parent revision ids of this tree.
    fn get_parent_ids(&self) -> Result<Vec<RevisionId>, Error>;

    /// Whether the tree has a file with the given filename.
    fn has_filename(&self, filename: &str) -> Result<bool, Error>;

    /// Whether the given filename is ignored.
    ///
    /// This defaults to `false`.
    fn is_ignored(&self, _filename: &str) -> bool {
        false
    }

    /// Iterate over all versioned paths in the tree.
    fn all_versioned_paths(&self) -> Result<Vec<String>, Error>;

    /// Walk the tree in by-directory order, yielding `(path, entry)` pairs.
    ///
    /// Returns a Python iterator.
    fn iter_entries_by_dir(
        &self,
        specific_files: Option<&[&str]>,
        recurse_nested: bool,
    ) -> Result<PyObject, Error>;

    /// Iterate over the children of the directory or tree reference at `path`.
    ///
    /// Returns a Python iterator of inventory entries.
    fn iter_child_entries(&self, path: &str) -> Result<PyObject, Error>;

    /// List all files in the tree.
    ///
    /// Returns a Python iterator of `(path, versioned, kind, entry)` tuples.
    fn list_files(
        &self,
        include_root: bool,
        from_dir: Option<&str>,
        recursive: bool,
        recurse_nested: bool,
    ) -> Result<PyObject, Error>;

    /// Yield the paths that are tree references.
    fn iter_references(&self) -> Result<Vec<String>, Error>;

    /// Find the nested tree that contains `path`.
    ///
    /// Returns the nested tree (as a Python object) and the sub-path within
    /// that tree, or `None` if `path` is not inside a nested tree.
    fn get_containing_nested_tree(&self, path: &str) -> Result<Option<(PyObject, String)>, Error>;

    /// Open the nested tree at `path`.
    fn get_nested_tree(&self, path: &str) -> Result<PyObject, Error>;

    /// Return the kind of the file at `path`.
    fn kind(&self, path: &str) -> Result<Kind, Error>;

    /// Return the stored kind of the file at `path`.
    ///
    /// Defaults to [`Tree::kind`].
    fn stored_kind(&self, path: &str) -> Result<Kind, Error> {
        self.kind(path)
    }

    /// Return a content summary for `path`.
    fn path_content_summary(&self, path: &str) -> Result<ContentSummary, Error>;

    /// Return the revision id that the tree reference at `path` points to.
    fn get_reference_revision(&self, path: &str) -> Result<RevisionId, Error>;

    /// Return a file object for the file at `path`.
    ///
    /// Returns a Python file-like object.
    fn get_file(&self, path: &str) -> Result<PyObject, Error>;

    /// Return a `(file_object, stat_value)` pair for the file at `path`.
    ///
    /// The stat value may be `None`. Returns Python objects.
    fn get_file_with_stat(&self, path: &str) -> Result<(PyObject, Option<PyObject>), Error>;

    /// Return the whole content of the file at `path` as bytes.
    fn get_file_text(&self, path: &str) -> Result<Vec<u8>, Error>;

    /// Return the content of the file at `path` as a list of lines.
    fn get_file_lines(&self, path: &str) -> Result<Vec<Vec<u8>>, Error>;

    /// Return a `(verifier_name, verifier_data)` pair for the file at `path`.
    ///
    /// The default implementation returns `("SHA1", sha1)`. The data is the
    /// hex digest as bytes, or `None` if it is not available.
    fn get_file_verifier(
        &self,
        path: &str,
        stat_value: Option<&PyObject>,
    ) -> Result<(String, Option<Vec<u8>>), Error> {
        Ok(("SHA1".to_string(), self.get_file_sha1(path, stat_value)?))
    }

    /// Return the SHA1 of the file at `path` as a hex digest in bytes.
    ///
    /// Returns `None` if the sha1 is not available (e.g. for non-file paths).
    fn get_file_sha1(
        &self,
        path: &str,
        stat_value: Option<&PyObject>,
    ) -> Result<Option<Vec<u8>>, Error>;

    /// Return the modification time of the file at `path`.
    fn get_file_mtime(&self, path: &str) -> Result<f64, Error>;

    /// Return the size of the file at `path` in bytes, or `None` if the
    /// tree does not give one, as for directories in revision trees.
    fn get_file_size(&self, path: &str) -> Result<Option<u64>, Error>;

    /// Whether the file at `path` is executable.
    fn is_executable(&self, path: &str) -> Result<bool, Error>;

    /// Iterate over file contents.
    ///
    /// `desired_files` is a list of `(path, identifier)` pairs. Returns a
    /// Python iterator yielding `(identifier, bytes_iterator)` pairs.
    fn iter_files_bytes(&self, desired_files: &[(&str, PyObject)]) -> Result<PyObject, Error>;

    /// Return the target of the symlink at `path`.
    ///
    /// Returns `None` if the path is not a symlink or has no recorded target.
    fn get_symlink_target(&self, path: &str) -> Result<Option<String>, Error>;

    /// Iterate over `(revision_id, line)` tuples for the file at `path`.
    ///
    /// Returns a Python iterator.
    fn annotate_iter(
        &self,
        path: &str,
        default_revision: Option<&RevisionId>,
    ) -> Result<PyObject, Error>;

    /// Whether `path` is versioned.
    fn is_versioned(&self, path: &str) -> Result<bool, Error>;

    /// Find related paths across trees.
    ///
    /// Returns a Python iterator of paths (or `None` for missing entries).
    fn find_related_paths_across_trees(
        &self,
        paths: &[&str],
        trees: Option<&[PyObject]>,
        require_versioned: bool,
    ) -> Result<PyObject, Error>;

    /// Lock the tree for reading.
    fn lock_read(&self) -> Result<crate::lock::ReadLockRef, crate::lock::Error>;

    /// Obtain a cached revision tree for `revision_id`.
    ///
    /// Returns a Python tree object.
    fn revision_tree(&self, revision_id: &RevisionId) -> Result<PyObject, Error>;

    /// Return the paths of unknown (unversioned, non-ignored) files.
    fn unknowns(&self) -> Result<Vec<String>, Error>;

    /// Release one lock on the tree.
    fn unlock(&self) -> Result<(), crate::lock::Error>;

    /// Return the subset of `paths` that are not versioned.
    fn filter_unversioned_files(&self, paths: &[&str]) -> Result<Vec<String>, Error> {
        let mut unversioned = Vec::new();
        for path in paths {
            if !self.is_versioned(path)? {
                unversioned.push(path.to_string());
            }
        }
        Ok(unversioned)
    }

    /// Walk the directories of the tree from `prefix`.
    ///
    /// Returns a Python iterator.
    fn walkdirs(&self, prefix: &str) -> Result<PyObject, Error>;

    /// Find the preferences and rules for a set of filenames.
    ///
    /// Returns a Python iterator of rule tuple sequences, one per path.
    fn iter_search_rules(
        &self,
        path_names: &[&str],
        pref_names: Option<&[&str]>,
    ) -> Result<PyObject, Error>;

    /// Create an archive of this tree.
    ///
    /// Returns a Python iterator over archive chunks.
    fn archive(
        &self,
        format: &str,
        name: &str,
        root: &str,
        subdir: Option<&str>,
        force_mtime: Option<f64>,
        recurse_nested: bool,
    ) -> Result<PyObject, Error>;

    /// Whether the given kind can be versioned by this tree.
    fn versionable_kind(kind: &str) -> bool
    where
        Self: Sized,
    {
        matches!(kind, "file" | "directory" | "symlink" | "tree-reference")
    }

    /// Obtain a transform object for previewing changes.
    ///
    /// Returns a Python transform object.
    fn preview_transform(&self) -> Result<PyObject, Error>;
}

/// Whether entries of `kind` can be versioned.
pub fn versionable_kind(kind: Kind) -> bool {
    matches!(
        kind,
        Kind::File | Kind::Directory | Kind::Symlink | Kind::TreeReference
    )
}

/// A trait for trees that can be modified.
///
/// This trait extends [`Tree`] with methods for making changes to the working
/// directory, such as adding files, creating directories, and committing
/// changes. It mirrors the Python `breezy.mutabletree.MutableTree` class.
pub trait MutableTree: Tree {
    /// Whether file names in the tree are case sensitive.
    fn case_sensitive(&self) -> Result<bool, Error>;

    /// Whether `filename` is the name of a control file in this tree.
    fn is_control_filename(&self, filename: &str) -> Result<bool, Error>;

    /// Add paths to the set of versioned paths.
    ///
    /// Note that the command line normally calls [`MutableTree::smart_add`]
    /// instead, which can automatically recurse.
    ///
    /// This adds the files to the tree, so that they will be recorded by the
    /// next commit.
    ///
    /// * `paths` - List of paths to add, relative to the base of the tree.
    /// * `kinds` - Optional list of kinds, one per path.
    fn add(&mut self, paths: &[&str], kinds: Option<&[&str]>) -> Result<(), Error>;

    /// Add a tree reference to the tree pointing at `sub_tree`.
    fn add_reference(&mut self, sub_tree: &PyObject) -> Result<(), Error>;

    /// Commit the changes in this tree to a new revision.
    ///
    /// Returns the `RevisionId` of the new commit.
    fn commit(
        &mut self,
        message: Option<&str>,
        revprops: Option<&PyObject>,
    ) -> Result<RevisionId, Error>;

    /// Quickly check whether the tree contains at least one committable change.
    fn has_changes(&self, from_tree: Option<&PyObject>) -> Result<bool, Error>;

    /// Check the tree for uncommitted changes and branch sync.
    ///
    /// Depending on `strict`, warns or raises when the tree has uncommitted
    /// changes or is out of date.
    fn check_changed_or_out_of_date(
        &self,
        strict: Option<bool>,
        opt_name: &str,
        more_error: &str,
        more_warning: &str,
    ) -> Result<(), Error>;

    /// Return the revision id of the last commit performed in this tree.
    ///
    /// This is the leftmost parent id, or `None` if there are no parents.
    fn last_revision(&self) -> Result<Option<RevisionId>, Error>;

    /// Lock the working tree for tree-write and the branch for read.
    ///
    /// This is useful for operations which only need to mutate the working
    /// tree. Taking out branch write locks is a relatively expensive process
    /// and may fail if the branch is on read-only media, so branch write locks
    /// should only be taken out when modifying branch data.
    fn lock_tree_write(&self) -> Result<crate::lock::WriteLockRef, crate::lock::Error>;

    /// Lock the tree and its branch to allow mutating calls.
    fn lock_write(&self) -> Result<crate::lock::WriteLockRef, crate::lock::Error>;

    /// Create a directory in the tree.
    ///
    /// Returns the file id of the new directory, or `None` for trees that do
    /// not track file ids.
    fn mkdir(&mut self, path: &str) -> Result<Option<FileId>, Error>;

    /// Update the content of a file in the tree, writing in place.
    ///
    /// Note that the file is written in-place rather than being written to a
    /// temporary location and renamed. As a consequence, readers can
    /// potentially see the file half-written.
    fn put_file_bytes_non_atomic(&mut self, path: &str, bytes: &[u8]) -> Result<(), Error>;

    /// Set the parent ids of the working tree.
    fn set_parent_ids(
        &mut self,
        revision_ids: &[RevisionId],
        allow_leftmost_as_ghost: bool,
    ) -> Result<(), Error>;

    /// Set the parents of the working tree from `(revision_id, tree)` pairs.
    fn set_parent_trees(
        &mut self,
        parents_list: &[(RevisionId, PyObject)],
        allow_leftmost_as_ghost: bool,
    ) -> Result<(), Error>;

    /// Version a list of files, optionally recursing into directories.
    ///
    /// This method is designed for user convenience rather than API clarity.
    ///
    /// * `file_list` - Paths to add, interpreted relative to the process's
    ///   current working directory, not relative to the tree.
    /// * `recurse` - Whether to recursively add files in directories.
    /// * `save` - Whether to save the changes. If false, this provides dry-run
    ///   functionality.
    ///
    /// Returns `(files_added, ignored_files)`, where `ignored_files` maps each
    /// ignore pattern to the paths it caused to be ignored.
    fn smart_add(
        &mut self,
        file_list: &[&str],
        recurse: bool,
        action: Option<&PyObject>,
        save: bool,
    ) -> Result<(Vec<String>, IgnoredFiles), Error>;

    /// Rename one file, changing directory, filename, or both.
    fn rename_one(&mut self, from_rel: &str, to_rel: &str, after: bool) -> Result<(), Error>;

    /// Copy one file or directory.
    fn copy_one(&mut self, from_rel: &str, to_rel: &str) -> Result<(), Error>;

    /// Return a transform object for use with this tree.
    ///
    /// Returns a Python transform object.
    fn transform(&self) -> Result<PyObject, Error>;
}

/// A trait for trees that represent a specific revision.
///
/// This trait extends [`Tree`] with methods for accessing revision-specific
/// information. It mirrors the Python `breezy.revisiontree.RevisionTree` class.
pub trait RevisionTree: Tree {
    /// Return the revision id of this tree.
    fn get_revision_id(&self) -> Result<RevisionId, Error>;

    /// Return the revision id in which the file at `path` last changed.
    fn get_file_revision(&self, path: &str) -> Result<RevisionId, Error>;

    /// Whether the underlying repository is locked.
    fn is_locked(&self) -> Result<bool, Error>;
}

/// A trait for working trees.
///
/// A working tree represents the current state of the working directory,
/// including both versioned and unversioned files. It mirrors the Python
/// `breezy.workingtree.WorkingTree` class.
pub trait WorkingTree: MutableTree {
    /// The absolute path of the tree's root directory (the Python ``basedir``).
    fn basedir(&self) -> Result<std::path::PathBuf, Error>;

    /// Whether the tree supports storing merge-modified information.
    fn supports_merge_modified(&self) -> Result<bool, Error>;

    /// Whether the tree requires rich root support.
    fn requires_rich_root(&self) -> Result<bool, Error>;

    /// Whether the tree supports views.
    fn supports_views(&self) -> Result<bool, Error>;

    /// The tree's views, as a Python view manager object.
    fn views(&self) -> Result<PyObject, Error>;

    /// Whether the tree supports setting file ids.
    fn supports_setting_file_ids(&self) -> Result<bool, Error>;

    /// Return the branch this working tree is connected to.
    fn branch(&self) -> Result<crate::controldir::BranchRef, Error>;

    /// The control directory the tree lives in.
    fn controldir(&self) -> Result<Box<dyn crate::controldir::ControlDir>, Error>;

    /// Return the transport for user files in the working tree.
    ///
    /// Returns a Python transport object.
    fn user_transport(&self) -> Result<PyObject, Error>;

    /// Return the transport for control files in the working tree.
    ///
    /// Returns a Python transport object.
    fn control_transport(&self) -> Result<PyObject, Error>;

    /// Return the config stack for this tree.
    ///
    /// Returns a Python config stack object.
    fn get_config_stack(&self) -> Result<PyObject, Error>;

    /// Return the absolute path for a file or directory in the tree.
    fn abspath(&self, path: &str) -> Result<std::path::PathBuf, Error>;

    /// Return the path portion of `path` relative to the tree base.
    fn relpath(&self, path: &str) -> Result<String, Error>;

    /// The tree-relative paths of `file_list`: canonicalised for the
    /// filesystem when `canonicalize`, and checked against the current view
    /// when `apply_view`.
    fn safe_relpath_files(
        &self,
        file_list: &[&str],
        canonicalize: bool,
        apply_view: bool,
    ) -> Result<Vec<String>, Error>;

    /// Return the revision tree for the current last revision.
    ///
    /// Returns a Python revision tree object.
    fn basis_tree(&self) -> Result<PyObject, Error>;

    /// Return the revision id of the last commit in this tree.
    fn last_revision(&self) -> Result<RevisionId, Error>;

    /// Break a lock held by another instance.
    fn break_lock(&self) -> Result<(), crate::lock::Error>;

    /// Duplicate this working tree into another control directory.
    fn clone(
        &self,
        to_controldir: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<PyObject, Error>;

    /// Copy the current content and user files into another tree.
    fn copy_content_into(
        &self,
        tree: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<(), Error>;

    /// Add a revision id as an additional parent.
    fn add_parent_tree_id(
        &mut self,
        revision_id: &RevisionId,
        allow_leftmost_as_ghost: bool,
    ) -> Result<(), Error>;

    /// Add a `(revision_id, tree)` pair as a parent.
    fn add_parent_tree(
        &mut self,
        parent_tuple: (RevisionId, PyObject),
        allow_leftmost_as_ghost: bool,
    ) -> Result<(), Error>;

    /// Add revision ids as pending-merge parents.
    fn add_pending_merge(&mut self, revision_ids: &[RevisionId]) -> Result<(), Error>;

    /// Set the list of pending merge revision ids.
    fn set_pending_merges(&mut self, rev_list: &[RevisionId]) -> Result<(), Error>;

    /// Set the merge-modified hashes.
    fn set_merge_modified(&mut self, modified_hashes: &PyObject) -> Result<(), Error>;

    /// Return a dict of files modified by a merge (`file_id -> sha1`).
    ///
    /// Returns a Python dict object.
    fn merge_modified(&self) -> Result<PyObject, Error>;

    /// Merge from a branch into this working tree.
    ///
    /// Returns a Python `ConflictList` of the conflicts encountered.
    fn merge_from_branch(
        &mut self,
        branch: &PyObject,
        to_revision: Option<&RevisionId>,
        from_revision: Option<&RevisionId>,
        merge_type: Option<&PyObject>,
        force: bool,
    ) -> Result<PyObject, Error>;

    /// Subsume another working tree into this one.
    fn subsume(&mut self, other_tree: &PyObject) -> Result<(), Error>;

    /// Extract a subtree into a new branch.
    ///
    /// Returns the extracted working tree as a Python object.
    fn extract(&mut self, path: &str, format: Option<&PyObject>) -> Result<PyObject, Error>;

    /// Write in-memory metadata to disk.
    fn flush(&mut self) -> Result<(), Error>;

    /// Move or rename files within the tree.
    ///
    /// Returns the list of `(from, to)` pairs that were moved.
    fn move_files(
        &mut self,
        from_paths: &[&str],
        to_dir: Option<&str>,
        after: bool,
    ) -> Result<Vec<(String, String)>, Error>;

    /// Remove paths from the versioned set.
    fn unversion(&mut self, paths: &[&str]) -> Result<(), Error>;

    /// Pull changes from another branch.
    ///
    /// Returns a Python `PullResult`.
    #[allow(clippy::too_many_arguments)]
    fn pull(
        &mut self,
        source: &PyObject,
        overwrite: bool,
        stop_revision: Option<&RevisionId>,
        change_reporter: Option<&PyObject>,
        local: bool,
        show_base: bool,
        tag_selector: Option<&PyObject>,
    ) -> Result<PyObject, Error>;

    /// Yield ignored files as `(path, pattern)` pairs.
    fn ignored_files(&self) -> Result<Vec<(String, String)>, Error>;

    /// Whether this tree is locked.
    fn is_locked(&self) -> Result<bool, Error>;

    /// Whether the physical lock is held, by anyone.
    fn get_physical_lock_status(&self) -> Result<bool, crate::lock::Error>;

    /// Change the last revision recorded in the working tree.
    fn set_last_revision(&mut self, new_revision: &RevisionId) -> Result<(), Error>;

    /// Remove files from the working tree metadata.
    fn remove(
        &mut self,
        files: &[&str],
        verbose: bool,
        keep_files: bool,
        force: bool,
    ) -> Result<(), Error>;

    /// Revert files in the working tree.
    ///
    /// Returns a Python `ConflictList` describing conflicts encountered.
    fn revert(
        &mut self,
        filenames: Option<&[&str]>,
        old_tree: Option<&PyObject>,
        backups: bool,
        report_changes: bool,
    ) -> Result<PyObject, Error>;

    /// Store uncommitted changes into the branch.
    fn store_uncommitted(&mut self) -> Result<(), Error>;

    /// Restore uncommitted changes from the branch.
    fn restore_uncommitted(&mut self) -> Result<(), Error>;

    /// Update the working tree along its branch.
    ///
    /// Returns the number of conflicts encountered.
    fn update(
        &mut self,
        change_reporter: Option<&PyObject>,
        revision: Option<&RevisionId>,
        old_tip: Option<&RevisionId>,
        show_base: bool,
    ) -> Result<i64, Error>;

    /// Set the list of conflicts.
    fn set_conflicts(&mut self, conflicts: &PyObject) -> Result<(), Error>;

    /// Add to the list of conflicts.
    fn add_conflicts(&mut self, conflicts: &PyObject) -> Result<(), Error>;

    /// Auto-resolve text conflicts by content.
    ///
    /// Returns `(unresolved, resolved)` Python conflict lists.
    fn auto_resolve(&mut self) -> Result<(PyObject, PyObject), Error>;

    /// Check that the working state is valid.
    fn check_state(&self) -> Result<(), Error>;

    /// Hard-reset the tree to a last-known-good state.
    fn reset_state(&mut self, revision_ids: Option<&[RevisionId]>) -> Result<(), Error>;

    /// Return the shelf manager for this tree.
    ///
    /// Returns a Python `ShelfManager` object.
    fn get_shelf_manager(&self) -> Result<PyObject, Error>;

    /// Case-insensitively canonicalize a single path.
    fn get_canonical_path(&self, path: &str) -> Result<String, Error>;

    /// Case-insensitively canonicalize multiple paths.
    fn get_canonical_paths(&self, paths: &[&str]) -> Result<Vec<String>, Error>;

    /// Return the parent branch for the tree reference at `path`.
    ///
    /// Returns a Python branch object.
    fn reference_parent(
        &self,
        path: &str,
        branch: Option<&PyObject>,
        possible_transports: Option<&[PyObject]>,
    ) -> Result<PyObject, Error>;

    /// Return the branch location for the tree reference at `path`.
    ///
    /// Returns `None` if the reference has no recorded location.
    fn get_reference_info(
        &self,
        path: &str,
        branch: Option<&PyObject>,
    ) -> Result<Option<String>, Error>;

    /// Set the tree reference info for `tree_path`.
    fn set_reference_info(&mut self, tree_path: &str, branch_location: &str) -> Result<(), Error>;
}

impl From<crate::lock::Error> for Error {
    fn from(err: crate::lock::Error) -> Self {
        match err {
            crate::lock::Error::UnsupportedOperation(msg) => Error::UnsupportedOperation(msg),
            #[cfg(feature = "pyo3")]
            crate::lock::Error::Python(e) => Error::Python(e),
            other => Error::Other(other.to_string()),
        }
    }
}
