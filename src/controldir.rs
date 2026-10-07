//! Control directories: probing, formats and opening.
//!
//! This mirrors ``breezy.controldir``. A [`Prober`] recognises one kind of
//! control directory on a transport and names its [`ControlDirFormat`], which
//! opens the [`ControlDir`] giving access to the working tree, branch and
//! repository there. Probers live in a runtime registry: native ones register
//! themselves with [`declare_prober!`], and other implementations of the
//! trait, such as wrappers around Python probers, are added with
//! [`register_prober`]. Nothing here depends on Python.

use crate::branch::Branch;
use crate::repository::Repository;
use crate::tree::WorkingTree;
use dromedary::Transport;
use std::sync::{Arc, OnceLock, RwLock};

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

/// A control directory: the ``.bzr`` or ``.git`` of a location, from which
/// the working tree, branch and repository there are opened.
pub trait ControlDir: Send + Sync {
    /// The URL of the directory the control directory lives in.
    fn user_url(&self) -> Result<String, Error>;

    /// Whether a working tree is present.
    fn has_workingtree(&self) -> Result<bool, Error>;

    /// Whether the branch `name` (the default branch for `None`) is present.
    fn has_branch(&self, name: Option<&str>) -> Result<bool, Error>;

    /// Whether a repository is present.
    fn has_repository(&self) -> Result<bool, Error>;

    /// Open the working tree.
    fn open_workingtree(&self) -> Result<Box<dyn WorkingTree + Send + Sync>, Error>;

    /// Open the branch `name` (the default branch for `None`).
    fn open_branch(&self, name: Option<&str>) -> Result<Box<dyn Branch + Send + Sync>, Error>;

    /// Open the repository in this control directory.
    fn open_repository(&self) -> Result<Box<dyn Repository + Send + Sync>, Error>;

    /// Find the repository serving this control directory, which may be a
    /// shared repository in an enclosing directory.
    fn find_repository(&self) -> Result<Box<dyn Repository + Send + Sync>, Error>;
}

/// A kind of control directory, able to open one found by its [`Prober`].
pub trait ControlDirFormat: Send + Sync {
    /// A short description of the format for the user.
    fn get_format_description(&self) -> Result<String, Error>;

    /// Open the control directory of this format at `transport`.
    fn open(&self, transport: Arc<dyn Transport>) -> Result<Box<dyn ControlDir>, Error>;
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

/// Open the control directory at `transport` using `probers`.
pub fn open_from_transport_with(
    transport: Arc<dyn Transport>,
    probers: &[Arc<dyn Prober>],
) -> Result<Box<dyn ControlDir>, Error> {
    find_format_with(transport.as_ref(), probers)?.open(transport)
}

/// Open the control directory at `transport`.
pub fn open_from_transport(transport: Arc<dyn Transport>) -> Result<Box<dyn ControlDir>, Error> {
    open_from_transport_with(transport, &all_probers())
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
        match open_from_transport_with(Arc::clone(&transport), probers) {
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

/// Open the control directory containing `location`, searching upwards.
///
/// Returns the control directory and the part of `location` below it.
pub fn open_containing(location: &str) -> Result<(Box<dyn ControlDir>, String), Error> {
    open_containing_from_transport(get_transport(location)?)
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
