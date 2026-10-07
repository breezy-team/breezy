//! Control directories: probing, formats and opening.
//!
//! This mirrors ``breezy.controldir``. A [`Prober`] recognises one kind of
//! control directory on a transport and names its [`ControlDirFormat`], which
//! opens (or creates) the [`ControlDir`] giving access to the working tree,
//! branch and repository there. Probers live in a runtime registry: native
//! ones register themselves with [`declare_prober!`], and other
//! implementations of the trait, such as wrappers around Python probers, are
//! added with [`register_prober`]. Nothing here depends on Python.

use crate::branch::Branch;
use crate::repository::Repository;
use crate::tree::{Tree, WorkingTree};
use bazaar::RevisionId;
use dromedary::Transport;
use std::collections::HashMap;
use std::sync::{Arc, OnceLock, RwLock};

/// A handle to an opaque Python object, for the few results (configs, push
/// results, branch formats) that have no native representation yet.
#[cfg(feature = "pyo3")]
pub type PyObject = pyo3::Py<pyo3::PyAny>;

/// The non-pyo3 stand-in for [`PyObject`], so the traits type-check without
/// the `pyo3` feature.
#[cfg(not(feature = "pyo3"))]
pub type PyObject = ();

/// A shared transport, as the openers here take it.
pub type TransportRef = Arc<dyn Transport>;
/// A branch handle as the control directory hands it out.
pub type BranchRef = Box<dyn Branch + Send + Sync>;
/// A repository handle as the control directory hands it out.
pub type RepositoryRef = Box<dyn Repository + Send + Sync>;
/// A working tree handle as the control directory hands it out.
pub type WorkingTreeRef = Box<dyn WorkingTree + Send + Sync>;

/// Errors from locating and opening control directories.
#[derive(Debug)]
pub enum Error {
    /// No control directory was found at `path`.
    NotBranch {
        /// The location probed.
        path: String,
        /// Why, when there is more to say than "nothing there".
        detail: Option<String>,
    },
    /// A control directory was found but its format is not recognised.
    UnknownFormat {
        /// The format marker found.
        format: String,
        /// What kind of object the marker describes (``bzrdir``, ``branch``, ...).
        kind: String,
    },
    /// The control directory at `base` has no working tree.
    NoWorkingTree(String),
    /// The control directory at `path` has no repository.
    NoRepository(String),
    /// The operation needs a local filesystem path but `url` is not local.
    NotLocalUrl(String),
    /// The implementation does not support the operation.
    UnsupportedOperation(String),
    /// The format, named by its description, is not supported.
    UnsupportedFormat(String),
    /// The transport failed.
    Transport(dromedary::Error),
    /// Any other failure.
    Other(String),
    /// A Python exception raised by a Python-backed implementation, carried
    /// as is so it reaches Python again with its type intact.
    #[cfg(feature = "pyo3")]
    Python(pyo3::PyErr),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::NotBranch { path, detail } => {
                write!(f, "Not a branch: \"{path}\"")?;
                if let Some(detail) = detail {
                    write!(f, ": {detail}")?;
                }
                write!(f, ".")
            }
            Error::UnknownFormat { format, kind } => {
                write!(f, "Unknown {kind} format: {format:?}")
            }
            Error::NoWorkingTree(base) => write!(f, "No WorkingTree exists for \"{base}\"."),
            Error::NoRepository(path) => write!(f, "No repository present: \"{path}\""),
            Error::NotLocalUrl(url) => write!(f, "{url} is not a local path."),
            Error::UnsupportedOperation(msg) => write!(f, "Unsupported operation: {msg}"),
            Error::UnsupportedFormat(format) => write!(f, "Unsupported format: {format}"),
            Error::Transport(dromedary::Error::NoSuchFile(path)) => {
                write!(f, "No such file: {}", path.as_deref().unwrap_or(""))
            }
            Error::Transport(dromedary::Error::PermissionDenied(path)) => {
                write!(f, "Permission denied: {}", path.as_deref().unwrap_or(""))
            }
            Error::Transport(e) => write!(f, "{e:?}"),
            Error::Other(msg) => f.write_str(msg),
            #[cfg(feature = "pyo3")]
            Error::Python(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<dromedary::Error> for Error {
    fn from(err: dromedary::Error) -> Self {
        Error::Transport(err)
    }
}

impl From<dromedary::urlutils::Error> for Error {
    fn from(err: dromedary::urlutils::Error) -> Self {
        Error::Transport(err.into())
    }
}

impl From<Error> for crate::tree::Error {
    fn from(err: Error) -> Self {
        match err {
            Error::UnsupportedOperation(msg) => crate::tree::Error::UnsupportedOperation(msg),
            other => crate::tree::Error::Other(other.to_string()),
        }
    }
}

impl From<Error> for crate::branch::Error {
    fn from(err: Error) -> Self {
        match err {
            Error::UnsupportedOperation(msg) => crate::branch::Error::UnsupportedOperation(msg),
            other => crate::branch::Error::Other(other.to_string()),
        }
    }
}

impl From<Error> for crate::repository::Error {
    fn from(err: Error) -> Self {
        match err {
            Error::UnsupportedOperation(msg) => crate::repository::Error::UnsupportedOperation(msg),
            other => crate::repository::Error::Other(other.to_string()),
        }
    }
}

impl From<crate::tree::Error> for Error {
    fn from(err: crate::tree::Error) -> Self {
        match err {
            crate::tree::Error::UnsupportedOperation(msg) => Error::UnsupportedOperation(msg),
            other => Error::Other(other.to_string()),
        }
    }
}

impl From<crate::branch::Error> for Error {
    fn from(err: crate::branch::Error) -> Self {
        match err {
            crate::branch::Error::UnsupportedOperation(msg) => Error::UnsupportedOperation(msg),
            other => Error::Other(other.to_string()),
        }
    }
}

impl From<crate::repository::Error> for Error {
    fn from(err: crate::repository::Error) -> Self {
        match err {
            crate::repository::Error::UnsupportedOperation(msg) => Error::UnsupportedOperation(msg),
            other => Error::Other(other.to_string()),
        }
    }
}

/// The options of [`ControlDir::sprout`].
pub struct SproutOptions<'a> {
    /// The revision to sprout at; the tip when `None`.
    pub revision_id: Option<&'a RevisionId>,
    /// Create a new repository even inside a shared one.
    pub force_new_repo: bool,
    /// How to treat nested trees: ``"down"`` (the default) or ``"none"``.
    pub recurse: &'a str,
    /// A tree to copy file contents from where they match.
    pub accelerator_tree: Option<&'a (dyn Tree + Send + Sync)>,
    /// Hard-link files from the accelerator tree instead of copying.
    pub hardlink: bool,
    /// Stack the new branch on this one.
    pub stacked: bool,
    /// The branch to sprout; the default branch when `None`.
    pub source_branch: Option<&'a (dyn Branch + Send + Sync)>,
    /// Create a working tree when the target is local (the default).
    pub create_tree_if_local: bool,
    /// Allow a lossy conversion between formats.
    pub lossy: bool,
}

impl Default for SproutOptions<'_> {
    fn default() -> Self {
        SproutOptions {
            revision_id: None,
            force_new_repo: false,
            recurse: "down",
            accelerator_tree: None,
            hardlink: false,
            stacked: false,
            source_branch: None,
            create_tree_if_local: true,
            lossy: false,
        }
    }
}

