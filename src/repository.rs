use crate::controldir::ControlDir;
use crate::delta::TreeDelta;
use crate::graph::Graph;
use crate::revisionid::RevisionId;
use crate::tree::RevisionTree;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

#[derive(Clone)]
pub struct RepositoryFormat(pub(crate) PyObject);

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
pub struct Repository(pub(crate) PyObject);

pub struct Revision {
    pub message: String,
    pub committer: String,
    pub timestamp: u64,
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
        py.import("breezy.revision")
            .unwrap()
            .getattr("Revision")
            .unwrap()
            .call((), Some(kwargs.into()))
            .unwrap()
            .to_object(py)
    }
}

impl FromPyObject<'_> for Revision {
    fn extract(ob: &'_ PyAny) -> PyResult<Self> {
        Ok(Revision {
            message: ob.getattr("message")?.extract()?,
            committer: ob.getattr("committer")?.extract()?,
            timestamp: ob.getattr("timestamp")?.extract()?,
            timezone: ob.getattr("timezone")?.extract()?,
        })
    }
}

pub struct RevisionIterator(PyObject);

impl Iterator for RevisionIterator {
    type Item = Revision;

    fn next(&mut self) -> Option<Self::Item> {
        Python::with_gil(|py| {
            let o = self.0.call_method0(py, "__next__").unwrap();
            if o.is_none(py) {
                None
            } else {
                Some(o.extract(py).unwrap())
            }
        })
    }
}

pub struct DeltaIterator(PyObject);

impl Iterator for DeltaIterator {
    type Item = Vec<TreeDelta>;

    fn next(&mut self) -> Option<Self::Item> {
        Python::with_gil(|py| {
            let o = self.0.call_method0(py, "__next__").unwrap();
            if o.is_none(py) {
                None
            } else {
                Some(o.extract(py).unwrap())
            }
        })
    }
}

impl Repository {
    pub fn revision_tree(&self, revid: &RevisionId) -> PyResult<RevisionTree> {
        Python::with_gil(|py| {
            let o = self.0.call_method1(py, "revision_tree", (revid.clone(),))?;
            Ok(RevisionTree(o))
        })
    }

    pub fn get_graph(&self) -> Graph {
        Python::with_gil(|py| Graph(self.0.call_method0(py, "get_graph").unwrap()))
    }

    pub fn controldir(&self) -> ControlDir {
        Python::with_gil(|py| ControlDir(self.0.getattr(py, "controldir").unwrap()))
    }

    pub fn format(&self) -> RepositoryFormat {
        Python::with_gil(|py| RepositoryFormat(self.0.getattr(py, "_format").unwrap()))
    }

    pub fn iter_revisions(&self, revision_ids: Vec<RevisionId>) -> impl Iterator<Item = Revision> {
        Python::with_gil(|py| {
            let o = self
                .0
                .call_method1(py, "iter_revisions", (revision_ids,))
                .unwrap();
            RevisionIterator(o)
        })
    }

    pub fn get_revision_deltas(&self, revs: &[Revision]) -> impl Iterator<Item = Vec<TreeDelta>> {
        Python::with_gil(|py| {
            let revs = revs.iter().map(|r| r.to_object(py)).collect::<Vec<_>>();
            let o = self
                .0
                .call_method1(py, "get_revision_deltas", (revs,))
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
