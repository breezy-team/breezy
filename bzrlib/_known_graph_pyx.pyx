# Copyright (C) 2009 Canonical Ltd
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

"""Implementation of Graph algorithms when we have already loaded everything.
"""

cdef extern from "python-compat.h":
    pass

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef struct PyObject:
        pass

    object PyTuple_New(Py_ssize_t n)
    Py_ssize_t PyTuple_GET_SIZE(object t)
    PyObject * PyTuple_GET_ITEM(object t, Py_ssize_t o)
    void PyTuple_SET_ITEM(object t, Py_ssize_t o, object v)

    Py_ssize_t PyList_GET_SIZE(object l)
    PyObject * PyList_GET_ITEM(object l, Py_ssize_t o)
    int PyList_SetItem(object l, Py_ssize_t o, object l) except -1
    int PyList_Append(object l, object v) except -1

    int PyDict_CheckExact(object d)
    Py_ssize_t PyDict_Size(object d) except -1
    PyObject * PyDict_GetItem(object d, object k)
    int PyDict_SetItem(object d, object k, object v) except -1
    int PyDict_DelItem(object d, object k) except -1
    int PyDict_Next(object d, Py_ssize_t *pos, PyObject **k, PyObject **v)

    void Py_INCREF(object)


from bzrlib import errors, revision

cdef object NULL_REVISION
NULL_REVISION = revision.NULL_REVISION


cdef class _KnownGraphNode:
    """Represents a single object in the known graph."""

    cdef object key
    cdef object parents
    cdef object children
    cdef public long gdfo
    cdef int seen

    def __init__(self, key):
        cdef int i

        self.key = key
        self.parents = None

        self.children = []
        # Greatest distance from origin
        self.gdfo = -1
        self.seen = 0

    property child_keys:
        def __get__(self):
            cdef _KnownGraphNode child

            keys = []
            for child in self.children:
                PyList_Append(keys, child.key)
            return keys

    cdef clear_references(self):
        self.parents = None
        self.children = None

    def __repr__(self):
        cdef _KnownGraphNode node

        parent_keys = []
        if self.parents is not None:
            for node in self.parents:
                parent_keys.append(node.key)
        child_keys = []
        if self.children is not None:
            for node in self.children:
                child_keys.append(node.key)
        return '%s(%s  gdfo:%s par:%s child:%s)' % (
            self.__class__.__name__, self.key, self.gdfo,
            parent_keys, child_keys)


cdef _KnownGraphNode _get_list_node(lst, Py_ssize_t pos):
    cdef PyObject *temp_node

    temp_node = PyList_GET_ITEM(lst, pos)
    return <_KnownGraphNode>temp_node


cdef _KnownGraphNode _get_parent(parents, Py_ssize_t pos):
    cdef PyObject *temp_node
    cdef _KnownGraphNode node

    temp_node = PyTuple_GET_ITEM(parents, pos)
    return <_KnownGraphNode>temp_node