/// The options of [`ControlDir::clone`].
#[derive(Default)]
pub struct CloneOptions<'a> {
    /// The revision to clone up to; the tip when `None`.
    pub revision_id: Option<&'a RevisionId>,
    /// Create a new repository even inside a shared one.
    pub force_new_repo: bool,
    /// Stack the clone where the source is stacked.
    pub preserve_stacking: bool,
    /// A Python callable choosing which tags to copy.
    pub tag_selector: Option<&'a PyObject>,
}

/// The options of [`ControlDir::clone_on_transport`].
pub struct CloneOnTransportOptions<'a> {
    /// The revision to clone up to; the tip when `None`.
    pub revision_id: Option<&'a RevisionId>,
    /// Create a new repository even inside a shared one.
    pub force_new_repo: bool,
    /// Stack the clone where the source is stacked.
    pub preserve_stacking: bool,
    /// The URL to stack the clone on.
    pub stacked_on: Option<&'a str>,
    /// Create the leading directories of the target.
    pub create_prefix: bool,
    /// Allow the target directory to exist already (the default).
    pub use_existing_dir: bool,
    /// Do not create a working tree.
    pub no_tree: bool,
    /// A Python callable choosing which tags to copy.
    pub tag_selector: Option<&'a PyObject>,
}

impl Default for CloneOnTransportOptions<'_> {
    fn default() -> Self {
        CloneOnTransportOptions {
            revision_id: None,
            force_new_repo: false,
            preserve_stacking: false,
            stacked_on: None,
            create_prefix: false,
            use_existing_dir: true,
            no_tree: false,
            tag_selector: None,
        }
    }
}

