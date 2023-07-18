use crate::branch::Branch;
use crate::controldir::ControlDir;
use crate::lock::Lock;
use crate::revisionid::RevisionId;
use pyo3::import_exception;
use pyo3::prelude::*;

import_exception!(breezy.commit, PointlessCommit);

pub trait Tree {
    fn obj(&self) -> &PyObject;

    fn get_tag_dict(&self) -> Result<std::collections::HashMap<String, RevisionId>, PyErr> {
        Python::with_gil(|py| {
            let branch = self.obj().getattr(py, "branch")?;
            let tags = branch.getattr(py, "tags")?;
            let tag_dict = tags.call_method0(py, "get_tag_dict")?;
            tag_dict.extract(py)
        })
    }

    fn get_file(&self, path: &std::path::Path) -> PyResult<Box<dyn std::io::Read>> {
        Python::with_gil(|py| {
            let f = self.obj().call_method1(py, "get_file", (path,))?;

            let f = pyo3_file::PyFileLikeObject::with_requirements(f, true, false, false)?;

            Ok(Box::new(f) as Box<dyn std::io::Read>)
        })
    }

    fn lock_read(&self) -> PyResult<Lock> {
        Python::with_gil(|py| {
            let lock = self.obj().call_method0(py, "lock_read").unwrap();
            Ok(Lock(lock))
        })
    }

    fn has_filename(&self, path: &std::path::Path) -> bool {
        Python::with_gil(|py| {
            self.obj()
                .call_method1(py, "has_filename", (path,))
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    fn get_parent_ids(&self) -> PyResult<Vec<RevisionId>> {
        Python::with_gil(|py| {
            self.obj()
                .call_method0(py, "get_parent_ids")
                .unwrap()
                .extract(py)
        })
    }

    fn is_ignored(&self, path: &std::path::Path) -> Option<String> {
        Python::with_gil(|py| {
            self.obj()
                .call_method1(py, "is_ignored", (path,))
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    fn is_versioned(&self, path: &std::path::Path) -> bool {
        Python::with_gil(|py| {
            self.obj()
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
    ) -> PyResult<Box<dyn Iterator<Item = PyResult<TreeChange>>>> {
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
                type Item = PyResult<TreeChange>;

                fn next(&mut self) -> Option<Self::Item> {
                    Python::with_gil(|py| {
                        let next = match self.0.call_method0(py, "__next__") {
                            Ok(v) => v,
                            Err(e) => {
                                if e.is_instance_of::<pyo3::exceptions::PyStopIteration>(py) {
                                    return None;
                                }
                                return Some(Err(e));
                            }
                        };

                        if next.is_none(py) {
                            None
                        } else {
                            Some(next.extract(py))
                        }
                    })
                }
            }

            Ok(Box::new(TreeChangeIter(self.obj().call_method(
                py,
                "iter_changes",
                (other.obj(),),
                Some(kwargs),
            )?))
                as Box<dyn Iterator<Item = PyResult<TreeChange>>>)
        })
    }

    fn has_versioned_directories(&self) -> bool {
        Python::with_gil(|py| {
            self.obj()
                .call_method0(py, "has_versioned_directories")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }
}

pub trait MutableTree: Tree {
    fn lock_write(&self) -> PyResult<Lock> {
        Python::with_gil(|py| {
            let lock = self.obj().call_method0(py, "lock_write").unwrap();
            Ok(Lock(lock))
        })
    }
}

pub struct RevisionTree(pub PyObject);

impl Tree for RevisionTree {
    fn obj(&self) -> &PyObject {
        &self.0
    }
}

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

impl WorkingTree {
    pub fn new(obj: PyObject) -> Result<WorkingTree, PyErr> {
        Ok(WorkingTree(obj))
    }

    pub fn branch(&self) -> Branch {
        Python::with_gil(|py| {
            let branch = self.0.getattr(py, "branch").unwrap();
            Branch(branch)
        })
    }

    pub fn controldir(&self) -> ControlDir {
        Python::with_gil(|py| {
            let controldir = self.0.getattr(py, "controldir").unwrap();
            ControlDir(controldir)
        })
    }

    pub fn open(path: &std::path::Path) -> Result<WorkingTree, PyErr> {
        Python::with_gil(|py| {
            let m = py.import("breezy.workingtree")?;
            let c = m.getattr("WorkingTree")?;
            let wt = c.call_method1("open", (path,))?;
            Ok(WorkingTree(wt.to_object(py)))
        })
    }

    pub fn open_containing(
        path: &std::path::Path,
    ) -> Result<(WorkingTree, std::path::PathBuf), PyErr> {
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
            let tree = self.0.call_method0(py, "basis_tree").unwrap();
            Box::new(RevisionTree(tree))
        })
    }

    pub fn get_tag_dict(&self) -> Result<std::collections::HashMap<String, RevisionId>, PyErr> {
        Python::with_gil(|py| {
            let branch = self.0.getattr(py, "branch")?;
            let tags = branch.getattr(py, "tags")?;
            let tag_dict = tags.call_method0(py, "get_tag_dict")?;
            tag_dict.extract(py)
        })
    }

    pub fn abspath(&self, path: &std::path::Path) -> PyResult<std::path::PathBuf> {
        Python::with_gil(|py| self.0.call_method1(py, "abspath", (path,))?.extract(py))
    }

    pub fn supports_setting_file_ids(&self) -> bool {
        Python::with_gil(|py| {
            self.0
                .call_method0(py, "supports_setting_file_ids")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    pub fn add(&self, paths: &[&std::path::Path]) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "add", (paths.to_vec(),)).unwrap();
        });
        Ok(())
    }

    pub fn smart_add(&self, paths: &[&std::path::Path]) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0
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
                .0
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
            let last_revision = self.0.call_method0(py, "last_revision")?;
            Ok(RevisionId::from(last_revision.extract::<Vec<u8>>(py)?))
        })
    }
}

impl Tree for WorkingTree {
    fn obj(&self) -> &PyObject {
        &self.0
    }
}

impl MutableTree for WorkingTree {}

#[derive(Debug)]
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
