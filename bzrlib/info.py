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

from osutils import format_date


def _countiter(it):
    # surely there's a builtin for this?
    i = 0
    for j in it:
        i += 1
    return i        



def show_info(b):
    import diff
    
    print 'branch format:', b.controlfile('branch-format', 'r').readline().rstrip('\n')

    def plural(n, base='', pl=None):
        if n == 1:
            return base
        elif pl != None:
            return pl
        else:
            return 's'

    count_version_dirs = 0

    basis = b.basis_tree()
    working = b.working_tree()
    work_inv = working.inventory
    delta = diff.compare_trees(basis, working)
    
    print
    print 'in the working tree:'
    print '  %8s unchanged' % '?'
    print '  %8d modified' % len(delta.modified)
    print '  %8d added' % len(delta.added)
    print '  %8d removed' % len(delta.removed)
    print '  %8d renamed' % len(delta.renamed)

    ignore_cnt = unknown_cnt = 0
    for path in working.extras():
        if working.is_ignored(path):
            ignore_cnt += 1
        else:
            unknown_cnt += 1

    print '  %8d unknown' % unknown_cnt
    print '  %8d ignored' % ignore_cnt

    dir_cnt = 0
    for file_id in work_inv:
        if work_inv.get_file_kind(file_id) == 'directory':
            dir_cnt += 1
    print '  %8d versioned %s' \
          % (dir_cnt,
             plural(dir_cnt, 'subdirectory', 'subdirectories'))

    print
    print 'branch history:'
    history = b.revision_history()
    revno = len(history)
    print '  %8d revision%s' % (revno, plural(revno))
    committers = Set()
    for rev in history:
        committers.add(b.get_revision(rev).committer)
    print '  %8d committer%s' % (len(committers), plural(len(committers)))
    if revno > 0:
        firstrev = b.get_revision(history[0])
        age = int((time.time() - firstrev.timestamp) / 3600 / 24)
        print '  %8d day%s old' % (age, plural(age))
        print '   first revision: %s' % format_date(firstrev.timestamp,
                                                    firstrev.timezone)

        lastrev = b.get_revision(history[-1])
        print '  latest revision: %s' % format_date(lastrev.timestamp,
                                                    lastrev.timezone)

    print
    print 'text store:'
    c, t = b.text_store.total_size()
    print '  %8d file texts' % c
    print '  %8d kB' % (t/1024)

    print
    print 'revision store:'
    c, t = b.revision_store.total_size()
    print '  %8d revisions' % c
    print '  %8d kB' % (t/1024)


    print
    print 'inventory store:'
    c, t = b.inventory_store.total_size()
    print '  %8d inventories' % c
    print '  %8d kB' % (t/1024)

