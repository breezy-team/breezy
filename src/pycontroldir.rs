//! Python control directories, formats and probers as implementations of the
//! [`crate::controldir`] traits.
//!
//! A [`PyProber`] wraps a Python ``Prober`` class; registering it with
//! [`crate::controldir::register_prober`] makes every kind of control
//! directory Python knows reachable from Rust, yielding Python-backed trees,
//! branches and repositories.

use crate::branch::Branch;
use crate::controldir::{ControlDir, ControlDirFormat, Error, Prober};
use crate::pybranch::PyBranch;
use crate::pyrepository::PyRepository;
use crate::pytree::PyTree;
use crate::repository::Repository;
use crate::tree::WorkingTree;
use dromedary::Transport;
use pyo3::exceptions::PyRuntimeError;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyDict;

import_exception!(breezy.errors, NotBranchError);
import_exception!(breezy.errors, UnknownFormatError);
import_exception!(breezy.errors, NoWorkingTree);
import_exception!(breezy.errors, NoRepositoryPresent);
import_exception!(dromedary.errors, NoSuchFile);

/// Map a Python exception onto [`Error`]; anything not modelled is carried
/// as is.
fn map_py_err(py: Python<'_>, err: PyErr) -> Error {
    let value = err.value(py);
    let attr = |name: &str| {
        value
            .getattr(name)
            .and_then(|v| v.extract::<Option<String>>())
            .ok()
            .flatten()
    };
    if err.is_instance_of::<NotBranchError>(py) {
        Error::NotBranch {
            path: attr("path").unwrap_or_default(),
            // NotBranchError stores the detail with its ": " separator.
            detail: attr("detail").map(|d| d.trim_start_matches(": ").to_string()),
        }
    } else if err.is_instance_of::<UnknownFormatError>(py) {
        Error::UnknownFormat {
            format: attr("format").unwrap_or_default(),
            kind: attr("kind").unwrap_or_else(|| "branch".to_string()),
        }
    } else if err.is_instance_of::<NoWorkingTree>(py) {
        Error::NoWorkingTree(attr("base").unwrap_or_default())
    } else if err.is_instance_of::<NoRepositoryPresent>(py) {
        Error::NoRepository(attr("path").unwrap_or_default())
    } else {
        Error::Python(err)
    }
}

/// Run `f` with the interpreter, mapping its exception onto [`Error`].
fn with_py<T>(f: impl FnOnce(Python<'_>) -> PyResult<T>) -> Result<T, Error> {
    Python::attach(|py| f(py).map_err(|e| map_py_err(py, e)))
}

fn kwargs<'py>(py: Python<'py>, items: &[(&str, Option<&str>)]) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    for (key, value) in items {
        dict.set_item(*key, *value)?;
    }
    Ok(dict)
}

fn py_err(py: Python<'_>, err: Error) -> PyResult<PyErr> {
    let errors = py.import("breezy.errors")?;
    let exc = match err {
        Error::Python(e) => return Ok(e),
        Error::NotBranch { path, detail } => errors.getattr("NotBranchError")?.call(
            (),
            Some(&kwargs(
                py,
                &[("path", Some(&path)), ("detail", detail.as_deref())],
            )?),
        )?,
        Error::UnknownFormat { format, kind } => errors.getattr("UnknownFormatError")?.call(
            (),
            Some(&kwargs(
                py,
                &[("format", Some(&format)), ("kind", Some(&kind))],
            )?),
        )?,
        Error::NoWorkingTree(base) => errors.getattr("NoWorkingTree")?.call1((base,))?,
        Error::NoRepository(path) => {
            // NoRepositoryPresent's constructor derives the path from a
            // control directory object; build it as BzrError would with
            // the path given directly.
            let class = errors.getattr("NoRepositoryPresent")?;
            let exc = class.call_method1("__new__", (&class,))?;
            errors.getattr("BzrError")?.call_method(
                "__init__",
                (&exc,),
                Some(&kwargs(py, &[("path", Some(&path))])?),
            )?;
            exc
        }
        Error::Transport(dromedary::Error::NoSuchFile(path)) => {
            return Ok(NoSuchFile::new_err(path.unwrap_or_default()))
        }
        other => return Ok(PyRuntimeError::new_err(other.to_string())),
    };
    Ok(PyErr::from_value(exc))
}

impl From<Error> for PyErr {
    /// Raise a control directory error as the matching breezy exception.
    fn from(err: Error) -> PyErr {
        Python::attach(|py| py_err(py, err).unwrap_or_else(|e| e))
    }
}

