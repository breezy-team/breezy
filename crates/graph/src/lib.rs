#![allow(clippy::if_same_then_else)]
use std::borrow::Borrow;
/// DIAGRAM of terminology
///       A
///       /\
///      B  C
///      |  |\
///      D  E F
///      |\/| |
///      |/\|/
///      G  H
///
/// In this diagram, relative to G and H:
/// A, B, C, D, E are common ancestors.
/// C, D and E are border ancestors, because each has a non-common descendant.
/// D and E are least common ancestors because none of their descendants are
/// common ancestors.
/// C is not a least common ancestor because its descendant, E, is a common
/// ancestor.
///
/// The find_unique_lca algorithm will pick A in two steps:
/// 1. find_lca('G', 'H') => ['D', 'E']
/// 2. Since len(['D', 'E']) > 1, find_lca('D', 'E') => ['A']
use std::collections::{HashMap, HashSet};
use std::hash::Hash;

//mod known_graph;
mod parents_provider;
pub use parents_provider::{DictParentsProvider, ParentsProvider, StackedParentsProvider};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Parents<K: Clone + PartialEq + Eq> {
    Ghost,
    Known(Vec<K>),
}

impl<K: Clone + PartialEq + Eq> Parents<K> {
    pub fn is_ghost(&self) -> bool {
        match self {
            Parents::Ghost => true,
            Parents::Known(_) => false,
        }
    }

    pub fn is_known(&self) -> bool {
        match self {
            Parents::Ghost => false,
            Parents::Known(_) => true,
        }
    }

    pub fn unwrap(&self) -> Vec<K> {
        match self {
            Parents::Ghost => panic!("unwrap called on Ghost"),
            Parents::Known(v) => v.clone(),
        }
    }

    pub fn as_ref(&self) -> Parents<&K> {
        match self {
            Parents::Ghost => Parents::Ghost,
            Parents::Known(v) => Parents::Known(v.iter().collect()),
        }
    }
}

#[cfg(feature = "pyo3")]
impl<'py, K: pyo3::IntoPyObject<'py> + Clone + PartialEq + Eq> pyo3::IntoPyObject<'py>
    for Parents<K>
{
    type Target = pyo3::types::PyAny;

    type Output = pyo3::Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: pyo3::Python<'py>) -> Result<Self::Output, Self::Error> {
        match self {
            Parents::Ghost => Ok(py.None().into_pyobject(py)?),
            Parents::Known(v) => Ok(v.into_pyobject(py)?.into_any()),
        }
    }
}

