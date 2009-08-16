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

import gc

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
    cdef object extra

    def __init__(self, key):
        cdef int i

        self.key = key
        self.parents = None

        self.children = []
        # Greatest distance from origin
        self.gdfo = -1
        self.seen = 0
        self.extra = None

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


cdef class _MergeSorter

cdef class KnownGraph:
    """This is a class which assumes we already know the full graph."""

    cdef public object _nodes
    cdef object _known_heads
    cdef public int do_cache

    def __init__(self, parent_map, do_cache=True):
        """Create a new KnownGraph instance.

        :param parent_map: A dictionary mapping key => parent_keys
        """
        cdef int was_enabled
        # tests at pre-allocating the node dict actually slowed things down
        self._nodes = {}
        # Maps {sorted(revision_id, revision_id): heads}
        self._known_heads = {}
        self.do_cache = int(do_cache)
        was_enabled = gc.isenabled()
        if was_enabled:
            gc.disable()
        # This allocates a lot of nodes but nothing that can be gc'd
        # disable gc while building
        self._initialize_nodes(parent_map)
        if was_enabled:
            gc.enable()
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
        cdef _MergeSorter sorter

        sorter = _MergeSorter(self, tip_key)
        return sorter.topo_order()


cdef class _MergeSortNode:
    """Tracks information about a node during the merge_sort operation."""

    cdef Py_ssize_t merge_depth
    cdef _KnownGraphNode left_parent
    cdef _KnownGraphNode left_pending_parent
    cdef object pending_parents # list of _KnownGraphNode for non-left parents
    cdef Py_ssize_t revno_first
    cdef Py_ssize_t revno_second
    cdef Py_ssize_t revno_last
    # TODO: turn these into flag/bit fields rather than individual members
    cdef int is_first_child # Is this the first child?
    cdef int seen_by_child # A child node has seen this parent
    cdef int completed # Fully Processed

    def __init__(self):
        self.merge_depth = -1
        self.left_parent = None
        self.left_pending_parent = None
        self.pending_parents = None
        self.revno_first = -1
        self.revno_second = -1
        self.revno_last = -1
        self.is_first_child = 0
        self.seen_by_child = 0
        self.completed = 0

    def __repr__(self):
        return '%s(depth:%s rev:%s,%s,%s first:%s seen:%s)' % (self.__class__.__name__,
            self.merge_depth,
            self.revno_first, self.revno_second, self.revno_last,
            self.is_first_child, self.seen_by_child)

    cdef int has_pending_parents(self):
        if self.left_pending_parent is not None or self.pending_parents:
            return 1
        return 0


# cdef _MergeSortNode _get_ms_node(lst, Py_ssize_t pos):
#     cdef PyObject *temp_node
# 
#     temp_node = PyList_GET_ITEM(lst, pos)
#     return <_MergeSortNode>temp_node
# 