/// The options of [`ControlDir::push_branch`].
#[derive(Default)]
pub struct PushOptions<'a> {
    /// The revision to push up to; the tip when `None`.
    pub revision_id: Option<&'a RevisionId>,
    /// Replace diverged history on the target.
    pub overwrite: bool,
    /// Record the target as the source's push location.
    pub remember: bool,
    /// Create the leading directories of the target.
    pub create_prefix: bool,
    /// Allow a lossy conversion between formats.
    pub lossy: bool,
    /// A Python callable choosing which tags to push.
    pub tag_selector: Option<&'a PyObject>,
    /// The colocated branch to push to; the default branch when `None`.
    pub name: Option<&'a str>,
}

/// A control directory: the ``.bzr`` or ``.git`` of a location, from which
/// the working tree, branch and repository there are opened.
pub trait ControlDir: Send + Sync {
    /// The Python control directory this one wraps, if it wraps one.
    ///
    /// Bindings use this to hand a Python-backed object back to Python as the
    /// original object rather than as a Rust object proxying to it.
    fn python_object(&self) -> Option<&PyObject> {
        None
    }

    /// The URL of the directory the control directory lives in.
    fn user_url(&self) -> Result<String, Error>;

    /// The URL of the control directory itself (``.bzr/``, ``.git/``).
    fn control_url(&self) -> Result<String, Error>;

    /// The transport rooted at the directory the control directory lives in.
    fn user_transport(&self) -> Result<TransportRef, Error>;

    /// The transport rooted at the control directory itself.
    fn control_transport(&self) -> Result<TransportRef, Error>;

    /// The user transport, under the name Python's ``ControlDir`` uses.
    fn root_transport(&self) -> Result<TransportRef, Error> {
        self.user_transport()
    }

    /// Whether a working tree is present.
    fn has_workingtree(&self) -> Result<bool, Error>;

    /// Whether the branch `name` (the default branch for `None`) is present.
    fn has_branch(&self, name: Option<&str>) -> Result<bool, Error>;

    /// Whether a repository is present.
    fn has_repository(&self) -> Result<bool, Error>;

    /// Open the working tree.
    fn open_workingtree(&self) -> Result<WorkingTreeRef, Error>;

    /// Open the branch `name` (the default branch for `None`).
    fn open_branch(&self, name: Option<&str>) -> Result<BranchRef, Error>;

    /// Open the repository in this control directory.
    fn open_repository(&self) -> Result<RepositoryRef, Error>;

    /// Find the repository serving this control directory, which may be a
    /// shared repository in an enclosing directory.
    fn find_repository(&self) -> Result<RepositoryRef, Error>;

    /// Whether this control directory can be converted to another format.
    fn can_convert_format(&self) -> Result<bool, Error>;

    /// Whether converting to `format` (the default format for `None`) would
    /// change anything.
    fn needs_format_conversion(&self, format: Option<&dyn ControlDirFormat>)
        -> Result<bool, Error>;

    /// Check that this control directory can be converted to `target_format`.
    fn check_conversion_target(&self, target_format: &dyn ControlDirFormat) -> Result<(), Error>;

    /// Whether `filename` names (part of) the control directory itself.
    fn is_control_filename(&self, filename: &str) -> Result<bool, Error>;

    /// The URL the branch `name` refers to, or `None` for a real branch.
    fn get_branch_reference(&self, name: Option<&str>) -> Result<Option<String>, Error>;

    /// Make the branch `name` a reference to `target_branch`, returning the
    /// reference branch.
    fn set_branch_reference(
        &self,
        target_branch: &(dyn Branch + Send + Sync),
        name: Option<&str>,
    ) -> Result<BranchRef, Error>;

    /// The format of the branch `name`, as a Python branch format object.
    fn find_branch_format(&self, name: Option<&str>) -> Result<PyObject, Error>;

    /// The names of the branches in this control directory.
    fn branch_names(&self) -> Result<Vec<String>, Error> {
        match self.get_branch_reference(None) {
            Ok(_) => Ok(vec![String::new()]),
            Err(Error::NotBranch { .. }) | Err(Error::NoRepository(_)) => Ok(Vec::new()),
            Err(e) => Err(e),
        }
    }

    /// The branches in this control directory, by name.
    fn get_branches(&self) -> Result<HashMap<String, BranchRef>, Error> {
        match self.open_branch(None) {
            Ok(branch) => Ok(HashMap::from([(String::new(), branch)])),
            Err(Error::NotBranch { .. }) | Err(Error::NoRepository(_)) => Ok(HashMap::new()),
            Err(e) => Err(e),
        }
    }

    /// The branches in this control directory.
    fn list_branches(&self) -> Result<Vec<BranchRef>, Error> {
        Ok(self.get_branches()?.into_values().collect())
    }

    /// Create a repository here, shared with branches below it if `shared`.
    fn create_repository(&self, shared: bool) -> Result<RepositoryRef, Error>;

