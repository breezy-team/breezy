#![allow(clippy::if_same_then_else)]
use crate::{Error, RevnoVec};
use std::collections::{HashMap, HashSet};
use std::hash::Hash;

#[derive(Debug)]
pub struct TopoSorter<K: Eq + Hash> {
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

impl<K: Eq + Hash + std::fmt::Debug + Clone> TopoSorter<K> {
    /// Create a new `TopoSorter` from a graph represented as a sequence of pairs
    /// of node_name->parent_names_list.
    pub fn new(graph: impl Iterator<Item = (K, Vec<K>)>) -> TopoSorter<K> {
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
        self.iter_topo_order()
            .collect::<std::result::Result<Vec<K>, Error<K>>>()
    }

    /// Yield the nodes of the graph in a topological order.
    ///
    /// After finishing iteration the sorter is empty and you cannot continue
    /// iteration.
    pub fn iter_topo_order(
        &mut self,
    ) -> impl Iterator<Item = std::result::Result<K, Error<K>>> + '_ {
        self
    }
}

impl<K: Eq + Hash + std::fmt::Debug + Clone> Iterator for TopoSorter<K> {
    type Item = std::result::Result<K, Error<K>>;
    fn next(&mut self) -> Option<std::result::Result<K, Error<K>>> {
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

/// Merge-aware topological sorting of a graph.
///
/// :param graph: sequence of pairs of node_name->parent_names_list.
///               i.e. [('C', ['B']), ('B', ['A']), ('A', [])]
///               For this input the output from the sort or
///               iter_topo_order routines will be:
///               'A', 'B', 'C'
/// :param branch_tip: the tip of the branch to graph. Revisions not
///                reachable from branch_tip are not included in the
///                output.
/// :param mainline_revisions: If not None this forces a mainline to be
///                        used rather than synthesised from the graph.
///                        This must be a valid path through some part
///                        of the graph. If the mainline does not cover all
///                        the revisions, output stops at the start of the
///                        old revision listed in the mainline revisions
///                        list.
///                        The order for this parameter is oldest-first.
/// :param generate_revno: Optional parameter controlling the generation of
///     revision number sequences in the output. See the output description
///     for more details.
///
/// The result is a list sorted so that all parents come before
/// their children. Each element of the list is a tuple containing:
/// (sequence_number, node_name, merge_depth, end_of_merge)
///  * sequence_number: The sequence of this row in the output. Useful for
///    GUIs.
///  * node_name: The node name: opaque text to the merge routine.
///  * merge_depth: How many levels of merging deep this node has been
///    found.
///  * revno_sequence: When requested this field provides a sequence of
///      revision numbers for all revisions. The format is:
///      (REVNO, BRANCHNUM, BRANCHREVNO). BRANCHNUM is the number of the
///      branch that the revno is on. From left to right the REVNO numbers
///      are the sequence numbers within that branch of the revision.
///      For instance, the graph {A:[], B:['A'], C:['A', 'B']} will get
///      the following revno_sequences assigned: A:(1,), B:(1,1,1), C:(2,).
///      This should be read as 'A is the first commit in the trunk',
///      'B is the first commit on the first branch made from A', 'C is the
///      second commit in the trunk'.
///  * end_of_merge: When True the next node is part of a different merge.
///
///
/// node identifiers can be any hashable object, and are typically strings.
///
/// If you have a graph like [('a', ['b']), ('a', ['c'])] this will only use
/// one of the two values for 'a'.
///
/// The graph is sorted lazily: until you iterate or sort the input is
/// not processed other than to create an internal representation.
///
/// iteration or sorting may raise GraphCycleError if a cycle is present
/// in the graph.
///
/// Background information on the design:
/// -------------------------------------
/// definition: the end of any cluster or 'merge' occurs when:
///     1 - the next revision has a lower merge depth than we do.
///       i.e.
///       A 0
///       B  1
///       C   2
///       D  1
///       E 0
///       C, D are the ends of clusters, E might be but we need more data.
///     2 - or the next revision at our merge depth is not our left most
///       ancestor.
///       This is required to handle multiple-merges in one commit.
///       i.e.
///       A 0    [F, B, E]
///       B  1   [D, C]
///       C   2  [D]
///       D  1   [F]
///       E  1   [F]
///       F 0
///       C is the end of a cluster due to rule 1.
///       D is not the end of a cluster from rule 1, but is from rule 2: E
///         is not its left most ancestor
///       E is the end of a cluster due to rule 1
///       F might be but we need more data.
///
/// we show connecting lines to a parent when:
///  - The parent is the start of a merge within this cluster.
///    That is, the merge was not done to the mainline before this cluster
///    was merged to the mainline.
///    This can be detected thus:
///     * The parent has a higher merge depth and is the next revision in
///       the list.
///
///   The next revision in the list constraint is needed for this case:
///   A 0   [D, B]
///   B  1  [C, F]   # we do not want to show a line to F which is depth 2
///                    but not a merge
///   C  1  [H]      # note that this is a long line to show back to the
///                    ancestor - see the end of merge rules.
///   D 0   [G, E]
///   E  1  [G, F]
///   F   2 [G]
///   G  1  [H]
///   H 0
///  - Part of this merges 'branch':
///   The parent has the same merge depth and is our left most parent and we
///    are not the end of the cluster.
///   A 0   [C, B] lines: [B, C]
///   B  1  [E, C] lines: [C]
///   C 0   [D]    lines: [D]
///   D 0   [F, E] lines: [E, F]
///   E  1  [F]    lines: [F]
///   F 0
///  - The end of this merge/cluster:
///   we can ONLY have multiple parents at the end of a cluster if this
///   branch was previously merged into the 'mainline'.
///   - if we have one and only one parent, show it
///     Note that this may be to a greater merge depth - for instance if
///     this branch continued from a deeply nested branch to add something
///     to it.
///   - if we have more than one parent - show the second oldest (older ==
///     further down the list) parent with
///     an equal or lower merge depth
///      XXXX revisit when awake. ddaa asks about the relevance of each one
///      - maybe more than one parent is relevant
pub struct MergeSorter<K> {
    // this is a stack storing the depth first search into the graph.
    node_name_stack: Vec<K>,
    // at each level of recursion we need the merge depth this node is at:
    node_merge_depth_stack: Vec<usize>,
    // at each level of 'recursion' we have to check each parent. This
    // stack stores the parents we have not yet checked for the node at the
    // matching depth in _node_name_stack
    pending_parents_stack: Vec<Vec<K>>,
    // When we first look at a node we assign it a seqence number from its
    // leftmost parent.
    first_child_stack: Vec<Option<bool>>,
    // This records for each node when we have processed its left most
    // unmerged subtree. After this subtree is scheduled, all other subtrees
    // have their merge depth increased by one from this nodes merge depth.
    // it contains tuples - name, merge_depth
    left_subtree_pushed_stack: Vec<bool>,
    generate_revno: bool,
    graph: HashMap<K, Vec<K>>,
    stop_revision: Option<K>,
    original_graph: HashMap<K, Vec<K>>,
    revnos: HashMap<K, (Option<RevnoVec>, bool)>,
    // Each mainline revision counts how many child branches have spawned from it.
    revno_to_branch_count: HashMap<usize, usize>,
    // this is a set of the nodes who have been completely analysed for fast
    // membership checking
    completed_node_names: HashSet<K>,
    // this is the scheduling of nodes list.
    // Nodes are scheduled
    // from the bottom left of the tree: in the tree
    // A 0  [D, B]
    // B  1 [C]
    // C  1 [D]
    // D 0  [F, E]
    // E  1 [F]
    // F 0
    // the scheduling order is: F, E, D, C, B, A
    // that is - 'left subtree, right subtree, node'
    // which would mean that when we schedule A we can emit the entire tree.
    scheduled_nodes: Vec<(K, usize, RevnoVec)>,
    sequence_number: usize,
}

impl<K: Eq + Hash + Clone + std::fmt::Debug> MergeSorter<K> {
    pub fn new(
        mut graph: HashMap<K, Vec<K>>,
        branch_tip: Option<K>,
        mainline_revisions: Option<Vec<K>>,
        generate_revno: bool,
    ) -> Self {
        let stop_revision;

        // if there is an explicit mainline, alter the graph to match. This is
        // easier than checking at every merge whether we are on the mainline and
        // if so which path to take.
        if let Some(mainline_revisions) = mainline_revisions.as_ref() {
            stop_revision = Some(mainline_revisions[0].clone());

            // skip the first revision, its what we reach and its parents are
            // therefore irrelevant
            for (index, revision) in mainline_revisions[1..].iter().enumerate() {
                // NB: index 0 means self._mainline_revisions[1]
                // if the mainline matches the graph, nothing to do.
                let parent = &mainline_revisions[index];
                let graph_parent_ids = graph.get_mut(revision).unwrap();
                if !graph_parent_ids.is_empty() {
                    if graph_parent_ids[0] == *parent {
                        continue;
                    }
                    let current_position =
                        graph_parent_ids.iter().position(|x| x == parent).unwrap();
                    graph_parent_ids.swap(0, current_position);
                } else {
                    // We ran into a ghost, skip over it, this is a workaround for
                    // bug #243536, the _graph has had ghosts stripped, but the
                    // mainline_revisions have not
                    continue;
                }
            }
        } else {
            stop_revision = None;
        }

        // we need to do a check late in the process to detect end-of-merges
        // which requires the parents to be accessible: its easier for now
        // to just keep the original graph around.
        let original_graph = graph.clone();

        // we need to know the revision numbers of revisions to determine
        // the revision numbers of their descendants
        // this is a graph from node to [revno_tuple, first_child]
        // where first_child is True if no other children have seen this node
        // and revno_tuple is the tuple that was assigned to the node.
        // we dont know revnos to start with, so we start it seeded with
        // [None, True]
        let revnos = graph
            .keys()
            .map(|revision| (revision.clone(), (None, true)))
            .collect::<HashMap<K, (Option<RevnoVec>, bool)>>();

        let mut sorter = MergeSorter {
            generate_revno,
            graph,
            stop_revision,
            original_graph,
            revnos,
            revno_to_branch_count: HashMap::new(),
            node_name_stack: Vec::new(),
            node_merge_depth_stack: Vec::new(),
            pending_parents_stack: Vec::new(),
            first_child_stack: Vec::new(),
            completed_node_names: HashSet::new(),
            scheduled_nodes: Vec::new(),
            left_subtree_pushed_stack: Vec::new(),
            sequence_number: 0,
        };

        if let Some(branch_tip) = branch_tip {
            let parents = sorter.graph.remove(&branch_tip);
            sorter.push_node(branch_tip, 0, parents.unwrap());
        }
        sorter
    }

    /// Sort the graph and return as a list.
    ///
    /// After calling this the sorter is empty and you must create a new one.
    pub fn sorted(
        &mut self,
    ) -> std::result::Result<Vec<(usize, K, usize, Option<RevnoVec>, bool)>, Error<K>> {
        self.iter_topo_order().collect()
    }

    ///
    /// After finishing iteration the sorter is empty and you cannot continue
    /// iteration.
    pub fn iter_topo_order(
        &mut self,
    ) -> impl Iterator<Item = std::result::Result<(usize, K, usize, Option<RevnoVec>, bool), Error<K>>>
           + '_ {
        self
    }

    /// Add node_name to the pending node stack.
    ///
    /// Names in this stack will get emitted into the output as they are popped
    /// off the stack.
    pub fn push_node(&mut self, node_name: K, merge_depth: usize, parents: Vec<K>) {
        self.node_name_stack.push(node_name);
        self.node_merge_depth_stack.push(merge_depth);
        self.left_subtree_pushed_stack.push(false);

        // As we push it, figure out if this is the first child
        let first_child: Option<bool>;
        if !parents.is_empty() {
            // Node has parents, assign from the left most parent.
            if let Some(entry) = self.revnos.get_mut(&parents[0]) {
                first_child = Some(entry.1);
                entry.1 = false;
            } else {
                // Left-hand parent is a ghost, consider it not to exist
                first_child = None;
            }
        } else {
            first_child = None;
        }
        self.pending_parents_stack.push(parents);
        self.first_child_stack.push(first_child);
    }

    pub fn pop_node(&mut self) -> K {
        // Pop the top node off the stack
        //
        // The node is appended to the sorted output.
        let node_name = self.node_name_stack.pop().unwrap();
        let merge_depth = self.node_merge_depth_stack.pop().unwrap();
        let first_child = self.first_child_stack.pop().unwrap();
        // remove this node from the pending lists:
        self.left_subtree_pushed_stack.pop().unwrap();
        self.pending_parents_stack.pop().unwrap();

        let parents = self.original_graph.get(&node_name).unwrap();
        let mut parent_revno = None;
        if !parents.is_empty() {
            // node has parents, assign from the left most parent.
            parent_revno = if let Some(entry) = self.revnos.get(&parents[0]) {
                entry.0.clone()
            } else {
                // Left-hand parent is a ghost, consider it not to exist
                None
            };
        }
        let revno: RevnoVec = if let Some(parent_revno) = parent_revno {
            if first_child.is_none() || !first_child.unwrap() {
                // not the first child, make a new branch
                let base_revno = parent_revno[0];
                let mut branch_count = *self.revno_to_branch_count.get(&base_revno).unwrap_or(&0);
                branch_count += 1;
                self.revno_to_branch_count.insert(base_revno, branch_count);
                parent_revno.new_branch(branch_count)
            } else {
                // as the first child, we just increase the final revision
                // number
                parent_revno.bump_last()
            }
        } else {
            // no parents, use the root sequence
            let root_count = if let Some(root_count) = self.revno_to_branch_count.get(&0) {
                root_count + 1
            } else {
                0
            };
            self.revno_to_branch_count.insert(0, root_count);
            if root_count > 0 {
                RevnoVec::from(vec![0, root_count, 1])
            } else {
                RevnoVec::from(1)
            }
        };

        // store the revno for this node for future reference
        self.revnos
            .entry(node_name.clone())
            .and_modify(|e| e.0 = Some(revno.clone()));
        self.completed_node_names.insert(node_name.clone());
        self.scheduled_nodes
            .push((node_name.clone(), merge_depth, revno));
        node_name
    }

    fn build(&mut self) -> std::result::Result<(), Error<K>> {
        while !self.node_name_stack.is_empty() {
            let parents_to_visit = self.pending_parents_stack.last().unwrap();
            if parents_to_visit.is_empty() {
                self.pop_node();
            } else {
                while !self.pending_parents_stack.last().unwrap().is_empty() {
                    let is_left_subtree;
                    let next_node_name;
                    if !self.left_subtree_pushed_stack.last().unwrap() {
                        next_node_name = self.pending_parents_stack.last_mut().unwrap().remove(0);
                        is_left_subtree = true;
                        *self.left_subtree_pushed_stack.last_mut().unwrap() = true;
                        // recurse depth first into the primary parent
                    } else {
                        next_node_name = self
                            .pending_parents_stack
                            .last_mut()
                            .unwrap()
                            .pop()
                            .unwrap();
                        is_left_subtree = false;
                        // place any merges in right-to-left order for scheduling
                        // which gives us left-to-right order after we reverse
                        // the scheduled queue. XXX: This has the effect of
                        // allocating common-new revisions to the right-most
                        // subtree rather than the left most, which will
                        // display nicely (you get smaller trees at the top
                        // of the combined merge).
                    }
                    if self.completed_node_names.contains(&next_node_name) {
                        // this parent was completed by a child on the
                        // call stack. skip it.
                        continue;
                    }

                    // otherwise transfer it from the source graph into the
                    // top of the current depth first search stack.
                    let parents = match self.graph.remove(&next_node_name) {
                        Some(parents) => parents,
                        None => {
                            // if the next node is not in the source graph it has
                            // already been popped from it and placed into the
                            // current search stack (but not completed or we would
                            // have hit the continue 4 lines up.
                            // this indicates a cycle.
                            if self.original_graph.contains_key(&next_node_name) {
                                return Err(Error::Cycle(self.node_name_stack.clone()));
                            } else {
                                // This is just a ghost parent, ignore it
                                continue;
                            }
                        }
                    };
                    let next_merge_depth =
                        usize::from(!is_left_subtree) + self.node_merge_depth_stack.last().unwrap();
                    self.push_node(next_node_name, next_merge_depth, parents);
                    // and do not continue processing parents until this 'call'
                    // has recursed.
                    break;
                }
            }
        }
        Ok(())
    }
}

impl<K: Eq + Hash + std::fmt::Debug + Clone> Iterator for MergeSorter<K> {
    type Item = std::result::Result<(usize, K, usize, Option<RevnoVec>, bool), Error<K>>;
    fn next(
        &mut self,
    ) -> Option<std::result::Result<(usize, K, usize, Option<RevnoVec>, bool), Error<K>>> {
        if let Err(err) = self.build() {
            return Some(Err(err));
        }
        if let Some((node_name, merge_depth, revno)) = self.scheduled_nodes.pop() {
            if self.stop_revision.is_some() && &node_name == self.stop_revision.as_ref().unwrap() {
                return None;
            }
            let end_of_merge: bool;
            if self.scheduled_nodes.is_empty() {
                // last revision is the end of a merge
                end_of_merge = true;
            } else if self.scheduled_nodes.last().unwrap().1 < merge_depth {
                // the next node is to our left
                end_of_merge = true;
            } else if self.scheduled_nodes.last().unwrap().1 == merge_depth
                && !self
                    .original_graph
                    .get(&node_name)
                    .unwrap()
                    .contains(&self.scheduled_nodes.last().unwrap().0)
            {
                // the next node was part of a multiple-merge.
                end_of_merge = true;
            } else {
                end_of_merge = false;
            }
            let result = if self.generate_revno {
                (
                    self.sequence_number,
                    node_name,
                    merge_depth,
                    Some(revno),
                    end_of_merge,
                )
            } else {
                (
                    self.sequence_number,
                    node_name,
                    merge_depth,
                    None,
                    end_of_merge,
                )
            };
            self.sequence_number += 1;
            Some(Ok(result))
        } else {
            None
        }
    }
}

pub fn merge_sort<K: Eq + Hash + std::fmt::Debug + Clone>(
    graph: HashMap<K, Vec<K>>,
    branch_tip: Option<K>,
    mainline_revisions: Option<Vec<K>>,
    generate_revno: bool,
) -> std::result::Result<Vec<(usize, K, usize, Option<RevnoVec>, bool)>, Error<K>> {
    MergeSorter::new(graph, branch_tip, mainline_revisions, generate_revno).sorted()
}
