use bazaar::versionedfile::{ContentFactory, Key};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

#[pyclass(subclass, unsendable)]
struct AbstractContentFactory(Box<dyn ContentFactory>);

pyo3::import_exception!(breezy.bzr.versionedfile, UnavailableRepresentation);

#[pymethods]
impl AbstractContentFactory {
    #[getter]
    fn sha1(&self, py: Python) -> Option<PyObject> {
        self.0.sha1().map(|x| PyBytes::new(py, &x).into())
    }

    #[getter]
    fn key(&self) -> Key {
        self.0.key()
    }

    #[getter]
    fn parents(&self) -> Option<Vec<Key>> {
        self.0.parents()
    }

    #[getter]
    fn storage_kind(&self) -> String {
        self.0.storage_kind()
    }

    #[getter]
    fn size(&self) -> Option<usize> {
        self.0.size()
    }

    fn get_bytes_as(&self, py: Python, storage_kind: &str) -> PyResult<PyObject> {
        match storage_kind {
            "fulltext" => Ok(PyBytes::new(py, self.0.to_fulltext().as_ref()).into()),
            "lines" => Ok(self
                .0
                .to_lines()
                .map(|b| PyBytes::new(py, b.as_ref()))
                .collect::<Vec<_>>()
                .to_object(py)),
            "chunked" => Ok(self
                .0
                .to_chunks()
                .map(|b| PyBytes::new(py, b.as_ref()))
                .collect::<Vec<_>>()
                .to_object(py)),
            _ => Err(UnavailableRepresentation::new_err(format!(
                "Unsupported storage kind: {}",
                storage_kind
            ))),
        }
    }

    fn add_key_prefix(&mut self, py: Python, prefix: PyObject) -> PyResult<()> {
        match prefix.as_ref(py).get_type().name().unwrap() {
            "tuple" | "StaticTuple" => {}
            _ => {
                return Err(pyo3::exceptions::PyTypeError::new_err("Expected tuple"));
            }
        }

        let mut lprefix = Vec::new();

        for i in 0..prefix.as_ref(py).len()? {
            lprefix.push(prefix.as_ref(py).get_item(i)?.extract::<Vec<u8>>()?);
        }

        let prefix = lprefix.iter().map(|x| x.as_slice()).collect::<Vec<_>>();

        self.0.add_key_prefix(prefix.as_slice());
        Ok(())
    }
}

#[pyclass(extends=AbstractContentFactory)]
struct FulltextContentFactory;

#[pymethods]
impl FulltextContentFactory {
    #[new]
    fn new(
        key: Key,
        parents: Option<Vec<Key>>,
        sha1: Option<Vec<u8>>,
        text: Vec<u8>,
    ) -> PyResult<(Self, AbstractContentFactory)> {
        let of = bazaar::versionedfile::FulltextContentFactory::new(sha1, key, parents, text);

        Ok((FulltextContentFactory, AbstractContentFactory(Box::new(of))))
    }
}

#[pyclass(extends=AbstractContentFactory)]
struct ChunkedContentFactory;

#[pymethods]
impl ChunkedContentFactory {
    #[new]
    fn new(
        key: Key,
        parents: Option<Vec<Key>>,
        sha1: Option<Vec<u8>>,
        chunks: Vec<Vec<u8>>,
    ) -> PyResult<(Self, AbstractContentFactory)> {
        let of = bazaar::versionedfile::ChunkedContentFactory::new(sha1, key, parents, chunks);

        Ok((ChunkedContentFactory, AbstractContentFactory(Box::new(of))))
    }
}

#[pyfunction]
pub fn record_to_fulltext_bytes(py: Python, record: PyObject) -> PyResult<PyObject> {
    let record = record.extract::<bazaar::pyversionedfile::PyContentFactory>(py)?;

    let mut s = Vec::new();

    bazaar::versionedfile::record_to_fulltext_bytes(record, &mut s)?;

    Ok(PyBytes::new(py, &s).into())
}

#[pyclass(extends=AbstractContentFactory)]
struct AbsentContentFactory;

#[pymethods]
impl AbsentContentFactory {
    #[new]
    fn new(key: Key) -> PyResult<(Self, AbstractContentFactory)> {
        let of = bazaar::versionedfile::AbsentContentFactory::new(key);

        Ok((AbsentContentFactory, AbstractContentFactory(Box::new(of))))
    }
}

pub(crate) fn _versionedfile_rs(py: Python) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "versionedfile")?;
    m.add_class::<AbstractContentFactory>()?;
    m.add_class::<FulltextContentFactory>()?;
    m.add_class::<ChunkedContentFactory>()?;
    m.add_class::<AbsentContentFactory>()?;
    m.add_function(wrap_pyfunction!(record_to_fulltext_bytes, m)?)?;
    Ok(m)
}
