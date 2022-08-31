# Copyright (C) 2009, 2010 Canonical Ltd
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
#
# cython: language_level=3

"""Implementation of Graph algorithms when we have already loaded everything.
"""

cdef extern from "python-compat.h":
    pass

from cpython.bytes cimport (
    PyBytes_CheckExact,
    )
from cpython.dict cimport (
    PyDict_CheckExact,
    PyDict_DelItem,
    PyDict_GetItem,
    PyDict_Next,
    PyDict_SetItem,
    PyDict_Size,
    )
from cpython.list cimport (
    PyList_Append,
    PyList_CheckExact,
    PyList_GET_SIZE,
    PyList_GET_ITEM,
    PyList_SetItem,
    )
from cpython.object cimport (
    Py_LT,
    PyObject,
    PyObject_RichCompareBool,
    )
from cpython.ref cimport (
    Py_INCREF,
    )
from cpython.tuple cimport (
    PyTuple_CheckExact,
    PyTuple_GET_SIZE,
    PyTuple_GET_ITEM,
    PyTuple_New,
    PyTuple_SET_ITEM,
    )

import collections
import gc

from . import errors, revision

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

    property parent_keys:
        def __get__(self):
            if self.parents is None:
                return None

            cdef _KnownGraphNode parent

            keys = []
            for parent in self.parents:
                PyList_Append(keys, parent.key)
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


cdef _KnownGraphNode _get_tuple_node(tpl, Py_ssize_t pos):
    cdef PyObject *temp_node

    temp_node = PyTuple_GET_ITEM(tpl, pos)
    return <_KnownGraphNode>temp_node


def get_key(node):
    cdef _KnownGraphNode real_node
    real_node = node
    return real_node.key


cdef object _sort_list_nodes(object lst_or_tpl, int reverse):
    """Sort a list of _KnownGraphNode objects.

    If lst_or_tpl is a list, it is allowed to mutate in place. It may also
    just return the input list if everything is already sorted.
    """
    cdef _KnownGraphNode node1, node2
    cdef int do_swap, is_tuple
    cdef Py_ssize_t length

    is_tuple = PyTuple_CheckExact(lst_or_tpl)
    if not (is_tuple or PyList_CheckExact(lst_or_tpl)):
        raise TypeError('lst_or_tpl must be a list or tuple.')
    length = len(lst_or_tpl)
    if length == 0 or length == 1:
        return lst_or_tpl
    if length == 2:
        if is_tuple:
            node1 = _get_tuple_node(lst_or_tpl, 0)
            node2 = _get_tuple_node(lst_or_tpl, 1)
        else:
            node1 = _get_list_node(lst_or_tpl, 0)
            node2 = _get_list_node(lst_or_tpl, 1)
        if reverse:
            do_swap = PyObject_RichCompareBool(node1.key, node2.key, Py_LT)
        else:
            do_swap = PyObject_RichCompareBool(node2.key, node1.key, Py_LT)
        if not do_swap:
            return lst_or_tpl
        if is_tuple:
            return (node2, node1)
        else:
            # Swap 'in-place', since lists are mutable
            Py_INCREF(node1)
            PyList_SetItem(lst_or_tpl, 1, node1)
            Py_INCREF(node2)
            PyList_SetItem(lst_or_tpl, 0, node2)
            return lst_or_tpl
    # For all other sizes, we just use 'sorted()'
    if is_tuple:
        # Note that sorted() is just list(iterable).sort()
        lst_or_tpl = list(lst_or_tpl)
    lst_or_tpl.sort(key=get_key, reverse=reverse)
    return lst_or_tpl


cdef class _MergeSorter