#[cfg(feature = "pyo3")]
impl<'a, K: pyo3::FromPyObject<'a> + Clone + PartialEq + Eq> pyo3::FromPyObject<'a> for Parents<K>
where
    K: 'a,
{
    fn extract_bound(obj: &pyo3::Bound<'a, pyo3::PyAny>) -> pyo3::PyResult<Self> {
        use pyo3::prelude::*;
        if obj.is_none() {
            Ok(Parents::Ghost)
        } else {
            let v = obj.extract::<Vec<K>>()?;
            Ok(Parents::Known(v))
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParentMap<K: Hash + Clone + PartialEq + Eq>(HashMap<K, Parents<K>>);

impl<K: Clone + Hash + PartialEq + Eq> ParentMap<K> {
    pub fn new() -> Self {
        ParentMap(HashMap::new())
    }

    #[inline]
    pub fn insert(&mut self, k: K, v: Parents<K>) {
        self.0.insert(k, v);
    }

    #[inline]
    pub fn get(&self, k: &K) -> Option<&Parents<K>> {
        self.0.get(k)
    }

    #[inline]
    pub fn get_key_value(&self, k: &K) -> Option<(&K, &Parents<K>)> {
        self.0.get_key_value(k)
    }

    #[inline]
    pub fn iter(&self) -> impl Iterator<Item = (&K, &Parents<K>)> {
        self.0.iter()
    }

    #[inline]
    pub fn contains_key(&self, k: &K) -> bool {
        self.0.contains_key(k)
    }

    #[inline]
    pub fn keys(&self) -> impl Iterator<Item = &K> {
        self.0.keys()
    }

    #[inline]
    pub fn values(&self) -> impl Iterator<Item = &Parents<K>> {
        self.0.values()
    }

    #[inline]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    #[inline]
    pub fn remove(&mut self, k: &K) -> Option<Parents<K>> {
        self.0.remove(k)
    }

    #[inline]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    #[inline]
    pub fn extend(&mut self, other: ParentMap<K>) {
        self.0.extend(other.0);
    }
}

impl<K: Hash + Clone + PartialEq + Eq> Default for ParentMap<K> {
    fn default() -> Self {
        Self::new()
    }
}

impl<K: Hash + Clone + PartialEq + Eq> From<ParentMap<K>> for HashMap<K, Vec<K>> {
    fn from(map: ParentMap<K>) -> Self {
        map.0
            .into_iter()
            .map(|(k, v)| (k, v.unwrap()))
            .collect::<HashMap<K, Vec<K>>>()
    }
}

impl<K: Hash + Clone + PartialEq + Eq> From<HashMap<K, Vec<K>>> for ParentMap<K> {
    fn from(map: HashMap<K, Vec<K>>) -> Self {
        ParentMap(
            map.into_iter()
                .map(|(k, v)| (k, Parents::Known(v)))
                .collect::<HashMap<K, Parents<K>>>(),
        )
    }
}

impl<K: Hash + Clone + PartialEq + Eq> IntoIterator for ParentMap<K> {
    type Item = (K, Parents<K>);
    type IntoIter = std::collections::hash_map::IntoIter<K, Parents<K>>;

    fn into_iter(self) -> Self::IntoIter {
        self.0.into_iter()
    }
}

#[cfg(feature = "pyo3")]
impl<'py, K: pyo3::IntoPyObject<'py, Error = pyo3::PyErr> + Hash + Clone + PartialEq + Eq>
    pyo3::IntoPyObject<'py> for ParentMap<K>
{
    type Target = pyo3::types::PyDict;

    type Output = pyo3::Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: pyo3::Python<'py>) -> Result<Self::Output, Self::Error> {
        use pyo3::prelude::*;
        let dict = pyo3::types::PyDict::new(py);
        for (k, v) in self.into_iter() {
            dict.set_item(k, v)?;
        }
        Ok(dict)
    }
}

#[cfg(feature = "pyo3")]
impl<'a, K: pyo3::FromPyObject<'a> + Hash + Clone + PartialEq + Eq + 'a> pyo3::FromPyObject<'a>
    for ParentMap<K>
where
    K: 'a,
{
    fn extract_bound(obj: &pyo3::Bound<'a, pyo3::PyAny>) -> pyo3::PyResult<Self> {
        use pyo3::prelude::*;
        let dict = obj.downcast::<pyo3::types::PyDict>()?;
        let mut result = ParentMap::new();
        for (k, v) in dict.iter() {
            let k = k.extract::<K>()?;
            let v = v.extract::<Parents<K>>()?;
            result.insert(k, v);
        }
        Ok(result)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChildMap<K: PartialEq + Eq + Hash>(HashMap<K, Vec<K>>);

impl<K: Clone + Hash + PartialEq + Eq> ChildMap<K> {
    pub fn new() -> Self {
        ChildMap(HashMap::new())
    }

    #[inline]
    pub fn insert(&mut self, k: K) {
        self.0.entry(k).or_insert_with(Vec::new);
    }

    #[inline]
    pub fn drain(&mut self) -> impl Iterator<Item = (K, Vec<K>)> + '_ {
        self.0.drain()
    }

    #[inline]
    pub fn add(&mut self, k: K, v: K) {
        self.0.entry(k).or_insert_with(Vec::new).push(v);
    }

    #[inline]
    pub fn iter(&self) -> impl Iterator<Item = (&K, &Vec<K>)> {
        self.0.iter()
    }

    #[inline]
    pub fn get(&self, k: &K) -> Option<&Vec<K>> {
        self.0.get(k)
    }

    #[inline]
    pub fn remove(&mut self, k: &K) -> Option<Vec<K>> {
        self.0.remove(k)
    }

    #[inline]
    pub fn into_iter(self) -> impl Iterator<Item = (K, Vec<K>)> {
        self.0.into_iter()
    }

    #[inline]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    #[inline]
    pub fn contains_key(&self, k: &K) -> bool {
        self.0.contains_key(k)
    }
}

impl<K: Hash + Clone + Eq> std::ops::Index<&K> for ChildMap<K> {
    type Output = Vec<K>;

    fn index(&self, index: &K) -> &Self::Output {
        &self.0[index]
    }
}

#[cfg(feature = "pyo3")]
impl<'py, K: pyo3::IntoPyObject<'py> + Hash + Clone + PartialEq + Eq> pyo3::IntoPyObject<'py>
    for ChildMap<K>
{
    type Target = pyo3::types::PyDict;

    type Output = pyo3::Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: pyo3::Python<'py>) -> Result<Self::Output, Self::Error> {
        use pyo3::prelude::*;
        let dict = pyo3::types::PyDict::new(py);
        for (k, v) in self.into_iter() {
            dict.set_item(k, v)?;
        }
        Ok(dict)
    }
}

impl<K: Hash + Clone + Eq> From<HashMap<K, Vec<K>>> for ChildMap<K> {
    fn from(map: HashMap<K, Vec<K>>) -> Self {
        ChildMap(map)
    }
}

/// Create a child map from a parent map.
pub fn invert_parent_map<K: Hash + Eq + Clone>(parent_map: &ParentMap<K>) -> ChildMap<K> {
    let mut child_map = ChildMap::new();
    for (child, parents) in parent_map.iter() {
        if parents.is_ghost() {
            continue;
        }
        for p in parents.unwrap().iter() {
            child_map.add(p.clone(), child.clone());
        }
    }
    child_map
}

impl<K> From<ParentMap<K>> for ChildMap<K>
where
    K: Hash + Eq + Clone,
{
    fn from(parent_map: ParentMap<K>) -> Self {
        invert_parent_map(&parent_map)
    }
}

#[cfg(test)]
mod invert_parent_map_tests {
    use super::*;
    use maplit::hashmap;
    #[test]
    fn test_invert() {
        assert_eq!(
            ChildMap::from(hashmap! {
                1 => vec![2, 3],
                2 => vec![3],
                3 => vec![],
            }),
            super::invert_parent_map(&ParentMap::from(hashmap! {
                2 => vec![1],
                3 => vec![1, 2],
            }))
        );
    }

    #[test]
    fn test_ghost() {
        assert_eq!(
            ChildMap::from(hashmap! {
                1 => vec![2, 3],
                2 => vec![3],
            }),
            super::invert_parent_map(&ParentMap::from(hashmap! {
                2 => vec![1],
                3 => vec![1, 2],
            }))
        );
    }
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
/// Args:
///   parent_map: A dictionary mapping children to their parents
/// Returns: Another dictionary with 'linear' chains collapsed
pub fn collapse_linear_regions<K: Hash + Eq + Clone>(parent_map: &ParentMap<K>) -> ParentMap<K> {
    // Note: this isn't a strictly minimal collapse. For example:
    //   A
    //  / \
    // B   C
    //  \ /
    //   D
    //   |
    //   E
    // Will not have 'D' removed, even though 'E' could fit. Also:
    //   A
    //   |    A
    //   B => |
    //   |    C
    //   C
    // A and C are both kept because they are edges of the graph. We *could* get
    // rid of A if we wanted.
    //   A
    //  / \
    // B   C
    // |   |
    // D   E
    //  \ /
    //   F
    // Will not have any nodes removed, even though you do have an
    // 'uninteresting' linear D->B and E->C
    let mut children: HashMap<K, Vec<K>> = HashMap::new();
    for (child, parents) in parent_map.iter() {
        children.entry(child.clone()).or_default();
        for p in parents.unwrap().iter() {
            children.entry(p.clone()).or_default().push(child.clone());
        }
    }

    let mut removed = HashSet::new();
    let mut result: ParentMap<K> = parent_map.clone();
    for node in parent_map.keys() {
        let node = node.borrow();
        let parents = result.get(node).unwrap().unwrap();
        if parents.len() == 1 {
            let parent_children = children.get(&parents[0]).unwrap();
            if parent_children.len() != 1 {
                // This is not the only child
                continue;
            }
            let node_children = children.get(node).unwrap();
            if node_children.len() != 1 {
                continue;
            }
            if let Some(child_parents) = result.get(&node_children[0]) {
                if child_parents.unwrap().len() != 1 {
                    // This is not its only parent
                    continue;
                }
                // The child of this node only points at it, and the parent only has
                // this as a child. remove this node, and join the others together
                let parents = parents.clone();
                result.remove(node);
                result.insert(node_children[0].clone(), Parents::Known(parents.clone()));
                children.insert(parents[0].clone(), node_children.clone());
                children.remove(node);
                removed.insert(node);
            }
        }
    }

    result
}

pub mod tsort;

#[cfg(test)]
mod test;

#[derive(Clone, PartialEq, Eq)]
pub struct RevnoVec(Vec<usize>);

impl RevnoVec {
    pub fn new() -> Self {
        RevnoVec(vec![])
    }

    pub fn bump_last(&self) -> Self {
        let mut ret = self.clone();
        let last_index = ret.0.len() - 1;
        ret.0[last_index] += 1;
        ret
    }

    pub fn new_branch(&self, branch_count: usize) -> Self {
        RevnoVec::from(vec![self[0], branch_count, 1])
    }
}

impl Default for RevnoVec {
    fn default() -> Self {
        Self::new()
    }
}

impl IntoIterator for RevnoVec {
    type Item = usize;
    type IntoIter = std::vec::IntoIter<usize>;

    fn into_iter(self) -> Self::IntoIter {
        self.0.into_iter()
    }
}

impl std::ops::Index<usize> for RevnoVec {
    type Output = usize;

    fn index(&self, index: usize) -> &Self::Output {
        &self.0[index]
    }
}

impl std::ops::IndexMut<usize> for RevnoVec {
    fn index_mut(&mut self, index: usize) -> &mut Self::Output {
        &mut self.0[index]
    }
}

impl std::fmt::Debug for RevnoVec {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "RevnoVec({:?})", self.0)
    }
}

impl std::fmt::Display for RevnoVec {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        let mut first = true;
        for r in self.0.iter() {
            if first {
                first = false;
            } else {
                write!(f, ".")?;
            }
            write!(f, "{}", r)?;
        }
        Ok(())
    }
}

