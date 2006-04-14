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
from bzrlib.errors import (NoWorkingTree, NotBranchError,
                           NoRepositoryPresent, NotLocalUrl)
from bzrlib.missing import find_unmerged
from bzrlib.osutils import format_date
from bzrlib.symbol_versioning import *


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


def _show_location_info(repository=None, branch=None, working=None):
    """Show known locations for working, branch and repository."""
    print 'Location:'
    if working and branch and working.bzrdir != branch.bzrdir:
        # Lightweight checkout
        print '       checkout root: %s' % (
            working.bzrdir.root_transport.base)
        print '  checkout of branch: %s' % (
            branch.bzrdir.root_transport.base)
    elif branch:
        # Standalone or bound branch (normal checkout)
        print '         branch root: %s' % (
            branch.bzrdir.root_transport.base)
        if branch.get_bound_location():
            print '     bound to branch: %s' % branch.get_bound_location()

    # No branch? Info was requested on a repository, show it.
    # If we have a branch with the same location as repository, hide it,
    # unless that repository is shared.
    if repository and (not branch or
                       repository.bzrdir != branch.bzrdir or
                       repository.is_shared()):
        if repository.is_shared():
            print '   shared repository: %s' % (
                repository.bzrdir.root_transport.base)
        else:
            print '          repository: %s' % (
                repository.bzrdir.root_transport.base)

    if branch:
        if branch.get_parent():
            print '       parent branch: %s' % branch.get_parent()
        if branch.get_push_location():
            print '      push to branch: %s' % branch.get_push_location()


def _show_format_info(control=None, repository=None, branch=None, working=None):
    """Show known formats for control, working, branch and repository."""
    print
    print 'Format:'
    if control:
        print '       control: %s' % control._format.get_format_description()
    if working:
        print '  working tree: %s' % working._format.get_format_description()
    if branch:
        print '        branch: %s' % branch._format.get_format_description()
    if repository:
        print '    repository: %s' % repository._format.get_format_description()


def _show_missing_revisions_branch(branch):
    """Show missing master revisions in branch."""
    # Try with inaccessible branch ?
    master = branch.get_master_branch()
    if master:
        local_extra, remote_extra = find_unmerged(branch, master)
        if remote_extra:
            print
            print 'Branch is out of date: missing %d revision%s.' % (
                len(remote_extra), plural(len(remote_extra)))


def _show_missing_revisions_working(working):
    """Show missing revisions in working tree."""
    branch = working.branch
    basis = working.basis_tree()
    work_inv = working.inventory
    delta = diff.compare_trees(basis, working, want_unchanged=True)
    history = branch.revision_history()
    tree_last_id = working.last_revision()

    if len(history) and tree_last_id != history[-1]:
        tree_last_revno = branch.revision_id_to_revno(tree_last_id)
        missing_count = len(history) - tree_last_revno
        print
        print 'Working tree is out of date: missing %d revision%s.' % (
            missing_count, plural(missing_count))


def _show_working_stats(working):
    """Show statistics about a working tree."""
    basis = working.basis_tree()
    work_inv = working.inventory
    delta = diff.compare_trees(basis, working, want_unchanged=True)

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


def _show_branch_stats(branch, verbose):
    """Show statistics about a branch."""
    repository = branch.repository
    history = branch.revision_history()

    print
    print 'Branch history:'
    revno = len(history)
    print '  %8d revision%s' % (revno, plural(revno))
    if verbose:
        committers = {}
        for rev in history:
            committers[repository.get_revision(rev).committer] = True
        print '  %8d committer%s' % (len(committers), plural(len(committers)))
    if revno > 0:
        firstrev = repository.get_revision(history[0])
        age = int((time.time() - firstrev.timestamp) / 3600 / 24)
        print '  %8d day%s old' % (age, plural(age))
        print '   first revision: %s' % format_date(firstrev.timestamp,
                                                    firstrev.timezone)

        lastrev = repository.get_revision(history[-1])
        print '  latest revision: %s' % format_date(lastrev.timestamp,
                                                    lastrev.timezone)

#     print
#     print 'Text store:'
#     c, t = branch.text_store.total_size()
#     print '  %8d file texts' % c
#     print '  %8d KiB' % (t/1024)

#     print
#     print 'Inventory store:'
#     c, t = branch.inventory_store.total_size()
#     print '  %8d inventories' % c
#     print '  %8d KiB' % (t/1024)


def _show_repository_info(repository):
    """Show settings of a repository."""
    if repository.make_working_trees():
        print
        print 'Create working tree for new branches inside the repository.'


def _show_repository_stats(repository):
    """Show statistics about a repository."""
    if repository.bzrdir.root_transport.listable():
        print
        print 'Revision store:'
        c, t = repository._revision_store.total_size(repository.get_transaction())
        print '  %8d revision%s' % (c, plural(c))
        print '  %8d KiB' % (t/1024)


@deprecated_function(zero_eight)
def show_info(b):
    """Please see show_bzrdir_info."""
    return show_bzrdir_info(b.bzrdir)


def show_bzrdir_info(a_bzrdir, verbose=False):
    """Output to stdout the 'info' for a_bzrdir."""
    try:
        working = a_bzrdir.open_workingtree()
        working.lock_read()
        try:
            show_tree_info(working, verbose)
        finally:
            working.unlock()
        return
    except (NoWorkingTree, NotLocalUrl):
        pass

    try:
        branch = a_bzrdir.open_branch()
        branch.lock_read()
        try:
            show_branch_info(branch, verbose)
        finally:
            branch.unlock()
        return
    except NotBranchError:
        pass

    try:
        repository = a_bzrdir.open_repository()
        repository.lock_read()
        try:
            show_repository_info(repository, verbose)
        finally:
            repository.unlock()
        return
    except NoRepositoryPresent:
        pass

    # Return silently, cmd_info returns NotBranchError if no bzrdir
    # could be opened.


def show_tree_info(working, verbose):
    """Output to stdout the 'info' for working."""
    branch = working.branch
    repository = branch.repository
    control = working.bzrdir

    _show_location_info(repository, branch, working)
    _show_format_info(control, repository, branch, working)
    _show_missing_revisions_branch(branch)
    _show_missing_revisions_working(working)
    _show_working_stats(working)
    _show_branch_stats(branch, verbose)
    _show_repository_stats(repository)


def show_branch_info(branch, verbose):
    """Output to stdout the 'info' for branch."""
    repository = branch.repository
    control = branch.bzrdir

    _show_location_info(repository, branch)
    _show_format_info(control, repository, branch)
    _show_missing_revisions_branch(branch)
    _show_branch_stats(branch, verbose)
    _show_repository_stats(repository)


def show_repository_info(repository, verbose):
    """Output to stdout the 'info' for repository."""
    control = repository.bzrdir

    _show_location_info(repository)
    _show_format_info(control, repository)
    _show_repository_info(repository)
    _show_repository_stats(repository)
