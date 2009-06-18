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
    annotate,
    errors,
    graph as _mod_graph,
    osutils,
    patiencediff,
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
        self._annotations_cache = {}
        self._heads_provider = None

    def _get_needed_texts(self, key):
        """Get the texts we need to properly annotate key.

        :param key: A Key that is present in self._vf
        :return: Yield (this_key, text, num_lines)
            'text' is an opaque object that just has to work with whatever
            matcher object we are using. Currently it is always 'lines' but
            future improvements may change this to a simple text string.
        """
        graph = _mod_graph.Graph(self._vf)
        parent_map = dict((k, v) for k, v in graph.iter_ancestry([key])
                          if v is not None)
        self._parent_map.update(parent_map)
        keys = parent_map.keys()
        for record in self._vf.get_record_stream(keys, 'topological', True):
            this_key = record.key
            lines = osutils.chunks_to_lines(record.get_bytes_as('chunked'))
            num_lines = len(lines)
            self._text_cache[this_key] = lines
            yield this_key, lines, num_lines

    def _get_parent_annotations_and_matches(self, text, parent_key):
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

    def _update_from_one_parent(self, annotations, lines, parent_key):
        """Reannotate this text relative to its first parent."""
        parent_annotations, matching_blocks = self._get_parent_annotations_and_matches(
            lines, parent_key)

        for parent_idx, lines_idx, match_len in matching_blocks:
            # For all matching regions we copy across the parent annotations
            annotations[lines_idx:lines_idx + match_len] = \
                parent_annotations[parent_idx:parent_idx + match_len]

    def _update_from_other_parents(self, annotations, lines, this_annotation,
                                   parent_key):
        """Reannotate this text relative to a second (or more) parent."""
        parent_annotations, matching_blocks = self._get_parent_annotations_and_matches(
            lines, parent_key)

        last_ann = None
        last_parent = None
        last_res = None
        # TODO: consider making all annotations unique and then using 'is'
        #       everywhere. Current results claim that isn't any faster,
        #       because of the time spent deduping
        for parent_idx, lines_idx, match_len in matching_blocks:
            # For lines which match this parent, we will now resolve whether
            # this parent wins over the current annotation
            for idx in xrange(match_len):
                ann_idx = lines_idx + idx
                ann = annotations[ann_idx]
                par_ann = parent_annotations[parent_idx + idx]
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

    def _init_annotations(self, key, num_lines):
        """Build a new annotation list for this key.

        :return: (this_annotation, annotations)
            this_annotation: a tuple indicating this line was only introduced
                             by revision key
            annotations: A list of this_annotation keys
        """
        this_annotation = (key,)
        # Note: annotations will be mutated by calls to _update_from*
        annotations = [this_annotation] * num_lines
        return this_annotation, annotations

    def _cache_annotations(self, key, parent_keys, annotations):
        self._annotations_cache[key] = annotations

    def annotate(self, key):
        """Return annotated fulltext for the given key."""
        keys = self._get_needed_texts(key)
        for text_key, text, num_lines in self._get_needed_texts(key):
            (this_annotation,
             annotations) = self._init_annotations(text_key, num_lines)

            parent_keys = self._parent_map[text_key]
            if parent_keys:
                self._update_from_one_parent(annotations, text, parent_keys[0])
                for parent in parent_keys[1:]:
                    self._update_from_other_parents(annotations, text,
                                                    this_annotation, parent)
            self._cache_annotations(text_key, parent_keys, annotations)
        try:
            annotations = self._annotations_cache[key]
        except KeyError:
            raise errors.RevisionNotPresent(key, self._vf)
        return annotations, self._text_cache[key]

    def annotate_flat(self, key):
        """Determine the single-best-revision to source for each line.

        This is meant as a compatibility thunk to how annotate() used to work.
        """
        annotations, lines = self.annotate(key)
        assert len(annotations) == len(lines)
        out = []
        graph = _mod_graph.KnownGraph(self._parent_map)
        heads = graph.heads
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
