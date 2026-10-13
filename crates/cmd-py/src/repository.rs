//! Python binding that exposes a Rust `dyn Repository` to Python.
//!
//! Counterpart to [`breezy::pyrepository::PyRepository`]: where `PyRepository`
//! wraps a Python repository for Rust, this `Repository` pyclass wraps a Rust
//! repository for Python. The `#[new]` constructor wraps a Python repository
//! (via `PyRepository`).

use breezy::pyrepository::PyRepository;
use breezy::repository::Error;
use breezy::RevisionId;
use pyo3::exceptions::PyRuntimeError;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

import_exception!(breezy.errors, NoSuchRevision);

/// Convert a repository [`Error`] into the matching Python exception.
///
/// `NoSuchRevision(branch, revision)` takes a `branch` positional argument in
/// Python; since a native repository has no Python object, `None` is passed.
fn err_to_py(err: Error) -> PyErr {
    Python::attach(|py| match err {
        Error::NoSuchRevision(revid) => {
            NoSuchRevision::new_err((py.None(), revid.as_bytes().to_vec()))
        }
        Error::UnsupportedOperation(msg) => breezy::pyerrors::unsupported_operation(py, &msg),
        Error::Other(msg) => PyRuntimeError::new_err(msg),
    })
}

/// A breezy repository: the store of revisions, file texts and signatures that
/// one or more branches share.
///
/// Construct one by wrapping an existing breezy repository object, as
/// ``Repository(repo)``, or use ``Repository.open`` or ``Repository.create``.
/// Revision ids are passed and returned as bytes.
#[pyclass(module = "breezy._cmd_rs")]
pub struct Repository(Box<dyn breezy::repository::Repository + Send + Sync>);

impl Repository {
    /// Wrap an already-boxed repository.
    pub fn from_boxed(repo: Box<dyn breezy::repository::Repository + Send + Sync>) -> Self {
        Repository(repo)
    }
}

#[pymethods]
impl Repository {
    /// Wrap an existing breezy repository object.
    ///
    /// Args:
    ///     repository: A ``breezy.repository.Repository`` instance. Every
    ///         method call is forwarded to it.
    #[new]
    fn new(repository: Py<PyAny>) -> Self {
        Repository(Box::new(PyRepository::new(repository)))
    }

    /// Open the repository at a location.
    ///
    /// Args:
    ///     location: URL or local path of the control directory that holds
    ///         the repository.
    ///
    /// Returns:
    ///     The repository. A repository backed by a breezy repository object
    ///     is returned as that object rather than as a ``Repository`` wrapper.
    ///
    /// Raises:
    ///     NotBranchError: If there is no control directory at ``location``.
    ///     NoRepositoryPresent: If the control directory has no repository.
    #[staticmethod]
    fn open(location: &str) -> PyResult<Self> {
        Ok(Repository(
            breezy::controldir::open(location)?.open_repository()?,
        ))
    }

    /// The transport for user-visible data.
    #[getter]
    fn user_transport(&self) -> PyResult<Py<PyAny>> {
        self.0.user_transport().map_err(err_to_py)
    }

    /// The transport for the repository's control files.
    #[getter]
    fn control_transport(&self) -> PyResult<Py<PyAny>> {
        self.0.control_transport().map_err(err_to_py)
    }

    /// Break a lock held by another instance, if one is present.
    ///
    /// The UI factory is used to ask for confirmation if the lock may be held
    /// by an active process.
    fn break_lock(&mut self) -> PyResult<()> {
        self.0.break_lock().map_err(err_to_py)
    }

    /// Return True if the repository is locked.
    fn is_locked(&self) -> PyResult<bool> {
        self.0.is_locked().map_err(err_to_py)
    }

    /// Return True if the repository is locked for writing.
    fn is_write_locked(&self) -> PyResult<bool> {
        self.0.is_write_locked().map_err(err_to_py)
    }

