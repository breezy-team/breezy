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
    PyObject * PyDict_GetItem(object d, object k)
    int PyDict_SetItem(object d, object k, object v) except -1
    int PySet_Add(object s, object k) except -1
    void Py_INCREF(object)


import heapq

from bzrlib import revision

heappush = heapq.heappush
heappop = heapq.heappop


cdef class _KnownGraphNode:
    """Represents a single object in the known graph."""

    cdef object key
    # 99% of all revisions have <= 2 parents, so we pre-allocate space for it,
    # but allow the flexibility of having N parents
    cdef _KnownGraphNode left_parent
    cdef _KnownGraphNode right_parent
    cdef list parents
    cdef list children
    cdef _KnownGraphNode linear_dominator_node
    cdef public long dominator_distance
    cdef public object gdfo # Int
    # This could also be simplified
    cdef object ancestor_of

    def __init__(self, key, parents):
        cdef _KnownGraphNode _parent_node
        cdef int i

        self.key = key
        self.left_parent = None
        self.right_parent = None
        self.set_parents(parents)

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
            cdef list keys
            cdef _KnownGraphNode child

            keys = []
            for child in self.children:
                keys.append(child.key)
            return keys

    property linear_dominator:
        def __get__(self):
            if self.linear_dominator_node is None:
                return None
            else:
                return self.linear_dominator_node.key

    cdef set_parents(self, list parents):
        cdef int num_parents
        self.parents = parents
        if parents is None:
            return
        num_parents = len(self.parents)
        if num_parents > 2:
            # No special ops
            return
        if num_parents > 0:
            self.left_parent = self.parents[0]
        if num_parents > 1:
            self.right_parent = self.parents[1]

    cdef clear_references(self):
        self.parents = None
        self.children = None
        self.linear_dominator_node = None
        self.left_parent = None
        self.right_parent = None

    def __repr__(self):
        parent_keys = []
        for parent in self.parents:
            parent_keys.append(parent.key)
        child_keys = []
        for child in self.children:
            child_keys.append(child.key)
        return '%s(%s  gdfo:%s par:%s child:%s dom:%s %s)' % (
            self.__class__.__name__, self.key, self.gdfo,
            parent_keys, child_keys,
            self.linear_dominator, self.dominator_distance)


# TODO: slab allocate all _KnownGraphNode objects.
#       We already know how many we are going to need...

