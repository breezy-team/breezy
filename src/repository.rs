use crate::controldir::ControlDir;
use crate::delta::TreeDelta;
use crate::graph::Graph;
use crate::revisionid::RevisionId;
use crate::tree::RevisionTree;
use pyo3::exceptions::PyStopIteration;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[derive(Clone)]
pub struct RepositoryFormat(PyObject);

impl RepositoryFormat {
    pub fn supports_chks(&self) -> bool {
        Python::with_gil(|py| {
            self.0
                .getattr(py, "supports_chks")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }
}

#[derive(Clone)]
pub struct Repository(PyObject);

#[derive(Debug)]
pub struct Revision {
    pub revision_id: RevisionId,
    pub parent_ids: Vec<RevisionId>,
    pub message: String,
    pub committer: String,
    pub timestamp: f64,
    pub timezone: i32,
}

impl ToPyObject for Revision {
    fn to_object(&self, py: Python) -> PyObject {
        let kwargs = PyDict::new(py);
        kwargs.set_item("message", self.message.clone()).unwrap();
        kwargs
            .set_item("committer", self.committer.clone())
            .unwrap();
        kwargs.set_item("timestamp", self.timestamp).unwrap();
        kwargs.set_item("timezone", self.timezone).unwrap();
        kwargs.set_item("revision_id", &self.revision_id).unwrap();
        kwargs
            .set_item("parent_ids", self.parent_ids.iter().collect::<Vec<_>>())
            .unwrap();
        py.import("breezy.revision")
            .unwrap()
            .getattr("Revision")
            .unwrap()
            .call((), Some(kwargs))
            .unwrap()
            .to_object(py)
    }
}

impl FromPyObject<'_> for Revision {
    fn extract(ob: &'_ PyAny) -> PyResult<Self> {
        Ok(Revision {
            revision_id: ob.getattr("revision_id")?.extract()?,
            parent_ids: ob.getattr("parent_ids")?.extract()?,
            message: ob.getattr("message")?.extract()?,
            committer: ob.getattr("committer")?.extract()?,
            timestamp: ob.getattr("timestamp")?.extract()?,
            timezone: ob.getattr("timezone")?.extract()?,
        })
    }
}

pub struct RevisionIterator(PyObject);

impl Iterator for RevisionIterator {
    type Item = (RevisionId, Option<Revision>);

    fn next(&mut self) -> Option<Self::Item> {
        Python::with_gil(|py| match self.0.call_method0(py, "__next__") {
            Err(e) if e.is_instance_of::<PyStopIteration>(py) => None,
            Ok(o) => Some(o.extract(py).unwrap()),
            Err(e) => panic!("Error in revision iterator: {}", e),
        })
    }
}

pub struct DeltaIterator(PyObject);

impl Iterator for DeltaIterator {
    type Item = TreeDelta;

    fn next(&mut self) -> Option<Self::Item> {
        Python::with_gil(|py| match self.0.call_method0(py, "__next__") {
            Err(e) if e.is_instance_of::<PyStopIteration>(py) => None,
            Ok(o) => Some(o.extract(py).unwrap()),
            Err(e) => panic!("Error in delta iterator: {}", e),
        })
    }
}

impl ToPyObject for Repository {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl Repository {
    pub fn new(obj: PyObject) -> Self {
        Repository(obj)
    }

    pub fn fetch(
        &self,
        other_repository: &Repository,
        stop_revision: Option<&RevisionId>,
    ) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method1(
                py,
                "fetch",
                (
                    other_repository.to_object(py),
                    stop_revision.map(|r| r.to_object(py)),
                ),
            )?;
            Ok(())
        })
    }

    pub fn revision_tree(&self, revid: &RevisionId) -> PyResult<RevisionTree> {
        Python::with_gil(|py| {
            let o = self.0.call_method1(py, "revision_tree", (revid.clone(),))?;
            Ok(RevisionTree(o))
        })
    }

    pub fn get_graph(&self) -> Graph {
        Python::with_gil(|py| Graph::from(self.0.call_method0(py, "get_graph").unwrap()))
    }

    pub fn controldir(&self) -> ControlDir {
        Python::with_gil(|py| ControlDir::new(self.0.getattr(py, "controldir").unwrap()))
    }

    pub fn format(&self) -> RepositoryFormat {
        Python::with_gil(|py| RepositoryFormat(self.0.getattr(py, "_format").unwrap()))
    }

    pub fn iter_revisions(
        &self,
        revision_ids: Vec<RevisionId>,
    ) -> impl Iterator<Item = (RevisionId, Option<Revision>)> {
        Python::with_gil(|py| {
            let o = self
                .0
                .call_method1(py, "iter_revisions", (revision_ids,))
                .unwrap();
            RevisionIterator(o)
        })
    }

    pub fn get_revision_deltas(
        &self,
        revs: &[Revision],
        specific_files: Option<&[&std::path::Path]>,
    ) -> impl Iterator<Item = TreeDelta> {
        Python::with_gil(|py| {
            let revs = revs.iter().map(|r| r.to_object(py)).collect::<Vec<_>>();
            let specific_files = specific_files
                .map(|files| files.iter().map(|f| f.to_path_buf()).collect::<Vec<_>>());
            let o = self
                .0
                .call_method1(py, "get_revision_deltas", (revs, specific_files))
                .unwrap();
            DeltaIterator(o)
        })
    }

    pub fn get_revision(&self, revision_id: &RevisionId) -> PyResult<Revision> {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "get_revision", (revision_id.clone(),))?
                .extract(py)
        })
    }
}
