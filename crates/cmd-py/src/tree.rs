//! Python bindings that expose Rust tree trait objects to Python.
//!
//! These are the counterpart to [`breezy::pytree::PyTree`]: where `PyTree`
//! wraps a Python tree so Rust can call it, the classes here wrap a Rust tree
//! so Python can call it. The class hierarchy mirrors the trait (and Python)
//! hierarchy: [`WorkingTree`] extends [`MutableTree`] extends [`Tree`], and
//! [`RevisionTree`] extends [`Tree`].
//!
//! A single tree is stored once, in the base [`Tree`] pyclass, as an
//! [`AnyTree`] enum tagged with the richest trait level it satisfies. Methods
//! at each level recover the appropriate `&dyn`/`&mut dyn` view by matching on
//! that enum, so `&mut self` trait methods keep working and a native Rust tree
//! can be wrapped without cloning or reference counting.
//!
//! Today the only trait implementor is `PyTree`, so the Python constructors
//! wrap a Python tree behind the trait object (Python -> Rust -> Python); the
//! `from_native_*` constructors are ready for a future native Rust tree.

use breezy::pytree::PyTree;
use breezy::tree::{ContentSummary, Error, IgnoredFiles, Sha1OrLink};
use breezy::RevisionId;
use pyo3::exceptions::{PyRuntimeError, PyTypeError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

import_exception!(bzrformats.errors, NotVersionedError);
import_exception!(breezy.errors, PathsNotVersionedError);
import_exception!(dromedary.errors, NoSuchFile);
import_exception!(breezy.errors, NoSuchRevision);

/// Convert a tree [`Error`] into the matching Python exception.
pub(crate) fn err_to_py(err: Error) -> PyErr {
    match err {
        Error::NotVersioned(path) => NotVersionedError::new_err(path),
        Error::PathsNotVersioned(paths) => PathsNotVersionedError::new_err(paths),
        Error::NoSuchFile(path) => NoSuchFile::new_err(path),
        Error::NoSuchRevision(revid) => NoSuchRevision::new_err(revid.as_bytes().to_vec()),
        Error::UnsupportedOperation(msg) => {
            Python::attach(|py| breezy::pyerrors::unsupported_operation(py, &msg))
        }
        Error::Other(msg) => PyRuntimeError::new_err(msg),
    }
}

/// The wrong-level error raised when a method requires a richer tree than the
/// one actually stored.
fn wrong_level(needed: &str) -> PyErr {
    PyTypeError::new_err(format!("tree does not implement {needed}"))
}

/// A Rust tree stored at the richest trait level it satisfies.
///
/// Every variant can be viewed as a [`breezy::tree::Tree`]; the richer
/// variants additionally offer [`breezy::tree::MutableTree`],
/// [`breezy::tree::WorkingTree`] and [`breezy::tree::RevisionTree`] views.
pub enum AnyTree {
    /// A plain tree.
    Tree(Box<dyn breezy::tree::Tree + Send + Sync>),
    /// A mutable tree.
    Mutable(Box<dyn breezy::tree::MutableTree + Send + Sync>),
    /// A working tree.
    Working(Box<dyn breezy::tree::WorkingTree + Send + Sync>),
    /// A revision tree.
    Revision(Box<dyn breezy::tree::RevisionTree + Send + Sync>),
}

impl AnyTree {
    fn as_tree(&self) -> &(dyn breezy::tree::Tree + Send + Sync) {
        match self {
            AnyTree::Tree(t) => t.as_ref(),
            AnyTree::Mutable(t) => t.as_ref(),
            AnyTree::Working(t) => t.as_ref(),
            AnyTree::Revision(t) => t.as_ref(),
        }
    }

    fn as_tree_mut(&mut self) -> &mut (dyn breezy::tree::Tree + Send + Sync) {
        match self {
            AnyTree::Tree(t) => t.as_mut(),
            AnyTree::Mutable(t) => t.as_mut(),
            AnyTree::Working(t) => t.as_mut(),
            AnyTree::Revision(t) => t.as_mut(),
        }
    }

    fn as_mutable(&self) -> Option<&(dyn breezy::tree::MutableTree + Send + Sync)> {
        match self {
            AnyTree::Mutable(t) => Some(t.as_ref()),
            AnyTree::Working(t) => Some(t.as_ref()),
            _ => None,
        }
    }

    fn as_mutable_mut(&mut self) -> Option<&mut (dyn breezy::tree::MutableTree + Send + Sync)> {
        match self {
            AnyTree::Mutable(t) => Some(t.as_mut()),
            AnyTree::Working(t) => Some(t.as_mut()),
            _ => None,
        }
    }

    fn as_working(&self) -> Option<&(dyn breezy::tree::WorkingTree + Send + Sync)> {
        match self {
            AnyTree::Working(t) => Some(t.as_ref()),
            _ => None,
        }
    }

    fn as_working_mut(&mut self) -> Option<&mut (dyn breezy::tree::WorkingTree + Send + Sync)> {
        match self {
            AnyTree::Working(t) => Some(t.as_mut()),
            _ => None,
        }
    }

    fn as_revision(&self) -> Option<&(dyn breezy::tree::RevisionTree + Send + Sync)> {
        match self {
            AnyTree::Revision(t) => Some(t.as_ref()),
            _ => None,
        }
    }
}

/// A version control tree.
///
/// ``Tree(tree)`` wraps an existing breezy tree object, such as a working tree
/// or a revision tree, and offers the ``breezy.tree.Tree`` API on it.
/// ``MutableTree``, ``WorkingTree`` and ``RevisionTree`` extend this class
/// with the richer APIs.
///
/// Methods that return trees, such as ``revision_tree``, return the original
/// breezy tree object where there is one.
#[pyclass(subclass, module = "breezy._cmd_rs")]
pub struct Tree(AnyTree);

impl Tree {
    /// Wrap a Rust tree at whichever level it satisfies.
    pub fn from_any(tree: AnyTree) -> Self {
        Tree(tree)
    }

    fn tree(&self) -> &(dyn breezy::tree::Tree + Send + Sync) {
        self.0.as_tree()
    }

    fn tree_mut(&mut self) -> &mut (dyn breezy::tree::Tree + Send + Sync) {
        self.0.as_tree_mut()
    }
}

#[pymethods]
impl Tree {
    /// Wrap the breezy tree object ``tree``.
    #[new]
    fn new(tree: Py<PyAny>) -> Self {
        Tree(AnyTree::Tree(Box::new(PyTree::new(tree))))
    }

    /// Return True if this tree supports rename tracking.
    fn supports_rename_tracking(&self) -> PyResult<bool> {
        self.tree().supports_rename_tracking().map_err(err_to_py)
    }

    /// Return True if this tree can contain explicitly versioned directories.
    fn has_versioned_directories(&self) -> PyResult<bool> {
        self.tree().has_versioned_directories().map_err(err_to_py)
    }

    /// Return True if this tree supports tree references.
    fn supports_tree_reference(&self) -> PyResult<bool> {
        self.tree().supports_tree_reference().map_err(err_to_py)
    }

    /// Return True if this tree supports symbolic links.
    fn supports_symlinks(&self) -> PyResult<bool> {
        self.tree().supports_symlinks().map_err(err_to_py)
    }

    /// Return True if ``path`` is special to the version control system.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    fn is_special_path(&self, path: &str) -> PyResult<bool> {
        self.tree().is_special_path(path).map_err(err_to_py)
    }

    /// Return True if this tree supports file ids.
    fn supports_file_ids(&self) -> PyResult<bool> {
        self.tree().supports_file_ids().map_err(err_to_py)
    }

    /// Return True if this tree supports content filtering.
    fn supports_content_filtering(&self) -> PyResult<bool> {
        self.tree().supports_content_filtering().map_err(err_to_py)
    }

    /// Return the conflicts in this tree.
    ///
    /// Returns:
    ///     A ``ConflictList`` of ``breezy.conflicts.Conflict`` objects. It is
    ///     empty for trees that do not record conflicts, such as revision
    ///     trees.
    fn conflicts(&self) -> PyResult<Py<PyAny>> {
        self.tree().conflicts().map_err(err_to_py)
    }

    /// Return the unversioned paths in this tree.
    ///
    /// Returns:
    ///     A list of paths relative to the tree root.
    fn extras(&self) -> PyResult<Vec<String>> {
        self.tree().extras().map_err(err_to_py)
    }

    /// Return the parent revision ids of this tree.
    ///
    /// Returns:
    ///     A list of revision ids as bytes; empty if the tree has no parents.
    fn get_parent_ids<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyBytes>>> {
        Ok(self
            .tree()
            .get_parent_ids()
            .map_err(err_to_py)?
            .into_iter()
            .map(|r| PyBytes::new(py, r.as_bytes()))
            .collect())
    }

    /// Return True if the tree has a file at ``filename``.
    ///
    /// Args:
    ///     filename: A path relative to the tree root.
    fn has_filename(&self, filename: &str) -> PyResult<bool> {
        self.tree().has_filename(filename).map_err(err_to_py)
    }

    /// Check whether ``filename`` is ignored by this tree.
    ///
    /// Args:
    ///     filename: A path relative to the tree root.
    ///
    /// Returns:
    ///     The ignore pattern that matches ``filename``, as a str, or None if
    ///     it is not ignored.
    fn is_ignored(&self, filename: &str) -> bool {
        self.tree().is_ignored(filename)
    }

    /// Return all versioned paths, including those of missing files.
    ///
    /// Returns:
    ///     A list of paths relative to the tree root.
    fn all_versioned_paths(&self) -> PyResult<Vec<String>> {
        self.tree().all_versioned_paths().map_err(err_to_py)
    }

    /// Return the versioned entries of the tree in by-directory order.
    ///
    /// The root comes first. Each directory's children are listed together,
    /// sorted by name, before the contents of those children.
    ///
    /// Args:
    ///     specific_files: An optional list of paths to restrict the result
    ///         to.
    ///     recurse_nested: If True, include the contents of nested trees as if
    ///         they were part of this tree; otherwise nested trees appear as
    ///         ``TreeReference`` entries without children.
    ///
    /// Returns:
    ///     A list of ``(path, entry)`` tuples, where ``entry`` is a
    ///     ``bzrformats.inventory`` entry holding the file id, name, parent id
    ///     and, for files, the executable bit.
    #[pyo3(signature = (specific_files=None, recurse_nested=false))]
    fn iter_entries_by_dir(
        &self,
        specific_files: Option<Vec<String>>,
        recurse_nested: bool,
    ) -> PyResult<Py<PyAny>> {
        let refs = specific_files
            .as_ref()
            .map(|s| s.iter().map(|p| p.as_str()).collect::<Vec<_>>());
        self.tree()
            .iter_entries_by_dir(refs.as_deref(), recurse_nested)
            .map_err(err_to_py)
    }

    /// Return the entries of the children of a directory or tree reference.
    ///
    /// Args:
    ///     path: The path of the directory, relative to the tree root.
    ///
    /// Returns:
    ///     A list of ``bzrformats.inventory`` entries, sorted by name.
    ///
    /// Raises:
    ///     NoSuchFile: If ``path`` is not versioned in the tree.
    ///     NotADirectory: If ``path`` is not a directory.
    fn iter_child_entries(&self, path: &str) -> PyResult<Py<PyAny>> {
        self.tree().iter_child_entries(path).map_err(err_to_py)
    }

    /// List the files in this tree.
    ///
    /// Unversioned directories are listed but not descended into.
    ///
    /// Args:
    ///     include_root: Whether to include an entry for the tree root.
    ///     from_dir: The directory to list, relative to the tree root, or None
    ///         for the root.
    ///     recursive: Whether to list the contents of subdirectories.
    ///     recurse_nested: Whether to descend into nested trees.
    ///
    /// Returns:
    ///     A list of ``(path, class, kind, entry)`` tuples. ``path`` is
    ///     relative to ``from_dir``; ``class`` is "V" for versioned, "?" for
    ///     unknown and "I" for ignored entries; ``kind`` is the kind as a str
    ///     and ``entry`` is a ``ListedFile``.
    #[pyo3(signature = (include_root=false, from_dir=None, recursive=true, recurse_nested=false))]
    fn list_files(
        &self,
        include_root: bool,
        from_dir: Option<&str>,
        recursive: bool,
        recurse_nested: bool,
    ) -> PyResult<Py<PyAny>> {
        self.tree()
            .list_files(include_root, from_dir, recursive, recurse_nested)
            .map_err(err_to_py)
    }

    /// Return the paths of the tree references in this tree.
    ///
    /// Returns:
    ///     A list of paths relative to the tree root.
    fn iter_references(&self) -> PyResult<Vec<String>> {
        self.tree().iter_references().map_err(err_to_py)
    }

    /// Find the nested tree that contains a path.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     A ``(tree, subpath)`` tuple with the nested tree and the path of
    ///     ``path`` inside it, or None if ``path`` is not inside a nested
    ///     tree.
    fn get_containing_nested_tree(&self, path: &str) -> PyResult<Option<(Py<PyAny>, String)>> {
        self.tree()
            .get_containing_nested_tree(path)
            .map_err(err_to_py)
    }

    /// Open the nested tree at ``path``.
    ///
    /// Args:
    ///     path: The path of the tree reference, relative to the tree root.
    ///
    /// Returns:
    ///     The nested tree.
    ///
    /// Raises:
    ///     MissingNestedTree: If the nested tree cannot be opened.
    fn get_nested_tree(&self, path: &str) -> PyResult<Py<PyAny>> {
        self.tree().get_nested_tree(path).map_err(err_to_py)
    }

    /// Return the kind of the file at ``path``.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The kind as a str: "file", "directory", "symlink" or
    ///     "tree-reference".
    ///
    /// Raises:
    ///     NoSuchFile: If there is nothing at ``path``.
    fn kind(&self, path: &str) -> PyResult<String> {
        self.tree()
            .kind(path)
            .map(|k| k.to_string())
            .map_err(err_to_py)
    }

    /// Return the kind recorded for ``path``.
    ///
    /// This may differ from ``kind`` in a working tree, and is available for
    /// versioned files even when the file itself is missing.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The kind as a str.
    fn stored_kind(&self, path: &str) -> PyResult<String> {
        self.tree()
            .stored_kind(path)
            .map(|k| k.to_string())
            .map_err(err_to_py)
    }

    /// Return a summary of the information about ``path``.
    ///
    /// The values describe the canonical form of the file, not the form after
    /// content filtering.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     A ``(kind, size, executable, sha1_or_link)`` tuple. ``size`` is the
    ///     size of a file if it can be cheaply determined and None otherwise;
    ///     ``executable`` is None unless the path is a file and the platform
    ///     supports the executable bit; ``sha1_or_link`` is the target of a
    ///     symlink as a str, the hex sha1 of a file as bytes if it is
    ///     available without reading the file, or None.
    fn path_content_summary<'py>(
        &self,
        py: Python<'py>,
        path: &str,
    ) -> PyResult<Bound<'py, pyo3::types::PyTuple>> {
        let ContentSummary {
            kind,
            size,
            executable,
            sha1_or_link,
        } = self.tree().path_content_summary(path).map_err(err_to_py)?;
        pyo3::types::PyTuple::new(
            py,
            [
                kind.into_pyobject(py)?.into_any(),
                size.into_pyobject(py)?.into_any(),
                executable.into_pyobject(py)?.into_any(),
                match sha1_or_link {
                    None => py.None().into_bound(py),
                    Some(Sha1OrLink::Sha1(sha1)) => PyBytes::new(py, &sha1).into_any(),
                    Some(Sha1OrLink::Link(target)) => target.into_pyobject(py)?.into_any(),
                },
            ],
        )
    }

    /// Return the revision id the tree reference at ``path`` points to.
    ///
    /// Args:
    ///     path: The path of the tree reference, relative to the tree root.
    ///
    /// Returns:
    ///     The revision id as bytes.
    fn get_reference_revision<'py>(
        &self,
        py: Python<'py>,
        path: &str,
    ) -> PyResult<Bound<'py, PyBytes>> {
        self.tree()
            .get_reference_revision(path)
            .map(|r| PyBytes::new(py, r.as_bytes()))
            .map_err(err_to_py)
    }

    /// Return a file object for reading the file at ``path``.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Raises:
    ///     NoSuchFile: If there is no file at ``path``.
    fn get_file(&self, path: &str) -> PyResult<Py<PyAny>> {
        self.tree().get_file(path).map_err(err_to_py)
    }

    /// Return a file object and stat value for the file at ``path``.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     A ``(file, stat_value)`` tuple. ``stat_value`` is None if the tree
    ///     has no stat information for the file.
    fn get_file_with_stat(&self, path: &str) -> PyResult<(Py<PyAny>, Option<Py<PyAny>>)> {
        self.tree().get_file_with_stat(path).map_err(err_to_py)
    }

    /// Return the content of the file at ``path``.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The whole content of the file as bytes.
    ///
    /// Raises:
    ///     NoSuchFile: If there is no file at ``path``.
    fn get_file_text<'py>(&self, py: Python<'py>, path: &str) -> PyResult<Bound<'py, PyBytes>> {
        self.tree()
            .get_file_text(path)
            .map(|b| PyBytes::new(py, &b))
            .map_err(err_to_py)
    }

    /// Return the content of the file at ``path`` as lines.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     A list of lines as bytes, each including its line ending.
    fn get_file_lines<'py>(
        &self,
        py: Python<'py>,
        path: &str,
    ) -> PyResult<Vec<Bound<'py, PyBytes>>> {
        Ok(self
            .tree()
            .get_file_lines(path)
            .map_err(err_to_py)?
            .into_iter()
            .map(|line| PyBytes::new(py, &line))
            .collect())
    }

    /// Return a verifier for the content of the file at ``path``.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///     stat_value: An optional stat value for the file.
    ///
    /// Returns:
    ///     A ``(verifier_name, verifier_data)`` tuple, such as ``("SHA1",
    ///     sha1)``. ``verifier_data`` is bytes, or None if it is not
    ///     available.
    #[pyo3(signature = (path, stat_value=None))]
    fn get_file_verifier<'py>(
        &self,
        py: Python<'py>,
        path: &str,
        stat_value: Option<Py<PyAny>>,
    ) -> PyResult<(String, Option<Bound<'py, PyBytes>>)> {
        let (name, data) = self
            .tree()
            .get_file_verifier(path, stat_value.as_ref())
            .map_err(err_to_py)?;
        Ok((name, data.map(|d| PyBytes::new(py, &d))))
    }

    /// Return the SHA1 of the file at ``path``.
    ///
    /// Prefer ``get_file_verifier`` where possible, as some trees can provide
    /// another verifier more cheaply.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///     stat_value: An optional stat value for the file.
    ///
    /// Returns:
    ///     The hex digest as bytes, or None if it is not available.
    #[pyo3(signature = (path, stat_value=None))]
    fn get_file_sha1<'py>(
        &self,
        py: Python<'py>,
        path: &str,
        stat_value: Option<Py<PyAny>>,
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        Ok(self
            .tree()
            .get_file_sha1(path, stat_value.as_ref())
            .map_err(err_to_py)?
            .map(|d| PyBytes::new(py, &d)))
    }

    /// Return the modification time of the file at ``path``.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The time in seconds since the epoch, as a float.
    fn get_file_mtime(&self, path: &str) -> PyResult<f64> {
        self.tree().get_file_mtime(path).map_err(err_to_py)
    }

    /// Return the size in bytes of the file at ``path``.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The size as an int, or None where the tree gives none, as revision
    ///     trees do for directories and symlinks.
    fn get_file_size(&self, path: &str) -> PyResult<Option<u64>> {
        self.tree().get_file_size(path).map_err(err_to_py)
    }

    /// Return True if the file at ``path`` is executable.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    fn is_executable(&self, path: &str) -> PyResult<bool> {
        self.tree().is_executable(path).map_err(err_to_py)
    }

    /// Iterate over the contents of several files.
    ///
    /// The files are not necessarily returned in the order given.
    ///
    /// Args:
    ///     desired_files: A list of ``(path, identifier)`` tuples. The
    ///         identifier is an opaque value that is passed back with the
    ///         file's content.
    ///
    /// Returns:
    ///     An iterator of ``(identifier, chunks)`` tuples, where ``chunks`` is
    ///     an iterable of bytes making up the file's content.
    fn iter_files_bytes(
        &self,
        py: Python<'_>,
        desired_files: Vec<(String, Py<PyAny>)>,
    ) -> PyResult<Py<PyAny>> {
        let pairs: Vec<(&str, Py<PyAny>)> = desired_files
            .iter()
            .map(|(p, id)| (p.as_str(), id.clone_ref(py)))
            .collect();
        self.tree().iter_files_bytes(&pairs).map_err(err_to_py)
    }

    /// Return the target of the symlink at ``path``.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The target as a str, or None if there is no symlink target for
    ///     ``path``.
    fn get_symlink_target(&self, path: &str) -> PyResult<Option<String>> {
        self.tree().get_symlink_target(path).map_err(err_to_py)
    }

    /// Return the lines of the file at ``path`` with the revision they came
    /// from.
    ///
    /// Mutable trees use the revision id b"current:" for lines that are new in
    /// the tree.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///     default_revision: A revision id, as bytes, to use for lines that do
    ///         not match a basis. Not all trees use it.
    ///
    /// Returns:
    ///     An iterator of ``(revision_id, line)`` tuples.
    #[pyo3(signature = (path, default_revision=None))]
    fn annotate_iter(&self, path: &str, default_revision: Option<Vec<u8>>) -> PyResult<Py<PyAny>> {
        let rev = default_revision.map(RevisionId::from);
        self.tree()
            .annotate_iter(path, rev.as_ref())
            .map_err(err_to_py)
    }

    /// Return True if ``path`` is versioned in this tree.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    fn is_versioned(&self, path: &str) -> PyResult<bool> {
        self.tree().is_versioned(path).map_err(err_to_py)
    }

    /// Find the paths in this tree related to paths in any of several trees.
    ///
    /// All matches in all trees are used, as are all children of matched
    /// directories.
    ///
    /// Args:
    ///     paths: The paths to look up, or None.
    ///     trees: An optional list of further trees to look the paths up in.
    ///     require_versioned: If True, every path must be versioned in at
    ///         least one of the trees.
    ///
    /// Returns:
    ///     A set of paths in this tree for ``paths`` and their children, or
    ///     None if ``paths`` is None.
    ///
    /// Raises:
    ///     PathsNotVersionedError: If ``require_versioned`` is set and some
    ///         paths are not versioned in any of the trees.
    #[pyo3(signature = (paths, trees=None, require_versioned=true))]
    fn find_related_paths_across_trees(
        &self,
        paths: Vec<String>,
        trees: Option<Vec<Py<PyAny>>>,
        require_versioned: bool,
    ) -> PyResult<Py<PyAny>> {
        let refs = paths.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        self.tree()
            .find_related_paths_across_trees(&refs, trees.as_deref(), require_versioned)
            .map_err(err_to_py)
    }

    /// Return a ``TreeDelta`` of the changes from ``other`` to this tree.
    ///
    /// Args:
    ///     other: The tree to compare with.
    ///     want_unchanged: Whether to include unchanged entries.
    ///     specific_files: An optional list of paths to restrict the
    ///         comparison to. All matches in all trees, including
    ///         ``extra_trees``, are used, and all children of matched
    ///         directories are included.
    ///     extra_trees: An optional list of further trees to use when looking
    ///         up ``specific_files``.
    ///     require_versioned: If True, all of ``specific_files`` must be
    ///         versioned.
    ///     include_root: Whether to include the root entry.
    ///     want_unversioned: Whether to include unversioned paths.
    ///
    /// Returns:
    ///     A ``breezy.delta.TreeDelta``.
    ///
    /// Raises:
    ///     PathsNotVersionedError: If ``require_versioned`` is set and some of
    ///         ``specific_files`` are not versioned.
    #[pyo3(signature = (other, want_unchanged=false, specific_files=None, extra_trees=None, require_versioned=false, include_root=false, want_unversioned=false))]
    #[allow(clippy::too_many_arguments)]
    fn changes_from(
        &self,
        other: Py<PyAny>,
        want_unchanged: bool,
        specific_files: Option<Vec<String>>,
        extra_trees: Option<Vec<Py<PyAny>>>,
        require_versioned: bool,
        include_root: bool,
        want_unversioned: bool,
    ) -> PyResult<Py<PyAny>> {
        let files = specific_files
            .as_ref()
            .map(|s| s.iter().map(|p| p.as_str()).collect::<Vec<_>>());
        self.tree()
            .changes_from(
                &other,
                want_unchanged,
                files.as_deref(),
                extra_trees.as_deref(),
                require_versioned,
                include_root,
                want_unversioned,
            )
            .map_err(err_to_py)
    }

    /// Return the changes from ``from_tree`` to this tree.
    ///
    /// Args:
    ///     from_tree: The tree to compare with.
    ///     include_unchanged: Whether to include unchanged entries.
    ///     specific_files: An optional list of paths to restrict the
    ///         comparison to. All matches in all trees, including
    ///         ``extra_trees``, are used, and all children of matched
    ///         directories are included.
    ///     pb: Ignored; accepted for compatibility.
    ///     extra_trees: An optional list of further trees to use when looking
    ///         up ``specific_files``.
    ///     require_versioned: If True, all of ``specific_files`` must be
    ///         versioned in one of the trees.
    ///     want_unversioned: Whether to include unversioned paths.
    ///
    /// Returns:
    ///     A list of ``InventoryTreeChange`` objects, in parent-to-child order
    ///     relative to this tree.
    ///
    /// Raises:
    ///     PathsNotVersionedError: If ``require_versioned`` is set and some of
    ///         ``specific_files`` are not versioned.
    #[pyo3(signature = (from_tree, include_unchanged=false, specific_files=None, extra_trees=None, require_versioned=true, want_unversioned=false))]
    fn iter_changes(
        &self,
        from_tree: Py<PyAny>,
        include_unchanged: bool,
        specific_files: Option<Vec<String>>,
        extra_trees: Option<Vec<Py<PyAny>>>,
        require_versioned: bool,
        want_unversioned: bool,
    ) -> PyResult<Py<PyAny>> {
        let files = specific_files
            .as_ref()
            .map(|s| s.iter().map(|p| p.as_str()).collect::<Vec<_>>());
        self.tree()
            .iter_changes(
                &from_tree,
                include_unchanged,
                files.as_deref(),
                extra_trees.as_deref(),
                require_versioned,
                want_unversioned,
            )
            .map_err(err_to_py)
    }

    /// Lock this tree for reading.
    ///
    /// Returns:
    ///     A ``breezy.lock.LogicalLockResult``, which can be used as a context
    ///     manager to release the lock.
    fn lock_read(&self) -> PyResult<Py<PyAny>> {
        self.tree().lock_read().map_err(err_to_py)
    }

    /// Release one lock held on this tree.
    fn unlock(&mut self) -> PyResult<()> {
        self.tree_mut().unlock().map_err(PyRuntimeError::new_err)
    }

    /// Return a revision tree for ``revision_id`` from data the tree has
    /// locally.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///
    /// Returns:
    ///     A ``RevisionTree``.
    ///
    /// Raises:
    ///     NoSuchRevision: If the tree for ``revision_id`` is not available
    ///         locally.
    fn revision_tree(&self, revision_id: Vec<u8>) -> PyResult<Py<PyAny>> {
        self.tree()
            .revision_tree(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return the unknown files in this tree: those neither versioned nor
    /// ignored.
    ///
    /// Returns:
    ///     A list of paths relative to the tree root.
    fn unknowns(&self) -> PyResult<Vec<String>> {
        self.tree().unknowns().map_err(err_to_py)
    }

    /// Return the paths from ``paths`` that are not versioned.
    ///
    /// Args:
    ///     paths: A list of paths relative to the tree root.
    ///
    /// Returns:
    ///     A list of the unversioned paths.
    fn filter_unversioned_files(&self, paths: Vec<String>) -> PyResult<Vec<String>> {
        let refs = paths.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        self.tree()
            .filter_unversioned_files(&refs)
            .map_err(err_to_py)
    }

    /// Walk the contents of this tree, one directory at a time.
    ///
    /// Args:
    ///     prefix: The path to start walking from, relative to the tree root.
    ///
    /// Returns:
    ///     An iterator of ``(directory_path, entries)`` tuples, as
    ///     ``breezy.tree.Tree.walkdirs`` yields them.
    #[pyo3(signature = (prefix=""))]
    fn walkdirs(&self, prefix: &str) -> PyResult<Py<PyAny>> {
        self.tree().walkdirs(prefix).map_err(err_to_py)
    }

    /// Find the preferences for a set of paths.
    ///
    /// Args:
    ///     path_names: A list of paths relative to the tree root.
    ///     pref_names: The names of the preferences to look up, or None for
    ///         all of them.
    ///
    /// Returns:
    ///     An iterator with one sequence of ``(name, value)`` tuples per path.
    #[pyo3(signature = (path_names, pref_names=None))]
    fn iter_search_rules(
        &self,
        path_names: Vec<String>,
        pref_names: Option<Vec<String>>,
    ) -> PyResult<Py<PyAny>> {
        let names = path_names.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        let prefs = pref_names
            .as_ref()
            .map(|p| p.iter().map(|s| s.as_str()).collect::<Vec<_>>());
        self.tree()
            .iter_search_rules(&names, prefs.as_deref())
            .map_err(err_to_py)
    }

    /// Create an archive of this tree.
    ///
    /// Args:
    ///     format: The archive format name, such as "tar" or "zip".
    ///     name: The name of the target file.
    ///     root: The name of the root directory inside the archive.
    ///     subdir: An optional subdirectory of the tree to export.
    ///     force_mtime: An optional modification time to give all files.
    ///     recurse_nested: Whether to include the contents of nested trees.
    ///
    /// Returns:
    ///     An iterator of bytes chunks making up the archive.
    #[pyo3(signature = (format, name, root="", subdir=None, force_mtime=None, recurse_nested=false))]
    fn archive(
        &self,
        format: &str,
        name: &str,
        root: &str,
        subdir: Option<&str>,
        force_mtime: Option<f64>,
        recurse_nested: bool,
    ) -> PyResult<Py<PyAny>> {
        self.tree()
            .archive(format, name, root, subdir, force_mtime, recurse_nested)
            .map_err(err_to_py)
    }

    /// Return True if files of ``kind`` can be versioned.
    ///
    /// Args:
    ///     kind: A kind name, such as "file" or "directory".
    #[staticmethod]
    fn versionable_kind(kind: &str) -> bool {
        matches!(kind, "file" | "directory" | "symlink" | "tree-reference")
    }

    /// Return a transform object for previewing changes to this tree.
    fn preview_transform(&self) -> PyResult<Py<PyAny>> {
        self.tree().preview_transform().map_err(err_to_py)
    }
}

/// A tree that can be modified.
///
/// ``MutableTree(tree)`` wraps an existing breezy mutable tree object, such as
/// a ``MemoryTree`` or a working tree, and adds the
/// ``breezy.mutabletree.MutableTree`` API to that of ``Tree``.
#[pyclass(extends=Tree, subclass, module = "breezy._cmd_rs")]
pub struct MutableTree;

impl MutableTree {
    fn init(tree: AnyTree) -> PyClassInitializer<Self> {
        PyClassInitializer::from(Tree(tree)).add_subclass(MutableTree)
    }
}

#[pymethods]
impl MutableTree {
    /// Wrap the breezy mutable tree object ``tree``.
    #[new]
    fn new(tree: Py<PyAny>) -> PyClassInitializer<Self> {
        MutableTree::init(AnyTree::Mutable(Box::new(PyTree::new(tree))))
    }

    /// Return True if ``filename`` is a control file of this tree.
    ///
    /// Only the metadata the version control system keeps for this tree
    /// counts; a stray ``.bzr`` directory placed on disk does not.
    ///
    /// Args:
    ///     filename: A path relative to the tree root.
    fn is_control_filename(self_: PyRef<'_, Self>, filename: &str) -> PyResult<bool> {
        self_
            .as_super()
            .0
            .as_mutable()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .is_control_filename(filename)
            .map_err(err_to_py)
    }

    /// Add paths to the set of versioned paths.
    ///
    /// The paths are recorded by the next commit. Most callers want
    /// ``smart_add``, which can recurse into directories.
    ///
    /// Args:
    ///     paths: A list of paths to add, relative to the tree root.
    ///     kinds: An optional list of kinds, one for each path.
    #[pyo3(signature = (paths, kinds=None))]
    fn add(
        mut self_: PyRefMut<'_, Self>,
        paths: Vec<String>,
        kinds: Option<Vec<String>>,
    ) -> PyResult<()> {
        let path_refs = paths.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        let kind_refs = kinds
            .as_ref()
            .map(|k| k.iter().map(|s| s.as_str()).collect::<Vec<_>>());
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .add(&path_refs, kind_refs.as_deref())
            .map_err(err_to_py)
    }

    /// Add a tree reference pointing at ``sub_tree``.
    ///
    /// Args:
    ///     sub_tree: The tree to reference. It must be inside this tree.
    fn add_reference(mut self_: PyRefMut<'_, Self>, sub_tree: Py<PyAny>) -> PyResult<()> {
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .add_reference(&sub_tree)
            .map_err(err_to_py)
    }

    /// Commit the changes in this tree to a new revision.
    ///
    /// Args:
    ///     message: The commit message.
    ///     revprops: An optional dict of revision properties.
    ///
    /// Returns:
    ///     The revision id of the new revision, as bytes.
    #[pyo3(signature = (message=None, revprops=None))]
    fn commit<'py>(
        mut self_: PyRefMut<'py, Self>,
        py: Python<'py>,
        message: Option<&str>,
        revprops: Option<Py<PyAny>>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .commit(message, revprops.as_ref())
            .map(|r| PyBytes::new(py, r.as_bytes()))
            .map_err(err_to_py)
    }

    /// Return True if the tree has at least one committable change.
    ///
    /// Args:
    ///     from_tree: The tree to compare with; defaults to the basis tree.
    #[pyo3(signature = (from_tree=None))]
    fn has_changes(self_: PyRef<'_, Self>, from_tree: Option<Py<PyAny>>) -> PyResult<bool> {
        self_
            .as_super()
            .0
            .as_mutable()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .has_changes(from_tree.as_ref())
            .map_err(err_to_py)
    }

    /// Check the tree for uncommitted changes and for being out of date.
    ///
    /// If ``strict`` is None and not set in the configuration, a warning is
    /// issued; if it is True, an error is raised; if it is False, nothing is
    /// checked.
    ///
    /// Args:
    ///     strict: True, False or None. If None, it is looked up in the branch
    ///         configuration under ``opt_name``.
    ///     opt_name: The name of the configuration option holding ``strict``.
    ///     more_error: Text explaining how to avoid the check.
    ///     more_warning: Text explaining what is happening.
    ///
    /// Raises:
    ///     UncommittedChanges: If ``strict`` and the tree has changes.
    ///     OutOfDateTree: If ``strict`` and the tree is out of date with its
    ///         branch.
    #[pyo3(signature = (strict, opt_name, more_error, more_warning))]
    fn check_changed_or_out_of_date(
        self_: PyRef<'_, Self>,
        strict: Option<bool>,
        opt_name: &str,
        more_error: &str,
        more_warning: &str,
    ) -> PyResult<()> {
        self_
            .as_super()
            .0
            .as_mutable()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .check_changed_or_out_of_date(strict, opt_name, more_error, more_warning)
            .map_err(err_to_py)
    }

    /// Lock the tree for writing and its branch for reading.
    ///
    /// Use this for operations that only change the tree; taking a write lock
    /// on the branch is more expensive and fails on read-only media.
    ///
    /// Returns:
    ///     A ``breezy.lock.LogicalLockResult``, which can be used as a context
    ///     manager to release the lock.
    fn lock_tree_write(mut self_: PyRefMut<'_, Self>) -> PyResult<()> {
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .lock_tree_write()
            .map_err(PyRuntimeError::new_err)
    }

    /// Lock the tree and its branch for writing.
    ///
    /// Returns:
    ///     A ``breezy.lock.LogicalLockResult``, which can be used as a context
    ///     manager to release the lock.
    fn lock_write(mut self_: PyRefMut<'_, Self>) -> PyResult<Py<PyAny>> {
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .lock_write()
            .map_err(err_to_py)
    }

    /// Create a directory in the tree and version it.
    ///
    /// Args:
    ///     path: The path of the new directory, relative to the tree root.
    ///
    /// Returns:
    ///     The file id of the new directory as bytes, or None if the tree does
    ///     not use file ids.
    fn mkdir<'py>(
        mut self_: PyRefMut<'py, Self>,
        py: Python<'py>,
        path: &str,
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        Ok(self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .mkdir(path)
            .map_err(err_to_py)?
            .map(|id| PyBytes::new(py, id.as_bytes())))
    }

    /// Replace the content of the file at ``path``.
    ///
    /// The file is written in place rather than renamed into place, so readers
    /// may see it half-written.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///     bytes: The new content.
    fn put_file_bytes_non_atomic(
        mut self_: PyRefMut<'_, Self>,
        path: &str,
        bytes: &[u8],
    ) -> PyResult<()> {
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .put_file_bytes_non_atomic(path, bytes)
            .map_err(err_to_py)
    }

    /// Set the parent revision ids of the tree.
    ///
    /// Args:
    ///     revision_ids: A list of revision ids, as bytes. Any of them may be
    ///         ghosts.
    ///     allow_leftmost_as_ghost: Whether the first parent may be a ghost.
    #[pyo3(signature = (revision_ids, allow_leftmost_as_ghost=false))]
    fn set_parent_ids(
        mut self_: PyRefMut<'_, Self>,
        revision_ids: Vec<Vec<u8>>,
        allow_leftmost_as_ghost: bool,
    ) -> PyResult<()> {
        let revids = revision_ids
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .set_parent_ids(&revids, allow_leftmost_as_ghost)
            .map_err(err_to_py)
    }

    /// Set the parents of the tree.
    ///
    /// Args:
    ///     parents_list: A list of ``(revision_id, tree)`` tuples. Pass None
    ///         as the tree for a ghost revision.
    ///     allow_leftmost_as_ghost: Whether the first parent may be a ghost.
    #[pyo3(signature = (parents_list, allow_leftmost_as_ghost=false))]
    fn set_parent_trees(
        mut self_: PyRefMut<'_, Self>,
        parents_list: Vec<(Vec<u8>, Py<PyAny>)>,
        allow_leftmost_as_ghost: bool,
    ) -> PyResult<()> {
        let parents = parents_list
            .into_iter()
            .map(|(revid, tree)| (RevisionId::from(revid), tree))
            .collect::<Vec<_>>();
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .set_parent_trees(&parents, allow_leftmost_as_ghost)
            .map_err(err_to_py)
    }

    /// Version the files in ``file_list``, recursing into directories.
    ///
    /// Args:
    ///     file_list: A list of paths. These are relative to the current
    ///         working directory, not to the tree root.
    ///     recurse: Whether to add the contents of directories.
    ///     action: An optional callable invoked for each path being added.
    ///     save: Whether to save the changes; if False, this is a dry run.
    ///
    /// Returns:
    ///     An ``(added, ignored)`` tuple: a list of the added paths and a dict
    ///     mapping each ignore pattern to the list of paths it caused to be
    ///     skipped.
    #[pyo3(signature = (file_list, recurse=true, action=None, save=true))]
    fn smart_add(
        mut self_: PyRefMut<'_, Self>,
        file_list: Vec<String>,
        recurse: bool,
        action: Option<Py<PyAny>>,
        save: bool,
    ) -> PyResult<(Vec<String>, IgnoredFiles)> {
        let refs = file_list.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .smart_add(&refs, recurse, action.as_ref(), save)
            .map_err(err_to_py)
    }

    /// Rename one file or directory.
    ///
    /// This can change the directory, the name or both.
    ///
    /// Args:
    ///     from_rel: The current path, relative to the tree root.
    ///     to_rel: The new path, relative to the tree root.
    ///     after: If True, the file has already been moved on disk and only
    ///         the versioning metadata is updated.
    #[pyo3(signature = (from_rel, to_rel, after=false))]
    fn rename_one(
        mut self_: PyRefMut<'_, Self>,
        from_rel: &str,
        to_rel: &str,
        after: bool,
    ) -> PyResult<()> {
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .rename_one(from_rel, to_rel, after)
            .map_err(err_to_py)
    }

    /// Copy one file or directory, and version the copy.
    ///
    /// Args:
    ///     from_rel: The path to copy, relative to the tree root.
    ///     to_rel: The path of the copy, relative to the tree root.
    fn copy_one(mut self_: PyRefMut<'_, Self>, from_rel: &str, to_rel: &str) -> PyResult<()> {
        self_
            .as_super()
            .0
            .as_mutable_mut()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .copy_one(from_rel, to_rel)
            .map_err(err_to_py)
    }

    /// Return a transform object for making changes to this tree.
    fn transform(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        self_
            .as_super()
            .0
            .as_mutable()
            .ok_or_else(|| wrong_level("MutableTree"))?
            .transform()
            .map_err(err_to_py)
    }

    /// Return the revision id of the last commit in this tree.
    ///
    /// Returns:
    ///     The leftmost parent id as bytes, or None if the tree has no
    ///     parents.
    fn last_revision<'py>(
        self_: PyRef<'py, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        let mt = self_
            .as_super()
            .0
            .as_mutable()
            .ok_or_else(|| wrong_level("MutableTree"))?;
        Ok(breezy::tree::MutableTree::last_revision(mt)
            .map_err(err_to_py)?
            .map(|r| PyBytes::new(py, r.as_bytes())))
    }
}

