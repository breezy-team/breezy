use crate::branch::{Branch, RegularBranch};
use crate::controldir::ControlDir;
use crate::lock::Lock;
use crate::revisionid::RevisionId;
use pyo3::import_exception;
use pyo3::prelude::*;

import_exception!(breezy.commit, PointlessCommit);
import_exception!(breezy.errors, NotBranchError);
import_exception!(breezy.errors, DependencyNotPresent);
import_exception!(breezy.transport, NoSuchFile);

#[derive(Debug)]
pub enum Error {
    NoSuchFile(std::path::PathBuf),
    Other(PyErr),
}

impl std::error::Error for Error {}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Error::NoSuchFile(path) => write!(f, "No such file: {}", path.to_string_lossy()),
            Error::Other(e) => write!(f, "{}", e),
        }
    }
}

impl From<PyErr> for Error {
    fn from(e: PyErr) -> Self {
        Python::with_gil(|py| {
            if e.is_instance_of::<NoSuchFile>(py) {
                return Error::NoSuchFile(e.value(py).getattr("path").unwrap().extract().unwrap());
            }
            Error::Other(e)
        })
    }
}

impl From<Error> for PyErr {
    fn from(e: Error) -> Self {
        match e {
            Error::NoSuchFile(path) => NoSuchFile::new_err(path.to_string_lossy().to_string()),
            Error::Other(e) => e,
        }
    }
}

pub trait Tree: ToPyObject {
    fn get_tag_dict(&self) -> Result<std::collections::HashMap<String, RevisionId>, PyErr> {
        Python::with_gil(|py| {
            let branch = self.to_object(py).getattr(py, "branch")?;
            let tags = branch.getattr(py, "tags")?;
            let tag_dict = tags.call_method0(py, "get_tag_dict")?;
            tag_dict.extract(py)
        })
    }

    fn get_file(&self, path: &std::path::Path) -> Result<Box<dyn std::io::Read>, Error> {
        Python::with_gil(|py| {
            let f = self.to_object(py).call_method1(py, "get_file", (path,))?;

            let f = pyo3_file::PyFileLikeObject::with_requirements(f, true, false, false)?;

            Ok(Box::new(f) as Box<dyn std::io::Read>)
        })
    }

    fn get_file_text(&self, path: &std::path::Path) -> Result<Vec<u8>, Error> {
        Python::with_gil(|py| {
            let text = self
                .to_object(py)
                .call_method1(py, "get_file_text", (path,))?;
            text.extract(py).map_err(|e| e.into())
        })
    }

    fn get_file_lines(&self, path: &std::path::Path) -> Result<Vec<Vec<u8>>, Error> {
        Python::with_gil(|py| {
            let lines = self
                .to_object(py)
                .call_method1(py, "get_file_lines", (path,))?;
            lines.extract(py).map_err(|e| e.into())
        })
    }

    fn lock_read(&self) -> Result<Lock, Error> {
        Python::with_gil(|py| {
            let lock = self.to_object(py).call_method0(py, "lock_read")?;
            Ok(Lock::from(lock))
        })
    }

