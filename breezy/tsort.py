# Copyright (C) 2005, 2006, 2008 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Topological sorting routines."""


from . import (
    errors,
    graph as _mod_graph,
    revision as _mod_revision,
    )


__all__ = ["topo_sort", "TopoSorter", "merge_sort", "MergeSorter"]


def topo_sort(graph):
    """Topological sort a graph.

    graph -- sequence of pairs of node->parents_list.

    The result is a list of node names, such that all parents come before their
    children.

    node identifiers can be any hashable object, and are typically strings.

    This function has the same purpose as the TopoSorter class, but uses a
    different algorithm to sort the graph. That means that while both return a
    list with parents before their child nodes, the exact ordering can be
    different.

    topo_sort is faster when the whole list is needed, while when iterating
    over a part of the list, TopoSorter.iter_topo_order should be used.
    """
    kg = _mod_graph.KnownGraph(dict(graph))
    return kg.topo_sort()


class TopoSorter(object):

    def __init__(self, graph):
        """Topological sorting of a graph.

        :param graph: sequence of pairs of node_name->parent_names_list.
                      i.e. [('C', ['B']), ('B', ['A']), ('A', [])]
                      For this input the output from the sort or
                      iter_topo_order routines will be:
                      'A', 'B', 'C'

        node identifiers can be any hashable object, and are typically strings.

        If you have a graph like [('a', ['b']), ('a', ['c'])] this will only use
        one of the two values for 'a'.

        The graph is sorted lazily: until you iterate or sort the input is
        not processed other than to create an internal representation.

        iteration or sorting may raise GraphCycleError if a cycle is present
        in the graph.
        """
        # store a dict of the graph.
        self._graph = dict(graph)

    def sorted(self):
        """Sort the graph and return as a list.

        After calling this the sorter is empty and you must create a new one.
        """
        return list(self.iter_topo_order())

# Useful if fiddling with this code.
# cross check
###        sorted_names = list(self.iter_topo_order())
# for index in range(len(sorted_names)):
###            rev = sorted_names[index]
# for left_index in range(index):
# if rev in self.original_graph[sorted_names[left_index]]:
# print "revision in parent list of earlier revision"
###                    import pdb;pdb.set_trace()

    def iter_topo_order(self):
        """Yield the nodes of the graph in a topological order.

        After finishing iteration the sorter is empty and you cannot continue
        iteration.
        """
        graph = self._graph
        visitable = set(graph)

        # this is a stack storing the depth first search into the graph.
        pending_node_stack = []
        # at each level of 'recursion' we have to check each parent. This
        # stack stores the parents we have not yet checked for the node at the
        # matching depth in pending_node_stack
        pending_parents_stack = []

        # this is a set of the completed nodes for fast checking whether a
        # parent in a node we are processing on the stack has already been
        # emitted and thus can be skipped.
        completed_node_names = set()

        while graph:
            # now pick a random node in the source graph, and transfer it to the
            # top of the depth first search stack of pending nodes.
            node_name, parents = graph.popitem()
            pending_node_stack.append(node_name)
            pending_parents_stack.append(list(parents))

            # loop until pending_node_stack is empty
            while pending_node_stack:
                parents_to_visit = pending_parents_stack[-1]
                # if there are no parents left, the revision is done
                if not parents_to_visit:
                    # append the revision to the topo sorted list
                    # all the nodes parents have been added to the output,
                    # now we can add it to the output.
                    popped_node = pending_node_stack.pop()
                    pending_parents_stack.pop()
                    completed_node_names.add(popped_node)
                    yield popped_node
                else:
                    # recurse depth first into a single parent
                    next_node_name = parents_to_visit.pop()

                    if next_node_name in completed_node_names:
                        # parent was already completed by a child, skip it.
                        continue
                    if next_node_name not in visitable:
                        # parent is not a node in the original graph, skip it.
                        continue

                    # transfer it along with its parents from the source graph
                    # into the top of the current depth first search stack.
                    try:
                        parents = graph.pop(next_node_name)
                    except KeyError:
                        # if the next node is not in the source graph it has
                        # already been popped from it and placed into the
                        # current search stack (but not completed or we would
                        # have hit the continue 6 lines up).  this indicates a
                        # cycle.
                        raise errors.GraphCycleError(pending_node_stack)
                    pending_node_stack.append(next_node_name)
                    pending_parents_stack.append(list(parents))