/// A working tree: the versioned files checked out on disk.
///
/// ``WorkingTree(tree)`` wraps an existing breezy ``WorkingTree``. Use
/// ``WorkingTree.open``, ``WorkingTree.open_containing`` or
/// ``WorkingTree.open_containing_paths`` to open one from a location. This
/// adds the ``breezy.workingtree.WorkingTree`` API to that of ``MutableTree``.
#[pyclass(extends=MutableTree, module = "breezy._cmd_rs")]
pub struct WorkingTree;

#[pymethods]
impl WorkingTree {
    /// Wrap the breezy working tree object ``tree``.
    #[new]
    fn new(tree: Py<PyAny>) -> PyClassInitializer<Self> {
        PyClassInitializer::from(Tree(AnyTree::Working(Box::new(PyTree::new(tree)))))
            .add_subclass(MutableTree)
            .add_subclass(WorkingTree)
    }

    /// Return True if this tree can store merge-modified hashes.
    fn supports_merge_modified(self_: PyRef<'_, Self>) -> PyResult<bool> {
        base(&self_)?.supports_merge_modified().map_err(err_to_py)
    }

    /// Return True if this tree requires a repository with rich roots.
    fn requires_rich_root(self_: PyRef<'_, Self>) -> PyResult<bool> {
        base(&self_)?.requires_rich_root().map_err(err_to_py)
    }

