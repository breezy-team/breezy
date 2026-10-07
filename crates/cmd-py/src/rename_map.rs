//! Python bindings for `breezy::rename_map`, exposed as `breezy._cmd_rs.rename_map`.
//!
//! `RenameMap` here is a base class: `breezy.rename_map.RenameMap` subclasses
//! it to add the tree walking, progress reporting and inventory delta
//! construction, which call back into Python tree objects anyway.
//!
//! Files are identified by tags, which may be any hashable Python object (a
//! bzr file id, a path, whatever the tree implementation uses). Tags are
//! interned to dense indices before reaching the generic core, so hashing
//! and equality follow Python semantics while the core never sees a Python
//! object.

use breezy::rename_map;
use pyo3::exceptions::PySystemError;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedBytes;
use pyo3::types::{PyDict, PyList, PyModule, PySet};
use std::collections::{HashMap, HashSet};

/// Two-way mapping between tag objects and the indices the core works on.
struct Interner {
    index: Py<PyDict>,
    objects: Vec<Py<PyAny>>,
}

impl Interner {
    fn new(py: Python<'_>) -> Self {
        Interner {
            index: PyDict::new(py).unbind(),
            objects: Vec::new(),
        }
    }

    fn intern(&mut self, obj: &Bound<'_, PyAny>) -> PyResult<usize> {
        let index = self.index.bind(obj.py());
        if let Some(i) = index.get_item(obj)? {
            return i.extract();
        }
        let i = self.objects.len();
        index.set_item(obj, i)?;
        self.objects.push(obj.clone().unbind());
        Ok(i)
    }

    fn intern_all(&mut self, objs: &Bound<'_, PyAny>) -> PyResult<HashSet<usize>> {
        objs.try_iter()?.map(|o| self.intern(&o?)).collect()
    }

    fn get<'py>(&self, py: Python<'py>, i: usize) -> Bound<'py, PyAny> {
        self.objects[i].bind(py).clone()
    }

    fn get_all<'py>(
        &self,
        py: Python<'py>,
        indices: impl IntoIterator<Item = usize>,
    ) -> PyResult<Bound<'py, PySet>> {
        PySet::new(py, indices.into_iter().map(|i| self.get(py, i)))
    }

    /// Sort interned tags descending by Python ordering, as `sorted(tags,
    /// reverse=True)` would.
    fn sort_descending(&self, py: Python<'_>, tags: &mut [usize]) -> PyResult<()> {
        let list = PyList::new(py, tags.iter().map(|&i| self.get(py, i)))?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("reverse", true)?;
        list.call_method("sort", (), Some(&kwargs))?;
        let index = self.index.bind(py);
        for (slot, obj) in tags.iter_mut().zip(list.iter()) {
            *slot = index
                .get_item(&obj)?
                .ok_or_else(|| PySystemError::new_err("sorted tag is no longer interned"))?
                .extract()?;
        }
        Ok(())
    }

    fn to_path_map<'py>(
        &self,
        py: Python<'py>,
        map: HashMap<String, usize>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (path, i) in map {
            dict.set_item(path, self.get(py, i))?;
        }
        Ok(dict)
    }
}

/// Hash one edge: a line and the line following it, or `None` after the last
/// line of a file.
#[pyfunction]
#[pyo3(signature = (line, next = None))]
fn edge_hash(line: &[u8], next: Option<&[u8]>) -> u32 {
    rename_map::edge_hash(line, next)
}

/// Determine a mapping of renames.
#[pyclass(subclass, module = "breezy._cmd_rs.rename_map")]
struct RenameMap {
    #[pyo3(get)]
    tree: Py<PyAny>,
    tags: Interner,
    inner: rename_map::RenameMap<usize>,
}

#[pymethods]
impl RenameMap {
    #[new]
    fn new(py: Python<'_>, tree: Py<PyAny>) -> Self {
        RenameMap {
            tree,
            tags: Interner::new(py),
            inner: rename_map::RenameMap::new(),
        }
    }