def merge_sort(graph, branch_tip, mainline_revisions=None, generate_revno=False):
    """Topological sort a graph which groups merges.

    :param graph: sequence of pairs of node->parents_list.
    :param branch_tip: the tip of the branch to graph. Revisions not
                       reachable from branch_tip are not included in the
                       output.
    :param mainline_revisions: If not None this forces a mainline to be
                               used rather than synthesised from the graph.
                               This must be a valid path through some part
                               of the graph. If the mainline does not cover all
                               the revisions, output stops at the start of the
                               old revision listed in the mainline revisions
                               list.
                               The order for this parameter is oldest-first.
    :param generate_revno: Optional parameter controlling the generation of
        revision number sequences in the output. See the output description of
        the MergeSorter docstring for details.
    :result: See the MergeSorter docstring for details.

    Node identifiers can be any hashable object, and are typically strings.
    """
    return MergeSorter(graph, branch_tip, mainline_revisions,
                       generate_revno).sorted()


class MergeSorter(object):

    __slots__ = ['_node_name_stack',
                 '_node_merge_depth_stack',
                 '_pending_parents_stack',
                 '_first_child_stack',
                 '_left_subtree_pushed_stack',
                 '_generate_revno',
                 '_graph',
                 '_mainline_revisions',
                 '_stop_revision',
                 '_original_graph',
                 '_revnos',
                 '_revno_to_branch_count',
                 '_completed_node_names',
                 '_scheduled_nodes',
                 ]

    def __init__(self, graph, branch_tip, mainline_revisions=None,
                 generate_revno=False):
        """Merge-aware topological sorting of a graph.

        :param graph: sequence of pairs of node_name->parent_names_list.
                      i.e. [('C', ['B']), ('B', ['A']), ('A', [])]
                      For this input the output from the sort or
                      iter_topo_order routines will be:
                      'A', 'B', 'C'
        :param branch_tip: the tip of the branch to graph. Revisions not
                       reachable from branch_tip are not included in the
                       output.
        :param mainline_revisions: If not None this forces a mainline to be
                               used rather than synthesised from the graph.
                               This must be a valid path through some part
                               of the graph. If the mainline does not cover all
                               the revisions, output stops at the start of the
                               old revision listed in the mainline revisions
                               list.
                               The order for this parameter is oldest-first.
        :param generate_revno: Optional parameter controlling the generation of
            revision number sequences in the output. See the output description
            for more details.

        The result is a list sorted so that all parents come before
        their children. Each element of the list is a tuple containing:
        (sequence_number, node_name, merge_depth, end_of_merge)
         * sequence_number: The sequence of this row in the output. Useful for
           GUIs.
         * node_name: The node name: opaque text to the merge routine.
         * merge_depth: How many levels of merging deep this node has been
           found.
         * revno_sequence: When requested this field provides a sequence of
             revision numbers for all revisions. The format is:
             (REVNO, BRANCHNUM, BRANCHREVNO). BRANCHNUM is the number of the
             branch that the revno is on. From left to right the REVNO numbers
             are the sequence numbers within that branch of the revision.
             For instance, the graph {A:[], B:['A'], C:['A', 'B']} will get
             the following revno_sequences assigned: A:(1,), B:(1,1,1), C:(2,).
             This should be read as 'A is the first commit in the trunk',
             'B is the first commit on the first branch made from A', 'C is the
             second commit in the trunk'.
         * end_of_merge: When True the next node is part of a different merge.


        node identifiers can be any hashable object, and are typically strings.

        If you have a graph like [('a', ['b']), ('a', ['c'])] this will only use
        one of the two values for 'a'.

        The graph is sorted lazily: until you iterate or sort the input is
        not processed other than to create an internal representation.

        iteration or sorting may raise GraphCycleError if a cycle is present
        in the graph.

        Background information on the design:
        -------------------------------------
        definition: the end of any cluster or 'merge' occurs when:
            1 - the next revision has a lower merge depth than we do.
              i.e.
              A 0
              B  1
              C   2
              D  1
              E 0
              C, D are the ends of clusters, E might be but we need more data.
            2 - or the next revision at our merge depth is not our left most
              ancestor.
              This is required to handle multiple-merges in one commit.
              i.e.
              A 0    [F, B, E]
              B  1   [D, C]
              C   2  [D]
              D  1   [F]
              E  1   [F]
              F 0
              C is the end of a cluster due to rule 1.
              D is not the end of a cluster from rule 1, but is from rule 2: E
                is not its left most ancestor
              E is the end of a cluster due to rule 1
              F might be but we need more data.

        we show connecting lines to a parent when:
         - The parent is the start of a merge within this cluster.
           That is, the merge was not done to the mainline before this cluster
           was merged to the mainline.
           This can be detected thus:
            * The parent has a higher merge depth and is the next revision in
              the list.

          The next revision in the list constraint is needed for this case:
          A 0   [D, B]
          B  1  [C, F]   # we do not want to show a line to F which is depth 2
                           but not a merge
          C  1  [H]      # note that this is a long line to show back to the
                           ancestor - see the end of merge rules.
          D 0   [G, E]
          E  1  [G, F]
          F   2 [G]
          G  1  [H]
          H 0
         - Part of this merges 'branch':
          The parent has the same merge depth and is our left most parent and we
           are not the end of the cluster.
          A 0   [C, B] lines: [B, C]
          B  1  [E, C] lines: [C]
          C 0   [D]    lines: [D]
          D 0   [F, E] lines: [E, F]
          E  1  [F]    lines: [F]
          F 0
         - The end of this merge/cluster:
          we can ONLY have multiple parents at the end of a cluster if this
          branch was previously merged into the 'mainline'.
          - if we have one and only one parent, show it
            Note that this may be to a greater merge depth - for instance if
            this branch continued from a deeply nested branch to add something
            to it.
          - if we have more than one parent - show the second oldest (older ==
            further down the list) parent with
            an equal or lower merge depth
             XXXX revisit when awake. ddaa asks about the relevance of each one
             - maybe more than one parent is relevant
        """
        self._generate_revno = generate_revno
        # a dict of the graph.
        self._graph = dict(graph)
        # if there is an explicit mainline, alter the graph to match. This is
        # easier than checking at every merge whether we are on the mainline and
        # if so which path to take.
        if mainline_revisions is None:
            self._mainline_revisions = []
            self._stop_revision = None
        else:
            self._mainline_revisions = list(mainline_revisions)
            self._stop_revision = self._mainline_revisions[0]
        # skip the first revision, its what we reach and its parents are
        # therefore irrelevant
        for index, revision in enumerate(self._mainline_revisions[1:]):
            # NB: index 0 means self._mainline_revisions[1]
            # if the mainline matches the graph, nothing to do.
            parent = self._mainline_revisions[index]
            if parent is None:
                # end of mainline_revisions history
                continue
            graph_parent_ids = self._graph[revision]
            if not graph_parent_ids:
                # We ran into a ghost, skip over it, this is a workaround for
                # bug #243536, the _graph has had ghosts stripped, but the
                # mainline_revisions have not
                continue
            if graph_parent_ids[0] == parent:
                continue
            # remove it from its prior spot
            self._graph[revision].remove(parent)
            # insert it into the start of the mainline
            self._graph[revision].insert(0, parent)
        # we need to do a check late in the process to detect end-of-merges
        # which requires the parents to be accessible: its easier for now
        # to just keep the original graph around.
        self._original_graph = self._graph.copy()
        # we need to know the revision numbers of revisions to determine
        # the revision numbers of their descendants
        # this is a graph from node to [revno_tuple, first_child]
        # where first_child is True if no other children have seen this node
        # and revno_tuple is the tuple that was assigned to the node.
        # we dont know revnos to start with, so we start it seeded with
        # [None, True]
        self._revnos = dict((revision, [None, True])
                            for revision in self._graph)
        # Each mainline revision counts how many child branches have spawned from it.
        self._revno_to_branch_count = {}

        # this is a stack storing the depth first search into the graph.
        self._node_name_stack = []
        # at each level of recursion we need the merge depth this node is at:
        self._node_merge_depth_stack = []
        # at each level of 'recursion' we have to check each parent. This
        # stack stores the parents we have not yet checked for the node at the
        # matching depth in _node_name_stack
        self._pending_parents_stack = []
        # When we first look at a node we assign it a seqence number from its
        # leftmost parent.
        self._first_child_stack = []
        # this is a set of the nodes who have been completely analysed for fast
        # membership checking
        self._completed_node_names = set()
        # this is the scheduling of nodes list.
        # Nodes are scheduled
        # from the bottom left of the tree: in the tree
        # A 0  [D, B]
        # B  1 [C]
        # C  1 [D]
        # D 0  [F, E]
        # E  1 [F]
        # F 0
        # the scheduling order is: F, E, D, C, B, A
        # that is - 'left subtree, right subtree, node'
        # which would mean that when we schedule A we can emit the entire tree.
        self._scheduled_nodes = []
        # This records for each node when we have processed its left most
        # unmerged subtree. After this subtree is scheduled, all other subtrees
        # have their merge depth increased by one from this nodes merge depth.
        # it contains tuples - name, merge_depth
        self._left_subtree_pushed_stack = []

        # seed the search with the tip of the branch
        if (branch_tip is not None
            and branch_tip != _mod_revision.NULL_REVISION
                and branch_tip != (_mod_revision.NULL_REVISION,)):
            parents = self._graph.pop(branch_tip)
            self._push_node(branch_tip, 0, parents)

    def sorted(self):
        """Sort the graph and return as a list.

        After calling this the sorter is empty and you must create a new one.
        """
        return list(self.iter_topo_order())

    def iter_topo_order(self):
        """Yield the nodes of the graph in a topological order.

        After finishing iteration the sorter is empty and you cannot continue
        iteration.
        """
        # These are safe to offload to local variables, because they are used
        # as a stack and modified in place, never assigned to.
        node_name_stack = self._node_name_stack
        node_merge_depth_stack = self._node_merge_depth_stack
        pending_parents_stack = self._pending_parents_stack
        left_subtree_pushed_stack = self._left_subtree_pushed_stack
        completed_node_names = self._completed_node_names
        scheduled_nodes = self._scheduled_nodes

        graph_pop = self._graph.pop

        def push_node(node_name, merge_depth, parents,
                      node_name_stack_append=node_name_stack.append,
                      node_merge_depth_stack_append=node_merge_depth_stack.append,
                      left_subtree_pushed_stack_append=left_subtree_pushed_stack.append,
                      pending_parents_stack_append=pending_parents_stack.append,
                      first_child_stack_append=self._first_child_stack.append,
                      revnos=self._revnos,
                      ):
            """Add node_name to the pending node stack.

            Names in this stack will get emitted into the output as they are popped
            off the stack.

            This inlines a lot of self._variable.append functions as local
            variables.
            """
            node_name_stack_append(node_name)
            node_merge_depth_stack_append(merge_depth)
            left_subtree_pushed_stack_append(False)
            pending_parents_stack_append(list(parents))
            # as we push it, check if it is the first child
            parent_info = None
            if parents:
                # node has parents, assign from the left most parent.
                try:
                    parent_info = revnos[parents[0]]
                except KeyError:
                    # Left-hand parent is a ghost, consider it not to exist
                    pass
            if parent_info is not None:
                first_child = parent_info[1]
                parent_info[1] = False
            else:
                # We don't use the same algorithm here, but we need to keep the
                # stack in line
                first_child = None
            first_child_stack_append(first_child)

        def pop_node(node_name_stack_pop=node_name_stack.pop,
                     node_merge_depth_stack_pop=node_merge_depth_stack.pop,
                     first_child_stack_pop=self._first_child_stack.pop,
                     left_subtree_pushed_stack_pop=left_subtree_pushed_stack.pop,
                     pending_parents_stack_pop=pending_parents_stack.pop,
                     original_graph=self._original_graph,
                     revnos=self._revnos,
                     completed_node_names_add=self._completed_node_names.add,
                     scheduled_nodes_append=scheduled_nodes.append,
                     revno_to_branch_count=self._revno_to_branch_count,
                     ):
            """Pop the top node off the stack

            The node is appended to the sorted output.
            """
            # we are returning from the flattened call frame:
            # pop off the local variables
            node_name = node_name_stack_pop()
            merge_depth = node_merge_depth_stack_pop()
            first_child = first_child_stack_pop()
            # remove this node from the pending lists:
            left_subtree_pushed_stack_pop()
            pending_parents_stack_pop()

            parents = original_graph[node_name]
            parent_revno = None
            if parents:
                # node has parents, assign from the left most parent.
                try:
                    parent_revno = revnos[parents[0]][0]
                except KeyError:
                    # left-hand parent is a ghost, treat it as not existing
                    pass
            if parent_revno is not None:
                if not first_child:
                    # not the first child, make a new branch
                    base_revno = parent_revno[0]
                    branch_count = revno_to_branch_count.get(base_revno, 0)
                    branch_count += 1
                    revno_to_branch_count[base_revno] = branch_count
                    revno = (parent_revno[0], branch_count, 1)
                    # revno = (parent_revno[0], branch_count, parent_revno[-1]+1)
                else:
                    # as the first child, we just increase the final revision
                    # number
                    revno = parent_revno[:-1] + (parent_revno[-1] + 1,)
            else:
                # no parents, use the root sequence
                root_count = revno_to_branch_count.get(0, -1)
                root_count += 1
                if root_count:
                    revno = (0, root_count, 1)
                else:
                    revno = (1,)
                revno_to_branch_count[0] = root_count

            # store the revno for this node for future reference
            revnos[node_name][0] = revno
            completed_node_names_add(node_name)
            scheduled_nodes_append((node_name, merge_depth, revno))
            return node_name

        while node_name_stack:
            # loop until this call completes.
            parents_to_visit = pending_parents_stack[-1]
            # if all parents are done, the revision is done
            if not parents_to_visit:
                # append the revision to the topo sorted scheduled list:
                # all the nodes parents have been scheduled added, now
                # we can add it to the output.
                pop_node()
            else:
                while pending_parents_stack[-1]:
                    if not left_subtree_pushed_stack[-1]:
                        # recurse depth first into the primary parent
                        next_node_name = pending_parents_stack[-1].pop(0)
                        is_left_subtree = True
                        left_subtree_pushed_stack[-1] = True
                    else:
                        # place any merges in right-to-left order for scheduling
                        # which gives us left-to-right order after we reverse
                        # the scheduled queue. XXX: This has the effect of
                        # allocating common-new revisions to the right-most
                        # subtree rather than the left most, which will
                        # display nicely (you get smaller trees at the top
                        # of the combined merge).
                        next_node_name = pending_parents_stack[-1].pop()
                        is_left_subtree = False
                    if next_node_name in completed_node_names:
                        # this parent was completed by a child on the
                        # call stack. skip it.
                        continue
                    # otherwise transfer it from the source graph into the
                    # top of the current depth first search stack.
                    try:
                        parents = graph_pop(next_node_name)
                    except KeyError:
                        # if the next node is not in the source graph it has
                        # already been popped from it and placed into the
                        # current search stack (but not completed or we would
                        # have hit the continue 4 lines up.
                        # this indicates a cycle.
                        if next_node_name in self._original_graph:
                            raise errors.GraphCycleError(node_name_stack)
                        else:
                            # This is just a ghost parent, ignore it
                            continue
                    next_merge_depth = 0
                    if is_left_subtree:
                        # a new child branch from name_stack[-1]
                        next_merge_depth = 0
                    else:
                        next_merge_depth = 1
                    next_merge_depth = (
                        node_merge_depth_stack[-1] + next_merge_depth)
                    push_node(
                        next_node_name,
                        next_merge_depth,
                        parents)
                    # and do not continue processing parents until this 'call'
                    # has recursed.
                    break

        # We have scheduled the graph. Now deliver the ordered output:
        sequence_number = 0
        stop_revision = self._stop_revision
        generate_revno = self._generate_revno
        original_graph = self._original_graph

        while scheduled_nodes:
            node_name, merge_depth, revno = scheduled_nodes.pop()
            if node_name == stop_revision:
                return
            if not len(scheduled_nodes):
                # last revision is the end of a merge
                end_of_merge = True
            elif scheduled_nodes[-1][1] < merge_depth:
                # the next node is to our left
                end_of_merge = True
            elif (scheduled_nodes[-1][1] == merge_depth
                  and (scheduled_nodes[-1][0] not in
                       original_graph[node_name])):
                # the next node was part of a multiple-merge.
                end_of_merge = True
            else:
                end_of_merge = False
            if generate_revno:
                yield (sequence_number, node_name, merge_depth, revno, end_of_merge)
            else:
                yield (sequence_number, node_name, merge_depth, end_of_merge)
            sequence_number += 1

    def _push_node(self, node_name, merge_depth, parents):
        """Add node_name to the pending node stack.

        Names in this stack will get emitted into the output as they are popped
        off the stack.
        """
        self._node_name_stack.append(node_name)
        self._node_merge_depth_stack.append(merge_depth)
        self._left_subtree_pushed_stack.append(False)
        self._pending_parents_stack.append(list(parents))
        # as we push it, figure out if this is the first child
        parent_info = None
        if parents:
            # node has parents, assign from the left most parent.
            try:
                parent_info = self._revnos[parents[0]]
            except KeyError:
                # Left-hand parent is a ghost, consider it not to exist
                pass
        if parent_info is not None:
            first_child = parent_info[1]
            parent_info[1] = False
        else:
            # We don't use the same algorithm here, but we need to keep the
            # stack in line
            first_child = None
        self._first_child_stack.append(first_child)

    def _pop_node(self):
        """Pop the top node off the stack

        The node is appended to the sorted output.
        """
        # we are returning from the flattened call frame:
        # pop off the local variables
        node_name = self._node_name_stack.pop()
        merge_depth = self._node_merge_depth_stack.pop()
        first_child = self._first_child_stack.pop()
        # remove this node from the pending lists:
        self._left_subtree_pushed_stack.pop()
        self._pending_parents_stack.pop()

        parents = self._original_graph[node_name]
        parent_revno = None
        if parents:
            # node has parents, assign from the left most parent.
            try:
                parent_revno = self._revnos[parents[0]][0]
            except KeyError:
                # left-hand parent is a ghost, treat it as not existing
                pass
        if parent_revno is not None:
            if not first_child:
                # not the first child, make a new branch
                base_revno = parent_revno[0]
                branch_count = self._revno_to_branch_count.get(base_revno, 0)
                branch_count += 1
                self._revno_to_branch_count[base_revno] = branch_count
                revno = (parent_revno[0], branch_count, 1)
                # revno = (parent_revno[0], branch_count, parent_revno[-1]+1)
            else:
                # as the first child, we just increase the final revision
                # number
                revno = parent_revno[:-1] + (parent_revno[-1] + 1,)
        else:
            # no parents, use the root sequence
            root_count = self._revno_to_branch_count.get(0, 0)
            root_count = self._revno_to_branch_count.get(0, -1)
            root_count += 1
            if root_count:
                revno = (0, root_count, 1)
            else:
                revno = (1,)
            self._revno_to_branch_count[0] = root_count

        # store the revno for this node for future reference
        self._revnos[node_name][0] = revno
        self._completed_node_names.add(node_name)
        self._scheduled_nodes.append(
            (node_name, merge_depth, self._revnos[node_name][0]))
        return node_name