    /// Delete the repository here.
    fn destroy_repository(&self) -> Result<(), Error>;

    /// Create the branch `name` (the default branch for `None`), in
    /// `repository` or the one found for this control directory.
    fn create_branch(
        &self,
        name: Option<&str>,
        repository: Option<&(dyn Repository + Send + Sync)>,
        append_revisions_only: Option<bool>,
    ) -> Result<BranchRef, Error>;

    /// Delete the branch `name` (the default branch for `None`).
    fn destroy_branch(&self, name: Option<&str>) -> Result<(), Error>;

    /// Create a working tree, at `revision_id` or the branch tip.
    fn create_workingtree(
        &self,
        revision_id: Option<&RevisionId>,
        from_branch: Option<&(dyn Branch + Send + Sync)>,
        accelerator_tree: Option<&(dyn Tree + Send + Sync)>,
        hardlink: bool,
    ) -> Result<WorkingTreeRef, Error>;

    /// Delete the working tree, including its files.
    fn destroy_workingtree(&self) -> Result<(), Error>;

    /// Forget the working tree without touching its files.
    fn destroy_workingtree_metadata(&self) -> Result<(), Error>;

    /// The format to clone this control directory into.
    fn cloning_metadir(&self, require_stacking: bool) -> Result<Box<dyn ControlDirFormat>, Error>;

    /// The format to create checkouts of this control directory in.
    fn checkout_metadir(&self) -> Result<Box<dyn ControlDirFormat>, Error>;

    /// The configuration of this control directory, as a Python object.
    fn get_config(&self) -> Result<PyObject, Error>;

    /// Create a copy of this control directory at `url` with its own
    /// history, as ``brz branch`` does.
    fn sprout(&self, url: &str, options: &SproutOptions<'_>) -> Result<Box<dyn ControlDir>, Error>;

    /// Create an exact copy of this control directory at `url`.
    fn clone(&self, url: &str, options: &CloneOptions<'_>) -> Result<Box<dyn ControlDir>, Error>;

    /// Create an exact copy of this control directory at `transport`.
    fn clone_on_transport(
        &self,
        transport: Arc<dyn Transport>,
        options: &CloneOnTransportOptions<'_>,
    ) -> Result<Box<dyn ControlDir>, Error>;

    /// Push `source` into this control directory, returning the Python
    /// push result.
    fn push_branch(
        &self,
        source: &(dyn Branch + Send + Sync),
        options: &PushOptions<'_>,
    ) -> Result<PyObject, Error>;
}

/// A kind of control directory, able to open or create one.
pub trait ControlDirFormat: Send + Sync {
    /// The Python format this one wraps, if it wraps one.
    fn python_object(&self) -> Option<&PyObject> {
        None
    }

    /// A short description of the format for the user.
    fn get_format_description(&self) -> Result<String, Error>;

    /// Whether this format can be written to and read from.
    fn is_supported(&self) -> Result<bool, Error> {
        Ok(true)
    }

    /// Fail unless the format is supported, or `allow_unsupported` is set.
    fn check_support_status(&self, allow_unsupported: bool) -> Result<(), Error> {
        if allow_unsupported || self.is_supported()? {
            Ok(())
        } else {
            Err(Error::UnsupportedFormat(self.get_format_description()?))
        }
    }

    /// Open the control directory of this format at `transport`.
    fn open(&self, transport: Arc<dyn Transport>) -> Result<Box<dyn ControlDir>, Error>;

    /// Create an empty control directory of this format at `transport`.
    fn initialize_on_transport(
        &self,
        transport: Arc<dyn Transport>,
    ) -> Result<Box<dyn ControlDir>, Error>;

    /// Create an empty control directory of this format at `location`.
    fn initialize(&self, location: &str) -> Result<Box<dyn ControlDir>, Error> {
        self.initialize_on_transport(get_transport(location)?)
    }
}

/// Detects one kind of control directory.
pub trait Prober: Send + Sync {
    /// The format of the control directory at `transport`.
    ///
    /// Errors with [`Error::NotBranch`] when there is none of this prober's
    /// kind, and [`Error::UnknownFormat`] when there is one in a format the
    /// prober does not know.
    fn probe_transport(
        &self,
        transport: &dyn Transport,
    ) -> Result<Box<dyn ControlDirFormat>, Error>;

    /// The order in which probers are tried: lower first. By convention -10
    /// for a server prober, 10 for a regular file-based one, 100 for one that
    /// detects unsupported formats, 0 otherwise.
    fn priority(&self, transport: &dyn Transport) -> Result<i32, Error> {
        let _ = transport;
        Ok(0)
    }
}

/// A native prober's registration, collected by the [`inventory`] crate.
pub struct ProberRegistration {
    /// Builds the prober.
    pub factory: fn() -> Arc<dyn Prober>,
}

inventory::collect!(ProberRegistration);

/// Register a native prober so [`all_probers`] includes it.
///
/// The argument is a type implementing [`Prober`] and `Default`.
#[macro_export]
macro_rules! declare_prober {
    ($prober:ty) => {
        $crate::__inventory::submit! {
            $crate::controldir::ProberRegistration {
                factory: || ::std::sync::Arc::new(<$prober>::default()) as ::std::sync::Arc<dyn $crate::controldir::Prober>,
            }
        }
    };
}

/// The probers registered natively with [`declare_prober!`].
pub fn native_probers() -> Vec<Arc<dyn Prober>> {
    inventory::iter::<ProberRegistration>()
        .map(|registration| (registration.factory)())
        .collect()
}

fn registry() -> &'static RwLock<Vec<Arc<dyn Prober>>> {
    static REGISTRY: OnceLock<RwLock<Vec<Arc<dyn Prober>>>> = OnceLock::new();
    REGISTRY.get_or_init(|| RwLock::new(native_probers()))
}

/// Add `prober` after the ones already registered.
pub fn register_prober(prober: Arc<dyn Prober>) {
    registry().write().unwrap().push(prober);
}

/// Remove the registration of `prober`, returning whether it was registered.
pub fn unregister_prober(prober: &Arc<dyn Prober>) -> bool {
    let mut probers = registry().write().unwrap();
    let before = probers.len();
    probers.retain(|p| !Arc::ptr_eq(p, prober));
    probers.len() != before
}

/// All registered probers, in registration order.
pub fn all_probers() -> Vec<Arc<dyn Prober>> {
    registry().read().unwrap().clone()
}

fn default_format() -> &'static RwLock<Option<Arc<dyn ControlDirFormat>>> {
    static DEFAULT: OnceLock<RwLock<Option<Arc<dyn ControlDirFormat>>>> = OnceLock::new();
    DEFAULT.get_or_init(|| RwLock::new(None))
}

