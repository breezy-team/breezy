#![allow(non_snake_case)]

use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};
use pyo3::wrap_pyfunction;
use std::collections::{HashMap, HashSet};
use std::hash::Hash;

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
        Python::with_gil(|py| match self.0.as_ref(py).hash() {
            Err(err) => err.restore(py),
            Ok(hash) => state.write_isize(hash),
        });
    }
}

impl PartialEq for PyNode {
    fn eq(&self, other: &PyNode) -> bool {
        Python::with_gil(|py| match self.0.as_ref(py).eq(other.0.as_ref(py)) {
            Err(err) => {
                err.restore(py);
                false
            }
            Ok(b) => b,
        })
    }
}

impl std::cmp::Eq for PyNode {}

fn extract_parent_map(parent_map: &PyDict) -> PyResult<HashMap<PyNode, Vec<PyNode>>> {
    parent_map
        .iter()
        .map(|(k, v)| {
            let vs = v
                .iter()?
                .map(|v| Ok::<_, PyErr>(v?.into()))
                .into_iter()
                .collect::<Result<Vec<_>, _>>()?;
            Ok((k.into(), vs))
        })
        .into_iter()
        .collect::<Result<HashMap<_, _>, _>>()
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
            PyList::new(py, vs.into_iter().map(|v| v.into_py(py))),
        )?;
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
            PyList::new(py, vs.into_iter().map(|v| v.into_py(py))),
        )?;
    }

    Ok(ret.to_object(py))
}

#[pyclass]
struct PyParentsProvider {
    provider: Box<dyn breezy_graph::ParentsProvider<PyNode> + Send>,
}

#[pymethods]
impl PyParentsProvider {
    fn get_parent_map(&mut self, py: Python, keys: PyObject) -> PyResult<PyObject> {
        let mut hash_key: HashSet<PyNode> = HashSet::new();
        for key in keys.as_ref(py).iter()? {
            hash_key.insert(key?.into());
        }
        let result = self.provider.get_parent_map(&hash_key.iter().collect());
        let ret = PyDict::new(py);
        for (k, vs) in result {
            ret.set_item::<PyObject, &PyTuple>(
                k.into_py(py),
                PyTuple::new(py, vs.into_iter().map(|v| v.into_py(py))),
            )?;
        }
        Ok(ret.to_object(py))
    }
}

#[pyfunction]
fn DictParentsProvider(py: Python, parent_map: &PyDict) -> PyResult<PyObject> {
    let parent_map = extract_parent_map(parent_map)?;
    let provider = PyParentsProvider {
        provider: Box::new(breezy_graph::DictParentsProvider::<PyNode>::new(parent_map)),
    };
    Ok(provider.into_py(py))
}

#[pyclass]
struct TopoSorter {
    sorter: breezy_graph::tsort::TopoSorter<PyNode>,
}

