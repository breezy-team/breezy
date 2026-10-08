use bazaar::RevisionId;
use std::collections::HashMap;

/// A handle to an opaque Python object.
///
/// A number of repository methods return rich domain objects (revisions,
/// commit builders, trees, deltas, graphs, transactions, results, ...) that
/// do not yet have native Rust equivalents. Because the primary implementor is
/// `PyRepository`, which delegates to a Python repository, such values are
/// represented as a handle to the underlying Python object.
#[cfg(feature = "pyo3")]
pub type PyObject = pyo3::Py<pyo3::PyAny>;

/// A handle to an opaque Python object (non-pyo3 fallback).
#[cfg(not(feature = "pyo3"))]
pub type PyObject = ();

/// Errors that can occur when working with repositories.
#[derive(Debug)]
pub enum Error {
    /// The requested revision does not exist.
    NoSuchRevision(RevisionId),
    /// The operation is not supported by this repository.
    UnsupportedOperation(String),
    /// A generic error occurred.
    Other(String),
    /// A Python exception raised by a Python-backed implementation, kept so
    /// it reaches Python again with its type.
    #[cfg(feature = "pyo3")]
    Python(pyo3::PyErr),
}

#[cfg(feature = "pyo3")]
pyo3::import_exception!(breezy.errors, NoSuchRevision);

impl Error {
    /// Whether the revision asked for does not exist, as Rust's
    /// [`Error::NoSuchRevision`] or Python's ``NoSuchRevision``.
    pub fn is_no_such_revision(&self) -> bool {
        match self {
            Error::NoSuchRevision(_) => true,
            #[cfg(feature = "pyo3")]
            Error::Python(e) => pyo3::Python::attach(|py| e.is_instance_of::<NoSuchRevision>(py)),
            _ => false,
        }
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            #[cfg(feature = "pyo3")]
            Error::Python(e) => write!(f, "{e}"),
            Error::NoSuchRevision(revid) => write!(f, "No such revision: {}", revid),
            Error::UnsupportedOperation(msg) => write!(f, "Unsupported operation: {}", msg),
            Error::Other(msg) => write!(f, "{}", msg),
        }
    }
}

impl std::error::Error for Error {}

/// A trait representing a version control repository.
///
/// A repository stores the complete history of a project: revisions,
/// inventories, file texts and signatures. This mirrors the Python
/// `breezy.repository.Repository` class. Methods that return rich Python-only
/// domain objects use [`PyObject`].
///
pub trait Repository {
    /// The Python repository this one wraps, if it wraps one.
    ///
    /// Bindings use this to hand a Python-backed repository back to Python
    /// as the original object rather than as a Rust object proxying to it.
    fn python_object(&self) -> Option<&PyObject> {
        None
    }

    /// The branches this repository serves; with `using`, those in control
    /// directories below it too.
    fn find_branches(
        &self,
        using: bool,
    ) -> Result<Vec<Box<dyn crate::branch::Branch + Send + Sync>>, Error>;

    /// The URL of the repository, as the user refers to it.
    fn base(&self) -> Result<String, Error>;

    /// The URL of the directory holding the repository's control directory.
    fn user_url(&self) -> Result<String, Error>;

    /// The URL of the repository's own control files.
    fn control_url(&self) -> Result<String, Error>;

    /// The control directory the repository lives in.
    fn controldir(&self) -> Result<Box<dyn crate::controldir::ControlDir>, Error>;

    /// Whether the repository can be read at arbitrary positions cheaply.
    fn supports_random_access(&self) -> Result<bool, Error>;

    /// The repository's lockable control files, as a Python object.
    fn control_files(&self) -> Result<PyObject, Error>;

    // Transports

    /// The transport for user-visible data.
    ///
    /// Returns a Python transport object.
    fn user_transport(&self) -> Result<PyObject, Error>;

    /// The transport for control data.
    ///
    /// Returns a Python transport object.
    fn control_transport(&self) -> Result<PyObject, Error>;

    // Locking

    /// Break a lock held by another instance.
    fn break_lock(&self) -> Result<(), crate::lock::Error>;

    /// Whether the repository is locked.
    fn is_locked(&self) -> Result<bool, Error>;

    /// Whether the repository is write-locked.
    fn is_write_locked(&self) -> Result<bool, Error>;

    /// Lock the repository for writing; with `token`, take over the
    /// physical lock it names.
    fn lock_write(
        &self,
        token: Option<&[u8]>,
    ) -> Result<crate::lock::WriteLockRef, crate::lock::Error>;

    /// Lock the repository for reading.
    fn lock_read(&self) -> Result<crate::lock::ReadLockRef, crate::lock::Error>;

    /// Release one lock on the repository.
    fn unlock(&self) -> Result<(), crate::lock::Error>;

    /// Whether the physical lock is held, by anyone.
    fn get_physical_lock_status(&self) -> Result<bool, crate::lock::Error>;

    /// Keep the physical lock in place on unlock.
    fn leave_lock_in_place(&self) -> Result<(), crate::lock::Error>;

    /// Release the physical lock on unlock.
    fn dont_leave_lock_in_place(&self) -> Result<(), crate::lock::Error>;