/// Make `format` the one [`create`] uses when no format is given.
pub fn set_default_format(format: Option<Arc<dyn ControlDirFormat>>) {
    *default_format().write().unwrap() = format;
}

/// The format [`create`] uses when no format is given.
pub fn get_default_format() -> Result<Arc<dyn ControlDirFormat>, Error> {
    default_format()
        .read()
        .unwrap()
        .clone()
        .ok_or_else(|| Error::Other("no default control directory format is set".to_string()))
}

fn not_branch(path: impl std::fmt::Display) -> Error {
    Error::NotBranch {
        path: path.to_string(),
        detail: None,
    }
}

/// The format of the control directory at `transport`, asking `probers` in
/// priority order.
pub fn find_format_with(
    transport: &dyn Transport,
    probers: &[Arc<dyn Prober>],
) -> Result<Box<dyn ControlDirFormat>, Error> {
    let mut ordered = probers
        .iter()
        .map(|p| Ok((p.priority(transport)?, p)))
        .collect::<Result<Vec<_>, Error>>()?;
    // A stable sort keeps registration order among equal priorities, so a
    // native prober registered first wins over a later one for the same kind.
    ordered.sort_by_key(|(priority, _)| *priority);
    for (_, prober) in ordered {
        match prober.probe_transport(transport) {
            Err(Error::NotBranch { .. }) => continue,
            result => return result,
        }
    }
    Err(not_branch(transport.base()))
}

/// The format of the control directory at `transport`, asking every
/// registered prober.
pub fn find_format(transport: &dyn Transport) -> Result<Box<dyn ControlDirFormat>, Error> {
    find_format_with(transport, &all_probers())
}

/// Open the control directory at `transport` using `probers`, refusing an
/// unsupported format unless `allow_unsupported`.
pub fn open_from_transport_with(
    transport: Arc<dyn Transport>,
    probers: &[Arc<dyn Prober>],
    allow_unsupported: bool,
) -> Result<Box<dyn ControlDir>, Error> {
    let format = find_format_with(transport.as_ref(), probers)?;
    format.check_support_status(allow_unsupported)?;
    format.open(transport)
}

/// Open the control directory at `transport`.
pub fn open_from_transport(transport: Arc<dyn Transport>) -> Result<Box<dyn ControlDir>, Error> {
    open_from_transport_with(transport, &all_probers(), false)
}