    /// Return True if this tree supports views.
    fn supports_views(self_: PyRef<'_, Self>) -> PyResult<bool> {
        base(&self_)?.supports_views().map_err(err_to_py)
    }

    /// Return True if file ids can be set explicitly in this tree.
    fn supports_setting_file_ids(self_: PyRef<'_, Self>) -> PyResult<bool> {
        base(&self_)?.supports_setting_file_ids().map_err(err_to_py)
    }

    /// The ``Branch`` this working tree is connected to.
    #[getter]
    fn branch(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        base(&self_)?.branch().map_err(err_to_py)
    }

    /// The transport for the user files in this working tree.
    #[getter]
    fn user_transport(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        base(&self_)?.user_transport().map_err(err_to_py)
    }

    /// The transport for the control files of this working tree.
    #[getter]
    fn control_transport(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        base(&self_)?.control_transport().map_err(err_to_py)
    }

    /// Return the configuration stack for this tree.
    ///
    /// Returns:
    ///     A ``breezy.config.Stack``.
    fn get_config_stack(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        base(&self_)?.get_config_stack().map_err(err_to_py)
    }

    /// The absolute path of the root of this working tree, as a str.
    // Paths are returned as OsString so they reach Python as str, like the
    // Python tree's, rather than as pathlib.Path.
    #[getter]
    fn basedir(self_: PyRef<'_, Self>) -> PyResult<std::ffi::OsString> {
        Ok(base(&self_)?.basedir().map_err(err_to_py)?.into_os_string())
    }

