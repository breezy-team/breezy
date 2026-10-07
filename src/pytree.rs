use crate::tree::{
    ContentSummary, Error, IgnoredFiles, MutableTree, PyObject, RevisionTree, Tree, WorkingTree,
};
use bazaar::osutils::Kind;
use bazaar::{FileId, RevisionId};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList, PyTuple};
use std::str::FromStr;

/// A wrapper around a Python tree object.
///
/// This struct provides a Rust interface to Python tree objects, implementing
/// the various tree traits (`Tree`, `MutableTree`, `WorkingTree`, `RevisionTree`).
/// It allows Rust code to interact with Python tree implementations.
pub struct PyTree(Py<PyAny>);

impl PyTree {
    /// Creates a new `PyTree` wrapper around a Python tree object.
    ///
    /// # Arguments
    ///
    /// * `obj` - The Python tree object to wrap.
    pub fn new(obj: Py<PyAny>) -> Self {
        PyTree(obj)
    }

    /// Returns a reference to the wrapped Python object.
    pub fn as_pyobject(&self) -> &Py<PyAny> {
        &self.0
    }
}

import_exception!(bzrformats.errors, NotVersionedError);
import_exception!(breezy.errors, PathsNotVersionedError);
import_exception!(dromedary.errors, NoSuchFile);
import_exception!(breezy.errors, NoSuchRevisionInTree);
import_exception!(breezy.errors, NoSuchRevision);
import_exception!(breezy.errors, UnsupportedOperation);

fn map_py_err_to_err(py: Python<'_>, py_err: PyErr) -> Error {
    if py_err.is_instance_of::<NotVersionedError>(py) {
        Error::NotVersioned(
            py_err
                .value(py)
                .getattr("path")
                .map(|p| p.to_string())
                .unwrap_or_default(),
        )
    } else if py_err.is_instance_of::<PathsNotVersionedError>(py) {
        let paths = py_err
            .value(py)
            .getattr("paths")
            .and_then(|p| p.extract::<Vec<String>>())
            .unwrap_or_default();
        Error::PathsNotVersioned(paths)
    } else if py_err.is_instance_of::<NoSuchFile>(py) {
        Error::NoSuchFile(
            py_err
                .value(py)
                .getattr("path")
                .map(|p| p.to_string())
                .unwrap_or_default(),
        )
    } else if py_err.is_instance_of::<NoSuchRevisionInTree>(py)
        || py_err.is_instance_of::<NoSuchRevision>(py)
    {
        // NoSuchRevisionInTree stores the id on `revision_id`; NoSuchRevision
        // uses `revision`. Fall back to the raw error text if neither yields a
        // valid revision id, rather than fabricating an (invalid) one.
        let value = py_err.value(py);
        let revid = value
            .getattr("revision_id")
            .and_then(|r| r.extract::<RevisionId>())
            .or_else(|_| {
                value
                    .getattr("revision")
                    .and_then(|r| r.extract::<RevisionId>())
            });
        match revid {
            Ok(revid) => Error::NoSuchRevision(revid),
            Err(_) => Error::Other(py_err.to_string()),
        }
    } else if py_err.is_instance_of::<UnsupportedOperation>(py) {
        Error::UnsupportedOperation(py_err.to_string())
    } else {
        Error::Other(py_err.to_string())
    }
}

/// Call a no-argument method, returning any error mapped to [`Error`].
fn call0(obj: &Py<PyAny>, name: &str) -> Result<PyObject, Error> {
    Python::attach(|py| {
        obj.bind(py)
            .call_method0(name)
            .map(|r| r.unbind())
            .map_err(|e| map_py_err_to_err(py, e))
    })
}

/// Call a method without arguments and extract a bool result.
fn call0_bool(obj: &Py<PyAny>, name: &str) -> Result<bool, Error> {
    call1_extract(obj, name, ())
}

