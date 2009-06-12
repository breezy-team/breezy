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

    object PyFrozenSet_New(object)
    object PyTuple_New(Py_ssize_t n)
    void PyTuple_SET_ITEM(object t, Py_ssize_t o, object v)
    PyObject * PyTuple_GET_ITEM(object t, Py_ssize_t o)
    Py_ssize_t PyTuple_GET_SIZE(object t)
    PyObject * PyDict_GetItem(object d, object k)
    PyObject * PyDict_GetItem(object d, object k)
    Py_ssize_t PyDict_Size(object d) except -1
    int PyDict_CheckExact(object d)
    int PyDict_Next(object d, Py_ssize_t *pos, PyObject **k, PyObject **v)
    int PyList_Append(object l, object v) except -1
    PyObject * PyList_GET_ITEM(object l, Py_ssize_t o)
    Py_ssize_t PyList_GET_SIZE(object l)
    int PyDict_SetItem(object d, object k, object v) except -1
    int PySet_Add(object s, object k) except -1
    void Py_INCREF(object)


import heapq

from bzrlib import revision

# Define these as cdef objects, so we don't have to getattr them later
cdef object heappush, heappop, heapify, heapreplace
heappush = heapq.heappush
heappop = heapq.heappop
heapify = heapq.heapify
heapreplace = heapq.heapreplace


cdef class _KnownGraphNode:
    """Represents a single object in the known graph."""

    cdef object key
    cdef object parents
    cdef object children
    cdef _KnownGraphNode linear_dominator_node
    cdef public long dominator_distance
    cdef public object gdfo # Int
    # This could also be simplified
    cdef object ancestor_of

    def __init__(self, key):
        cdef int i

        self.key = key
        self.parents = None

        self.children = []
        # oldest ancestor, such that no parents between here and there have >1
        # child or >1 parent.
        self.linear_dominator_node = None
        self.dominator_distance = 0
        # Greatest distance from origin
        self.gdfo = -1
        # This will become a tuple of known heads that have this node as an
        # ancestor
        self.ancestor_of = None

    property child_keys:
        def __get__(self):
            cdef _KnownGraphNode child

            keys = []
            for child in self.children:
                PyList_Append(keys, child.key)
            return keys

    property linear_dominator:
        def __get__(self):
            if self.linear_dominator_node is None:
                return None
            else:
                return self.linear_dominator_node.key

    cdef clear_references(self):
        self.parents = None
        self.children = None
        self.linear_dominator_node = None

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
        return '%s(%s  gdfo:%s par:%s child:%s dom:%s %s)' % (
            self.__class__.__name__, self.key, self.gdfo,
            parent_keys, child_keys,
            self.linear_dominator, self.dominator_distance)


# TODO: slab allocate all _KnownGraphNode objects.
#       We already know how many we are going to need, except for a couple of
#       ghosts that could be allocated on demand.

