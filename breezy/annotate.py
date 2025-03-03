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

"""File annotate based on weave storage."""

# TODO: Choice of more or less verbose formats:
#
# interposed: show more details between blocks of modified lines

# TODO: Show which revision caused a line to merge into the parent

# TODO: perhaps abbreviate timescales depending on how recent they are
# e.g. "3:12 Tue", "13 Oct", "Oct 2005", etc.

import sys
import time

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
import patiencediff

from breezy import (
    tsort,
    )
""",
)
from . import config, errors, osutils
from .repository import _strip_NULL_ghosts
from .revision import CURRENT_REVISION, Revision


def annotate_file_tree(
    tree, path, to_file, verbose=False, full=False, show_ids=False, branch=None
):
    """Annotate path in a tree.

    The tree should already be read_locked() when annotate_file_tree is called.

    :param tree: The tree to look for revision numbers and history from.
    :param path: The path to annotate
    :param to_file: The file to output the annotation to.
    :param verbose: Show all details rather than truncating to ensure
        reasonable text width.
    :param full: XXXX Not sure what this does.
    :param show_ids: Show revision ids in the annotation output.
    :param branch: Branch to use for revision revno lookups
    """
    if branch is None:
        branch = tree.branch
    if to_file is None:
        to_file = sys.stdout

    encoding = osutils.get_terminal_encoding()
    # Handle the show_ids case
    annotations = list(tree.annotate_iter(path))
    if show_ids:
        return _show_id_annotations(annotations, to_file, full, encoding)

    if not getattr(tree, "get_revision_id", False):
        # Create a virtual revision to represent the current tree state.
        # Should get some more pending commit attributes, like pending tags,
        # bugfixes etc.
        current_rev = Revision(CURRENT_REVISION)
        current_rev.parent_ids = tree.get_parent_ids()
        try:
            current_rev.committer = branch.get_config_stack().get("email")
        except errors.NoWhoami:
            current_rev.committer = "local user"
        current_rev.message = "?"
        current_rev.timestamp = round(time.time(), 3)
        current_rev.timezone = osutils.local_time_offset()
    else:
        current_rev = None
    annotation = list(_expand_annotations(annotations, branch, current_rev))
    _print_annotations(annotation, verbose, to_file, full, encoding)


def _print_annotations(annotation, verbose, to_file, full, encoding):
    """Print annotations to to_file.

    :param to_file: The file to output the annotation to.
    :param verbose: Show all details rather than truncating to ensure
        reasonable text width.
    :param full: XXXX Not sure what this does.
    """
    if len(annotation) == 0:
        max_origin_len = max_revno_len = 0
    else:
        max_origin_len = max(len(x[1]) for x in annotation)
        max_revno_len = max(len(x[0]) for x in annotation)
    if not verbose:
        max_revno_len = min(max_revno_len, 12)
    max_revno_len = max(max_revno_len, 3)

    # Output the annotations
    prevanno = ""
    for revno_str, author, date_str, _line_rev_id, text in annotation:
        if verbose:
            anno = f"{revno_str:<{max_revno_len}} {author:<{max_origin_len}} {date_str:>8} "
        else:
            if len(revno_str) > max_revno_len:
                revno_str = revno_str[: max_revno_len - 1] + ">"
            anno = f"{revno_str:<{max_revno_len}} {author[:7]:<7} "
        if anno.lstrip() == "" and full:
            anno = prevanno
        # GZ 2017-05-21: Writing both unicode annotation and bytes from file
        # which the given to_file must cope with.
        to_file.write(anno)
        to_file.write("| {}\n".format(text.decode(encoding)))
        prevanno = anno


def _show_id_annotations(annotations, to_file, full, encoding):
    if not annotations:
        return
    last_rev_id = None
    max_origin_len = max(len(origin) for origin, text in annotations)
    for origin, text in annotations:
        if full or last_rev_id != origin:
            this = origin
        else:
            this = b""
        to_file.write(
            f"{this.decode('utf-8'):>{max_origin_len}} | {text.decode(encoding)}"
        )
        last_rev_id = origin
    return


def _expand_annotations(annotations, branch, current_rev=None):
    """Expand a file's annotations into command line UI ready tuples.

    Each tuple includes detailed information, such as the author name, and date
    string for the commit, rather than just the revision id.

    :param annotations: The annotations to expand.
    :param revision_id_to_revno: A map from id to revision numbers.
    :param branch: A locked branch to query for revision details.
    """
    repository = branch.repository
    revision_ids = {o for o, t in annotations}
    if current_rev is not None:
        # This can probably become a function on MutableTree, get_revno_map
        # there, or something.
        last_revision = current_rev.revision_id
        # XXX: Partially Cloned from branch, uses the old_get_graph, eep.
        # XXX: The main difficulty is that we need to inject a single new node
        #      (current_rev) into the graph before it gets numbered, etc.
        #      Once KnownGraph gets an 'add_node()' function, we can use
        #      VF.get_known_graph_ancestry().
        graph = repository.get_graph()
        revision_graph = {
            key: value
            for key, value in graph.iter_ancestry(current_rev.parent_ids)
            if value is not None
        }
        revision_graph = _strip_NULL_ghosts(revision_graph)
        revision_graph[last_revision] = current_rev.parent_ids
        merge_sorted_revisions = tsort.merge_sort(
            revision_graph, last_revision, None, generate_revno=True
        )
        revision_id_to_revno = {
            rev_id: revno
            for seq_num, rev_id, depth, revno, end_of_merge in merge_sorted_revisions
        }
    else:
        # TODO(jelmer): Only look up the revision ids that we need (i.e. those
        # in revision_ids). Possibly add a HPSS call that can look those up
        # in bulk over HPSS.
        revision_id_to_revno = branch.get_revision_id_to_revno_map()
    last_origin = None
    revisions = {}
    if CURRENT_REVISION in revision_ids:
        revision_id_to_revno[CURRENT_REVISION] = (f"{branch.revno()+1}?",)
        revisions[CURRENT_REVISION] = current_rev
    revisions.update(
        entry
        for entry in repository.iter_revisions(revision_ids)
        if entry[1] is not None
    )
    for origin, text in annotations:
        text = text.rstrip(b"\r\n")
        if origin == last_origin:
            (revno_str, author, date_str) = ("", "", "")
        else:
            last_origin = origin
            if origin not in revisions:
                (revno_str, author, date_str) = ("?", "?", "?")
            else:
                revno_str = ".".join(str(i) for i in revision_id_to_revno[origin])
            rev = revisions[origin]
            tz = rev.timezone or 0
            date_str = time.strftime("%Y%m%d", time.gmtime(rev.timestamp + tz))
            # a lazy way to get something like the email address
            # TODO: Get real email address
            author = rev.get_apparent_authors()[0]
            _, email = config.parse_username(author)
            if email:
                author = email
        yield (revno_str, author, date_str, origin, text)


def reannotate(
    parents_lines,
    new_lines,
    new_revision_id,
    _left_matching_blocks=None,
    heads_provider=None,
):
    """Create a new annotated version from new lines and parent annotations.

    :param parents_lines: List of annotated lines for all parents
    :param new_lines: The un-annotated new lines
    :param new_revision_id: The revision-id to associate with new lines
        (will often be CURRENT_REVISION)
    :param left_matching_blocks: a hint about which areas are common
        between the text and its left-hand-parent.  The format is
        the SequenceMatcher.get_matching_blocks format
        (start_left, start_right, length_of_match).
    :param heads_provider: An object which provides a .heads() call to resolve
        if any revision ids are children of others.
        If None, then any ancestry disputes will be resolved with
        new_revision_id
    """
    if len(parents_lines) == 0:
        lines = [(new_revision_id, line) for line in new_lines]
    elif len(parents_lines) == 1:
        lines = _reannotate(
            parents_lines[0], new_lines, new_revision_id, _left_matching_blocks
        )
    elif len(parents_lines) == 2:
        left = _reannotate(
            parents_lines[0], new_lines, new_revision_id, _left_matching_blocks
        )
        lines = _reannotate_annotated(
            parents_lines[1], new_lines, new_revision_id, left, heads_provider
        )
    else:
        reannotations = [
            _reannotate(
                parents_lines[0], new_lines, new_revision_id, _left_matching_blocks
            )
        ]
        reannotations.extend(
            _reannotate(p, new_lines, new_revision_id) for p in parents_lines[1:]
        )
        lines = []
        for annos in zip(*reannotations):
            origins = {a for a, l in annos}
            if len(origins) == 1:
                # All the parents agree, so just return the first one
                lines.append(annos[0])
            else:
                line = annos[0][1]
                if len(origins) == 2 and new_revision_id in origins:
                    origins.remove(new_revision_id)
                if len(origins) == 1:
                    lines.append((origins.pop(), line))
                else:
                    lines.append((new_revision_id, line))
    return lines


def _reannotate(parent_lines, new_lines, new_revision_id, matching_blocks=None):
    new_cur = 0
    if matching_blocks is None:
        plain_parent_lines = [l for r, l in parent_lines]
        matcher = patiencediff.PatienceSequenceMatcher(
            None, plain_parent_lines, new_lines
        )
        matching_blocks = matcher.get_matching_blocks()
    lines = []
    for i, j, n in matching_blocks:
        for line in new_lines[new_cur:j]:
            lines.append((new_revision_id, line))
        lines.extend(parent_lines[i : i + n])
        new_cur = j + n
    return lines


def _get_matching_blocks(old, new):
    matcher = patiencediff.PatienceSequenceMatcher(None, old, new)
    return matcher.get_matching_blocks()


_break_annotation_tie = None


def _old_break_annotation_tie(annotated_lines):
    """Chose an attribution between several possible ones.

    :param annotated_lines: A list of tuples ((file_id, rev_id), line) where
        the lines are identical but the revids different while no parent
        relation exist between them

     :return : The "winning" line. This must be one with a revid that
         guarantees that further criss-cross merges will converge. Failing to
         do so have performance implications.
    """
    # sort lexicographically so that we always get a stable result.

    # TODO: while 'sort' is the easiest (and nearly the only possible solution)
    # with the current implementation, chosing the oldest revision is known to
    # provide better results (as in matching user expectations). The most
    # common use case being manual cherry-pick from an already existing
    # revision.
    return sorted(annotated_lines)[0]


def _find_matching_unannotated_lines(
    output_lines,
    plain_child_lines,
    child_lines,
    start_child,
    end_child,
    right_lines,
    start_right,
    end_right,
    heads_provider,
    revision_id,
):
    """Find lines in plain_right_lines that match the existing lines.

    :param output_lines: Append final annotated lines to this list
    :param plain_child_lines: The unannotated new lines for the child text
    :param child_lines: Lines for the child text which have been annotated
        for the left parent

    :param start_child: Position in plain_child_lines and child_lines to start
        the match searching
    :param end_child: Last position in plain_child_lines and child_lines to
        search for a match
    :param right_lines: The annotated lines for the whole text for the right
        parent
    :param start_right: Position in right_lines to start the match
    :param end_right: Last position in right_lines to search for a match
    :param heads_provider: When parents disagree on the lineage of a line, we
        need to check if one side supersedes the other
    :param revision_id: The label to give if a line should be labeled 'tip'
    """
    output_extend = output_lines.extend
    output_append = output_lines.append
    # We need to see if any of the unannotated lines match
    plain_right_subset = [l for a, l in right_lines[start_right:end_right]]
    plain_child_subset = plain_child_lines[start_child:end_child]
    match_blocks = _get_matching_blocks(plain_right_subset, plain_child_subset)

    last_child_idx = 0

    for right_idx, child_idx, match_len in match_blocks:
        # All the lines that don't match are just passed along
        if child_idx > last_child_idx:
            output_extend(
                child_lines[start_child + last_child_idx : start_child + child_idx]
            )
        for offset in range(match_len):
            left = child_lines[start_child + child_idx + offset]
            right = right_lines[start_right + right_idx + offset]
            if left[0] == right[0]:
                # The annotations match, just return the left one
                output_append(left)
            elif left[0] == revision_id:
                # The left parent marked this as unmatched, so let the
                # right parent claim it
                output_append(right)
            else:
                # Left and Right both claim this line
                if heads_provider is None:
                    output_append((revision_id, left[1]))
                else:
                    heads = heads_provider.heads((left[0], right[0]))
                    if len(heads) == 1:
                        output_append((next(iter(heads)), left[1]))
                    else:
                        # Both claim different origins, get a stable result.
                        # If the result is not stable, there is a risk a
                        # performance degradation as criss-cross merges will
                        # flip-flop the attribution.
                        if _break_annotation_tie is None:
                            output_append(_old_break_annotation_tie([left, right]))
                        else:
                            output_append(_break_annotation_tie([left, right]))
        last_child_idx = child_idx + match_len


def _reannotate_annotated(
    right_parent_lines, new_lines, new_revision_id, annotated_lines, heads_provider
):
    """Update the annotations for a node based on another parent.

    :param right_parent_lines: A list of annotated lines for the right-hand
        parent.
    :param new_lines: The unannotated new lines.
    :param new_revision_id: The revision_id to attribute to lines which are not
        present in either parent.
    :param annotated_lines: A list of annotated lines. This should be the
        annotation of new_lines based on parents seen so far.
    :param heads_provider: When parents disagree on the lineage of a line, we
        need to check if one side supersedes the other.
    """
    if len(new_lines) != len(annotated_lines):
        raise AssertionError("mismatched new_lines and annotated_lines")
    # First compare the newly annotated lines with the right annotated lines.
    # Lines which were not changed in left or right should match. This tends to
    # be the bulk of the lines, and they will need no further processing.
    lines = []
    lines_extend = lines.extend
    # The line just after the last match from the right side
    last_right_idx = 0
    last_left_idx = 0
    matching_left_and_right = _get_matching_blocks(right_parent_lines, annotated_lines)
    for right_idx, left_idx, match_len in matching_left_and_right:
        # annotated lines from last_left_idx to left_idx did not match the
        # lines from last_right_idx to right_idx, the raw lines should be
        # compared to determine what annotations need to be updated
        if last_right_idx == right_idx or last_left_idx == left_idx:
            # One of the sides is empty, so this is a pure insertion
            lines_extend(annotated_lines[last_left_idx:left_idx])
        else:
            # We need to see if any of the unannotated lines match
            _find_matching_unannotated_lines(
                lines,
                new_lines,
                annotated_lines,
                last_left_idx,
                left_idx,
                right_parent_lines,
                last_right_idx,
                right_idx,
                heads_provider,
                new_revision_id,
            )
        last_right_idx = right_idx + match_len
        last_left_idx = left_idx + match_len
        # If left and right agree on a range, just push that into the output
        lines_extend(annotated_lines[left_idx : left_idx + match_len])
    return lines


try:
    from breezy._annotator_pyx import Annotator
except ImportError as e:
    osutils.failed_to_load_extension(e)
    from breezy._annotator_py import Annotator  # noqa: F401
