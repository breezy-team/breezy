use crate::tags::Tags;
use bazaar::RevisionId;

/// A handle to an opaque Python object.
///
/// A number of branch methods return rich domain objects (config stacks,
/// commit builders, trees, control directories, pull/push results, lock
/// results, ...) that do not yet have native Rust equivalents. Because the
/// primary implementor is `PyBranch`, which delegates to a Python branch,
/// such values are represented as a handle to the underlying Python object.
#[cfg(feature = "pyo3")]
pub type PyObject = pyo3::Py<pyo3::PyAny>;

/// A handle to an opaque Python object (non-pyo3 fallback).
#[cfg(not(feature = "pyo3"))]
pub type PyObject = ();

/// Errors that can occur when working with branches.
#[derive(Debug)]
pub enum Error {
    /// The requested revision does not exist.
    NoSuchRevision(RevisionId),
    /// The branch is not stacked but a stacked-on URL was requested.
    NotStacked,
    /// The operation requires a format upgrade.
    UpgradeRequired,
    /// Binding is not supported by this branch.
    BindingUnsupported,
    /// The operation is not supported by this branch.
    UnsupportedOperation(String),
    /// A generic error occurred.
    Other(String),
    /// A Python exception raised by a Python-backed implementation, kept so
    /// it reaches Python again with its type.
    #[cfg(feature = "pyo3")]
    Python(pyo3::PyErr),
}

#[cfg(feature = "pyo3")]
mod py_exceptions {
    pyo3::import_exception!(breezy.errors, NoSuchRevision);
}

impl Error {
    /// Whether the revision asked for does not exist, as Rust's
    /// [`Error::NoSuchRevision`] or Python's ``NoSuchRevision``.
    pub fn is_no_such_revision(&self) -> bool {
        match self {
            Error::NoSuchRevision(_) => true,
            #[cfg(feature = "pyo3")]
            Error::Python(e) => {
                pyo3::Python::attach(|py| e.is_instance_of::<py_exceptions::NoSuchRevision>(py))
            }
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
            Error::NotStacked => write!(f, "Branch is not stacked"),
            Error::UpgradeRequired => write!(f, "Upgrade required"),
            Error::BindingUnsupported => write!(f, "Binding is not supported"),
            Error::UnsupportedOperation(msg) => write!(f, "Unsupported operation: {}", msg),
            Error::Other(msg) => write!(f, "{}", msg),
        }
    }
}

impl std::error::Error for Error {}

/// A trait representing a version control branch.
///
/// This mirrors the Python `breezy.branch.Branch` class. Methods that return
/// rich Python-only domain objects use [`PyObject`]; methods with a trivial
/// constant default in Python are given a Rust default.
pub trait Branch {
    /// The Python branch this one wraps, if it wraps one.
    ///
    /// Bindings use this to hand a Python-backed branch back to Python as the
    /// original object rather than as a Rust object proxying to it.
    fn python_object(&self) -> Option<&PyObject> {
        None
    }

    // Properties and identity

    /// The name of this branch (the empty string for the default branch).
    fn name(&self) -> Result<String, Error>;

    /// The URL of the branch, as the user refers to it.
    fn base(&self) -> Result<String, Error>;

    /// The URL of the directory holding the branch's control directory.
    fn user_url(&self) -> Result<String, Error>;

    /// The URL of the branch's own control files.
    fn control_url(&self) -> Result<String, Error>;

    /// The repository holding the branch's revisions.
    fn repository(&self) -> Result<crate::controldir::RepositoryRef, Error>;

    /// The control directory the branch lives in.
    fn controldir(&self) -> Result<Box<dyn crate::controldir::ControlDir>, Error>;

    /// The transport for user files in the branch's control directory.
    ///
    /// Returns a Python transport object.
    fn user_transport(&self) -> Result<PyObject, Error>;

    /// Get the branch nickname.
    fn nick(&self) -> Result<String, Error>;

