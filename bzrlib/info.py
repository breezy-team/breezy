# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

__all__ = ['show_bzrdir_info']

import time


from bzrlib import (
    bzrdir,
    diff,
    osutils,
    urlutils,
    )
from bzrlib.errors import (NoWorkingTree, NotBranchError,
                           NoRepositoryPresent, NotLocalUrl)
from bzrlib.missing import find_unmerged
from bzrlib.symbol_versioning import (deprecated_function,
        zero_eight, zero_seventeen)


def plural(n, base='', pl=None):
    if n == 1:
        return base
    elif pl is not None:
        return pl
    else:
        return 's'


def _repo_rel_url(repo_url, inner_url):
    """Return path with common prefix of repository path removed.

    If path is not part of the repository, the original path is returned.
    If path is equal to the repository, the current directory marker '.' is
    returned.
    Otherwise, a relative path is returned, with trailing '/' stripped.
    """
    inner_url = urlutils.normalize_url(inner_url)
    repo_url = urlutils.normalize_url(repo_url)
    if inner_url == repo_url:
        return '.'
    result = urlutils.relative_url(repo_url, inner_url)
    if result != inner_url:
        result = result.rstrip('/')
    return result


def _show_location_info(repository, branch=None, working=None):
    """Show known locations for working, branch and repository."""
    repository_path = repository.bzrdir.root_transport.base
    print 'Location:'
    if working and branch:
        working_path = working.bzrdir.root_transport.base
        branch_path = branch.bzrdir.root_transport.base
        if working_path != branch_path:
            # lightweight checkout
            print ' light checkout root: %s' % working_path
            if repository.is_shared():
                # lightweight checkout of branch in shared repository
                print '   shared repository: %s' % repository_path
                print '   repository branch: %s' % (
                    _repo_rel_url(repository_path, branch_path))
            else:
                # lightweight checkout of standalone branch
                print '  checkout of branch: %s' % branch_path
        elif repository.is_shared():
            # branch with tree inside shared repository
            print '    shared repository: %s' % repository_path
            print '  repository checkout: %s' % (
                _repo_rel_url(repository_path, branch_path))
        elif branch.get_bound_location():
            # normal checkout
            print '       checkout root: %s' % working_path
            print '  checkout of branch: %s' % branch.get_bound_location()
        else:
            # standalone
            print '  branch root: %s' % working_path
    elif branch:
        branch_path = branch.bzrdir.root_transport.base
        if repository.is_shared():
            # branch is part of shared repository
            print '  shared repository: %s' % repository_path
            print '  repository branch: %s' % (
                _repo_rel_url(repository_path, branch_path))
        else:
            # standalone branch
            print '  branch root: %s' % branch_path
    else:
        # shared repository
        assert repository.is_shared()
        print '  shared repository: %s' % repository_path


def _show_related_info(branch):
    """Show parent and push location of branch."""
    if branch.get_parent() or branch.get_push_location():
        print
        print 'Related branches:'
        if branch.get_parent():
            if branch.get_push_location():
                print '      parent branch: %s' % branch.get_parent()
            else:
                print '  parent branch: %s' % branch.get_parent()
        if branch.get_push_location():
            print '  publish to branch: %s' % branch.get_push_location()


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


def _show_locking_info(repository, branch=None, working=None):
    """Show locking status of working, branch and repository."""
    if (repository.get_physical_lock_status() or
        (branch and branch.get_physical_lock_status()) or
        (working and working.get_physical_lock_status())):
        print
        print 'Lock status:'
        if working:
            if working.get_physical_lock_status():
                status = 'locked'
            else:
                status = 'unlocked'
            print '  working tree: %s' % status
        if branch:
            if branch.get_physical_lock_status():
                status = 'locked'
            else:
                status = 'unlocked'
            print '        branch: %s' % status
        if repository:
            if repository.get_physical_lock_status():
                status = 'locked'
            else:
                status = 'unlocked'
            print '    repository: %s' % status


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
    branch_revno, branch_last_revision = branch.last_revision_info()
    try:
        tree_last_id = working.get_parent_ids()[0]
    except IndexError:
        tree_last_id = None

    if branch_revno and tree_last_id != branch_last_revision:
        tree_last_revno = branch.revision_id_to_revno(tree_last_id)
        missing_count = branch_revno - tree_last_revno
        print
        print 'Working tree is out of date: missing %d revision%s.' % (
            missing_count, plural(missing_count))


def _show_working_stats(working):
    """Show statistics about a working tree."""
    basis = working.basis_tree()
    work_inv = working.inventory
    delta = working.changes_from(basis, want_unchanged=True)

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
        if (work_inv.get_file_kind(file_id) == 'directory' and 
            not work_inv.is_root(file_id)):
            dir_cnt += 1
    print '  %8d versioned %s' \
          % (dir_cnt,
             plural(dir_cnt, 'subdirectory', 'subdirectories'))


def _show_branch_stats(branch, verbose):
    """Show statistics about a branch."""
    revno, head = branch.last_revision_info()
    print
    print 'Branch history:'
    print '  %8d revision%s' % (revno, plural(revno))
    stats = branch.repository.gather_stats(head, committers=verbose)
    if verbose:
        committers = stats['committers']
        print '  %8d committer%s' % (committers, plural(committers))
    if revno:
        timestamp, timezone = stats['firstrev']
        age = int((time.time() - timestamp) / 3600 / 24)
        print '  %8d day%s old' % (age, plural(age))
        print '   first revision: %s' % osutils.format_date(timestamp,
            timezone)
        timestamp, timezone = stats['latestrev']
        print '  latest revision: %s' % osutils.format_date(timestamp,
            timezone)
    return stats


def _show_repository_info(repository):
    """Show settings of a repository."""
    if repository.make_working_trees():
        print
        print 'Create working tree for new branches inside the repository.'


