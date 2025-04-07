use pyo3::prelude::*;

use pyo3::wrap_pyfunction;

use pyo3::exceptions::{PyIOError, PyNotImplementedError, PyTypeError, PyValueError};
use pyo3::types::{PyBytes, PyDict, PyIterator, PyList, PyString, PyType};

use pyo3::class::basic::CompareOp;

use std::io::BufReader;

use pyo3_filelike::PyBinaryFile;

#[pyfunction]
fn valid_tag(tag: &str) -> bool {
    bazaar::rio::valid_tag(tag)
}

#[pyclass]
#[derive(Clone, PartialEq)]
struct Stanza {
    stanza: bazaar::rio::Stanza,
}

#[pymethods]
impl Stanza {
    #[new]
    #[pyo3(signature = (**kwargs))]
    fn new(kwargs: Option<&Bound<PyDict>>) -> PyResult<Self> {
        let mut obj = Stanza {
            stanza: bazaar::rio::Stanza::new(),
        };

        if let Some(kwargs) = kwargs {
            let items = kwargs.items();
            items.sort()?;
            for item in items.iter() {
                let (key, value) = item.extract::<(String, Bound<PyAny>)>()?;
                obj.add(&key.to_string(), &value)?;
            }
        }

        Ok(obj)
    }

    fn __richcmp__(&self, other: &Bound<PyAny>, op: CompareOp) -> PyResult<bool> {
        match op {
            CompareOp::Eq => {
                let other_stanza = other.extract::<Stanza>();
                if other_stanza.is_err() {
                    Ok(false)
                } else {
                    Ok(self.stanza.eq(&other_stanza.unwrap().stanza))
                }
            }
            _ => Err(PyErr::new::<PyNotImplementedError, _>("Not implemented")),
        }
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("{:?}", self.stanza))
    }

    fn get<'py>(&self, tag: &str, py: Python<'py>) -> PyResult<Option<Bound<'py, PyAny>>> {
        if let Some(value) = self.stanza.get(tag) {
            match value {
                bazaar::rio::StanzaValue::String(v) => Ok(Some(PyString::new(py, v).into_any())),
                bazaar::rio::StanzaValue::Stanza(v) => Ok(Some(
                    Bound::new(py, Stanza { stanza: *v.clone() })?.into_any(),
                )),
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

    fn to_bytes<'a>(&self, py: Python<'a>) -> PyResult<Bound<'a, PyBytes>> {
        let ret: Bound<PyBytes> = PyBytes::new(py, self.stanza.to_bytes().as_slice());
        Ok(ret)
    }

    fn to_string<'a>(&self, py: Python<'a>) -> PyResult<Bound<'a, PyBytes>> {
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
    fn add(&mut self, tag: &str, value: &Bound<PyAny>) -> PyResult<()> {
        if !valid_tag(tag) {
            return Err(PyErr::new::<PyValueError, _>("Invalid tag"));
        }
        // If the type of value is PyString, then extract it as a String and add it to the stanza.
        // Otherwise, if the type of value is Stanza, then extract it as a Stanza and add it to the stanza.
        // Otherwise, return an error.
        let ret = if let Ok(val) = value.extract::<String>() {
            self.stanza
                .add(tag.to_string(), bazaar::rio::StanzaValue::String(val))
        } else if let Ok(val) = value.extract::<Stanza>() {
            self.stanza.add(
                tag.to_string(),
                bazaar::rio::StanzaValue::Stanza(Box::new(val.stanza)),
            )
        } else {
            return Err(PyErr::new::<PyTypeError, _>(format!(
                "Invalid value: {}",
                value.repr()?
            )));
        };
        if let Err(e) = ret {
            if let bazaar::rio::Error::Io(e) = e {
                return Err(PyErr::new::<PyIOError, _>(format!("IO error: {}", e)));
            } else {
                return Err(PyErr::new::<PyValueError, _>(format!(
                    "Invalid value: {}",
                    value.repr()?
                )));
            }
        }
        Ok(())
    }

    /// Create a stanza from a list of pairs.
    #[classmethod]
    fn from_pairs(_cls: &Bound<PyType>, pairs: Vec<(String, Bound<PyAny>)>) -> PyResult<Stanza> {
        let mut ret = Stanza::new(None)?;
        for (tag, value) in pairs {
            ret.add(tag.as_str(), &value)?;
        }
        Ok(ret)
    }

    // TODO: This is a hack to get around the fact that PyO3 doesn't support returning an iterator.
    fn iter_pairs<'a>(&self, py: Python<'a>) -> PyResult<Bound<'a, PyIterator>> {
        let ret = PyList::empty(py);
        for (tag, value) in self.stanza.iter_pairs() {
            match value {
                bazaar::rio::StanzaValue::String(v) => {
                    ret.append((tag.to_string(), v.to_string()))?
                }
                bazaar::rio::StanzaValue::Stanza(v) => {
                    let sub: Stanza = Stanza { stanza: *v.clone() };
                    ret.append((tag.to_string(), sub))?;
                }
            }
        }
        PyIterator::from_object(&ret)
    }

    fn as_dict(&self, py: Python) -> PyResult<Py<PyDict>> {
        let ret = PyDict::new(py);
        for (tag, value) in self.stanza.iter_pairs() {
            match value {
                bazaar::rio::StanzaValue::String(v) => ret.set_item(tag, v.to_string())?,
                bazaar::rio::StanzaValue::Stanza(v) => {
                    let sub: Stanza = Stanza { stanza: *v.clone() };
                    ret.set_item(tag, sub)?;
                }
            }
        }
        Ok(ret.into())
    }

    fn get_all(&self, tag: &str, py: Python) -> PyResult<Py<PyList>> {
        let ret = PyList::empty(py);
        for value in self.stanza.get_all(tag) {
            match value {
                bazaar::rio::StanzaValue::String(v) => ret.append(v.to_string())?,
                bazaar::rio::StanzaValue::Stanza(v) => {
                    let sub: Stanza = Stanza { stanza: *v.clone() };
                    ret.append(sub.into_py(py))?;
                }
            }
        }
        Ok(ret.into())
    }

    fn write(&self, file: PyObject) -> PyResult<()> {
        let mut writer = PyBinaryFile::from(file);
        self.stanza.write(&mut writer)?;
        Ok(())
    }
}