cdef class KnownGraph:
    """This is a class which assumes we already know the full graph."""

    cdef public object _nodes
    cdef public object _known_heads
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
        # TODO: consider disabling gc since we are allocating a lot of nodes
        #       that won't be collectable anyway. real world testing has not
        #       shown a specific impact, yet.
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

    cdef _populate_parents(self, _KnownGraphNode node, parent_keys):
        cdef Py_ssize_t num_parent_keys, pos
        cdef _KnownGraphNode parent_node

        num_parent_keys = len(parent_keys)
        # We know how many parents, so we pre allocate the tuple
        parent_nodes = PyTuple_New(num_parent_keys)
        for pos from 0 <= pos < num_parent_keys:
            # Note: it costs us 10ms out of 40ms to lookup all of these
            #       parents, it doesn't seem to be an allocation overhead,
            #       but rather a lookup overhead. There doesn't seem to be
            #       a way around it, and that is one reason why
            #       KnownGraphNode maintains a direct pointer to the parent
            #       node.
            # We use [] because parent_keys may be a tuple or list
            parent_node = self._get_or_create_node(parent_keys[pos])
            # PyTuple_SET_ITEM will steal a reference, so INCREF first
            Py_INCREF(parent_node)
            PyTuple_SET_ITEM(parent_nodes, pos, parent_node)
            PyList_Append(parent_node.children, node)
        node.parents = parent_nodes

    def _initialize_nodes(self, parent_map):
        """Populate self._nodes.

        After this has finished:
        - self._nodes will have an entry for every entry in parent_map.
        - ghosts will have a parent_keys = None,
        - all nodes found will also have child_keys populated with all known
          child keys,
        """
        cdef PyObject *temp_key
        cdef PyObject *temp_parent_keys
        cdef PyObject *temp_node
        cdef Py_ssize_t pos
        cdef _KnownGraphNode node
        cdef _KnownGraphNode parent_node

        if not PyDict_CheckExact(parent_map):
            raise TypeError('parent_map should be a dict of {key:parent_keys}')
        # for key, parent_keys in parent_map.iteritems():
        pos = 0
        while PyDict_Next(parent_map, &pos, &temp_key, &temp_parent_keys):
            key = <object>temp_key
            parent_keys = <object>temp_parent_keys
            node = self._get_or_create_node(key)
            self._populate_parents(node, parent_keys)

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

    def _find_tips(self):
        cdef PyObject *temp_node
        cdef _KnownGraphNode node
        cdef Py_ssize_t pos

        tips = []
        pos = 0
        while PyDict_Next(self._nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            if PyList_GET_SIZE(node.children) == 0:
                PyList_Append(tips, node)
        return tips

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

    def add_node(self, key, parent_keys):
        """Add a new node to the graph.

        If this fills in a ghost, then the gdfos of all children will be
        updated accordingly.

        :param key: The node being added. If this is a duplicate, this is a
            no-op.
        :param parent_keys: The parents of the given node.
        :return: None (should we return if this was a ghost, etc?)
        """
        cdef PyObject *maybe_node
        cdef _KnownGraphNode node, parent_node, child_node
        cdef long parent_gdfo, next_gdfo

        maybe_node = PyDict_GetItem(self._nodes, key)
        if maybe_node != NULL:
            node = <_KnownGraphNode>maybe_node
            if node.parents is None:
                # We are filling in a ghost
                self._populate_parents(node, parent_keys)
                # We can't trust cached heads anymore
                self._known_heads.clear()
            else: # Ensure that the parent_key list matches
                existing_parent_keys = []
                for parent_node in node.parents:
                    existing_parent_keys.append(parent_node.key)
                # Make sure we use a list for the comparison, in case it was a
                # tuple, etc
                parent_keys = list(parent_keys)
                if existing_parent_keys == parent_keys:
                    # Exact match, nothing more to do
                    return
                else:
                    raise ValueError('Parent key mismatch, existing node %s'
                        ' has parents of %s not %s'
                        % (key, existing_parent_keys, parent_keys))
        else:
            node = _KnownGraphNode(key)
            PyDict_SetItem(self._nodes, key, node)
            self._populate_parents(node, parent_keys)
        parent_gdfo = 0
        for parent_node in node.parents:
            if parent_node.gdfo == -1:
                # This is a newly introduced ghost, so it gets gdfo of 1
                parent_node.gdfo = 1
            if parent_gdfo < parent_node.gdfo:
                parent_gdfo = parent_node.gdfo
        node.gdfo = parent_gdfo + 1
        # Now fill the gdfo to all children
        # Note that this loop is slightly inefficient, in that we may visit the
        # same child (and its decendents) more than once, however, it is
        # 'efficient' in that we only walk to nodes that would be updated,
        # rather than all nodes
        # We use a deque rather than a simple list stack, to go for BFD rather
        # than DFD. So that if a longer path is possible, we walk it before we
        # get to the final child
        pending = collections.deque([node])
        pending_popleft = pending.popleft
        pending_append = pending.append
        while pending:
            node = pending_popleft()
            next_gdfo = node.gdfo + 1
            for child_node in node.children:
                if child_node.gdfo < next_gdfo:
                    # This child is being updated, we need to check its
                    # children
                    child_node.gdfo = next_gdfo
                    pending_append(child_node)

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
                    parent_node = _get_tuple_node(node.parents, pos)
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

    def gc_sort(self):
        """Return a reverse topological ordering which is 'stable'.

        There are a few constraints:
          1) Reverse topological (all children before all parents)
          2) Grouped by prefix
          3) 'stable' sorting, so that we get the same result, independent of
             machine, or extra data.
        To do this, we use the same basic algorithm as topo_sort, but when we
        aren't sure what node to access next, we sort them lexicographically.
        """
        cdef PyObject *temp
        cdef Py_ssize_t pos, last_item
        cdef _KnownGraphNode node, node2, parent_node

        tips = self._find_tips()
        # Split the tips based on prefix
        prefix_tips = {}
        for pos from 0 <= pos < PyList_GET_SIZE(tips):
            node = _get_list_node(tips, pos)
            if PyBytes_CheckExact(node.key) or len(node.key) == 1:
                prefix = ''
            else:
                prefix = node.key[0]
            temp = PyDict_GetItem(prefix_tips, prefix)
            if temp == NULL:
                prefix_tips[prefix] = [node]
            else:
                tip_nodes = <object>temp
                PyList_Append(tip_nodes, node)

        result = []
        for prefix in sorted(prefix_tips):
            temp = PyDict_GetItem(prefix_tips, prefix)
            assert temp != NULL
            tip_nodes = <object>temp
            pending = _sort_list_nodes(tip_nodes, 1)
            last_item = PyList_GET_SIZE(pending) - 1
            while last_item >= 0:
                node = _get_list_node(pending, last_item)
                last_item = last_item - 1
                if node.parents is None:
                    # Ghost
                    continue
                PyList_Append(result, node.key)
                # Sorting the parent keys isn't strictly necessary for stable
                # sorting of a given graph. But it does help minimize the
                # differences between graphs
                # For bzr.dev ancestry:
                #   4.73ms  no sort
                #   7.73ms  RichCompareBool sort
                parents = _sort_list_nodes(node.parents, 1)
                for pos from 0 <= pos < len(parents):
                    if PyTuple_CheckExact(parents):
                        parent_node = _get_tuple_node(parents, pos)
                    else:
                        parent_node = _get_list_node(parents, pos)
                    # TODO: GraphCycle detection
                    parent_node.seen = parent_node.seen + 1
                    if (parent_node.seen
                        == PyList_GET_SIZE(parent_node.children)):
                        # All children have been processed, queue up this
                        # parent
                        last_item = last_item + 1
                        if last_item < PyList_GET_SIZE(pending):
                            Py_INCREF(parent_node) # SetItem steals a ref
                            PyList_SetItem(pending, last_item, parent_node)
                        else:
                            PyList_Append(pending, parent_node)
                        parent_node.seen = 0
        return result

    def merge_sort(self, tip_key):
        """Compute the merge sorted graph output."""
        cdef _MergeSorter sorter

        # TODO: consider disabling gc since we are allocating a lot of nodes
        #       that won't be collectable anyway. real world testing has not
        #       shown a specific impact, yet.
        sorter = _MergeSorter(self, tip_key)
        return sorter.topo_order()

    def get_parent_keys(self, key):
        """Get the parents for a key

        Returns a list containing the parents keys. If the key is a ghost,
        None is returned. A KeyError will be raised if the key is not in
        the graph.

        :param keys: Key to check (eg revision_id)
        :return: A list of parents
        """
        return self._nodes[key].parent_keys

    def get_child_keys(self, key):
        """Get the children for a key

        Returns a list containing the children keys. A KeyError will be raised
        if the key is not in the graph.

        :param keys: Key to check (eg revision_id)
        :return: A list of children
        """
        return self._nodes[key].child_keys


cdef class _MergeSortNode:
    """Tracks information about a node during the merge_sort operation."""

    # Public api
    cdef public object key
    cdef public long merge_depth
    cdef public object end_of_merge # True/False Is this the end of the current merge

    # Private api, used while computing the information
    cdef _KnownGraphNode left_parent
    cdef _KnownGraphNode left_pending_parent
    cdef object pending_parents # list of _KnownGraphNode for non-left parents
    cdef long _revno_first
    cdef long _revno_second
    cdef long _revno_last
    # TODO: turn these into flag/bit fields rather than individual members
    cdef int is_first_child # Is this the first child?
    cdef int seen_by_child # A child node has seen this parent
    cdef int completed # Fully Processed

    def __init__(self, key):
        self.key = key
        self.merge_depth = -1
        self.left_parent = None
        self.left_pending_parent = None
        self.pending_parents = None
        self._revno_first = -1
        self._revno_second = -1
        self._revno_last = -1
        self.is_first_child = 0
        self.seen_by_child = 0
        self.completed = 0

    def __repr__(self):
        return '%s(%s depth:%s rev:%s,%s,%s first:%s seen:%s)' % (
            self.__class__.__name__, self.key,
            self.merge_depth,
            self._revno_first, self._revno_second, self._revno_last,
            self.is_first_child, self.seen_by_child)

    cdef int has_pending_parents(self): # cannot_raise
        if self.left_pending_parent is not None or self.pending_parents:
            return 1
        return 0

    cdef object _revno(self):
        if self._revno_first == -1:
            if self._revno_second != -1:
                raise RuntimeError('Something wrong with: %s' % (self,))
            return (self._revno_last,)
        else:
            return (self._revno_first, self._revno_second, self._revno_last)

    property revno:
        def __get__(self):
            return self._revno()


cdef class _MergeSorter:
    """This class does the work of computing the merge_sort ordering.

    We have some small advantages, in that we get all the extra information
    that KnownGraph knows, like knowing the child lists, etc.
    """

    # Current performance numbers for merge_sort(bzr_dev_parent_map):
    #  302ms tsort.merge_sort()
    #   91ms graph.KnownGraph().merge_sort()
    #   40ms kg.merge_sort()

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
        if (tip_key is not None and tip_key != NULL_REVISION
            and tip_key != (NULL_REVISION,)):
            node = self.graph._nodes[tip_key]
            self._push_node(node, 0)

    cdef _MergeSortNode _get_ms_node(self, _KnownGraphNode node):
        cdef PyObject *temp_node
        cdef _MergeSortNode ms_node

        if node.extra is None:
            ms_node = _MergeSortNode(node.key)
            node.extra = ms_node
        else:
            ms_node = <_MergeSortNode>node.extra
        return ms_node

    cdef _push_node(self, _KnownGraphNode node, long merge_depth):
        cdef _KnownGraphNode parent_node
        cdef _MergeSortNode ms_node, ms_parent_node
        cdef Py_ssize_t pos

        ms_node = self._get_ms_node(node)
        ms_node.merge_depth = merge_depth
        if node.parents is None:
            raise RuntimeError('ghost nodes should not be pushed'
                               ' onto the stack: %s' % (node,))
        if PyTuple_GET_SIZE(node.parents) > 0:
            parent_node = _get_tuple_node(node.parents, 0)
            ms_node.left_parent = parent_node
            if parent_node.parents is None: # left-hand ghost
                ms_node.left_pending_parent = None
                ms_node.left_parent = None
            else:
                ms_node.left_pending_parent = parent_node
        if PyTuple_GET_SIZE(node.parents) > 1:
            ms_node.pending_parents = []
            for pos from 1 <= pos < PyTuple_GET_SIZE(node.parents):
                parent_node = _get_tuple_node(node.parents, pos)
                if parent_node.parents is None: # ghost
                    continue
                PyList_Append(ms_node.pending_parents, parent_node)

        ms_node.is_first_child = 1
        if ms_node.left_parent is not None:
            ms_parent_node = self._get_ms_node(ms_node.left_parent)
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

    cdef _pop_node(self):
        cdef PyObject *temp
        cdef _MergeSortNode ms_node, ms_parent_node, ms_prev_node
        cdef _KnownGraphNode node, parent_node, prev_node

        node = _get_list_node(self._depth_first_stack, self._last_stack_item)
        ms_node = <_MergeSortNode>node.extra
        self._last_stack_item = self._last_stack_item - 1
        if ms_node.left_parent is not None:
            # Assign the revision number from the left-hand parent
            ms_parent_node = <_MergeSortNode>ms_node.left_parent.extra
            if ms_node.is_first_child:
                # First child just increments the final digit
                ms_node._revno_first = ms_parent_node._revno_first
                ms_node._revno_second = ms_parent_node._revno_second
                ms_node._revno_last = ms_parent_node._revno_last + 1
            else:
                # Not the first child, make a new branch
                #  (mainline_revno, branch_count, 1)
                if ms_parent_node._revno_first == -1:
                    # Mainline ancestor, the increment is on the last digit
                    base_revno = ms_parent_node._revno_last
                else:
                    base_revno = ms_parent_node._revno_first
                temp = PyDict_GetItem(self._revno_to_branch_count,
                                      base_revno)
                if temp == NULL:
                    branch_count = 1
                else:
                    branch_count = (<object>temp) + 1
                PyDict_SetItem(self._revno_to_branch_count, base_revno,
                               branch_count)
                ms_node._revno_first = base_revno
                ms_node._revno_second = branch_count
                ms_node._revno_last = 1
        else:
            temp = PyDict_GetItem(self._revno_to_branch_count, 0)
            if temp == NULL:
                # The first root node doesn't have a 3-digit revno
                root_count = 0
                ms_node._revno_first = -1
                ms_node._revno_second = -1
                ms_node._revno_last = 1
            else:
                root_count = (<object>temp) + 1
                ms_node._revno_first = 0
                ms_node._revno_second = root_count
                ms_node._revno_last = 1
            PyDict_SetItem(self._revno_to_branch_count, 0, root_count)
        ms_node.completed = 1
        if PyList_GET_SIZE(self._scheduled_nodes) == 0:
            # The first scheduled node is always the end of merge
            ms_node.end_of_merge = True
        else:
            prev_node = _get_list_node(self._scheduled_nodes,
                                    PyList_GET_SIZE(self._scheduled_nodes) - 1)
            ms_prev_node = <_MergeSortNode>prev_node.extra
            if ms_prev_node.merge_depth < ms_node.merge_depth:
                # The previously pushed node is to our left, so this is the end
                # of this right-hand chain
                ms_node.end_of_merge = True
            elif (ms_prev_node.merge_depth == ms_node.merge_depth
                  and prev_node not in node.parents):
                # The next node is not a direct parent of this node
                ms_node.end_of_merge = True
            else:
                ms_node.end_of_merge = False
        PyList_Append(self._scheduled_nodes, node)

    cdef _schedule_stack(self):
        cdef _KnownGraphNode last_node, next_node
        cdef _MergeSortNode ms_node, ms_last_node, ms_next_node
        cdef long next_merge_depth
        ordered = []
        while self._last_stack_item >= 0:
            # Peek at the last item on the stack
            last_node = _get_list_node(self._depth_first_stack,
                                       self._last_stack_item)
            if last_node.gdfo == -1:
                # if _find_gdfo skipped a node, that means there is a graph
                # cycle, error out now
                raise errors.GraphCycleError(self.graph._nodes)
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
                    # the scheduled queue.
                    # Note: This has the effect of allocating common-new
                    #       revisions to the right-most subtree rather than the
                    #       left most, which will display nicely (you get
                    #       smaller trees at the top of the combined merge).
                    next_node = ms_last_node.pending_parents.pop()
                ms_next_node = self._get_ms_node(next_node)
                if ms_next_node.completed:
                    # this parent was completed by a child on the
                    # call stack. skip it.
                    continue
                # otherwise transfer it from the source graph into the
                # top of the current depth first search stack.

                if next_node is ms_last_node.left_parent:
                    next_merge_depth = ms_last_node.merge_depth
                else:
                    next_merge_depth = ms_last_node.merge_depth + 1
                self._push_node(next_node, next_merge_depth)
                # and do not continue processing parents until this 'call'
                # has recursed.
                break

    cdef topo_order(self):
        cdef _MergeSortNode ms_node
        cdef _KnownGraphNode node
        cdef Py_ssize_t pos
        cdef PyObject *temp_key
        cdef PyObject *temp_node

        # Note: allocating a _MergeSortNode and deallocating it for all nodes
        #       costs approx 8.52ms (21%) of the total runtime
        #       We might consider moving the attributes into the base
        #       KnownGraph object.
        self._schedule_stack()

        # We've set up the basic schedule, now we can continue processing the
        # output.
        # Note: This final loop costs us 40.0ms => 28.8ms (11ms, 25%) on
        #       bzr.dev, to convert the internal Object representation into a
        #       Tuple representation...
        #       2ms is walking the data and computing revno tuples
        #       7ms is computing the return tuple
        #       4ms is PyList_Append()
        ordered = []
        # output the result in reverse order, and separate the generated info
        for pos from PyList_GET_SIZE(self._scheduled_nodes) > pos >= 0:
            node = _get_list_node(self._scheduled_nodes, pos)
            ms_node = <_MergeSortNode>node.extra
            PyList_Append(ordered, ms_node)
            node.extra = None
        # Clear out the scheduled nodes now that we're done
        self._scheduled_nodes = []
        return ordered