    /// Return the absolute path of ``path`` in this working tree.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The absolute path as a str.
    fn abspath(self_: PyRef<'_, Self>, path: &str) -> PyResult<std::ffi::OsString> {
        Ok(base(&self_)?
            .abspath(path)
            .map_err(err_to_py)?
            .into_os_string())
    }

    /// Return ``path`` relative to the root of this working tree.
    ///
    /// Args:
    ///     path: An absolute path, or a path relative to the current working
    ///         directory.
    ///
    /// Returns:
    ///     The path relative to the tree root.
    ///
    /// Raises:
    ///     PathNotChild: If ``path`` is not inside the tree.
    fn relpath(self_: PyRef<'_, Self>, path: &str) -> PyResult<String> {
        base(&self_)?.relpath(path).map_err(err_to_py)
    }

    /// Return the tree of the last revision of this working tree.
    ///
    /// If the leftmost parent is a ghost, this is an empty tree.
    ///
    /// Returns:
    ///     A ``RevisionTree``.
    fn basis_tree(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        base(&self_)?.basis_tree().map_err(err_to_py)
    }

    /// Return the revision id of the last revision of this working tree.
    ///
    /// Returns:
    ///     The revision id as bytes; ``b"null:"`` if there is none.
    fn last_revision<'py>(
        self_: PyRef<'py, Self>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let wt = base(&self_)?;
        Ok(PyBytes::new(
            py,
            breezy::tree::WorkingTree::last_revision(wt)
                .map_err(err_to_py)?
                .as_bytes(),
        ))
    }

    /// Break a lock on this tree held by another instance.
    ///
    /// The user is asked for confirmation through the UI factory if the lock
    /// may belong to an active process. The lock on the repository is checked
    /// as well.
    fn break_lock(mut self_: PyRefMut<'_, Self>) -> PyResult<()> {
        base_mut(&mut self_)?.break_lock().map_err(err_to_py)
    }

    /// Duplicate this working tree into another control directory.
    ///
    /// Modified files stay modified; ignored and unknown files are not copied.
    ///
    /// Args:
    ///     to_controldir: The ``ControlDir`` to create the new tree in.
    ///     revision_id: If not None, the revision the new tree's last revision
    ///         is set to, with the differences from this tree's last revision
    ///         merged in.
    ///
    /// Returns:
    ///     The new working tree.
    #[pyo3(signature = (to_controldir, revision_id=None))]
    fn clone(
        self_: PyRef<'_, Self>,
        to_controldir: Py<PyAny>,
        revision_id: Option<Vec<u8>>,
    ) -> PyResult<Py<PyAny>> {
        let rev = revision_id.map(RevisionId::from);
        base(&self_)?
            .clone(&to_controldir, rev.as_ref())
            .map_err(err_to_py)
    }

    /// Copy the current content and user files of this tree into ``tree``.
    ///
    /// Args:
    ///     tree: The tree to copy into.
    ///     revision_id: An optional revision id, as bytes, to copy instead of
    ///         the tree's last revision.
    #[pyo3(signature = (tree, revision_id=None))]
    fn copy_content_into(
        self_: PyRef<'_, Self>,
        tree: Py<PyAny>,
        revision_id: Option<Vec<u8>>,
    ) -> PyResult<()> {
        let rev = revision_id.map(RevisionId::from);
        base(&self_)?
            .copy_content_into(&tree, rev.as_ref())
            .map_err(err_to_py)
    }

    /// Add ``revision_id`` to the parents of this tree.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes. It may be a ghost unless it
    ///         would be the first parent and ``allow_leftmost_as_ghost`` is
    ///         False.
    ///     allow_leftmost_as_ghost: Whether the first parent may be a ghost.
    #[pyo3(signature = (revision_id, allow_leftmost_as_ghost=false))]
    fn add_parent_tree_id(
        mut self_: PyRefMut<'_, Self>,
        revision_id: Vec<u8>,
        allow_leftmost_as_ghost: bool,
    ) -> PyResult<()> {
        base_mut(&mut self_)?
            .add_parent_tree_id(&RevisionId::from(revision_id), allow_leftmost_as_ghost)
            .map_err(err_to_py)
    }

    /// Add a revision and its tree to the parents of this tree.
    ///
    /// Prefer this over ``add_parent_tree_id`` when the tree is already at
    /// hand.
    ///
    /// Args:
    ///     parent_tuple: A ``(revision_id, tree)`` tuple. Pass None as the
    ///         tree for a ghost revision.
    ///     allow_leftmost_as_ghost: Whether the first parent may be a ghost.
    #[pyo3(signature = (parent_tuple, allow_leftmost_as_ghost=false))]
    fn add_parent_tree(
        mut self_: PyRefMut<'_, Self>,
        parent_tuple: (Vec<u8>, Py<PyAny>),
        allow_leftmost_as_ghost: bool,
    ) -> PyResult<()> {
        let (revid, tree) = parent_tuple;
        base_mut(&mut self_)?
            .add_parent_tree((RevisionId::from(revid), tree), allow_leftmost_as_ghost)
            .map_err(err_to_py)
    }

    /// Add revisions to the pending merges of this tree.
    ///
    /// Args:
    ///     revision_ids: A list of revision ids, as bytes.
    fn add_pending_merge(
        mut self_: PyRefMut<'_, Self>,
        revision_ids: Vec<Vec<u8>>,
    ) -> PyResult<()> {
        let revids = revision_ids
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        base_mut(&mut self_)?
            .add_pending_merge(&revids)
            .map_err(err_to_py)
    }

    /// Set the pending merges of this tree.
    ///
    /// Args:
    ///     rev_list: A list of revision ids, as bytes.
    fn set_pending_merges(mut self_: PyRefMut<'_, Self>, rev_list: Vec<Vec<u8>>) -> PyResult<()> {
        let revids = rev_list
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        base_mut(&mut self_)?
            .set_pending_merges(&revids)
            .map_err(err_to_py)
    }

    /// Set the hashes of the files modified by a merge.
    ///
    /// Args:
    ///     modified_hashes: A dict mapping paths to SHA1 hex digests.
    fn set_merge_modified(
        mut self_: PyRefMut<'_, Self>,
        modified_hashes: Py<PyAny>,
    ) -> PyResult<()> {
        base_mut(&mut self_)?
            .set_merge_modified(&modified_hashes)
            .map_err(err_to_py)
    }

    /// Return the files modified by a merge that still have the merged
    /// content.
    ///
    /// Returns:
    ///     A dict mapping paths to SHA1 hex digests.
    fn merge_modified(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        base(&self_)?.merge_modified().map_err(err_to_py)
    }

    /// Merge changes from ``branch`` into this working tree.
    ///
    /// Args:
    ///     branch: The ``Branch`` to merge from.
    ///     to_revision: The revision id, as bytes, to merge up to; defaults to
    ///         the tip of ``branch``. It does not need to be in the history of
    ///         ``branch``.
    ///     from_revision: An optional revision id, as bytes, to use as the
    ///         base of the merge.
    ///     merge_type: An optional merger class to use.
    ///     force: Whether to merge even if the tree has uncommitted changes.
    ///
    /// Returns:
    ///     The conflicts reported by the merge.
    ///
    /// Raises:
    ///     UncommittedChanges: If the tree has changes and ``force`` is False.
    ///     PointlessMerge: If there is nothing to merge.
    #[pyo3(signature = (branch, to_revision=None, from_revision=None, merge_type=None, force=false))]
    fn merge_from_branch(
        mut self_: PyRefMut<'_, Self>,
        branch: Py<PyAny>,
        to_revision: Option<Vec<u8>>,
        from_revision: Option<Vec<u8>>,
        merge_type: Option<Py<PyAny>>,
        force: bool,
    ) -> PyResult<Py<PyAny>> {
        let to = to_revision.map(RevisionId::from);
        let from = from_revision.map(RevisionId::from);
        base_mut(&mut self_)?
            .merge_from_branch(
                &branch,
                to.as_ref(),
                from.as_ref(),
                merge_type.as_ref(),
                force,
            )
            .map_err(err_to_py)
    }

    /// Make ``other_tree``, a working tree nested inside this one, part of it.
    ///
    /// Args:
    ///     other_tree: The working tree to subsume.
    fn subsume(mut self_: PyRefMut<'_, Self>, other_tree: Py<PyAny>) -> PyResult<()> {
        base_mut(&mut self_)?
            .subsume(&other_tree)
            .map_err(err_to_py)
    }

    /// Extract a subdirectory of this tree into a tree of its own.
    ///
    /// A new branch is created for it.
    ///
    /// Args:
    ///     path: The path of the directory, relative to the tree root.
    ///     format: An optional control directory format for the new tree.
    ///
    /// Returns:
    ///     The new working tree.
    #[pyo3(signature = (path, format=None))]
    fn extract(
        mut self_: PyRefMut<'_, Self>,
        path: &str,
        format: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        base_mut(&mut self_)?
            .extract(path, format.as_ref())
            .map_err(err_to_py)
    }

    /// Write the in-memory metadata of this tree to disk.
    fn flush(mut self_: PyRefMut<'_, Self>) -> PyResult<()> {
        base_mut(&mut self_)?.flush().map_err(err_to_py)
    }

    /// Move files into a directory.
    ///
    /// The files keep their names. With ``after`` set, files already moved on
    /// disk only have the versioning metadata updated.
    ///
    /// Args:
    ///     from_paths: A list of paths to move, relative to the tree root.
    ///     to_dir: The versioned directory to move them into.
    ///     after: Whether the files have already been moved on disk.
    ///
    /// Returns:
    ///     A list of ``(from_path, to_path)`` tuples, one for each moved file.
    #[pyo3(name = "move", signature = (from_paths, to_dir=None, after=false))]
    fn move_files(
        mut self_: PyRefMut<'_, Self>,
        from_paths: Vec<String>,
        to_dir: Option<&str>,
        after: bool,
    ) -> PyResult<Vec<(String, String)>> {
        let refs = from_paths.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        base_mut(&mut self_)?
            .move_files(&refs, to_dir, after)
            .map_err(err_to_py)
    }

    /// Stop versioning ``paths`` and everything below them.
    ///
    /// The files are left on disk.
    ///
    /// Args:
    ///     paths: A list of paths relative to the tree root.
    ///
    /// Raises:
    ///     NoSuchFile: If a path is not versioned.
    fn unversion(mut self_: PyRefMut<'_, Self>, paths: Vec<String>) -> PyResult<()> {
        let refs = paths.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        base_mut(&mut self_)?.unversion(&refs).map_err(err_to_py)
    }

    /// Pull revisions from ``source`` into the branch and update this tree.
    ///
    /// Args:
    ///     source: The ``Branch`` to pull from.
    ///     overwrite: Whether to replace diverged history.
    ///     stop_revision: An optional revision id, as bytes, to pull up to.
    ///     change_reporter: An optional object to report changes to the tree.
    ///     local: Whether to only update the local branch of a bound branch.
    ///     show_base: Whether to show the base text in text conflicts.
    ///     tag_selector: An optional callable selecting the tags to pull.
    ///
    /// Returns:
    ///     The ``PullResult`` the tree's ``pull`` returns.
    #[pyo3(signature = (source, overwrite=false, stop_revision=None, change_reporter=None, local=false, show_base=false, tag_selector=None))]
    #[allow(clippy::too_many_arguments)]
    fn pull(
        mut self_: PyRefMut<'_, Self>,
        source: Py<PyAny>,
        overwrite: bool,
        stop_revision: Option<Vec<u8>>,
        change_reporter: Option<Py<PyAny>>,
        local: bool,
        show_base: bool,
        tag_selector: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let stop = stop_revision.map(RevisionId::from);
        base_mut(&mut self_)?
            .pull(
                &source,
                overwrite,
                stop.as_ref(),
                change_reporter.as_ref(),
                local,
                show_base,
                tag_selector.as_ref(),
            )
            .map_err(err_to_py)
    }

    /// Return the ignored files in this tree.
    ///
    /// Returns:
    ///     A list of ``(path, pattern)`` tuples with each ignored path and the
    ///     ignore pattern it matches.
    fn ignored_files(self_: PyRef<'_, Self>) -> PyResult<Vec<(String, String)>> {
        base(&self_)?.ignored_files().map_err(err_to_py)
    }

    /// Return True if this tree is locked.
    fn is_locked(self_: PyRef<'_, Self>) -> PyResult<bool> {
        base(&self_)?.is_locked().map_err(err_to_py)
    }

    /// Return True if the tree's lock on disk is held, by anyone.
    fn get_physical_lock_status(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        base(&self_)?.get_physical_lock_status().map_err(err_to_py)
    }

    /// Set the last revision of this working tree.
    ///
    /// Args:
    ///     new_revision: The revision id, as bytes.
    fn set_last_revision(mut self_: PyRefMut<'_, Self>, new_revision: Vec<u8>) -> PyResult<()> {
        base_mut(&mut self_)?
            .set_last_revision(&RevisionId::from(new_revision))
            .map_err(err_to_py)
    }

    /// Remove files from version control.
    ///
    /// Args:
    ///     files: A list of paths relative to the tree root.
    ///     verbose: Whether to report each removed file.
    ///     keep_files: Whether to keep the files on disk.
    ///     force: Whether to delete files and directories even if they have
    ///         changes or, for directories, are not empty.
    #[pyo3(signature = (files, verbose=false, keep_files=true, force=false))]
    fn remove(
        mut self_: PyRefMut<'_, Self>,
        files: Vec<String>,
        verbose: bool,
        keep_files: bool,
        force: bool,
    ) -> PyResult<()> {
        let refs = files.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        base_mut(&mut self_)?
            .remove(&refs, verbose, keep_files, force)
            .map_err(err_to_py)
    }

    /// Revert files in this tree to their content in ``old_tree``.
    ///
    /// Args:
    ///     filenames: An optional list of paths to revert, relative to the
    ///         tree root; None reverts the whole tree.
    ///     old_tree: The tree to revert to; defaults to the basis tree.
    ///     backups: Whether to keep backups of changed files.
    ///     report_changes: Whether to report the changes made.
    ///
    /// Returns:
    ///     The conflicts encountered.
    #[pyo3(signature = (filenames=None, old_tree=None, backups=true, report_changes=false))]
    fn revert(
        mut self_: PyRefMut<'_, Self>,
        filenames: Option<Vec<String>>,
        old_tree: Option<Py<PyAny>>,
        backups: bool,
        report_changes: bool,
    ) -> PyResult<Py<PyAny>> {
        let refs = filenames
            .as_ref()
            .map(|f| f.iter().map(|p| p.as_str()).collect::<Vec<_>>());
        base_mut(&mut self_)?
            .revert(refs.as_deref(), old_tree.as_ref(), backups, report_changes)
            .map_err(err_to_py)
    }

    /// Store the uncommitted changes in the branch and remove them from the
    /// tree.
    fn store_uncommitted(mut self_: PyRefMut<'_, Self>) -> PyResult<()> {
        base_mut(&mut self_)?.store_uncommitted().map_err(err_to_py)
    }

    /// Restore the uncommitted changes stored in the branch into the tree.
    fn restore_uncommitted(mut self_: PyRefMut<'_, Self>) -> PyResult<()> {
        base_mut(&mut self_)?
            .restore_uncommitted()
            .map_err(err_to_py)
    }

    /// Update this working tree to the tip of its branch.
    ///
    /// If the branch is bound, it is first updated from its master branch.
    /// Local uncommitted changes are preserved by merging them in.
    ///
    /// Args:
    ///     change_reporter: An optional object to report changes to the tree.
    ///     revision: An optional revision id, as bytes, to update to instead
    ///         of the tip. It must be in the branch history.
    ///     old_tip: If the branch has already been updated, the old tip it
    ///         returned, as bytes.
    ///     show_base: Whether to show the base text in text conflicts.
    ///
    /// Returns:
    ///     The number of conflicts, as an int.
    #[pyo3(signature = (change_reporter=None, revision=None, old_tip=None, show_base=false))]
    fn update(
        mut self_: PyRefMut<'_, Self>,
        change_reporter: Option<Py<PyAny>>,
        revision: Option<Vec<u8>>,
        old_tip: Option<Vec<u8>>,
        show_base: bool,
    ) -> PyResult<i64> {
        let rev = revision.map(RevisionId::from);
        let tip = old_tip.map(RevisionId::from);
        base_mut(&mut self_)?
            .update(
                change_reporter.as_ref(),
                rev.as_ref(),
                tip.as_ref(),
                show_base,
            )
            .map_err(err_to_py)
    }

    /// Replace the conflicts recorded in this tree.
    ///
    /// Args:
    ///     conflicts: A ``ConflictList``.
    fn set_conflicts(mut self_: PyRefMut<'_, Self>, conflicts: Py<PyAny>) -> PyResult<()> {
        base_mut(&mut self_)?
            .set_conflicts(&conflicts)
            .map_err(err_to_py)
    }

    /// Add conflicts to those recorded in this tree.
    ///
    /// Args:
    ///     conflicts: A list of ``breezy.conflicts.Conflict`` objects.
    fn add_conflicts(mut self_: PyRefMut<'_, Self>, conflicts: Py<PyAny>) -> PyResult<()> {
        base_mut(&mut self_)?
            .add_conflicts(&conflicts)
            .map_err(err_to_py)
    }

    /// Resolve text conflicts whose files no longer contain conflict markers.
    ///
    /// The ``.THIS``, ``.BASE`` and ``.OTHER`` files of resolved conflicts are
    /// deleted.
    ///
    /// Returns:
    ///     An ``(unresolved, resolved)`` tuple of ``ConflictList`` objects.
    fn auto_resolve(mut self_: PyRefMut<'_, Self>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
        base_mut(&mut self_)?.auto_resolve().map_err(err_to_py)
    }

    /// Check that the stored state of this tree is valid.
    fn check_state(self_: PyRef<'_, Self>) -> PyResult<()> {
        base(&self_)?.check_state().map_err(err_to_py)
    }

    /// Reset the stored state of this tree to a last-known-good state.
    ///
    /// This repairs corruption of the tree's metadata, such as its dirstate
    /// file.
    ///
    /// Args:
    ///     revision_ids: An optional list of revision ids, as bytes, to use as
    ///         the parents; defaults to the current parents.
    #[pyo3(signature = (revision_ids=None))]
    fn reset_state(
        mut self_: PyRefMut<'_, Self>,
        revision_ids: Option<Vec<Vec<u8>>>,
    ) -> PyResult<()> {
        let revids = revision_ids.map(|r| r.into_iter().map(RevisionId::from).collect::<Vec<_>>());
        base_mut(&mut self_)?
            .reset_state(revids.as_deref())
            .map_err(err_to_py)
    }

    /// Return the ``ShelfManager`` for this tree.
    fn get_shelf_manager(self_: PyRef<'_, Self>) -> PyResult<Py<PyAny>> {
        base(&self_)?.get_shelf_manager().map_err(err_to_py)
    }

    /// Return the path in the tree that matches ``path``, ignoring case.
    ///
    /// This allows case-insensitive lookups, for example on FAT filesystems.
    /// If nothing matches, ``path`` is returned with as many of its existing
    /// components as possible changed to their canonical form. Use
    /// ``get_canonical_paths`` to look up many paths.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The canonical path.
    fn get_canonical_path(self_: PyRef<'_, Self>, path: &str) -> PyResult<String> {
        base(&self_)?.get_canonical_path(path).map_err(err_to_py)
    }

    /// Return the canonical form of each of ``paths``.
    ///
    /// See ``get_canonical_path``.
    ///
    /// Args:
    ///     paths: A list of paths relative to the tree root.
    ///
    /// Returns:
    ///     A list of the canonical paths, in the same order.
    fn get_canonical_paths(self_: PyRef<'_, Self>, paths: Vec<String>) -> PyResult<Vec<String>> {
        let refs = paths.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        base(&self_)?.get_canonical_paths(&refs).map_err(err_to_py)
    }

    /// Return the parent branch of the tree reference at ``path``.
    ///
    /// Args:
    ///     path: The path of the tree reference, relative to the tree root.
    ///     branch: An optional branch to resolve the reference against.
    ///     possible_transports: An optional list of transports to reuse.
    ///
    /// Returns:
    ///     A ``Branch``.
    #[pyo3(signature = (path, branch=None, possible_transports=None))]
    fn reference_parent(
        self_: PyRef<'_, Self>,
        path: &str,
        branch: Option<Py<PyAny>>,
        possible_transports: Option<Vec<Py<PyAny>>>,
    ) -> PyResult<Py<PyAny>> {
        base(&self_)?
            .reference_parent(path, branch.as_ref(), possible_transports.as_deref())
            .map_err(err_to_py)
    }

    /// Return the branch location of the tree reference at ``path``.
    ///
    /// Args:
    ///     path: The path of the tree reference, relative to the tree root.
    ///     branch: An optional branch to look the reference up in.
    ///
    /// Returns:
    ///     The branch location as a str, or None if none is recorded.
    #[pyo3(signature = (path, branch=None))]
    fn get_reference_info(
        self_: PyRef<'_, Self>,
        path: &str,
        branch: Option<Py<PyAny>>,
    ) -> PyResult<Option<String>> {
        base(&self_)?
            .get_reference_info(path, branch.as_ref())
            .map_err(err_to_py)
    }

    /// Set the branch location of the tree reference at ``tree_path``.
    ///
    /// Args:
    ///     tree_path: The path of the tree reference, relative to the tree
    ///         root.
    ///     branch_location: The location of the referenced branch.
    fn set_reference_info(
        mut self_: PyRefMut<'_, Self>,
        tree_path: &str,
        branch_location: &str,
    ) -> PyResult<()> {
        base_mut(&mut self_)?
            .set_reference_info(tree_path, branch_location)
            .map_err(err_to_py)
    }
}

