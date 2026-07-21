use crate::branch::{Branch, Error, PyObject};
use bazaar::RevisionId;
use pyo3::import_exception;
use pyo3::prelude::*;

/// A wrapper around a Python branch object.
///
/// This struct provides a Rust interface to Python branch objects, implementing
/// the [`Branch`] trait by delegating each method to the wrapped Python branch.
pub struct PyBranch(Py<PyAny>);

impl PyBranch {
    /// Creates a new `PyBranch` wrapper around a Python branch object.
    pub fn new(o: Py<PyAny>) -> Self {
        PyBranch(o)
    }

    /// Returns a reference to the wrapped Python object.
    pub fn as_pyobject(&self) -> &Py<PyAny> {
        &self.0
    }
}

import_exception!(breezy.errors, NoSuchRevision);
import_exception!(breezy.errors, NotStacked);
import_exception!(breezy.errors, UpgradeRequired);
import_exception!(breezy.branch, BindingUnsupported);
import_exception!(breezy.errors, UnsupportedOperation);

fn map_err(py: Python<'_>, err: PyErr) -> Error {
    if err.is_instance_of::<NoSuchRevision>(py) {
        let revid = err
            .value(py)
            .getattr("revision")
            .and_then(|r| r.extract::<RevisionId>());
        match revid {
            Ok(revid) => Error::NoSuchRevision(revid),
            Err(_) => Error::Other(err.to_string()),
        }
    } else if err.is_instance_of::<NotStacked>(py) {
        Error::NotStacked
    } else if err.is_instance_of::<UpgradeRequired>(py) {
        Error::UpgradeRequired
    } else if err.is_instance_of::<BindingUnsupported>(py) {
        Error::BindingUnsupported
    } else if err.is_instance_of::<UnsupportedOperation>(py) {
        Error::UnsupportedOperation(err.to_string())
    } else {
        Error::Other(err.to_string())
    }
}

/// Call a no-argument method and map any error.
fn call0(obj: &Py<PyAny>, name: &str) -> Result<PyObject, Error> {
    Python::attach(|py| {
        obj.bind(py)
            .call_method0(name)
            .map(|r| r.unbind())
            .map_err(|e| map_err(py, e))
    })
}

/// Call a no-argument method and extract a value, mapping any error.
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

