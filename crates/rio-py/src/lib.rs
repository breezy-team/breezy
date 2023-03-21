use pyo3::prelude::*;

use pyo3::wrap_pyfunction;

use pyo3::types::{PyDict,PyType,PyBytes,PyList,PyIterator,PyString};
use pyo3::exceptions::{PyTypeError, PyValueError};

#[pyfunction]
fn valid_tag(tag: &str) -> bool {
    return bazaar_rio::rio::valid_tag(tag);
}

#[pyclass]
#[derive(Clone)]
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
            for (tag, value) in kwargs {
                obj.add(&tag.to_string(), value)?;
            }
        }

        Ok(obj)
    }

    fn __eq__(&self, other: &Stanza) -> PyResult<bool> {
        Ok(self.stanza.eq(&other.stanza))
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
    fn from_pairs(cls: &PyType, pairs: Vec<(String, &PyAny)>) -> PyResult<Stanza> {
        let mut ret = Stanza::new(None)?;
        for (tag, value) in pairs {
            ret.add(tag.as_str(), value)?;
        }
        Ok(ret)
    }

    // TODO: This is a hack to get around the fact that PyO3 doesn't support returning an iterator.
    fn iter_pairs(&self, py: Python) -> PyResult<Py<PyIterator>> {
        let mut ret = PyList::empty(py);
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
}

#[pymodule]
fn _rio_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(valid_tag))?;

    m.add_class::<Stanza>()?;
    Ok(())
}
