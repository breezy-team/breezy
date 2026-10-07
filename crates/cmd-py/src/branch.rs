//! Python binding that exposes a Rust `dyn Branch` to Python.
//!
//! Counterpart to [`breezy::pybranch::PyBranch`]: where `PyBranch` wraps a
//! Python branch for Rust, this `Branch` pyclass wraps a Rust branch for
//! Python. The `#[new]` constructor wraps a Python branch (via `PyBranch`).

use breezy::branch::Error;
use breezy::pybranch::PyBranch;
use breezy::RevisionId;
use pyo3::exceptions::PyRuntimeError;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

import_exception!(breezy.errors, NoSuchRevision);
import_exception!(breezy.errors, NotStacked);

/// A pair of revision-id byte lists, as returned by `heads_to_fetch`.
type HeadPair<'py> = (Vec<Bound<'py, PyBytes>>, Vec<Bound<'py, PyBytes>>);

/// Convert a branch [`Error`] into the matching Python exception.
///
/// `NoSuchRevision(branch, revision)` and `NotStacked(branch)` both take a
/// `branch` positional argument in Python; the error does not carry the
/// branch, so `None` is passed for it (the error message renders it as
/// `None`).
pub(crate) fn err_to_py(err: Error) -> PyErr {
    Python::attach(|py| match err {
        Error::NoSuchRevision(revid) => {
            NoSuchRevision::new_err((py.None(), revid.as_bytes().to_vec()))
        }
        Error::NotStacked => NotStacked::new_err((py.None(),)),
        Error::UpgradeRequired => {
            breezy::pyerrors::bzr_error(py, "breezy.errors", "UpgradeRequired", &err.to_string())
        }
        Error::BindingUnsupported => {
            breezy::pyerrors::bzr_error(py, "breezy.branch", "BindingUnsupported", &err.to_string())
        }
        Error::UnsupportedOperation(msg) => breezy::pyerrors::unsupported_operation(py, &msg),
        Error::Other(msg) => PyRuntimeError::new_err(msg),
    })
}

/// A branch: a line of development holding a history of revisions.
///
/// This mirrors ``breezy.branch.Branch``. Construct one by wrapping an
/// existing breezy branch object, e.g. ``Branch(breezy_branch)``. The
/// ``open``, ``open_from_transport`` and ``open_containing`` static methods
/// return the opened branch; a branch that is backed by a Python branch object
/// is returned as that original object rather than wrapped in this class.
///
/// Revision ids are passed and returned as bytes.
///
/// Args:
///     branch: The breezy branch object to wrap.
#[pyclass(module = "breezy._cmd_rs")]
pub struct Branch(Box<dyn breezy::branch::Branch + Send + Sync>);

/// Hand a branch to Python: the Python branch it wraps, or a [`Branch`]
/// around a native one.
pub(crate) fn branch_to_py(
    py: Python<'_>,
    branch: Box<dyn breezy::branch::Branch + Send + Sync>,
) -> PyResult<Py<PyAny>> {
    match branch.python_object() {
        Some(obj) => Ok(obj.clone_ref(py)),
        None => Ok(Py::new(py, Branch::from_boxed(branch))?.into_any()),
    }
}

impl Branch {
    /// Wrap an already-boxed branch.
    pub fn from_boxed(branch: Box<dyn breezy::branch::Branch + Send + Sync>) -> Self {
        Branch(branch)
    }
}

#[pymethods]
impl Branch {
    /// Wrap an existing breezy branch object.
    ///
    /// Args:
    ///     branch: The ``breezy.branch.Branch`` instance to wrap.
    #[new]
    fn new(branch: Py<PyAny>) -> Self {
        Branch(Box::new(PyBranch::new(branch)))
    }

    /// Open the branch rooted at a location.
    ///
    /// A ``,branch=NAME`` segment parameter on the location selects a
    /// colocated branch by name.
    ///
    /// Args:
    ///     location: The URL or local path of the branch.
    ///
    /// Returns:
    ///     The branch. A branch backed by a Python branch object is returned
    ///     as that object.
    ///
    /// Raises:
    ///     NotBranchError: If there is no branch at the location.
    ///     UnknownFormatError: If the control directory format is not
    ///         recognised.
    #[staticmethod]
    fn open(py: Python<'_>, location: &str) -> PyResult<Py<PyAny>> {
        branch_to_py(py, breezy::branch::open(location)?)
    }

    /// Open the branch rooted at a transport.
    ///
    /// Only the transport's ``base`` URL is used; a new transport is opened
    /// for it.
    ///
    /// Args:
    ///     transport: A transport pointing at the branch's location.
    ///     name: Name of a colocated branch, or None for the default branch.
    ///
    /// Returns:
    ///     The branch. A branch backed by a Python branch object is returned
    ///     as that object.
    ///
    /// Raises:
    ///     NotBranchError: If there is no branch at the location.
    #[staticmethod]
    #[pyo3(signature = (transport, name=None))]
    fn open_from_transport(
        py: Python<'_>,
        transport: &Bound<'_, PyAny>,
        name: Option<&str>,
    ) -> PyResult<Py<PyAny>> {
        let base: String = transport.getattr("base")?.extract()?;
        let transport = breezy::controldir::get_transport(&base)?;
        branch_to_py(py, breezy::branch::open_from_transport(transport, name)?)
    }

