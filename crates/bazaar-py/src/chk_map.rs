use bazaar::chk_map::{self, Key, SerialisedKey, SearchKeyFn, SearchPrefix};
use pyo3::exceptions::{PyKeyError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyTuple};
use pyo3::wrap_pyfunction;
use std::collections::HashMap;
use std::sync::Arc;

#[pyclass]
pub struct LeafNode {
    node: chk_map::Node,
}

#[pymethods]
impl LeafNode {
    #[new]
    #[pyo3(signature = (search_key_func = None))]
    fn new(search_key_func: Option<PyObject>) -> PyResult<Self> {
        let search_key_func = search_key_func
            .map(|_| chk_map::search_key_plain as SearchKeyFn)
            .unwrap_or(chk_map::DEFAULT_SEARCH_KEY_FUNC);
        Ok(Self {
            node: chk_map::Node::leaf(Some(search_key_func)),
        })
    }

    #[getter]
    fn _items(&self, py: Python) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        let items = match &self.node {
            chk_map::Node::Leaf { items, .. } => items,
            _ => return Err(PyTypeError::new_err("Not a leaf node")),
        };

        for (key, value) in items {
            let py_key = key_to_py_tuple(py, key)?;
            let py_value = PyBytes::new(py, value);
            dict.set_item(py_key, py_value)?;
        }
        Ok(dict.into())
    }

    #[setter]
    fn set__items(&mut self, py: Python, items: &PyDict) -> PyResult<()> {
        let mut rust_items = HashMap::new();
        for (key, value) in items.iter() {
            let key: Key = py_to_key(py, key)?;
            let value = value.extract::<&PyBytes>()?.as_bytes().to_vec();
            rust_items.insert(key, value);
        }

        if let chk_map::Node::Leaf { ref mut items, .. } = self.node {
            *items = rust_items;
        } else {
            return Err(PyTypeError::new_err("Not a leaf node"));
        }
        Ok(())
    }

    #[getter]
    fn _len(&self) -> usize {
        self.node.len()
    }

    #[setter]
    fn set__len(&mut self, len: usize) -> PyResult<()> {
        if let chk_map::Node::Leaf { ref mut len, .. } = self.node {
            *len = len;
            Ok(())
        } else {
            Err(PyTypeError::new_err("Not a leaf node"))
        }
    }

    #[getter]
    fn _maximum_size(&self) -> usize {
        self.node.maximum_size()
    }

    #[getter]
    fn _key(&self, py: Python) -> Option<Py<PyTuple>> {
        match self.node.key() {
            Some(key) => Some(key_to_py_tuple(py, key).unwrap()),
            None => None,
        }
    }

    #[setter]
    fn set__key(&mut self, py: Python, key: Option<PyObject>) -> PyResult<()> {
        let key = match key {
            Some(k) => Some(py_to_key(py, &k)?),
            None => None,
        };

        match &mut self.node {
            chk_map::Node::Leaf { ref mut key: node_key, .. } => {
                *node_key = key;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    #[getter]
    fn _key_width(&self) -> PyResult<usize> {
        match &self.node {
            chk_map::Node::Leaf { key_width, .. } => Ok(*key_width),
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    #[setter]
    fn set__key_width(&mut self, width: usize) -> PyResult<()> {
        match &mut self.node {
            chk_map::Node::Leaf { ref mut key_width, .. } => {
                *key_width = width;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    #[getter]
    fn _raw_size(&self) -> PyResult<usize> {
        match &self.node {
            chk_map::Node::Leaf { raw_size, .. } => Ok(*raw_size),
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    #[setter]
    fn set__raw_size(&mut self, size: usize) -> PyResult<()> {
        match &mut self.node {
            chk_map::Node::Leaf { ref mut raw_size, .. } => {
                *raw_size = size;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    #[getter]
    fn _search_prefix(&self, py: Python) -> PyResult<Option<Py<PyBytes>>> {
        match &self.node {
            chk_map::Node::Leaf { search_prefix, .. } => {
                match search_prefix {
                    SearchPrefix::Unknown => Ok(None),
                    SearchPrefix::None => Ok(None),
                    SearchPrefix::Known(prefix) => Ok(Some(PyBytes::new(py, prefix).into())),
                }
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    #[setter]
    fn set__search_prefix(&mut self, py: Python, prefix: Option<PyObject>) -> PyResult<()> {
        let search_prefix = match prefix {
            Some(p) => {
                if p.is_none(py) {
                    SearchPrefix::None
                } else {
                    let bytes = p.extract::<&PyBytes>(py)?.as_bytes().to_vec();
                    SearchPrefix::Known(bytes)
                }
            }
            None => SearchPrefix::Unknown,
        };

        match &mut self.node {
            chk_map::Node::Leaf { ref mut search_prefix: node_prefix, .. } => {
                *node_prefix = search_prefix;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    #[getter]
    fn _common_serialised_prefix(&self, py: Python) -> PyResult<Option<Py<PyBytes>>> {
        match &self.node {
            chk_map::Node::Leaf { common_serialised_prefix, .. } => {
                match common_serialised_prefix {
                    Some(prefix) => Ok(Some(PyBytes::new(py, prefix).into())),
                    None => Ok(None),
                }
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    #[setter]
    fn set__common_serialised_prefix(&mut self, py: Python, prefix: Option<PyObject>) -> PyResult<()> {
        let common_serialised_prefix = match prefix {
            Some(p) => {
                if p.is_none(py) {
                    None
                } else {
                    Some(p.extract::<&PyBytes>(py)?.as_bytes().to_vec())
                }
            }
            None => None,
        };

        match &mut self.node {
            chk_map::Node::Leaf { ref mut common_serialised_prefix: node_prefix, .. } => {
                *node_prefix = common_serialised_prefix;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    fn set_maximum_size(&mut self, size: usize) -> PyResult<()> {
        self.node.set_maximum_size(size);
        Ok(())
    }

    fn _current_size(&self) -> usize {
        self.node.current_size()
    }
    
    fn _compute_search_prefix(&mut self) -> PyResult<()> {
        match &mut self.node {
            chk_map::Node::Leaf { .. } => {
                self.node.compute_search_prefix();
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    fn _compute_serialised_prefix(&mut self) -> PyResult<()> {
        match &mut self.node {
            chk_map::Node::Leaf { .. } => {
                self.node.compute_serialised_prefix();
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not a leaf node")),
        }
    }

    fn __len__(&self) -> usize {
        self.node.len()
    }
}

#[pyclass]
pub struct InternalNode {
    node: chk_map::Node,
}

#[pymethods]
impl InternalNode {
    #[new]
    #[pyo3(signature = (search_prefix, search_key_func = None))]
    fn new(py: Python, search_prefix: PyObject, search_key_func: Option<PyObject>) -> PyResult<Self> {
        let search_key_func = search_key_func
            .map(|_| chk_map::search_key_plain as SearchKeyFn)
            .unwrap_or(chk_map::DEFAULT_SEARCH_KEY_FUNC);
        
        let search_prefix = if search_prefix.is_none(py) {
            SearchPrefix::None
        } else if let Ok(bytes) = search_prefix.extract::<&PyBytes>(py) {
            SearchPrefix::Known(bytes.as_bytes().to_vec())
        } else {
            return Err(PyTypeError::new_err("search_prefix must be bytes or None"));
        };

        Ok(Self {
            node: chk_map::Node::internal(search_prefix, Some(search_key_func)),
        })
    }

    #[getter]
    fn _items(&self, py: Python) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        let items = match &self.node {
            chk_map::Node::Internal { items, .. } => items,
            _ => return Err(PyTypeError::new_err("Not an internal node")),
        };

        for (prefix, node_child) in items {
            let py_prefix = PyBytes::new(py, prefix);
            let py_value = match node_child {
                chk_map::NodeChild::Tuple(key) => {
                    let py_tuple = key_to_py_tuple(py, key)?;
                    py_tuple.into_py(py)
                },
                chk_map::NodeChild::Node(_) => {
                    // This shouldn't happen in normal Python code
                    PyTuple::new(py, [PyBytes::new(py, b"node")]).into_py(py)
                }
            };
            dict.set_item(py_prefix, py_value)?;
        }
        Ok(dict.into())
    }

    #[setter]
    fn set__items(&mut self, py: Python, items: &PyDict) -> PyResult<()> {
        let mut rust_items = HashMap::new();
        for (prefix, value) in items.iter() {
            let prefix = prefix.extract::<&PyBytes>()?.as_bytes().to_vec();
            
            if let Ok(tuple) = value.extract::<&PyTuple>() {
                let key = py_tuple_to_key(py, tuple)?;
                rust_items.insert(prefix, chk_map::NodeChild::Tuple(key));
            } else {
                return Err(PyTypeError::new_err("Item value must be a tuple"));
            }
        }

        if let chk_map::Node::Internal { ref mut items, .. } = self.node {
            *items = rust_items;
        } else {
            return Err(PyTypeError::new_err("Not an internal node"));
        }
        Ok(())
    }

    #[getter]
    fn _len(&self) -> usize {
        self.node.len()
    }

    #[setter]
    fn set__len(&mut self, len: usize) -> PyResult<()> {
        if let chk_map::Node::Internal { ref mut len, .. } = self.node {
            *len = len;
            Ok(())
        } else {
            Err(PyTypeError::new_err("Not an internal node"))
        }
    }

    #[getter]
    fn _maximum_size(&self) -> usize {
        self.node.maximum_size()
    }

    #[getter]
    fn _key(&self, py: Python) -> Option<Py<PyTuple>> {
        match self.node.key() {
            Some(key) => Some(key_to_py_tuple(py, key).unwrap()),
            None => None,
        }
    }

    #[setter]
    fn set__key(&mut self, py: Python, key: Option<PyObject>) -> PyResult<()> {
        let key = match key {
            Some(k) => Some(py_to_key(py, &k)?),
            None => None,
        };

        match &mut self.node {
            chk_map::Node::Internal { ref mut key: node_key, .. } => {
                *node_key = key;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not an internal node")),
        }
    }

    #[getter]
    fn _key_width(&self) -> PyResult<usize> {
        match &self.node {
            chk_map::Node::Internal { key_width, .. } => Ok(*key_width),
            _ => Err(PyTypeError::new_err("Not an internal node")),
        }
    }

    #[setter]
    fn set__key_width(&mut self, width: usize) -> PyResult<()> {
        match &mut self.node {
            chk_map::Node::Internal { ref mut key_width, .. } => {
                *key_width = width;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not an internal node")),
        }
    }

    #[getter]
    fn _search_prefix(&self, py: Python) -> PyResult<Option<Py<PyBytes>>> {
        match &self.node {
            chk_map::Node::Internal { search_prefix, .. } => {
                match search_prefix {
                    SearchPrefix::Unknown => Ok(None),
                    SearchPrefix::None => Ok(None),
                    SearchPrefix::Known(prefix) => Ok(Some(PyBytes::new(py, prefix).into())),
                }
            }
            _ => Err(PyTypeError::new_err("Not an internal node")),
        }
    }

    #[setter]
    fn set__search_prefix(&mut self, py: Python, prefix: Option<PyObject>) -> PyResult<()> {
        let search_prefix = match prefix {
            Some(p) => {
                if p.is_none(py) {
                    SearchPrefix::None
                } else {
                    let bytes = p.extract::<&PyBytes>(py)?.as_bytes().to_vec();
                    SearchPrefix::Known(bytes)
                }
            }
            None => SearchPrefix::Unknown,
        };

        match &mut self.node {
            chk_map::Node::Internal { ref mut search_prefix: node_prefix, .. } => {
                *node_prefix = search_prefix;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not an internal node")),
        }
    }

    #[getter]
    fn _node_width(&self) -> PyResult<usize> {
        match &self.node {
            chk_map::Node::Internal { node_width, .. } => Ok(*node_width),
            _ => Err(PyTypeError::new_err("Not an internal node")),
        }
    }

    #[setter]
    fn set__node_width(&mut self, width: usize) -> PyResult<()> {
        match &mut self.node {
            chk_map::Node::Internal { ref mut node_width, .. } => {
                *node_width = width;
                Ok(())
            }
            _ => Err(PyTypeError::new_err("Not an internal node")),
        }
    }

    fn set_maximum_size(&mut self, size: usize) -> PyResult<()> {
        self.node.set_maximum_size(size);
        Ok(())
    }

    fn add_node(&mut self, py: Python, prefix: &PyBytes, node: PyObject) -> PyResult<()> {
        let prefix = prefix.as_bytes().to_vec();
        
        let new_node = if let Ok(leaf_node) = node.extract::<PyRef<LeafNode>>(py) {
            leaf_node.node.clone()
        } else if let Ok(internal_node) = node.extract::<PyRef<InternalNode>>(py) {
            internal_node.node.clone()
        } else {
            return Err(PyTypeError::new_err("node must be a LeafNode or InternalNode"));
        };

        match &mut self.node {
            chk_map::Node::Internal { .. } => {
                self.node.add_node(&prefix, new_node).map_err(|e| {
                    PyValueError::new_err(format!("Failed to add node: {:?}", e))
                })
            }
            _ => Err(PyTypeError::new_err("Not an internal node")),
        }
    }

    fn __len__(&self) -> usize {
        self.node.len()
    }
}

// Helper functions to convert between Rust and Python types
fn py_to_key(py: Python, obj: &PyAny) -> PyResult<Key> {
    if let Ok(tuple) = obj.extract::<&PyTuple>() {
        py_tuple_to_key(py, tuple)
    } else {
        Err(PyTypeError::new_err("Expected a tuple for key"))
    }
}

fn py_tuple_to_key(py: Python, tuple: &PyTuple) -> PyResult<Key> {
    let mut elements = Vec::with_capacity(tuple.len());
    for item in tuple.iter() {
        let bytes = if let Ok(bytes) = item.extract::<&PyBytes>() {
            bytes.as_bytes().to_vec()
        } else if let Ok(s) = item.extract::<&str>() {
            s.as_bytes().to_vec()
        } else {
            return Err(PyTypeError::new_err("Key tuple elements must be bytes or str"));
        };
        elements.push(bytes);
    }
    if elements.is_empty() {
        return Err(PyValueError::new_err("Key cannot be empty"));
    }
    Ok(Key::from(elements))
}

fn key_to_py_tuple(py: Python, key: &Key) -> PyResult<Py<PyTuple>> {
    let elements: Vec<&[u8]> = key.iter().collect();
    Ok(PyTuple::new(py, elements.iter().map(|&v| PyBytes::new(py, v))).into())
}

#[pyfunction]
fn _search_key_16(py: Python, key: Vec<Vec<u8>>) -> Bound<PyBytes> {
    let key: Key = key.into();
    let ret = bazaar::chk_map::search_key_16(&key);
    PyBytes::new(py, &ret)
}

#[pyfunction]
fn _search_key_255(py: Python, key: Vec<Vec<u8>>) -> Bound<PyBytes> {
    let key: Key = key.into();
    let ret = bazaar::chk_map::search_key_255(&key);
    PyBytes::new(py, &ret)
}

#[pyfunction]
fn _bytes_to_text_key(py: Python, key: Vec<u8>) -> PyResult<(Bound<PyBytes>, Bound<PyBytes>)> {
    let ret = bazaar::chk_map::bytes_to_text_key(key.as_slice());
    if ret.is_err() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "Invalid key",
        ));
    }
    let ret = ret.unwrap();
    Ok((PyBytes::new(py, ret.0), PyBytes::new(py, ret.1)))
}

#[pyfunction]
fn common_prefix_pair<'a>(py: Python<'a>, key: &'a [u8], key2: &'a [u8]) -> Bound<'a, PyBytes> {
    PyBytes::new(py, bazaar::chk_map::common_prefix_pair(key, key2))
}

#[pyfunction]
fn common_prefix_many(py: Python, keys: Vec<Vec<u8>>) -> Option<Bound<PyBytes>> {
    let keys = keys.iter().map(|v| v.as_slice()).collect::<Vec<&[u8]>>();
    bazaar::chk_map::common_prefix_many(keys.into_iter())
        .as_ref()
        .map(|v| PyBytes::new(py, v))
}

#[pyfunction]
fn _search_key_plain(py: Python, key: PyObject) -> PyResult<Bound<PyBytes>> {
    let key = py_to_key(py, key.extract(py)?)?;
    let serialized = bazaar::chk_map::search_key_plain(&key);
    Ok(PyBytes::new(py, &serialized))
}

/// Python wrapper for Store trait
#[pyclass]
pub struct PyStore {
    #[pyo3(get)]
    search_key_func: Option<PyObject>,
    inner: PyObject,
}

#[pymethods]
impl PyStore {
    #[new]
    fn new(inner: PyObject, search_key_func: Option<PyObject>) -> Self {
        Self { inner, search_key_func }
    }
}

pub(crate) fn _chk_map_rs(py: Python) -> PyResult<Bound<PyModule>> {
    let m = PyModule::new(py, "chk_map")?;
    m.add_wrapped(wrap_pyfunction!(_search_key_16))?;
    m.add_wrapped(wrap_pyfunction!(_search_key_255))?;
    m.add_wrapped(wrap_pyfunction!(_bytes_to_text_key))?;
    m.add_wrapped(wrap_pyfunction!(common_prefix_pair))?;
    m.add_wrapped(wrap_pyfunction!(common_prefix_many))?;
    m.add_wrapped(wrap_pyfunction!(_search_key_plain))?;
    m.add_class::<LeafNode>()?;
    m.add_class::<InternalNode>()?;
    m.add_class::<PyStore>()?;
    Ok(m)
}