/// Borrow the wrapped tree as a `WorkingTree`, walking up to the base struct.
fn base<'a>(
    self_: &'a PyRef<'_, WorkingTree>,
) -> PyResult<&'a (dyn breezy::tree::WorkingTree + Send + Sync)> {
    self_
        .as_super()
        .as_super()
        .0
        .as_working()
        .ok_or_else(|| wrong_level("WorkingTree"))
}

/// Mutably borrow the wrapped tree as a `WorkingTree`, walking up to the base.
fn base_mut<'a>(
    self_: &'a mut PyRefMut<'_, WorkingTree>,
) -> PyResult<&'a mut (dyn breezy::tree::WorkingTree + Send + Sync)> {
    self_
        .as_super()
        .as_super()
        .0
        .as_working_mut()
        .ok_or_else(|| wrong_level("WorkingTree"))
}

/// A read-only tree of the contents of a single revision.
///
/// ``RevisionTree(tree)`` wraps an existing breezy ``RevisionTree``, such as
/// one returned by ``Repository.revision_tree``. This adds the
/// ``breezy.revisiontree.RevisionTree`` API to that of ``Tree``.
#[pyclass(extends=Tree, module = "breezy._cmd_rs")]
pub struct RevisionTree;

#[pymethods]
impl RevisionTree {
    /// Wrap the breezy revision tree object ``tree``.
    #[new]
    fn new(tree: Py<PyAny>) -> PyClassInitializer<Self> {
        PyClassInitializer::from(Tree(AnyTree::Revision(Box::new(PyTree::new(tree)))))
            .add_subclass(RevisionTree)
    }

