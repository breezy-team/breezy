//! Python bindings for the Rust control directory layer.
//!
//! `ControlDir` wraps a boxed [`breezy::controldir::ControlDir`]; its static
//! methods mirror the ``ControlDir`` class methods. Anything handed back that
//! is backed by a Python object, because a Python prober opened it, is
//! returned as that object itself rather than as a Rust class proxying to
//! it, so Python code gets its own objects back.

use breezy::controldir::{
    self, BranchRef, CloneOnTransportOptions, CloneOptions, Error, Prober, PushOptions,
    SproutOptions, TransportRef, WorkingTreeRef,
};
use breezy::pybranch::PyBranch;
use breezy::pycontroldir::{PyControlDir, PyControlDirFormat, PyProber};
use breezy::pyrepository::PyRepository;
use breezy::pytree::PyTree;
use breezy::RevisionId;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::{Arc, Mutex, OnceLock};

/// A Rust transport for a Python transport object, by its URL.
fn rust_transport(transport: &Bound<'_, PyAny>) -> PyResult<TransportRef> {
    let base: String = transport.getattr("base")?.extract()?;
    Ok(controldir::get_transport(&base)?)
}

/// A Python transport at the location of a Rust transport.
fn py_transport<'py>(py: Python<'py>, transport: TransportRef) -> PyResult<Bound<'py, PyAny>> {
    py.import("breezy.transport")?
        .call_method1("get_transport_from_url", (transport.base().as_str(),))
}

/// Hand a control directory to Python: the Python object it wraps, or a
/// [`ControlDir`] around a native one.
pub(crate) fn controldir_to_py(
    py: Python<'_>,
    dir: Box<dyn controldir::ControlDir>,
) -> PyResult<Py<PyAny>> {
    match dir.python_object() {
        Some(obj) => Ok(obj.clone_ref(py)),
        None => Ok(Py::new(py, ControlDir(dir))?.into_any()),
    }
}

fn format_to_py(
    py: Python<'_>,
    format: Box<dyn controldir::ControlDirFormat>,
) -> PyResult<Py<PyAny>> {
    match format.python_object() {
        Some(obj) => Ok(obj.clone_ref(py)),
        None => Ok(Py::new(py, ControlDirFormat(Arc::from(format)))?.into_any()),
    }
}

/// Run `f` with the Rust format behind a Python format argument: a
/// [`ControlDirFormat`] gives its own, anything else is a Python format.
fn with_format<T>(
    format: &Bound<'_, PyAny>,
    f: impl FnOnce(&dyn controldir::ControlDirFormat) -> T,
) -> PyResult<T> {
    if let Ok(wrapped) = format.extract::<PyRef<'_, ControlDirFormat>>() {
        return Ok(f(wrapped.0.as_ref()));
    }
    Ok(f(&PyControlDirFormat::new(format.clone().unbind())))
}

fn optional_format<T>(
    format: Option<&Bound<'_, PyAny>>,
    f: impl FnOnce(Option<&dyn controldir::ControlDirFormat>) -> T,
) -> PyResult<T> {
    match format {
        Some(format) => with_format(format, |format| f(Some(format))),
        None => Ok(f(None)),
    }
}

fn revision_id(revision_id: Option<Vec<u8>>) -> Option<RevisionId> {
    revision_id.map(RevisionId::from)
}

fn tree_tuple(
    py: Python<'_>,
    tree: Option<WorkingTreeRef>,
    branch: BranchRef,
) -> PyResult<(Option<Py<PyAny>>, Py<PyAny>)> {
    let tree = tree
        .map(|tree| crate::tree::working_tree_to_py(py, tree))
        .transpose()?;
    Ok((tree, crate::branch::branch_to_py(py, branch)?))
}

/// A control directory format implemented in ``breezy._cmd_rs``.
///
/// Instances are returned in place of a ``breezy.controldir.ControlDirFormat``
/// for formats that have no Python implementation, for example by
/// ``ControlDir.cloning_metadir`` and ``get_default_format``. They provide a
/// subset of the methods of ``breezy.controldir.ControlDirFormat``.
#[pyclass(module = "breezy._cmd_rs")]
pub struct ControlDirFormat(Arc<dyn controldir::ControlDirFormat>);

#[pymethods]
impl ControlDirFormat {
    /// Return the short description of this format.
    fn get_format_description(&self) -> PyResult<String> {
        self.0.get_format_description().map_err(PyErr::from)
    }

    /// Check whether this format is supported.
    ///
    /// Supported formats can be opened; unsupported ones may lack
    /// initialization, committing or other features.
    fn is_supported(&self) -> PyResult<bool> {
        Ok(self.0.is_supported()?)
    }

    /// Raise an error if this format is unsupported.
    ///
    /// Args:
    ///     allow_unsupported: If true, do not raise for unsupported formats.
    ///
    /// Raises:
    ///     UnsupportedFormatError: If the format is not supported and
    ///         ``allow_unsupported`` is false.
    fn check_support_status(&self, allow_unsupported: bool) -> PyResult<()> {
        Ok(self.0.check_support_status(allow_unsupported)?)
    }

