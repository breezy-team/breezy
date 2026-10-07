//! Python control directories, formats and probers as implementations of the
//! [`crate::controldir`] traits.
//!
//! A [`PyProber`] wraps a Python ``Prober`` class; registering it with
//! [`crate::controldir::register_prober`] makes every kind of control
//! directory Python knows reachable from Rust, yielding Python-backed trees,
//! branches and repositories.

use crate::branch::Branch;
use crate::controldir::{
    BranchRef, CloneOnTransportOptions, CloneOptions, ControlDir, ControlDirFormat, Error, Prober,
    PushOptions, PyObject, RepositoryRef, SproutOptions, TransportRef, WorkingTreeRef,
};
use crate::pybranch::PyBranch;
use crate::pyrepository::PyRepository;
use crate::pytree::PyTree;
use crate::repository::Repository;
use crate::tree::Tree;
use bazaar::RevisionId;
use dromedary::Transport;
use pyo3::exceptions::{PyNotImplementedError, PyRuntimeError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use std::collections::HashMap;
use std::sync::Arc;

import_exception!(breezy.errors, NotBranchError);
import_exception!(breezy.errors, UnknownFormatError);
import_exception!(breezy.errors, NoWorkingTree);
import_exception!(breezy.errors, NoRepositoryPresent);
import_exception!(dromedary.errors, NoSuchFile);
import_exception!(dromedary.errors, NotLocalUrl);

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
    } else if err.is_instance_of::<NotLocalUrl>(py) {
        Error::NotLocalUrl(attr("url").unwrap_or_default())
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
        Error::NotLocalUrl(url) => return Ok(NotLocalUrl::new_err(url)),
        Error::UnsupportedOperation(msg) => {
            return Ok(crate::pyerrors::unsupported_operation(py, &msg))
        }
        Error::UnsupportedFormat(format) => {
            return Ok(crate::pyerrors::bzr_error_with(
                py,
                "breezy.errors",
                "UnsupportedFormatError",
                &[("format", &format)],
            ))
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

/// The Python object behind a Rust handle, for passing it to Python code.
///
/// TODO: a native object could be handed to Python wrapped in its `_cmd_rs`
/// class; that class lives in the bindings crate, so for now only
/// Python-backed objects can cross back.
fn py_of<'py>(
    py: Python<'py>,
    what: &str,
    object: Option<&PyObject>,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    match object {
        Some(object) => Ok(Some(object.bind(py).clone())),
        None => Err(PyNotImplementedError::new_err(format!(
            "a native {what} cannot be passed to a Python control directory"
        ))),
    }
}

fn py_branch<'py>(
    py: Python<'py>,
    branch: Option<&(dyn Branch + Send + Sync)>,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    match branch {
        Some(branch) => py_of(py, "branch", branch.python_object()),
        None => Ok(None),
    }
}

fn py_format<'py>(
    py: Python<'py>,
    format: Option<&dyn ControlDirFormat>,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    match format {
        Some(format) => py_of(py, "control directory format", format.python_object()),
        None => Ok(None),
    }
}

fn py_revision_id<'py>(
    py: Python<'py>,
    revision_id: Option<&RevisionId>,
) -> PyResult<Option<Bound<'py, PyBytes>>> {
    Ok(revision_id.map(|r| PyBytes::new(py, r.as_bytes())))
}

fn branch_ref(branch: Bound<'_, PyAny>) -> BranchRef {
    Box::new(PyBranch::new(branch.unbind()))
}

