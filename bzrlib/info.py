# Copyright (C) 2004, 2005 by Martin Pool
# Copyright (C) 2005 by Canonical Ltd


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

from sets import Set
import time

import bzrlib
from osutils import format_date

def show_info(b):
    # TODO: Maybe show space used by working tree, versioned files,
    # unknown files, text store.
    
    print 'branch format:', b.controlfile('branch-format', 'r').readline().rstrip('\n')

    def plural(n, base='', pl=None):
        if n == 1:
            return base
        elif pl is not None:
            return pl
        else:
            return 's'

    count_version_dirs = 0

    count_status = {'A': 0, 'D': 0, 'M': 0, 'R': 0, '?': 0, 'I': 0, '.': 0}
    for st_tup in bzrlib.diff_trees(b.basis_tree(), b.working_tree()):
        fs = st_tup[0]
        count_status[fs] += 1
        if fs not in ['I', '?'] and st_tup[4] == 'directory':
            count_version_dirs += 1

    print
    print 'in the working tree:'
    for name, fs in (('unchanged', '.'),
                     ('modified', 'M'), ('added', 'A'), ('removed', 'D'),
                     ('renamed', 'R'), ('unknown', '?'), ('ignored', 'I'),
                     ):
        print '  %5d %s' % (count_status[fs], name)
    print '  %5d versioned subdirector%s' % (count_version_dirs,
                                             plural(count_version_dirs, 'y', 'ies'))

    print
    print 'branch history:'
    history = b.revision_history()
    revno = len(history)
    print '  %5d revision%s' % (revno, plural(revno))
    committers = Set()
    for rev in history:
        committers.add(b.get_revision(rev).committer)
    print '  %5d committer%s' % (len(committers), plural(len(committers)))
    if revno > 0:
        firstrev = b.get_revision(history[0])
        age = int((time.time() - firstrev.timestamp) / 3600 / 24)
        print '  %5d day%s old' % (age, plural(age))
        print '   first revision: %s' % format_date(firstrev.timestamp,
                                                    firstrev.timezone)

        lastrev = b.get_revision(history[-1])
        print '  latest revision: %s' % format_date(lastrev.timestamp,
                                                    lastrev.timezone)

    print
    print 'text store:'
    print '  %5d file texts' % len(b.text_store)

    print
    print 'revision store:'
    print '  %5d revisions' % len(b.revision_store)

    print
    print 'inventory store:'
    print '  %5d inventories' % len(b.inventory_store)