impl From<Vec<usize>> for RevnoVec {
    fn from(v: Vec<usize>) -> Self {
        RevnoVec(v)
    }
}

impl From<usize> for RevnoVec {
    fn from(v: usize) -> Self {
        RevnoVec(vec![v])
    }
}

#[cfg(feature = "pyo3")]
impl<'py> pyo3::IntoPyObject<'py> for RevnoVec {
    type Target = pyo3::types::PyTuple;

    type Output = pyo3::Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: pyo3::Python<'py>) -> Result<Self::Output, Self::Error> {
        pyo3::types::PyTuple::new(py, self.0.iter())
    }
}

#[cfg(feature = "pyo3")]
impl<'source> pyo3::FromPyObject<'source> for RevnoVec {
    fn extract_bound(ob: &pyo3::Bound<'source, pyo3::PyAny>) -> pyo3::PyResult<Self> {
        use pyo3::prelude::*;
        let tuple = ob.downcast::<pyo3::types::PyTuple>()?;
        let mut ret = RevnoVec::new();
        for r in tuple.iter() {
            ret.0.push(r.extract()?);
        }
        Ok(ret)
    }
}

#[derive(std::fmt::Debug)]
pub enum Error<K> {
    Cycle(Vec<K>),
    ParentMismatch {
        key: K,
        expected: Vec<K>,
        actual: Vec<K>,
    },
}

impl<K: std::fmt::Display> std::fmt::Display for Error<K> {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Error::Cycle(cycle) => {
                write!(f, "Cycle: ")?;
                let mut first = true;
                for c in cycle.iter() {
                    if first {
                        first = false;
                    } else {
                        write!(f, " -> ")?;
                    }
                    write!(f, "{}", c)?;
                }
                Ok(())
            }
            Error::ParentMismatch {
                key,
                expected,
                actual,
            } => {
                write!(f, "Parent mismatch for {}: ", key)?;
                let mut first = true;
                for e in expected.iter() {
                    if first {
                        first = false;
                    } else {
                        write!(f, ", ")?;
                    }
                    write!(f, "{}", e)?;
                }
                write!(f, " != ")?;
                let mut first = true;
                for a in actual.iter() {
                    if first {
                        first = false;
                    } else {
                        write!(f, ", ")?;
                    }
                    write!(f, "{}", a)?;
                }
                Ok(())
            }
        }
    }
}

impl<K: std::fmt::Debug + std::fmt::Display> std::error::Error for Error<K> {}