    fn has_filename(&self, path: &std::path::Path) -> bool {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method1(py, "has_filename", (path,))
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    fn get_parent_ids(&self) -> Result<Vec<RevisionId>, Error> {
        Python::with_gil(|py| {
            Ok(self
                .to_object(py)
                .call_method0(py, "get_parent_ids")
                .unwrap()
                .extract(py)?)
        })
    }

    fn is_ignored(&self, path: &std::path::Path) -> Option<String> {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method1(py, "is_ignored", (path,))
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    fn is_versioned(&self, path: &std::path::Path) -> bool {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method1(py, "is_versioned", (path,))
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    fn iter_changes(
        &self,
        other: &Box<dyn Tree>,
        specific_files: Option<&[&std::path::Path]>,
        want_unversioned: Option<bool>,
        require_versioned: Option<bool>,
    ) -> Result<Box<dyn Iterator<Item = Result<TreeChange, Error>>>, Error> {
        Python::with_gil(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            if let Some(specific_files) = specific_files {
                kwargs.set_item("specific_files", specific_files)?;
            }
            if let Some(want_unversioned) = want_unversioned {
                kwargs.set_item("want_unversioned", want_unversioned)?;
            }
            if let Some(require_versioned) = require_versioned {
                kwargs.set_item("require_versioned", require_versioned)?;
            }
            struct TreeChangeIter(pyo3::PyObject);

            impl Iterator for TreeChangeIter {
                type Item = Result<TreeChange, Error>;

                fn next(&mut self) -> Option<Self::Item> {
                    Python::with_gil(|py| {
                        let next = match self.0.call_method0(py, "__next__") {
                            Ok(v) => v,
                            Err(e) => {
                                if e.is_instance_of::<pyo3::exceptions::PyStopIteration>(py) {
                                    return None;
                                }
                                return Some(Err(e.into()));
                            }
                        };

                        if next.is_none(py) {
                            None
                        } else {
                            Some(next.extract(py).map_err(|e| e.into()))
                        }
                    })
                }
            }

            Ok(Box::new(TreeChangeIter(self.to_object(py).call_method(
                py,
                "iter_changes",
                (other.to_object(py),),
                Some(kwargs),
            )?))
                as Box<dyn Iterator<Item = Result<TreeChange, Error>>>)
        })
    }

    fn has_versioned_directories(&self) -> bool {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method0(py, "has_versioned_directories")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }
}

pub trait MutableTree: Tree {
    fn lock_write(&self) -> Result<Lock, Error> {
        Python::with_gil(|py| {
            let lock = self.to_object(py).call_method0(py, "lock_write").unwrap();
            Ok(Lock::from(lock))
        })
    }

    fn put_file_bytes_non_atomic(&self, path: &std::path::Path, data: &[u8]) -> Result<(), Error> {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method1(py, "put_file_bytes_non_atomic", (path, data))?;
            Ok(())
        })
    }

    fn has_changes(&self) -> std::result::Result<bool, Error> {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method0(py, "has_changes")?
                .extract::<bool>(py)
                .map_err(|e| e.into())
        })
    }
}

pub struct RevisionTree(pub PyObject);

impl ToPyObject for RevisionTree {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl Tree for RevisionTree {}

#[derive(Debug)]
pub enum CommitError {
    PointlessCommit,
    Other(PyErr),
}

impl std::fmt::Display for CommitError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            CommitError::PointlessCommit => write!(f, "Pointless commit"),
            CommitError::Other(e) => write!(f, "Other error: {}", e),
        }
    }
}

impl std::error::Error for CommitError {}

pub struct WorkingTree(pub PyObject);

impl ToPyObject for WorkingTree {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

#[derive(Debug)]
pub enum WorkingTreeOpenError {
    NotBranchError(String),
    DependencyNotPresent(String, String),
    Other(PyErr),
}

impl From<PyErr> for WorkingTreeOpenError {
    fn from(err: PyErr) -> Self {
        Python::with_gil(|py| {
            if err.is_instance_of::<NotBranchError>(py) {
                let l = err
                    .value(py)
                    .getattr("path")
                    .unwrap()
                    .extract::<String>()
                    .unwrap();
                WorkingTreeOpenError::NotBranchError(l)
            } else if err.is_instance_of::<DependencyNotPresent>(py) {
                let l = err
                    .value(py)
                    .getattr("library")
                    .unwrap()
                    .extract::<String>()
                    .unwrap();
                let e = err
                    .value(py)
                    .getattr("error")
                    .unwrap()
                    .extract::<String>()
                    .unwrap();
                WorkingTreeOpenError::DependencyNotPresent(l, e)
            } else {
                WorkingTreeOpenError::Other(err)
            }
        })
    }
}

impl From<WorkingTreeOpenError> for PyErr {
    fn from(err: WorkingTreeOpenError) -> Self {
        match err {
            WorkingTreeOpenError::NotBranchError(l) => NotBranchError::new_err((l,)),
            WorkingTreeOpenError::DependencyNotPresent(d, e) => {
                DependencyNotPresent::new_err((d, e))
            }
            WorkingTreeOpenError::Other(err) => err,
        }
    }
}

impl std::fmt::Display for WorkingTreeOpenError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            WorkingTreeOpenError::NotBranchError(l) => write!(f, "Not branch error: {}", l),
            WorkingTreeOpenError::DependencyNotPresent(d, e) => {
                write!(f, "Dependency not present: {} {}", d, e)
            }
            WorkingTreeOpenError::Other(e) => write!(f, "Other error: {}", e),
        }
    }
}