    /// Return the revision id of this tree, as bytes.
    fn get_revision_id<'py>(
        self_: PyRef<'py, Self>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let rev = self_
            .as_super()
            .0
            .as_revision()
            .ok_or_else(|| wrong_level("RevisionTree"))?
            .get_revision_id()
            .map_err(err_to_py)?;
        Ok(PyBytes::new(py, rev.as_bytes()))
    }

    /// Return the revision id in which the file at ``path`` last changed.
    ///
    /// Args:
    ///     path: A path relative to the tree root.
    ///
    /// Returns:
    ///     The revision id as bytes.
    fn get_file_revision<'py>(
        self_: PyRef<'py, Self>,
        py: Python<'py>,
        path: &str,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let rev = self_
            .as_super()
            .0
            .as_revision()
            .ok_or_else(|| wrong_level("RevisionTree"))?
            .get_file_revision(path)
            .map_err(err_to_py)?;
        Ok(PyBytes::new(py, rev.as_bytes()))
    }

    /// Return True if the repository of this tree is locked.
    fn is_locked(self_: PyRef<'_, Self>) -> PyResult<bool> {
        self_
            .as_super()
            .0
            .as_revision()
            .ok_or_else(|| wrong_level("RevisionTree"))?
            .is_locked()
            .map_err(err_to_py)
    }
}