cdef class _MergeSorter:
    """This class does the work of computing the merge_sort ordering.

    We have some small advantages, in that we get all the extra information
    that KnownGraph knows, like knowing the child lists, etc.
    """

    # Current performance numbers for merge_sort(bzr_dev_parent_map):
    #  310ms tsort.merge_sort()
    #   92ms graph.KnownGraph().merge_sort()
    #   42ms kg.merge_sort()

    cdef KnownGraph graph
    cdef object _depth_first_stack  # list
    cdef Py_ssize_t _last_stack_item # offset to last item on stack
    # cdef object _ms_nodes # dict of key => _MergeSortNode
    cdef object _revno_to_branch_count # {revno => num child branches}
    cdef object _scheduled_nodes # List of nodes ready to be yielded

    def __init__(self, known_graph, tip_key):
        cdef _KnownGraphNode node

        self.graph = known_graph
        # self._ms_nodes = {}
        self._revno_to_branch_count = {}
        self._depth_first_stack = []
        self._last_stack_item = -1
        self._scheduled_nodes = []
        if tip_key is not None and tip_key != NULL_REVISION:
            node = self.graph._nodes[tip_key]
            self._push_node(node, 0)

    cdef _MergeSortNode _get_or_create_node(self, _KnownGraphNode node):
        cdef PyObject *temp_node
        cdef _MergeSortNode ms_node

        if node.extra is None:
            ms_node = _MergeSortNode()
            node.extra = ms_node
        else:
            ms_node = <_MergeSortNode>node.extra
        return ms_node

    cdef _push_node(self, _KnownGraphNode node, Py_ssize_t merge_depth):
        cdef _KnownGraphNode parent_node
        cdef _MergeSortNode ms_node, ms_parent_node
        cdef Py_ssize_t pos

        ms_node = self._get_or_create_node(node)
        ms_node.merge_depth = merge_depth
        if PyTuple_GET_SIZE(node.parents) > 0:
            parent_node = _get_parent(node.parents, 0)
            ms_node.left_parent = parent_node
            ms_node.left_pending_parent = parent_node
        if PyTuple_GET_SIZE(node.parents) > 1:
            ms_node.pending_parents = list(node.parents[1:])
            # ms_node.pending_parents = []
            # for pos from 1 <= pos < PyTuple_GET_SIZE(node.parents):
            #     parent_node = _get_parent(node.parents, pos)
            #     PyList_Append(ms_node.pending_parents, parent_node)

        ms_node.is_first_child = 1
        if ms_node.left_parent is not None:
            ms_parent_node = self._get_or_create_node(ms_node.left_parent)
            if ms_parent_node.seen_by_child:
                ms_node.is_first_child = 0
            ms_parent_node.seen_by_child = 1
        self._last_stack_item = self._last_stack_item + 1
        if self._last_stack_item < PyList_GET_SIZE(self._depth_first_stack):
            Py_INCREF(node) # SetItem steals a ref
            PyList_SetItem(self._depth_first_stack, self._last_stack_item,
                           node)
        else:
            PyList_Append(self._depth_first_stack, node)
        # print 'pushed: %s' % (ms_node,)

    cdef _pop_node(self):
        cdef PyObject *temp
        cdef _MergeSortNode ms_node, ms_parent_node
        cdef _KnownGraphNode node, parent_node

        assert self._last_stack_item >= 0
        node = _get_list_node(self._depth_first_stack, self._last_stack_item)
        ms_node = <_MergeSortNode>node.extra
        self._last_stack_item = self._last_stack_item - 1
        # print 'popping: %s' % (ms_node,)
        if ms_node.left_parent is not None:
            # Assign the revision number for *this* node, from its left-hand
            # parent
            ms_parent_node = <_MergeSortNode>ms_node.left_parent.extra
            if ms_node.is_first_child:
                # First child just increments the final digit
                ms_node.revno_first = ms_parent_node.revno_first
                ms_node.revno_second = ms_parent_node.revno_second
                ms_node.revno_last = ms_parent_node.revno_last + 1
            else:
                # Not the first child, make a new branch
                if ms_parent_node.revno_first == -1:
                    # Mainline ancestor, the increment is on the last digit
                    base_revno = ms_parent_node.revno_last
                else:
                    base_revno = ms_parent_node.revno_first
                temp = PyDict_GetItem(self._revno_to_branch_count,
                                      base_revno)
                if temp == NULL:
                    branch_count = 1
                else:
                    branch_count = (<object>temp) + 1
                PyDict_SetItem(self._revno_to_branch_count, base_revno,
                               branch_count)
                if ms_parent_node.revno_first == -1:
                    ms_node.revno_first = ms_parent_node.revno_last
                else:
                    ms_node.revno_first = ms_parent_node.revno_first
                ms_node.revno_second = branch_count
                ms_node.revno_last = 1
        else:
            root_count = self._revno_to_branch_count.get(0, -1)
            root_count = root_count + 1
            if root_count:
                ms_node.revno_first = 0
                ms_node.revno_second = root_count
                ms_node.revno_last = 1
            else:
                # The first root node doesn't have a 3-digit revno
                ms_node.revno_first = -1
                ms_node.revno_second = -1
                ms_node.revno_last = 1
            self._revno_to_branch_count[0] = root_count
        ms_node.completed = 1
        PyList_Append(self._scheduled_nodes, node)

    cdef _schedule_stack(self):
        cdef _KnownGraphNode last_node, next_node
        cdef _MergeSortNode ms_node, ms_last_node, ms_next_node
        cdef Py_ssize_t next_merge_depth
        ordered = []
        while self._last_stack_item >= 0:
            # Peek at the last item on the stack
            # print self._depth_first_stack
            # print '  ', self._scheduled_nodes
            last_node = _get_list_node(self._depth_first_stack,
                                       self._last_stack_item)
            ms_last_node = <_MergeSortNode>last_node.extra
            if not ms_last_node.has_pending_parents():
                # Processed all parents, pop this node
                self._pop_node()
                continue
            while ms_last_node.has_pending_parents():
                if ms_last_node.left_pending_parent is not None:
                    # recurse depth first into the primary parent
                    next_node = ms_last_node.left_pending_parent
                    ms_last_node.left_pending_parent = None
                else:
                    # place any merges in right-to-left order for scheduling
                    # which gives us left-to-right order after we reverse
                    # the scheduled queue. XXX: This has the effect of
                    # allocating common-new revisions to the right-most
                    # subtree rather than the left most, which will
                    # display nicely (you get smaller trees at the top
                    # of the combined merge).
                    next_node = ms_last_node.pending_parents.pop()
                ms_next_node = self._get_or_create_node(next_node)
                if ms_next_node.completed:
                    # this parent was completed by a child on the
                    # call stack. skip it.
                    continue
                # otherwise transfer it from the source graph into the
                # top of the current depth first search stack.
                # TODO: Check for GraphCycleError
                ## try:
                ##     parents = graph_pop(next_node_name)
                ## except KeyError:
                ##     # if the next node is not in the source graph it has
                ##     # already been popped from it and placed into the
                ##     # current search stack (but not completed or we would
                ##     # have hit the continue 4 lines up.
                ##     # this indicates a cycle.
                ##     raise errors.GraphCycleError(self._depth_first_stack)

                assert ms_next_node is not None
                next_merge_depth = 0
                if next_node is ms_last_node.left_parent:
                    next_merge_depth = 0
                else:
                    next_merge_depth = 1
                next_merge_depth = next_merge_depth + ms_last_node.merge_depth
                self._push_node(next_node, next_merge_depth)
                # and do not continue processing parents until this 'call'
                # has recursed.
                break

    cdef topo_order(self):
        cdef _MergeSortNode ms_node, ms_prev_node
        cdef _KnownGraphNode node, prev_node
        cdef Py_ssize_t pos

        # print
        self._schedule_stack()
        # print self._scheduled_nodes

        # We've set up the basic schedule, now we can continue processing the
        # output.
        # TODO: This final loop costs us 55ms => 41.2ms (14ms) on bzr.dev, to
        #       evaluate end-of-merge and convert the internal Object
        #       representation into a Tuple representation...
        sequence_number = 0
        ordered = []
        pos = PyList_GET_SIZE(self._scheduled_nodes) - 1
        if pos >= 0:
            prev_node = _get_list_node(self._scheduled_nodes, pos)
            ms_prev_node = <_MergeSortNode>prev_node.extra
        while pos >= 0:
            if node is not None:
                # Clear out the extra info we don't need
                node.extra = None
            node = prev_node
            ms_node = ms_prev_node
            pos = pos - 1
            if pos == -1:
                # Final node is always the end-of-chain
                end_of_merge = True
            else:
                prev_node = _get_list_node(self._scheduled_nodes, pos)
                ms_prev_node = <_MergeSortNode>prev_node.extra
                if ms_prev_node.merge_depth < ms_node.merge_depth:
                    # Next node is to our left, so this is the end of the right
                    # chain
                    end_of_merge = True
                elif (ms_prev_node.merge_depth == ms_node.merge_depth
                      and prev_node not in node.parents):
                    # The next node is not a direct parent of this node
                    end_of_merge = True
                else:
                    end_of_merge = False
            if ms_node.revno_first == -1:
                if ms_node.revno_second != -1:
                    raise ValueError('Something wrong with: %s' % (ms_node,))
                revno = (ms_node.revno_last,)
            else:
                revno = (ms_node.revno_first, ms_node.revno_second,
                         ms_node.revno_last)
            PyList_Append(ordered, (sequence_number, node.key,
                                    ms_node.merge_depth, revno, end_of_merge))
            sequence_number = sequence_number + 1
        if node is not None:
            node.extra = None
        # Clear out the scheduled nodes
        self._scheduled_nodes = []
        return ordered