cdef class KnownGraph:
    """This is a class which assumes we already know the full graph."""

    cdef public object _nodes
    cdef dict _known_heads
    cdef public int do_cache
    # Nodes we've touched that we'll need to reset their info when heads() is
    # done
    cdef list _to_cleanup

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

        for child in self._nodes.itervalues():
            child.clear_references()

    def _initialize_nodes(self, parent_map):
        """Populate self._nodes.

        After this has finished, self._nodes will have an entry for every entry
        in parent_map. Ghosts will have a parent_keys = None, all nodes found
        will also have .child_keys populated with all known child_keys.
        """
        cdef _KnownGraphNode node
        cdef _KnownGraphNode parent_node
        cdef list parent_nodes
        cdef dict nodes

        nodes = self._nodes

        for key, parent_keys in parent_map.iteritems():
            parent_nodes = []
            for parent_key in parent_keys:
                try:
                    parent_node = nodes[parent_key]
                except KeyError:
                    parent_node = _KnownGraphNode(parent_key, None)
                    nodes[parent_key] = parent_node
                parent_nodes.append(parent_node)
            if key in nodes:
                node = nodes[key]
                assert node.parents is None
                node.set_parents(parent_nodes)
            else:
                node = _KnownGraphNode(key, parent_nodes)
                nodes[key] = node
            for parent_node in parent_nodes:
                parent_node.children.append(node)

    cdef object _check_is_linear(self, _KnownGraphNode node):
        """Check to see if a given node is part of a linear chain."""
        cdef _KnownGraphNode parent_node
        if node.parents is None or len(node.parents) != 1:
            # This node is either a ghost, a tail, or has multiple parents
            # It its own dominator
            node.linear_dominator_node = node
            node.dominator_distance = 0
            return None
        parent_node = node.parents[0]
        if len(parent_node.children) > 1:
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
        cdef _KnownGraphNode node
        cdef _KnownGraphNode next_node
        cdef list stack

        for node in self._nodes.itervalues():
            # The parent is not filled in, so walk until we get somewhere
            if node.linear_dominator_node is not None: #already done
                continue
            next_node = self._check_is_linear(node)
            if next_node is None:
                # Nothing more needs to be done
                continue
            stack = []
            while next_node is not None:
                stack.append(node)
                node = next_node
                next_node = self._check_is_linear(node)
            # The stack now contains the linear chain, and 'node' should have
            # been labeled
            assert node.linear_dominator_node is not None
            dominator = node.linear_dominator_node
            while stack:
                next_node = stack.pop()
                next_node.linear_dominator_node = dominator
                next_node.dominator_distance = node.dominator_distance + 1
                node = next_node

    cdef list _find_tails(self):
        cdef list tails
        cdef _KnownGraphNode node
        tails = []

        for node in self._nodes.itervalues():
            if not node.parents:
                tails.append(node)
        return tails

    def _find_gdfo(self):
        # TODO: Consider moving the tails search into the first-pass over the
        #       data, inside _find_linear_dominators
        cdef _KnownGraphNode node
        cdef _KnownGraphNode child_node
        cdef _KnownGraphNode parent_node

        tails = self._find_tails()
        todo = []
        heappush = heapq.heappush
        heappop = heapq.heappop
        for node in tails:
            node.gdfo = 1
            heappush(todo, (1, node))
        processed = 0
        max_gdfo = len(self._nodes) + 1
        while todo:
            gdfo, node = heappop(todo)
            processed += 1
            if node.gdfo != -1 and gdfo < node.gdfo:
                # This node was reached from a longer path, we assume it was
                # enqued correctly with the longer gdfo, so don't continue
                # processing now
                continue
            next_gdfo = gdfo + 1
            assert next_gdfo <= max_gdfo
            for child_node in node.children:
                if child_node.gdfo < next_gdfo:
                    # Only enque children when all of their parents have been
                    # resolved
                    for parent_node in child_node.parents:
                        # We know that 'this' parent is counted
                        if parent_node is not node:
                            if parent_node.gdfo == -1:
                                break
                    else:
                        child_node.gdfo = next_gdfo
                        heappush(todo, (next_gdfo, child_node))

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
        cdef dict candidate_nodes
        cdef dict dom_to_node
        cdef dict nodes
        cdef _KnownGraphNode node
        cdef PyObject *maybe_node

        candidate_nodes = {}
        nodes = self._nodes
        for key in keys:
            # node = nodes[key]
            # candidate_nodes[key] = node
            maybe_node = PyDict_GetItem(nodes, key)
            if maybe_node == NULL:
                raise KeyError('key %s not in nodes' % (key,))
            PyDict_SetItem(candidate_nodes, key, <object>maybe_node)
        if revision.NULL_REVISION in candidate_nodes:
            # NULL_REVISION is only a head if it is the only entry
            candidate_nodes.pop(revision.NULL_REVISION)
            if not candidate_nodes:
                return set([revision.NULL_REVISION])
        heads_key = PyFrozenSet_New(candidate_nodes)
        if len(candidate_nodes) < 2:
            return heads_key
        try:
            heads = self._known_heads[heads_key]
            return heads
        except KeyError:
            pass # compute it ourselves
        # Check the linear dominators of these keys, to see if we already
        # know the heads answer
        dom_lookup_key, heads = self._heads_from_dominators(
                                    candidate_nodes.values())
        if heads is not None:
            return heads
        heads = self._heads_from_candidate_nodes(candidate_nodes)
        if self.do_cache:
            self._cache_heads(heads, heads_key, dom_lookup_key, candidate_nodes)
        return heads

    cdef object _cache_heads(self, heads, heads_key, dom_lookup_key,
                             candidate_nodes):
        cdef list dom_heads
        cdef PyObject *maybe_node
        cdef _KnownGraphNode node

        PyDict_SetItem(self._known_heads, heads_key, heads)
        dom_heads = []
        for key in heads:
            maybe_node = PyDict_GetItem(candidate_nodes, key)
            if maybe_node == NULL:
                raise KeyError
            node = <object>maybe_node
            dom_heads.append(node.linear_dominator_node.key)
        PyDict_SetItem(self._known_heads, dom_lookup_key,
                       PyFrozenSet_New(dom_heads))

    cdef object _heads_from_dominators(self, list candidates):
        cdef PyObject *test_heads
        cdef PyObject *test_key
        cdef list heads, dom_list_key
        cdef _KnownGraphNode node

        dom_list_key = []
        for node in candidates:
            dom_list_key.append(node.linear_dominator_node.key)
        dom_lookup_key = PyFrozenSet_New(dom_list_key)
        test_heads = PyDict_GetItem(self._known_heads, dom_lookup_key)
        if test_heads == NULL:
            return dom_lookup_key, None
        # We need to map back to the original keys
        dom_heads = <object>test_heads
        dom_to_key = {}
        for node in candidates:
            PyDict_SetItem(dom_to_key, node.linear_dominator_node.key,
                                       node.key)
        heads = []
        for dom_key in dom_heads:
            test_key = PyDict_GetItem(dom_to_key, dom_key)
            if test_key == NULL:
                # Should never happen
                raise KeyError
            heads.append(<object>test_key)
        return dom_lookup_key, PyFrozenSet_New(heads)

    cdef int _process_parent(self, _KnownGraphNode node,
                             _KnownGraphNode parent_node,
                             dict candidate_nodes,
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
            self._to_cleanup.append(parent_node)
        elif parent_node.ancestor_of != node.ancestor_of:
            # Combine to get the full set of parents
            # Rewrite using PySet_* functions, unfortunately you have to use
            # PySet_Add since there is no PySet_Update... :(
            all_ancestors = set(parent_node.ancestor_of)
            for k in node.ancestor_of:
                PySet_Add(all_ancestors, k)
            parent_node.ancestor_of = tuple(sorted(all_ancestors))
        return 0

    cdef object _heads_from_candidate_nodes(self, dict candidate_nodes):
        cdef _KnownGraphNode node
        cdef _KnownGraphNode parent_node
        cdef int num_candidates
        cdef int num_parents
        cdef list queue

        queue = []
        for node in candidate_nodes.itervalues():
            assert node.ancestor_of is None
            node.ancestor_of = (node.key,)
            queue.append((-node.gdfo, node))
            self._to_cleanup.append(node)
        heapq.heapify(queue)
        # These are nodes that we determined are 'common' that we are no longer
        # walking
        # Now we walk nodes until all nodes that are being walked are 'common'
        num_candidates = len(candidate_nodes)
        heappop = heapq.heappop
        heappush = heapq.heappush
        while len(queue) > 0 and len(candidate_nodes) > 1:
            _, node = heappop(queue)
            if len(node.ancestor_of) == num_candidates:
                # This node is now considered 'common'
                # Make sure all parent nodes are marked as such
                for parent_node in node.parents:
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
            # Note: using linear_dominator speeds things up quite a bit
            #       enough that we actually start to be slightly faster
            #       than the default heads() implementation
            if node.linear_dominator_node is not node:
                # We are at the tip of a long linear region
                # We know that there is nothing between here and the tail
                # that is interesting, so skip to the end
                if (self._process_parent(node, node.linear_dominator_node,
                                         candidate_nodes, queue)):
                    break
            else:
                num_parents = len(node.parents)
                if num_parents > 2:
                   for parent_node in node.parents:
                       if (self._process_parent(node, parent_node,
                                                candidate_nodes, queue)):
                           break
                else:
                    if num_parents > 0:
                        if (self._process_parent(node, node.left_parent,
                                                 candidate_nodes, queue)):
                            break
                    if num_parents > 1:
                        if (self._process_parent(node, node.right_parent,
                                                 candidate_nodes, queue)):
                            break
        for node in self._to_cleanup:
            node.ancestor_of = None
        self._to_cleanup = []
        return PyFrozenSet_New(candidate_nodes)
