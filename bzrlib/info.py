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
from bzrlib.trace import warning


def _countiter(it):
    # surely there's a builtin for this?
    i = 0
    for j in it:
        i += 1
    return i        


def plural(n, base='', pl=None):
    if n == 1:
        return base
    elif pl != None:
        return pl
    else:
        return 's'


def _get_format_string(target):
    """Return format string of target.
    
    Target must be of type bzrlib.workingtree, bzrlib.branch or
    bzrlib.repository.

    """
    try:
        return target._format.get_format_string().rstrip()
    except NotImplementedError:
        return target.bzrdir._format    # XXX: Use rstrip to be safe?


@deprecated_function(zero_eight)
def show_info(b):
    """Please see show_bzrdir_info."""
    return show_bzrdir_info(b.bzrdir)


def show_bzrdir_info(a_bzrdir, debug):
    """Output to stdout the 'info' for a_bzrdir."""

    working = a_bzrdir.open_workingtree()
    working.lock_read()
    try:
        show_tree_info(working, debug)
    finally:
        working.unlock()


def show_tree_info(working, debug):
    """Output to stdout the 'info' for working."""

    branch = working.branch
    repository = branch.repository
    working_format = _get_format_string(working)
    branch_format = _get_format_string(branch)
    repository_format = _get_format_string(repository)
    # TODO: metadir_format = ...

    if debug:
        print '   working.bzrdir = %s' % working.bzrdir.root_transport.base
        print '    branch.bzrdir = %s' % branch.bzrdir.root_transport.base
        print 'repository.bzrdir = %s' % repository.bzrdir.root_transport.base
        print '    branch.parent = %s' % (branch.get_parent() or '')
        print '    branch.push   = %s' % (branch.get_push_location() or '')
        print '    branch.bound  = %s' % (branch.get_bound_location() or '')
        print '   working.format = %s' % working_format
        print '    branch.format = %s' % branch_format
        print 'repository.format = %s' % repository_format
        print 'repository.shared = %s' % repository.is_shared()
        return

    print 'Location:'
    if working.bzrdir != branch.bzrdir:
        # Lightweight checkout
        print '        checkout root: %s' % (
            working.bzrdir.root_transport.base)
        print '   checkout of branch: %s' % (
            branch.bzrdir.root_transport.base)
    else:
        # Standalone or bound branch (normal checkout)
        print '          branch root: %s' % (
            branch.bzrdir.root_transport.base)
        if branch.get_bound_location():
            print '      bound to branch: %s' % branch.get_bound_location()

    if repository.bzrdir != branch.bzrdir:
        if repository.is_shared():
            print '    shared repository: %s' % (
                repository.bzrdir.root_transport.base)
        else:
            print '           repository: %s' % (
                repository.bzrdir.root_transport.base)

    if branch.get_parent():
        print '        parent branch: %s' % branch.get_parent()
    if branch.get_push_location():
        print '       push to branch: %s' % branch.get_push_location()

    print
    print 'Format:'
    if working_format == branch_format == repository_format:
        print '        branch format: %s' % branch_format
    else:
        # TODO: print 'meta directory format: %s' % metadir_format
        print '  working tree format: %s' % working_format
        print '        branch format: %s' % branch_format
        print '    repository format: %s' % repository_format

    basis = working.basis_tree()
    work_inv = working.inventory
    delta = diff.compare_trees(basis, working, want_unchanged=True)
    history = branch.revision_history()
    
    print
    # Try with inaccessible branch ?
    master = branch.get_master_branch()
    if master:
        local_extra, remote_extra = find_unmerged(branch, master)
        if remote_extra:
            print 'Branch is out of date: missing %d revision%s.' % (
                len(remote_extra), plural(len(remote_extra)))
            print

    if len(history) and working.last_revision() != history[-1]:
        try:
            missing_count = len(history) - history.index(working.last_revision())
        except ValueError:
            # consider it all out of date
            missing_count = len(history)
        print 'Working tree is out of date: missing %d revision%s.' % (
            missing_count, plural(missing_count))
        print

    print 'In the working tree:'
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
    print 'Branch history:'
    revno = len(history)
    print '  %8d revision%s' % (revno, plural(revno))
    committers = {}
    for rev in history:
        committers[branch.repository.get_revision(rev).committer] = True
    print '  %8d committer%s' % (len(committers), plural(len(committers)))
    if revno > 0:
        firstrev = branch.repository.get_revision(history[0])
        age = int((time.time() - firstrev.timestamp) / 3600 / 24)
        print '  %8d day%s old' % (age, plural(age))
        print '   first revision: %s' % format_date(firstrev.timestamp,
                                                    firstrev.timezone)

        lastrev = branch.repository.get_revision(history[-1])
        print '  latest revision: %s' % format_date(lastrev.timestamp,
                                                    lastrev.timezone)

#     print
#     print 'Text store:'
#     c, t = branch.text_store.total_size()
#     print '  %8d file texts' % c
#     print '  %8d kB' % (t/1024)

    print
    print 'Revision store:'
    c, t = branch.repository._revision_store.total_size(branch.repository.get_transaction())
    print '  %8d revision%s' % (c, plural(c))
    print '  %8d kB' % (t/1024)

#     print
#     print 'Inventory store:'
#     c, t = branch.inventory_store.total_size()
#     print '  %8d inventories' % c
#     print '  %8d kB' % (t/1024)
