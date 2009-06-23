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

"""Functionality for doing annotations in the 'optimal' way"""

cdef extern from "python-compat.h":
    pass

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef struct PyObject:
        pass
    int PyList_CheckExact(object)
    PyObject *PyList_GET_ITEM(object, Py_ssize_t o)
    Py_ssize_t PyList_GET_SIZE(object)
    int PyList_Append(object, object) except -1
    int PyList_SetItem(object, Py_ssize_t o, object) except -1
    int PyList_Sort(object) except -1

    int PyTuple_CheckExact(object)
    object PyTuple_New(Py_ssize_t len)
    void PyTuple_SET_ITEM(object, Py_ssize_t pos, object)
    int PyTuple_Resize(PyObject **, Py_ssize_t newlen)
    PyObject *PyTuple_GET_ITEM(object, Py_ssize_t o)
    Py_ssize_t PyTuple_GET_SIZE(object)

    PyObject *PyDict_GetItem(object d, object k)
    int PyDict_SetItem(object d, object k, object v) except -1

    void Py_INCREF(object)

    int Py_EQ
    int PyObject_RichCompareBool(object, object, int opid) except -1

from bzrlib import errors, graph as _mod_graph, osutils, patiencediff, ui

import time


counters = {}
cdef object _counters
_counters = counters

cdef _update_counter(name, value):
    _counters[name] = value + _counters.setdefault(name, 0)

def update_counter(name, value):
    _update_counter(name, value)

cdef object c
c = time.clock

cdef class _NeededTextIterator:

    cdef object counter
    cdef object text_cache
    cdef object stream
    cdef object stream_len
    cdef object pb

    def __init__(self, stream, text_cache, stream_len, pb=None):
        self.counter = 0
        self.stream = stream
        self.stream_len = stream_len
        self.text_cache = text_cache
        self.stream_len = stream_len
        self.pb = pb

    def __iter__(self):
        return self

    def __next__(self):
        record = self.stream.next()
        if self.pb is not None:
            self.pb.update('extracting', self.counter, self.stream_len)
        self.counter = self.counter + 1
        lines = osutils.chunks_to_lines(record.get_bytes_as('chunked'))
        num_lines = len(lines)
        self.text_cache[record.key] = lines
        return record.key, lines, num_lines


cdef int _check_annotations_are_lists(annotations,
                                      parent_annotations) except -1:
    if not PyList_CheckExact(annotations):
        raise TypeError('annotations must be a list')
    if not PyList_CheckExact(parent_annotations):
        raise TypeError('parent_annotations must be a list')
    return 0


cdef int _check_match_ranges(parent_annotations, annotations,
                         Py_ssize_t parent_idx, Py_ssize_t lines_idx,
                         Py_ssize_t match_len) except -1:
    if parent_idx + match_len > PyList_GET_SIZE(parent_annotations):
        raise ValueError('Match length exceeds len of'
                         ' parent_annotations %s > %s'
                         % (parent_idx + match_len,
                            PyList_GET_SIZE(parent_annotations)))
    if lines_idx + match_len > PyList_GET_SIZE(annotations):
        raise ValueError('Match length exceeds len of'
                         ' annotations %s > %s'
                         % (lines_idx + match_len,
                            PyList_GET_SIZE(annotations)))
    return 0


cdef object _combine_annotations(ann_one, ann_two, cache):
    """Combine the annotations from both sides."""
    cdef Py_ssize_t pos_one, pos_two, len_one, len_two
    cdef Py_ssize_t out_pos
    cdef PyObject *temp

    cache_key = (ann_one, ann_two)
    temp = PyDict_GetItem(cache, cache_key)
    if temp != NULL:
        return <object>temp

    if not PyTuple_CheckExact(ann_one) or not PyTuple_CheckExact(ann_two):
        raise TypeError('annotations must be tuples')
    # We know that annotations are tuples, and that both sides are already
    # sorted, so we can just walk and update a new list.
    len_one = PyTuple_GET_SIZE(ann_one)
    len_two = PyTuple_GET_SIZE(ann_two)
    if len_one < 1 or len_two < 1:
        raise ValueError('annotations cannot claim 0 references.')
    pos_one = 0
    pos_two = 0
    out_pos = 0
    temp = PyTuple_GET_ITEM(ann_one, pos_one); left = <object>temp
    temp = PyTuple_GET_ITEM(ann_two, pos_two); right = <object>temp
    new_ann = PyTuple_New(len_one + len_two)
    while left is not None or right is not None:
        if PyObject_RichCompareBool(left, right, Py_EQ):
            # Append once, increment both
            Py_INCREF(left)
            PyTuple_SET_ITEM(new_ann, out_pos, left)
            pos_one = pos_one + 1
            pos_two = pos_two + 1
            if pos_one >= len_one:
                left = None
            else:
                temp = PyTuple_GET_ITEM(ann_one, pos_one); left = <object>temp
            if pos_two >= len_two:
                right = None
            else:
                temp = PyTuple_GET_ITEM(ann_two, pos_two); right = <object>temp
        elif right is None or (left is not None and left < right):
            Py_INCREF(left)
            PyTuple_SET_ITEM(new_ann, out_pos, left)
            pos_one = pos_one + 1
            if pos_one >= len_one:
                left = None
            else:
                temp = PyTuple_GET_ITEM(ann_one, pos_one); left = <object>temp
        else: # right < left
            Py_INCREF(right)
            PyTuple_SET_ITEM(new_ann, out_pos, right)
            pos_two = pos_two + 1
            if pos_two >= len_two:
                right = None
            else:
                temp = PyTuple_GET_ITEM(ann_two, pos_two); right = <object>temp
        out_pos = out_pos + 1
    if out_pos != len_one + len_two:
        # PyTuple_Resize((<PyObject **>new_ann), out_pos)
        new_ann = new_ann[0:out_pos]
    PyDict_SetItem(cache, cache_key, new_ann)
    return new_ann