#[pyclass]
struct RioWriter {
    writer: bazaar::rio::RioWriter<PyBinaryFile>,
}

#[pymethods]
impl RioWriter {
    #[new]
    fn new(file: PyObject) -> PyResult<RioWriter> {
        let fw = PyBinaryFile::from(file);
        let writer = bazaar::rio::RioWriter::new(fw);
        Ok(RioWriter { writer })
    }

    fn write_stanza(&mut self, stanza: &Stanza) -> PyResult<()> {
        self.writer.write_stanza(&stanza.stanza)?;
        Ok(())
    }
}

#[pyfunction]
fn read_stanza_file(file: PyObject) -> PyResult<Option<Stanza>> {
    let reader = PyBinaryFile::from(file);

    let mut reader = BufReader::new(reader);

    let stanza = bazaar::rio::read_stanza_file(&mut reader).map_err(|e| match e {
        bazaar::rio::Error::Io(e) => {
            PyErr::new::<PyIOError, _>(format!("Error reading stanza file: {}", e))
        }
        _ => PyErr::new::<PyValueError, _>("Error reading stanza file".to_string()),
    })?;

    if let Some(stanza) = stanza {
        Ok(Some(Stanza { stanza }))
    } else {
        Ok(None)
    }
}

#[pyfunction]
fn read_stanza(file: &Bound<PyAny>) -> PyResult<Option<Stanza>> {
    let mut py_iter = file.try_iter()?;
    let mut pyerr: Option<PyErr> = None;
    let line_iter = std::iter::from_fn(|| -> Option<Result<Vec<u8>, bazaar::rio::Error>> {
        let line = py_iter.next()?;
        if let Err(e) = line {
            pyerr = Some(e);
            Some(Err(bazaar::rio::Error::Other("Python error".to_string())))
        } else {
            let line = line.unwrap();
            let line = line.extract::<Vec<u8>>();
            if let Err(e) = line {
                pyerr = Some(e);
                Some(Err(bazaar::rio::Error::Other("invalid input".to_string())))
            } else {
                Some(Ok(line.unwrap()))
            }
        }
    });

    let stanza = bazaar::rio::read_stanza(line_iter).map_err(|e| {
        if let Some(e) = pyerr {
            return e;
        }
        match e {
            bazaar::rio::Error::Io(e) => {
                PyErr::new::<PyIOError, _>(format!("Error reading stanza: {}", e))
            }
            _ => PyErr::new::<PyValueError, _>("Error reading stanza".to_string()),
        }
    })?;

    if let Some(stanza) = stanza {
        Ok(Some(Stanza { stanza }))
    } else {
        Ok(None)
    }
}