    /// Lock the repository for writing.
    ///
    /// A write lock is required to start a write group, and write groups are
    /// required for inserting data. Locks are counted; each successful call
    /// must be matched by a call to ``unlock``.
    ///
    /// Args:
    ///     token: If the repository is already physically locked, the token of
    ///         that lock, to take it over instead of failing.
    ///
    /// Returns:
    ///     A ``RepositoryWriteLockResult``. It can be used as a context
    ///     manager, and its ``repository_token`` attribute holds the lock
    ///     token (or None if the format does not support tokens).
    ///
    /// Raises:
    ///     TokenLockingNotSupported: If a token is given but the format does
    ///         not support lock tokens.
    ///     TokenMismatch: If the token does not match the existing lock.
    #[pyo3(signature = (token=None))]
    fn lock_write(&mut self, token: Option<&str>) -> PyResult<Py<PyAny>> {
        self.0.lock_write(token).map_err(err_to_py)
    }

    /// Lock the repository for reading.
    ///
    /// Each successful call must be matched by a call to ``unlock``.
    ///
    /// Returns:
    ///     A ``LogicalLockResult`` whose ``unlock`` method releases the lock;
    ///     it can be used as a context manager.
    fn lock_read(&self) -> PyResult<Py<PyAny>> {
        self.0.lock_read().map_err(err_to_py)
    }

    /// Release one lock on the repository.
    ///
    /// Raises:
    ///     BzrError: If a write group is still open when the last write lock
    ///         is released; the write group is aborted.
    fn unlock(&mut self) -> PyResult<()> {
        self.0.unlock().map_err(err_to_py)
    }

    /// Return True if the physical lock is held, by this or any other process.
    fn get_physical_lock_status(&self) -> PyResult<Py<PyAny>> {
        self.0.get_physical_lock_status().map_err(err_to_py)
    }

    /// Keep the physical lock when this object is unlocked.
    ///
    /// Only supported by formats whose ``lock_write`` returns a token.
    fn leave_lock_in_place(&mut self) -> PyResult<()> {
        self.0.leave_lock_in_place().map_err(err_to_py)
    }

    /// Release the physical lock when this object is unlocked.
    ///
    /// This applies even if this object did not originally take the lock. Only
    /// supported by formats whose ``lock_write`` returns a token.
    fn dont_leave_lock_in_place(&mut self) -> PyResult<()> {
        self.0.dont_leave_lock_in_place().map_err(err_to_py)
    }

    /// Return True if ``other`` is a repository at the same location.
    ///
    /// This may return False even when both objects access the same physical
    /// repository via different URLs.
    ///
    /// Args:
    ///     other: Another repository object.
    fn has_same_location(&self, other: Py<PyAny>) -> PyResult<bool> {
        self.0.has_same_location(&other).map_err(err_to_py)
    }

    /// Return True if the repository is flagged as a shared repository.
    fn is_shared(&self) -> PyResult<bool> {
        self.0.is_shared().map_err(err_to_py)
    }

    /// Return True if the repository supports rich root data.
    fn supports_rich_root(&self) -> PyResult<bool> {
        self.0.supports_rich_root().map_err(err_to_py)
    }

    /// Return the current transaction of the repository's control files.
    fn get_transaction(&self) -> PyResult<Py<PyAny>> {
        self.0.get_transaction().map_err(err_to_py)
    }

    /// Return True if new branches in this repository get working trees.
    fn make_working_trees(&self) -> PyResult<bool> {
        self.0.make_working_trees().map_err(err_to_py)
    }

    /// Set whether new branches in this repository get working trees.
    ///
    /// Only applies to branches that use this repository. The default is True.
    ///
    /// Args:
    ///     new_value: True to create working trees, False to not create them.
    fn set_make_working_trees(&mut self, new_value: bool) -> PyResult<()> {
        self.0.set_make_working_trees(new_value).map_err(err_to_py)
    }

    /// Return the ids of all revisions in the repository.
    ///
    /// Code should generally work on the graph reachable from a particular
    /// revision instead, as this is linear in the size of the history.
    ///
    /// Returns:
    ///     A list of revision ids, as bytes.
    fn all_revision_ids<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyBytes>>> {
        Ok(self
            .0
            .all_revision_ids()
            .map_err(err_to_py)?
            .into_iter()
            .map(|r| PyBytes::new(py, r.as_bytes()))
            .collect())
    }