    /// Open the control directory of this format at a transport.
    ///
    /// Args:
    ///     transport: The Transport of the directory containing the control
    ///         directory.
    ///
    /// Returns:
    ///     The ControlDir found there.
    fn open(&self, py: Python<'_>, transport: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        controldir_to_py(py, self.0.open(rust_transport(transport)?)?)
    }

    /// Create a control directory of this format at a location.
    ///
    /// Args:
    ///     location: A path or URL.
    ///
    /// Returns:
    ///     The new ControlDir.
    fn initialize(&self, py: Python<'_>, location: &str) -> PyResult<Py<PyAny>> {
        controldir_to_py(py, self.0.initialize(location)?)
    }

    /// Create a control directory of this format at a transport.
    ///
    /// Args:
    ///     transport: The Transport of the directory to create the control
    ///         directory in.
    ///
    /// Returns:
    ///     The new ControlDir.
    fn initialize_on_transport(
        &self,
        py: Python<'_>,
        transport: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        controldir_to_py(
            py,
            self.0.initialize_on_transport(rust_transport(transport)?)?,
        )
    }
}

/// A control directory, such as a ``.bzr`` or ``.git`` directory.
///
/// A control directory holds the working tree, branch and repository at a
/// location. Use the static methods such as ``ControlDir.open`` or
/// ``ControlDir.create`` to get one. Control directories that are
/// implemented in Python are returned as the Python
/// ``breezy.controldir.ControlDir`` objects themselves; instances of this
/// class provide the same methods for the others.
#[pyclass(module = "breezy._cmd_rs")]
pub struct ControlDir(Box<dyn controldir::ControlDir>);

impl ControlDir {
    /// The wrapped control directory.
    pub(crate) fn inner(&self) -> &dyn controldir::ControlDir {
        self.0.as_ref()
    }
}

#[pymethods]
impl ControlDir {
    /// Wrap a Python control directory.
    ///
    /// The result provides the methods of this class on top of ``controldir``,
    /// for code that wants to use the ``breezy._cmd_rs`` implementation.
    ///
    /// Args:
    ///     controldir: A ``breezy.controldir.ControlDir``.
    #[new]
    fn new(controldir: Py<PyAny>) -> Self {
        ControlDir(Box::new(PyControlDir::new(controldir)))
    }

    /// Open the control directory at a location.
    ///
    /// Args:
    ///     location: A path or URL.
    ///
    /// Returns:
    ///     The control directory found there.
    ///
    /// Raises:
    ///     NotBranchError: If there is no control directory at ``location``.
    ///     UnknownFormatError: If the control directory there has a format
    ///         that is not recognised.
    #[staticmethod]
    fn open(py: Python<'_>, location: &str) -> PyResult<Py<PyAny>> {
        controldir_to_py(py, controldir::open(location)?)
    }

    /// Open the control directory at a location, even if unsupported.
    ///
    /// Args:
    ///     location: A path or URL.
    ///
    /// Returns:
    ///     The control directory found there.
    ///
    /// Raises:
    ///     NotBranchError: If there is no control directory at ``location``.
    #[staticmethod]
    fn open_unsupported(py: Python<'_>, location: &str) -> PyResult<Py<PyAny>> {
        controldir_to_py(py, controldir::open_unsupported(location)?)
    }