class Annotator:
    """Class that drives performing annotations."""

    def __init__(self, vf):
        """Create a new Annotator from a VersionedFile."""
        self._vf = vf
        self._parent_map = {}
        self._text_cache = {}
        # Map from key => number of nexts that will be built from this key
        self._num_needed_children = {}
        self._annotations_cache = {}
        self._heads_provider = None

    def _get_needed_keys(self, key):
        graph = _mod_graph.Graph(self._vf)
        parent_map = {}
        # We need 1 extra copy of the node we will be looking at when we are
        # done
        self._num_needed_children[key] = 1
        for key, parent_keys in graph.iter_ancestry([key]):
            if parent_keys is None:
                continue
            parent_map[key] = parent_keys
            for parent_key in parent_keys:
                if parent_key in self._num_needed_children:
                    self._num_needed_children[parent_key] += 1
                else:
                    self._num_needed_children[parent_key] = 1
                _update_counter('num children', 1)
        self._parent_map.update(parent_map)
        # _heads_provider does some graph caching, so it is only valid while
        # self._parent_map hasn't changed
        self._heads_provider = None
        keys = parent_map.keys()
        return keys

    def _get_needed_texts(self, key, pb=None):
        """Get the texts we need to properly annotate key.

        :param key: A Key that is present in self._vf
        :return: Yield (this_key, text, num_lines)
            'text' is an opaque object that just has to work with whatever
            matcher object we are using. Currently it is always 'lines' but
            future improvements may change this to a simple text string.
        """
        keys = self._get_needed_keys(key)
        if pb is not None:
            pb.update('getting stream', 0, len(keys))
        stream  = self._vf.get_record_stream(keys, 'topological', True)
        iterator = _NeededTextIterator(stream, self._text_cache, len(keys), pb)
        return iterator

    def _get_parent_annotations_and_matches(self, key, text, parent_key):
        """Get the list of annotations for the parent, and the matching lines.

        :param text: The opaque value given by _get_needed_texts
        :param parent_key: The key for the parent text
        :return: (parent_annotations, matching_blocks)
            parent_annotations is a list as long as the number of lines in
                parent
            matching_blocks is a list of (parent_idx, text_idx, len) tuples
                indicating which lines match between the two texts
        """
        parent_lines = self._text_cache[parent_key]
        parent_annotations = self._annotations_cache[parent_key]
        # PatienceSequenceMatcher should probably be part of Policy
        t = c()
        matcher = patiencediff.PatienceSequenceMatcher(None,
            parent_lines, text)
        matching_blocks = matcher.get_matching_blocks()
        _update_counter('get_matching_blocks()', c() - t)
        return parent_annotations, matching_blocks

    def _pyx_update_from_one_parent(self, key, annotations, lines, parent_key):
        """Reannotate this text relative to its first parent."""
        cdef Py_ssize_t parent_idx, lines_idx, match_len, idx
        cdef PyObject *temp

        parent_annotations, matching_blocks = self._get_parent_annotations_and_matches(
            key, lines, parent_key)
        _check_annotations_are_lists(annotations, parent_annotations)

        for parent_idx, lines_idx, match_len in matching_blocks:
            _check_match_ranges(parent_annotations, annotations,
                                parent_idx, lines_idx, match_len)
            for idx from 0 <= idx < match_len:
                temp = PyList_GET_ITEM(parent_annotations, parent_idx + idx)
                ann = <object>temp
                Py_INCREF(ann) # PyList_SetItem steals a ref
                PyList_SetItem(annotations, lines_idx + idx, ann)

    def _update_from_one_parent(self, key, annotations, lines, parent_key):
        """Reannotate this text relative to its first parent."""
        parent_annotations, matching_blocks = self._get_parent_annotations_and_matches(
            key, lines, parent_key)

        for parent_idx, lines_idx, match_len in matching_blocks:
            # For all matching regions we copy across the parent annotations
            annotations[lines_idx:lines_idx + match_len] = \
                parent_annotations[parent_idx:parent_idx + match_len]

    def _update_from_other_parents(self, key, annotations, lines,
                                   this_annotation, parent_key):
        """Reannotate this text relative to a second (or more) parent."""
        cdef Py_ssize_t parent_idx, ann_idx, lines_idx, match_len, idx
        cdef Py_ssize_t pos
        cdef PyObject *temp
        t1 = c()
        parent_annotations, matching_blocks = self._get_parent_annotations_and_matches(
            key, lines, parent_key)
        t2 = c()
        _update_counter('update other match', t2 - t1)
        _check_annotations_are_lists(annotations, parent_annotations)
        last_ann = None
        last_parent = None
        last_res = None
        cache = {}
        for parent_idx, lines_idx, match_len in matching_blocks:
            _check_match_ranges(parent_annotations, annotations,
                                parent_idx, lines_idx, match_len)
            # For lines which match this parent, we will now resolve whether
            # this parent wins over the current annotation
            for idx from 0 <= idx < match_len:
                ann_idx = lines_idx + idx
                temp = PyList_GET_ITEM(annotations, ann_idx)
                ann = <object>temp
                temp = PyList_GET_ITEM(parent_annotations, parent_idx + idx)
                par_ann = <object>temp
                if (PyObject_RichCompareBool(ann, par_ann, Py_EQ)):
                    # Nothing to change
                    continue
                if (PyObject_RichCompareBool(ann, this_annotation, Py_EQ)):
                    # Originally claimed 'this', but it was really in this
                    # parent
                    Py_INCREF(par_ann)
                    PyList_SetItem(annotations, ann_idx, par_ann)
                    continue
                # Resolve the fact that both sides have a different value for
                # last modified
                if (PyObject_RichCompareBool(ann, last_ann, Py_EQ)
                    and PyObject_RichCompareBool(par_ann, last_parent, Py_EQ)):
                    Py_INCREF(last_res)
                    PyList_SetItem(annotations, ann_idx, last_res)
                else:
                    new_ann = _combine_annotations(ann, par_ann, cache)
                    Py_INCREF(new_ann)
                    PyList_SetItem(annotations, ann_idx, new_ann)
                    last_ann = ann
                    last_parent = par_ann
                    last_res = new_ann
        t3 = c()
        _update_counter('update other resolve', t3 - t2)

    def _record_annotation(self, key, parent_keys, annotations):
        self._annotations_cache[key] = annotations
        for parent_key in parent_keys:
            num = self._num_needed_children[parent_key]
            num -= 1
            if num == 0:
                del self._text_cache[parent_key]
                del self._annotations_cache[parent_key]
                # Do we want to clean up _num_needed_children at this point as
                # well?
            self._num_needed_children[parent_key] = num

    def _annotate_one(self, key, text, num_lines):
        this_annotation = (key,)
        # Note: annotations will be mutated by calls to _update_from*
        annotations = [this_annotation] * num_lines
        parent_keys = self._parent_map[key]
        if parent_keys:
            t1 = c()
            self._update_from_one_parent(key, annotations, text, parent_keys[0])
            _update_counter('left parents', 1)
            t2 = c()
            for parent in parent_keys[1:]:
                self._update_from_other_parents(key, annotations, text,
                                                this_annotation, parent)
                _update_counter('right parents', 1)
            t3 = c()
            _update_counter('update left', t2 - t1)
            _update_counter('update rest', t3 - t2)
        self._record_annotation(key, parent_keys, annotations)

    def annotate(self, key):
        """Return annotated fulltext for the given key."""
        keys = self._get_needed_texts(key)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for text_key, text, num_lines in self._get_needed_texts(key, pb=pb):
                t = c()
                self._annotate_one(text_key, text, num_lines)
                _update_counter('annotate one', c() - t)
        finally:
            pb.finished()
        try:
            annotations = self._annotations_cache[key]
        except KeyError:
            raise errors.RevisionNotPresent(key, self._vf)
        return annotations, self._text_cache[key]

    def _get_heads_provider(self):
        if self._heads_provider is None:
            self._heads_provider = _mod_graph.KnownGraph(self._parent_map)
        return self._heads_provider

    def annotate_flat(self, key):
        """Determine the single-best-revision to source for each line.

        This is meant as a compatibility thunk to how annotate() used to work.
        """
        t_first = c()
        annotations, lines = self.annotate(key)
        _update_counter('annotate time', c() - t_first)
        assert len(annotations) == len(lines)
        out = []
        heads = self._get_heads_provider().heads
        append = out.append
        t_second = c()
        for annotation, line in zip(annotations, lines):
            if len(annotation) == 1:
                _update_counter('one source', 1)
                append((annotation[0], line))
            else:
                _update_counter('multi source', 1)
                t = c()
                the_heads = heads(annotation)
                _update_counter('heads time', c() - t)
                if len(the_heads) == 1:
                    _update_counter('one head', 1)
                    for head in the_heads:
                        break
                else:
                    _update_counter('multi heads', 1)
                    # We need to resolve the ambiguity, for now just pick the
                    # sorted smallest
                    head = sorted(the_heads)[0]
                if head == annotation[0]:
                    _update_counter('first ann', 1)
                append((head, line))
        _update_counter('resolve annotations', c() - t_second)
        _update_counter('overall', c() - t_first)
        return out