    // Location and identity

    /// Whether this repository is at the same location as `other`.
    fn has_same_location(&self, other: &PyObject) -> Result<bool, Error>;

    /// Whether the repository is shared.
    fn is_shared(&self) -> Result<bool, Error>;

    /// Whether the repository supports rich root data.
    fn supports_rich_root(&self) -> Result<bool, Error>;

    /// Return the current transaction.
    ///
    /// Returns a Python transaction object.
    fn get_transaction(&self) -> Result<PyObject, Error>;

    /// Whether new branches should make working trees.
    fn make_working_trees(&self) -> Result<bool, Error>;

    /// Set whether new branches should make working trees.
    fn set_make_working_trees(&mut self, new_value: bool) -> Result<(), Error>;

    // Revisions

    /// Return the ids of all revisions in the repository.
    fn all_revision_ids(&self) -> Result<Vec<RevisionId>, Error>;

    /// Whether the repository has the given revision.
    fn has_revision(&self, revision_id: &RevisionId) -> Result<bool, Error>;

    /// Return the subset of `revision_ids` present in the repository.
    fn has_revisions(&self, revision_ids: &[RevisionId]) -> Result<Vec<RevisionId>, Error>;

    /// Return the revision object for `revision_id`.
    ///
    /// Returns a Python `Revision`.
    fn get_revision(&self, revision_id: &RevisionId) -> Result<PyObject, Error>;