impl std::error::Error for WorkingTreeOpenError {}

impl WorkingTree {
    pub fn new(obj: PyObject) -> Result<WorkingTree, PyErr> {
        Ok(WorkingTree(obj))
    }

    pub fn branch(&self) -> Box<dyn Branch> {
        Python::with_gil(|py| {
            let branch = self.to_object(py).getattr(py, "branch").unwrap();
            Box::new(RegularBranch::new(branch)) as Box<dyn Branch>
        })
    }

    pub fn controldir(&self) -> ControlDir {
        Python::with_gil(|py| {
            let controldir = self.to_object(py).getattr(py, "controldir").unwrap();
            ControlDir::new(controldir)
        })
    }

    pub fn open(path: &std::path::Path) -> Result<WorkingTree, WorkingTreeOpenError> {
        Python::with_gil(|py| {
            let m = py.import("breezy.workingtree")?;
            let c = m.getattr("WorkingTree")?;
            let wt = c.call_method1("open", (path,))?;
            Ok(WorkingTree(wt.to_object(py)))
        })
    }

    pub fn open_containing(
        path: &std::path::Path,
    ) -> Result<(WorkingTree, std::path::PathBuf), WorkingTreeOpenError> {
        Python::with_gil(|py| {
            let m = py.import("breezy.workingtree")?;
            let c = m.getattr("WorkingTree")?;
            let (wt, p): (&PyAny, String) =
                c.call_method1("open_containing", (path,))?.extract()?;
            Ok((WorkingTree(wt.to_object(py)), std::path::PathBuf::from(p)))
        })
    }

    pub fn basis_tree(&self) -> Box<dyn Tree> {
        Python::with_gil(|py| {
            let tree = self.to_object(py).call_method0(py, "basis_tree").unwrap();
            Box::new(RevisionTree(tree))
        })
    }

    pub fn get_tag_dict(&self) -> Result<std::collections::HashMap<String, RevisionId>, PyErr> {
        Python::with_gil(|py| {
            let branch = self.to_object(py).getattr(py, "branch")?;
            let tags = branch.getattr(py, "tags")?;
            let tag_dict = tags.call_method0(py, "get_tag_dict")?;
            tag_dict.extract(py)
        })
    }

    pub fn abspath(&self, path: &std::path::Path) -> Result<std::path::PathBuf, Error> {
        Python::with_gil(|py| {
            Ok(self
                .to_object(py)
                .call_method1(py, "abspath", (path,))?
                .extract(py)?)
        })
    }