#[pymethods]
impl TopoSorter {
    #[new]
    fn new(py: Python, graph: PyObject) -> PyResult<TopoSorter> {
        let iter = if graph.as_ref(py).is_instance_of::<PyDict>()? {
            graph
                .downcast::<PyDict>(py)?
                .call_method0("items")?
                .iter()?
        } else {
            graph.as_ref(py).iter()?
        };
        let graph = iter
            .map(|k| k?.extract::<(PyObject, Vec<PyObject>)>())
            .map(|k| {
                k.map(|(k, vs)| {
                    (
                        PyNode::from(k),
                        vs.into_iter().map(|v| PyNode::from(v)).collect(),
                    )
                })
            })
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

#[pyclass]
struct PyRevnoVec {
    revno_vec: breezy_graph::RevnoVec,
}

impl From<breezy_graph::RevnoVec> for PyRevnoVec {
    fn from(revno_vec: breezy_graph::RevnoVec) -> Self {
        PyRevnoVec { revno_vec }
    }
}

impl From<PyRevnoVec> for breezy_graph::RevnoVec {
    fn from(revno_vec: PyRevnoVec) -> Self {
        revno_vec.revno_vec
    }
}

#[pyclass]
struct MergeSorter {
    sorter: breezy_graph::tsort::MergeSorter<PyNode>,
}

fn branch_tip_is_null(py: Python, branch_tip: PyObject) -> bool {
    if let Ok(branch_tip) = branch_tip.extract::<&[u8]>(py) {
        branch_tip == b"null:"
    } else if let Ok((branch_tip,)) = branch_tip.extract::<(&[u8],)>(py) {
        branch_tip == b"null:"
    } else {
        false
    }
}

#[pymethods]
impl MergeSorter {
    #[new]
    fn new(
        py: Python,
        graph: PyObject,
        mut branch_tip: Option<PyObject>,
        mainline_revisions: Option<PyObject>,
        generate_revno: Option<bool>,
    ) -> PyResult<MergeSorter> {
        let iter = if graph.as_ref(py).is_instance_of::<PyDict>()? {
            graph
                .downcast::<PyDict>(py)?
                .call_method0("items")?
                .iter()?
        } else {
            graph.as_ref(py).iter()?
        };
        let graph = iter
            .map(|k| k?.extract::<(PyObject, Vec<PyObject>)>())
            .map(|k| {
                k.map(|(k, vs)| {
                    (
                        PyNode::from(k),
                        vs.into_iter().map(|v| PyNode::from(v)).collect(),
                    )
                })
            })
            .collect::<PyResult<HashMap<PyNode, Vec<PyNode>>>>()?;

        let mainline_revisions = if let Some(mainline_revisions) = mainline_revisions {
            let mainline_revisions = mainline_revisions
                .as_ref(py)
                .iter()?
                .map(|k| k?.extract::<PyObject>())
                .collect::<PyResult<Vec<PyObject>>>()?;
            Some(
                mainline_revisions
                    .into_iter()
                    .map(|k| PyNode::from(k))
                    .collect(),
            )
        } else {
            None
        };

        // The null: revision doesn't exist in the graph, so don't attempt to remove it
        match branch_tip {
            Some(ref mut tip_obj) => {
                if branch_tip_is_null(py, tip_obj.clone_ref(py)) {
                    branch_tip = None;
                }
            }
            None => (),
        }

        let sorter = breezy_graph::tsort::MergeSorter::<PyNode>::new(
            graph,
            branch_tip.map(|k| PyNode::from(k)),
            mainline_revisions,
            generate_revno.unwrap_or(true),
        );
        Ok(MergeSorter { sorter })
    }

    fn __next__(&mut self, py: Python) -> Option<(usize, PyObject, usize, Option<PyObject>, bool)> {
        match self.sorter.next() {
            None => None,
            Some((sequence_number, node, merge_depth, revno, end_of_merge)) => Some((
                sequence_number,
                node.into_py(py),
                merge_depth,
                revno.map(|r| PyRevnoVec::from(r).into_py(py)),
                end_of_merge,
            )),
        }
    }

    fn __iter__(slf: PyRefMut<Self>) -> PyRefMut<Self> {
        slf
    }

    fn iter_topo_order(slf: PyRefMut<Self>) -> PyRefMut<Self> {
        slf
    }

    fn sorted(&mut self, py: Python) -> PyResult<PyObject> {
        let ret = PyList::empty(py);
        while let Some((sequence_number, node, merge_depth, revno, end_of_merge)) =
            self.__next__(py)
        {
            ret.append((sequence_number, node, merge_depth, revno, end_of_merge))?;
        }
        Ok(ret.to_object(py))
    }
}

/// Topological sort a graph which groups merges.
///
/// :param graph: sequence of pairs of node->parents_list.
/// :param branch_tip: the tip of the branch to graph. Revisions not
///                    reachable from branch_tip are not included in the
///                    output.
/// :param mainline_revisions: If not None this forces a mainline to be
///                            used rather than synthesised from the graph.
///                            This must be a valid path through some part
///                            of the graph. If the mainline does not cover all
///                            the revisions, output stops at the start of the
///                            old revision listed in the mainline revisions
///                            list.
///                            The order for this parameter is oldest-first.
/// :param generate_revno: Optional parameter controlling the generation of
///     revision number sequences in the output. See the output description of
///     the MergeSorter docstring for details.
/// :result: See the MergeSorter docstring for details.
///
/// Node identifiers can be any hashable object, and are typically strings.
#[pyfunction]
fn merge_sort(
    py: Python,
    graph: PyObject,
    branch_tip: Option<PyObject>,
    mainline_revisions: Option<PyObject>,
    generate_revno: Option<bool>,
) -> PyResult<PyObject> {
    let mut sorter = MergeSorter::new(py, graph, branch_tip, mainline_revisions, generate_revno)?;
    Ok(sorter.sorted(py)?)
}

#[pymodule]
fn _graph_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(invert_parent_map))?;
    m.add_wrapped(wrap_pyfunction!(collapse_linear_regions))?;
    m.add_wrapped(wrap_pyfunction!(DictParentsProvider))?;
    m.add_wrapped(wrap_pyfunction!(merge_sort))?;
    m.add_class::<TopoSorter>()?;
    m.add_class::<MergeSorter>()?;
    Ok(())
}