/// Open the control directory containing `transport`, searching upwards from
/// it with `probers`.
///
/// Returns the control directory and the part of the starting URL below it.
pub fn open_containing_from_transport_with(
    transport: Arc<dyn Transport>,
    probers: &[Arc<dyn Prober>],
) -> Result<(Box<dyn ControlDir>, String), Error> {
    let url = transport.base();
    let mut transport = transport;
    loop {
        match open_from_transport_with(Arc::clone(&transport), probers, false) {
            Ok(dir) => {
                let relpath = transport.relpath(&url)?;
                return Ok((dir, dromedary::urlutils::unescape(&relpath)?));
            }
            // Keep looking upwards, as the Python code does, past a directory
            // that is not a control directory or that cannot be read.
            Err(Error::NotBranch { .. })
            | Err(Error::Transport(dromedary::Error::PermissionDenied(_))) => {}
            Err(e) => return Err(e),
        }
        let parent = match Transport::clone(transport.as_ref(), Some("..")) {
            Ok(parent) => parent,
            Err(dromedary::Error::UrlutilsError(_)) => return Err(not_branch(&url)),
            Err(e) => return Err(e.into()),
        };
        if parent.base() == transport.base() {
            return Err(not_branch(&url));
        }
        transport = Arc::from(parent);
    }
}

/// Open the control directory containing `transport`, searching upwards from
/// it with every registered prober.
pub fn open_containing_from_transport(
    transport: Arc<dyn Transport>,
) -> Result<(Box<dyn ControlDir>, String), Error> {
    open_containing_from_transport_with(transport, &all_probers())
}

/// The URL for a location given by the user: a URL as it is, anything else
/// as a local path.
///
/// TODO: ``breezy.location.location_to_url`` also runs the ``rewrite_location``
/// hooks and resolves directory services (``lp:...``) and rcp-style
/// ``host:path`` locations. Those are not available natively yet.
pub fn location_to_url(location: &str) -> Result<String, Error> {
    if dromedary::urlutils::is_url(location) {
        return Ok(location.to_string());
    }
    dromedary::urlutils::local_path_to_url(location).map_err(|e| Error::Other(e.to_string()))
}

/// A transport for the user-given `location`.
pub fn get_transport(location: &str) -> Result<Arc<dyn Transport>, Error> {
    let url = location_to_url(location)?;
    let transport: Box<dyn Transport> = dromedary::registry::get_transport(&url)?;
    Ok(Arc::from(transport))
}

/// Open the control directory at `location`.
pub fn open(location: &str) -> Result<Box<dyn ControlDir>, Error> {
    open_from_transport(get_transport(location)?)
}

/// Open the control directory at `location` even if its format is not
/// supported.
pub fn open_unsupported(location: &str) -> Result<Box<dyn ControlDir>, Error> {
    open_from_transport_with(get_transport(location)?, &all_probers(), true)
}

/// Open the control directory containing `location`, searching upwards.
///
/// Returns the control directory and the part of `location` below it.
pub fn open_containing(location: &str) -> Result<(Box<dyn ControlDir>, String), Error> {
    open_containing_from_transport(get_transport(location)?)
}

/// The working tree, if any, and the branch `name` of `dir`.
///
/// The Python version takes the branch from the tree when there is one and
/// no name is given; opening the control directory's branch gives the same
/// branch without depending on the tree implementation to supply it.
fn tree_and_branch(
    dir: &dyn ControlDir,
    name: Option<&str>,
) -> Result<(Option<WorkingTreeRef>, BranchRef), Error> {
    let tree = match dir.open_workingtree() {
        Ok(tree) => Some(tree),
        Err(Error::NoWorkingTree(_)) | Err(Error::NotLocalUrl(_)) => None,
        Err(e) => return Err(e),
    };
    Ok((tree, dir.open_branch(name)?))
}

/// The working tree, if any, and the branch `name` at `location`.
pub fn open_tree_or_branch(
    location: &str,
    name: Option<&str>,
) -> Result<(Option<WorkingTreeRef>, BranchRef), Error> {
    tree_and_branch(open(location)?.as_ref(), name)
}

/// The working tree, if any, and the branch containing `location`, with the
/// part of `location` below them.
pub fn open_containing_tree_or_branch(
    location: &str,
) -> Result<(Option<WorkingTreeRef>, BranchRef, String), Error> {
    let (dir, relpath) = open_containing(location)?;
    let (tree, branch) = tree_and_branch(dir.as_ref(), None)?;
    Ok((tree, branch, relpath))
}

/// The working tree and branch, if any, and the repository containing
/// `location`, with the part of `location` below them.
///
/// A location inside a shared repository with no branch yields only the
/// repository.
#[allow(clippy::type_complexity)]
pub fn open_containing_tree_branch_or_repository(
    location: &str,
) -> Result<
    (
        Option<WorkingTreeRef>,
        Option<BranchRef>,
        RepositoryRef,
        String,
    ),
    Error,
