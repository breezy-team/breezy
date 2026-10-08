//! Python lock results as implementations of the [`crate::lock`] traits.

use crate::lock::{Error, Lock, LockToken, ReadLock, WriteLock};
use crate::tree::PyObject;
use pyo3::import_exception;
use pyo3::prelude::*;

import_exception!(breezy.errors, LockContention);
import_exception!(breezy.errors, LockNotHeld);
import_exception!(breezy.errors, ReadOnlyError);
import_exception!(breezy.errors, TokenMismatch);
import_exception!(breezy.errors, LockFailed);

/// A lock result returned by a Python object's ``lock_read`` or
/// ``lock_write``: a ``LogicalLockResult``, ``BranchWriteLockResult`` or
/// ``RepositoryWriteLockResult``.
pub struct PyLock {
    result: Option<PyObject>,
    token: Option<LockToken>,
}

impl PyLock {
    /// Wrap the Python lock result `result`.
    pub fn new(result: &Bound<'_, PyAny>) -> PyResult<Self> {
        // Branches record the token as ``token``, repositories as
        // ``repository_token``.
        let mut token = None;
        for name in ["token", "repository_token"] {
            if let Ok(value) = result.getattr(name) {
                if !value.is_none() {
                    token = Some(value.extract()?);
                    break;
                }
            }
        }
        Ok(PyLock {
            result: Some(result.clone().unbind()),
            token,
        })
    }

    fn release(&mut self) -> Result<(), Error> {
        let Some(result) = self.result.take() else {
            return Ok(());
        };
        Python::attach(|py| {
            result
                .bind(py)
                .call_method0("unlock")
                .map(|_| ())
                .map_err(Error::Python)
        })
    }
}

impl Lock for PyLock {
    fn unlock(mut self: Box<Self>) -> Result<(), Error> {
        self.release()
    }

    fn detach(mut self: Box<Self>) {
        self.result = None;
    }

    fn python_object(&self) -> Option<&PyObject> {
        self.result.as_ref()
    }
}

impl ReadLock for PyLock {}

impl WriteLock for PyLock {
    fn token(&self) -> Option<&[u8]> {
        self.token.as_deref()
    }
}

impl Drop for PyLock {
    /// Released when dropped, with a failure logged as there is no caller
    /// left to report it to.
    fn drop(&mut self) {
        if let Err(e) = self.release() {
            log::warn!(target: "brz", "failed to release lock: {e}");
        }
    }
}

impl From<Error> for PyErr {
    fn from(err: Error) -> PyErr {
        match err {
            Error::Contention { lock, msg } => LockContention::new_err((lock, msg)),
            Error::NotHeld(lock) => LockNotHeld::new_err((lock,)),
            Error::ReadOnly(obj) => ReadOnlyError::new_err((obj,)),
            Error::TokenMismatch { given, held } => Python::attach(|py| {
                TokenMismatch::new_err((
                    pyo3::types::PyBytes::new(py, &given).unbind(),
                    held.map(|held| pyo3::types::PyBytes::new(py, &held).unbind()),
                ))
            }),
            Error::Failed { lock, why } => LockFailed::new_err((lock, why)),
            Error::UnsupportedOperation(msg) => {
                Python::attach(|py| crate::pyerrors::unsupported_operation(py, &msg))
            }
            Error::Other(msg) => pyo3::exceptions::PyRuntimeError::new_err(msg),
            Error::Python(e) => e,
        }
    }
}

/// Call `method` on `obj` with `args` and wrap the lock result it returns.
fn take_lock(
    obj: &PyObject,
    method: &str,
    args: impl for<'py> pyo3::call::PyCallArgs<'py>,
) -> Result<PyLock, Error> {
    Python::attach(|py| {
        obj.bind(py)
            .call_method1(method, args)
            .and_then(|result| PyLock::new(&result))
            .map_err(Error::Python)
    })
}

/// ``obj.lock_read()``.
pub fn lock_read(obj: &PyObject) -> Result<crate::lock::ReadLockRef, Error> {
    Ok(Box::new(take_lock(obj, "lock_read", ())?))
}

/// ``obj.<method>()`` for a write lock without a token, such as a working
/// tree's ``lock_write`` or ``lock_tree_write``.
pub fn lock_write(obj: &PyObject, method: &str) -> Result<crate::lock::WriteLockRef, Error> {
    Ok(Box::new(take_lock(obj, method, ())?))
}

/// ``obj.lock_write(token=token)`` for branches and repositories.
pub fn lock_write_with_token(
    obj: &PyObject,
    token: Option<&[u8]>,
) -> Result<crate::lock::WriteLockRef, Error> {
    let token =
        Python::attach(|py| token.map(|token| pyo3::types::PyBytes::new(py, token).unbind()));
    Ok(Box::new(take_lock(obj, "lock_write", (token,))?))
}

/// ``obj.<method>()``, for the lock methods that return nothing.
pub fn call(obj: &PyObject, method: &str) -> Result<(), Error> {
    Python::attach(|py| {
        obj.bind(py)
            .call_method0(method)
            .map(|_| ())
            .map_err(Error::Python)
    })
}

/// ``obj.get_physical_lock_status()``.
pub fn get_physical_lock_status(obj: &PyObject) -> Result<bool, Error> {
    Python::attach(|py| {
        obj.bind(py)
            .call_method0("get_physical_lock_status")
            .and_then(|status| status.extract())
            .map_err(Error::Python)
    })
}
