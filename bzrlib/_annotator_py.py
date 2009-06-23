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

from bzrlib import (
    errors,
    graph as _mod_graph,
    osutils,
    patiencediff,
    ui,
    )


class AnnotatorPolicy(object):
    """Variables that define annotations."""


class Annotator(object):
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
        for idx, record in enumerate(stream):
            if pb is not None:
                pb.update('extracting', 0, len(keys))
            this_key = record.key
            lines = osutils.chunks_to_lines(record.get_bytes_as('chunked'))
            num_lines = len(lines)
            self._text_cache[this_key] = lines
            yield this_key, lines, num_lines

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
        matcher = patiencediff.PatienceSequenceMatcher(None,
            parent_lines, text)
        matching_blocks = matcher.get_matching_blocks()
        return parent_annotations, matching_blocks

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
        parent_annotations, matching_blocks = self._get_parent_annotations_and_matches(
            key, lines, parent_key)

        last_ann = None
        last_parent = None
        last_res = None
        # TODO: consider making all annotations unique and then using 'is'
        #       everywhere. Current results claim that isn't any faster,
        #       because of the time spent deduping
        #       deduping also saves a bit of memory. For NEWS it saves ~1MB,
        #       but that is out of 200-300MB for extracting everything, so a
        #       fairly trivial amount
        for parent_idx, lines_idx, match_len in matching_blocks:
            # For lines which match this parent, we will now resolve whether
            # this parent wins over the current annotation
            ann_sub = annotations[lines_idx:lines_idx + match_len]
            par_sub = parent_annotations[parent_idx:parent_idx + match_len]
            if ann_sub == par_sub:
                continue
            for idx in xrange(match_len):
                ann = ann_sub[idx]
                par_ann = par_sub[idx]
                ann_idx = lines_idx + idx
                if ann == par_ann:
                    # Nothing to change
                    continue
                if ann == this_annotation:
                    # Originally claimed 'this', but it was really in this
                    # parent
                    annotations[ann_idx] = par_ann
                    continue
                # Resolve the fact that both sides have a different value for
                # last modified
                if ann == last_ann and par_ann == last_parent:
                    annotations[ann_idx] = last_res
                else:
                    new_ann = set(ann)
                    new_ann.update(par_ann)
                    new_ann = tuple(sorted(new_ann))
                    annotations[ann_idx] = new_ann
                    last_ann = ann
                    last_parent = par_ann
                    last_res = new_ann

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
            self._update_from_one_parent(key, annotations, text, parent_keys[0])
            for parent in parent_keys[1:]:
                self._update_from_other_parents(key, annotations, text,
                                                this_annotation, parent)
        self._record_annotation(key, parent_keys, annotations)

    def annotate(self, key):
        """Return annotated fulltext for the given key."""
        keys = self._get_needed_texts(key)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for text_key, text, num_lines in self._get_needed_texts(key, pb=pb):
                self._annotate_one(text_key, text, num_lines)
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
        annotations, lines = self.annotate(key)
        assert len(annotations) == len(lines)
        out = []
        heads = self._get_heads_provider().heads
        append = out.append
        for annotation, line in zip(annotations, lines):
            if len(annotation) == 1:
                append((annotation[0], line))
            else:
                the_heads = heads(annotation)
                if len(the_heads) == 1:
                    for head in the_heads:
                        break
                else:
                    # We need to resolve the ambiguity, for now just pick the
                    # sorted smallest
                    head = sorted(the_heads)[0]
                append((head, line))
        return out