    /// Set the branch nickname.
    fn set_nick(&mut self, nick: &str) -> Result<(), Error>;

    // Locking

    /// Break a lock held by another instance.
    fn break_lock(&self) -> Result<(), crate::lock::Error>;

    /// Whether the branch is locked.
    fn is_locked(&self) -> Result<bool, Error>;

    /// Lock the branch, and its repository, for writing; with `token`,
    /// take over the physical lock it names.
    fn lock_write(
        &self,
        token: Option<&[u8]>,
    ) -> Result<crate::lock::WriteLockRef, crate::lock::Error>;

    /// Lock the branch, and its repository, for reading.
    fn lock_read(&self) -> Result<crate::lock::ReadLockRef, crate::lock::Error>;

    /// Release one lock on the branch.
    fn unlock(&self) -> Result<(), crate::lock::Error>;

    /// Return the current lock mode: `"r"`, `"w"`, or `None`.
    fn peek_lock_mode(&self) -> Result<Option<String>, Error>;

    /// Whether the physical lock is held, by anyone.
    fn get_physical_lock_status(&self) -> Result<bool, crate::lock::Error>;

    /// Keep the physical lock in place on unlock.
    fn leave_lock_in_place(&self) -> Result<(), crate::lock::Error>;

    /// Release the physical lock on unlock.
    fn dont_leave_lock_in_place(&self) -> Result<(), crate::lock::Error>;

    // Revision history

    /// Return the last revision id, or the null revision.
    fn last_revision(&self) -> Result<RevisionId, Error>;

    /// Return the `(revno, revision_id)` of the tip.
    fn last_revision_info(&self) -> Result<(u64, RevisionId), Error>;

    /// Set the branch's last revision to `(revno, revision_id)`.
    fn set_last_revision_info(&mut self, revno: u64, revision_id: &RevisionId)
        -> Result<(), Error>;

    /// Return the current revision number.
    fn revno(&self) -> Result<u64, Error>;

    /// Return the revno for a revision id.
    fn revision_id_to_revno(&self, revision_id: &RevisionId) -> Result<u64, Error>;

    /// Return the revision id for a revno.
    fn get_rev_id(&self, revno: i64) -> Result<RevisionId, Error>;

    /// Return the dotted revno for a revision id.
    fn revision_id_to_dotted_revno(&self, revision_id: &RevisionId) -> Result<Vec<i32>, Error>;

    /// Return the revision id for a dotted revno.
    fn dotted_revno_to_revision_id(&self, revno: &[i32]) -> Result<RevisionId, Error>;

    /// Return the cached `revision_id -> dotted revno` map.
    ///
    /// Returns a Python dict object.
    fn get_revision_id_to_revno_map(&self) -> Result<PyObject, Error>;

    /// Walk revisions in merge-sorted order.
    ///
    /// Returns a Python iterator.
    fn iter_merge_sorted_revisions(
        &self,
        start_revision_id: Option<&RevisionId>,
        stop_revision_id: Option<&RevisionId>,
        stop_rule: &str,
        direction: &str,
    ) -> Result<PyObject, Error>;

    /// Set the history tip to `revision_id`.
    fn generate_revision_history(
        &mut self,
        revision_id: &RevisionId,
        last_rev: Option<&RevisionId>,
        other_branch: Option<&PyObject>,
    ) -> Result<(), Error>;

    /// Import the last revision info and tags from `source`.
    fn import_last_revision_info_and_tags(
        &mut self,
        source: &PyObject,
        revno: u64,
        revid: &RevisionId,
        lossy: bool,
    ) -> Result<(u64, RevisionId), Error>;

    /// Validate a revno (0 is allowed).
    fn check_revno(&self, revno: i64) -> Result<(), Error>;

    /// Validate a revno (0 is not allowed).
    fn check_real_revno(&self, revno: i64) -> Result<(), Error>;

    /// Return the `(must_fetch, if_present_fetch)` head sets.
    fn heads_to_fetch(&self) -> Result<(Vec<RevisionId>, Vec<RevisionId>), Error>;

