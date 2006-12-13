# Copyright (C) 2004, 2005 Canonical Ltd
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
    tsort,
    )
from bzrlib.config import extract_email_address


def annotate_file(branch, rev_id, file_id, verbose=False, full=False,
                  to_file=None, show_ids=False):
    if to_file is None:
        to_file = sys.stdout

    prevanno=''
    annotation = list(_annotate_file(branch, rev_id, file_id))
    if len(annotation) == 0:
        max_origin_len = 0
        max_revno_len = 0
    else:
        max_origin_len = max(len(origin) for origin in set(x[1] for x in annotation))
        max_revno_len = max(len(x[0]) for x in annotation)

    if not verbose:
        max_revno_len = min(max_revno_len, 10)

    for (revno_str, author, date_str, line_rev_id, text ) in annotation:
        if verbose:
            anno = '%-*s %-*s %8s ' % (max_revno_len, revno_str, max_origin_len, author, date_str)
        else:
            if len(revno_str) > max_revno_len:
                revno_str = revno_str[:9] + '>'
            anno = "%-*s %-7s " % (max_revno_len, revno_str, author[:7] )

        if anno.lstrip() == "" and full: anno = prevanno
        print >>to_file, '%s| %s' % (anno, text)
        prevanno=anno

def _annotate_file(branch, rev_id, file_id ):

    rh = branch.revision_history()
    revision_graph = branch.repository.get_revision_graph(rev_id)
    merge_sorted_revisions = tsort.merge_sort(
        revision_graph,
        rev_id,
        None,
        generate_revno=True)
    revision_id_to_revno = dict((rev_id, revno)
                                for seq_num, rev_id, depth, revno, end_of_merge
                                 in merge_sorted_revisions)
    w = branch.repository.weave_store.get_weave(file_id,
        branch.repository.get_transaction())
    last_origin = None
    annotations = list(w.annotate_iter(rev_id))
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
            author = rev.committer
            try:
                author = extract_email_address(author)
            except errors.NoEmailInUsername:
                pass        # use the whole name
        yield (revno_str, author, date_str, origin, text)