    /// Record that every edge of `lines` occurs in the file tagged `tag`.
    ///
    /// A tag is any hashable object that uniquely identifies a file, such as
    /// a file id.
    fn add_edge_hashes(
        &mut self,
        lines: Vec<PyBackedBytes>,
        tag: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let tag = self.tags.intern(tag)?;
        self.inner.add_edge_hashes(&lines, tag);
        Ok(())
    }

    /// The set of tags recorded for an edge hash, or None.
    fn edge_hash_tags<'py>(
        &self,
        py: Python<'py>,
        hash: u32,
    ) -> PyResult<Option<Bound<'py, PySet>>> {
        self.inner
            .edge_hash_tags(hash)
            .map(|tags| self.tags.get_all(py, tags.iter().copied()))
            .transpose()
    }

    /// Count the number of hash hits for each tag, for the given lines.
    ///
    /// Hits are weighted by the number of tags a hash is associated with, so
    /// common edges count for little. Returns a dict of {tag: count}.
    fn hitcounts<'py>(
        &self,
        py: Python<'py>,
        lines: Vec<PyBackedBytes>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (tag, count) in self.inner.hitcounts(&lines) {
            dict.set_item(self.tags.get(py, tag), count)?;
        }
        Ok(dict)
    }

    /// Turn a list of (count, path, tag) hits into a path-to-tag map, taking
    /// the strongest hits first and using each path and tag once.
    #[staticmethod]
    fn _match_hits<'py>(
        py: Python<'py>,
        hit_list: Vec<(f64, String, Bound<'py, PyAny>)>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let mut tags = Interner::new(py);
        let hits = hit_list
            .into_iter()
            .map(|(count, path, tag)| Ok((count, path, tags.intern(&tag)?)))
            .collect::<PyResult<Vec<_>>>()?;
        let matches = rename_map::match_hits(hits, |t| tags.sort_descending(py, t))?;
        tags.to_path_map(py, matches)
    }

    /// Return a dict of all file parents that must be versioned.
    ///
    /// The keys are the required parents and the values are sets of the tags
    /// of their matched children.
    fn get_required_parents<'py>(
        &mut self,
        py: Python<'py>,
        matches: HashMap<String, Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let matches = matches
            .into_iter()
            .map(|(path, tag)| Ok((path, self.tags.intern(&tag)?)))
            .collect::<PyResult<HashMap<_, _>>>()?;
        let tree = self.tree.bind(py);
        let required = rename_map::required_parents(&matches, |path| {
            tree.call_method1("is_versioned", (path,))?.is_truthy()
        })?;
        let dict = PyDict::new(py);
        for (path, children) in required {
            dict.set_item(path, self.tags.get_all(py, children)?)?;
        }
        Ok(dict)
    }

    /// Map parent directories to tags by the similarity of their children.
    ///
    /// `required_parents` maps paths to sets of tags; `missing_parents` maps
    /// tags to sets of tags.
    fn match_parents<'py>(
        &mut self,
        py: Python<'py>,
        required_parents: &Bound<'py, PyDict>,
        missing_parents: &Bound<'py, PyDict>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let required_parents = required_parents
            .iter()
            .map(|(path, children)| Ok((path.extract()?, self.tags.intern_all(&children)?)))
            .collect::<PyResult<HashMap<String, _>>>()?;
        let missing_parents = missing_parents
            .iter()
            .map(|(tag, children)| Ok((self.tags.intern(&tag)?, self.tags.intern_all(&children)?)))
            .collect::<PyResult<HashMap<_, _>>>()?;
        let matches = rename_map::match_parents(&required_parents, &missing_parents, |t| {
            self.tags.sort_descending(py, t)
        })?;
        self.tags.to_path_map(py, matches)
    }
}

/// Register the `rename_map` submodule on `parent`.
pub fn rename_map(parent: &Bound<PyModule>) -> PyResult<()> {
    parent.add_class::<RenameMap>()?;
    parent.add_function(wrap_pyfunction!(edge_hash, parent)?)?;
    Ok(())
}