fn control_dir(dir: Bound<'_, PyAny>) -> Box<dyn ControlDir> {
    Box::new(PyControlDir(dir.unbind()))
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

impl PyControlDirFormat {
    /// Wrap the Python format `obj`.
    pub fn new(obj: Py<PyAny>) -> Self {
        PyControlDirFormat(obj)
    }
}

impl ControlDirFormat for PyControlDirFormat {
    fn python_object(&self) -> Option<&PyObject> {
        Some(&self.0)
    }

    fn get_format_description(&self) -> Result<String, Error> {
        with_py(|py| {
            self.0
                .bind(py)
                .call_method0("get_format_description")?
                .extract()
        })
    }

    fn is_supported(&self) -> Result<bool, Error> {
        with_py(|py| self.0.bind(py).call_method0("is_supported")?.extract())
    }

    fn check_support_status(&self, allow_unsupported: bool) -> Result<(), Error> {
        with_py(|py| {
            self.0
                .bind(py)
                .call_method1("check_support_status", (allow_unsupported,))?;
            Ok(())
        })
    }

    fn open(&self, transport: Arc<dyn Transport>) -> Result<Box<dyn ControlDir>, Error> {
        with_py(|py| {
            let transport = py_transport(py, transport.as_ref())?;
            Ok(control_dir(
                self.0.bind(py).call_method1("open", (transport,))?,
            ))
        })
    }

    fn initialize_on_transport(
        &self,
        transport: Arc<dyn Transport>,
    ) -> Result<Box<dyn ControlDir>, Error> {
        with_py(|py| {
            let transport = py_transport(py, transport.as_ref())?;
            Ok(control_dir(
                self.0
                    .bind(py)
                    .call_method1("initialize_on_transport", (transport,))?,
            ))
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

    fn call<T>(
        &self,
        name: &str,
        f: impl FnOnce(Python<'_>, Bound<'_, PyAny>) -> PyResult<T>,
    ) -> Result<T, Error> {
        with_py(|py| {
            let result = self.0.bind(py).call_method0(name)?;
            f(py, result)
        })
    }
}

impl ControlDir for PyControlDir {
    fn python_object(&self) -> Option<&PyObject> {
        Some(&self.0)
    }

    fn user_url(&self) -> Result<String, Error> {
        with_py(|py| self.0.bind(py).getattr("user_url")?.extract())
    }

    fn has_workingtree(&self) -> Result<bool, Error> {
        self.call("has_workingtree", |_, r| r.extract())
    }

    fn has_branch(&self, name: Option<&str>) -> Result<bool, Error> {
        with_py(|py| {
            self.0
                .bind(py)
                .call_method1("has_branch", (name,))?
                .extract()
        })
    }

    fn control_url(&self) -> Result<String, Error> {
        with_py(|py| self.0.bind(py).getattr("control_url")?.extract())
    }

    /// A Rust transport at the same location as the Python one; dromedary's
    /// wrapper around a Python transport needs a pyo3 the workspace does not
    /// use yet, so this is a separate transport object.
    fn user_transport(&self) -> Result<TransportRef, Error> {
        crate::controldir::get_transport(&self.user_url()?)
    }

    fn control_transport(&self) -> Result<TransportRef, Error> {
        crate::controldir::get_transport(&self.control_url()?)
    }

    /// Python control directories have no ``has_repository``; the answer is
    /// whether a repository opens.
    fn has_repository(&self) -> Result<bool, Error> {
        match self.open_repository() {
            Ok(_) => Ok(true),
            Err(Error::NoRepository(_)) => Ok(false),
            Err(e) => Err(e),
        }
    }

    fn open_workingtree(&self) -> Result<WorkingTreeRef, Error> {
        self.call("open_workingtree", |_, tree| {
            Ok(Box::new(PyTree::new(tree.unbind())) as WorkingTreeRef)
        })
    }

    fn open_branch(&self, name: Option<&str>) -> Result<BranchRef, Error> {
        with_py(|py| {
            let branch = self.0.bind(py).call_method(
                "open_branch",
                (),
                Some(&kwargs(py, &[("name", name)])?),
            )?;
            Ok(branch_ref(branch))
        })
    }

    fn open_repository(&self) -> Result<RepositoryRef, Error> {
        self.call("open_repository", |_, repository| {
            Ok(Box::new(PyRepository::new(repository.unbind())) as RepositoryRef)
        })
    }

    fn find_repository(&self) -> Result<RepositoryRef, Error> {
        self.call("find_repository", |_, repository| {
            Ok(Box::new(PyRepository::new(repository.unbind())) as RepositoryRef)
        })
    }

    fn can_convert_format(&self) -> Result<bool, Error> {
        self.call("can_convert_format", |_, r| r.extract())
    }

    fn needs_format_conversion(
        &self,
        format: Option<&dyn ControlDirFormat>,
    ) -> Result<bool, Error> {
        with_py(|py| {
            let format = py_format(py, format)?;
            self.0
                .bind(py)
                .call_method1("needs_format_conversion", (format,))?
                .extract()
        })
    }

    fn check_conversion_target(&self, target_format: &dyn ControlDirFormat) -> Result<(), Error> {
        with_py(|py| {
            let format = py_format(py, Some(target_format))?;
            self.0
                .bind(py)
                .call_method1("check_conversion_target", (format,))?;
            Ok(())
        })
    }

    fn is_control_filename(&self, filename: &str) -> Result<bool, Error> {
        with_py(|py| {
            self.0
                .bind(py)
                .call_method1("is_control_filename", (filename,))?
                .extract()
        })
    }

    fn get_branch_reference(&self, name: Option<&str>) -> Result<Option<String>, Error> {
        with_py(|py| {
            self.0
                .bind(py)
                .call_method1("get_branch_reference", (name,))?
                .extract()
        })
    }

    fn set_branch_reference(
        &self,
        target_branch: &(dyn Branch + Send + Sync),
        name: Option<&str>,
    ) -> Result<BranchRef, Error> {
        with_py(|py| {
            let target = py_branch(py, Some(target_branch))?;
            let branch = self.0.bind(py).call_method(
                "set_branch_reference",
                (target,),
                Some(&kwargs(py, &[("name", name)])?),
            )?;
            Ok(branch_ref(branch))
        })
    }

    fn find_branch_format(&self, name: Option<&str>) -> Result<PyObject, Error> {
        with_py(|py| {
            Ok(self
                .0
                .bind(py)
                .call_method1("find_branch_format", (name,))?
                .unbind())
        })
    }

    fn branch_names(&self) -> Result<Vec<String>, Error> {
        self.call("branch_names", |_, r| r.extract())
    }

    fn get_branches(&self) -> Result<HashMap<String, BranchRef>, Error> {
        self.call("get_branches", |_, branches| {
            branches
                .cast::<PyDict>()?
                .iter()
                .map(|(name, branch)| Ok((name.extract()?, branch_ref(branch))))
                .collect()
        })
    }

    fn list_branches(&self) -> Result<Vec<BranchRef>, Error> {
        self.call("list_branches", |_, branches| {
            branches
                .try_iter()?
                .map(|branch| Ok(branch_ref(branch?)))
                .collect()
        })
    }

    fn create_repository(&self, shared: bool) -> Result<RepositoryRef, Error> {
        with_py(|py| {
            let repository = self
                .0
                .bind(py)
                .call_method1("create_repository", (shared,))?;
            Ok(Box::new(PyRepository::new(repository.unbind())) as RepositoryRef)
        })
    }

    fn destroy_repository(&self) -> Result<(), Error> {
        self.call("destroy_repository", |_, _| Ok(()))
    }

    fn create_branch(
        &self,
        name: Option<&str>,
        repository: Option<&(dyn Repository + Send + Sync)>,
        append_revisions_only: Option<bool>,
    ) -> Result<BranchRef, Error> {
        with_py(|py| {
            let kwargs = kwargs(py, &[("name", name)])?;
            if let Some(repository) = repository {
                kwargs.set_item(
                    "repository",
                    py_of(py, "repository", repository.python_object())?,
                )?;
            }
            kwargs.set_item("append_revisions_only", append_revisions_only)?;
            let branch = self
                .0
                .bind(py)
                .call_method("create_branch", (), Some(&kwargs))?;
            Ok(branch_ref(branch))
        })
    }

    fn destroy_branch(&self, name: Option<&str>) -> Result<(), Error> {
        with_py(|py| {
            self.0.bind(py).call_method1("destroy_branch", (name,))?;
            Ok(())
        })
    }

    fn create_workingtree(
        &self,
        revision_id: Option<&RevisionId>,
        from_branch: Option<&(dyn Branch + Send + Sync)>,
        accelerator_tree: Option<&(dyn Tree + Send + Sync)>,
        hardlink: bool,
    ) -> Result<WorkingTreeRef, Error> {
        with_py(|py| {
            let kwargs = PyDict::new(py);
            kwargs.set_item("revision_id", py_revision_id(py, revision_id)?)?;
            kwargs.set_item("from_branch", py_branch(py, from_branch)?)?;
            if let Some(tree) = accelerator_tree {
                kwargs.set_item("accelerator_tree", py_of(py, "tree", tree.python_object())?)?;
            }
            kwargs.set_item("hardlink", hardlink)?;
            let tree = self
                .0
                .bind(py)
                .call_method("create_workingtree", (), Some(&kwargs))?;
            Ok(Box::new(PyTree::new(tree.unbind())) as WorkingTreeRef)
        })
    }

    fn destroy_workingtree(&self) -> Result<(), Error> {
        self.call("destroy_workingtree", |_, _| Ok(()))
    }

    fn destroy_workingtree_metadata(&self) -> Result<(), Error> {
        self.call("destroy_workingtree_metadata", |_, _| Ok(()))
    }

    fn cloning_metadir(&self, require_stacking: bool) -> Result<Box<dyn ControlDirFormat>, Error> {
        with_py(|py| {
            let format = self
                .0
                .bind(py)
                .call_method1("cloning_metadir", (require_stacking,))?;
            Ok(Box::new(PyControlDirFormat(format.unbind())) as Box<dyn ControlDirFormat>)
        })
    }

    fn checkout_metadir(&self) -> Result<Box<dyn ControlDirFormat>, Error> {
        self.call("checkout_metadir", |_, format| {
            Ok(Box::new(PyControlDirFormat(format.unbind())) as Box<dyn ControlDirFormat>)
        })
    }

    fn get_config(&self) -> Result<PyObject, Error> {
        self.call("get_config", |_, config| Ok(config.unbind()))
    }

    fn sprout(&self, url: &str, options: &SproutOptions<'_>) -> Result<Box<dyn ControlDir>, Error> {
        with_py(|py| {
            let kwargs = PyDict::new(py);
            kwargs.set_item("revision_id", py_revision_id(py, options.revision_id)?)?;
            kwargs.set_item("force_new_repo", options.force_new_repo)?;
            kwargs.set_item("recurse", options.recurse)?;
            if let Some(tree) = options.accelerator_tree {
                kwargs.set_item("accelerator_tree", py_of(py, "tree", tree.python_object())?)?;
            }
            kwargs.set_item("hardlink", options.hardlink)?;
            kwargs.set_item("stacked", options.stacked)?;
            kwargs.set_item("source_branch", py_branch(py, options.source_branch)?)?;
            kwargs.set_item("create_tree_if_local", options.create_tree_if_local)?;
            kwargs.set_item("lossy", options.lossy)?;
            Ok(control_dir(self.0.bind(py).call_method(
                "sprout",
                (url,),
                Some(&kwargs),
            )?))
        })
    }

    fn clone(&self, url: &str, options: &CloneOptions<'_>) -> Result<Box<dyn ControlDir>, Error> {
        with_py(|py| {
            let kwargs = PyDict::new(py);
            kwargs.set_item("revision_id", py_revision_id(py, options.revision_id)?)?;
            kwargs.set_item("force_new_repo", options.force_new_repo)?;
            kwargs.set_item("preserve_stacking", options.preserve_stacking)?;
            kwargs.set_item("tag_selector", options.tag_selector.map(|s| s.bind(py)))?;
            Ok(control_dir(self.0.bind(py).call_method(
                "clone",
                (url,),
                Some(&kwargs),
            )?))
        })
    }

    fn clone_on_transport(
        &self,
        transport: Arc<dyn Transport>,
        options: &CloneOnTransportOptions<'_>,
    ) -> Result<Box<dyn ControlDir>, Error> {
        with_py(|py| {
            let transport = py_transport(py, transport.as_ref())?;
            let kwargs = PyDict::new(py);
            kwargs.set_item("revision_id", py_revision_id(py, options.revision_id)?)?;
            kwargs.set_item("force_new_repo", options.force_new_repo)?;
            kwargs.set_item("preserve_stacking", options.preserve_stacking)?;
            kwargs.set_item("stacked_on", options.stacked_on)?;
            kwargs.set_item("create_prefix", options.create_prefix)?;
            kwargs.set_item("use_existing_dir", options.use_existing_dir)?;
            kwargs.set_item("no_tree", options.no_tree)?;
            kwargs.set_item("tag_selector", options.tag_selector.map(|s| s.bind(py)))?;
            Ok(control_dir(self.0.bind(py).call_method(
                "clone_on_transport",
                (transport,),
                Some(&kwargs),
            )?))
        })
    }

    fn push_branch(
        &self,
        source: &(dyn Branch + Send + Sync),
        options: &PushOptions<'_>,
    ) -> Result<PyObject, Error> {
        with_py(|py| {
            let source = py_branch(py, Some(source))?;
            let kwargs = PyDict::new(py);
            kwargs.set_item("revision_id", py_revision_id(py, options.revision_id)?)?;
            kwargs.set_item("overwrite", options.overwrite)?;
            kwargs.set_item("remember", options.remember)?;
            kwargs.set_item("create_prefix", options.create_prefix)?;
            kwargs.set_item("lossy", options.lossy)?;
            kwargs.set_item("tag_selector", options.tag_selector.map(|s| s.bind(py)))?;
            kwargs.set_item("name", options.name)?;
            Ok(self
                .0
                .bind(py)
                .call_method("push_branch", (source,), Some(&kwargs))?
                .unbind())
        })
    }
}