    /// Open the control directory in the directory of a transport.
    ///
    /// Args:
    ///     transport: The Transport of the directory containing the control
    ///         directory. Only its ``base`` URL is used.
    ///
    /// Returns:
    ///     The control directory found there.
    ///
    /// Raises:
    ///     NotBranchError: If there is no control directory at ``transport``.
    ///     UnknownFormatError: If the control directory there has a format
    ///         that is not recognised.
    #[staticmethod]
    fn open_from_transport(py: Python<'_>, transport: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        controldir_to_py(
            py,
            controldir::open_from_transport(rust_transport(transport)?)?,
        )
    }

    /// Open the control directory containing a location.
    ///
    /// This looks for a control directory at ``location`` and then in each of
    /// its parents in turn.
    ///
    /// Args:
    ///     location: A path or URL.
    ///
    /// Returns:
    ///     A ``(controldir, relpath)`` tuple, where ``relpath`` is the
    ///     unescaped part of ``location`` below the control directory.
    ///
    /// Raises:
    ///     NotBranchError: If no control directory contains ``location``.
    ///     UnknownFormatError: If the control directory found has a format
    ///         that is not recognised.
    #[staticmethod]
    fn open_containing(py: Python<'_>, location: &str) -> PyResult<(Py<PyAny>, String)> {
        let (dir, relpath) = controldir::open_containing(location)?;
        Ok((controldir_to_py(py, dir)?, relpath))
    }

    /// Open the control directory containing the directory of a transport.
    ///
    /// This looks for a control directory at ``transport`` and then in each of
    /// its parents in turn.
    ///
    /// Args:
    ///     transport: A Transport. Only its ``base`` URL is used.
    ///
    /// Returns:
    ///     A ``(controldir, relpath)`` tuple, where ``relpath`` is the
    ///     unescaped part of the transport URL below the control directory.
    ///
    /// Raises:
    ///     NotBranchError: If no control directory contains ``transport``.
    ///     UnknownFormatError: If the control directory found has a format
    ///         that is not recognised.
    #[staticmethod]
    fn open_containing_from_transport(
        py: Python<'_>,
        transport: &Bound<'_, PyAny>,
    ) -> PyResult<(Py<PyAny>, String)> {
        let (dir, relpath) =
            controldir::open_containing_from_transport(rust_transport(transport)?)?;
        Ok((controldir_to_py(py, dir)?, relpath))
    }

    /// Open the working tree and branch at a location.
    ///
    /// Args:
    ///     location: A path or URL.
    ///     name: The name of the colocated branch to open, or None for the
    ///         default branch.
    ///
    /// Returns:
    ///     A ``(tree, branch)`` tuple. ``tree`` is None if there is no working
    ///     tree at ``location``.
    ///
    /// Raises:
    ///     NotBranchError: If there is no branch at ``location``.
    #[staticmethod]
    #[pyo3(signature = (location, name=None))]
    fn open_tree_or_branch(
        py: Python<'_>,
        location: &str,
        name: Option<&str>,
    ) -> PyResult<(Option<Py<PyAny>>, Py<PyAny>)> {
        let (tree, branch) = controldir::open_tree_or_branch(location, name)?;
        tree_tuple(py, tree, branch)
    }

    /// Open the working tree and branch containing a location.
    ///
    /// Args:
    ///     location: A path or URL.
    ///
    /// Returns:
    ///     A ``(tree, branch, relpath)`` tuple. ``tree`` is None if there is
    ///     no working tree, and ``relpath`` is the part of ``location`` below
    ///     the branch.
    ///
    /// Raises:
    ///     NotBranchError: If no branch contains ``location``.
    #[staticmethod]
    fn open_containing_tree_or_branch(
        py: Python<'_>,
        location: &str,
    ) -> PyResult<(Option<Py<PyAny>>, Py<PyAny>, String)> {
        let (tree, branch, relpath) = controldir::open_containing_tree_or_branch(location)?;
        let (tree, branch) = tree_tuple(py, tree, branch)?;
        Ok((tree, branch, relpath))
    }

    /// Open the working tree, branch and repository containing a location.
    ///
    /// Args:
    ///     location: A path or URL.
    ///
    /// Returns:
    ///     A ``(tree, branch, repository, relpath)`` tuple. ``tree`` and
    ///     ``branch`` are None if there is no working tree or branch, and
    ///     ``relpath`` is the part of ``location`` below the innermost control
    ///     directory.
    ///
    /// Raises:
    ///     NotBranchError: If neither a branch nor a repository contains
    ///         ``location``.
    #[staticmethod]
    #[allow(clippy::type_complexity)]
    fn open_containing_tree_branch_or_repository(
        py: Python<'_>,
        location: &str,
    ) -> PyResult<(Option<Py<PyAny>>, Option<Py<PyAny>>, Py<PyAny>, String)> {
        let (tree, branch, repository, relpath) =
            controldir::open_containing_tree_branch_or_repository(location)?;
        let tree = tree
            .map(|tree| crate::tree::working_tree_to_py(py, tree))
            .transpose()?;
        let branch = branch
            .map(|branch| crate::branch::branch_to_py(py, branch))
            .transpose()?;
        Ok((
            tree,
            branch,
            crate::repository::repository_to_py(py, repository)?,
            relpath,
        ))
    }

    /// Create a new control directory at a location.
    ///
    /// The directory is created if it does not exist yet.
    ///
    /// Args:
    ///     location: A path or URL.
    ///     format: The ControlDirFormat to create, or None for the default
    ///         format.
    ///
    /// Returns:
    ///     The new control directory.
    #[staticmethod]
    #[pyo3(signature = (location, format=None))]
    fn create(
        py: Python<'_>,
        location: &str,
        format: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let dir = optional_format(format, |format| controldir::create(location, format))??;
        controldir_to_py(py, dir)
    }

    /// Create a new control directory with a branch and repository.
    ///
    /// If a shared repository encloses ``location`` it is used, unless
    /// ``force_new_repo`` is true.
    ///
    /// Args:
    ///     location: A path or URL.
    ///     force_new_repo: If true, always create a new repository.
    ///     format: The ControlDirFormat to create, or None for the default
    ///         format.
    ///
    /// Returns:
    ///     The new Branch.
    #[staticmethod]
    #[pyo3(signature = (location, force_new_repo=false, format=None))]
    fn create_branch_and_repo(
        py: Python<'_>,
        location: &str,
        force_new_repo: bool,
        format: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let branch = optional_format(format, |format| {
            controldir::create_branch_and_repo(location, force_new_repo, format)
        })??;
        crate::branch::branch_to_py(py, branch)
    }

    /// Create a new control directory with a branch, repository and tree.
    ///
    /// An enclosing shared repository is used if there is one, unless
    /// ``force_new_repo`` is true. Unless ``force_new_tree`` says otherwise, a
    /// working tree is created if the repository's policy is to make working
    /// trees. If ``location`` is not local no working tree is created, and no
    /// error is raised unless ``force_new_tree`` is true.
    ///
    /// Args:
    ///     location: A path or URL.
    ///     force_new_repo: If true, always create a new repository.
    ///     force_new_tree: True or False to force or prevent creation of a
    ///         working tree, or None to follow the repository's policy.
    ///     format: The ControlDirFormat to create, or None for the default
    ///         format.
    ///
    /// Returns:
    ///     The new Branch.
    ///
    /// Raises:
    ///     NotLocalUrl: If ``force_new_tree`` is true and ``location`` is not
    ///         local; nothing is created in that case.
    #[staticmethod]
    #[pyo3(signature = (location, force_new_repo=false, force_new_tree=None, format=None))]
    fn create_branch_convenience(
        py: Python<'_>,
        location: &str,
        force_new_repo: bool,
        force_new_tree: Option<bool>,
        format: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let branch = optional_format(format, |format| {
            controldir::create_branch_convenience(location, force_new_repo, force_new_tree, format)
        })??;
        crate::branch::branch_to_py(py, branch)
    }

    /// Create a new control directory with a working tree.
    ///
    /// A new branch and a new repository are always created as well.
    ///
    /// Args:
    ///     location: A local path or ``file://`` URL.
    ///     format: The ControlDirFormat to create, or None for the default
    ///         format.
    ///
    /// Returns:
    ///     The new WorkingTree.
    ///
    /// Raises:
    ///     NotLocalUrl: If ``location`` is not local.
    #[staticmethod]
    #[pyo3(signature = (location, format=None))]
    fn create_standalone_workingtree(
        py: Python<'_>,
        location: &str,
        format: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let tree = optional_format(format, |format| {
            controldir::create_standalone_workingtree(location, format)
        })??;
        crate::tree::working_tree_to_py(py, tree)
    }

    /// Find the control directories at and below a transport.
    ///
    /// Unlike ``breezy.controldir.ControlDir.find_controldirs`` this does not
    /// take ``evaluate`` or ``list_current`` callbacks: every control
    /// directory found is returned and searched below.
    ///
    /// Args:
    ///     transport: The Transport to start searching at. Only its ``base``
    ///         URL is used.
    ///
    /// Returns:
    ///     A list of control directories.
    #[staticmethod]
    fn find_controldirs(py: Python<'_>, transport: &Bound<'_, PyAny>) -> PyResult<Vec<Py<PyAny>>> {
        let dirs = controldir::find_controldirs(rust_transport(transport)?, |dir| Ok((true, dir)))?;
        dirs.into_iter()
            .map(|dir| controldir_to_py(py, dir))
            .collect()
    }

    /// Find all branches at and below a transport.
    ///
    /// This includes branches inside other branches. Where a repository is
    /// found, its ``find_branches`` is used for the branches below it.
    ///
    /// Args:
    ///     transport: The Transport to start searching at. Only its ``base``
    ///         URL is used.
    ///
    /// Returns:
    ///     A list of Branch objects.
    #[staticmethod]
    fn find_branches(py: Python<'_>, transport: &Bound<'_, PyAny>) -> PyResult<Vec<Py<PyAny>>> {
        controldir::find_branches(rust_transport(transport)?)?
            .into_iter()
            .map(|branch| crate::branch::branch_to_py(py, branch))
            .collect()
    }

    /// The URL of the directory the control directory lives in.
    #[getter]
    fn user_url(&self) -> PyResult<String> {
        Ok(self.0.user_url()?)
    }

    /// The URL of the control directory itself, such as ``.bzr/``.
    #[getter]
    fn control_url(&self) -> PyResult<String> {
        Ok(self.0.control_url()?)
    }

    /// A Transport for the directory the control directory lives in.
    ///
    /// A new Transport is returned on each access.
    #[getter]
    fn user_transport<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        py_transport(py, self.0.user_transport()?)
    }

    /// The same as ``user_transport``.
    #[getter]
    fn root_transport<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.user_transport(py)
    }

    /// A Transport for the control directory itself, such as ``.bzr/``.
    ///
    /// A new Transport is returned on each access.
    #[getter]
    fn control_transport<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        py_transport(py, self.0.control_transport()?)
    }

    /// The same as ``control_transport``.
    #[getter]
    fn transport<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.control_transport(py)
    }

    /// Check whether this control directory contains a working tree.
    fn has_workingtree(&self) -> PyResult<bool> {
        Ok(self.0.has_workingtree()?)
    }

    /// Check whether this control directory contains a branch.
    ///
    /// Args:
    ///     name: The name of the colocated branch, or None for the default
    ///         branch.
    #[pyo3(signature = (name=None))]
    fn has_branch(&self, name: Option<&str>) -> PyResult<bool> {
        Ok(self.0.has_branch(name)?)
    }

    /// Check whether this control directory contains a repository.
    fn has_repository(&self) -> PyResult<bool> {
        Ok(self.0.has_repository()?)
    }

    /// Open the working tree in this control directory.
    ///
    /// Returns:
    ///     The WorkingTree.
    ///
    /// Raises:
    ///     NoWorkingTree: If there is no working tree.
    ///     NotLocalUrl: If the control directory is not local.
    fn open_workingtree(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::tree::working_tree_to_py(py, self.0.open_workingtree()?)
    }

    /// Open the branch in this control directory.
    ///
    /// Args:
    ///     name: The name of the colocated branch, or None for the default
    ///         branch.
    ///
    /// Returns:
    ///     The Branch.
    ///
    /// Raises:
    ///     NotBranchError: If there is no such branch.
    #[pyo3(signature = (name=None))]
    fn open_branch(&self, py: Python<'_>, name: Option<&str>) -> PyResult<Py<PyAny>> {
        crate::branch::branch_to_py(py, self.0.open_branch(name)?)
    }

    /// Open the repository in this control directory.
    ///
    /// This does not look for a shared repository in enclosing directories;
    /// use ``find_repository`` for that.
    ///
    /// Returns:
    ///     The Repository.
    ///
    /// Raises:
    ///     NoRepositoryPresent: If there is no repository here.
    fn open_repository(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::repository::repository_to_py(py, self.0.open_repository()?)
    }

    /// Find the repository that should be used for this control directory.
    ///
    /// This is the repository in this control directory, or else a shared
    /// repository in an enclosing directory.
    ///
    /// Returns:
    ///     The Repository.
    ///
    /// Raises:
    ///     NoRepositoryPresent: If there is no such repository.
    fn find_repository(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::repository::repository_to_py(py, self.0.find_repository()?)
    }

    /// Check whether this control directory's format can be converted.
    fn can_convert_format(&self) -> PyResult<bool> {
        Ok(self.0.can_convert_format()?)
    }

    /// Check whether this control directory needs converting to a format.
    ///
    /// Args:
    ///     format: The ControlDirFormat to convert to, or None for the default
    ///         format.
    #[pyo3(signature = (format=None))]
    fn needs_format_conversion(&self, format: Option<&Bound<'_, PyAny>>) -> PyResult<bool> {
        Ok(optional_format(format, |format| {
            self.0.needs_format_conversion(format)
        })??)
    }

    /// Check that this control directory can be converted to a format.
    ///
    /// Args:
    ///     target_format: The ControlDirFormat to convert to.
    fn check_conversion_target(&self, target_format: &Bound<'_, PyAny>) -> PyResult<()> {
        Ok(with_format(target_format, |format| {
            self.0.check_conversion_target(format)
        })??)
    }

    /// Check whether a filename is reserved for the control directory.
    ///
    /// Args:
    ///     filename: A filename relative to ``user_transport``.
    ///
    /// Returns:
    ///     True if ``filename`` is part of the control directory, such as
    ///     ``.bzr``.
    fn is_control_filename(&self, filename: &str) -> PyResult<bool> {
        Ok(self.0.is_control_filename(filename)?)
    }

    /// Return the URL a branch in this control directory refers to.
    ///
    /// Args:
    ///     name: The name of the colocated branch, or None for the default
    ///         branch.
    ///
    /// Returns:
    ///     The URL the branch refers to if it is a branch reference, or None
    ///     for a regular branch.
    ///
    /// Raises:
    ///     NotBranchError: If there is no such branch.
    #[pyo3(signature = (name=None))]
    fn get_branch_reference(&self, name: Option<&str>) -> PyResult<Option<String>> {
        Ok(self.0.get_branch_reference(name)?)
    }

    /// Make a branch in this control directory a reference to another branch.
    ///
    /// Args:
    ///     target_branch: The Branch to refer to.
    ///     name: The name of the colocated branch, or None for the default
    ///         branch.
    ///
    /// Returns:
    ///     The reference Branch.
    #[pyo3(signature = (target_branch, name=None))]
    fn set_branch_reference(
        &self,
        py: Python<'_>,
        target_branch: Py<PyAny>,
        name: Option<&str>,
    ) -> PyResult<Py<PyAny>> {
        let branch = self
            .0
            .set_branch_reference(&PyBranch::new(target_branch), name)?;
        crate::branch::branch_to_py(py, branch)
    }

    /// Return the format of a branch in this control directory.
    ///
    /// Args:
    ///     name: The name of the colocated branch, or None for the default
    ///         branch.
    ///
    /// Returns:
    ///     A ``breezy.branch.BranchFormat``.
    #[pyo3(signature = (name=None))]
    fn find_branch_format(&self, name: Option<&str>) -> PyResult<Py<PyAny>> {
        Ok(self.0.find_branch_format(name)?)
    }

    /// Return the names of the branches in this control directory.
    ///
    /// Returns:
    ///     A list of branch names, as str.
    fn branch_names(&self) -> PyResult<Vec<String>> {
        Ok(self.0.branch_names()?)
    }

    /// Return the branches in this control directory.
    ///
    /// Returns:
    ///     A dict mapping branch names to Branch objects.
    fn get_branches<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let branches = PyDict::new(py);
        for (name, branch) in self.0.get_branches()? {
            branches.set_item(name, crate::branch::branch_to_py(py, branch)?)?;
        }
        Ok(branches)
    }

    /// Return the branches in this control directory.
    ///
    /// Returns:
    ///     A list of Branch objects.
    fn list_branches(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        self.0
            .list_branches()?
            .into_iter()
            .map(|branch| crate::branch::branch_to_py(py, branch))
            .collect()
    }

    /// Create a repository in this control directory.
    ///
    /// Args:
    ///     shared: Whether the repository should be shared with branches in
    ///         directories below it.
    ///
    /// Returns:
    ///     The new Repository.
    #[pyo3(signature = (shared=false))]
    fn create_repository(&self, py: Python<'_>, shared: bool) -> PyResult<Py<PyAny>> {
        crate::repository::repository_to_py(py, self.0.create_repository(shared)?)
    }

    /// Delete the repository in this control directory.
    fn destroy_repository(&self) -> PyResult<()> {
        Ok(self.0.destroy_repository()?)
    }

    /// Create a branch in this control directory.
    ///
    /// The format of this control directory decides the branch format.
    ///
    /// Args:
    ///     name: The name of the colocated branch to create, or None for the
    ///         default branch.
    ///     repository: The Repository to create the branch in, or None to use
    ///         the one ``find_repository`` returns.
    ///     append_revisions_only: Whether the branch should only allow
    ///         appending revisions to its history, or None for the format's
    ///         default.
    ///
    /// Returns:
    ///     The new Branch.
    #[pyo3(signature = (name=None, repository=None, append_revisions_only=None))]
    fn create_branch(
        &self,
        py: Python<'_>,
        name: Option<&str>,
        repository: Option<Py<PyAny>>,
        append_revisions_only: Option<bool>,
    ) -> PyResult<Py<PyAny>> {
        let repository = repository.map(PyRepository::new);
        let branch = self.0.create_branch(
            name,
            repository
                .as_ref()
                .map(|r| r as &(dyn breezy::repository::Repository + Send + Sync)),
            append_revisions_only,
        )?;
        crate::branch::branch_to_py(py, branch)
    }

    /// Delete a branch in this control directory.
    ///
    /// Args:
    ///     name: The name of the colocated branch, or None for the default
    ///         branch.
    ///
    /// Raises:
    ///     NotBranchError: If there is no such branch.
    #[pyo3(signature = (name=None))]
    fn destroy_branch(&self, name: Option<&str>) -> PyResult<()> {
        Ok(self.0.destroy_branch(name)?)
    }

    /// Create a working tree in this control directory.
    ///
    /// Args:
    ///     revision_id: The revision id, as bytes, to create the tree at, or
    ///         None for the branch tip.
    ///     from_branch: The Branch to use instead of the one in this control
    ///         directory, as for lightweight checkouts.
    ///     accelerator_tree: A tree to take file contents from where they
    ///         match the revision, such as an existing working tree, as that
    ///         can be faster than the revision tree.
    ///     hardlink: If true, hard-link files from ``accelerator_tree`` where
    ///         possible.
    ///
    /// Returns:
    ///     The new WorkingTree.
    #[pyo3(signature = (revision_id=None, from_branch=None, accelerator_tree=None, hardlink=false))]
    fn create_workingtree(
        &self,
        py: Python<'_>,
        revision_id: Option<Vec<u8>>,
        from_branch: Option<Py<PyAny>>,
        accelerator_tree: Option<Py<PyAny>>,
        hardlink: bool,
    ) -> PyResult<Py<PyAny>> {
        let revision_id = self::revision_id(revision_id);
        let from_branch = from_branch.map(PyBranch::new);
        let accelerator_tree = accelerator_tree.map(PyTree::new);
        let tree = self.0.create_workingtree(
            revision_id.as_ref(),
            from_branch
                .as_ref()
                .map(|b| b as &(dyn breezy::branch::Branch + Send + Sync)),
            accelerator_tree
                .as_ref()
                .map(|t| t as &(dyn breezy::tree::Tree + Send + Sync)),
            hardlink,
        )?;
        crate::tree::working_tree_to_py(py, tree)
    }

    /// Delete the working tree in this control directory, including its files.
    ///
    /// Raises:
    ///     UnsupportedOperation: If the format does not support this.
    fn destroy_workingtree(&self) -> PyResult<()> {
        Ok(self.0.destroy_workingtree()?)
    }

    /// Delete the control files of the working tree, leaving its files alone.
    ///
    /// Raises:
    ///     UnsupportedOperation: If the format does not support this.
    fn destroy_workingtree_metadata(&self) -> PyResult<()> {
        Ok(self.0.destroy_workingtree_metadata()?)
    }

    /// Return a format suitable for cloning or sprouting with.
    ///
    /// Args:
    ///     require_stacking: If true, formats that can not stack are upgraded
    ///         to similar formats that can.
    ///
    /// Returns:
    ///     A ControlDirFormat.
    #[pyo3(signature = (require_stacking=false))]
    fn cloning_metadir(&self, py: Python<'_>, require_stacking: bool) -> PyResult<Py<PyAny>> {
        format_to_py(py, self.0.cloning_metadir(require_stacking)?)
    }

    /// Return a format suitable for checkouts of this control directory.
    ///
    /// Returns:
    ///     A ControlDirFormat.
    fn checkout_metadir(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        format_to_py(py, self.0.checkout_metadir()?)
    }

    /// Return the configuration of this control directory.
    ///
    /// Returns:
    ///     A configuration object, such as a ``breezy.config.BzrDirConfig``.
    fn get_config(&self) -> PyResult<Py<PyAny>> {
        Ok(self.0.get_config()?)
    }

    /// Create a copy of this control directory for a new line of development.
    ///
    /// The last component of ``url`` is created if it does not exist. A local
    /// branch is always created; identity settings of the source branch, such
    /// as its nickname, are not copied.
    ///
    /// Args:
    ///     url: The URL to create the copy at.
    ///     revision_id: The revision id, as bytes, to make the tip of the new
    ///         branch, or None for the tip of the source branch.
    ///     force_new_repo: If true, do not use a shared repository for the
    ///         target even if one is available.
    ///     recurse: How to treat nested trees: ``"down"`` to copy them too, or
    ///         ``"none"``.
    ///     accelerator_tree: A tree to take file contents from where they
    ///         match the revision, such as an existing working tree.
    ///     hardlink: If true, hard-link files from ``accelerator_tree`` where
    ///         possible.
    ///     stacked: If true, create a branch stacked on this control
    ///         directory's branch.
    ///     source_branch: The Branch to copy, or None for this control
    ///         directory's branch.
    ///     create_tree_if_local: If true, create a working tree when the
    ///         target is local.
    ///     lossy: If true, allow converting to a format that can not represent
    ///         everything in the source.
    ///
    /// Returns:
    ///     The new control directory.
    #[pyo3(signature = (url, revision_id=None, force_new_repo=false, recurse="down", accelerator_tree=None, hardlink=false, stacked=false, source_branch=None, create_tree_if_local=true, lossy=false))]
    #[allow(clippy::too_many_arguments)]
    fn sprout(
        &self,
        py: Python<'_>,
        url: &str,
        revision_id: Option<Vec<u8>>,
        force_new_repo: bool,
        recurse: &str,
        accelerator_tree: Option<Py<PyAny>>,
        hardlink: bool,
        stacked: bool,
        source_branch: Option<Py<PyAny>>,
        create_tree_if_local: bool,
        lossy: bool,
    ) -> PyResult<Py<PyAny>> {
        let revision_id = self::revision_id(revision_id);
        let accelerator_tree = accelerator_tree.map(PyTree::new);
        let source_branch = source_branch.map(PyBranch::new);
        let options = SproutOptions {
            revision_id: revision_id.as_ref(),
            force_new_repo,
            recurse,
            accelerator_tree: accelerator_tree
                .as_ref()
                .map(|t| t as &(dyn breezy::tree::Tree + Send + Sync)),
            hardlink,
            stacked,
            source_branch: source_branch
                .as_ref()
                .map(|b| b as &(dyn breezy::branch::Branch + Send + Sync)),
            create_tree_if_local,
            lossy,
        };
        controldir_to_py(py, self.0.sprout(url, &options)?)
    }

    /// Copy this control directory and its contents to a URL verbatim.
    ///
    /// Args:
    ///     url: The URL to create the clone at. Its last component is created
    ///         if it does not exist.
    ///     revision_id: The revision id, as bytes, to use as the tip of any
    ///         branch or working tree, or None for the current tip.
    ///     force_new_repo: If true, do not use a shared repository for the
    ///         target even if one is available.
    ///     preserve_stacking: If true, stack a clone of a stacked branch on
    ///         the branch the source is stacked on.
    ///     tag_selector: A callable that takes a tag name and returns whether
    ///         to copy that tag, or None to copy all tags.
    ///
    /// Returns:
    ///     The new control directory.
    #[pyo3(signature = (url, revision_id=None, force_new_repo=false, preserve_stacking=false, tag_selector=None))]
    fn clone(
        &self,
        py: Python<'_>,
        url: &str,
        revision_id: Option<Vec<u8>>,
        force_new_repo: bool,
        preserve_stacking: bool,
        tag_selector: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let revision_id = self::revision_id(revision_id);
        let options = CloneOptions {
            revision_id: revision_id.as_ref(),
            force_new_repo,
            preserve_stacking,
            tag_selector: tag_selector.as_ref(),
        };
        controldir_to_py(py, self.0.clone(url, &options)?)
    }

    /// Copy this control directory and its contents to a transport verbatim.
    ///
    /// Args:
    ///     transport: The Transport to create the clone at. Only its ``base``
    ///         URL is used. The directory is created if it does not exist.
    ///     revision_id: The revision id, as bytes, to use as the tip of any
    ///         branch or working tree, or None for the current tip.
    ///     force_new_repo: If true, do not use a shared repository for the
    ///         target even if one is available.
    ///     preserve_stacking: If true, stack a clone of a stacked branch on
    ///         the branch the source is stacked on.
    ///     stacked_on: The URL to stack the new branch on, or None.
    ///     create_prefix: If true, create missing parent directories of the
    ///         target.
    ///     use_existing_dir: If true, use the target directory if it exists.
    ///     no_tree: If true, do not create a working tree.
    ///     tag_selector: A callable that takes a tag name and returns whether
    ///         to copy that tag, or None to copy all tags.
    ///
    /// Returns:
    ///     The new control directory.
    #[pyo3(signature = (transport, revision_id=None, force_new_repo=false, preserve_stacking=false, stacked_on=None, create_prefix=false, use_existing_dir=true, no_tree=false, tag_selector=None))]
    #[allow(clippy::too_many_arguments)]
    fn clone_on_transport(
        &self,
        py: Python<'_>,
        transport: &Bound<'_, PyAny>,
        revision_id: Option<Vec<u8>>,
        force_new_repo: bool,
        preserve_stacking: bool,
        stacked_on: Option<&str>,
        create_prefix: bool,
        use_existing_dir: bool,
        no_tree: bool,
        tag_selector: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let revision_id = self::revision_id(revision_id);
        let options = CloneOnTransportOptions {
            revision_id: revision_id.as_ref(),
            force_new_repo,
            preserve_stacking,
            stacked_on,
            create_prefix,
            use_existing_dir,
            no_tree,
            tag_selector: tag_selector.as_ref(),
        };
        let dir = self
            .0
            .clone_on_transport(rust_transport(transport)?, &options)?;
        controldir_to_py(py, dir)
    }

    /// Push a branch into this control directory.
    ///
    /// Args:
    ///     source: The Branch to push.
    ///     revision_id: The revision id, as bytes, to push up to, or None for
    ///         the tip of ``source``.
    ///     overwrite: If true, replace diverged history in the target.
    ///     remember: If true, set the target as the push location of
    ///         ``source``.
    ///     create_prefix: If true, create missing parent directories of the
    ///         target.
    ///     lossy: If true, allow converting to a format that can not represent
    ///         everything in ``source``.
    ///     tag_selector: A callable that takes a tag name and returns whether
    ///         to push that tag, or None to push all tags.
    ///     name: The name of the colocated branch to push to, or None for the
    ///         default branch.
    ///
    /// Returns:
    ///     A ``breezy.push.PushResult``.
    #[pyo3(signature = (source, revision_id=None, overwrite=false, remember=false, create_prefix=false, lossy=false, tag_selector=None, name=None))]
    #[allow(clippy::too_many_arguments)]
    fn push_branch(
        &self,
        source: Py<PyAny>,
        revision_id: Option<Vec<u8>>,
        overwrite: bool,
        remember: bool,
        create_prefix: bool,
        lossy: bool,
        tag_selector: Option<Py<PyAny>>,
        name: Option<&str>,
    ) -> PyResult<Py<PyAny>> {
        let revision_id = self::revision_id(revision_id);
        let options = PushOptions {
            revision_id: revision_id.as_ref(),
            overwrite,
            remember,
            create_prefix,
            lossy,
            tag_selector: tag_selector.as_ref(),
            name,
        };
        Ok(self.0.push_branch(&PyBranch::new(source), &options)?)
    }
}

