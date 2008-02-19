# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""File annotate based on weave storage"""

# TODO: Choice of more or less verbose formats:
# 
# interposed: show more details between blocks of modified lines

# TODO: Show which revision caused a line to merge into the parent

# TODO: perhaps abbreviate timescales depending on how recent they are
# e.g. "3:12 Tue", "13 Oct", "Oct 2005", etc.  

import sys
import time

from bzrlib import (
    errors,
    osutils,
    patiencediff,
    tsort,
    )
from bzrlib.config import extract_email_address


def annotate_file(branch, rev_id, file_id, verbose=False, full=False,
                  to_file=None, show_ids=False):
    """Annotate file_id at revision rev_id in branch.

    The branch should already be read_locked() when annotate_file is called.

    :param branch: The branch to look for revision numbers and history from.
    :param rev_id: The revision id to annotate.
    :param file_id: The file_id to annotate.
    :param verbose: Show all details rather than truncating to ensure
        reasonable text width.
    :param full: XXXX Not sure what this does.
    :param to_file: The file to output the annotation to; if None stdout is
        used.
    :param show_ids: Show revision ids in the annotation output.
    """
    if to_file is None:
        to_file = sys.stdout

    # Handle the show_ids case
    last_rev_id = None
    if show_ids:
        annotations = _annotations(branch.repository, file_id, rev_id)
        max_origin_len = max(len(origin) for origin, text in annotations)
        for origin, text in annotations:
            if full or last_rev_id != origin:
                this = origin
            else:
                this = ''
            to_file.write('%*s | %s' % (max_origin_len, this, text))
            last_rev_id = origin
        return

    # Calculate the lengths of the various columns
    annotation = list(_annotate_file(branch, rev_id, file_id))
    if len(annotation) == 0:
        max_origin_len = max_revno_len = max_revid_len = 0
    else:
        max_origin_len = max(len(x[1]) for x in annotation)
        max_revno_len = max(len(x[0]) for x in annotation)
        max_revid_len = max(len(x[3]) for x in annotation)
    if not verbose:
        max_revno_len = min(max_revno_len, 12)
    max_revno_len = max(max_revno_len, 3)

    # Output the annotations
    prevanno = ''
    encoding = getattr(to_file, 'encoding', None) or \
            osutils.get_terminal_encoding()
    for (revno_str, author, date_str, line_rev_id, text) in annotation:
        if verbose:
            anno = '%-*s %-*s %8s ' % (max_revno_len, revno_str,
                                       max_origin_len, author, date_str)
        else:
            if len(revno_str) > max_revno_len:
                revno_str = revno_str[:max_revno_len-1] + '>'
            anno = "%-*s %-7s " % (max_revno_len, revno_str, author[:7])
        if anno.lstrip() == "" and full:
            anno = prevanno
        try:
            to_file.write(anno)
        except UnicodeEncodeError:
            # cmd_annotate should be passing in an 'exact' object, which means
            # we have a direct handle to sys.stdout or equivalent. It may not
            # be able to handle the exact Unicode characters, but 'annotate' is
            # a user function (non-scripting), so shouldn't die because of
            # unrepresentable annotation characters. So encode using 'replace',
            # and write them again.
            to_file.write(anno.encode(encoding, 'replace'))
        to_file.write('| %s\n' % (text,))
        prevanno = anno


def _annotations(repo, file_id, rev_id):
    """Return the list of (origin,text) for a revision of a file in a repository."""
    w = repo.weave_store.get_weave(file_id, repo.get_transaction())
    return list(w.annotate_iter(rev_id))


def _annotate_file(branch, rev_id, file_id):
    """Yield the origins for each line of a file.

    This includes detailed information, such as the author name, and
    date string for the commit, rather than just the revision id.
    """
    revision_id_to_revno = branch.get_revision_id_to_revno_map()
    annotations = _annotations(branch.repository, file_id, rev_id)
    last_origin = None
    revision_ids = set(o for o, t in annotations)
    revision_ids = [o for o in revision_ids if 
                    branch.repository.has_revision(o)]
    revisions = dict((r.revision_id, r) for r in 
                     branch.repository.get_revisions(revision_ids))
    for origin, text in annotations:
        text = text.rstrip('\r\n')
        if origin == last_origin:
            (revno_str, author, date_str) = ('','','')
        else:
            last_origin = origin
            if origin not in revisions:
                (revno_str, author, date_str) = ('?','?','?')
            else:
                revno_str = '.'.join(str(i) for i in
                                            revision_id_to_revno[origin])
            rev = revisions[origin]
            tz = rev.timezone or 0
            date_str = time.strftime('%Y%m%d',
                                     time.gmtime(rev.timestamp + tz))
            # a lazy way to get something like the email address
            # TODO: Get real email address
            author = rev.get_apparent_author()
            try:
                author = extract_email_address(author)
            except errors.NoEmailInUsername:
                pass        # use the whole name
        yield (revno_str, author, date_str, origin, text)


