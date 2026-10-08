//! Locks on branches, repositories and trees, as ``breezy.lock`` and the
//! ``lock_read``/``lock_write`` methods describe them.
//!
//! Locking an object returns a lock handle. As in Python, the object
//! counts its locks and ``unlock`` on the object releases one; a handle
//! releases the lock it stands for when unlocked or dropped, or can be
//! detached to leave that to the object's ``unlock``.

use crate::tree::PyObject;

/// A lock token: the nonce of a physical lock, which lets another holder
/// take over a lock that is held already.
pub type LockToken = Vec<u8>;

/// Why a lock operation failed.
#[derive(Debug)]
pub enum Error {
    /// The lock is held by someone else (``LockContention``).
    Contention {
        /// The lock, for display.
        lock: String,
        /// Who holds it, if known.
        msg: String,
    },
    /// An unlock was attempted on something that was not locked
    /// (``LockNotHeld``).
    NotHeld(String),
    /// A write lock was requested on an object that is read-locked
    /// (``ReadOnlyError``).
    ReadOnly(String),
    /// The token given does not match the lock that is held
    /// (``TokenMismatch``).
    TokenMismatch {
        /// The token given.
        given: LockToken,
        /// The token of the held lock, if one is held.
        held: Option<LockToken>,
    },
    /// The lock could not be created or taken for a reason other than
    /// contention (``LockFailed``).
    Failed {
        /// The lock, for display.
        lock: String,
        /// Why.
        why: String,
    },
    /// The operation is not supported by this implementation.
    UnsupportedOperation(String),
    /// Any other failure.
    Other(String),
    /// A Python exception raised by a Python-backed implementation.
    #[cfg(feature = "pyo3")]
    Python(pyo3::PyErr),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Contention { lock, msg } => {
                write!(f, "Could not acquire lock \"{lock}\": {msg}")
            }
            Error::NotHeld(lock) => write!(f, "Lock not held: {lock}"),
            Error::ReadOnly(obj) => {
                write!(
                    f,
                    "A write attempt was made in a read only transaction on {obj}"
                )
            }
            Error::TokenMismatch { given, held } => write!(
                f,
                "The lock token {:?} does not match lock token {:?}.",
                String::from_utf8_lossy(given),
                held.as_ref()
                    .map(|held| String::from_utf8_lossy(held).into_owned())
            ),
            Error::Failed { lock, why } => write!(f, "Cannot lock {lock}: {why}"),
            Error::UnsupportedOperation(msg) => write!(f, "Unsupported operation: {msg}"),
            Error::Other(msg) => f.write_str(msg),
            #[cfg(feature = "pyo3")]
            Error::Python(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for Error {}

/// A held lock.
pub trait Lock: Send {
    /// Release the lock, as calling ``unlock`` on Python's lock result does.
    fn unlock(self: Box<Self>) -> Result<(), Error>;

    /// Stop tracking the lock without releasing it; the locked object's own
    /// ``unlock`` releases it, as Python callers that ignore the lock result
    /// do.
    fn detach(self: Box<Self>);

    /// The Python lock result behind this lock, if it is Python-backed.
    fn python_object(&self) -> Option<&PyObject> {
        None
    }
}

/// A held read lock.
pub trait ReadLock: Lock {}

/// A held write lock.
pub trait WriteLock: Lock {
    /// The token of the physical lock, for objects that take one.
    fn token(&self) -> Option<&[u8]>;
}

/// An owned read lock of any implementation.
pub type ReadLockRef = Box<dyn ReadLock>;

/// An owned write lock of any implementation.
pub type WriteLockRef = Box<dyn WriteLock>;

macro_rules! from_object_error {
    ($($module:ident),*) => {$(
        impl From<crate::$module::Error> for Error {
            /// A failure to reach the object to lock, such as opening its
            /// repository.
            fn from(err: crate::$module::Error) -> Self {
                match err {
                    #[cfg(feature = "pyo3")]
                    crate::$module::Error::Python(e) => Error::Python(e),
                    other => Error::Other(other.to_string()),
                }
            }
        }
    )*};
}

from_object_error!(branch, repository, tree, controldir);
