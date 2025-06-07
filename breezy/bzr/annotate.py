# Copyright (C) 2005-2010 Canonical Ltd
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

"""File annotate based on VersionedFiles."""

from typing import TYPE_CHECKING

from .. import annotate as _mod_annotate
from .. import errors, osutils, ui
from .. import graph as _mod_graph
from ..annotate import Annotator

if TYPE_CHECKING:
    from bzrformats.versionedfile import VersionedFiles


class VersionedFileAnnotator(Annotator):
    """Class that drives performing annotations."""

    _vf: "VersionedFiles"

    def __init__(self, vf):
        """Create a new Annotator from a VersionedFile."""
        self._vf = vf
        self._parent_map = {}
        self._text_cache = {}
        # Map from key => number of nexts that will be built from this key
        self._num_needed_children = {}
        self._annotations_cache = {}
        self._heads_provider = None
        self._ann_tuple_cache = {}

    def _update_needed_children(self, key, parent_keys):
        for parent_key in parent_keys:
            if parent_key in self._num_needed_children:
                self._num_needed_children[parent_key] += 1
            else:
                self._num_needed_children[parent_key] = 1

    def _get_needed_keys(self, key):
        """Determine the texts we need to get from the backing vf.

        :return: (vf_keys_needed, ann_keys_needed)
            vf_keys_needed  These are keys that we need to get from the vf
            ann_keys_needed Texts which we have in self._text_cache but we
                            don't have annotations for. We need to yield these
                            in the proper order so that we can get proper
                            annotations.
        """
        parent_map = self._parent_map
        # We need 1 extra copy of the node we will be looking at when we are
        # done
        self._num_needed_children[key] = 1
        vf_keys_needed = set()
        ann_keys_needed = set()
        needed_keys = {key}
        while needed_keys:
            parent_lookup = []
            next_parent_map = {}
            for key in needed_keys:
                if key in self._parent_map:
                    # We don't need to lookup this key in the vf
                    if key not in self._text_cache:
                        # Extract this text from the vf
                        vf_keys_needed.add(key)
                    elif key not in self._annotations_cache:
                        # We do need to annotate
                        ann_keys_needed.add(key)
                        next_parent_map[key] = self._parent_map[key]
                else:
                    parent_lookup.append(key)
                    vf_keys_needed.add(key)
            needed_keys = set()
            next_parent_map.update(self._vf.get_parent_map(parent_lookup))
            for key, parent_keys in next_parent_map.items():
                if parent_keys is None:  # No graph versionedfile
                    parent_keys = ()
                    next_parent_map[key] = ()
                self._update_needed_children(key, parent_keys)
                needed_keys.update(
                    [key for key in parent_keys if key not in parent_map]
                )
            parent_map.update(next_parent_map)
            # _heads_provider does some graph caching, so it is only valid
            # while self._parent_map hasn't changed
            self._heads_provider = None
        return vf_keys_needed, ann_keys_needed

    def _get_needed_texts(self, key, pb=None):
        """Get the texts we need to properly annotate key.

        :param key: A Key that is present in self._vf
        :return: Yield (this_key, text, num_lines)
            'text' is an opaque object that just has to work with whatever
            matcher object we are using. Currently it is always 'lines' but
            future improvements may change this to a simple text string.
        """
        keys, ann_keys = self._get_needed_keys(key)
        if pb is not None:
            pb.update("getting stream", 0, len(keys))
        stream = self._vf.get_record_stream(keys, "topological", True)
        for _idx, record in enumerate(stream):
            if pb is not None:
                pb.update("extracting", 0, len(keys))
            if record.storage_kind == "absent":
                raise errors.RevisionNotPresent(record.key, self._vf)
            this_key = record.key
            lines = record.get_bytes_as("lines")
            num_lines = len(lines)
            self._text_cache[this_key] = lines
            yield this_key, lines, num_lines
        for key in ann_keys:
            lines = self._text_cache[key]
            num_lines = len(lines)
            yield key, lines, num_lines

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
        from patiencediff import PatienceSequenceMatcher

        matcher = PatienceSequenceMatcher(None, parent_lines, text)
        matching_blocks = matcher.get_matching_blocks()
        return parent_annotations, matching_blocks

    def _update_from_first_parent(self, key, annotations, lines, parent_key):
        """Reannotate this text relative to its first parent."""
        (
            parent_annotations,
            matching_blocks,
        ) = self._get_parent_annotations_and_matches(key, lines, parent_key)

        for parent_idx, lines_idx, match_len in matching_blocks:
            # For all matching regions we copy across the parent annotations
            annotations[lines_idx : lines_idx + match_len] = parent_annotations[
                parent_idx : parent_idx + match_len
            ]

    def _update_from_other_parents(
        self, key, annotations, lines, this_annotation, parent_key
    ):
        """Reannotate this text relative to a second (or more) parent."""
        (
            parent_annotations,
            matching_blocks,
        ) = self._get_parent_annotations_and_matches(key, lines, parent_key)

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
            ann_sub = annotations[lines_idx : lines_idx + match_len]
            par_sub = parent_annotations[parent_idx : parent_idx + match_len]
            if ann_sub == par_sub:
                continue
            for idx in range(match_len):
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
            self._update_from_first_parent(key, annotations, text, parent_keys[0])
            for parent in parent_keys[1:]:
                self._update_from_other_parents(
                    key, annotations, text, this_annotation, parent
                )
        self._record_annotation(key, parent_keys, annotations)

    def add_special_text(self, key, parent_keys, text):
        """Add a specific text to the graph.

        This is used to add a text which is not otherwise present in the
        versioned file. (eg. a WorkingTree injecting 'current:' into the
        graph to annotate the edited content.)

        :param key: The key to use to request this text be annotated
        :param parent_keys: The parents of this text
        :param text: A string containing the content of the text
        """
        self._parent_map[key] = parent_keys
        self._text_cache[key] = osutils.split_lines(text)
        self._heads_provider = None

    def annotate(self, key):
        """Return annotated fulltext for the given key.

        :param key: A tuple defining the text to annotate
        :return: ([annotations], [lines])
            annotations is a list of tuples of keys, one for each line in lines
                        each key is a possible source for the given line.
            lines the text of "key" as a list of lines
        """
        with ui.ui_factory.nested_progress_bar() as pb:
            for text_key, text, num_lines in self._get_needed_texts(key, pb=pb):
                self._annotate_one(text_key, text, num_lines)
        try:
            annotations = self._annotations_cache[key]
        except KeyError as exc:
            raise errors.RevisionNotPresent(key, self._vf) from exc
        return annotations, self._text_cache[key]

    def _get_heads_provider(self):
        if self._heads_provider is None:
            self._heads_provider = _mod_graph.KnownGraph(self._parent_map)
        return self._heads_provider

    def _resolve_annotation_tie(self, the_heads, line, tiebreaker):
        if tiebreaker is None:
            head = sorted(the_heads)[0]
        else:
            # Backwards compatibility, break up the heads into pairs and
            # resolve the result
            next_head = iter(the_heads)
            head = next(next_head)
            for possible_head in next_head:
                annotated_lines = ((head, line), (possible_head, line))
                head = tiebreaker(annotated_lines)[0]
        return head

    def annotate_flat(self, key):
        """Determine the single-best-revision to source for each line.

        This is meant as a compatibility thunk to how annotate() used to work.
        :return: [(ann_key, line)]
            A list of tuples with a single annotation key for each line.
        """
        custom_tiebreaker = _mod_annotate._break_annotation_tie
        annotations, lines = self.annotate(key)
        out = []
        heads = self._get_heads_provider().heads
        append = out.append
        for annotation, line in zip(annotations, lines):
            if len(annotation) == 1:
                head = annotation[0]
            else:
                the_heads = heads(annotation)
                if len(the_heads) == 1:
                    # get the item out of the set
                    head = next(iter(the_heads))
                else:
                    head = self._resolve_annotation_tie(
                        the_heads, line, custom_tiebreaker
                    )
            append((head, line))
        return out