/// Call a method and extract its result.
fn call1_extract<T, A>(obj: &Py<PyAny>, name: &str, args: A) -> Result<T, Error>
where
    A: for<'py> pyo3::call::PyCallArgs<'py>,
    T: for<'a, 'py> pyo3::FromPyObject<'a, 'py, Error = PyErr>,
{
    Python::attach(|py| {
        obj.bind(py)
            .call_method1(name, args)
            .and_then(|r| r.extract())
            .map_err(|e| map_py_err_to_err(py, e))
    })
}

/// Read an attribute and extract it.
fn getattr_extract<T>(obj: &Py<PyAny>, name: &str) -> Result<T, Error>
where
    T: for<'a, 'py> pyo3::FromPyObject<'a, 'py, Error = PyErr>,
{
    Python::attach(|py| {
        obj.bind(py)
            .getattr(name)
            .and_then(|r| r.extract())
            .map_err(|e| map_py_err_to_err(py, e))
    })
}

/// Collect a Python iterable (generator, iterator, list, set, ...) into a `Vec`.
///
/// Several tree methods return generators rather than materialized sequences,
/// which cannot be extracted into a `Vec` directly.
fn collect_iter<'py, T>(py: Python<'py>, obj: Bound<'py, PyAny>) -> Result<Vec<T>, Error>
where
    T: for<'a> pyo3::FromPyObject<'a, 'py, Error = pyo3::PyErr>,
{
    let mut out = Vec::new();
    for item in obj.try_iter().map_err(|e| map_py_err_to_err(py, e))? {
        let item = item.map_err(|e| map_py_err_to_err(py, e))?;
        out.push(item.extract().map_err(|e| map_py_err_to_err(py, e))?);
    }
    Ok(out)
}

impl Tree for PyTree {
    fn python_object(&self) -> Option<&PyObject> {
        Some(&self.0)
    }