impl Branch for PyBranch {
    fn name(&self) -> Result<String, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("name")
                .and_then(|n| n.extract::<Option<String>>())
                .map(Option::unwrap_or_default)
                .map_err(|e| map_err(py, e))
        })
    }

    fn user_transport(&self) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("user_transport")
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn nick(&self) -> Result<String, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("nick")
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn set_nick(&mut self, nick: &str) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .setattr("nick", nick)
                .map_err(|e| map_err(py, e))
        })
    }

    fn break_lock(&mut self) -> Result<(), Error> {
        call0(&self.0, "break_lock").map(|_| ())
    }

    fn is_locked(&self) -> Result<bool, Error> {
        call0_extract(&self.0, "is_locked")
    }

    fn lock_write(&mut self, token: Option<&str>) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("lock_write", (token,))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn lock_read(&self) -> Result<PyObject, Error> {
        call0(&self.0, "lock_read")
    }

    fn unlock(&mut self) -> Result<(), Error> {
        call0(&self.0, "unlock").map(|_| ())
    }

    fn peek_lock_mode(&self) -> Result<Option<String>, Error> {
        call0_extract(&self.0, "peek_lock_mode")
    }

    fn get_physical_lock_status(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_physical_lock_status")
    }

    fn leave_lock_in_place(&mut self) -> Result<(), Error> {
        call0(&self.0, "leave_lock_in_place").map(|_| ())
    }

    fn dont_leave_lock_in_place(&mut self) -> Result<(), Error> {
        call0(&self.0, "dont_leave_lock_in_place").map(|_| ())
    }

    fn last_revision(&self) -> Result<RevisionId, Error> {
        call0_extract(&self.0, "last_revision")
    }

    fn last_revision_info(&self) -> Result<(u64, RevisionId), Error> {
        call0_extract(&self.0, "last_revision_info")
    }

    fn set_last_revision_info(
        &mut self,
        revno: u64,
        revision_id: &RevisionId,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_last_revision_info", (revno, revision_id))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn revno(&self) -> Result<u64, Error> {
        call0_extract(&self.0, "revno")
    }

    fn revision_id_to_revno(&self, revision_id: &RevisionId) -> Result<u64, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("revision_id_to_revno", (revision_id,))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_rev_id(&self, revno: i64) -> Result<RevisionId, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_rev_id", (revno,))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn revision_id_to_dotted_revno(&self, revision_id: &RevisionId) -> Result<Vec<i32>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("revision_id_to_dotted_revno", (revision_id,))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn dotted_revno_to_revision_id(&self, revno: &[i32]) -> Result<RevisionId, Error> {
        Python::attach(|py| {
            // Python compares the revno with the tuples of its revno map.
            pyo3::types::PyTuple::new(py, revno)
                .and_then(|revno| {
                    self.0
                        .bind(py)
                        .call_method1("dotted_revno_to_revision_id", (revno,))
                })
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_revision_id_to_revno_map(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_revision_id_to_revno_map")
    }

    fn iter_merge_sorted_revisions(
        &self,
        start_revision_id: Option<&RevisionId>,
        stop_revision_id: Option<&RevisionId>,
        stop_rule: &str,
        direction: &str,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs
                .set_item("start_revision_id", start_revision_id)
                .unwrap();
            kwargs
                .set_item("stop_revision_id", stop_revision_id)
                .unwrap();
            kwargs.set_item("stop_rule", stop_rule).unwrap();
            kwargs.set_item("direction", direction).unwrap();
            self.0
                .bind(py)
                .call_method("iter_merge_sorted_revisions", (), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn generate_revision_history(
        &mut self,
        revision_id: &RevisionId,
        last_rev: Option<&RevisionId>,
        other_branch: Option<&PyObject>,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "generate_revision_history",
                    (revision_id, last_rev, other_branch.map(|b| b.bind(py))),
                )
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn import_last_revision_info_and_tags(
        &mut self,
        source: &PyObject,
        revno: u64,
        revid: &RevisionId,
        lossy: bool,
    ) -> Result<(u64, RevisionId), Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("lossy", lossy).unwrap();
            self.0
                .bind(py)
                .call_method(
                    "import_last_revision_info_and_tags",
                    (source.bind(py), revno, revid),
                    Some(&kwargs),
                )
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn check_revno(&self, revno: i64) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("check_revno", (revno,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn check_real_revno(&self, revno: i64) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("check_real_revno", (revno,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn heads_to_fetch(&self) -> Result<(Vec<RevisionId>, Vec<RevisionId>), Error> {
        // Python returns a tuple of two sets, which cannot be extracted as
        // Vec directly, so extract as HashSet and collect.
        let (must, if_present): (
            std::collections::HashSet<RevisionId>,
            std::collections::HashSet<RevisionId>,
        ) = call0_extract(&self.0, "heads_to_fetch")?;
        Ok((must.into_iter().collect(), if_present.into_iter().collect()))
    }

    fn get_config(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_config")
    }

    fn get_config_stack(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_config_stack")
    }

    fn get_append_revisions_only(&self) -> Result<bool, Error> {
        call0_extract(&self.0, "get_append_revisions_only")
    }

    fn set_append_revisions_only(&mut self, enabled: bool) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_append_revisions_only", (enabled,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_parent(&self) -> Result<Option<String>, Error> {
        call0_extract(&self.0, "get_parent")
    }

    fn set_parent(&mut self, url: Option<&str>) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_parent", (url,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_push_location(&self) -> Result<Option<String>, Error> {
        call0_extract(&self.0, "get_push_location")
    }

    fn set_push_location(&mut self, location: &str) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_push_location", (location,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_submit_branch(&self) -> Result<Option<String>, Error> {
        call0_extract(&self.0, "get_submit_branch")
    }

    fn set_submit_branch(&mut self, location: &str) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_submit_branch", (location,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_public_branch(&self) -> Result<Option<String>, Error> {
        call0_extract(&self.0, "get_public_branch")
    }

    fn set_public_branch(&mut self, location: &str) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_public_branch", (location,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_child_submit_format(&self) -> Result<Option<String>, Error> {
        call0_extract(&self.0, "get_child_submit_format")
    }

    fn get_stacked_on_url(&self) -> Result<String, Error> {
        call0_extract(&self.0, "get_stacked_on_url")
    }

    fn set_stacked_on_url(&mut self, url: Option<&str>) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_stacked_on_url", (url,))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn bind(&mut self, other: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("bind", (other.bind(py),))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn unbind(&mut self) -> Result<(), Error> {
        call0(&self.0, "unbind").map(|_| ())
    }

    fn get_bound_location(&self) -> Result<Option<String>, Error> {
        call0_extract(&self.0, "get_bound_location")
    }

    fn get_old_bound_location(&self) -> Result<Option<String>, Error> {
        call0_extract(&self.0, "get_old_bound_location")
    }

    fn get_master_branch(&self) -> Result<Option<PyObject>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method0("get_master_branch")
                .map_err(|e| map_err(py, e))?;
            if result.is_none() {
                Ok(None)
            } else {
                Ok(Some(result.unbind()))
            }
        })
    }

    fn update(&mut self) -> Result<(), Error> {
        call0(&self.0, "update").map(|_| ())
    }

    fn tags(&self) -> Box<dyn crate::tags::Tags> {
        Python::attach(|py| {
            let py_tags = self.0.bind(py).getattr("tags").unwrap();
            Box::new(crate::pytags::PyTags(py_tags.unbind()))
        })
    }

    fn supports_tags(&self) -> bool {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("supports_tags")
                .and_then(|r| r.extract())
                .unwrap_or(false)
        })
    }

    fn automatic_tag_name(&self, revision_id: &RevisionId) -> Result<Option<String>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("automatic_tag_name", (revision_id,))
                .and_then(|r| r.extract())
                .map_err(|e| map_err(py, e))
        })
    }

    fn fetch(
        &mut self,
        from_branch: &PyObject,
        stop_revision: Option<&RevisionId>,
        limit: Option<u64>,
        lossy: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("stop_revision", stop_revision).unwrap();
            kwargs.set_item("limit", limit).unwrap();
            kwargs.set_item("lossy", lossy).unwrap();
            self.0
                .bind(py)
                .call_method("fetch", (from_branch.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn pull(
        &mut self,
        source: &PyObject,
        overwrite: bool,
        stop_revision: Option<&RevisionId>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("overwrite", overwrite).unwrap();
            kwargs.set_item("stop_revision", stop_revision).unwrap();
            self.0
                .bind(py)
                .call_method("pull", (source.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn push(
        &mut self,
        target: &PyObject,
        overwrite: bool,
        stop_revision: Option<&RevisionId>,
        lossy: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("overwrite", overwrite).unwrap();
            kwargs.set_item("stop_revision", stop_revision).unwrap();
            kwargs.set_item("lossy", lossy).unwrap();
            self.0
                .bind(py)
                .call_method("push", (target.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn basis_tree(&self) -> Result<PyObject, Error> {
        call0(&self.0, "basis_tree")
    }

    fn get_commit_builder(
        &mut self,
        parents: &[RevisionId],
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
                .call_method("get_commit_builder", (parents.to_vec(),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn create_memorytree(&self) -> Result<PyObject, Error> {
        call0(&self.0, "create_memorytree")
    }

    fn clone(
        &self,
        to_controldir: &PyObject,
        revision_id: Option<&RevisionId>,
        name: Option<&str>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("revision_id", revision_id).unwrap();
            kwargs.set_item("name", name).unwrap();
            self.0
                .bind(py)
                .call_method("clone", (to_controldir.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn sprout(
        &self,
        to_controldir: &PyObject,
        revision_id: Option<&RevisionId>,
        lossy: bool,
        name: Option<&str>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("revision_id", revision_id).unwrap();
            kwargs.set_item("lossy", lossy).unwrap();
            kwargs.set_item("name", name).unwrap();
            self.0
                .bind(py)
                .call_method("sprout", (to_controldir.bind(py),), Some(&kwargs))
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
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("revision_id", revision_id).unwrap();
            self.0
                .bind(py)
                .call_method("copy_content_into", (destination.bind(py),), Some(&kwargs))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn update_references(&self, target: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("update_references", (target.bind(py),))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn create_clone_on_transport(
        &self,
        to_transport: &PyObject,
        revision_id: Option<&RevisionId>,
        stacked_on: Option<&str>,
        create_prefix: bool,
        use_existing_dir: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("revision_id", revision_id).unwrap();
            kwargs.set_item("stacked_on", stacked_on).unwrap();
            kwargs.set_item("create_prefix", create_prefix).unwrap();
            kwargs
                .set_item("use_existing_dir", use_existing_dir)
                .unwrap();
            self.0
                .bind(py)
                .call_method(
                    "create_clone_on_transport",
                    (to_transport.bind(py),),
                    Some(&kwargs),
                )
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn create_checkout(
        &self,
        to_location: &str,
        revision_id: Option<&RevisionId>,
        lightweight: bool,
        hardlink: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("revision_id", revision_id).unwrap();
            kwargs.set_item("lightweight", lightweight).unwrap();
            kwargs.set_item("hardlink", hardlink).unwrap();
            self.0
                .bind(py)
                .call_method("create_checkout", (to_location,), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn check(&self, refs: &PyObject) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("check", (refs.bind(py),))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn reconcile(&mut self, thorough: bool) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("reconcile", (thorough,))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }

    fn store_uncommitted(&mut self, creator: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("store_uncommitted", (creator.bind(py),))
                .map(|_| ())
                .map_err(|e| map_err(py, e))
        })
    }

    fn get_unshelver(&self, tree: &PyObject) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_unshelver", (tree.bind(py),))
                .map(|r| r.unbind())
                .map_err(|e| map_err(py, e))
        })
    }
}