cdef class KnownGraph:
    """This is a class which assumes we already know the full graph."""

    cdef public object _nodes
    cdef object _known_heads
    cdef public int do_cache
    # Nodes we've touched that we'll need to reset their info when heads() is
    # done
    cdef object _to_cleanup

    def __init__(self, parent_map, do_cache=True):
        """Create a new KnownGraph instance.

        :param parent_map: A dictionary mapping key => parent_keys
        """
        self._nodes = {}
        # Maps {sorted(revision_id, revision_id): heads}
        self._known_heads = {}
        self._to_cleanup = []
        self.do_cache = int(do_cache)
        self._initialize_nodes(parent_map)
        self._find_linear_dominators()
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

        After this has finished, self._nodes will have an entry for every entry
        in parent_map. Ghosts will have a parent_keys = None, all nodes found
        will also have .child_keys populated with all known child_keys.
        """
        cdef PyObject *temp_key, *temp_parent_keys, *temp_node
        cdef Py_ssize_t pos, pos2, num_parent_keys
        cdef _KnownGraphNode node
        cdef _KnownGraphNode parent_node

        nodes = self._nodes

        if not PyDict_CheckExact(parent_map):
            raise TypeError('parent_map should be a dict of {key:parent_keys}')
        # for key, parent_keys in parent_map.iteritems():
        pos = 0
        while PyDict_Next(parent_map, &pos, &temp_key, &temp_parent_keys):
            key = <object>temp_key
            parent_keys = <object>temp_parent_keys
            node = self._get_or_create_node(key)
            assert node.parents is None
            # We know how many parents, so we could pre allocate an exact sized
            # tuple here
            num_parent_keys = len(parent_keys)
            parent_nodes = PyTuple_New(num_parent_keys)
            # We use iter here, because parent_keys maybe be a list or tuple
            for pos2 from 0 <= pos2 < num_parent_keys:
                parent_key = parent_keys[pos2]
                parent_node = self._get_or_create_node(parent_keys[pos2])
                # PyTuple_SET_ITEM will steal a reference, so INCREF first
                Py_INCREF(parent_node)
                PyTuple_SET_ITEM(parent_nodes, pos2, parent_node)
                PyList_Append(parent_node.children, node)
            node.parents = parent_nodes

    cdef _KnownGraphNode _check_is_linear(self, _KnownGraphNode node):
        """Check to see if a given node is part of a linear chain."""
        cdef _KnownGraphNode parent_node
        if node.parents is None or PyTuple_GET_SIZE(node.parents) != 1:
            # This node is either a ghost, a tail, or has multiple parents
            # It its own dominator
            node.linear_dominator_node = node
            node.dominator_distance = 0
            return None
        parent_node = <_KnownGraphNode>PyTuple_GET_ITEM(node.parents, 0)
        if PyList_GET_SIZE(parent_node.children) > 1:
            # The parent has multiple children, so *this* node is the
            # dominator
            node.linear_dominator_node = node
            node.dominator_distance = 0
            return None
        # The parent is already filled in, so add and continue
        if parent_node.linear_dominator_node is not None:
            node.linear_dominator_node = parent_node.linear_dominator_node
            node.dominator_distance = parent_node.dominator_distance + 1
            return None
        # We don't know this node, or its parent node, so start walking to
        # next
        return parent_node

    def _find_linear_dominators(self):
        """For each node in the set, find any linear dominators.

        For any given node, the 'linear dominator' is an ancestor, such that
        all parents between this node and that one have a single parent, and a
        single child. So if A->B->C->D then B,C,D all have a linear dominator
        of A. Because there are no interesting siblings, we can quickly skip to
        the nearest dominator when doing comparisons.
        """
        cdef PyObject *temp_node
        cdef Py_ssize_t pos
        cdef _KnownGraphNode node
        cdef _KnownGraphNode next_node
        cdef _KnownGraphNode dominator
        cdef int i, num_elements

        pos = 0
        while PyDict_Next(self._nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            # The parent is not filled in, so walk until we get somewhere
            if node.linear_dominator_node is not None: #already done
                continue
            next_node = self._check_is_linear(node)
            if next_node is None:
                # Nothing more needs to be done
                continue
            stack = []
            while next_node is not None:
                PyList_Append(stack, node)
                node = next_node
                next_node = self._check_is_linear(node)
            # The stack now contains the linear chain, and 'node' should have
            # been labeled
            assert node.linear_dominator_node is not None
            dominator = node.linear_dominator_node
            num_elements = len(stack)
            for i from num_elements > i >= 0:
                temp_node = PyList_GET_ITEM(stack, i)
                next_node = <_KnownGraphNode>temp_node
                next_node.linear_dominator_node = dominator
                next_node.dominator_distance = node.dominator_distance + 1
                node = next_node

    cdef object _find_tails(self):
        cdef object tails
        cdef PyObject *temp_node
        cdef Py_ssize_t pos
        cdef _KnownGraphNode node

        tails = []
        pos = 0
        while PyDict_Next(self._nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            if node.parents is None or PyTuple_GET_SIZE(node.parents) == 0:
                PyList_Append(tails, node)
        return tails

    def _find_gdfo(self):
        cdef PyObject *temp_node, *temp_tuple
        cdef Py_ssize_t pos, pos2
        cdef _KnownGraphNode node
        cdef _KnownGraphNode child_node
        cdef _KnownGraphNode parent_node
        cdef int replace_node, missing_parent

        tails = self._find_tails()
        todo = []
        for pos from 0 <= pos < PyList_GET_SIZE(tails):
            temp_node = PyList_GET_ITEM(tails, pos)
            node = <_KnownGraphNode>temp_node
            node.gdfo = 1
            PyList_Append(todo, (1, node))
        # No need to heapify, because all tails have priority=1
        max_gdfo = len(self._nodes) + 1
        while PyList_GET_SIZE(todo) > 0:
            temp_tuple = PyList_GET_ITEM(todo, 0)
            t = <object>temp_tuple
            temp_node = PyTuple_GET_ITEM(t, 1)
            node = <_KnownGraphNode>temp_node
            next_gdfo = node.gdfo + 1
            assert next_gdfo <= max_gdfo
            replace_node = 1
            for pos from 0 <= pos < PyList_GET_SIZE(node.children):
                temp_node = PyList_GET_ITEM(node.children, pos)
                child_node = <_KnownGraphNode>temp_node
                # We should never have numbered children before we numbered
                # a parent
                if child_node.gdfo != -1:
                    assert child_node.gdfo >= next_gdfo
                    continue
                # Only enque children when all of their parents have been
                # resolved. With a single parent, we can just take 'this' value
                child_gdfo = next_gdfo
                if PyTuple_GET_SIZE(child_node.parents) > 1:
                    missing_parent = 0
                    for pos2 from 0 <= pos2 < PyTuple_GET_SIZE(child_node.parents):
                        temp_node = PyTuple_GET_ITEM(child_node.parents, pos2)
                        parent_node = <_KnownGraphNode>temp_node
                        if parent_node.gdfo == -1:
                            missing_parent = 1
                            break
                        if parent_node.gdfo >= child_gdfo:
                            child_gdfo = parent_node.gdfo + 1
                    if missing_parent:
                        # One of the parents is not numbered, so wait until we get
                        # back here
                        continue
                child_node.gdfo = child_gdfo
                if replace_node:
                    heapreplace(todo, (child_gdfo, child_node))
                    replace_node = 0
                else:
                    heappush(todo, (child_gdfo, child_node))
            if replace_node:
                heappop(todo)

    def heads(self, keys):
        """Return the heads from amongst keys.

        This is done by searching the ancestries of each key.  Any key that is
        reachable from another key is not returned; all the others are.

        This operation scales with the relative depth between any two keys. If
        any two keys are completely disconnected all ancestry of both sides
        will be retrieved.

        :param keys: An iterable of keys.
        :return: A set of the heads. Note that as a set there is no ordering
            information. Callers will need to filter their input to create
            order if they need it.
        """
        cdef PyObject *maybe_node
        cdef PyObject *maybe_heads

        heads_key = PyFrozenSet_New(keys)
        maybe_heads = PyDict_GetItem(self._known_heads, heads_key)
        if maybe_heads != NULL:
            return <object>maybe_heads

        # Not cached, compute it ourselves
        candidate_nodes = {}
        nodes = self._nodes
        for key in keys:
            maybe_node = PyDict_GetItem(nodes, key)
            if maybe_node == NULL:
                raise KeyError('key %s not in nodes' % (key,))
            PyDict_SetItem(candidate_nodes, key, <object>maybe_node)
        if revision.NULL_REVISION in candidate_nodes:
            # NULL_REVISION is only a head if it is the only entry
            candidate_nodes.pop(revision.NULL_REVISION)
            if not candidate_nodes:
                return set([revision.NULL_REVISION])
            # The keys changed, so recalculate heads_key
            heads_key = PyFrozenSet_New(candidate_nodes)
        if len(candidate_nodes) < 2:
            return heads_key
        # Check the linear dominators of these keys, to see if we already
        # know the heads answer
        dom_lookup_key, heads = self._heads_from_dominators(candidate_nodes)
        if heads is not None:
            if self.do_cache:
                # This heads was not in the cache, or it would have been caught
                # earlier, but the dom head *was*, so do the simple cache
                PyDict_SetItem(self._known_heads, heads_key, heads)
            return heads
        heads = self._heads_from_candidate_nodes(candidate_nodes)
        if self.do_cache:
            self._cache_heads(heads, heads_key, dom_lookup_key, candidate_nodes)
        return heads

    cdef object _cache_heads(self, heads, heads_key, dom_lookup_key,
                             candidate_nodes):
        cdef PyObject *maybe_node
        cdef _KnownGraphNode node

        PyDict_SetItem(self._known_heads, heads_key, heads)
        dom_heads = []
        for key in heads:
            maybe_node = PyDict_GetItem(candidate_nodes, key)
            if maybe_node == NULL:
                raise KeyError
            node = <_KnownGraphNode>maybe_node
            PyList_Append(dom_heads, node.linear_dominator_node.key)
        PyDict_SetItem(self._known_heads, dom_lookup_key,
                       PyFrozenSet_New(dom_heads))

    cdef object _heads_from_dominators(self, candidate_nodes):
        cdef PyObject *maybe_heads
        cdef PyObject *maybe_key
        cdef _KnownGraphNode node
        cdef Py_ssize_t pos
        cdef PyObject *temp_node

        dom_list_key = []
        pos = 0
        while PyDict_Next(candidate_nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            PyList_Append(dom_list_key, node.linear_dominator_node.key)
        dom_lookup_key = PyFrozenSet_New(dom_list_key)
        maybe_heads = PyDict_GetItem(self._known_heads, dom_lookup_key)
        if maybe_heads == NULL:
            return dom_lookup_key, None
        # We need to map back from the dominator head to the original keys
        dom_heads = <object>maybe_heads
        dom_to_key = {}
        pos = 0
        while PyDict_Next(candidate_nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            PyDict_SetItem(dom_to_key, node.linear_dominator_node.key,
                                       node.key)
        heads = []
        for dom_key in dom_heads:
            maybe_key = PyDict_GetItem(dom_to_key, dom_key)
            if maybe_key == NULL:
                # Should never happen
                raise KeyError
            PyList_Append(heads, <object>maybe_key)
        return dom_lookup_key, PyFrozenSet_New(heads)

    cdef int _process_parent(self, _KnownGraphNode node,
                             _KnownGraphNode parent_node,
                             candidate_nodes,
                             queue) except -1:
        """Process the parent of a node, seeing if we need to walk it.

        :return: 0 No extra work needed
                 1 This was a candidate node, and now there is only 1 candidate
                   left, so break out of the loop
        """
        cdef PyObject *maybe_candidate
        maybe_candidate = PyDict_GetItem(candidate_nodes, parent_node.key)
        if maybe_candidate != NULL:
            candidate_nodes.pop(parent_node.key)
            if len(candidate_nodes) <= 1:
                return 1
        if parent_node.ancestor_of is None:
            # This node hasn't been walked yet, so just project node's ancestor
            # info directly to parent_node, and enqueue it for later processing
            parent_node.ancestor_of = node.ancestor_of
            heappush(queue, (-parent_node.gdfo, parent_node))
            PyList_Append(self._to_cleanup, parent_node)
        elif parent_node.ancestor_of != node.ancestor_of:
            # Combine to get the full set of parents
            # Rewrite using PySet_* functions, unfortunately you have to use
            # PySet_Add since there is no PySet_Update... :(
            all_ancestors = set(parent_node.ancestor_of)
            for k in node.ancestor_of:
                PySet_Add(all_ancestors, k)
            parent_node.ancestor_of = tuple(sorted(all_ancestors))
        return 0

    cdef object _heads_from_candidate_nodes(self, candidate_nodes):
        cdef _KnownGraphNode node
        cdef _KnownGraphNode parent_node
        cdef Py_ssize_t num_candidates
        cdef int num_parents
        cdef Py_ssize_t pos
        cdef PyObject *temp_node

        queue = []
        pos = 0
        while PyDict_Next(candidate_nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            assert node.ancestor_of is None
            node.ancestor_of = (node.key,)
            PyList_Append(queue, (-node.gdfo, node))
            PyList_Append(self._to_cleanup, node)
        heapify(queue)
        # These are nodes that we determined are 'common' that we are no longer
        # walking
        # Now we walk nodes until all nodes that are being walked are 'common'
        num_candidates = len(candidate_nodes)
        while PyList_GET_SIZE(queue) > 0 and PyDict_Size(candidate_nodes) > 1:
            temp_node = PyTuple_GET_ITEM(heappop(queue), 1)
            node = <_KnownGraphNode>temp_node
            if PyTuple_GET_SIZE(node.ancestor_of) == num_candidates:
                # This node is now considered 'common'
                # Make sure all parent nodes are marked as such
                for pos from 0 <= pos < PyTuple_GET_SIZE(node.parents):
                    temp_node = PyTuple_GET_ITEM(node.parents, pos)
                    parent_node = <_KnownGraphNode>temp_node
                    if parent_node.ancestor_of is not None:
                        parent_node.ancestor_of = node.ancestor_of
                if node.linear_dominator_node is not node:
                    parent_node = node.linear_dominator_node
                    if parent_node.ancestor_of is not None:
                        parent_node.ancestor_of = node.ancestor_of
                continue
            if node.parents is None:
                # This is a ghost
                continue
            # Now project the current nodes ancestor list to the parent nodes,
            # and queue them up to be walked
            if node.linear_dominator_node is not node:
                # We are at the tip of a long linear region
                # We know that there is nothing between here and the tail
                # that is interesting, so skip to the end
                if (self._process_parent(node, node.linear_dominator_node,
                                         candidate_nodes, queue)):
                    break
            else:
               for pos from 0 <= pos < PyTuple_GET_SIZE(node.parents):
                   temp_node = PyTuple_GET_ITEM(node.parents, pos)
                   parent_node = <_KnownGraphNode>temp_node
                   if (self._process_parent(node, parent_node,
                                            candidate_nodes, queue)):
                       break
        for pos from 0 <= pos < PyList_GET_SIZE(self._to_cleanup):
            temp_node = PyList_GET_ITEM(self._to_cleanup, pos)
            node = <_KnownGraphNode>temp_node
            node.ancestor_of = None
        self._to_cleanup = []
        return PyFrozenSet_New(candidate_nodes)
