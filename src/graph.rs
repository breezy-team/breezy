use crate::revisionid::RevisionId;
use pyo3::exceptions::PyStopIteration;
use pyo3::import_exception;
use pyo3::prelude::*;

import_exception!(breezy.errors, RevisionNotPresent);

pub struct Graph(PyObject);

impl ToPyObject for Graph {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl FromPyObject<'_> for Graph {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        Ok(Graph(ob.to_object(ob.py())))
    }
}

impl From<PyObject> for Graph {
    fn from(ob: PyObject) -> Self {
        Graph(ob)
    }
}

struct RevIter(PyObject);

impl Iterator for RevIter {
    type Item = Result<RevisionId, Error>;

    fn next(&mut self) -> Option<Self::Item> {
        Python::with_gil(|py| match self.0.call_method0(py, "__next__") {
            Ok(item) => Some(Ok(RevisionId::from(item.extract::<Vec<u8>>(py).unwrap()))),
            Err(e) if e.is_instance_of::<PyStopIteration>(py) => None,
            Err(e) => Some(Err(e.into())),
        })
    }
}

#[derive(Debug)]
pub enum Error {
    RevisionNotPresent(RevisionId),
}

impl From<PyErr> for Error {
    fn from(e: PyErr) -> Self {
        Python::with_gil(|py| {
            if e.is_instance_of::<RevisionNotPresent>(py) {
                Error::RevisionNotPresent(RevisionId::from(
                    e.value(py)
                        .getattr("revision_id")
                        .unwrap()
                        .extract::<Vec<u8>>()
                        .unwrap(),
                ))
            } else {
                panic!("unexpected error: {:?}", e)
            }
        })
    }
}

impl Graph {
    pub fn is_ancestor(&self, rev1: &RevisionId, rev2: &RevisionId) -> bool {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "is_ancestor", (rev1.as_bytes(), rev2.as_bytes()))
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    pub fn iter_lefthand_ancestry(
        &self,
        revid: &RevisionId,
    ) -> impl Iterator<Item = Result<RevisionId, Error>> {
        Python::with_gil(|py| {
            let iter = self
                .0
                .call_method1(py, "iter_lefthand_ancestry", (revid.as_bytes(),))
                .unwrap();
            RevIter(iter)
        })
    }
}
