//! Python bindings for breezy-annotate.
//!
//! Replaces the historical Cython module `breezy._annotator_pyx`. The three
//! functions exposed here are the hot inner loops used by
//! `breezy.bzr.annotate.VersionedFileAnnotator`.

use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};

/// Validate that the matching block fits inside both sequences.
fn check_match_ranges(
    parent_len: usize,
    annotations_len: usize,
    parent_idx: usize,
    lines_idx: usize,
    match_len: usize,
) -> PyResult<()> {
    if parent_idx + match_len > parent_len {
        return Err(PyValueError::new_err(format!(
            "Match length exceeds len of parent_annotations {} > {}",
            parent_idx + match_len,
            parent_len
        )));
    }
    if lines_idx + match_len > annotations_len {
        return Err(PyValueError::new_err(format!(
            "Match length exceeds len of annotations {} > {}",
            lines_idx + match_len,
            annotations_len
        )));
    }
    Ok(())
}

/// Combine two annotation tuples into a single sorted, de-duplicated tuple.
///
/// Both inputs must already be sorted ascending. The result is cached in
/// `cache` keyed on the lexicographically-ordered pair of inputs so that
/// callers see referentially identical objects for equal inputs.
#[pyfunction]
#[pyo3(name = "_combine_annotations")]
fn combine_annotations<'py>(
    py: Python<'py>,
    ann_one: &Bound<'py, PyAny>,
    ann_two: &Bound<'py, PyAny>,
    cache: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyAny>> {
    let cache_key: Bound<'py, PyTuple> = if ann_one.lt(ann_two)? {
        PyTuple::new(py, [ann_one, ann_two])?
    } else {
        PyTuple::new(py, [ann_two, ann_one])?
    };
    if let Some(cached) = cache.get_item(&cache_key)? {
        return Ok(cached);
    }

    let one: &Bound<'py, PyTuple> = ann_one
        .cast::<PyTuple>()
        .map_err(|_| PyTypeError::new_err("annotations must be tuples"))?;
    let two: &Bound<'py, PyTuple> = ann_two
        .cast::<PyTuple>()
        .map_err(|_| PyTypeError::new_err("annotations must be tuples"))?;

    let one_len = one.len();
    let two_len = two.len();
    let mut merged: Vec<Bound<'py, PyAny>> = Vec::with_capacity(one_len + two_len);
    let mut i = 0usize;
    let mut j = 0usize;
    while i < one_len && j < two_len {
        let left = one.get_item(i)?;
        let right = two.get_item(j)?;
        if left.is(&right) || left.eq(&right)? {
            merged.push(left);
            i += 1;
            j += 1;
        } else if left.lt(&right)? {
            merged.push(left);
            i += 1;
        } else {
            merged.push(right);
            j += 1;
        }
    }
    while i < one_len {
        merged.push(one.get_item(i)?);
        i += 1;
    }
    while j < two_len {
        merged.push(two.get_item(j)?);
        j += 1;
    }

    let new_ann = PyTuple::new(py, merged)?;
    let new_ann_any: Bound<'py, PyAny> = new_ann.into_any();
    cache.set_item(&cache_key, &new_ann_any)?;
    Ok(new_ann_any)
}

/// Splice parent annotations into the child annotations for each matching block.
#[pyfunction]
#[pyo3(name = "_apply_parent_annotations")]
fn apply_parent_annotations<'py>(
    annotations: &Bound<'py, PyList>,
    parent_annotations: &Bound<'py, PyList>,
    matching_blocks: &Bound<'py, PyAny>,
) -> PyResult<()> {
    let parent_len = parent_annotations.len();
    let annotations_len = annotations.len();
    let parent_any: &Bound<'py, PyAny> = parent_annotations.as_any();
    for block in matching_blocks.try_iter()? {
        let block = block?;
        let (parent_idx, lines_idx, match_len): (usize, usize, usize) = block.extract()?;
        check_match_ranges(
            parent_len,
            annotations_len,
            parent_idx,
            lines_idx,
            match_len,
        )?;
        if match_len == 0 {
            continue;
        }
        let slice = parent_any.get_item(pyo3::types::PySlice::new(
            annotations.py(),
            parent_idx as isize,
            (parent_idx + match_len) as isize,
            1,
        ))?;
        annotations.set_slice(lines_idx, lines_idx + match_len, &slice)?;
    }
    Ok(())
}

/// For each matching block, merge the parent annotations with the existing
/// annotations, resolving disagreements via `_combine_annotations`.
#[pyfunction]
#[pyo3(name = "_merge_annotations")]
fn merge_annotations<'py>(
    py: Python<'py>,
    this_annotation: &Bound<'py, PyAny>,
    annotations: &Bound<'py, PyList>,
    parent_annotations: &Bound<'py, PyList>,
    matching_blocks: &Bound<'py, PyAny>,
    ann_cache: &Bound<'py, PyDict>,
) -> PyResult<()> {
    let parent_len = parent_annotations.len();
    let annotations_len = annotations.len();

    let mut last_ann: Option<Bound<'py, PyAny>> = None;
    let mut last_parent: Option<Bound<'py, PyAny>> = None;
    let mut last_res: Option<Bound<'py, PyAny>> = None;

    for block in matching_blocks.try_iter()? {
        let block = block?;
        let (parent_idx, lines_idx, match_len): (usize, usize, usize) = block.extract()?;
        check_match_ranges(
            parent_len,
            annotations_len,
            parent_idx,
            lines_idx,
            match_len,
        )?;
        for idx in 0..match_len {
            let ann_idx = lines_idx + idx;
            let par_idx = parent_idx + idx;
            let ann = annotations.get_item(ann_idx)?;
            let par_ann = parent_annotations.get_item(par_idx)?;
            // Identical (pointer or value) — nothing to do
            if ann.is(&par_ann) || ann.eq(&par_ann)? {
                continue;
            }
            // Originally claimed `this`, but it was really in this parent.
            if ann.is(this_annotation) {
                annotations.set_item(ann_idx, &par_ann)?;
                continue;
            }
            // Memoized result from the previous iteration.
            let memo_hit = match (&last_ann, &last_parent) {
                (Some(la), Some(lp)) => ann.is(la) && par_ann.is(lp),
                _ => false,
            };
            if memo_hit {
                annotations.set_item(ann_idx, last_res.as_ref().unwrap())?;
            } else {
                let new_ann = combine_annotations(py, &ann, &par_ann, ann_cache)?;
                annotations.set_item(ann_idx, &new_ann)?;
                last_ann = Some(ann);
                last_parent = Some(par_ann);
                last_res = Some(new_ann);
            }
        }
    }
    Ok(())
}

#[pymodule]
fn _annotator_rs(_py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(combine_annotations, m)?)?;
    m.add_function(wrap_pyfunction!(apply_parent_annotations, m)?)?;
    m.add_function(wrap_pyfunction!(merge_annotations, m)?)?;
    Ok(())
}
