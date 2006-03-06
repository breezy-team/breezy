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

__all__ = ['show_bzrdir_info']

import time


import bzrlib.diff as diff
from bzrlib.missing import find_unmerged
from bzrlib.osutils import format_date
from bzrlib.symbol_versioning import *


def _countiter(it):
    # surely there's a builtin for this?
    i = 0
    for j in it:
        i += 1
    return i        


@deprecated_function(zero_eight)
def show_info(b):
    """Please see show_bzrdir_info."""
    return show_bzrdir_info(b.bzrdir)

def show_bzrdir_info(a_bzrdir):
    """Output to stdout the 'info' for a_bzrdir."""

    def plural(n, base='', pl=None):
        if n == 1:
            return base
        elif pl != None:
            return pl
        else:
            return 's'

    working = a_bzrdir.open_workingtree()
    b = a_bzrdir.open_branch()
    
    if working.bzrdir != b.bzrdir:
        print 'working tree format:', working._format
        print 'branch location:', b.bzrdir.root_transport.base
    try:
        b._format.get_format_string()
        format = b._format
    except NotImplementedError:
        format = b.bzrdir._format
    print 'branch format:', format

    if b.get_bound_location():
        print 'bound to branch:',  b.get_bound_location()

    count_version_dirs = 0

    basis = working.basis_tree()
    work_inv = working.inventory
    delta = diff.compare_trees(basis, working, want_unchanged=True)
    history = b.revision_history()
    
    print
    # Try with inaccessible branch ?
    master = b.get_master_branch()
    if master:
        local_extra, remote_extra = find_unmerged(b, b.get_master_branch())
        if remote_extra:
            print 'Branch is out of date: missing %d revision%s.' % (
                len(remote_extra), plural(len(remote_extra)))

    if len(history) and working.last_revision() != history[-1]:
        try:
            missing_count = len(history) - history.index(working.last_revision())
        except ValueError:
            # consider it all out of date
            missing_count = len(history)
        print 'Working tree is out of date: missing %d revision%s.' % (
            missing_count, plural(missing_count))
    print 'in the working tree:'
    print '  %8s unchanged' % len(delta.unchanged)
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
    revno = len(history)
    print '  %8d revision%s' % (revno, plural(revno))
    committers = {}
    for rev in history:
        committers[b.repository.get_revision(rev).committer] = True
    print '  %8d committer%s' % (len(committers), plural(len(committers)))
    if revno > 0:
        firstrev = b.repository.get_revision(history[0])
        age = int((time.time() - firstrev.timestamp) / 3600 / 24)
        print '  %8d day%s old' % (age, plural(age))
        print '   first revision: %s' % format_date(firstrev.timestamp,
                                                    firstrev.timezone)

        lastrev = b.repository.get_revision(history[-1])
        print '  latest revision: %s' % format_date(lastrev.timestamp,
                                                    lastrev.timezone)

#     print
#     print 'text store:'
#     c, t = b.text_store.total_size()
#     print '  %8d file texts' % c
#     print '  %8d kB' % (t/1024)

    print
    print 'revision store:'
    c, t = b.repository.revision_store.total_size()
    print '  %8d revision%s' % (c, plural(c))
    print '  %8d kB' % (t/1024)


#     print
#     print 'inventory store:'
#     c, t = b.inventory_store.total_size()
#     print '  %8d inventories' % c
#     print '  %8d kB' % (t/1024)

