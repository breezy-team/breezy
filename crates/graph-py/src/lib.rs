use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::{PyDict, PyList, PyIterator};
use std::collections::HashMap;
use std::hash::Hash;
use pyo3::import_exception;

import_exception!(breezy.errors, GraphCycleError);

struct PyNode(PyObject);

impl std::fmt::Debug for PyNode {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        Python::with_gil(|py| {
            let repr = self.0.as_ref(py).repr();
            if PyErr::occurred(py) {
                return Err(std::fmt::Error);
            }
            if let Ok(repr) = repr {
                return write!(f, "{}", repr.to_string());
            } else {
                return write!(f, "???");
            }
        })
    }
}

impl std::fmt::Display for PyNode {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        Python::with_gil(|py| {
            let repr = self.0.as_ref(py).repr();
            if PyErr::occurred(py) {
                return Err(std::fmt::Error);
            }
            if let Ok(repr) = repr {
                return write!(f, "{}", repr.to_string());
            } else {
                return write!(f, "???");
            }
        })
    }
}

impl Clone for PyNode {
    fn clone(&self) -> PyNode {
        PyNode(self.0.clone())
    }
}

impl From<&PyAny> for PyNode {
    fn from(obj: &PyAny) -> PyNode {
        PyNode(obj.to_object(obj.py()))
    }
}

impl From<PyObject> for PyNode {
    fn from(obj: PyObject) -> PyNode {
        PyNode(obj)
    }
}

impl IntoPy<PyObject> for PyNode {
    fn into_py(self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl IntoPy<PyObject> for &PyNode {
    fn into_py(self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl Hash for PyNode {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        Python::with_gil(|py| {
            match self.0.as_ref(py).hash() {
                Err(err) => err.restore(py),
                Ok(hash) => state.write_isize(hash)
            }
        });
    }
}

impl PartialEq for PyNode {
    fn eq(&self, other: &PyNode) -> bool {
        Python::with_gil(|py| {
            match self.0.as_ref(py).eq(other.0.as_ref(py)) {
                Err(err) => {
                    err.restore(py);
                    false
                }
                Ok(b) => b
            }
        })
    }
}

impl std::cmp::Eq for PyNode {}

fn extract_parent_map(parent_map: &PyDict) -> PyResult<HashMap<PyNode, Vec<PyNode>>> {
    parent_map.iter().map(|(k, v)| {
        let vs = v
            .iter()?
            .map(|v| Ok::<_, PyErr>(v?.into()))
            .into_iter().collect::<Result<Vec<_>, _>>()?;
        Ok((k.into(), vs))
    }).into_iter().collect::<Result<HashMap<_, _>, _>>()
}

/// Given a map from child => parents, create a map of parent => children
#[pyfunction]
fn invert_parent_map(py: Python, parent_map: &PyDict) -> PyResult<PyObject> {
    let parent_map = extract_parent_map(parent_map)?;
    let ret = PyDict::new(py);
    let result = breezy_graph::invert_parent_map::<PyNode>(&parent_map);
    if PyErr::occurred(py) {
        return Err(PyErr::fetch(py));
    }

    for (k, vs) in result {
        ret.set_item::<PyObject, &PyList>(
            k.into_py(py),
            PyList::new(py, vs.into_iter().map(|v| v.into_py(py))))?;
    }

    Ok(ret.to_object(py))
}

/// Collapse regions of the graph that are 'linear'.
///
/// For example::
///
///   A:[B], B:[C]
///
/// can be collapsed by removing B and getting::
///
///   A:[C]
///
/// :param parent_map: A dictionary mapping children to their parents
/// :return: Another dictionary with 'linear' chains collapsed
#[pyfunction]
fn collapse_linear_regions(py: Python, parent_map: &PyDict) -> PyResult<PyObject> {
    let parent_map = extract_parent_map(parent_map)?;

    let result = breezy_graph::collapse_linear_regions::<PyNode>(&parent_map);
    if PyErr::occurred(py) {
        return Err(PyErr::fetch(py));
    }

    let ret = PyDict::new(py);
    for (k, vs) in result {
        ret.set_item::<PyObject, &PyList>(
            k.into_py(py),
            PyList::new(py, vs.into_iter().map(|v| v.into_py(py))))?;
    }

    Ok(ret.to_object(py))
}

#[pyclass]
struct TopoSorter {
    sorter: breezy_graph::tsort::TopoSorter<PyNode>
}

#[pymethods]
impl TopoSorter {
    #[new]
    fn new(py: Python, graph: PyObject) -> PyResult<TopoSorter> {
        let iter = if graph.as_ref(py).is_instance_of::<PyDict>()? {
            graph.downcast::<PyDict>(py)?.call_method0("items")?.iter()?
        } else {
            graph.as_ref(py).iter()?
        };
        let graph = iter
            .map(|k| k?.extract::<(PyObject, Vec<PyObject>)>())
            .map(|k| k.map(|(k, vs)| (PyNode::from(k), vs.into_iter().map(|v| PyNode::from(v)).collect())))
            .collect::<PyResult<Vec<(PyNode, Vec<PyNode>)>>>()?;

        let sorter = breezy_graph::tsort::TopoSorter::<PyNode>::new(graph.into_iter());
        Ok(TopoSorter { sorter })
    }

    fn __next__(&mut self, py: Python) -> PyResult<Option<PyObject>> {
        match self.sorter.next() {
            None => Ok(None),
            Some(Ok(node)) => Ok(Some(node.into_py(py))),
            Some(Err(breezy_graph::tsort::Error::Cycle(e))) => Err(GraphCycleError::new_err(e)),
        }
    }

    fn __iter__(slf: PyRefMut<Self>) -> PyRefMut<Self> {
        slf
    }

    fn iter_topo_order(slf: PyRefMut<Self>) -> PyRefMut<Self> {
        slf
    }

    fn sorted(&mut self, py: Python) -> PyResult<Vec<PyObject>> {
        let mut ret = Vec::new();
        while let Some(node) = self.__next__(py)? {
            ret.push(node);
        }
        Ok(ret)
    }
}

#[pymodule]
fn _graph_rs(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(invert_parent_map))?;
    m.add_wrapped(wrap_pyfunction!(collapse_linear_regions))?;
    m.add_class::<TopoSorter>()?;
    Ok(())
}
