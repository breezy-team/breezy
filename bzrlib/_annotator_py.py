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
    )


class AnnotatorPolicy(object):
    """Variables that define annotations."""


class Annotator(object):
    """Class that drives performing annotations."""

    def __init__(self, vf):
        """Create a new Annotator from a VersionedFile."""
        self._vf = vf

    def annotate(self, key):
        """Return annotated fulltext for the given key."""
        graph = _mod_graph.Graph(self._vf)
        parent_map = dict((k, v) for k, v in graph.iter_ancestry([key])
                          if v is not None)
        if not parent_map:
            raise errors.RevisionNotPresent(key, self)
        keys = parent_map.keys()
        heads_provider = _mod_graph.KnownGraph(parent_map)
        parent_cache = {}
        reannotate = annotate.reannotate
        for record in self._vf.get_record_stream(keys, 'topological', True):
            key = record.key
            fulltext = osutils.chunks_to_lines(record.get_bytes_as('chunked'))
            parents = parent_map[key]
            if parents is not None:
                parent_lines = [parent_cache[parent] for parent in parent_map[key]]
            else:
                parent_lines = []
            parent_cache[key] = list(
                reannotate(parent_lines, fulltext, key, None, heads_provider))
        try:
            annotated = parent_cache[key]
        except KeyError, e:
            raise errors.RevisionNotPresent(key, self._vf)
        annotations = [(a,) for a,l in annotated]
        lines = [l for a,l in annotated]
        return annotations, lines
