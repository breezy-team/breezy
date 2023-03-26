use pyo3::prelude::*;

use pyo3::wrap_pyfunction;

use pyo3::types::{PyDict,PyType,PyBytes,PyList,PyIterator,PyString};
use pyo3::exceptions::{PyTypeError, PyValueError};

use pyo3::class::basic::CompareOp;

use std::io::BufReader;

mod filelike;

use crate::filelike::PyFileLikeObject;

#[pyfunction]
fn valid_tag(tag: &str) -> bool {
    return bazaar_rio::rio::valid_tag(tag);
}

#[pyclass]
#[derive(Clone, PartialEq)]
struct Stanza {
    stanza: bazaar_rio::rio::Stanza,
}

#[pymethods]
impl Stanza {
    #[new]
    #[pyo3(signature = (**kwargs))]
    fn new(kwargs: Option<&PyDict>) -> PyResult<Self> {
        let mut obj = Stanza {
            stanza: bazaar_rio::rio::Stanza::new(),
        };

        if let Some(kwargs) = kwargs {
            let items = kwargs.items();
            items.sort()?;
            for item in items.iter() {
                let (key, value) = item.extract::<(String, &PyAny)>()?;
                obj.add(&key.to_string(), value)?;
            }
        }

        Ok(obj)
    }

    fn __richcmp__(&self, other: &PyAny, op: CompareOp) -> PyObject {
        match op {
            CompareOp::Eq => self.stanza.eq(&other.extract::<Stanza>().unwrap().stanza).into_py(other.py()),
            _ => other.py().NotImplemented()
        }
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("{:?}", self.stanza))
    }

    fn get(&self, tag: &str, py: Python) -> PyResult<Option<PyObject>> {
        if let Some(value) = self.stanza.get(tag) {
            match value {
                bazaar_rio::rio::StanzaValue::String(v) => Ok(Some(PyString::new(py, v).into_py(py))),
                bazaar_rio::rio::StanzaValue::Stanza(v) => Ok(Some(Stanza { stanza: *v.clone() }.into_py(py))),
            }
        } else {
            Ok(None)
        }
    }

    /// Returns true if the stanza contains the given tag.
    fn __contains__(&self, tag: &str) -> PyResult<bool> {
        Ok(self.stanza.contains(tag))
    }

    fn __len__(&self) -> PyResult<usize> {
        Ok(self.stanza.len())
    }

    fn to_bytes(&self, py: Python) -> PyResult<Py<PyBytes>> {
        let ret: &PyBytes = PyBytes::new(py, self.stanza.to_bytes().as_slice());
        Ok(ret.into())
    }

    fn to_string(&self, py: Python) -> PyResult<Py<PyBytes>> {
        self.to_bytes(py)
    }

    fn to_lines(&self, py: Python) -> PyResult<Py<PyList>> {
        let ret = PyList::empty(py);
        for line in self.stanza.to_lines() {
            ret.append(PyBytes::new(py, line.as_bytes()))?;
        }
        Ok(ret.into())
    }

    /// Add a tag and value to the stanza.
    fn add(&mut self, tag: &str, value: &PyAny) -> PyResult<()> {
        if !valid_tag(tag) {
            return Err(PyErr::new::<PyValueError, _>("Invalid tag"));
        }
        // If the type of value is PyString, then extract it as a String and add it to the stanza.
        // Otherwise, if the type of value is Stanza, then extract it as a Stanza and add it to the stanza.
        // Otherwise, return an error.
        if let Ok(val) = value.extract::<String>() {
            self.stanza.add(tag.to_string(), bazaar_rio::rio::StanzaValue::String(val));
        } else if let Ok(val) = value.extract::<Stanza>() {
            self.stanza.add(tag.to_string(), bazaar_rio::rio::StanzaValue::Stanza(Box::new(val.stanza)));
        } else {
            return Err(PyErr::new::<PyTypeError, _>("Invalid value"));
        }
        Ok(())
    }

    /// Create a stanza from a list of pairs.
    #[classmethod]
    fn from_pairs(_cls: &PyType, pairs: Vec<(String, &PyAny)>) -> PyResult<Stanza> {
        let mut ret = Stanza::new(None)?;
        for (tag, value) in pairs {
            ret.add(tag.as_str(), value)?;
        }
        Ok(ret)
    }

    // TODO: This is a hack to get around the fact that PyO3 doesn't support returning an iterator.
    fn iter_pairs(&self, py: Python) -> PyResult<Py<PyIterator>> {
        let ret = PyList::empty(py);
        for (tag, value) in self.stanza.iter_pairs() {
            match value {
                bazaar_rio::rio::StanzaValue::String(v) => ret.append((tag.to_string(), v.to_string()))?,
                bazaar_rio::rio::StanzaValue::Stanza(v) => {
                    let sub: Stanza = Stanza { stanza: *v.clone() };
                    ret.append((tag.to_string(), sub.into_py(py)))?;
                }
            }
        }
        Ok(PyIterator::from_object(py, ret)?.into())
    }

    fn as_dict(&self, py: Python) -> PyResult<Py<PyDict>> {
        let ret = PyDict::new(py);
        for (tag, value) in self.stanza.iter_pairs() {
            match value {
                bazaar_rio::rio::StanzaValue::String(v) => ret.set_item(tag, v.to_string())?,
                bazaar_rio::rio::StanzaValue::Stanza(v) => {
                    let sub: Stanza = Stanza { stanza: *v.clone() };
                    ret.set_item(tag, sub.into_py(py))?;
                }
            }
        }
        Ok(ret.into())
    }

    fn get_all(&self, tag: &str, py: Python) -> PyResult<Py<PyList>> {
        let ret = PyList::empty(py);
        for value in self.stanza.get_all(tag) {
            match value {
                bazaar_rio::rio::StanzaValue::String(v) => ret.append(v.to_string())?,
                bazaar_rio::rio::StanzaValue::Stanza(v) => {
                    let sub: Stanza = Stanza { stanza: *v.clone() };
                    ret.append(sub.into_py(py))?;
                }
            }
        }
        Ok(ret.into())
    }

    fn write(&self, file: PyObject) -> PyResult<()> {
        let mut writer = PyFileLikeObject::new(file);
        self.stanza.write(&mut writer)?;
        Ok(())
    }
}

