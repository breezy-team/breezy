use crate::versionedfile::{ContentFactory, Error, Key, Ordering, VersionId, VersionedFile};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::borrow::Cow;

pub struct PyContentFactory(PyObject);

impl ToPyObject for PyContentFactory {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl FromPyObject<'_> for PyContentFactory {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        Python::with_gil(|py| Ok(PyContentFactory(ob.to_object(py))))
    }
}

impl ContentFactory for PyContentFactory {
    fn size(&self) -> Option<usize> {
        Python::with_gil(|py| self.0.getattr(py, "size").unwrap().extract(py).unwrap())
    }

    fn key(&self) -> Key {
        Python::with_gil(|py| {
            let py_key = self.0.getattr(py, "key").unwrap();
            py_key.extract(py).unwrap()
        })
    }

    fn parents(&self) -> Option<Vec<Key>> {
        Python::with_gil(|py| {
            let py_parents = self.0.getattr(py, "parents").unwrap();
            py_parents.extract(py).unwrap()
        })
    }

    fn to_fulltext<'a, 'b>(&'a self) -> Cow<'b, [u8]>
    where
        'a: 'b,
    {
        Cow::Owned(Python::with_gil(|py| {
            let py_content = self
                .0
                .call_method1(py, "get_bytes_as", ("fulltext",))
                .unwrap();
            py_content.extract::<Vec<u8>>(py).unwrap()
        }))
    }

    fn to_lines<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>>>
    where
        'a: 'b,
    {
        let py_content = Python::with_gil(|py| {
            self.0
                .call_method1(py, "get_bytes_as", ("lines",))
                .unwrap()
                .extract::<Vec<Vec<u8>>>(py)
                .unwrap()
        });

        Box::new(py_content.into_iter().map(Cow::Owned))
    }

    fn to_chunks<'a, 'b>(&'a self) -> Box<dyn Iterator<Item = Cow<'b, [u8]>>>
    where
        'a: 'b,
    {
        let py_content = Python::with_gil(|py| {
            self.0
                .call_method1(py, "get_bytes_as", ("chunks",))
                .unwrap()
                .extract::<Vec<Vec<u8>>>(py)
                .unwrap()
        });

        Box::new(py_content.into_iter().map(Cow::Owned))
    }

    fn into_fulltext(self) -> Vec<u8> {
        self.to_fulltext().into_owned()
    }

    fn into_lines(self) -> Box<dyn Iterator<Item = Vec<u8>>> {
        let lines = Python::with_gil(|py| {
            let py_content = self.0.call_method1(py, "get_bytes", ("lines",)).unwrap();
            py_content.extract::<Vec<Vec<u8>>>(py).unwrap()
        });

        Box::new(lines.into_iter().map(|l| l.to_vec()))
    }

    fn into_chunks(self) -> Box<dyn Iterator<Item = Vec<u8>>> {
        let chunks = Python::with_gil(|py| {
            let py_content = self.0.call_method1(py, "get_bytes", ("chunks",)).unwrap();
            py_content.extract::<Vec<Vec<u8>>>(py).unwrap()
        });

        Box::new(chunks.into_iter().map(|c| c.to_vec()))
    }

    fn sha1(&self) -> Option<Vec<u8>> {
        Python::with_gil(|py| {
            let py_content = self.0.call_method0(py, "get_bytes").unwrap();
            py_content.extract(py).unwrap()
        })
    }

    fn storage_kind(&self) -> String {
        Python::with_gil(|py| {
            self.0
                .getattr(py, "storage_kind")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    fn map_key(&mut self, _f: &dyn Fn(Key) -> Key) {
        todo!();
    }
}

pub struct PyVersionedFile(PyObject);

pub struct PyRecordStreamIter(PyObject);

impl Iterator for PyRecordStreamIter {
    type Item = PyContentFactory;

    fn next(&mut self) -> Option<Self::Item> {
        Python::with_gil(|py| {
            let py_record_stream_iter = self.0.as_ref(py);
            let py_content_factory = py_record_stream_iter.call_method0("next").unwrap();
            let content_factory = PyContentFactory(py_content_factory.to_object(py));
            Some(content_factory)
        })
    }
}

impl VersionedFile<PyContentFactory, PyObject> for PyVersionedFile {
    fn check_not_reserved_id(version_id: &VersionId) -> bool {
        Python::with_gil(|py| {
            let m = py.import("breezy.bzr.versionedfile").unwrap();
            let c = m.getattr("VersionedFile").unwrap();
            c.call_method1("check_not_reserved_id", (version_id.to_object(py),))
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn has_version(&self, version_id: &VersionId) -> bool {
        Python::with_gil(|py| {
            let py_versioned_file = self.0.as_ref(py);
            py_versioned_file
                .call_method1("has_version", (version_id.to_object(py),))
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn get_format_signature(&self) -> String {
        Python::with_gil(|py| {
            self.0
                .call_method0(py, "get_format_signature")
                .unwrap()
                .extract(py)
                .unwrap()
        })
    }

    fn get_record_stream(
        &self,
        version_ids: &[&VersionId],
        ordering: Ordering,
        include_delta_closure: bool,
    ) -> Box<dyn Iterator<Item = PyContentFactory>> {
        Box::new(Python::with_gil(|py| {
            let py_versioned_file = self.0.as_ref(py);
            let version_ids = version_ids
                .iter()
                .map(|k| k.to_object(py))
                .collect::<Vec<_>>();
            let py_record_stream = py_versioned_file
                .call_method1(
                    "get_record_stream",
                    (version_ids, ordering, include_delta_closure),
                )
                .unwrap();
            Box::new(PyRecordStreamIter(py_record_stream.to_object(py)))
        }))
    }

    fn add_lines<'a>(
        &mut self,
        version_id: &VersionId,
        parent_texts: Option<std::collections::HashMap<VersionId, PyObject>>,
        lines: impl Iterator<Item = &'a [u8]>,
        nostore_sha: Option<bool>,
        random_id: bool,
    ) -> Result<(Vec<u8>, usize, PyObject), Error> {
        Python::with_gil(|py| {
            let py_versioned_file = self.0.as_ref(py);
            let py_lines = lines.map(|l| PyBytes::new(py, l)).collect::<Vec<_>>();
            let py_parent_texts = match parent_texts {
                Some(parent_texts) => {
                    let py_parent_texts = parent_texts
                        .into_iter()
                        .map(|(k, v)| (k.to_object(py), v.to_object(py)))
                        .collect::<Vec<_>>();
                    Some(py_parent_texts)
                }
                None => None,
            };
            let py_result = py_versioned_file.call_method1(
                "add_lines",
                (
                    version_id.to_object(py),
                    py_parent_texts,
                    py_lines,
                    nostore_sha,
                    random_id,
                ),
            )?;
            let py_result = py_result.extract::<(Vec<u8>, usize, PyObject)>()?;
            Ok(py_result)
        })
    }

    fn insert_record_stream(
        &mut self,
        stream: impl Iterator<Item = Box<dyn ContentFactory>>,
    ) -> Result<(), Error> {
        #[pyclass(unsendable)]
        struct PyContentFactory(Box<dyn ContentFactory>);

        #[pymethods]
        impl PyContentFactory {
            #[getter]
            fn sha1(&self, py: Python) -> PyObject {
                self.0.sha1().to_object(py)
            }

            #[getter]
            fn key(&self, py: Python) -> PyObject {
                self.0.key().to_object(py)
            }
        }

        Python::with_gil(|py| {
            let py_versioned_file = self.0.as_ref(py);
            let stream = stream.collect::<Vec<_>>();
            let py_stream = stream
                .into_iter()
                .map(|c| PyContentFactory(c))
                .collect::<Vec<_>>();
            py_versioned_file.call_method1("insert_record_stream", (py_stream,))?;
            Ok(())
        })
    }
}
