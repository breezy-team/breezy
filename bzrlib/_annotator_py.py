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
        self._lines_cache = {}
        self._annotations_cache = {}
        self._heads_provider = None

    def _get_needed_texts(self, key):
        graph = _mod_graph.Graph(self._vf)
        parent_map = dict((k, v) for k, v in graph.iter_ancestry([key])
                          if v is not None)
        self._parent_map.update(parent_map)
        keys = parent_map.keys()
        return keys

    def _get_heads_provider(self):
        if self._heads_provider is None:
            self._heads_provider = _mod_graph.KnownGraph(self._parent_map)
        return self._heads_provider

    def _reannotate_one_parent(self, annotations, lines, key, parent_key):
        """Reannotate this text relative to its first parent."""
        parent_lines = self._lines_cache[parent_key]
        parent_annotations = self._annotations_cache[parent_key]
        # PatienceSequenceMatcher should probably be part of Policy
        matcher = patiencediff.PatienceSequenceMatcher(None,
            parent_lines, lines)
        matching_blocks = matcher.get_matching_blocks()

        for parent_idx, lines_idx, match_len in matching_blocks:
            # For all matching regions we copy across the parent annotations
            annotations[lines_idx:lines_idx + match_len] = \
                parent_annotations[parent_idx:parent_idx + match_len]

    def annotate(self, key):
        """Return annotated fulltext for the given key."""
        keys = self._get_needed_texts(key)
        heads_provider = self._get_heads_provider
        for record in self._vf.get_record_stream(keys, 'topological', True):
            this_key = record.key
            lines = osutils.chunks_to_lines(record.get_bytes_as('chunked'))
            annotations = [(this_key,)]*len(lines)
            self._lines_cache[this_key] = lines
            self._annotations_cache[this_key] = annotations

            parents = self._parent_map[this_key]
            if not parents:
                continue
            self._reannotate_one_parent(annotations, lines, key, parents[0])
        try:
            annotations = self._annotations_cache[key]
        except KeyError:
            raise errors.RevisionNotPresent(key, self._vf)
        return annotations, self._lines_cache[key]