    pub fn supports_setting_file_ids(&self) -> bool {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method0(py, "supports_setting_file_ids")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    pub fn add(&self, paths: &[&std::path::Path]) -> Result<(), Error> {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method1(py, "add", (paths.to_vec(),))
                .unwrap();
        });
        Ok(())
    }

    pub fn smart_add(&self, paths: &[&std::path::Path]) -> Result<(), Error> {
        Python::with_gil(|py| {
            self.to_object(py)
                .call_method1(py, "smart_add", (paths.to_vec(),))
                .unwrap();
        });
        Ok(())
    }

    pub fn commit(
        &self,
        message: &str,
        allow_pointless: Option<bool>,
        committer: Option<&str>,
        specific_files: Option<&[&std::path::Path]>,
    ) -> Result<RevisionId, CommitError> {
        Python::with_gil(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            if let Some(committer) = committer {
                kwargs.set_item("committer", committer).unwrap();
            }
            if let Some(specific_files) = specific_files {
                kwargs.set_item("specific_files", specific_files).unwrap();
            }
            if let Some(allow_pointless) = allow_pointless {
                kwargs.set_item("allow_pointless", allow_pointless).unwrap();
            }

            let null_commit_reporter = py
                .import("breezy.commit")
                .unwrap()
                .getattr("NullCommitReporter")
                .unwrap()
                .call0()
                .unwrap();
            kwargs.set_item("reporter", null_commit_reporter).unwrap();

            Ok(self
                .to_object(py)
                .call_method(py, "commit", (message,), Some(kwargs))
                .map_err(|e| {
                    if e.is_instance_of::<PointlessCommit>(py) {
                        CommitError::PointlessCommit
                    } else {
                        CommitError::Other(e)
                    }
                })?
                .extract(py)
                .unwrap())
        })
    }

    pub fn last_revision(&self) -> Result<RevisionId, PyErr> {
        Python::with_gil(|py| {
            let last_revision = self.to_object(py).call_method0(py, "last_revision")?;
            Ok(RevisionId::from(last_revision.extract::<Vec<u8>>(py)?))
        })
    }
}

impl Tree for WorkingTree {}

impl MutableTree for WorkingTree {}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct TreeChange {
    pub path: (Option<std::path::PathBuf>, Option<std::path::PathBuf>),
    pub changed_content: bool,
    pub versioned: (Option<bool>, Option<bool>),
    pub name: (Option<std::ffi::OsString>, Option<std::ffi::OsString>),
    pub kind: (Option<String>, Option<String>),
    pub executable: (Option<bool>, Option<bool>),
    pub copied: bool,
}

impl ToPyObject for TreeChange {
    fn to_object(&self, py: Python) -> PyObject {
        let dict = pyo3::types::PyDict::new(py);
        dict.set_item("path", &self.path).unwrap();
        dict.set_item("changed_content", self.changed_content)
            .unwrap();
        dict.set_item("versioned", self.versioned).unwrap();
        dict.set_item("name", &self.name).unwrap();
        dict.set_item("kind", &self.kind).unwrap();
        dict.set_item("executable", self.executable).unwrap();
        dict.set_item("copied", self.copied).unwrap();
        dict.into()
    }
}

impl FromPyObject<'_> for TreeChange {
    fn extract(obj: &PyAny) -> PyResult<Self> {
        fn from_bool(o: &PyAny) -> PyResult<bool> {
            if let Ok(b) = o.extract::<isize>() {
                Ok(b != 0)
            } else {
                o.extract::<bool>()
            }
        }

        fn from_opt_bool_tuple(o: &PyAny) -> PyResult<(Option<bool>, Option<bool>)> {
            let tuple = o.extract::<(Option<&PyAny>, Option<&PyAny>)>()?;
            Ok((
                tuple.0.map(from_bool).transpose()?,
                tuple.1.map(from_bool).transpose()?,
            ))
        }

        let path = obj.getattr("path")?;
        let changed_content = from_bool(obj.getattr("changed_content")?)?;

        let versioned = from_opt_bool_tuple(obj.getattr("versioned")?)?;
        let name = obj.getattr("name")?;
        let kind = obj.getattr("kind")?;
        let executable = from_opt_bool_tuple(obj.getattr("executable")?)?;
        let copied = obj.getattr("copied")?;

        Ok(TreeChange {
            path: path.extract()?,
            changed_content,
            versioned,
            name: name.extract()?,
            kind: kind.extract()?,
            executable,
            copied: copied.extract()?,
        })
    }
}