    /// Open an existing branch which contains a location.
    ///
    /// This probes for a branch at the location, and searches upwards from
    /// there until a control directory is found or the root is reached.
    ///
    /// Args:
    ///     location: The URL or local path to start searching from.
    ///
    /// Returns:
    ///     A tuple ``(branch, relpath)``, where ``relpath`` is the unused
    ///     portion of the location below the branch root. A branch backed by a
    ///     Python branch object is returned as that object.
    ///
    /// Raises:
    ///     NotBranchError: If no containing branch is found.
    ///     UnknownFormatError: If the control directory format is not
    ///         recognised.
    #[staticmethod]
    fn open_containing(py: Python<'_>, location: &str) -> PyResult<(Py<PyAny>, String)> {
        let (branch, relpath) = breezy::branch::open_containing(location)?;
        Ok((branch_to_py(py, branch)?, relpath))
    }

    /// The name of this branch, or the empty string for the default branch.
    #[getter]
    fn name(&self) -> PyResult<String> {
        self.0.name().map_err(err_to_py)
    }

    /// The transport for the user-visible location of the branch.
    #[getter]
    fn user_transport(&self) -> PyResult<Py<PyAny>> {
        self.0.user_transport().map_err(err_to_py)
    }

    /// The URL of the branch.
    #[getter]
    fn base(&self) -> PyResult<String> {
        self.0.base().map_err(err_to_py)
    }

    /// The URL of the directory holding the branch, as the user sees it.
    #[getter]
    fn user_url(&self) -> PyResult<String> {
        self.0.user_url().map_err(err_to_py)
    }

    /// The URL of the branch's own control files.
    #[getter]
    fn control_url(&self) -> PyResult<String> {
        self.0.control_url().map_err(err_to_py)
    }

    /// The repository holding this branch's revisions.
    #[getter]
    fn repository(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::repository::repository_to_py(py, self.0.repository().map_err(err_to_py)?)
    }

    /// The control directory this branch lives in.
    #[getter]
    fn controldir(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::controldir::controldir_to_py(py, self.0.controldir().map_err(err_to_py)?)
    }