/// The Python transport for a Rust transport, by URL.
fn py_transport<'py>(py: Python<'py>, transport: &dyn Transport) -> PyResult<Bound<'py, PyAny>> {
    py.import("breezy.transport")?
        .call_method1("get_transport_from_url", (transport.base().as_str(),))
}

/// A Python ``Prober`` class.
pub struct PyProber(Py<PyAny>);

impl PyProber {
    /// Wrap the Python prober class `class`.
    pub fn new(class: Py<PyAny>) -> Self {
        PyProber(class)
    }

    /// The wrapped Python class.
    pub fn class(&self) -> &Py<PyAny> {
        &self.0
    }
}

impl Prober for PyProber {
    fn probe_transport(
        &self,
        transport: &dyn Transport,
    ) -> Result<Box<dyn ControlDirFormat>, Error> {
        with_py(|py| {
            let transport = py_transport(py, transport)?;
            let format = self
                .0
                .bind(py)
                .call0()?
                .call_method1("probe_transport", (transport,))?;
            Ok(Box::new(PyControlDirFormat(format.unbind())) as Box<dyn ControlDirFormat>)
        })
    }

    fn priority(&self, transport: &dyn Transport) -> Result<i32, Error> {
        with_py(|py| {
            let transport = py_transport(py, transport)?;
            self.0
                .bind(py)
                .call_method1("priority", (transport,))?
                .extract()
        })
    }
}

/// A Python ``ControlDirFormat`` object.
pub struct PyControlDirFormat(Py<PyAny>);

impl ControlDirFormat for PyControlDirFormat {
    fn get_format_description(&self) -> Result<String, Error> {
        with_py(|py| {
            self.0
                .bind(py)
                .call_method0("get_format_description")?
                .extract()
        })
    }

    fn open(&self, transport: std::sync::Arc<dyn Transport>) -> Result<Box<dyn ControlDir>, Error> {
        with_py(|py| {
            let transport = py_transport(py, transport.as_ref())?;
            let dir = self.0.bind(py).call_method1("open", (transport,))?;
            Ok(Box::new(PyControlDir(dir.unbind())) as Box<dyn ControlDir>)
        })
    }
}

/// A Python ``ControlDir`` object.
pub struct PyControlDir(Py<PyAny>);

impl PyControlDir {
    /// Wrap the Python control directory `obj`.
    pub fn new(obj: Py<PyAny>) -> Self {
        PyControlDir(obj)
    }
}

impl ControlDir for PyControlDir {
    fn user_url(&self) -> Result<String, Error> {
        with_py(|py| self.0.bind(py).getattr("user_url")?.extract())
    }

    fn has_workingtree(&self) -> Result<bool, Error> {
        with_py(|py| self.0.bind(py).call_method0("has_workingtree")?.extract())
    }

    fn has_branch(&self, name: Option<&str>) -> Result<bool, Error> {
        with_py(|py| {
            self.0
                .bind(py)
                .call_method1("has_branch", (name,))?
                .extract()
        })
    }

    fn has_repository(&self) -> Result<bool, Error> {
        with_py(|py| self.0.bind(py).call_method0("has_repository")?.extract())
    }

    fn open_workingtree(&self) -> Result<Box<dyn WorkingTree + Send + Sync>, Error> {
        with_py(|py| {
            let tree = self.0.bind(py).call_method0("open_workingtree")?;
            Ok(Box::new(PyTree::new(tree.unbind())) as Box<dyn WorkingTree + Send + Sync>)
        })
    }

    fn open_branch(&self, name: Option<&str>) -> Result<Box<dyn Branch + Send + Sync>, Error> {
        with_py(|py| {
            let branch = self.0.bind(py).call_method(
                "open_branch",
                (),
                Some(&kwargs(py, &[("name", name)])?),
            )?;
            Ok(Box::new(PyBranch::new(branch.unbind())) as Box<dyn Branch + Send + Sync>)
        })
    }

    fn open_repository(&self) -> Result<Box<dyn Repository + Send + Sync>, Error> {
        with_py(|py| {
            let repository = self.0.bind(py).call_method0("open_repository")?;
            Ok(Box::new(PyRepository::new(repository.unbind()))
                as Box<dyn Repository + Send + Sync>)
        })
    }

    fn find_repository(&self) -> Result<Box<dyn Repository + Send + Sync>, Error> {
        with_py(|py| {
            let repository = self.0.bind(py).call_method0("find_repository")?;
            Ok(Box::new(PyRepository::new(repository.unbind()))
                as Box<dyn Repository + Send + Sync>)
        })
    }
}
