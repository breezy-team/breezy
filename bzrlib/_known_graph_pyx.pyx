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


from bzrlib import revision

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
        - all nodes found will also have child_keys populated with all known
          child keys,
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
        cdef PyObject *temp
        cdef Py_ssize_t child_pos
        cdef int replace
        cdef Py_ssize_t last_item
        cdef long known_gdfo
        cdef long next_gdfo

        pending = []
        # Setting this as an attribute of _KnownGraphNode drops 774ms => 621ms,
        # but adds a field that we won't use again. It avoids a dict lookup,
        # and using PyInt rather than plain 'long'.
        known_parent_gdfos = {}

        for node in self._tails:
            node.gdfo = 1
            PyList_Append(pending, node)

        last_item = PyList_GET_SIZE(pending) - 1
        while last_item >= 0:
            # Avoid pop followed by push, instead, peek, and replace
            # timing shows this is 930ms => 770ms for OOo
            node = _get_list_node(pending, last_item)
            last_item = last_item - 1
            next_gdfo = node.gdfo + 1
            for child_pos from 0 <= child_pos < PyList_GET_SIZE(node.children):
                child = _get_list_node(node.children, child_pos)
                temp = PyDict_GetItem(known_parent_gdfos, child.key)
                if temp == NULL:
                    known_gdfo = 1
                else:
                    known_gdfo = <object>temp
                    known_gdfo = known_gdfo + 1
                if next_gdfo > child.gdfo:
                    child.gdfo = next_gdfo
                if known_gdfo == PyTuple_GET_SIZE(child.parents):
                    # This child is populated, queue it to be walked
                    last_item = last_item + 1
                    if last_item < PyList_GET_SIZE(pending):
                        Py_INCREF(child) # SetItem steals a ref
                        PyList_SetItem(pending, last_item, child)
                    else:
                        PyList_Append(pending, child)
                    if temp != NULL:
                        # We are done with this node, remove it from
                        # known_parent_gdfos
                        PyDict_DelItem(known_parent_gdfos, child.key)
                else:
                    # Not done with this child, so make sure to track the
                    # number of known parents
                    PyDict_SetItem(known_parent_gdfos, child.key, known_gdfo)

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
        cdef Py_ssize_t pos
        cdef long min_gdfo

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
        maybe_node = PyDict_GetItem(candidate_nodes, NULL_REVISION)
        if maybe_node != NULL:
            # NULL_REVISION is only a head if it is the only entry
            candidate_nodes.pop(NULL_REVISION)
            if not candidate_nodes:
                return frozenset([NULL_REVISION])
            # The keys changed, so recalculate heads_key
            heads_key = PyFrozenSet_New(candidate_nodes)
        if PyDict_Size(candidate_nodes) < 2:
            return heads_key

        cleanup = []
        pending = []
        pending_pop = pending.pop
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
        while PyList_GET_SIZE(pending) > 0:
            node = _get_list_node(pending, PyList_GET_SIZE(pending) - 1)
            if node.seen:
                # node already appears in some ancestry
                pending_pop()
                continue
            PyList_Append(cleanup, node)
            node.seen = 1
            if node.gdfo <= min_gdfo:
                pending_pop()
                continue
            if node.parents is not None and PyTuple_GET_SIZE(node.parents) > 0:
                for pos from 0 <= pos < PyTuple_GET_SIZE(node.parents):
                    parent_node = _get_parent(node.parents, pos)
                    if pos == 0:
                        Py_INCREF(parent_node)
                        PyList_SetItem(pending, PyList_GET_SIZE(pending) - 1,
                                        parent_node)
                    else:
                        PyList_Append(pending, parent_node)
            else:
                pending_pop()
        heads = []
        pos = 0
        while PyDict_Next(candidate_nodes, &pos, NULL, &temp_node):
            node = <_KnownGraphNode>temp_node
            if not node.seen:
                PyList_Append(heads, node.key)
        heads = PyFrozenSet_New(heads)
        for pos from 0 <= pos < PyList_GET_SIZE(cleanup):
            node = _get_list_node(cleanup, pos)
            node.seen = 0
        if self.do_cache:
            PyDict_SetItem(self._known_heads, heads_key, heads)
        return heads