#[pyclass]
struct RioWriter {
    file: PyFileLikeObject,
    writer: bazaar_rio::rio::RioWriter<'static, PyFileLikeObject>
}

#[pymethods]
impl RioWriter {
    #[new]
    fn new(file: PyObject) -> PyResult<RioWriter> {
        let file = PyFileLikeObject::new(file);
        let writer = bazaar_rio::rio::RioWriter::new(&mut file);
        Ok(RioWriter { writer, file })
    }

    fn write_stanza(&mut self, stanza: &Stanza) -> PyResult<()> {
        self.writer.write_stanza(&stanza.stanza)?;
        Ok(())
    }
}

#[pyfunction]
fn to_patch_lines(stanza: &Stanza) -> PyResult<Py<PyList>> {
    let py = Python::acquire_gil();
    let py = py.python();
    let ret = PyList::empty(py);
    for line in bazaar_rio::rio::to_patch_lines(&stanza.stanza, bazaar_rio::rio::MAX_RIO_WIDTH)? {
        ret.append(PyBytes::new(py, line.as_slice()))?;
    }
    Ok(ret.into())
}

#[pyfunction]
fn read_stanza(file: PyObject) -> PyResult<Option<Stanza>> {
    let reader = PyFileLikeObject::new(file);

    let mut reader = BufReader::new(reader);

    let stanza = bazaar_rio::rio::read_stanza(&mut reader)?;

    if stanza.is_none() {
        return Ok(None);
    } else {
        let stanza = stanza.unwrap();
        return Ok(Some(Stanza { stanza }));
    }
}

#[pyfunction]
fn read_stanzas(file: PyObject) -> PyResult<Py<PyList>> {
    let py = Python::acquire_gil();
    let py = py.python();
    let reader = PyFileLikeObject::new(file);
    let ret = PyList::empty(py);

    let mut reader = BufReader::new(reader);

    let stanzas = bazaar_rio::rio::read_stanzas(&mut reader)?;
    for stanza in stanzas {
        ret.append((Stanza { stanza }).into_py(py))?;
    }
    Ok(ret.into())
}

#[pyfunction]
fn read_patch_stanza(file: PyObject) -> PyResult<Option<Stanza>> {
    let reader = PyFileLikeObject::new(file);

    let mut reader = BufReader::new(reader);

    let stanza = bazaar_rio::rio::read_patch_stanza(&mut reader)?;

    if stanza.is_none() {
        return Ok(None);
    } else {
        let stanza = stanza.unwrap();
        return Ok(Some(Stanza { stanza }));
    }
}

#[pyclass]
struct RioReader {
    reader: bazaar_rio::rio::RioReader<BufReader<PyFileLikeObject>>,
}

#[pymethods]
impl RioReader {
    #[new]
    fn new(file: PyObject) -> PyResult<RioReader> {
        let reader = PyFileLikeObject::new(file);
        let reader = BufReader::new(reader);
        let reader = bazaar_rio::rio::RioReader::new(reader);

        Ok(RioReader { reader: reader })
    }

    fn __iter__(&mut self) -> PyResult<Py<PyIterator>> {
        let py = Python::acquire_gil();
        let py = py.python();
        let ret = PyList::empty(py);
        for stanza in self.reader {
            stanza?;
            ret.append((Stanza { stanza: stanza.unwrap().unwrap() }).into_py(py))?;
        }
        Ok(PyIterator::from_object(py, ret)?.into())
    }
}

#[pyfunction]
fn rio_iter(stanzas: Vec<Stanza>, header: Option<Vec<u8>>) -> PyResult<Py<PyIterator>> {
    let py = Python::acquire_gil();
    let py = py.python();
    let ret = PyList::empty(py);
    for line in bazaar_rio::rio::rio_iter(stanzas.into_iter().map(|ps| ps.stanza), header) {
        ret.append(line);
    }
    Ok(PyIterator::from_object(py, ret)?.into())
}

#[pymodule]
fn _rio_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(valid_tag))?;
    m.add_wrapped(wrap_pyfunction!(to_patch_lines))?;
    m.add_wrapped(wrap_pyfunction!(read_stanza))?;
    m.add_wrapped(wrap_pyfunction!(read_stanzas))?;
    m.add_wrapped(wrap_pyfunction!(read_patch_stanza))?;
    m.add_wrapped(wrap_pyfunction!(rio_iter))?;

    m.add_class::<Stanza>()?;
    m.add_class::<RioReader>()?;
    m.add_class::<RioWriter>()?;
    Ok(())
}