/// A Python prober class and the wrapper it was registered as.
type RegisteredProber = (Py<PyAny>, Arc<dyn Prober>);

/// The Python prober classes registered into the Rust registry, with the
/// wrapper each one was registered as, so it can be unregistered again.
fn registered_probers() -> &'static Mutex<Vec<RegisteredProber>> {
    static REGISTERED: OnceLock<Mutex<Vec<RegisteredProber>>> = OnceLock::new();
    REGISTERED.get_or_init(|| Mutex::new(Vec::new()))
}

/// Register a prober class with ``breezy._cmd_rs``.
///
/// This is called by ``breezy.controldir.ControlDirFormat.register_prober``,
/// so that control directories the prober recognises can also be opened by the
/// commands implemented in ``breezy._cmd_rs``.
///
/// Args:
///     prober: A ``breezy.controldir.Prober`` subclass.
#[pyfunction]
pub(crate) fn register_prober(py: Python<'_>, prober: Py<PyAny>) -> PyResult<()> {
    let wrapped: Arc<dyn Prober> = Arc::new(PyProber::new(prober.clone_ref(py)));
    controldir::register_prober(Arc::clone(&wrapped));
    registered_probers().lock().unwrap().push((prober, wrapped));
    Ok(())
}

/// Unregister a prober class registered with ``register_prober``.
///
/// Args:
///     prober: The ``breezy.controldir.Prober`` subclass.
///
/// Raises:
///     ValueError: If ``prober`` is not registered.
#[pyfunction]
pub(crate) fn unregister_prober(py: Python<'_>, prober: &Bound<'_, PyAny>) -> PyResult<()> {
    let mut registered = registered_probers().lock().unwrap();
    let index = registered
        .iter()
        .position(|(class, _)| class.bind(py).is(prober))
        .ok_or_else(|| PyValueError::new_err(format!("prober {prober} is not registered")))?;
    let (_, wrapped) = registered.remove(index);
    controldir::unregister_prober(&wrapped);
    Ok(())
}