    // Configuration

    /// Return the branch configuration.
    ///
    /// Returns a Python `BranchConfig`.
    fn get_config(&self) -> Result<PyObject, Error>;

    /// Return the branch config stack.
    ///
    /// Returns a Python config `Stack`.
    fn get_config_stack(&self) -> Result<PyObject, Error>;

    /// Whether only appends are allowed to the branch history.
    fn get_append_revisions_only(&self) -> Result<bool, Error>;

    /// Set the append-revisions-only flag.
    fn set_append_revisions_only(&mut self, enabled: bool) -> Result<(), Error>;

    // Locations

    /// Return the parent (pull) location as a URL, if any.
    fn get_parent(&self) -> Result<Option<String>, Error>;

    /// Set the parent location.
    fn set_parent(&mut self, url: Option<&str>) -> Result<(), Error>;

    /// Return the push location, if any.
    fn get_push_location(&self) -> Result<Option<String>, Error>;

    /// Set the push location.
    fn set_push_location(&mut self, location: &str) -> Result<(), Error>;

    /// Return the submit location, if any.
    fn get_submit_branch(&self) -> Result<Option<String>, Error>;

    /// Set the submit location.
    fn set_submit_branch(&mut self, location: &str) -> Result<(), Error>;

    /// Return the public location, if any.
    fn get_public_branch(&self) -> Result<Option<String>, Error>;

    /// Set the public location.
    fn set_public_branch(&mut self, location: &str) -> Result<(), Error>;

    /// Return the preferred submission format, if any.
    fn get_child_submit_format(&self) -> Result<Option<String>, Error>;

    // Stacking

    /// Return the URL this branch is stacked against.
    fn get_stacked_on_url(&self) -> Result<String, Error>;

    /// Set the stacked-on URL.
    fn set_stacked_on_url(&mut self, url: Option<&str>) -> Result<(), Error>;

    // Binding

    /// Bind this branch to `other`.
    fn bind(&mut self, other: &PyObject) -> Result<(), Error>;

    /// Unbind this branch.
    fn unbind(&mut self) -> Result<(), Error>;

    /// Return the URL of the bound branch, if any.
    fn get_bound_location(&self) -> Result<Option<String>, Error>;

    /// Return the URL the branch used to be bound to, if any.
    fn get_old_bound_location(&self) -> Result<Option<String>, Error>;

    /// Return the bound master branch, if any.
    ///
    /// Returns a Python branch object.
    fn get_master_branch(&self) -> Result<Option<PyObject>, Error>;

    /// Sync with the master branch.
    fn update(&mut self) -> Result<(), Error>;

    // Tags

    /// Return the tags associated with the branch.
    fn tags(&self) -> Result<Box<dyn Tags>, Error>;

    /// Whether the branch supports tags.
    fn supports_tags(&self) -> Result<bool, Error>;

    /// Automatically determine a tag name for `revision_id`, if any.
    fn automatic_tag_name(&self, revision_id: &RevisionId) -> Result<Option<String>, Error>;

    // Data transfer

    /// Copy revisions from another branch.
    ///
    /// Returns a Python `FetchResult`.
    fn fetch(
        &mut self,
        from_branch: &PyObject,
        stop_revision: Option<&RevisionId>,
        limit: Option<u64>,
        lossy: bool,
    ) -> Result<PyObject, Error>;

    /// Mirror `source` into this branch.
    ///
    /// Returns a Python `PullResult`.
    fn pull(
        &mut self,
        source: &PyObject,
        overwrite: bool,
        stop_revision: Option<&RevisionId>,
    ) -> Result<PyObject, Error>;

    /// Mirror this branch into `target`.
    ///
    /// Returns a Python `PushResult`.
    fn push(
        &mut self,
        target: &PyObject,
        overwrite: bool,
        stop_revision: Option<&RevisionId>,
        lossy: bool,
    ) -> Result<PyObject, Error>;

    // Trees and commit

