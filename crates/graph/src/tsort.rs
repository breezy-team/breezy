use std::collections::{HashMap, HashSet};

#[derive(Debug)]
pub enum Error<K> {
    Cycle(Vec<K>),
}

type Result<K> = std::result::Result<K, Error<K>>;

#[derive(Debug)]
pub struct TopoSorter<K: Eq + std::hash::Hash> {
    graph: HashMap<K, Vec<K>>,

    visitable: HashSet<K>,

    // this is a stack storing the depth first search into the graph.
    pending_node_stack: Vec<K>,

    // at each level of 'recursion' we have to check each parent. This
    // stack stores the parents we have not yet checked for the node at the
    // matching depth in pending_node_stack
    pending_parents_stack: Vec<Vec<K>>,

    // this is a set of the completed nodes for fast checking whether a
    // parent in a node we are processing on the stack has already been
    // emitted and thus can be skipped.
    completed_node_names: HashSet<K>,
}

impl<K: Eq + std::hash::Hash + std::fmt::Debug + Clone> TopoSorter<K> {
    /// Create a new `TopoSorter` from a graph represented as a sequence of pairs
    /// of node_name->parent_names_list.
    pub fn new(graph: impl Iterator<Item = (K, Vec<K>)>) -> TopoSorter<K>
    {
        let mut g = HashMap::new();
        for (node, parents) in graph {
            g.insert(node, parents.into_iter().collect());
        }
        let visitable = g.keys().cloned().collect();
        TopoSorter {
            graph: g,
            visitable,
            pending_node_stack: vec![],
            pending_parents_stack: vec![],
            completed_node_names: HashSet::new(),
        }
    }

    /// Sort the graph and return the nodes as a vector.
    ///
    /// After calling this the sorter is empty and you must create a new one.
    pub fn sorted(&mut self) -> std::result::Result<Vec<K>, Error<K>> {
        self.iter_topo_order().collect::<std::result::Result<Vec<K>, Error<K>>>()
    }

    /// Yield the nodes of the graph in a topological order.
    ///
    /// After finishing iteration the sorter is empty and you cannot continue
    /// iteration.
    pub fn iter_topo_order(&mut self) -> impl Iterator<Item = Result<K>> + '_ {
        self
    }
}

impl<K: Eq + std::hash::Hash + std::fmt::Debug + Clone> Iterator for TopoSorter<K> {
    type Item = Result<K>;
    fn next(&mut self) -> Option<Result<K>> {
        loop {
            // loop until pending_node_stack is empty
            while !self.pending_node_stack.is_empty() {
                let parents_to_visit = self.pending_parents_stack.last_mut().unwrap();

                // if there are no parents left, the revision is done
                if parents_to_visit.is_empty() {
                    // append the revision to the topo sorted list
                    // all the nodes parents have been added to the output,
                    // now we can add it to the output.
                    let popped_node = self.pending_node_stack.pop().unwrap();
                    self.pending_parents_stack.pop();
                    self.completed_node_names.insert(popped_node.clone());
                    return Some(Ok(popped_node));
                } else {
                    // recurse depth first into a single parent
                    let next_node_name = parents_to_visit.pop().unwrap();
                    if self.completed_node_names.contains(&next_node_name) {
                        // parent was already completed by a child, skip it.
                        continue;
                    }
                    if !self.visitable.contains(&next_node_name) {
                        // parent is not a node in the original graph, skip it.
                        continue;
                    }

                    // transfer it along with its parents from the source graph
                    // into the top of the current depth first search stack.
                    if let Some(parents) = self.graph.remove(&next_node_name) {
                        self.pending_node_stack.push(next_node_name);
                        self.pending_parents_stack.push(parents);
                    } else {
                        // if the next node is not in the source graph it has
                        // already been popped from it and placed into the
                        // current search stack (but not completed or we would
                        // have hit the continue 6 lines up).  this indicates a
                        // cycle.
                        return Some(Err(Error::Cycle(self.pending_node_stack.to_vec())));
                    }
                }
            }
            if let Some(node_name) = self.graph.keys().next() {
                let node_name = node_name.clone();
                let parents = self.graph.remove(&node_name).unwrap();
                // now pick a random node in the source graph, and transfer it to the
                // top of the depth first search stack of pending nodes.
                self.pending_node_stack.push(node_name);
                self.pending_parents_stack.push(parents);
            } else {
                // if the source graph is empty, we are done.
                return None;
            }
        }
    }
}