> {
    let (dir, relpath) = open_containing(location)?;
    match tree_and_branch(dir.as_ref(), None) {
        Ok((tree, branch)) => {
            let repository = dir.find_repository()?;
            Ok((tree, Some(branch), repository, relpath))
        }
        Err(Error::NotBranch { .. }) => match dir.find_repository() {
            Ok(repository) => Ok((None, None, repository, relpath)),
            Err(Error::NoRepository(_)) => Err(not_branch(location)),
            Err(e) => Err(e),
        },
        Err(e) => Err(e),
    }
}

/// Create a control directory at `location`, in `format` or the default one.
pub fn create(
    location: &str,
    format: Option<&dyn ControlDirFormat>,
) -> Result<Box<dyn ControlDir>, Error> {
    let transport = get_transport(location)?;
    transport.ensure_base(None)?;
    match format {
        Some(format) => format.initialize_on_transport(transport),
        None => get_default_format()?.initialize_on_transport(transport),
    }
}

fn find_or_create_repository(
    dir: &dyn ControlDir,
    force_new_repo: bool,
) -> Result<RepositoryRef, Error> {
    if force_new_repo {
        return dir.create_repository(false);
    }
    match dir.find_repository() {
        Ok(repository) => Ok(repository),
        Err(Error::NoRepository(_)) => dir.create_repository(false),
        Err(e) => Err(e),
    }
}

/// Create a control directory with a branch at `location`, in a new
/// repository or the enclosing shared one.
pub fn create_branch_and_repo(
    location: &str,
    force_new_repo: bool,
    format: Option<&dyn ControlDirFormat>,
) -> Result<BranchRef, Error> {
    let dir = create(location, format)?;
    find_or_create_repository(dir.as_ref(), force_new_repo)?;
    dir.create_branch(None, None, None)
}

fn require_local(location: &str) -> Result<(), Error> {
    match get_transport(location)?.local_abspath("") {
        Ok(_) => Ok(()),
        Err(dromedary::Error::NotLocalUrl(_)) => Err(Error::NotLocalUrl(location.to_string())),
        Err(e) => Err(e.into()),
    }
}

/// Create a branch at `location` with a working tree where the repository
/// makes them (or as `force_new_tree` says), as ``brz init`` does.
pub fn create_branch_convenience(
    location: &str,
    force_new_repo: bool,
    force_new_tree: Option<bool>,
    format: Option<&dyn ControlDirFormat>,
) -> Result<BranchRef, Error> {
    if force_new_tree == Some(true) {
        require_local(location)?;
    }
    let dir = create(location, format)?;
    let repository = find_or_create_repository(dir.as_ref(), force_new_repo)?;
    let branch = dir.create_branch(None, None, None)?;
    let want_tree = match force_new_tree {
        Some(force) => force,
        None => repository.make_working_trees()?,
    };
    if want_tree {
        match dir.create_workingtree(None, None, None, false) {
            Ok(_) | Err(Error::NotLocalUrl(_)) => {}
            Err(e) => return Err(e),
        }
    }
    Ok(branch)
}

/// Create a branch with its own repository and a working tree at the local
/// `location`.
pub fn create_standalone_workingtree(
    location: &str,
    format: Option<&dyn ControlDirFormat>,
) -> Result<WorkingTreeRef, Error> {
    require_local(location)?;
    let branch = create_branch_and_repo(location, true, format)?;
    branch
        .controldir()?
        .create_workingtree(None, None, None, false)
}

/// Find the control directories at and below `transport`.
///
/// `evaluate` is called with each one and returns whether to look below it
/// and the value to collect for it.
pub fn find_controldirs<T>(
    transport: Arc<dyn Transport>,
    mut evaluate: impl FnMut(Box<dyn ControlDir>) -> Result<(bool, T), Error>,
) -> Result<Vec<T>, Error> {
    let mut found = Vec::new();
    let mut pending = vec![transport];
    while let Some(current) = pending.pop() {
        let mut recurse = true;
        match open_from_transport(Arc::clone(&current)) {
            Ok(dir) => {
                let (below, value) = evaluate(dir)?;
                recurse = below;
                found.push(value);
            }
            Err(Error::NotBranch { .. })
            | Err(Error::UnknownFormat { .. })
            | Err(Error::Transport(dromedary::Error::PermissionDenied(_))) => {}
            Err(e) => return Err(e),
        }
        let subdirs: Result<Vec<String>, dromedary::Error> = current.list_dir("").collect();
        let mut subdirs = match subdirs {
            Ok(subdirs) => subdirs,
            // Entries that are not directories are listed with the rest and
            // cannot be descended into; Python's local transport reports
            // them as missing, so they are skipped here the same way.
            Err(dromedary::Error::NoSuchFile(_))
            | Err(dromedary::Error::NotADirectoryError(_))
            | Err(dromedary::Error::PermissionDenied(_)) => continue,
            Err(e) => return Err(e.into()),
        };
        if recurse {
            // Pushed in reverse so they are visited in sorted order.
            subdirs.sort();
            for subdir in subdirs.into_iter().rev() {
                pending.push(Arc::from(Transport::clone(
                    current.as_ref(),
                    Some(&subdir),
                )?));
            }
        }
    }
    Ok(found)
}

