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

import sys
import os

import bzrlib.weave

def annotate_file(branch, rev_id, file_id, to_file=None):
    if to_file is None:
        to_file = sys.stdout
    rh = branch.revision_history()
    w = branch.weave_store.get_weave(file_id)
    last_origin = None
    for origin, text in w.annotate_iter(rev_id):
        text = text.rstrip('\r\n')
        if origin == last_origin:
            print '      | %s' % (text)
        else:
            last_origin = origin
            line_rev_id = w.idx_to_name(origin)
            try:
                revno = rh.index(line_rev_id) + 1
                print '%5d | %s' % (revno, text)
            except ValueError:
                print 'merge | %s' % (text)



if __name__ == '__main__':
    from bzrlib.branch import find_branch
    from bzrlib.trace import enable_default_logging

    enable_default_logging()
    b = find_branch(sys.argv[1])
    rp = b.relpath(sys.argv[1])
    tree = b.revision_tree(b.last_revision())
    file_id = tree.inventory.path2id(rp)
    file_version = tree.inventory[file_id].text_version
    annotate_file(b, file_version, file_id, sys.stdout)