/// Set the format ``breezy._cmd_rs`` creates control directories in.
///
/// This is called by
/// ``breezy.controldir.ControlDirFormat._set_default_format`` and is used when
/// no format is passed to ``ControlDir.create`` and similar functions.
///
/// Args:
///     format: A ``breezy.controldir.ControlDirFormat``, or None to unset the
///         default.
#[pyfunction]
#[pyo3(signature = (format))]
pub(crate) fn set_default_format(format: Option<Py<PyAny>>) {
    controldir::set_default_format(
        format
            .map(|f| Arc::new(PyControlDirFormat::new(f)) as Arc<dyn controldir::ControlDirFormat>),
    );
}

/// Return the format ``breezy._cmd_rs`` creates control directories in.
///
/// Returns:
///     The default ControlDirFormat, or None if none is set.
#[pyfunction]
pub(crate) fn get_default_format(py: Python<'_>) -> PyResult<Option<Py<PyAny>>> {
    match controldir::get_default_format() {
        Ok(format) => match format.python_object() {
            Some(obj) => Ok(Some(obj.clone_ref(py))),
            None => Ok(Some(Py::new(py, ControlDirFormat(format))?.into_any())),
        },
        Err(Error::Other(_)) => Ok(None),
        Err(e) => Err(e.into()),
    }
}