    fn supports_rename_tracking(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "supports_rename_tracking")
    }

    fn has_versioned_directories(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "has_versioned_directories")
    }

    fn supports_tree_reference(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "supports_tree_reference")
    }

    fn supports_symlinks(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "supports_symlinks")
    }

    fn is_special_path(&self, path: &str) -> Result<bool, Error> {
        call1_extract(&self.0, "is_special_path", (path,))
    }

    fn supports_file_ids(&self) -> Result<bool, Error> {
        getattr_extract(&self.0, "supports_file_ids")
    }

    fn supports_content_filtering(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "supports_content_filtering")
    }

    fn changes_from(
        &self,
        other: &PyObject,
        want_unchanged: bool,
        specific_files: Option<&[&str]>,
        extra_trees: Option<&[PyObject]>,
        require_versioned: bool,
        include_root: bool,
        want_unversioned: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("want_unchanged", want_unchanged).unwrap();
            kwargs
                .set_item("specific_files", specific_files.map(|s| s.to_vec()))
                .unwrap();
            kwargs
                .set_item(
                    "extra_trees",
                    extra_trees.map(|t| t.iter().map(|o| o.bind(py)).collect::<Vec<_>>()),
                )
                .unwrap();
            kwargs
                .set_item("require_versioned", require_versioned)
                .unwrap();
            kwargs.set_item("include_root", include_root).unwrap();
            kwargs
                .set_item("want_unversioned", want_unversioned)
                .unwrap();
            self.0
                .bind(py)
                .call_method("changes_from", (other.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn iter_changes(
        &self,
        from_tree: &PyObject,
        include_unchanged: bool,
        specific_files: Option<&[&str]>,
        extra_trees: Option<&[PyObject]>,
        require_versioned: bool,
        want_unversioned: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs
                .set_item("include_unchanged", include_unchanged)
                .unwrap();
            kwargs
                .set_item("specific_files", specific_files.map(|s| s.to_vec()))
                .unwrap();
            kwargs
                .set_item(
                    "extra_trees",
                    extra_trees.map(|t| t.iter().map(|o| o.bind(py)).collect::<Vec<_>>()),
                )
                .unwrap();
            kwargs
                .set_item("require_versioned", require_versioned)
                .unwrap();
            kwargs
                .set_item("want_unversioned", want_unversioned)
                .unwrap();
            self.0
                .bind(py)
                .call_method("iter_changes", (from_tree.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn conflicts(&self) -> Result<PyObject, Error> {
        call0(&self.0, "conflicts")
    }

    fn extras(&self) -> Result<Vec<String>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method0("extras")
                .map_err(|e| map_py_err_to_err(py, e))?;
            collect_iter(py, result)
        })
    }

    fn get_parent_ids(&self) -> Result<Vec<RevisionId>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("get_parent_ids")
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn has_filename(&self, filename: &str) -> Result<bool, Error> {
        call1_extract(&self.0, "has_filename", (filename,))
    }

    fn is_ignored(&self, filename: &str) -> bool {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("is_ignored", (filename,))
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn all_versioned_paths(&self) -> Result<Vec<String>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method0("all_versioned_paths")
                .map_err(|e| map_py_err_to_err(py, e))?;
            collect_iter(py, result)
        })
    }

    fn iter_entries_by_dir(
        &self,
        specific_files: Option<&[&str]>,
        recurse_nested: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs
                .set_item("specific_files", specific_files.map(|s| s.to_vec()))
                .unwrap();
            kwargs.set_item("recurse_nested", recurse_nested).unwrap();
            self.0
                .bind(py)
                .call_method("iter_entries_by_dir", (), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn iter_child_entries(&self, path: &str) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("iter_child_entries", (path,))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn list_files(
        &self,
        include_root: bool,
        from_dir: Option<&str>,
        recursive: bool,
        recurse_nested: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "list_files",
                    (include_root, from_dir, recursive, recurse_nested),
                )
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn iter_references(&self) -> Result<Vec<String>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method0("iter_references")
                .map_err(|e| map_py_err_to_err(py, e))?;
            collect_iter(py, result)
        })
    }

    fn get_containing_nested_tree(&self, path: &str) -> Result<Option<(PyObject, String)>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method1("get_containing_nested_tree", (path,))
                .map_err(|e| map_py_err_to_err(py, e))?;
            let (tree, subpath): (Option<Py<PyAny>>, Option<String>) =
                result.extract().map_err(|e| map_py_err_to_err(py, e))?;
            Ok(match (tree, subpath) {
                (Some(t), Some(p)) => Some((t, p)),
                _ => None,
            })
        })
    }

    fn get_nested_tree(&self, path: &str) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_nested_tree", (path,))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn kind(&self, path: &str) -> Result<Kind, Error> {
        Python::attach(|py| {
            let kind_str: String = self
                .0
                .bind(py)
                .call_method1("kind", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))?;
            Kind::from_str(&kind_str).map_err(|e| Error::Other(e.to_string()))
        })
    }

    fn stored_kind(&self, path: &str) -> Result<Kind, Error> {
        Python::attach(|py| {
            let kind_str: String = self
                .0
                .bind(py)
                .call_method1("stored_kind", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))?;
            Kind::from_str(&kind_str).map_err(|e| Error::Other(e.to_string()))
        })
    }

    fn path_content_summary(&self, path: &str) -> Result<ContentSummary, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method1("path_content_summary", (path,))
                .map_err(|e| map_py_err_to_err(py, e))?;
            let tuple = result
                .cast::<PyTuple>()
                .map_err(|e| Error::Other(e.to_string()))?;
            let summary = (|| -> PyResult<ContentSummary> {
                let kind: String = tuple.get_item(0)?.extract()?;
                let last = tuple.get_item(3)?;
                // The sha1 is bytes, a symlink target str.
                let sha1_or_link = if last.is_none() {
                    None
                } else if let Ok(sha1) = last.cast::<PyBytes>() {
                    Some(crate::tree::Sha1OrLink::Sha1(sha1.as_bytes().to_vec()))
                } else {
                    Some(crate::tree::Sha1OrLink::Link(last.extract()?))
                };
                Ok(ContentSummary {
                    kind,
                    size: tuple.get_item(1)?.extract()?,
                    executable: tuple.get_item(2)?.extract()?,
                    sha1_or_link,
                })
            })();
            summary.map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_reference_revision(&self, path: &str) -> Result<RevisionId, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_reference_revision", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_file(&self, path: &str) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_file", (path,))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_file_with_stat(&self, path: &str) -> Result<(PyObject, Option<PyObject>), Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method1("get_file_with_stat", (path,))
                .map_err(|e| map_py_err_to_err(py, e))?;
            let (file, stat): (Py<PyAny>, Option<Py<PyAny>>) =
                result.extract().map_err(|e| map_py_err_to_err(py, e))?;
            Ok((file, stat))
        })
    }

    fn get_file_text(&self, path: &str) -> Result<Vec<u8>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_file_text", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_file_lines(&self, path: &str) -> Result<Vec<Vec<u8>>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_file_lines", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_file_verifier(
        &self,
        path: &str,
        stat_value: Option<&PyObject>,
    ) -> Result<(String, Option<Vec<u8>>), Error> {
        Python::attach(|py| {
            let stat = stat_value.map(|s| s.bind(py));
            self.0
                .bind(py)
                .call_method1("get_file_verifier", (path, stat))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_file_sha1(
        &self,
        path: &str,
        stat_value: Option<&PyObject>,
    ) -> Result<Option<Vec<u8>>, Error> {
        Python::attach(|py| {
            let stat = stat_value.map(|s| s.bind(py));
            self.0
                .bind(py)
                .call_method1("get_file_sha1", (path, stat))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_file_mtime(&self, path: &str) -> Result<f64, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_file_mtime", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_file_size(&self, path: &str) -> Result<Option<u64>, Error> {
        call1_extract(&self.0, "get_file_size", (path,))
    }

    fn is_executable(&self, path: &str) -> Result<bool, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("is_executable", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn iter_files_bytes(&self, desired_files: &[(&str, PyObject)]) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let items = PyList::empty(py);
            for (path, identifier) in desired_files {
                let pair = PyTuple::new(
                    py,
                    [
                        path.into_pyobject(py).unwrap().into_any(),
                        identifier.bind(py).clone(),
                    ],
                )
                .unwrap();
                items.append(pair).unwrap();
            }
            self.0
                .bind(py)
                .call_method1("iter_files_bytes", (items,))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_symlink_target(&self, path: &str) -> Result<Option<String>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_symlink_target", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn annotate_iter(
        &self,
        path: &str,
        default_revision: Option<&RevisionId>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            if let Some(rev) = default_revision {
                kwargs.set_item("default_revision", rev).unwrap();
            }
            self.0
                .bind(py)
                .call_method("annotate_iter", (path,), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn is_versioned(&self, path: &str) -> Result<bool, Error> {
        call1_extract(&self.0, "is_versioned", (path,))
    }

    fn find_related_paths_across_trees(
        &self,
        paths: &[&str],
        trees: Option<&[PyObject]>,
        require_versioned: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs
                .set_item(
                    "trees",
                    trees.map(|t| t.iter().map(|o| o.bind(py)).collect::<Vec<_>>()),
                )
                .unwrap();
            kwargs
                .set_item("require_versioned", require_versioned)
                .unwrap();
            self.0
                .bind(py)
                .call_method(
                    "find_related_paths_across_trees",
                    (paths.to_vec(),),
                    Some(&kwargs),
                )
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn lock_read(&self) -> Result<PyObject, Error> {
        call0(&self.0, "lock_read")
    }

    fn revision_tree(&self, revision_id: &RevisionId) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("revision_tree", (revision_id,))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn unknowns(&self) -> Result<Vec<String>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method0("unknowns")
                .map_err(|e| map_py_err_to_err(py, e))?;
            collect_iter(py, result)
        })
    }

    fn unlock(&mut self) -> Result<(), String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("unlock")
                .map_err(|e| e.to_string())
                .map(|_| ())
        })
    }

    /// Python returns a set, so the paths are collected rather than
    /// extracted as a sequence.
    fn filter_unversioned_files(&self, paths: &[&str]) -> Result<Vec<String>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method1("filter_unversioned_files", (paths.to_vec(),))
                .map_err(|e| map_py_err_to_err(py, e))?;
            collect_iter(py, result)
        })
    }

    fn walkdirs(&self, prefix: &str) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("walkdirs", (prefix,))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn iter_search_rules(
        &self,
        path_names: &[&str],
        pref_names: Option<&[&str]>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "iter_search_rules",
                    (path_names.to_vec(), pref_names.map(|p| p.to_vec())),
                )
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn archive(
        &self,
        format: &str,
        name: &str,
        root: &str,
        subdir: Option<&str>,
        force_mtime: Option<f64>,
        recurse_nested: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("force_mtime", force_mtime).unwrap();
            kwargs.set_item("recurse_nested", recurse_nested).unwrap();
            self.0
                .bind(py)
                .call_method("archive", (format, name, root, subdir), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn preview_transform(&self) -> Result<PyObject, Error> {
        call0(&self.0, "preview_transform")
    }
}

impl MutableTree for PyTree {
    fn case_sensitive(&self) -> Result<bool, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("case_sensitive")
                .and_then(|c| c.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn is_control_filename(&self, filename: &str) -> Result<bool, Error> {
        call1_extract(&self.0, "is_control_filename", (filename,))
    }

    fn add(&mut self, paths: &[&str], kinds: Option<&[&str]>) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("add", (paths.to_vec(), kinds.map(|k| k.to_vec())))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn add_reference(&mut self, sub_tree: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("add_reference", (sub_tree.bind(py),))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn commit(
        &mut self,
        message: Option<&str>,
        revprops: Option<&PyObject>,
    ) -> Result<RevisionId, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            if let Some(revprops) = revprops {
                kwargs.set_item("revprops", revprops.bind(py)).unwrap();
            }
            self.0
                .bind(py)
                .call_method("commit", (message,), Some(&kwargs))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn has_changes(&self, from_tree: Option<&PyObject>) -> Result<bool, Error> {
        Python::attach(|py| {
            let args = (from_tree.map(|t| t.bind(py)),);
            self.0
                .bind(py)
                .call_method1("has_changes", args)
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn check_changed_or_out_of_date(
        &self,
        strict: Option<bool>,
        opt_name: &str,
        more_error: &str,
        more_warning: &str,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "check_changed_or_out_of_date",
                    (strict, opt_name, more_error, more_warning),
                )
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn last_revision(&self) -> Result<Option<RevisionId>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("last_revision")
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn lock_tree_write(&mut self) -> Result<(), String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("lock_tree_write")
                .map_err(|e| e.to_string())
                .map(|_| ())
        })
    }

    fn lock_write(&mut self) -> Result<PyObject, Error> {
        call0(&self.0, "lock_write")
    }

    fn mkdir(&mut self, path: &str) -> Result<Option<FileId>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("mkdir", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn put_file_bytes_non_atomic(&mut self, path: &str, bytes: &[u8]) -> Result<(), Error> {
        Python::attach(|py| {
            let data = PyBytes::new(py, bytes);
            self.0
                .bind(py)
                .call_method1("put_file_bytes_non_atomic", (path, data))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn set_parent_ids(
        &mut self,
        revision_ids: &[RevisionId],
        allow_leftmost_as_ghost: bool,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "set_parent_ids",
                    (revision_ids.to_vec(), allow_leftmost_as_ghost),
                )
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn set_parent_trees(
        &mut self,
        parents_list: &[(RevisionId, PyObject)],
        allow_leftmost_as_ghost: bool,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            let list = PyList::empty(py);
            for (revid, tree) in parents_list {
                let pair = PyTuple::new(
                    py,
                    [
                        revid.into_pyobject(py).unwrap().into_any(),
                        tree.bind(py).clone(),
                    ],
                )
                .unwrap();
                list.append(pair).unwrap();
            }
            self.0
                .bind(py)
                .call_method1("set_parent_trees", (list, allow_leftmost_as_ghost))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn smart_add(
        &mut self,
        file_list: &[&str],
        recurse: bool,
        action: Option<&PyObject>,
        save: bool,
    ) -> Result<(Vec<String>, IgnoredFiles), Error> {
        Python::attach(|py| {
            let action_obj = action.map(|a| a.bind(py));
            self.0
                .bind(py)
                .call_method1("smart_add", (file_list.to_vec(), recurse, action_obj, save))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn rename_one(&mut self, from_rel: &str, to_rel: &str, after: bool) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("rename_one", (from_rel, to_rel, after))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn copy_one(&mut self, from_rel: &str, to_rel: &str) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("copy_one", (from_rel, to_rel))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn transform(&self) -> Result<PyObject, Error> {
        call0(&self.0, "transform")
    }
}

impl RevisionTree for PyTree {
    fn get_revision_id(&self) -> Result<RevisionId, Error> {
        call1_extract(&self.0, "get_revision_id", ())
    }

    fn get_file_revision(&self, path: &str) -> Result<RevisionId, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_file_revision", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn is_locked(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "is_locked")
    }
}

impl WorkingTree for PyTree {
    fn supports_merge_modified(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "supports_merge_modified")
    }

    fn requires_rich_root(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "requires_rich_root")
    }

    fn views(&self) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("views")
                .map(|v| v.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn supports_views(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "supports_views")
    }

    fn supports_setting_file_ids(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "supports_setting_file_ids")
    }

    fn branch(&self) -> Result<crate::controldir::BranchRef, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("branch")
                .map(|b| {
                    Box::new(crate::pybranch::PyBranch::new(b.unbind()))
                        as crate::controldir::BranchRef
                })
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn controldir(&self) -> Result<Box<dyn crate::controldir::ControlDir>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("controldir")
                .map(|d| {
                    Box::new(crate::pycontroldir::PyControlDir::new(d.unbind()))
                        as Box<dyn crate::controldir::ControlDir>
                })
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn user_transport(&self) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("user_transport")
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn control_transport(&self) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("control_transport")
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_config_stack(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_config_stack")
    }

    fn basedir(&self) -> Result<std::path::PathBuf, Error> {
        getattr_extract(&self.0, "basedir")
    }

    fn abspath(&self, path: &str) -> Result<std::path::PathBuf, Error> {
        call1_extract(&self.0, "abspath", (path,))
    }

    fn relpath(&self, path: &str) -> Result<String, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("relpath", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn safe_relpath_files(
        &self,
        file_list: &[&str],
        canonicalize: bool,
        apply_view: bool,
    ) -> Result<Vec<String>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1(
                    "safe_relpath_files",
                    (file_list.to_vec(), canonicalize, apply_view),
                )
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn basis_tree(&self) -> Result<PyObject, Error> {
        call0(&self.0, "basis_tree")
    }

    fn last_revision(&self) -> Result<RevisionId, Error> {
        call1_extract(&self.0, "last_revision", ())
    }

    fn break_lock(&mut self) -> Result<(), Error> {
        call0(&self.0, "break_lock").map(|_| ())
    }

    fn clone(
        &self,
        to_controldir: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("clone", (to_controldir.bind(py), revision_id))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn copy_content_into(
        &self,
        tree: &PyObject,
        revision_id: Option<&RevisionId>,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("copy_content_into", (tree.bind(py), revision_id))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn add_parent_tree_id(
        &mut self,
        revision_id: &RevisionId,
        allow_leftmost_as_ghost: bool,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("add_parent_tree_id", (revision_id, allow_leftmost_as_ghost))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn add_parent_tree(
        &mut self,
        parent_tuple: (RevisionId, PyObject),
        allow_leftmost_as_ghost: bool,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            let (revid, tree) = parent_tuple;
            let pair = PyTuple::new(
                py,
                [
                    revid.into_pyobject(py).unwrap().into_any(),
                    tree.bind(py).clone(),
                ],
            )
            .unwrap();
            self.0
                .bind(py)
                .call_method1("add_parent_tree", (pair, allow_leftmost_as_ghost))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn add_pending_merge(&mut self, revision_ids: &[RevisionId]) -> Result<(), Error> {
        Python::attach(|py| {
            let args = PyTuple::new(
                py,
                revision_ids.iter().map(|r| r.into_pyobject(py).unwrap()),
            )
            .unwrap();
            self.0
                .bind(py)
                .call_method1("add_pending_merge", args)
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn set_pending_merges(&mut self, rev_list: &[RevisionId]) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_pending_merges", (rev_list.to_vec(),))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn set_merge_modified(&mut self, modified_hashes: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_merge_modified", (modified_hashes.bind(py),))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn merge_modified(&self) -> Result<PyObject, Error> {
        call0(&self.0, "merge_modified")
    }

    fn merge_from_branch(
        &mut self,
        branch: &PyObject,
        to_revision: Option<&RevisionId>,
        from_revision: Option<&RevisionId>,
        merge_type: Option<&PyObject>,
        force: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("to_revision", to_revision).unwrap();
            kwargs.set_item("from_revision", from_revision).unwrap();
            kwargs
                .set_item("merge_type", merge_type.map(|m| m.bind(py)))
                .unwrap();
            kwargs.set_item("force", force).unwrap();
            self.0
                .bind(py)
                .call_method("merge_from_branch", (branch.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn subsume(&mut self, other_tree: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("subsume", (other_tree.bind(py),))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn extract(&mut self, path: &str, format: Option<&PyObject>) -> Result<PyObject, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("extract", (path, format.map(|f| f.bind(py))))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn flush(&mut self) -> Result<(), Error> {
        call0(&self.0, "flush").map(|_| ())
    }

    fn move_files(
        &mut self,
        from_paths: &[&str],
        to_dir: Option<&str>,
        after: bool,
    ) -> Result<Vec<(String, String)>, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("move", (from_paths.to_vec(), to_dir, after))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn unversion(&mut self, paths: &[&str]) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("unversion", (paths.to_vec(),))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn pull(
        &mut self,
        source: &PyObject,
        overwrite: bool,
        stop_revision: Option<&RevisionId>,
        change_reporter: Option<&PyObject>,
        local: bool,
        show_base: bool,
        tag_selector: Option<&PyObject>,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("overwrite", overwrite).unwrap();
            kwargs.set_item("stop_revision", stop_revision).unwrap();
            kwargs
                .set_item("change_reporter", change_reporter.map(|c| c.bind(py)))
                .unwrap();
            kwargs.set_item("local", local).unwrap();
            kwargs.set_item("show_base", show_base).unwrap();
            kwargs
                .set_item("tag_selector", tag_selector.map(|t| t.bind(py)))
                .unwrap();
            self.0
                .bind(py)
                .call_method("pull", (source.bind(py),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn ignored_files(&self) -> Result<Vec<(String, String)>, Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method0("ignored_files")
                .map_err(|e| map_py_err_to_err(py, e))?;
            collect_iter(py, result)
        })
    }

    fn is_locked(&self) -> Result<bool, Error> {
        call0_bool(&self.0, "is_locked")
    }

    fn get_physical_lock_status(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_physical_lock_status")
    }

    fn set_last_revision(&mut self, new_revision: &RevisionId) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_last_revision", (new_revision,))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn remove(
        &mut self,
        files: &[&str],
        verbose: bool,
        keep_files: bool,
        force: bool,
    ) -> Result<(), Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("verbose", verbose).unwrap();
            kwargs.set_item("keep_files", keep_files).unwrap();
            kwargs.set_item("force", force).unwrap();
            self.0
                .bind(py)
                .call_method("remove", (files.to_vec(),), Some(&kwargs))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn revert(
        &mut self,
        filenames: Option<&[&str]>,
        old_tree: Option<&PyObject>,
        backups: bool,
        report_changes: bool,
    ) -> Result<PyObject, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs
                .set_item("old_tree", old_tree.map(|t| t.bind(py)))
                .unwrap();
            kwargs.set_item("backups", backups).unwrap();
            kwargs.set_item("report_changes", report_changes).unwrap();
            self.0
                .bind(py)
                .call_method("revert", (filenames.map(|f| f.to_vec()),), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn store_uncommitted(&mut self) -> Result<(), Error> {
        call0(&self.0, "store_uncommitted").map(|_| ())
    }

    fn restore_uncommitted(&mut self) -> Result<(), Error> {
        call0(&self.0, "restore_uncommitted").map(|_| ())
    }

    fn update(
        &mut self,
        change_reporter: Option<&PyObject>,
        revision: Option<&RevisionId>,
        old_tip: Option<&RevisionId>,
        show_base: bool,
    ) -> Result<i64, Error> {
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs
                .set_item("change_reporter", change_reporter.map(|c| c.bind(py)))
                .unwrap();
            kwargs.set_item("revision", revision).unwrap();
            kwargs.set_item("old_tip", old_tip).unwrap();
            kwargs.set_item("show_base", show_base).unwrap();
            self.0
                .bind(py)
                .call_method("update", (), Some(&kwargs))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn set_conflicts(&mut self, conflicts: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_conflicts", (conflicts.bind(py),))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn add_conflicts(&mut self, conflicts: &PyObject) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("add_conflicts", (conflicts.bind(py),))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn auto_resolve(&mut self) -> Result<(PyObject, PyObject), Error> {
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method0("auto_resolve")
                .map_err(|e| map_py_err_to_err(py, e))?;
            result.extract().map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn check_state(&self) -> Result<(), Error> {
        call0(&self.0, "check_state").map(|_| ())
    }

    fn reset_state(&mut self, revision_ids: Option<&[RevisionId]>) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("reset_state", (revision_ids.map(|r| r.to_vec()),))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_shelf_manager(&self) -> Result<PyObject, Error> {
        call0(&self.0, "get_shelf_manager")
    }

    fn get_canonical_path(&self, path: &str) -> Result<String, Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("get_canonical_path", (path,))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_canonical_paths(&self, paths: &[&str]) -> Result<Vec<String>, Error> {
        // Concrete implementations return a generator, so iterate rather than
        // extracting directly into a Vec.
        Python::attach(|py| {
            let result = self
                .0
                .bind(py)
                .call_method1("get_canonical_paths", (paths.to_vec(),))
                .map_err(|e| map_py_err_to_err(py, e))?;
            collect_iter(py, result)
        })
    }

    fn reference_parent(
        &self,
        path: &str,
        branch: Option<&PyObject>,
        possible_transports: Option<&[PyObject]>,
    ) -> Result<PyObject, Error> {
        // git trees define reference_parent(self, path, possible_transports=None)
        // with no `branch` parameter, so pass optional arguments as keywords
        // only when supplied rather than positionally.
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            if let Some(branch) = branch {
                kwargs.set_item("branch", branch.bind(py)).unwrap();
            }
            if let Some(transports) = possible_transports {
                kwargs
                    .set_item(
                        "possible_transports",
                        transports.iter().map(|o| o.bind(py)).collect::<Vec<_>>(),
                    )
                    .unwrap();
            }
            self.0
                .bind(py)
                .call_method("reference_parent", (path,), Some(&kwargs))
                .map(|r| r.unbind())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn get_reference_info(
        &self,
        path: &str,
        branch: Option<&PyObject>,
    ) -> Result<Option<String>, Error> {
        // git's get_reference_info(self, path) takes no `branch`, so only pass
        // it as a keyword when supplied.
        Python::attach(|py| {
            let kwargs = pyo3::types::PyDict::new(py);
            if let Some(branch) = branch {
                kwargs.set_item("branch", branch.bind(py)).unwrap();
            }
            self.0
                .bind(py)
                .call_method("get_reference_info", (path,), Some(&kwargs))
                .and_then(|r| r.extract())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }

    fn set_reference_info(&mut self, tree_path: &str, branch_location: &str) -> Result<(), Error> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method1("set_reference_info", (tree_path, branch_location))
                .map(|_| ())
                .map_err(|e| map_py_err_to_err(py, e))
        })
    }
}
