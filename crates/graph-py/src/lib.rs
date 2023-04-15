use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::types::{PyDict, PyList, PyBytes};
use std::collections::HashMap;

type Key = Vec<u8>;

fn extract_parent_map(parent_map: &PyDict) -> PyResult<HashMap<Key, Vec<Key>>> {
    parent_map.iter().map(|(k, v)| {
        let vs = v
            .iter()?
            .map(|v| v?.extract::<Key>())
            .into_iter().collect::<Result<Vec<_>, _>>()?;
        Ok((k.extract()?, vs))
    }).into_iter().collect::<Result<HashMap<_, _>, _>>()
}

/// Given a map from child => parents, create a map of parent => children
#[pyfunction]
fn invert_parent_map(py: Python, parent_map: &PyDict) -> PyResult<PyObject> {
    let parent_map = extract_parent_map(parent_map)?;
    let ret = PyDict::new(py);
    for (k, vs) in breezy_graph::invert_parent_map::<Key>(&parent_map).into_iter() {
        ret.set_item(
            PyBytes::new(py, k),
            PyList::new(py, vs.into_iter().map(|v| PyBytes::new(py, v).to_object(py))))?;
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

    let ret = PyDict::new(py);
    for (k, vs) in breezy_graph::collapse_linear_regions::<Key>(&parent_map).into_iter() {
        ret.set_item(
            PyBytes::new(py, k),
            PyList::new(py, vs.into_iter().map(|v| PyBytes::new(py, v).to_object(py))))?;
    }
    Ok(ret.to_object(py))
}

#[pymodule]
fn _graph_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(invert_parent_map))?;
    m.add_wrapped(wrap_pyfunction!(collapse_linear_regions))?;
    Ok(())
}