cdef class KnownGraph:
    """This is a class which assumes we already know the full graph."""

    cdef public object _nodes
    cdef object _known_heads
    cdef public int do_cache

    def __init__(self, parent_map, do_cache=True):
        """Create a new KnownGraph instance.

        :param parent_map: A dictionary mapping key => parent_keys
        """
        # tests at pre-allocating the node dict actually slowed things down
        self._nodes = {}
        # Maps {sorted(revision_id, revision_id): heads}
        self._known_heads = {}
        self.do_cache = int(do_cache)
        self._initialize_nodes(parent_map)
        self._find_gdfo()

    def __dealloc__(self):
        cdef _KnownGraphNode child
        cdef Py_ssize_t pos
        cdef PyObject *temp_node

        while PyDict_Next(self._nodes, &pos, NULL, &temp_node):
            child = <_KnownGraphNode>temp_node
            child.clear_references()

    cdef _KnownGraphNode _get_or_create_node(self, key):
        cdef PyObject *temp_node
        cdef _KnownGraphNode node

        temp_node = PyDict_GetItem(self._nodes, key)
        if temp_node == NULL:
            node = _KnownGraphNode(key)
            PyDict_SetItem(self._nodes, key, node)
        else:
            node = <_KnownGraphNode>temp_node
        return node

    def _initialize_nodes(self, parent_map):
        """Populate self._nodes.

        After this has finished:
        - self._nodes will have an entry for every entry in parent_map.
        - ghosts will have a parent_keys = None,
        - all nodes found will also have child_keys populated with all known
          child keys,
        """
        cdef PyObject *temp_key, *temp_parent_keys, *temp_node
        cdef Py_ssize_t pos, pos2, num_parent_keys
        cdef _KnownGraphNode node
        cdef _KnownGraphNode parent_node

        if not PyDict_CheckExact(parent_map):
            raise TypeError('parent_map should be a dict of {key:parent_keys}')
        # for key, parent_keys in parent_map.iteritems():
        pos = 0
        while PyDict_Next(parent_map, &pos, &temp_key, &temp_parent_keys):
            key = <object>temp_key
            parent_keys = <object>temp_parent_keys
            num_parent_keys = len(parent_keys)
            node = self._get_or_create_node(key)
            # We know how many parents, so we could pre allocate an exact sized
            # tuple here
            parent_nodes = PyTuple_New(num_parent_keys)
            # We use iter here, because parent_keys maybe be a list or tuple
            for pos2 from 0 <= pos2 < num_parent_keys:
                parent_node = self._get_or_create_node(parent_keys[pos2])
                # PyTuple_SET_ITEM will steal a reference, so INCREF first
                Py_INCREF(parent_node)
                PyTuple_SET_ITEM(parent_nodes, pos2, parent_node)
                PyList_Append(parent_node.children, node)
            node.parents = parent_nodes

    def _find_tails(self):
        cdef PyObject *temp_node
        cdef _KnownGraphNode node
        cdef Py_ssize_t pos

        tails = []
        pos = 0
        while PyDict_Next(self._nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            if node.parents is None or PyTuple_GET_SIZE(node.parents) == 0:
                node.gdfo = 1
                PyList_Append(tails, node)
        return tails

    def _find_gdfo(self):
        cdef _KnownGraphNode node
        cdef _KnownGraphNode child
        cdef PyObject *temp
        cdef Py_ssize_t pos
        cdef int replace
        cdef Py_ssize_t last_item
        cdef long next_gdfo

        pending = self._find_tails()

        last_item = PyList_GET_SIZE(pending) - 1
        while last_item >= 0:
            # Avoid pop followed by push, instead, peek, and replace
            # timing shows this is 930ms => 770ms for OOo
            node = _get_list_node(pending, last_item)
            last_item = last_item - 1
            next_gdfo = node.gdfo + 1
            for pos from 0 <= pos < PyList_GET_SIZE(node.children):
                child = _get_list_node(node.children, pos)
                if next_gdfo > child.gdfo:
                    child.gdfo = next_gdfo
                child.seen = child.seen + 1
                if child.seen == PyTuple_GET_SIZE(child.parents):
                    # This child is populated, queue it to be walked
                    last_item = last_item + 1
                    if last_item < PyList_GET_SIZE(pending):
                        Py_INCREF(child) # SetItem steals a ref
                        PyList_SetItem(pending, last_item, child)
                    else:
                        PyList_Append(pending, child)
                    # We have queued this node, we don't need to track it
                    # anymore
                    child.seen = 0

    def heads(self, keys):
        """Return the heads from amongst keys.

        This is done by searching the ancestries of each key.  Any key that is
        reachable from another key is not returned; all the others are.

        This operation scales with the relative depth between any two keys. It
        uses gdfo to avoid walking all ancestry.

        :param keys: An iterable of keys.
        :return: A set of the heads. Note that as a set there is no ordering
            information. Callers will need to filter their input to create
            order if they need it.
        """
        cdef PyObject *maybe_node
        cdef PyObject *maybe_heads
        cdef PyObject *temp_node
        cdef _KnownGraphNode node
        cdef Py_ssize_t pos, last_item
        cdef long min_gdfo

        heads_key = frozenset(keys)
        maybe_heads = PyDict_GetItem(self._known_heads, heads_key)
        if maybe_heads != NULL:
            return <object>maybe_heads
        # Not cached, compute it ourselves
        candidate_nodes = {}
        for key in keys:
            maybe_node = PyDict_GetItem(self._nodes, key)
            if maybe_node == NULL:
                raise KeyError('key %s not in nodes' % (key,))
            PyDict_SetItem(candidate_nodes, key, <object>maybe_node)
        maybe_node = PyDict_GetItem(candidate_nodes, NULL_REVISION)
        if maybe_node != NULL:
            # NULL_REVISION is only a head if it is the only entry
            candidate_nodes.pop(NULL_REVISION)
            if not candidate_nodes:
                return frozenset([NULL_REVISION])
            # The keys changed, so recalculate heads_key
            heads_key = frozenset(candidate_nodes)
        if PyDict_Size(candidate_nodes) < 2:
            return heads_key

        cleanup = []
        pending = []
        # we know a gdfo cannot be longer than a linear chain of all nodes
        min_gdfo = PyDict_Size(self._nodes) + 1
        # Build up nodes that need to be walked, note that starting nodes are
        # not added to seen()
        pos = 0
        while PyDict_Next(candidate_nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            if node.parents is not None:
                pending.extend(node.parents)
            if node.gdfo < min_gdfo:
                min_gdfo = node.gdfo

        # Now do all the real work
        last_item = PyList_GET_SIZE(pending) - 1
        while last_item >= 0:
            node = _get_list_node(pending, last_item)
            last_item = last_item - 1
            if node.seen:
                # node already appears in some ancestry
                continue
            PyList_Append(cleanup, node)
            node.seen = 1
            if node.gdfo <= min_gdfo:
                continue
            if node.parents is not None and PyTuple_GET_SIZE(node.parents) > 0:
                for pos from 0 <= pos < PyTuple_GET_SIZE(node.parents):
                    parent_node = _get_parent(node.parents, pos)
                    last_item = last_item + 1
                    if last_item < PyList_GET_SIZE(pending):
                        Py_INCREF(parent_node) # SetItem steals a ref
                        PyList_SetItem(pending, last_item, parent_node)
                    else:
                        PyList_Append(pending, parent_node)
        heads = []
        pos = 0
        while PyDict_Next(candidate_nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            if not node.seen:
                PyList_Append(heads, node.key)
        heads = frozenset(heads)
        for pos from 0 <= pos < PyList_GET_SIZE(cleanup):
            node = _get_list_node(cleanup, pos)
            node.seen = 0
        if self.do_cache:
            PyDict_SetItem(self._known_heads, heads_key, heads)
        return heads

    def topo_sort(self):
        """Return the nodes in topological order.

        All parents must occur before all children.
        """
        # This is, for the most part, the same iteration order that we used for
        # _find_gdfo, consider finding a way to remove the duplication
        # In general, we find the 'tails' (nodes with no parents), and then
        # walk to the children. For children that have all of their parents
        # yielded, we queue up the child to be yielded as well.
        cdef _KnownGraphNode node
        cdef _KnownGraphNode child
        cdef PyObject *temp
        cdef Py_ssize_t pos
        cdef int replace
        cdef Py_ssize_t last_item

        pending = self._find_tails()
        if PyList_GET_SIZE(pending) == 0 and len(self._nodes) > 0:
            raise errors.GraphCycleError(self._nodes)

        topo_order = []

        last_item = PyList_GET_SIZE(pending) - 1
        while last_item >= 0:
            # Avoid pop followed by push, instead, peek, and replace
            # timing shows this is 930ms => 770ms for OOo
            node = _get_list_node(pending, last_item)
            last_item = last_item - 1
            if node.parents is not None:
                # We don't include ghost parents
                PyList_Append(topo_order, node.key)
            for pos from 0 <= pos < PyList_GET_SIZE(node.children):
                child = _get_list_node(node.children, pos)
                if child.gdfo == -1:
                    # We know we have a graph cycle because a node has a parent
                    # which we couldn't find
                    raise errors.GraphCycleError(self._nodes)
                child.seen = child.seen + 1
                if child.seen == PyTuple_GET_SIZE(child.parents):
                    # All parents of this child have been yielded, queue this
                    # one to be yielded as well
                    last_item = last_item + 1
                    if last_item < PyList_GET_SIZE(pending):
                        Py_INCREF(child) # SetItem steals a ref
                        PyList_SetItem(pending, last_item, child)
                    else:
                        PyList_Append(pending, child)
                    # We have queued this node, we don't need to track it
                    # anymore
                    child.seen = 0
        # We started from the parents, so we don't need to do anymore work
        return topo_order


    def merge_sort(self, tip_key):
        """Compute the merge sorted graph output."""
        cdef _KnownGraphNode node, parent_node
        from bzrlib import tsort
        # TODO: merge_sort doesn't handle ghosts (yet), figure out what to do
        #       when we want it to.
        as_parent_map = {}
        for node in self._nodes.itervalues():
            parent_keys = []
            for parent_node in node.parents:
                parent_keys.append(parent_node.key)
            as_parent_map[node.key] = parent_keys
        # We intentionally always generate revnos and never force the
        # mainline_revisions
        return tsort.merge_sort(as_parent_map, tip_key,
                                mainline_revisions=None,
                                generate_revno=True)


cdef class _MergeSortNode:
    """Tracks information about a node during the merge_sort operation."""

    cdef _KnownGraphNode node
    cdef Py_ssize_t merge_depth
    cdef int left_subtree_pushed # True/False
    cdef object pending_parents # list of _MergeSortNode objects
    cdef object revno # tuple of dotted revnos
    cdef int is_first_child # Is this the first child?


cdef _MergeSortNode _make_merge_sort_node(_KnownGraphNode node,
                                          Py_ssize_t merge_depth,
                                          int left_subtree_pushed):
    cdef _MergeSortNode ms_node
    return ms_node


cdef class _MergeSorter:
    """This class does the work of computing the merge_sort ordering.

    We have some small advantages, in that we get all the extra information
    that KnownGraph knows, like knowing the child lists, etc.
    """

    cdef KnownGraph graph
    cdef object _stack  # list
    cdef object _seen_parents # set of keys for which we have seen a child

    def __init__(self, known_graph, tip_key):
        self.graph = known_graph
        self._seen_parents = set()
        if tip_key is not None and tip_key != NULL_REVISION:
            node = self.graph._nodes[tip_key]
            self._push_node(node, 0)

    cdef _push_node(self, _KnownGraphNode node, Py_ssize_t merge_depth):
        cdef _KnownGraphNode parent_node

        ms_node = _MergeSortNode()
        ms_node.node = node
        ms_node.merge_depth = merge_depth
        ms_node.left_subtree_pushed = 0
        ms_node.pending_parents = list(node.parents)
        ms_node.revno = None
        ms_node.is_first_child = 1
        self._stack.append(ms_node)
        if node.parents:
            parent_node = _get_parent(node.parents, 0)

            if parent_node.key in self._seen_parents:
                ms_node.is_first_child = True
            self._seen_parents.add(parent_node.key)

#     def iter_topo_order(self):
#         """Yield the nodes of the graph in a topological order.
# 
#         After finishing iteration the sorter is empty and you cannot continue
#         iteration.
#         """
#         # These are safe to offload to local variables, because they are used
#         # as a stack and modified in place, never assigned to.
#         node_name_stack = self._node_name_stack
#         node_merge_depth_stack = self._node_merge_depth_stack
#         pending_parents_stack = self._pending_parents_stack
#         left_subtree_pushed_stack = self._left_subtree_pushed_stack
#         completed_node_names = self._completed_node_names
#         scheduled_nodes = self._scheduled_nodes
# 
#         graph_pop = self._graph.pop
# 
#         def push_node(node_name, merge_depth, parents,
#                       node_name_stack_append=node_name_stack.append,
#                       node_merge_depth_stack_append=node_merge_depth_stack.append,
#                       left_subtree_pushed_stack_append=left_subtree_pushed_stack.append,
#                       pending_parents_stack_append=pending_parents_stack.append,
#                       first_child_stack_append=self._first_child_stack.append,
#                       revnos=self._revnos,
#                       ):
#             """Add node_name to the pending node stack.
# 
#             Names in this stack will get emitted into the output as they are popped
#             off the stack.
# 
#             This inlines a lot of self._variable.append functions as local
#             variables.
#             """
#             node_name_stack_append(node_name)
#             node_merge_depth_stack_append(merge_depth)
#             left_subtree_pushed_stack_append(False)
#             pending_parents_stack_append(list(parents))
#             # as we push it, check if it is the first child
#             if parents:
#                 # node has parents, assign from the left most parent.
#                 parent_info = revnos[parents[0]]
#                 first_child = parent_info[1]
#                 parent_info[1] = False
#             else:
#                 # We don't use the same algorithm here, but we need to keep the
#                 # stack in line
#                 first_child = None
#             first_child_stack_append(first_child)
# 
#         def pop_node(node_name_stack_pop=node_name_stack.pop,
#                      node_merge_depth_stack_pop=node_merge_depth_stack.pop,
#                      first_child_stack_pop=self._first_child_stack.pop,
#                      left_subtree_pushed_stack_pop=left_subtree_pushed_stack.pop,
#                      pending_parents_stack_pop=pending_parents_stack.pop,
#                      original_graph=self._original_graph,
#                      revnos=self._revnos,
#                      completed_node_names_add=self._completed_node_names.add,
#                      scheduled_nodes_append=scheduled_nodes.append,
#                      revno_to_branch_count=self._revno_to_branch_count,
#                     ):
#             """Pop the top node off the stack
# 
#             The node is appended to the sorted output.
#             """
#             # we are returning from the flattened call frame:
#             # pop off the local variables
#             node_name = node_name_stack_pop()
#             merge_depth = node_merge_depth_stack_pop()
#             first_child = first_child_stack_pop()
#             # remove this node from the pending lists:
#             left_subtree_pushed_stack_pop()
#             pending_parents_stack_pop()
# 
#             parents = original_graph[node_name]
#             if parents:
#                 # node has parents, assign from the left most parent.
#                 parent_revno = revnos[parents[0]][0]
#                 if not first_child:
#                     # not the first child, make a new branch
#                     base_revno = parent_revno[0]
#                     branch_count = revno_to_branch_count.get(base_revno, 0)
#                     branch_count += 1
#                     revno_to_branch_count[base_revno] = branch_count
#                     revno = (parent_revno[0], branch_count, 1)
#                     # revno = (parent_revno[0], branch_count, parent_revno[-1]+1)
#                 else:
#                     # as the first child, we just increase the final revision
#                     # number
#                     revno = parent_revno[:-1] + (parent_revno[-1] + 1,)
#             else:
#                 # no parents, use the root sequence
#                 root_count = revno_to_branch_count.get(0, -1)
#                 root_count += 1
#                 if root_count:
#                     revno = (0, root_count, 1)
#                 else:
#                     revno = (1,)
#                 revno_to_branch_count[0] = root_count
# 
#             # store the revno for this node for future reference
#             revnos[node_name][0] = revno
#             completed_node_names_add(node_name)
#             scheduled_nodes_append((node_name, merge_depth, revno))
#             return node_name
# 
# 
#         while node_name_stack:
#             # loop until this call completes.
#             parents_to_visit = pending_parents_stack[-1]
#             # if all parents are done, the revision is done
#             if not parents_to_visit:
#                 # append the revision to the topo sorted scheduled list:
#                 # all the nodes parents have been scheduled added, now
#                 # we can add it to the output.
#                 pop_node()
#             else:
#                 while pending_parents_stack[-1]:
#                     if not left_subtree_pushed_stack[-1]:
#                         # recurse depth first into the primary parent
#                         next_node_name = pending_parents_stack[-1].pop(0)
#                     else:
#                         # place any merges in right-to-left order for scheduling
#                         # which gives us left-to-right order after we reverse
#                         # the scheduled queue. XXX: This has the effect of
#                         # allocating common-new revisions to the right-most
#                         # subtree rather than the left most, which will
#                         # display nicely (you get smaller trees at the top
#                         # of the combined merge).
#                         next_node_name = pending_parents_stack[-1].pop()
#                     if next_node_name in completed_node_names:
#                         # this parent was completed by a child on the
#                         # call stack. skip it.
#                         continue
#                     # otherwise transfer it from the source graph into the
#                     # top of the current depth first search stack.
#                     try:
#                         parents = graph_pop(next_node_name)
#                     except KeyError:
#                         # if the next node is not in the source graph it has
#                         # already been popped from it and placed into the
#                         # current search stack (but not completed or we would
#                         # have hit the continue 4 lines up.
#                         # this indicates a cycle.
#                         raise errors.GraphCycleError(node_name_stack)
#                     next_merge_depth = 0
#                     if left_subtree_pushed_stack[-1]:
#                         # a new child branch from name_stack[-1]
#                         next_merge_depth = 1
#                     else:
#                         next_merge_depth = 0
#                         left_subtree_pushed_stack[-1] = True
#                     next_merge_depth = (
#                         node_merge_depth_stack[-1] + next_merge_depth)
#                     push_node(
#                         next_node_name,
#                         next_merge_depth,
#                         parents)
#                     # and do not continue processing parents until this 'call'
#                     # has recursed.
#                     break
# 
#         # We have scheduled the graph. Now deliver the ordered output:
#         sequence_number = 0
#         stop_revision = self._stop_revision
#         generate_revno = self._generate_revno
#         original_graph = self._original_graph
# 
#         while scheduled_nodes:
#             node_name, merge_depth, revno = scheduled_nodes.pop()
#             if node_name == stop_revision:
#                 return
#             if not len(scheduled_nodes):
#                 # last revision is the end of a merge
#                 end_of_merge = True
#             elif scheduled_nodes[-1][1] < merge_depth:
#                 # the next node is to our left
#                 end_of_merge = True
#             elif (scheduled_nodes[-1][1] == merge_depth and
#                   (scheduled_nodes[-1][0] not in
#                    original_graph[node_name])):
#                 # the next node was part of a multiple-merge.
#                 end_of_merge = True
#             else:
#                 end_of_merge = False
#             if generate_revno:
#                 yield (sequence_number, node_name, merge_depth, revno, end_of_merge)
#             else:
#                 yield (sequence_number, node_name, merge_depth, end_of_merge)
#             sequence_number += 1
# 