    /// Return the branch's tags.
    ///
    /// This is the equivalent of ``branch.tags.get_tag_dict()``.
    ///
    /// Returns:
    ///     A dict mapping tag names (str) to revision ids (bytes).
    fn get_tag_dict<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<pyo3::Bound<'py, pyo3::types::PyDict>> {
        let dict = pyo3::types::PyDict::new(py);
        for (name, revid) in self.0.tags().get_tag_dict() {
            dict.set_item(name, PyBytes::new(py, revid.as_bytes()))?;
        }
        Ok(dict)
    }

    /// Return the branch nickname.
    ///
    /// Unlike ``breezy.branch.Branch.nick`` this is a method rather than a
    /// property. An explicitly set nickname takes precedence; otherwise the
    /// nickname of the master branch is used if the branch is bound, falling
    /// back to the branch name or one derived from the branch location.
    ///
    /// Returns:
    ///     The nickname, as a str.
    fn nick(&self) -> PyResult<String> {
        self.0.nick().map_err(err_to_py)
    }

    /// Set the branch nickname in the branch configuration.
    ///
    /// Args:
    ///     nick: The new nickname.
    fn set_nick(&mut self, nick: &str) -> PyResult<()> {
        self.0.set_nick(nick).map_err(err_to_py)
    }

    /// Break a lock if one is present from another instance.
    ///
    /// Uses the UI factory to ask for confirmation if the lock may be from an
    /// active process. This also probes the repository for its lock.
    fn break_lock(&mut self) -> PyResult<()> {
        self.0.break_lock().map_err(err_to_py)
    }

    /// Return True if this branch is locked.
    fn is_locked(&self) -> PyResult<bool> {
        self.0.is_locked().map_err(err_to_py)
    }

    /// Lock the branch for write operations.
    ///
    /// Args:
    ///     token: A token to permit reacquiring a previously held and
    ///         preserved lock, as bytes, or None.
    ///
    /// Returns:
    ///     A ``breezy.branch.BranchWriteLockResult``, which can be used as a
    ///     context manager and whose ``unlock`` releases the lock.
    ///
    /// Raises:
    ///     LockContention: If the lock is held by someone else.
    ///     TokenMismatch: If ``token`` does not match the held lock.
    #[pyo3(signature = (token=None))]
    fn lock_write(&mut self, token: Option<&str>) -> PyResult<Py<PyAny>> {
        self.0.lock_write(token).map_err(err_to_py)
    }

    /// Lock the branch for read operations.
    ///
    /// Returns:
    ///     A ``breezy.lock.LogicalLockResult``, which can be used as a context
    ///     manager and whose ``unlock`` releases the lock.
    fn lock_read(&self) -> PyResult<Py<PyAny>> {
        self.0.lock_read().map_err(err_to_py)
    }

    /// Release the lock on this branch.
    ///
    /// Raises:
    ///     LockNotHeld: If the branch is not locked.
    fn unlock(&mut self) -> PyResult<()> {
        self.0.unlock().map_err(err_to_py)
    }

    /// Return the lock mode of the branch: ``'r'``, ``'w'`` or None.
    fn peek_lock_mode(&self) -> PyResult<Option<String>> {
        self.0.peek_lock_mode().map_err(err_to_py)
    }

    /// Return whether the physical lock on the branch is held, by anyone.
    fn get_physical_lock_status(&self) -> PyResult<Py<PyAny>> {
        self.0.get_physical_lock_status().map_err(err_to_py)
    }

    /// Do not release the physical lock when this branch object is unlocked.
    ///
    /// Raises:
    ///     NotImplementedError: If the branch format does not support lock
    ///         tokens, i.e. ``lock_write`` does not return a token.
    fn leave_lock_in_place(&mut self) -> PyResult<()> {
        self.0.leave_lock_in_place().map_err(err_to_py)
    }

    /// Release the physical lock when this branch object is unlocked.
    ///
    /// This applies even if this object did not originally acquire the lock.
    ///
    /// Raises:
    ///     NotImplementedError: If the branch format does not support lock
    ///         tokens, i.e. ``lock_write`` does not return a token.
    fn dont_leave_lock_in_place(&mut self) -> PyResult<()> {
        self.0.dont_leave_lock_in_place().map_err(err_to_py)
    }

    /// Return the revision id of the branch tip.
    ///
    /// Returns:
    ///     The revision id as bytes, or ``b"null:"`` if the branch is empty.
    fn last_revision<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let revid = self.0.last_revision().map_err(err_to_py)?;
        Ok(PyBytes::new(py, revid.as_bytes()))
    }

    /// Return information about the branch tip.
    ///
    /// Returns:
    ///     A tuple ``(revno, revision_id)``, with the revision id as bytes.
    fn last_revision_info<'py>(&self, py: Python<'py>) -> PyResult<(u64, Bound<'py, PyBytes>)> {
        let (revno, revid) = self.0.last_revision_info().map_err(err_to_py)?;
        Ok((revno, PyBytes::new(py, revid.as_bytes())))
    }

    /// Set the tip of this branch.
    ///
    /// The caller is responsible for checking that the revno is correct for
    /// this revision id. Depending on the branch configuration, setting a tip
    /// that is not present in the repository, or that does not follow on from
    /// the existing history, may not be permitted.
    ///
    /// Args:
    ///     revno: The revision number of the new tip.
    ///     revision_id: The revision id of the new tip, as bytes.
    fn set_last_revision_info(&mut self, revno: u64, revision_id: Vec<u8>) -> PyResult<()> {
        self.0
            .set_last_revision_info(revno, &RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return the revision number of the branch tip.
    ///
    /// This is the number of revisions on the branch's mainline.
    fn revno(&self) -> PyResult<u64> {
        self.0.revno().map_err(err_to_py)
    }

    /// Return the mainline revision number for a revision id.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///
    /// Returns:
    ///     The revision number; 0 for the null revision.
    ///
    /// Raises:
    ///     NoSuchRevision: If the revision is not on the branch's mainline.
    fn revision_id_to_revno(&self, revision_id: Vec<u8>) -> PyResult<u64> {
        self.0
            .revision_id_to_revno(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return the revision id for a mainline revision number.
    ///
    /// Args:
    ///     revno: The revision number; 0 refers to the null revision.
    ///
    /// Returns:
    ///     The revision id, as bytes.
    ///
    /// Raises:
    ///     NoSuchRevision: If the branch has no revision with that number.
    fn get_rev_id<'py>(&self, py: Python<'py>, revno: i64) -> PyResult<Bound<'py, PyBytes>> {
        self.0
            .get_rev_id(revno)
            .map(|r| PyBytes::new(py, r.as_bytes()))
            .map_err(err_to_py)
    }

    /// Return the dotted revision number for a revision id.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///
    /// Returns:
    ///     The dotted revno as a list of ints, e.g. ``[1]`` or ``[1, 1, 2]``.
    ///
    /// Raises:
    ///     NoSuchRevision: If the revision is not in the branch's ancestry.
    ///     GhostRevisionsHaveNoRevno: If the revision's ancestry contains a
    ///         ghost.
    fn revision_id_to_dotted_revno(&self, revision_id: Vec<u8>) -> PyResult<Vec<i32>> {
        self.0
            .revision_id_to_dotted_revno(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Return the revision id for a dotted revision number.
    ///
    /// Args:
    ///     revno: The dotted revno as a sequence of ints, e.g. ``(1,)`` or
    ///         ``(1, 1, 2)``.
    ///
    /// Returns:
    ///     The revision id, as bytes.
    ///
    /// Raises:
    ///     NoSuchRevision: If no revision has that dotted revno.
    fn dotted_revno_to_revision_id<'py>(
        &self,
        py: Python<'py>,
        revno: Vec<i32>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        self.0
            .dotted_revno_to_revision_id(&revno)
            .map(|r| PyBytes::new(py, r.as_bytes()))
            .map_err(err_to_py)
    }

    /// Return a dict mapping revision ids to dotted revision numbers.
    ///
    /// The map is cached by the branch and should not be modified by the
    /// caller.
    ///
    /// Returns:
    ///     A dict mapping revision ids (bytes) to dotted revnos (tuples of
    ///     int).
    fn get_revision_id_to_revno_map(&self) -> PyResult<Py<PyAny>> {
        self.0.get_revision_id_to_revno_map().map_err(err_to_py)
    }

    /// Walk the revisions of the branch in merge sorted order.
    ///
    /// Merge sorted order is the output of a merge-aware topological sort: all
    /// parents come before their children going forward, and the opposite for
    /// reverse.
    ///
    /// Args:
    ///     start_revision_id: The revision id to begin walking from, or None
    ///         to start at the branch tip.
    ///     stop_revision_id: The revision id to terminate the walk after, or
    ///         None to include the rest of history.
    ///     stop_rule: If ``stop_revision_id`` is given, how to terminate:
    ///         ``'exclude'`` leaves the stop revision out, ``'include'`` makes
    ///         it the last item, ``'with-merges'`` includes it and all
    ///         revisions it merged, and
    ///         ``'with-merges-without-common-ancestry'`` also filters out
    ///         revisions that are in both ancestries.
    ///     direction: ``'reverse'`` to start at the most recent revision and
    ///         go back in history, or ``'forward'`` for the opposite order.
    ///
    /// Returns:
    ///     An iterator over ``(revision_id, depth, revno, end_of_merge)``
    ///     tuples, where ``depth`` is how many levels of merging deep the
    ///     revision is, ``revno`` is its dotted revno as a tuple, and
    ///     ``end_of_merge`` is True when the next revision is part of a
    ///     different merge.
    #[pyo3(signature = (start_revision_id=None, stop_revision_id=None, stop_rule="exclude", direction="reverse"))]
    fn iter_merge_sorted_revisions(
        &self,
        start_revision_id: Option<Vec<u8>>,
        stop_revision_id: Option<Vec<u8>>,
        stop_rule: &str,
        direction: &str,
    ) -> PyResult<Py<PyAny>> {
        let start = start_revision_id.map(RevisionId::from);
        let stop = stop_revision_id.map(RevisionId::from);
        self.0
            .iter_merge_sorted_revisions(start.as_ref(), stop.as_ref(), stop_rule, direction)
            .map_err(err_to_py)
    }

    /// Set the branch tip to a revision, computing its revision number.
    ///
    /// Args:
    ///     revision_id: The revision id of the new tip, as bytes.
    ///     last_rev: If given, the previous tip, which must be an ancestor of
    ///         ``revision_id``.
    ///     other_branch: The branch ``revision_id`` comes from, used when
    ///         reporting divergence.
    ///
    /// Raises:
    ///     DivergedBranches: If ``last_rev`` is not an ancestor of
    ///         ``revision_id``.
    ///     GhostRevisionsHaveNoRevno: If the ancestry of ``revision_id``
    ///         contains a ghost.
    #[pyo3(signature = (revision_id, last_rev=None, other_branch=None))]
    fn generate_revision_history(
        &mut self,
        revision_id: Vec<u8>,
        last_rev: Option<Vec<u8>>,
        other_branch: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        let last = last_rev.map(RevisionId::from);
        self.0
            .generate_revision_history(
                &RevisionId::from(revision_id),
                last.as_ref(),
                other_branch.as_ref(),
            )
            .map_err(err_to_py)
    }

    /// Set the branch tip, fetching revisions and tags from another branch.
    ///
    /// Revisions are fetched from ``source`` if necessary, along with the
    /// revisions referenced by its tags. This is used by bound branches to
    /// upload a revision to the master branch before updating the local tip.
    ///
    /// Args:
    ///     source: The branch to fetch from.
    ///     revno: The revision number of the new tip.
    ///     revid: The revision id of the new tip, as bytes.
    ///     lossy: Whether to discard metadata that can not be represented in
    ///         this branch's format.
    ///
    /// Returns:
    ///     A tuple ``(revno, revision_id)`` with the new tip. These only
    ///     differ from the arguments when ``lossy`` is True.
    #[pyo3(signature = (source, revno, revid, lossy=false))]
    fn import_last_revision_info_and_tags<'py>(
        &mut self,
        py: Python<'py>,
        source: Py<PyAny>,
        revno: u64,
        revid: Vec<u8>,
        lossy: bool,
    ) -> PyResult<(u64, Bound<'py, PyBytes>)> {
        let (revno, revid) = self
            .0
            .import_last_revision_info_and_tags(&source, revno, &RevisionId::from(revid), lossy)
            .map_err(err_to_py)?;
        Ok((revno, PyBytes::new(py, revid.as_bytes())))
    }

    /// Check that a revision number corresponds to a revision on the branch.
    ///
    /// Zero (the null revision) is considered valid.
    ///
    /// Args:
    ///     revno: The revision number to check.
    ///
    /// Raises:
    ///     InvalidRevisionNumber: If the number is out of range.
    fn check_revno(&self, revno: i64) -> PyResult<()> {
        self.0.check_revno(revno).map_err(err_to_py)
    }

    /// Check that a revision number corresponds to a real revision.
    ///
    /// Zero (the null revision) is considered invalid.
    ///
    /// Args:
    ///     revno: The revision number to check.
    ///
    /// Raises:
    ///     InvalidRevisionNumber: If the number is out of range.
    fn check_real_revno(&self, revno: i64) -> PyResult<()> {
        self.0.check_real_revno(revno).map_err(err_to_py)
    }

    /// Return the heads needed to copy this branch into another repository.
    ///
    /// Returns:
    ///     A tuple ``(must_fetch, if_present_fetch)`` of lists of revision ids
    ///     (bytes). ``must_fetch`` lists the heads that must be fetched;
    ///     ``if_present_fetch`` lists heads to fetch only if they are present.
    fn heads_to_fetch<'py>(&self, py: Python<'py>) -> PyResult<HeadPair<'py>> {
        let (must, if_present) = self.0.heads_to_fetch().map_err(err_to_py)?;
        let to_bytes = |v: Vec<RevisionId>| {
            v.into_iter()
                .map(|r| PyBytes::new(py, r.as_bytes()))
                .collect::<Vec<_>>()
        };
        Ok((to_bytes(must), to_bytes(if_present)))
    }

    /// Return the configuration of this branch.
    ///
    /// Returns:
    ///     A ``breezy.config.BranchConfig``.
    fn get_config(&self) -> PyResult<Py<PyAny>> {
        self.0.get_config().map_err(err_to_py)
    }

    /// Return the configuration stack of this branch.
    ///
    /// Returns:
    ///     A ``breezy.config.BranchStack``.
    fn get_config_stack(&self) -> PyResult<Py<PyAny>> {
        self.0.get_config_stack().map_err(err_to_py)
    }

    /// Return whether only appending revisions to the history is allowed.
    fn get_append_revisions_only(&self) -> PyResult<bool> {
        self.0.get_append_revisions_only().map_err(err_to_py)
    }

    /// Set whether only appending revisions to the history is allowed.
    ///
    /// Args:
    ///     enabled: True to only allow appending revisions.
    fn set_append_revisions_only(&mut self, enabled: bool) -> PyResult<()> {
        self.0.set_append_revisions_only(enabled).map_err(err_to_py)
    }

    /// Return the parent location of the branch.
    ///
    /// This is the default location for pull and missing.
    ///
    /// Returns:
    ///     The parent URL, or None if no parent is set.
    fn get_parent(&self) -> PyResult<Option<String>> {
        self.0.get_parent().map_err(err_to_py)
    }

    /// Set the parent location of the branch.
    ///
    /// The URL is stored relative to the branch where possible.
    ///
    /// Args:
    ///     url: The parent URL, or None to unset it.
    ///
    /// Raises:
    ///     InvalidURL: If the URL is not 7-bit ASCII.
    #[pyo3(signature = (url))]
    fn set_parent(&mut self, url: Option<&str>) -> PyResult<()> {
        self.0.set_parent(url).map_err(err_to_py)
    }

    /// Return the location to push this branch to, or None if none is set.
    fn get_push_location(&self) -> PyResult<Option<String>> {
        self.0.get_push_location().map_err(err_to_py)
    }

    /// Set the location to push this branch to.
    ///
    /// Args:
    ///     location: The push location.
    fn set_push_location(&mut self, location: &str) -> PyResult<()> {
        self.0.set_push_location(location).map_err(err_to_py)
    }

    /// Return the submit location of the branch, or None if none is set.
    ///
    /// This is the default location for bundles and merge proposals.
    fn get_submit_branch(&self) -> PyResult<Option<String>> {
        self.0.get_submit_branch().map_err(err_to_py)
    }

    /// Set the submit location of the branch.
    ///
    /// Args:
    ///     location: The submit location.
    fn set_submit_branch(&mut self, location: &str) -> PyResult<()> {
        self.0.set_submit_branch(location).map_err(err_to_py)
    }

    /// Return the public location of the branch, or None if none is set.
    ///
    /// This is used by merge directives.
    fn get_public_branch(&self) -> PyResult<Option<String>> {
        self.0.get_public_branch().map_err(err_to_py)
    }

    /// Set the public location of the branch.
    ///
    /// Args:
    ///     location: The public location.
    fn set_public_branch(&mut self, location: &str) -> PyResult<()> {
        self.0.set_public_branch(location).map_err(err_to_py)
    }

    /// Return the preferred format of submissions to this branch, or None.
    fn get_child_submit_format(&self) -> PyResult<Option<String>> {
        self.0.get_child_submit_format().map_err(err_to_py)
    }

    /// Return the URL this branch is stacked on.
    ///
    /// Raises:
    ///     NotStacked: If the branch is not stacked.
    ///     UnstackableBranchFormat: If the branch format does not support
    ///         stacking.
    fn get_stacked_on_url(&self) -> PyResult<String> {
        self.0.get_stacked_on_url().map_err(err_to_py)
    }

    /// Set the URL this branch is stacked on.
    ///
    /// Args:
    ///     url: The URL to stack on, or None to unstack the branch.
    ///
    /// Raises:
    ///     UnstackableBranchFormat: If the branch format does not support
    ///         stacking.
    ///     UnstackableRepositoryFormat: If the repository format does not
    ///         support stacking.
    #[pyo3(signature = (url))]
    fn set_stacked_on_url(&mut self, url: Option<&str>) -> PyResult<()> {
        self.0.set_stacked_on_url(url).map_err(err_to_py)
    }

    /// Bind this branch to another branch.
    ///
    /// This does not push or pull data between the branches.
    ///
    /// Args:
    ///     other: The branch to bind to.
    ///
    /// Raises:
    ///     BindingUnsupported: If this branch format does not support
    ///         binding.
    fn bind(&mut self, other: Py<PyAny>) -> PyResult<()> {
        self.0.bind(&other).map_err(err_to_py)
    }

    /// Unbind this branch, if it is bound.
    ///
    /// Raises:
    ///     BindingUnsupported: If this branch format does not support
    ///         binding.
    fn unbind(&mut self) -> PyResult<()> {
        self.0.unbind().map_err(err_to_py)
    }

    /// Return the URL of the branch this branch is bound to, or None.
    fn get_bound_location(&self) -> PyResult<Option<String>> {
        self.0.get_bound_location().map_err(err_to_py)
    }

    /// Return the URL of the branch this branch used to be bound to, or None.
    fn get_old_bound_location(&self) -> PyResult<Option<String>> {
        self.0.get_old_bound_location().map_err(err_to_py)
    }

    /// Return the branch this branch is bound to, or None if it is not bound.
    fn get_master_branch(&self) -> PyResult<Option<Py<PyAny>>> {
        self.0.get_master_branch().map_err(err_to_py)
    }

    /// Synchronise this branch with its master branch, if it has one.
    ///
    /// Unlike ``breezy.branch.Branch.update`` this always returns None; the
    /// revision pivoted out during the update is not reported.
    fn update(&mut self) -> PyResult<()> {
        self.0.update().map_err(err_to_py)
    }

    /// Return True if this branch supports tags.
    ///
    /// An error while checking is not raised; False is returned instead.
    fn supports_tags(&self) -> bool {
        self.0.supports_tags()
    }

    /// Try to automatically determine a tag name for a revision.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes.
    ///
    /// Returns:
    ///     A tag name, or None if no tag name could be determined.
    fn automatic_tag_name(&self, revision_id: Vec<u8>) -> PyResult<Option<String>> {
        self.0
            .automatic_tag_name(&RevisionId::from(revision_id))
            .map_err(err_to_py)
    }

    /// Copy revisions from another branch into this branch's repository.
    ///
    /// Args:
    ///     from_branch: The branch to copy from.
    ///     stop_revision: The revision id to stop at, as bytes, or None for
    ///         the tip of ``from_branch``.
    ///     limit: A rough limit on the number of revisions to fetch, or None.
    ///     lossy: Whether to allow lossy fetching.
    ///
    /// Returns:
    ///     The result reported by the underlying fetch, which may be None.
    #[pyo3(signature = (from_branch, stop_revision=None, limit=None, lossy=false))]
    fn fetch(
        &mut self,
        from_branch: Py<PyAny>,
        stop_revision: Option<Vec<u8>>,
        limit: Option<u64>,
        lossy: bool,
    ) -> PyResult<Py<PyAny>> {
        let stop = stop_revision.map(RevisionId::from);
        self.0
            .fetch(&from_branch, stop.as_ref(), limit, lossy)
            .map_err(err_to_py)
    }

    /// Mirror another branch into this branch.
    ///
    /// This branch is considered to be local, having low latency.
    ///
    /// Args:
    ///     source: The branch to pull from.
    ///     overwrite: Whether to overwrite this branch's history if it has
    ///         diverged.
    ///     stop_revision: The revision id to pull up to, as bytes, or None for
    ///         the tip of ``source``.
    ///
    /// Returns:
    ///     A ``breezy.branch.PullResult``.
    ///
    /// Raises:
    ///     DivergedBranches: If the branches have diverged and ``overwrite``
    ///         is False.
    #[pyo3(signature = (source, overwrite=false, stop_revision=None))]
    fn pull(
        &mut self,
        source: Py<PyAny>,
        overwrite: bool,
        stop_revision: Option<Vec<u8>>,
    ) -> PyResult<Py<PyAny>> {
        let stop = stop_revision.map(RevisionId::from);
        self.0
            .pull(&source, overwrite, stop.as_ref())
            .map_err(err_to_py)
    }

    /// Mirror this branch into another branch.
    ///
    /// This branch is considered to be local, having low latency.
    ///
    /// Args:
    ///     target: The branch to push to.
    ///     overwrite: Whether to overwrite the target's history if it has
    ///         diverged.
    ///     stop_revision: The revision id to push up to, as bytes, or None for
    ///         the tip of this branch.
    ///     lossy: Whether to discard data that can not be represented in the
    ///         target's format.
    ///
    /// Returns:
    ///     A ``breezy.branch.BranchPushResult``.
    ///
    /// Raises:
    ///     DivergedBranches: If the branches have diverged and ``overwrite``
    ///         is False.
    #[pyo3(signature = (target, overwrite=false, stop_revision=None, lossy=false))]
    fn push(
        &mut self,
        target: Py<PyAny>,
        overwrite: bool,
        stop_revision: Option<Vec<u8>>,
        lossy: bool,
    ) -> PyResult<Py<PyAny>> {
        let stop = stop_revision.map(RevisionId::from);
        self.0
            .push(&target, overwrite, stop.as_ref(), lossy)
            .map_err(err_to_py)
    }

    /// Return the tree for the branch tip.
    ///
    /// Returns:
    ///     A RevisionTree.
    fn basis_tree(&self) -> PyResult<Py<PyAny>> {
        self.0.basis_tree().map_err(err_to_py)
    }

    /// Obtain a commit builder for a new revision on this branch.
    ///
    /// Args:
    ///     parents: The revision ids (bytes) of the parents of the new
    ///         revision.
    ///     timestamp: The timestamp to record for the commit, or None.
    ///     timezone: The timezone offset of the timestamp in seconds, or None.
    ///     committer: The committer to record, or None.
    ///     revprops: A dict of revision properties, or None.
    ///     revision_id: The revision id to use, as bytes, or None to generate
    ///         one.
    ///     lossy: Whether to discard data that can not be represented, when
    ///         committing to a foreign VCS.
    ///
    /// Returns:
    ///     A ``breezy.repository.CommitBuilder``.
    #[pyo3(signature = (parents, timestamp=None, timezone=None, committer=None, revprops=None, revision_id=None, lossy=false))]
    #[allow(clippy::too_many_arguments)]
    fn get_commit_builder(
        &mut self,
        parents: Vec<Vec<u8>>,
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
                &parents,
                timestamp,
                timezone,
                committer,
                revprops.as_ref(),
                rev.as_ref(),
                lossy,
            )
            .map_err(err_to_py)
    }

    /// Create an in-memory tree for this branch.
    ///
    /// Returns:
    ///     An in-memory MutableTree.
    fn create_memorytree(&self) -> PyResult<Py<PyAny>> {
        self.0.create_memorytree().map_err(err_to_py)
    }

    /// Clone this branch into a control directory, preserving its settings.
    ///
    /// Most users will want ``create_clone_on_transport``, which creates the
    /// control directory as well.
    ///
    /// Args:
    ///     to_controldir: The control directory to create the new branch in.
    ///     revision_id: If given, the history of the new branch is truncated
    ///         to end with this revision id (bytes).
    ///     name: Name of the new colocated branch, or None for the default
    ///         branch.
    ///
    /// Returns:
    ///     The new branch.
    #[pyo3(signature = (to_controldir, revision_id=None, name=None))]
    fn clone(
        &self,
        to_controldir: Py<PyAny>,
        revision_id: Option<Vec<u8>>,
        name: Option<&str>,
    ) -> PyResult<Py<PyAny>> {
        let rev = revision_id.map(RevisionId::from);
        self.0
            .clone(&to_controldir, rev.as_ref(), name)
            .map_err(err_to_py)
    }

    /// Create a new line of development from this branch.
    ///
    /// The new branch is created in ``to_controldir``, which determines its
    /// format.
    ///
    /// Args:
    ///     to_controldir: The control directory to create the new branch in.
    ///     revision_id: If given, the history of the new branch is truncated
    ///         to end with this revision id (bytes).
    ///     lossy: Whether to discard data that can not be represented in the
    ///         target format.
    ///     name: Name of the new colocated branch, or None for the default
    ///         branch.
    ///
    /// Returns:
    ///     The new branch.
    #[pyo3(signature = (to_controldir, revision_id=None, lossy=false, name=None))]
    fn sprout(
        &self,
        to_controldir: Py<PyAny>,
        revision_id: Option<Vec<u8>>,
        lossy: bool,
        name: Option<&str>,
    ) -> PyResult<Py<PyAny>> {
        let rev = revision_id.map(RevisionId::from);
        self.0
            .sprout(&to_controldir, rev.as_ref(), lossy, name)
            .map_err(err_to_py)
    }

    /// Copy the history and settings of this branch into another branch.
    ///
    /// Args:
    ///     destination: The branch to copy into.
    ///     revision_id: If given, the history of the destination is truncated
    ///         to end with this revision id (bytes).
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

    /// Update any references in another branch to point to this branch.
    ///
    /// Args:
    ///     target: The branch whose references should be updated.
    fn update_references(&self, target: Py<PyAny>) -> PyResult<()> {
        self.0.update_references(&target).map_err(err_to_py)
    }

    /// Create a clone of this branch and its control directory on a transport.
    ///
    /// Args:
    ///     to_transport: The transport to clone onto.
    ///     revision_id: The revision id (bytes) to use as tip of the new
    ///         branch, or None to use the tip of this branch.
    ///     stacked_on: A URL to stack the clone on, or None.
    ///     create_prefix: Whether to create any missing directories leading up
    ///         to ``to_transport``.
    ///     use_existing_dir: Whether to use an existing directory if one
    ///         exists.
    ///
    /// Returns:
    ///     The new branch.
    #[pyo3(signature = (to_transport, revision_id=None, stacked_on=None, create_prefix=false, use_existing_dir=false))]
    fn create_clone_on_transport(
        &self,
        to_transport: Py<PyAny>,
        revision_id: Option<Vec<u8>>,
        stacked_on: Option<&str>,
        create_prefix: bool,
        use_existing_dir: bool,
    ) -> PyResult<Py<PyAny>> {
        let rev = revision_id.map(RevisionId::from);
        self.0
            .create_clone_on_transport(
                &to_transport,
                rev.as_ref(),
                stacked_on,
                create_prefix,
                use_existing_dir,
            )
            .map_err(err_to_py)
    }

    /// Create a checkout of this branch.
    ///
    /// Args:
    ///     to_location: The URL to create the checkout at.
    ///     revision_id: The revision id (bytes) to check out, or None for the
    ///         branch tip.
    ///     lightweight: If True, create a lightweight checkout; otherwise
    ///         create a bound branch (heavyweight checkout).
    ///     hardlink: Whether to hard-link files where possible.
    ///
    /// Returns:
    ///     The working tree of the new checkout.
    #[pyo3(signature = (to_location, revision_id=None, lightweight=false, hardlink=false))]
    fn create_checkout(
        &self,
        to_location: &str,
        revision_id: Option<Vec<u8>>,
        lightweight: bool,
        hardlink: bool,
    ) -> PyResult<Py<PyAny>> {
        let rev = revision_id.map(RevisionId::from);
        self.0
            .create_checkout(to_location, rev.as_ref(), lightweight, hardlink)
            .map_err(err_to_py)
    }

    /// Check the consistency of the branch.
    ///
    /// This checks that the revisions in the branch history match up with the
    /// revision graph and are present in the repository. Callers will
    /// typically also want to check the repository.
    ///
    /// Args:
    ///     refs: The references calculated for this branch, as specified by
    ///         ``branch._get_check_refs()``.
    ///
    /// Returns:
    ///     A ``breezy.branch.BranchCheckResult``.
    fn check(&self, refs: Py<PyAny>) -> PyResult<Py<PyAny>> {
        self.0.check(&refs).map_err(err_to_py)
    }

    /// Make sure the data stored in this branch is consistent.
    ///
    /// Args:
    ///     thorough: Whether to do a thorough check.
    ///
    /// Returns:
    ///     A ``breezy.reconcile.ReconcileResult``.
    #[pyo3(signature = (thorough=true))]
    fn reconcile(&mut self, thorough: bool) -> PyResult<Py<PyAny>> {
        self.0.reconcile(thorough).map_err(err_to_py)
    }

    /// Store uncommitted changes from a shelf creator in the branch.
    ///
    /// Args:
    ///     creator: The ``breezy.shelf.ShelfCreator`` holding the uncommitted
    ///         changes, or None to delete any stored changes.
    ///
    /// Raises:
    ///     ChangesAlreadyStored: If the branch already has stored changes.
    fn store_uncommitted(&mut self, creator: Py<PyAny>) -> PyResult<()> {
        self.0.store_uncommitted(&creator).map_err(err_to_py)
    }

    /// Return an unshelver for the changes stored in this branch.
    ///
    /// Args:
    ///     tree: The tree to construct the unshelver for.
    ///
    /// Returns:
    ///     A ``breezy.shelf.Unshelver``, or None if no changes are stored.
    fn get_unshelver(&self, tree: Py<PyAny>) -> PyResult<Py<PyAny>> {
        self.0.get_unshelver(&tree).map_err(err_to_py)
    }
}