#[pyfunction]
fn read_stanzas(file: PyObject) -> PyResult<Py<PyList>> {
    Python::with_gil(|py| {
        let reader = PyBinaryFile::from(file);
        let ret = PyList::empty(py);

        let mut reader = BufReader::new(reader);

        let stanzas = bazaar::rio::read_stanzas(&mut reader).map_err(|e| match e {
            bazaar::rio::Error::Io(e) => {
                PyErr::new::<PyIOError, _>(format!("Error reading stanza file: {}", e))
            }
            _ => PyErr::new::<PyValueError, _>("Error reading stanza file: ".to_string()),
        })?;
        for stanza in stanzas {
            ret.append(Stanza { stanza })?;
        }
        Ok(ret.into())
    })
}

#[pyclass]
struct RioReader {
    reader: bazaar::rio::RioReader<BufReader<PyBinaryFile>>,
}

#[pymethods]
impl RioReader {
    #[new]
    fn new(file: PyObject) -> PyResult<RioReader> {
        let reader = PyBinaryFile::from(file);
        let reader = BufReader::new(reader);
        let reader = bazaar::rio::RioReader::new(reader);

        Ok(RioReader { reader })
    }

    fn __iter__<'a>(&mut self, py: Python<'a>) -> PyResult<Bound<'a, PyIterator>> {
        let ret = PyList::empty(py);
        for stanza in self.reader.iter() {
            let stanza = stanza.map_err(|e| match e {
                bazaar::rio::Error::Io(e) => {
                    PyErr::new::<PyIOError, _>(format!("Error reading stanza file: {}", e))
                }
                _ => PyErr::new::<PyValueError, _>("Error reading stanza file: ".to_string()),
            })?;
            ret.append(Stanza {
                stanza: stanza.unwrap(),
            })?;
        }
        Ok(PyIterator::from_object(&ret)?)
    }
}

#[pyfunction]
fn rio_iter<'a>(
    py: Python<'a>,
    stanzas: &'a Bound<'a, PyAny>,
    header: Option<Vec<u8>>,
) -> PyResult<Bound<'a, PyIterator>> {
    let ret = PyList::empty(py);
    let pyiter = stanzas.try_iter()?;
    let mut stanzas = Vec::new();
    for stanza in pyiter {
        let stanza = stanza?;
        stanzas.push(stanza.extract::<Stanza>()?.stanza);
    }
    for line in bazaar::rio::rio_iter(stanzas.into_iter(), header) {
        let line = line.as_slice();
        ret.append(PyBytes::new(py, line))?;
    }
    Ok(PyIterator::from_object(&ret)?)
}

pub(crate) fn rio(m: &Bound<PyModule>) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(valid_tag))?;
    m.add_wrapped(wrap_pyfunction!(read_stanza))?;
    m.add_wrapped(wrap_pyfunction!(read_stanza_file))?;
    m.add_wrapped(wrap_pyfunction!(read_stanzas))?;
    m.add_wrapped(wrap_pyfunction!(rio_iter))?;

    m.add_class::<Stanza>()?;
    m.add_class::<RioReader>()?;
    m.add_class::<RioWriter>()?;
    Ok(())
}