    /// Return True if the repository has a copy of a revision.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    fn has_revision(&self, revision_id: Vec<u8>) -> PyResult<bool> {
        self.0
            .has_revision(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return which of the given revisions the repository has.
    ///
    /// Args:
    ///     revision_ids: The revision ids to look up, as a list of bytes.
    ///
    /// Returns:
    ///     A list of the revision ids that are present, as bytes, in no
    ///     particular order.
    fn has_revisions<'py>(
        &self,
        py: Python<'py>,
        revision_ids: Vec<Vec<u8>>,
    ) -> PyResult<Vec<Bound<'py, PyBytes>>> {
        let revids = revision_ids
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        Ok(self
            .0
            .has_revisions(&revids)
            .map_err(err_to_py)?
            .into_iter()
            .map(|r| PyBytes::new(py, r.as_bytes()))
            .collect())
    }

    /// Return the Revision object for a revision.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///
    /// Returns:
    ///     A ``Revision`` object.
    ///
    /// Raises:
    ///     NoSuchRevision: If the repository does not have the revision.
    fn get_revision(&self, revision_id: Vec<u8>) -> PyResult<Py<PyAny>> {
        self.0
            .get_revision(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return the Revision objects for several revisions.
    ///
    /// Args:
    ///     revision_ids: The revision ids, as a list of bytes.
    ///
    /// Returns:
    ///     A list of Revision objects, in the same order as ``revision_ids``.
    ///
    /// Raises:
    ///     NoSuchRevision: If any of the revisions is not present.
    fn get_revisions(&self, revision_ids: Vec<Vec<u8>>) -> PyResult<Py<PyAny>> {
        let revids = revision_ids
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        self.0.get_revisions(&revids).map_err(err_to_py)
    }

    /// Iterate over the Revision objects for several revisions.
    ///
    /// Args:
    ///     revision_ids: The revision ids, as a list of bytes.
    ///
    /// Returns:
    ///     An iterator of ``(revision_id, revision)`` tuples, not necessarily
    ///     in the order requested. Revisions that are not present are
    ///     yielded as ``(revision_id, None)``.
    fn iter_revisions(&self, revision_ids: Vec<Vec<u8>>) -> PyResult<Py<PyAny>> {
        let revids = revision_ids
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        self.0.iter_revisions(&revids).map_err(err_to_py)
    }

    /// Return the delta of a revision against its left-hand parent.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///
    /// Returns:
    ///     A TreeDelta.
    ///
    /// Raises:
    ///     NoSuchRevision: If the repository does not have the revision.
    fn get_revision_delta(&self, revision_id: Vec<u8>) -> PyResult<Py<PyAny>> {
        self.0
            .get_revision_delta(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return the revision id for a revno, given a later revision.
    ///
    /// The left-hand history is walked back from ``known_pair``.
    ///
    /// Args:
    ///     revno: The revision number to look up.
    ///     known_pair: A ``(revno, revision_id)`` tuple for a revision later
    ///         in the same left-hand history.
    ///
    /// Returns:
    ///     ``(True, revision_id)`` if the revno was found, or
    ///     ``(False, (closest_revno, closest_revision_id))`` if the available
    ///     history ran out before reaching it.
    ///
    /// Raises:
    ///     RevnoOutOfBounds: If ``revno`` is greater than the known revno.
    ///     NoSuchRevision: If the known revision is not present.
    fn get_rev_id_for_revno(&self, revno: i64, known_pair: (u64, Vec<u8>)) -> PyResult<Py<PyAny>> {
        let (known_revno, known_revid) = known_pair;
        self.0
            .get_rev_id_for_revno(revno, (known_revno, RevisionId::from(known_revid)))
            .map_err(err_to_py)
    }

    /// Return the parents of each of the given revisions.
    ///
    /// Args:
    ///     revision_ids: The revision ids to look up, as a list of bytes.
    ///
    /// Returns:
    ///     A dict mapping each revision id the repository has to a tuple of
    ///     its parent revision ids. Revisions it does not have are left out.
    ///     A revision without parents maps to ``(b'null:',)``.
    fn get_parent_map(&self, revision_ids: Vec<Vec<u8>>) -> PyResult<Py<PyAny>> {
        let revids = revision_ids
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        self.0.get_parent_map(&revids).map_err(err_to_py)
    }

    /// Return a KnownGraph for the given revisions and their ancestors.
    ///
    /// Args:
    ///     revision_ids: The revision ids, as a list of bytes.
    fn get_known_graph_ancestry(&self, revision_ids: Vec<Vec<u8>>) -> PyResult<Py<PyAny>> {
        let revids = revision_ids
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        self.0.get_known_graph_ancestry(&revids).map_err(err_to_py)
    }

    /// Return a Graph for walking the revision history of this repository.
    ///
    /// Args:
    ///     other_repository: If given and at a different location, its
    ///         revisions are consulted as well.
    #[pyo3(signature = (other_repository=None))]
    fn get_graph(&self, other_repository: Option<Py<PyAny>>) -> PyResult<Py<PyAny>> {
        self.0
            .get_graph(other_repository.as_ref())
            .map_err(err_to_py)
    }

    /// Return a graph for walking the history of file versions.
    fn get_file_graph(&self) -> PyResult<Py<PyAny>> {
        self.0.get_file_graph().map_err(err_to_py)
    }

    /// Return the tree of a revision.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes. ``b'null:'`` gives the
    ///         empty tree.
    ///
    /// Returns:
    ///     A RevisionTree.
    ///
    /// Raises:
    ///     NoSuchRevision: If the repository does not have the revision.
    fn revision_tree(&self, revision_id: Vec<u8>) -> PyResult<Py<PyAny>> {
        self.0
            .revision_tree(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return the trees of several revisions.
    ///
    /// Args:
    ///     revision_ids: The revision ids, as a list of bytes. They may not
    ///         include ``b'null:'``.
    ///
    /// Returns:
    ///     A list of RevisionTree objects.
    fn revision_trees(&self, revision_ids: Vec<Vec<u8>>) -> PyResult<Py<PyAny>> {
        let revids = revision_ids
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        self.0.revision_trees(&revids).map_err(err_to_py)
    }

    /// Iterate over the contents of file versions.
    ///
    /// Files are not necessarily returned in the order they were requested.
    ///
    /// Args:
    ///     desired_files: A list of ``(file_id, revision_id, identifier)``
    ///         tuples, where ``file_id`` and ``revision_id`` are bytes and
    ///         ``identifier`` is any value that identifies the file version to
    ///         the caller.
    ///
    /// Returns:
    ///     An iterator of ``(identifier, bytes_iterator)`` pairs, where
    ///     ``bytes_iterator`` yields the file's content as chunks of bytes.
    fn iter_files_bytes(
        &self,
        py: Python<'_>,
        desired_files: Vec<(Vec<u8>, Vec<u8>, Py<PyAny>)>,
    ) -> PyResult<Py<PyAny>> {
        let files: Vec<(RevisionId, RevisionId, Py<PyAny>)> = desired_files
            .into_iter()
            .map(|(fid, rev, id)| {
                (
                    RevisionId::from(fid),
                    RevisionId::from(rev),
                    id.clone_ref(py),
                )
            })
            .collect();
        self.0.iter_files_bytes(&files).map_err(err_to_py)
    }

    /// Return True if the repository has a signature for a revision.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    fn has_signature_for_revision_id(&self, revision_id: Vec<u8>) -> PyResult<bool> {
        self.0
            .has_signature_for_revision_id(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return the signature text stored for a revision.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///
    /// Returns:
    ///     The signature, as bytes.
    ///
    /// Raises:
    ///     NoSuchRevision: If there is no signature for the revision.
    fn get_signature_text<'py>(
        &self,
        py: Python<'py>,
        revision_id: Vec<u8>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        self.0
            .get_signature_text(&RevisionId::from(revision_id))
            .map(|s| PyBytes::new(py, &s))
            .map_err(err_to_py)
    }

    /// Store a signature text for a revision.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///     signature: The signature text, as bytes.
    fn add_signature_text(&mut self, revision_id: Vec<u8>, signature: &[u8]) -> PyResult<()> {
        self.0
            .add_signature_text(&RevisionId::from(revision_id), signature)
            .map_err(err_to_py)
    }

    /// Sign a revision with GPG and store the signature.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///     gpg_strategy: The ``breezy.gpg.GPGStrategy`` to sign with.
    fn sign_revision(&mut self, revision_id: Vec<u8>, gpg_strategy: Py<PyAny>) -> PyResult<()> {
        self.0
            .sign_revision(&RevisionId::from(revision_id), &gpg_strategy)
            .map_err(err_to_py)
    }

    /// Verify the signature on a revision.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///     gpg_strategy: The ``breezy.gpg.GPGStrategy`` to verify with.
    ///
    /// Returns:
    ///     A ``(result, key)`` tuple, where ``result`` is
    ///     ``breezy.gpg.SIGNATURE_VALID`` or one of the other
    ///     ``breezy.gpg.SIGNATURE_*`` values.
    fn verify_revision_signature(
        &self,
        revision_id: Vec<u8>,
        gpg_strategy: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        self.0
            .verify_revision_signature(&RevisionId::from(revision_id), &gpg_strategy)
            .map_err(err_to_py)
    }

    /// Return True if there is an open write group.
    fn is_in_write_group(&self) -> PyResult<bool> {
        self.0.is_in_write_group().map_err(err_to_py)
    }

    /// Start a write group in the repository.
    ///
    /// Data can only be inserted into a repository inside a write group. The
    /// repository must be write-locked. End the write group with
    /// ``commit_write_group``, ``abort_write_group`` or
    /// ``suspend_write_group`` before unlocking.
    ///
    /// Raises:
    ///     NotWriteLocked: If the repository is not write-locked.
    ///     BzrError: If a write group is already open.
    fn start_write_group(&mut self) -> PyResult<()> {
        self.0.start_write_group().map_err(err_to_py)
    }

    /// Commit the data inserted in the current write group.
    ///
    /// Returns:
    ///     A hint to pass to ``pack``, as a list of str, or None.
    ///
    /// Raises:
    ///     BzrError: If the repository was unlocked or relocked since the
    ///         write group was started.
    fn commit_write_group(&mut self) -> PyResult<Option<Py<PyAny>>> {
        self.0.commit_write_group().map_err(err_to_py)
    }

    /// Abort the current write group.
    ///
    /// This is not a rollback: data already handed to the repository may still
    /// end up in it.
    ///
    /// Args:
    ///     suppress_errors: If True, errors raised while aborting are logged
    ///         rather than raised.
    #[pyo3(signature = (suppress_errors=false))]
    fn abort_write_group(&mut self, suppress_errors: bool) -> PyResult<()> {
        self.0.abort_write_group(suppress_errors).map_err(err_to_py)
    }

    /// Re-read data from disk to pick up changes made by other instances.
    ///
    /// Raises:
    ///     IsInWriteGroupError: If called inside a write group and the format
    ///         does not support refreshing there.
    fn refresh_data(&mut self) -> PyResult<()> {
        self.0.refresh_data().map_err(err_to_py)
    }

    /// Fetch the content needed for a revision from another repository.
    ///
    /// May not be used while this repository is in a write group.
    ///
    /// Args:
    ///     source: The repository to fetch from.
    ///     revision_id: The revision id to fetch, as bytes. If None, all
    ///         content is fetched.
    ///     find_ghosts: If True, also fetch revisions that are ghosts in this
    ///         repository but present in ``source``.
    ///     lossy: If True, discard data that can not be represented in this
    ///         repository's format, when fetching into a foreign VCS.
    ///
    /// Returns:
    ///     A FetchResult.
    #[pyo3(signature = (source, revision_id=None, find_ghosts=false, lossy=false))]
    fn fetch(
        &mut self,
        source: Py<PyAny>,
        revision_id: Option<Vec<u8>>,
        find_ghosts: bool,
        lossy: bool,
    ) -> PyResult<Py<PyAny>> {
        let rev = revision_id.map(RevisionId::from);
        self.0
            .fetch(&source, rev.as_ref(), find_ghosts, lossy)
            .map_err(err_to_py)
    }

    /// Find the revisions another repository has that this one does not.
    ///
    /// Args:
    ///     other: The repository to compare with.
    ///     find_ghosts: If True, also search for revisions that are ghosts in
    ///         this repository.
    ///     revision_ids: If not None, only revisions in the ancestry of these
    ///         revision ids (a list of bytes) are considered; they must exist
    ///         in ``other``.
    ///     if_present_ids: Like ``revision_ids``, but ids that are not present
    ///         in ``other`` are ignored.
    ///     limit: If not None, the maximum number of revisions to return.
    ///
    /// Returns:
    ///     A search result describing the missing revisions.
    #[pyo3(signature = (other, find_ghosts=true, revision_ids=None, limit=None))]
    fn search_missing_revision_ids(
        &self,
        other: Py<PyAny>,
        find_ghosts: bool,
        revision_ids: Option<Vec<Vec<u8>>>,
        limit: Option<u64>,
    ) -> PyResult<Py<PyAny>> {
        let revids = revision_ids.map(|r| r.into_iter().map(RevisionId::from).collect::<Vec<_>>());
        self.0
            .search_missing_revision_ids(&other, find_ghosts, revids.as_deref(), limit)
            .map_err(err_to_py)
    }

    /// Copy the content of this repository into another repository.
    ///
    /// This is destructive; do not use it on an existing repository with
    /// content.
    ///
    /// Args:
    ///     destination: The repository to copy into.
    ///     revision_id: If given, only copy the ancestry of this revision id
    ///         (bytes).
    #[pyo3(signature = (destination, revision_id=None))]
    fn copy_content_into(
        &self,
        destination: Py<PyAny>,
        revision_id: Option<Vec<u8>>,
    ) -> PyResult<()> {
        let rev = revision_id.map(RevisionId::from);
        self.0
            .copy_content_into(&destination, rev.as_ref())
            .map_err(err_to_py)
    }

    /// Clone this repository into a control directory, keeping its format.
    ///
    /// Repository settings such as whether it is shared are copied too.
    ///
    /// Args:
    ///     controldir: The control directory to create the new repository in.
    ///     revision_id: If given, only copy the ancestry of this revision id
    ///         (bytes).
    ///
    /// Returns:
    ///     The new repository.
    #[pyo3(signature = (controldir, revision_id=None))]
    fn clone(&self, controldir: Py<PyAny>, revision_id: Option<Vec<u8>>) -> PyResult<Py<PyAny>> {
        let rev = revision_id.map(RevisionId::from);
        self.0.clone(&controldir, rev.as_ref()).map_err(err_to_py)
    }

    /// Create a new repository for new development, fetching history into it.
    ///
    /// Unlike ``clone``, the settings of this repository are not copied.
    ///
    /// Args:
    ///     to_bzrdir: The control directory to create the new repository in.
    ///     revision_id: If given, only fetch the ancestry of this revision id
    ///         (bytes).
    ///
    /// Returns:
    ///     The new repository.
    #[pyo3(signature = (to_bzrdir, revision_id=None))]
    fn sprout(&self, to_bzrdir: Py<PyAny>, revision_id: Option<Vec<u8>>) -> PyResult<Py<PyAny>> {
        let rev = revision_id.map(RevisionId::from);
        self.0.sprout(&to_bzrdir, rev.as_ref()).map_err(err_to_py)
    }

    /// Compress the data within the repository.
    ///
    /// Formats that do not support packing do nothing.
    ///
    /// Args:
    ///     hint: A hint returned by ``commit_write_group``, naming the parts
    ///         of the repository to pack. If None, the whole repository is
    ///         packed. Out of date hints are ignored.
    ///     clean_obsolete_packs: If True, remove obsolete packs immediately
    ///         after packing.
    #[pyo3(signature = (hint=None, clean_obsolete_packs=false))]
    fn pack(&mut self, hint: Option<Py<PyAny>>, clean_obsolete_packs: bool) -> PyResult<()> {
        self.0
            .pack(hint.as_ref(), clean_obsolete_packs)
            .map_err(err_to_py)
    }

    /// Reconcile the repository, fixing inconsistencies in its data.
    ///
    /// Args:
    ///     other: Not used by the bzr formats.
    ///     thorough: If True, do a more expensive check of all data.
    ///
    /// Returns:
    ///     A ReconcileResult.
    #[pyo3(signature = (other=None, thorough=false))]
    fn reconcile(&mut self, other: Option<Py<PyAny>>, thorough: bool) -> PyResult<Py<PyAny>> {
        self.0
            .reconcile(other.as_ref(), thorough)
            .map_err(err_to_py)
    }

    /// Check the consistency of the history of the given revisions.
    ///
    /// Args:
    ///     revision_ids: A non-empty list of revision ids (bytes) whose
    ///         ancestry is checked, typically the tip of a branch.
    ///     check_repo: If False, do not check the repository contents.
    ///
    /// Returns:
    ///     A check result object; call its ``report_results`` method to show
    ///     the findings.
    #[pyo3(signature = (revision_ids=None, check_repo=true))]
    fn check(&self, revision_ids: Option<Vec<Vec<u8>>>, check_repo: bool) -> PyResult<Py<PyAny>> {
        let revids = revision_ids.map(|r| r.into_iter().map(RevisionId::from).collect::<Vec<_>>());
        self.0
            .check(revids.as_deref(), check_repo)
            .map_err(err_to_py)
    }

    /// Gather statistics about the repository and a revision.
    ///
    /// Args:
    ///     revid: The revision id to gather statistics for, as bytes. If None,
    ///         no revision-specific statistics are gathered.
    ///     committers: If True, count the committers in the ancestry of
    ///         ``revid``.
    ///
    /// Returns:
    ///     A dict of statistics. Depending on the arguments and the format it
    ///     may contain ``committers`` (the number of committers), ``firstrev``
    ///     and ``latestrev`` (``(timestamp, timezone)`` tuples for the oldest
    ///     and newest revision in the ancestry of ``revid``) and ``revisions``
    ///     (the number of revisions in the repository).
    #[pyo3(signature = (revid=None, committers=None))]
    fn gather_stats(
        &self,
        py: Python<'_>,
        revid: Option<Vec<u8>>,
        committers: Option<bool>,
    ) -> PyResult<Py<PyAny>> {
        let rev = revid.map(RevisionId::from);
        let stats = self
            .0
            .gather_stats(rev.as_ref(), committers)
            .map_err(err_to_py)?;
        let dict = pyo3::types::PyDict::new(py);
        for (k, v) in stats {
            dict.set_item(k, v.bind(py))?;
        }
        Ok(dict.into_any().unbind())
    }

    /// Add a repository to look up data in that is not held locally.
    ///
    /// Args:
    ///     repository: The fallback repository.
    fn add_fallback_repository(&mut self, repository: Py<PyAny>) -> PyResult<()> {
        self.0
            .add_fallback_repository(&repository)
            .map_err(err_to_py)
    }

    /// Obtain a CommitBuilder for creating a new revision in this repository.
    ///
    /// Args:
    ///     branch: The Branch the commit is for.
    ///     parents: The parent revision ids of the new revision, as a list of
    ///         bytes.
    ///     config_stack: The configuration stack to use.
    ///     timestamp: The commit timestamp, as seconds since the epoch. If
    ///         None, the current time is used.
    ///     timezone: The offset of the committer's timezone from UTC, in
    ///         seconds.
    ///     committer: The committer, as a str. If None, it is taken from the
    ///         configuration.
    ///     revprops: A dict of extra revision properties.
    ///     revision_id: The revision id to use for the new revision, as bytes.
    ///         If None, one is generated.
    ///     lossy: If True, discard data that can not be represented when
    ///         committing to a foreign VCS.
    ///
    /// Returns:
    ///     A CommitBuilder.
    #[pyo3(signature = (branch, parents, config_stack, timestamp=None, timezone=None, committer=None, revprops=None, revision_id=None, lossy=false))]
    #[allow(clippy::too_many_arguments)]
    fn get_commit_builder(
        &mut self,
        branch: Py<PyAny>,
        parents: Vec<Vec<u8>>,
        config_stack: Py<PyAny>,
        timestamp: Option<f64>,
        timezone: Option<i32>,
        committer: Option<&str>,
        revprops: Option<Py<PyAny>>,
        revision_id: Option<Vec<u8>>,
        lossy: bool,
    ) -> PyResult<Py<PyAny>> {
        let parents = parents
            .into_iter()
            .map(RevisionId::from)
            .collect::<Vec<_>>();
        let rev = revision_id.map(RevisionId::from);
        self.0
            .get_commit_builder(
                &branch,
                &parents,
                &config_stack,
                timestamp,
                timezone,
                committer,
                revprops.as_ref(),
                rev.as_ref(),
                lossy,
            )
            .map_err(err_to_py)
    }
}