def reannotate(parents_lines, new_lines, new_revision_id,
               _left_matching_blocks=None):
    """Create a new annotated version from new lines and parent annotations.
    
    :param parents_lines: List of annotated lines for all parents
    :param new_lines: The un-annotated new lines
    :param new_revision_id: The revision-id to associate with new lines
        (will often be CURRENT_REVISION)
    :param left_matching_blocks: a hint about which areas are common
        between the text and its left-hand-parent.  The format is
        the SequenceMatcher.get_matching_blocks format
        (start_left, start_right, length_of_match).
    """
    if len(parents_lines) == 0:
        lines = [(new_revision_id, line) for line in new_lines]
    elif len(parents_lines) == 1:
        lines = _reannotate(parents_lines[0], new_lines, new_revision_id,
                            _left_matching_blocks)
    elif len(parents_lines) == 2:
        left = _reannotate(parents_lines[0], new_lines, new_revision_id,
                           _left_matching_blocks)
        lines = _reannotate_annotated(parents_lines[1], new_lines,
                                      new_revision_id, left)
    else:
        reannotations = [_reannotate(parents_lines[0], new_lines,
                                     new_revision_id, _left_matching_blocks)]
        reannotations.extend(_reannotate(p, new_lines, new_revision_id)
                             for p in parents_lines[1:])
        lines = []
        for annos in zip(*reannotations):
            origins = set(a for a, l in annos)
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


def _reannotate(parent_lines, new_lines, new_revision_id,
                matching_blocks=None):
    new_cur = 0
    if matching_blocks is None:
        plain_parent_lines = [l for r, l in parent_lines]
        matcher = patiencediff.PatienceSequenceMatcher(None,
            plain_parent_lines, new_lines)
        matching_blocks = matcher.get_matching_blocks()
    lines = []
    for i, j, n in matching_blocks:
        for line in new_lines[new_cur:j]:
            lines.append((new_revision_id, line))
        lines.extend(parent_lines[i:i+n])
        new_cur = j + n
    return lines


def _reannotate_annotated(right_parent_lines, new_lines, new_revision_id,
                          annotated_lines):
    """Update the annotations for a node based on another parent.

    :param right_parent_lines: A list of annotated lines for the right-hand
        parent.
    :param new_lines: The unannotated new lines.
    :param new_revision_id: The revision_id to attribute to lines which are not
        present in either parent.
    :param annotated_lines: A list of annotated lines. This should be the
        annotation of new_lines based on parents seen so far.
    """
    def get_matching_blocks(old, new):
        matcher = patiencediff.PatienceSequenceMatcher(None,
            old, new)
        return matcher.get_matching_blocks()

    assert len(new_lines) == len(annotated_lines)
    # First compare the newly annotated lines with the right annotated lines.
    # Lines which were not changed in left or right should match. This tends to
    # be the bulk of the lines, and they will need no further processing.
    matching_left_and_right = get_matching_blocks(right_parent_lines,
                                                  annotated_lines)
    lines = []
    lines_append = lines.append
    lines_extend = lines.extend
    last_i = 0 # The line just after the last match from the right side
    last_j = 0
    for i, j, n in matching_left_and_right:
        # annotated lines from last_j to j did not match the lines from last_i
        # to i, the raw lines should be compared to determine what annotations
        # need to be updated
        if last_i == i or last_j == j:
            # One of the sides is empty, so this is a pure insertion
            lines_extend(annotated_lines[last_j:j])
        else:
            # We need to see if any of the unannotated lines match
            plain_right_lines = [l for r,l in right_parent_lines[last_i:i]]
            last_jj = 0
            for ii, jj, nn in get_matching_blocks(plain_right_lines,
                                                  new_lines[last_j:j]):
                # All the lines that don't match are just passed along
                lines_extend(annotated_lines[last_j+last_jj:last_j+jj])
                for offset in xrange(nn):
                    left = annotated_lines[last_j+jj+offset]
                    right = right_parent_lines[last_i+ii+offset]
                    if left[0] == right[0]:
                        # The annotations match, just return the left one
                        lines_append(left)
                    elif left[0] == new_revision_id:
                        # The left parent marked this as unmatched, so let the
                        # right parent claim it
                        lines_append(right)
                    else:
                        # Left and Right both claim this line
                        # TODO: The correct method is to use a heads() call to
                        #       handle ancestry disagreements.
                        #       For now, just mark it unclaimed
                        lines_append((new_revision_id, left[1]))
                        ## # TODO: The correcb
                        ## # import pdb; pdb.set_trace()
                        ## heads = heads_provider.heads((left[0], right[0]))
                        ## if len(heads) == 1:
                        ##     # import pdb; pdb.set_trace()
                        ##     lines_append((heads.pop(), left[1]))
                        ## else:
                        ##     # Both claim different origins
                        ##     lines_append((new_revision_id, left[1]))
                        ##     # lines_append(left)
                last_jj = jj + nn
        last_i = i + n
        last_j = j + n
        # If left and right agree on a range, just push that into the output
        assert len(lines) == j
        lines_extend(annotated_lines[j:j+n])
    return lines
