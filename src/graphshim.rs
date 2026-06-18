use bazaar::RevisionId;
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use std::collections::HashSet;

/// A wrapper around a Python graph object.
///
/// This struct provides a Rust interface to Python graph objects, allowing
/// Rust code to interact with Python graph implementations for version control
/// history.
pub struct Graph(Py<PyAny>);

impl Graph {
    /// Creates a new `Graph` wrapper around a Python graph object.
    ///
    /// # Arguments
    ///
    /// * `o` - The Python graph object to wrap.
    pub fn new(o: Py<PyAny>) -> Self {
        Graph(o)
    }

    /// Finds the unique ancestors of a set of revisions.
    ///
    /// This method identifies all revisions that are ancestors of the given
    /// revisions but not ancestors of the old tip.
    ///
    /// # Arguments
    ///
    /// * `old_tip` - The revision ID of the old tip.
    /// * `parents` - A slice of revision IDs to find ancestors for.
    ///
    /// # Returns
    ///
    /// A `HashSet` containing the revision IDs of all unique ancestors.
    pub fn find_unique_ancestors(
        &self,
        old_tip: RevisionId,
        parents: &[RevisionId],
    ) -> HashSet<RevisionId> {
        Python::attach(|py| {
            let parents = PyTuple::new(py, parents).unwrap();
            let result = self
                .0
                .call_method1(py, "find_unique_ancestors", (old_tip, parents))
                .unwrap();

            result.extract::<HashSet<RevisionId>>(py).unwrap()
        })
    }
}
