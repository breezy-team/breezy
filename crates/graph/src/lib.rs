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

use std::collections::{HashMap,HashSet};
use std::hash::Hash;
use std::borrow::Borrow;

pub type ParentMap<'a, K> = HashMap<&'a K, &'a Vec<K>>;

pub fn invert_parent_map<'a, K: Hash + Eq>(parent_map: &'a HashMap<impl Borrow<K>, Vec<impl Borrow<K>>>) -> HashMap<&'a K, Vec<&'a K>> {
    let mut child_map: HashMap<&'a K, Vec<&'a K>> = HashMap::new();
    for (child, parents) in parent_map.iter() {
        for p in parents.iter() {
            child_map.entry(p.borrow()).or_insert_with(Vec::new).push(child.borrow());
        }
    }
    child_map
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
/// REturns: Another dictionary with 'linear' chains collapsed
pub fn collapse_linear_regions<'a, K: Hash + Eq + std::fmt::Debug>(
    parent_map: &'a HashMap<impl Borrow<K>, Vec<impl Borrow<K>>>,
) -> HashMap<&'a K, Vec<&'a K>> {
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
    let mut children: HashMap<&K, Vec<&K>> = HashMap::new();
    for (child, parents) in parent_map.iter() {
        children.entry(child.borrow()).or_insert(Vec::new());
        for p in parents.iter() {
            children.entry(p.borrow()).or_insert(Vec::new()).push(child.borrow());
        }
    }

    let mut removed = HashSet::new();
    let mut result: HashMap<&K, Vec<&K>> = parent_map.iter().map(|(k, v)| (k.borrow(), v.iter().map(|x| x.borrow()).collect())).collect();
    for node in parent_map.keys() {
        let node = node.borrow();
        let parents = result.entry(node);
        if parents.len() == 1 {
            let parent_children = children.get(parents[0]).unwrap();
            if parent_children.len() != 1 {
                // This is not the only child
                continue;
            }
            let node_children = children.get(node).unwrap();
            if node_children.len() != 1 {
                continue;
            }
            if let Some(child_parents) = result.get(&node_children[0]) {
                if child_parents.len() != 1 {
                    // This is not its only parent
                    continue;
                }
                // The child of this node only points at it, and the parent only has
                // this as a child. remove this node, and join the others together
                result.remove(node);
                result.insert(node_children[0], parents.clone());
                children.insert(parents[0], node_children.clone());
                children.remove(node);
                removed.insert(node);
            }
        }
    }

    result
}

#[cfg(test)]
mod tests;
