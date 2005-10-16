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
# short: just show revno
# long: revno, author, date
# interposed: show more details between blocks of modified lines

# TODO: Show which revision caused a line to merge into the parent

import sys
import os
import time

import bzrlib.weave

def annotate_file(branch, rev_id, file_id, to_file=None):
    if to_file is None:
        to_file = sys.stdout
    rh = branch.revision_history()
    w = branch.weave_store.get_weave(file_id, branch.get_transaction())
    last_origin = None
    for origin, text in w.annotate_iter(rev_id):
        text = text.rstrip('\r\n')
        if origin == last_origin:
            anno = ''
        else:
            last_origin = origin
            line_rev_id = w.idx_to_name(origin)
            if not branch.has_revision(line_rev_id):
                anno = '???'
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
            author = line_rev_id
            if '@' in author:
                author = author[:author.index('@')]
            author = author[:12]
            anno = '%5s %-12s %8s' % (revno_str, author, date_str)
        print '%-27.27s | %s' % (anno, text)


if __name__ == '__main__':
    from bzrlib.branch import Branch
    from bzrlib.trace import enable_default_logging
    from bzrlib.workingtree import WorkingTree

    enable_default_logging()
    b = Branch.open_containing(sys.argv[1])
    tree = WorkingTree(b.base, b)
    rp = tree.relpath(sys.argv[1])
    tree = b.revision_tree(b.last_revision())
    file_id = tree.inventory.path2id(rp)
    file_version = tree.inventory[file_id].revision
    annotate_file(b, file_version, file_id, sys.stdout)
