# Copyright (C) 2004, 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""File annotate based on weave storage"""

# TODO: Choice of more or less verbose formats:
# 
# interposed: show more details between blocks of modified lines

# TODO: Show which revision caused a line to merge into the parent

# TODO: With --long, show entire email address, not just the first bit

# TODO: perhaps abbreviate timescales depending on how recent they are
# e.g. "3:12 Tue", "13 Oct", "Oct 2005", etc.  

import sys
import os
import time

import bzrlib.weave
from bzrlib.config import extract_email_address
from bzrlib.errors import BzrError


def annotate_file(branch, rev_id, file_id, verbose=False, full=False,
        to_file=None):
    if to_file is None:
        to_file = sys.stdout

    prevanno=''
    for (revno_str, author, date_str, line_rev_id, text ) in \
            _annotate_file(branch, rev_id, file_id ):

        if verbose:
            anno = '%5s %-12s %8s ' % (revno_str, author[:12], date_str)
        else:
            anno = "%5s %-7s " % ( revno_str, author[:7] )

        if anno.lstrip() == "" and full: anno = prevanno
        print >>to_file, '%s| %s' % (anno, text)
        prevanno=anno

def _annotate_file(branch, rev_id, file_id ):

    rh = branch.revision_history()
    w = branch.weave_store.get_weave(file_id, branch.get_transaction())
    last_origin = None
    for origin, text in w.annotate_iter(rev_id):
        text = text.rstrip('\r\n')
        if origin == last_origin:
            (revno_str, author, date_str) = ('','','')
        else:
            last_origin = origin
            line_rev_id = w.idx_to_name(origin)
            if not branch.has_revision(line_rev_id):
                (revno_str, author, date_str) = ('?','?','?')
            else:
                if line_rev_id in rh:
                    revno_str = str(rh.index(line_rev_id) + 1)
                else:
                    revno_str = 'merge'
            rev = branch.get_revision(line_rev_id)
            tz = rev.timezone or 0
            date_str = time.strftime('%Y%m%d', 
                                     time.gmtime(rev.timestamp + tz))
            # a lazy way to get something like the email address
            # TODO: Get real email address
            author = rev.committer
            try:
                author = extract_email_address(author)
            except BzrError:
                pass        # use the whole name
        yield (revno_str, author, date_str, line_rev_id, text)
