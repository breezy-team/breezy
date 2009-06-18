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
    Py_ssize_t PyDict_Size(object d) except -1
    int PyDict_CheckExact(object d)
    int PyDict_Next(object d, Py_ssize_t *pos, PyObject **k, PyObject **v)
    int PyList_Append(object l, object v) except -1
    PyObject * PyList_GET_ITEM(object l, Py_ssize_t o)
    Py_ssize_t PyList_GET_SIZE(object l)
    int PyDict_SetItem(object d, object k, object v) except -1
    int PySet_Add(object s, object k) except -1
    void Py_INCREF(object)


from bzrlib import revision

cdef class _KnownGraphNode:
    """Represents a single object in the known graph."""

    cdef object key
    cdef object parents
    cdef object children
    cdef public object gdfo # Int

    def __init__(self, key):
        cdef int i

        self.key = key
        self.parents = None

        self.children = []
        # Greatest distance from origin
        self.gdfo = -1

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
            parent_keys, child_keysr)


# TODO: slab allocate all _KnownGraphNode objects.
#       We already know how many we are going to need, except for a couple of
#       ghosts that could be allocated on demand.

cdef class KnownGraph:
    """This is a class which assumes we already know the full graph."""

    cdef public object _nodes
    cdef public object _tails
    cdef object _known_heads
    cdef public int do_cache

    def __init__(self, parent_map, do_cache=True):
        """Create a new KnownGraph instance.

        :param parent_map: A dictionary mapping key => parent_keys
        """
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

    cdef _KnownGraphNode _get_or_create_node(self, key, int *created):
        cdef PyObject *temp_node
        cdef _KnownGraphNode node

        temp_node = PyDict_GetItem(self._nodes, key)
        if temp_node == NULL:
            node = _KnownGraphNode(key)
            PyDict_SetItem(self._nodes, key, node)
            created[0] = 1 # True
        else:
            node = <_KnownGraphNode>temp_node
            created[0] = 0 # False
        return node

    def _initialize_nodes(self, parent_map):
        """Populate self._nodes.

        After this has finished:
        - self._nodes will have an entry for every entry in parent_map.
        - ghosts will have a parent_keys = None,
        - all nodes found will also have .child_keys populated with all known
          child_keys,
        - self._tails will list all the nodes without parents.
        """
        cdef PyObject *temp_key, *temp_parent_keys, *temp_node
        cdef Py_ssize_t pos, pos2, num_parent_keys
        cdef _KnownGraphNode node
        cdef _KnownGraphNode parent_node
        cdef int created

        tails = self._tails = set()
        nodes = self._nodes

        if not PyDict_CheckExact(parent_map):
            raise TypeError('parent_map should be a dict of {key:parent_keys}')
        # for key, parent_keys in parent_map.iteritems():
        pos = 0
        while PyDict_Next(parent_map, &pos, &temp_key, &temp_parent_keys):
            key = <object>temp_key
            parent_keys = <object>temp_parent_keys
            num_parent_keys = len(parent_keys)
            node = self._get_or_create_node(key, &created)
            if not created and num_parent_keys != 0:
                # This node has been added before being seen in parent_map (see
                # below)
                tails.remove(node)
            # We know how many parents, so we could pre allocate an exact sized
            # tuple here
            parent_nodes = PyTuple_New(num_parent_keys)
            # We use iter here, because parent_keys maybe be a list or tuple
            for pos2 from 0 <= pos2 < num_parent_keys:
                parent_node = self._get_or_create_node(parent_keys[pos2],
                                                       &created)
                if created:
                    # Potentially a tail, if we're wrong we'll remove it later
                    # (see above)
                    tails.add(parent_node)
                # PyTuple_SET_ITEM will steal a reference, so INCREF first
                Py_INCREF(parent_node)
                PyTuple_SET_ITEM(parent_nodes, pos2, parent_node)
                PyList_Append(parent_node.children, node)
            node.parents = parent_nodes

    def _find_gdfo(self):
        cdef _KnownGraphNode node
        cdef _KnownGraphNode child

        nodes = self._nodes
        pending = []
        known_parent_gdfos = {}

        for node in self._tails:
            node.gdfo = 1
            known_parent_gdfos[node] = 0
            pending.append(node)

        while pending:
            node = <_KnownGraphNode>pending.pop()
            for child in node.children:
                try:
                    known_parents = known_parent_gdfos[child.key]
                except KeyError:
                    known_parents = 0
                known_parent_gdfos[child.key] = known_parents + 1
                if child.gdfo is None or node.gdfo + 1 > child.gdfo:
                    child.gdfo = node.gdfo + 1
                if known_parent_gdfos[child.key] == len(child.parents):
                    # We are the last parent updating that node, we can
                    # continue from there
                    pending.append(child)

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

        seen = set()
        pending = []
        cdef Py_ssize_t pos
        pos = 0
        min_gdfo = None
        while PyDict_Next(candidate_nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            if node.parents is not None:
                pending.extend(node.parents)
            if min_gdfo is None or node.gdfo < min_gdfo:
                min_gdfo = node.gdfo
        nodes = self._nodes
        while pending:
            node = pending.pop()
            if node.key in seen:
                # node already appears in some ancestry
                continue
            seen.add(node.key)
            if node.gdfo <= min_gdfo:
                continue
            if node.parents:
                pending.extend(node.parents)
        heads = heads_key.difference(seen)
        if self.do_cache:
            self._known_heads[heads_key] = heads
        return heads
