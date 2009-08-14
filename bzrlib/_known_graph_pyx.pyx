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
        cdef _MergeSorter sorter

        sorter = _MergeSorter(self, tip_key)
        return sorter.topo_order()


cdef class _MergeSortNode:
    """Tracks information about a node during the merge_sort operation."""

    cdef _KnownGraphNode node
    cdef Py_ssize_t merge_depth
    cdef int left_subtree_pushed # True/False
    cdef object pending_parents # list of _KnownGraphNode
    cdef object revno # tuple of dotted revnos
    cdef int is_first_child # Is this the first child?
    # cdef int seen_by_child # A child node has seen this parent

    def __repr__(self):
        return '_MSN(%s depth:%s lp:%s rev:%s)' % (#self.__class__.__name__,
            self.node.key, self.merge_depth, self.left_subtree_pushed,
            self.revno)


cdef class _MergeSorter:
    """This class does the work of computing the merge_sort ordering.

    We have some small advantages, in that we get all the extra information
    that KnownGraph knows, like knowing the child lists, etc.
    """

    # Current performance numbers for merge_sort(bzr_dev_parent_map):
    #  310ms tsort.merge_sort()
    #  194ms graph.KnownGraph().merge_sort()
    #  143ms kg.merge_sort()

    cdef KnownGraph graph
    cdef object _stack  # list
    cdef object _seen_parents # Set of keys
    cdef object _ms_nodes # dict of key => _MergeSortNode
    cdef object _revno_to_branch_count # {revno => num child branches}
    cdef object _completed_node_names # Set of keys that have been completed
    cdef object _scheduled_nodes # List of nodes ready to be yielded

    def __init__(self, known_graph, tip_key):
        self.graph = known_graph
        self._ms_nodes = {}
        self._revno_to_branch_count = {}
        self._seen_parents = set()
        self._stack = []
        self._completed_node_names = set()
        self._scheduled_nodes = []
        if tip_key is not None and tip_key != NULL_REVISION:
            node = self.graph._nodes[tip_key]
            self._push_node(node, 0)

    cdef _push_node(self, _KnownGraphNode node, Py_ssize_t merge_depth):
        cdef _KnownGraphNode parent_node
        cdef _MergeSortNode ms_node, ms_parent_node

        ms_node = _MergeSortNode()
        ms_node.node = node
        ms_node.merge_depth = merge_depth
        ms_node.left_subtree_pushed = 0
        # TODO: turn this into a list of pending _MergeSortNode rather than
        # keys
        ms_node.pending_parents = list(node.parents)
        ms_node.revno = None
        ms_node.is_first_child = 1
        # ms_node.seen_by_child = 0
        self._stack.append(ms_node)
        if node.parents:
            parent_node = _get_parent(node.parents, 0)

            # TODO: could we use a '.seen' member instead of a set?
            #       alternatively, track self._ms_nodes = {}, etc.
            #       If we use _ms_nodes, then we have to be able to create a
            #       new parent node 'on demand' even when we don't know the
            #       rest of the info yet.
            if parent_node.key in self._seen_parents:
                ms_node.is_first_child = 0
            self._seen_parents.add(parent_node.key)
        self._ms_nodes[ms_node.node.key] = ms_node

    cdef _pop_node(self):
        cdef _MergeSortNode ms_node, ms_parent_node
        cdef _KnownGraphNode parent_node

        ms_node = self._stack.pop()
        if ms_node.node.parents:
            # Assign the revision number for *this* node, from its left-hand
            # parent
            parent_node = _get_parent(ms_node.node.parents, 0)
            ms_parent_node = self._ms_nodes[parent_node.key]
            if not ms_node.is_first_child:
                # Not the first child, make a new branch
                base_revno = ms_parent_node.revno[0]
                branch_count = self._revno_to_branch_count.get(base_revno, 0)
                branch_count = branch_count + 1
                self._revno_to_branch_count[base_revno] = branch_count
                revno = (base_revno, branch_count, 1)
            else:
                # First child just increments the final digit
                final = ms_parent_node.revno[-1] + 1
                revno = ms_parent_node.revno[:-1] + (final,)
        else:
            root_count = self._revno_to_branch_count.get(0, -1)
            root_count = root_count + 1
            if root_count:
                revno = (0, root_count, 1)
            else:
                revno = (1,)
            self._revno_to_branch_count[0] = root_count
        ms_node.revno = revno
        self._completed_node_names.add(ms_node.node.key)
        self._scheduled_nodes.append(ms_node)

    cdef _schedule_stack(self):
        cdef _MergeSortNode ms_node, ms_last_node
        cdef _KnownGraphNode next_node
        ordered = []
        while self._stack:
            # Peek at the last item on the stack
            # print self._stack
            # print '  ', self._scheduled_nodes
            ms_last_node = self._stack[-1]
            if not ms_last_node.pending_parents:
                self._pop_node()
                continue
            while ms_last_node.pending_parents:
                if not ms_last_node.left_subtree_pushed:
                    # recurse depth first into the primary parent
                    next_node = ms_last_node.pending_parents.pop(0)
                else:
                    # place any merges in right-to-left order for scheduling
                    # which gives us left-to-right order after we reverse
                    # the scheduled queue. XXX: This has the effect of
                    # allocating common-new revisions to the right-most
                    # subtree rather than the left most, which will
                    # display nicely (you get smaller trees at the top
                    # of the combined merge).
                    next_node = ms_last_node.pending_parents.pop()
                if next_node.key in self._completed_node_names:
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
                ##     raise errors.GraphCycleError(self._stack)

                next_merge_depth = 0
                if ms_last_node.left_subtree_pushed:
                    next_merge_depth = 1
                else:
                    next_merge_depth = 0
                    ms_last_node.left_subtree_pushed = 1
                next_merge_depth = next_merge_depth + ms_last_node.merge_depth
                self._push_node(next_node, next_merge_depth)
                # and do not continue processing parents until this 'call'
                # has recursed.
                break

    cdef topo_order(self):
        cdef _MergeSortNode ms_node, ms_last_node
        cdef _KnownGraphNode next_node

        # print
        self._schedule_stack()
        # print self._scheduled_nodes

        # We've set up the basic schedule, now we can continue processing the
        # output.
        sequence_number = 0
        ordered = []
        while self._scheduled_nodes:
            ms_node = self._scheduled_nodes.pop()
            # TODO: stop_revision not supported
            # if ms_node == stop_revision:
            if len(self._scheduled_nodes) == 0:
                end_of_merge = True
            else:
                ms_last_node = self._scheduled_nodes[-1]
                if ms_last_node.merge_depth < ms_node.merge_depth:
                    # Next node is to our left, so this is the end of the right
                    # chain
                    end_of_merge = True
                elif (ms_last_node.merge_depth == ms_node.merge_depth
                      and ms_last_node.node not in ms_node.node.parents):
                    # The next node is not a direct parent of this node
                    end_of_merge = True
                else:
                    end_of_merge = False
            ordered.append((sequence_number, ms_node.node.key,
                            ms_node.merge_depth, ms_node.revno, end_of_merge))
            sequence_number = sequence_number + 1
        return ordered
