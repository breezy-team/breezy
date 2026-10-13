use crate::repository::{Error, PyObject, Repository};
use bazaar::RevisionId;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::collections::HashMap;

/// A wrapper around a Python repository object.
///
/// This struct provides a Rust interface to Python repository objects,
/// implementing the [`Repository`] trait by delegating each method to the
/// wrapped Python repository.
pub struct PyRepository(Py<PyAny>);

impl PyRepository {
    /// Creates a new `PyRepository` wrapper around a Python repository object.
    pub fn new(o: Py<PyAny>) -> Self {
        PyRepository(o)
    }

    /// Returns a reference to the wrapped Python object.
    pub fn as_pyobject(&self) -> &Py<PyAny> {
        &self.0
    }
}

/// Python exceptions are kept as they are, so they reach Python again with
/// all their arguments; [`Error::is_no_such_revision`] recognises the one
/// Rust code handles.
fn map_err(_py: Python<'_>, err: PyErr) -> Error {
    Error::Python(err)
}

fn call0(obj: &Py<PyAny>, name: &str) -> Result<PyObject, Error> {
    Python::attach(|py| {
        obj.bind(py)
            .call_method0(name)
            .map(|r| r.unbind())
            .map_err(|e| map_err(py, e))
    })
}

fn call0_extract<T>(obj: &Py<PyAny>, name: &str) -> Result<T, Error>
where
    T: for<'a, 'py> FromPyObject<'a, 'py, Error = PyErr>,
{
    Python::attach(|py| {
        obj.bind(py)
            .call_method0(name)
            .and_then(|r| r.extract())
            .map_err(|e| map_err(py, e))
    })
}

fn getattr_extract<T>(obj: &Py<PyAny>, name: &str) -> Result<T, Error>
where
    T: for<'a, 'py> FromPyObject<'a, 'py, Error = PyErr>,
{
    Python::attach(|py| {
        obj.bind(py)
            .getattr(name)
            .and_then(|r| r.extract())
            .map_err(|e| map_err(py, e))
    })
}

fn getattr_obj(obj: &Py<PyAny>, name: &str) -> Result<PyObject, Error> {
    Python::attach(|py| {
        obj.bind(py)
            .getattr(name)
            .map(|r| r.unbind())
            .map_err(|e| map_err(py, e))
    })
}

impl Repository for PyRepository {
    fn python_object(&self) -> Option<&PyObject> {
        Some(&self.0)
    }