    /// Return the revision objects for `revision_ids`.
    ///
    /// Returns a Python list of `Revision` objects.
    fn get_revisions(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error>;

    /// Iterate `(revision_id, revision)` pairs.
    ///
    /// Returns a Python iterator; absent revisions appear as `(revid, None)`.
    fn iter_revisions(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error>;

    /// Return the delta for `revision_id` against its left predecessor.
    ///
    /// Returns a Python `TreeDelta`.
    fn get_revision_delta(&self, revision_id: &RevisionId) -> Result<PyObject, Error>;

    /// The deltas of the Python `revisions` objects against their first
    /// parents, limited to `specific_files` when given.
    fn get_revision_deltas(
        &self,
        revisions: &[PyObject],
        specific_files: Option<&[&str]>,
    ) -> Result<Vec<PyObject>, Error>;

    /// The Python revision object for `revision_id`, read without the
    /// checks reconciliation would trip over.
    fn get_revision_reconcile(&self, revision_id: &RevisionId) -> Result<PyObject, Error>;

    /// Return the revision id for a revno, given a known later `(revno, revid)`.
    ///
    /// Returns a Python `(found, result)` tuple: `(True, revision_id)` when the
    /// revno was reached, or `(False, (closest_revno, closest_revid))` when the
    /// history ran out first. The shape of the second element differs between
    /// the two cases, so the raw tuple is returned as a Python object.
    fn get_rev_id_for_revno(
        &self,
        revno: i64,
        known_pair: (u64, RevisionId),
    ) -> Result<PyObject, Error>;

    /// Return the parent map for `revision_ids`.
    ///
    /// Returns a Python dict mapping revision id to its parents.
    fn get_parent_map(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error>;

    /// Return the known graph ancestry of `revision_ids`.
    ///
    /// Returns a Python graph object.
    fn get_known_graph_ancestry(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error>;

    /// Return the graph walker for this repository.
    ///
    /// Returns a Python graph object.
    fn get_graph(&self, other_repository: Option<&PyObject>) -> Result<PyObject, Error>;

    /// Return the graph walker for files.
    ///
    /// Returns a Python graph object.
    fn get_file_graph(&self) -> Result<PyObject, Error>;

    // Trees, inventories and texts

    /// Return the tree for `revision_id`.
    ///
    /// Returns a Python tree object.
    fn revision_tree(&self, revision_id: &RevisionId) -> Result<PyObject, Error>;

    /// Return the trees for `revision_ids`.
    ///
    /// Returns a Python iterator of tree objects.
    fn revision_trees(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error>;

    /// Iterate file versions for `desired_files`.
    ///
    /// `desired_files` is a list of `(file_id, revision_id, identifier)`.
    /// Returns a Python iterator of `(identifier, bytes_iterator)` pairs.
    fn iter_files_bytes(
        &self,
        desired_files: &[(RevisionId, RevisionId, PyObject)],
    ) -> Result<PyObject, Error>;

    // Signatures

    /// Whether a signature exists for `revision_id`.
    fn has_signature_for_revision_id(&self, revision_id: &RevisionId) -> Result<bool, Error>;

    /// Return the signature text for `revision_id`.
    fn get_signature_text(&self, revision_id: &RevisionId) -> Result<Vec<u8>, Error>;

    /// Store signature text for `revision_id`.
    fn add_signature_text(
        &mut self,
        revision_id: &RevisionId,
        signature: &[u8],
    ) -> Result<(), Error>;

    /// Store `plaintext` signed with the Python GPG strategy as the signature
    /// of `revision_id`.
    fn store_revision_signature(
        &mut self,
        gpg_strategy: &PyObject,
        plaintext: &[u8],
        revision_id: &RevisionId,
    ) -> Result<(), Error>;

    /// Verify the signatures of `revision_ids` with the Python GPG strategy,
    /// giving a Python ``(revision_id, result, key)`` tuple for each.
    fn verify_revision_signatures(
        &self,
        revision_ids: &[RevisionId],
        gpg_strategy: &PyObject,
    ) -> Result<Vec<PyObject>, Error>;

    /// Sign `revision_id` using a GPG strategy.
    fn sign_revision(
        &mut self,
        revision_id: &RevisionId,
        gpg_strategy: &PyObject,
    ) -> Result<(), Error>;

    /// Verify the signature on `revision_id`.
    ///
    /// Returns a Python verification result.
    fn verify_revision_signature(
        &self,
        revision_id: &RevisionId,
        gpg_strategy: &PyObject,
    ) -> Result<PyObject, Error>;

    // Write groups

    /// Whether a write group is open.
    fn is_in_write_group(&self) -> Result<bool, Error>;

    /// Start a write group.
    fn start_write_group(&mut self) -> Result<(), Error>;

    /// Commit the current write group.
    ///
    /// Returns an optional Python pack hint.
    fn commit_write_group(&mut self) -> Result<Option<PyObject>, Error>;

    /// Abort the current write group.
    fn abort_write_group(&mut self, suppress_errors: bool) -> Result<(), Error>;

    /// Suspend the current write group, returning the tokens that resume it.
    fn suspend_write_group(&mut self) -> Result<Vec<String>, Error>;

    /// Resume the write group suspended with `tokens`.
    fn resume_write_group(&mut self, tokens: &[String]) -> Result<(), Error>;

    /// Re-read data to synchronise with disk.
    fn refresh_data(&mut self) -> Result<(), Error>;

    // Data transfer and maintenance

    /// Fetch content needed to construct `revision_id` from `source`.
    ///
    /// Returns a Python `FetchResult`.
    fn fetch(
        &mut self,
        source: &PyObject,
        revision_id: Option<&RevisionId>,
        find_ghosts: bool,
        lossy: bool,
    ) -> Result<PyObject, Error>;

    /// Return the revision ids `other` has that this repository does not.
    ///
    /// Returns a Python search result.
    fn search_missing_revision_ids(
        &self,
        other: &PyObject,
        find_ghosts: bool,
        revision_ids: Option<&[RevisionId]>,
        if_present_ids: Option<&[RevisionId]>,
        limit: Option<u64>,
    ) -> Result<PyObject, Error>;

    /// Copy all content into `destination`.
    fn copy_content_into(
        &self,
        destination: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<(), Error>;

    /// Clone the repository into `controldir`.
    ///
    /// Returns a Python repository object.
    fn clone(
        &self,
        controldir: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<PyObject, Error>;

    /// Create a descendent repository for new development.
    ///
    /// Returns a Python repository object.
    fn sprout(
        &self,
        to_bzrdir: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<PyObject, Error>;

    /// Compress data within the repository.
    fn pack(&mut self, hint: Option<&PyObject>, clean_obsolete_packs: bool) -> Result<(), Error>;

    /// Reconcile the repository, fixing consistency problems.
    ///
    /// Returns a Python `ReconcileResult`.
    fn reconcile(&mut self, other: Option<&PyObject>, thorough: bool) -> Result<PyObject, Error>;

    /// Check the consistency of the repository history.
    ///
    /// Returns a Python check result.
    fn check(
        &self,
        revision_ids: Option<&[RevisionId]>,
        check_repo: bool,
    ) -> Result<PyObject, Error>;

    /// Gather repository/revision statistics.
    ///
    /// Returns a map of statistic names to Python values.
    fn gather_stats(
        &self,
        revid: Option<&RevisionId>,
        committers: Option<bool>,
    ) -> Result<HashMap<String, PyObject>, Error>;

    /// Add a fallback repository for looking up non-local data.
    fn add_fallback_repository(&mut self, repository: &PyObject) -> Result<(), Error>;

    /// Obtain a commit builder for this repository.
    ///
    /// Returns a Python `CommitBuilder`.
    #[allow(clippy::too_many_arguments)]
    fn get_commit_builder(
        &mut self,
        branch: &PyObject,
        parents: &[RevisionId],
        config_stack: &PyObject,
        timestamp: Option<f64>,
        timezone: Option<i32>,
        committer: Option<&str>,
        revprops: Option<&PyObject>,
        revision_id: Option<&RevisionId>,
        lossy: bool,
    ) -> Result<PyObject, Error>;
}

/// Open the repository at `location`, as ``Repository.open`` does.
pub fn open(location: &str) -> Result<crate::controldir::RepositoryRef, crate::controldir::Error> {
    crate::controldir::open(location)?.open_repository()
}

/// Create a repository in `controldir`, as ``Repository.create`` does.
///
/// Python initialises the default repository format there; the control
/// directory's own repository creation is the same for the formats in use.
pub fn create(
    controldir: &dyn crate::controldir::ControlDir,
) -> Result<crate::controldir::RepositoryRef, crate::controldir::Error> {
    controldir.create_repository(false)
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