def _show_repository_stats(stats):
    """Show statistics about a repository."""
    if 'revisions' in stats or 'size' in stats:
        print
        print 'Repository:'
    if 'revisions' in stats:
        revisions = stats['revisions']
        print '  %8d revision%s' % (revisions, plural(revisions))
    if 'size' in stats:
        print '  %8d KiB' % (stats['size']/1024)

def show_bzrdir_info(a_bzrdir, verbose=False):
    """Output to stdout the 'info' for a_bzrdir."""
    try:
        tree = a_bzrdir.open_workingtree(
            recommend_upgrade=False)
    except (NoWorkingTree, NotLocalUrl):
        tree = None
        try:
            branch = a_bzrdir.open_branch()
        except NotBranchError:
            branch = None
            try:
                repository = a_bzrdir.open_repository()
            except NoRepositoryPresent:
                # Return silently; cmd_info already returned NotBranchError
                # if no bzrdir could be opened.
                return
            else:
                lockable = repository
        else:
            repository = branch.repository
            lockable = branch
    else:
        branch = tree.branch
        repository = branch.repository
        lockable = tree

    lockable.lock_read()
    try:
        show_component_info(a_bzrdir, repository, branch, tree, verbose)
    finally:
        lockable.unlock()


def show_component_info(control, repository, branch=None, working=None,
    verbose=1):
    """Write info about all bzrdir components to stdout"""
    if verbose is False:
        verbose = 1
    if verbose is True:
        verbose = 2
    layout = describe_layout(repository, branch, working)
    format = describe_format(control, repository, branch, working)
    print "%s (format: %s)" % (layout, format)
    _show_location_info(repository, branch, working)
    if verbose == 0:
        return
    if branch is not None:
        _show_related_info(branch)
    _show_format_info(control, repository, branch, working)
    _show_locking_info(repository, branch, working)
    if branch is not None:
        _show_missing_revisions_branch(branch)
    if working is not None:
        _show_missing_revisions_working(working)
        _show_working_stats(working)
    elif branch is not None:
        _show_missing_revisions_branch(branch)
    if branch is not None:
        stats = _show_branch_stats(branch, verbose==2)
    else:
        stats = repository.gather_stats()
    if branch is None and working is None:
        _show_repository_info(repository)
    _show_repository_stats(stats)


def describe_layout(repository=None, branch=None, tree=None):
    """Convert a control directory layout into a user-understandable term

    Common outputs include "Standalone tree", "Repository branch" and
    "Checkout".  Uncommon outputs include "Unshared repository with trees"
    and "Empty control directory"
    """
    if repository is None:
        return 'Empty control directory'
    if branch is None and tree is None:
        if repository.is_shared():
            phrase = 'Shared repository'
        else:
            phrase = 'Unshared repository'
        if repository.make_working_trees():
            phrase += ' with trees'
        return phrase
    else:
        if repository.is_shared():
            independence = "Repository "
        else:
            independence = "Standalone "
        if tree is not None:
            phrase = "tree"
        else:
            phrase = "branch"
        if branch is None and tree is not None:
            phrase = "branchless tree"
        else:
            if (tree is not None and tree.bzrdir.root_transport.base !=
                branch.bzrdir.root_transport.base):
                independence = ''
                phrase = "Lightweight checkout"
            elif branch.get_bound_location() is not None:
                if independence == 'Standalone ':
                    independence = ''
                if tree is None:
                    phrase = "Bound branch"
                else:
                    phrase = "Checkout"
        if independence != "":
            phrase = phrase.lower()
        return "%s%s" % (independence, phrase)


def describe_format(control, repository, branch, tree):
    """Determine the format of an existing control directory

    Several candidates may be found.  If so, the names are returned as a
    single string, separated by slashes.

    If no matching candidate is found, "unnamed" is returned.
    """
    candidates  = []
    if (branch is not None and tree is not None and
        branch.bzrdir.root_transport.base !=
        tree.bzrdir.root_transport.base):
        branch = None
        repository = None
    for key in bzrdir.format_registry.keys():
        format = bzrdir.format_registry.make_bzrdir(key)
        if isinstance(format, bzrdir.BzrDirMetaFormat1):
            if (tree and format.workingtree_format !=
                tree._format):
                continue
            if (branch and format.get_branch_format() !=
                branch._format):
                continue
            if (repository and format.repository_format !=
                repository._format):
                continue
        if format.__class__ is not control._format.__class__:
            continue
        candidates.append(key)
    if len(candidates) == 0:
        return 'unnamed'
    new_candidates = [c for c in candidates if c != 'default']
    if len(new_candidates) > 0:
        candidates = new_candidates
    new_candidates = [c for c in candidates if not
        bzrdir.format_registry.get_info(c).hidden]
    if len(new_candidates) > 0:
        candidates = new_candidates
    return ' / '.join(candidates)

@deprecated_function(zero_eight)
def show_info(b):
    """Please see show_bzrdir_info."""
    return show_bzrdir_info(b.bzrdir)


@deprecated_function(zero_seventeen)
def show_tree_info(working, verbose):
    """Output to stdout the 'info' for working."""
    branch = working.branch
    repository = branch.repository
    control = working.bzrdir
    show_component_info(control, repository, branch, working, verbose)


@deprecated_function(zero_seventeen)
def show_branch_info(branch, verbose):
    """Output to stdout the 'info' for branch."""
    repository = branch.repository
    control = branch.bzrdir
    show_component_info(control, repository, branch, verbose=verbose)


@deprecated_function(zero_seventeen)
def show_repository_info(repository, verbose):
    """Output to stdout the 'info' for repository."""
    control = repository.bzrdir
    show_component_info(control, repository, verbose=verbose)