/// The branches at and below `transport`.
///
/// Python hands a repository it finds the walk below it; for a local
/// repository that is the same walk, so it is done here directly.
pub fn find_branches(transport: Arc<dyn Transport>) -> Result<Vec<BranchRef>, Error> {
    let found = find_controldirs(transport, |dir| Ok((true, dir.list_branches()?)))?;
    Ok(found.into_iter().flatten().collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    struct MockProber {
        priority: i32,
        claims: Option<&'static str>,
    }

    impl Prober for MockProber {
        fn probe_transport(
            &self,
            transport: &dyn Transport,
        ) -> Result<Box<dyn ControlDirFormat>, Error> {
            match self.claims {
                Some(name) => Ok(Box::new(MockFormat(name))),
                None => Err(not_branch(transport.base())),
            }
        }

        fn priority(&self, _transport: &dyn Transport) -> Result<i32, Error> {
            Ok(self.priority)
        }
    }

    struct MockFormat(&'static str);

    impl ControlDirFormat for MockFormat {
        fn get_format_description(&self) -> Result<String, Error> {
            Ok(self.0.to_string())
        }

        fn open(&self, _transport: Arc<dyn Transport>) -> Result<Box<dyn ControlDir>, Error> {
            Err(Error::Other("mock formats do not open".to_string()))
        }

        fn initialize_on_transport(
            &self,
            _transport: Arc<dyn Transport>,
        ) -> Result<Box<dyn ControlDir>, Error> {
            Err(Error::Other("mock formats do not initialize".to_string()))
        }
    }

    fn file_url(path: &Path) -> String {
        dromedary::urlutils::local_path_to_url(path).unwrap()
    }

    #[test]
    fn find_format_tries_probers_by_priority() {
        let dir = tempfile::tempdir().unwrap();
        let transport = get_transport(&file_url(dir.path())).unwrap();
        let probers: Vec<Arc<dyn Prober>> = vec![
            Arc::new(MockProber {
                priority: 10,
                claims: Some("file"),
            }),
            Arc::new(MockProber {
                priority: -10,
                claims: None,
            }),
            Arc::new(MockProber {
                priority: 0,
                claims: Some("default"),
            }),
        ];
        let format = find_format_with(transport.as_ref(), &probers).unwrap();
        assert_eq!("default", format.get_format_description().unwrap());
    }

    #[test]
    fn find_format_without_a_taker_is_not_a_branch() {
        let dir = tempfile::tempdir().unwrap();
        let transport = get_transport(&file_url(dir.path())).unwrap();
        let probers: Vec<Arc<dyn Prober>> = vec![Arc::new(MockProber {
            priority: 0,
            claims: None,
        })];
        let Err(err) = find_format_with(transport.as_ref(), &probers) else {
            panic!("a declining prober found a format");
        };
        assert_eq!(
            format!("Not a branch: \"{}\".", transport.base()),
            err.to_string()
        );
    }

    #[test]
    fn register_and_unregister_prober() {
        let prober: Arc<dyn Prober> = Arc::new(MockProber {
            priority: 0,
            claims: None,
        });
        register_prober(Arc::clone(&prober));
        assert!(all_probers().iter().any(|p| Arc::ptr_eq(p, &prober)));
        assert!(unregister_prober(&prober));
        assert!(!all_probers().iter().any(|p| Arc::ptr_eq(p, &prober)));
        assert!(!unregister_prober(&prober));
    }

    #[test]
    fn create_without_default_format_fails() {
        let dir = tempfile::tempdir().unwrap();
        let location = dir.path().join("new").to_str().unwrap().to_string();
        let Err(err) = create(&location, None) else {
            panic!("created a control directory without a format");
        };
        assert_eq!(
            "no default control directory format is set",
            err.to_string()
        );
    }

    #[test]
    fn location_to_url_cases() {
        assert_eq!(
            "http://example.com/x",
            location_to_url("http://example.com/x").unwrap()
        );
        let url = location_to_url("some/dir").unwrap();
        assert!(url.starts_with("file:///"), "{url}");
        assert!(url.ends_with("/some/dir"), "{url}");
    }
}