    fn find_branches(
        &self,
        using: bool,
    ) -> Result<Vec<Box<dyn crate::branch::Branch + Send + Sync>>, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("using", using).unwrap();
            self.0
                .bind(py)
                .call_method("find_branches", (), Some(&kwargs))
                .and_then(|branches| {
                    branches
                        .try_iter()?
                        .map(|branch| {
                            Ok(Box::new(crate::pybranch::PyBranch::new(branch?.unbind()))
                                as Box<dyn crate::branch::Branch + Send + Sync>)
                        })
                        .collect::<PyResult<Vec<_>>>()
                })
                .map_err(|e| map_err(py, e))
        })
    }

    fn suspend_write_group(&mut self) -> Result<Vec<String>, Error> {
        call0_extract(&self.0, "suspend_write_group")
    }

    fn resume_write_group(&mut self, tokens: &[String]) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("resume_write_group", (tokens.to_vec(),))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_revision_deltas(
        &self,
        revisions: &[PyObject],
        specific_files: Option<&[&str]>,
    ) -> Result<Vec<PyObject>, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs
                .set_item("specific_files", specific_files.map(|f| f.to_vec()))
                .unwrap();
            let revisions: Vec<_> = revisions.iter().map(|r| r.bind(py)).collect();
            self.0
                .bind(py)
                .call_method("get_revision_deltas", (revisions,), Some(&kwargs))
                .and_then(|deltas| {
                    deltas
                        .try_iter()?
                        .map(|delta| Ok(delta?.unbind()))
                        .collect::<PyResult<Vec<_>>>()
                })
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_revision_reconcile(&self, revision_id: &RevisionId) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_revision_reconcile", (revision_id,))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn store_revision_signature(
        &mut self,
        gpg_strategy: &PyObject,
        plaintext: &[u8],
        revision_id: &RevisionId,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "store_revision_signature",
                    (
                        gpg_strategy.bind(py),
                        pyo3::types::PyBytes::new(py, plaintext),
                        revision_id,
                    ),
                )
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn verify_revision_signatures(
        &self,
        revision_ids: &[RevisionId],
        gpg_strategy: &PyObject,
    ) -> Result<Vec<PyObject>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "verify_revision_signatures",
                    (revision_ids.to_vec(), gpg_strategy.bind(py)),
                )
                .and_then(|results| {
                    results
                        .try_iter()?
                        .map(|result| Ok(result?.unbind()))
                        .collect::<PyResult<Vec<_>>>()
                })
                .map_err(|e| map_err(py, e))
        })
    }

    fn base(&self) -> Result<String, Error> {
        getattr_extract(&self.0, "base")
    }

    fn user_url(&self) -> Result<String, Error> {
        getattr_extract(&self.0, "user_url")
    }

    fn control_url(&self) -> Result<String, Error> {
        getattr_extract(&self.0, "control_url")
    }

    fn controldir(&self) -> Result<Box<dyn crate::controldir::ControlDir>, Error> {
        let dir = getattr_obj(&self.0, "controldir")?;
        Ok(Box::new(crate::pycontroldir::PyControlDir::new(dir)))
    }

    fn supports_random_access(&self) -> Result<bool, Error> {
        getattr_extract(&self.0, "supports_random_access")
    }

    fn control_files(&self) -> Result<PyObject, Error> {
        getattr_obj(&self.0, "control_files")
    }

    fn user_transport(&self) -> Result<PyObject, Error> {
        getattr_obj(&self.0, "user_transport")
    }

    fn control_transport(&self) -> Result<PyObject, Error> {
        getattr_obj(&self.0, "control_transport")
    }

    fn break_lock(&self) -> Result<(), crate::lock::Error> {
        crate::pylock::call(&self.0, "break_lock")
    }

    fn is_locked(&self) -> Result<bool, Error> {
        call0_extract(&self.0, "is_locked")
    }

    fn is_write_locked(&self) -> Result<bool, Error> {
        call0_extract(&self.0, "is_write_locked")
    }

    fn lock_write(
        &self,
        token: Option<&[u8]>,
    ) -> Result<crate::lock::WriteLockRef, crate::lock::Error> {
        crate::pylock::lock_write_with_token(&self.0, token)
    }

    fn lock_read(&self) -> Result<crate::lock::ReadLockRef, crate::lock::Error> {
        crate::pylock::lock_read(&self.0)
    }

    fn unlock(&self) -> Result<(), crate::lock::Error> {
        crate::pylock::call(&self.0, "unlock")
    }

    fn get_physical_lock_status(&self) -> Result<bool, crate::lock::Error> {
        crate::pylock::get_physical_lock_status(&self.0)
    }

    fn leave_lock_in_place(&self) -> Result<(), crate::lock::Error> {
        crate::pylock::call(&self.0, "leave_lock_in_place")
    }

    fn dont_leave_lock_in_place(&self) -> Result<(), crate::lock::Error> {
        crate::pylock::call(&self.0, "dont_leave_lock_in_place")
    }

    fn has_same_location(&self, other: &PyObject) -> Result<bool, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("has_same_location", (other.bind(py),))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn is_shared(&self) -> Result<bool, Error> {
        call0_extract(&self.0, "is_shared")
    }

    fn supports_rich_root(&self) -> Result<bool, Error> {
        call0_extract(&self.0, "supports_rich_root")
    }

    fn get_transaction(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_transaction")
    }

    fn make_working_trees(&self) -> Result<bool, Error> {
        call0_extract(&self.0, "make_working_trees")
    }

    fn set_make_working_trees(&mut self, new_value: bool) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_make_working_trees", (new_value,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn all_revision_ids(&self) -> Result<Vec<RevisionId>, Error> {
        call0_extract(&self.0, "all_revision_ids")
    }

    fn has_revision(&self, revision_id: &RevisionId) -> Result<bool, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("has_revision", (revision_id,))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn has_revisions(&self, revision_ids: &[RevisionId]) -> Result<Vec<RevisionId>, Error> {
        Python::attach(|py| {
            let present: std::collections::HashSet<RevisionId> = self
                .0
                .bind(py)
                .call_method1("has_revisions", (revision_ids.to_vec(),))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))?;
            Ok(present.into_iter().collect())
        })
    }

    fn get_revision(&self, revision_id: &RevisionId) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_revision", (revision_id,))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_revisions(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_revisions", (revision_ids.to_vec(),))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn iter_revisions(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("iter_revisions", (revision_ids.to_vec(),))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_revision_delta(&self, revision_id: &RevisionId) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_revision_delta", (revision_id,))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_rev_id_for_revno(
        &self,
        revno: i64,
        known_pair: (u64, RevisionId),
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_rev_id_for_revno", (revno, known_pair))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_parent_map(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_parent_map", (revision_ids.to_vec(),))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_known_graph_ancestry(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_known_graph_ancestry", (revision_ids.to_vec(),))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_graph(&self, other_repository: Option<&PyObject>) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_graph", (other_repository.map(|r| r.bind(py)),))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_file_graph(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_file_graph")
    }

    fn revision_tree(&self, revision_id: &RevisionId) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("revision_tree", (revision_id,))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn revision_trees(&self, revision_ids: &[RevisionId]) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("revision_trees", (revision_ids.to_vec(),))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn iter_files_bytes(
        &self,
        desired_files: &[(RevisionId, RevisionId, PyObject)],
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let items = pyo3::types::PyList::empty(py);
            for (file_id, revision_id, identifier) in desired_files {
                let tuple = pyo3::types::PyTuple::new(
                    py,
                    [
                        file_id.into_pyobject(py).unwrap().into_any(),
                        revision_id.into_pyobject(py).unwrap().into_any(),
                        identifier.bind(py).clone(),
                    ],
                )
                .unwrap();
                items.append(tuple).unwrap();
            }
            self.0
                .bind(py)
                .call_method1("iter_files_bytes", (items,))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn has_signature_for_revision_id(&self, revision_id: &RevisionId) -> Result<bool, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("has_signature_for_revision_id", (revision_id,))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_signature_text(&self, revision_id: &RevisionId) -> Result<Vec<u8>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_signature_text", (revision_id,))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn add_signature_text(
        &mut self,
        revision_id: &RevisionId,
        signature: &[u8],
    ) -> Result<(), Error> {
        Python::attach(|py| {
            let sig = PyBytes::new(py, signature);
            self.0
                .bind(py)
                .call_method1("add_signature_text", (revision_id, sig))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn sign_revision(
        &mut self,
        revision_id: &RevisionId,
        gpg_strategy: &PyObject,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("sign_revision", (revision_id, gpg_strategy.bind(py)))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn verify_revision_signature(
        &self,
        revision_id: &RevisionId,
        gpg_strategy: &PyObject,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "verify_revision_signature",
                    (revision_id, gpg_strategy.bind(py)),
                )
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn is_in_write_group(&self) -> Result<bool, Error> {
        call0_extract(&self.0, "is_in_write_group")
    }

    fn start_write_group(&mut self) -> Result<(), Error> {
        call0(&self.0, "start_write_group").map(|_| ())
    }

    fn commit_write_group(&mut self) -> Result<Option<PyObject>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method0("commit_write_group")
                .map_err(|e| map_err(py, e))?;
            if result.is_none() {
                Ok(None)
            } else {
                Ok(Some(result.unbind()))
            }
        })
    }

    fn abort_write_group(&mut self, suppress_errors: bool) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("abort_write_group", (suppress_errors,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn refresh_data(&mut self) -> Result<(), Error> {
        call0(&self.0, "refresh_data").map(|_| ())
    }

    fn fetch(
        &mut self,
        source: &PyObject,
        revision_id: Option<&RevisionId>,
        find_ghosts: bool,
        lossy: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("revision_id", revision_id).unwrap();
            kwargs.set_item("find_ghosts", find_ghosts).unwrap();
            kwargs.set_item("lossy", lossy).unwrap();
            self.0
                .bind(py)
                .call_method("fetch", (source.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn search_missing_revision_ids(
        &self,
        other: &PyObject,
        find_ghosts: bool,
        revision_ids: Option<&[RevisionId]>,
        if_present_ids: Option<&[RevisionId]>,
        limit: Option<u64>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("find_ghosts", find_ghosts).unwrap();
            kwargs
                .set_item("revision_ids", revision_ids.map(|r| r.to_vec()))
                .unwrap();
            kwargs
                .set_item("if_present_ids", if_present_ids.map(|r| r.to_vec()))
                .unwrap();
            kwargs.set_item("limit", limit).unwrap();
            self.0
                .bind(py)
                .call_method(
                    "search_missing_revision_ids",
                    (other.bind(py),),
                    Some(&kwargs),
                )
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn copy_content_into(
        &self,
        destination: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("copy_content_into", (destination.bind(py), revision_id))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn clone(
        &self,
        controldir: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("clone", (controldir.bind(py), revision_id))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn sprout(
        &self,
        to_bzrdir: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("sprout", (to_bzrdir.bind(py), revision_id))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn pack(&mut self, hint: Option<&PyObject>, clean_obsolete_packs: bool) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("pack", (hint.map(|h| h.bind(py)), clean_obsolete_packs))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn reconcile(&mut self, other: Option<&PyObject>, thorough: bool) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("thorough", thorough).unwrap();
            self.0
                .bind(py)
                .call_method("reconcile", (other.map(|o| o.bind(py)),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn check(
        &self,
        revision_ids: Option<&[RevisionId]>,
        check_repo: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("check_repo", check_repo).unwrap();
            self.0
                .bind(py)
                .call_method("check", (revision_ids.map(|r| r.to_vec()),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn gather_stats(
        &self,
        revid: Option<&RevisionId>,
        committers: Option<bool>,
    ) -> Result<HashMap<String, PyObject>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("gather_stats", (revid, committers))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn add_fallback_repository(&mut self, repository: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("add_fallback_repository", (repository.bind(py),))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_commit_builder(
        &mut self,
        branch: &PyObject,
        parents: &[RevisionId],
        config_stack: &PyObject,
        timestamp: Option<f64>,
        timezone: Option<i32>,
        committer: Option<&str>,
        revprops: Option<&PyObject>,
        revision_id: Option<&RevisionId>,
        lossy: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("timestamp", timestamp).unwrap();
            kwargs.set_item("timezone", timezone).unwrap();
            kwargs.set_item("committer", committer).unwrap();
            kwargs
                .set_item("revprops", revprops.map(|r| r.bind(py)))
                .unwrap();
            kwargs.set_item("revision_id", revision_id).unwrap();
            kwargs.set_item("lossy", lossy).unwrap();
            self.0
                .bind(py)
                .call_method(
                    "get_commit_builder",
                    (branch.bind(py), parents.to_vec(), config_stack.bind(py)),
                    Some(&kwargs),
                )
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }
}
