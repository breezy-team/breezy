use crate::controldir::ControlDir;
use crate::graph::Graph;
use crate::revisionid::RevisionId;
use crate::tree::RevisionTree;
use pyo3::prelude::*;

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

    pub fn get_revision(&self, revision_id: &RevisionId) -> PyResult<Revision> {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "get_revision", (revision_id.clone(),))?
                .extract(py)
        })
    }
}