    /// Return the tree for the last revision.
    ///
    /// Returns a Python tree object.
    fn basis_tree(&self) -> Result<PyObject, Error>;

    /// Obtain a commit builder.
    ///
    /// Returns a Python `CommitBuilder`.
    #[allow(clippy::too_many_arguments)]
    fn get_commit_builder(
        &mut self,
        parents: &[RevisionId],
        timestamp: Option<f64>,
        timezone: Option<i32>,
        committer: Option<&str>,
        revprops: Option<&PyObject>,
        revision_id: Option<&RevisionId>,
        lossy: bool,
    ) -> Result<PyObject, Error>;

    /// Create an in-memory mutable tree.
    ///
    /// Returns a Python tree object.
    fn create_memorytree(&self) -> Result<PyObject, Error>;

    // Cloning and checkout

    /// Clone this branch into a control directory.
    ///
    /// Returns a Python branch object.
    fn clone(
        &self,
        to_controldir: &PyObject,
        revision_id: Option<&RevisionId>,
        name: Option<&str>,
    ) -> Result<PyObject, Error>;

    /// Start a new line of development in a control directory.
    ///
    /// Returns a Python branch object.
    fn sprout(
        &self,
        to_controldir: &PyObject,
        revision_id: Option<&RevisionId>,
        lossy: bool,
        name: Option<&str>,
    ) -> Result<PyObject, Error>;

    /// Copy this branch's content into `destination`.
    fn copy_content_into(
        &self,
        destination: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<(), Error>;

    /// Update references in `target` to point at this branch's content.
    fn update_references(&self, target: &PyObject) -> Result<(), Error>;

    /// Clone this branch and its control directory onto a transport.
    ///
    /// Returns a Python branch object.
    fn create_clone_on_transport(
        &self,
        to_transport: &PyObject,
        revision_id: Option<&RevisionId>,
        stacked_on: Option<&str>,
        create_prefix: bool,
        use_existing_dir: bool,
    ) -> Result<PyObject, Error>;

    /// Create a checkout.
    ///
    /// Returns a Python working tree object.
    fn create_checkout(
        &self,
        to_location: &str,
        revision_id: Option<&RevisionId>,
        lightweight: bool,
        hardlink: bool,
    ) -> Result<PyObject, Error>;

    // Consistency and maintenance

    /// Check branch consistency.
    ///
    /// Returns a Python `BranchCheckResult`.
    fn check(&self, refs: &PyObject) -> Result<PyObject, Error>;

    /// Reconcile the branch, fixing consistency problems.
    ///
    /// Returns a Python `ReconcileResult`.
    fn reconcile(&mut self, thorough: bool) -> Result<PyObject, Error>;

    // Shelving

    /// Store uncommitted changes from a shelf creator.
    fn store_uncommitted(&mut self, creator: &PyObject) -> Result<(), Error>;

    /// Return an unshelver for this branch and tree.
    ///
    /// Returns a Python `Unshelver`.
    fn get_unshelver(&self, tree: &PyObject) -> Result<PyObject, Error>;
}

/// Open the branch at `location`, as ``Branch.open`` does.
pub fn open(location: &str) -> Result<crate::controldir::BranchRef, crate::controldir::Error> {
    crate::controldir::open(location)?.open_branch(None)
}

/// Open the branch `name` at `transport`, as ``Branch.open_from_transport``
/// does.
pub fn open_from_transport(
    transport: crate::controldir::TransportRef,
    name: Option<&str>,
) -> Result<crate::controldir::BranchRef, crate::controldir::Error> {
    crate::controldir::open_from_transport(transport)?.open_branch(name)
}

/// Open the branch containing `location`, as ``Branch.open_containing``
/// does, with the part of `location` below it.
pub fn open_containing(
    location: &str,
) -> Result<(crate::controldir::BranchRef, String), crate::controldir::Error> {
    let (dir, relpath) = crate::controldir::open_containing(location)?;
    Ok((dir.open_branch(None)?, relpath))
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
