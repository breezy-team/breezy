# Copyright (C) 2006, 2007 Canonical Ltd.
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

# Original author: David Allouche

from bzrlib import errors, merge, revision
from bzrlib.branch import Branch, BranchFormat, BranchReferenceFormat
from bzrlib.bzrdir import BzrDir
from bzrlib.trace import note


def switch(control_dir, to_branch, force=False):
    """Switch the branch associated with a checkout.

    :param control_dir: BzrDir of the checkout to change
    :param to_branch: branch that the checkout is to reference
    :param force: skip the check for local commits in a heavy checkout
    """
    _check_pending_merges(control_dir, force)
    try:
        source_repository = control_dir.open_branch().repository
    except errors.NotBranchError:
        source_repository = to_branch.repository
    _set_branch_location(control_dir, to_branch, force)
    tree = control_dir.open_workingtree()
    _update(tree, source_repository)


def _check_pending_merges(control, force=False):
    """Check that there are no outstanding pending merges before switching.

    :param control: BzrDir of the branch to check
    """
    try:
        tree = control.open_workingtree()
    except errors.NotBranchError, ex:
        # Lightweight checkout and branch is no longer there
        if force:
            return
        else:
            raise ex
    # XXX: Should the tree be locked for get_parent_ids?
    existing_pending_merges = tree.get_parent_ids()[1:]
    if len(existing_pending_merges) > 0:
        raise errors.BzrCommandError('Pending merges must be '
            'committed or reverted before using switch.')


def _set_branch_location(control, to_branch, force=False):
    """Set location value of a branch reference.

    :param control: BzrDir of the checkout to change
    :param to_branch: branch that the checkout is to reference
    :param force: skip the check for local commits in a heavy checkout
    """
    branch_format = control.find_branch_format()
    if branch_format.get_reference(control) is not None:
        # Lightweight checkout: update the branch reference
        branch_format.set_reference(control, to_branch)
    else:
        b = control.open_branch()
        bound_branch = b.get_bound_location()
        if bound_branch is not None:
            # Heavyweight checkout: check all local commits
            # have been pushed to the current bound branch then
            # synchronise the local branch with the new remote branch
            # and bind to it
            possible_transports = []
            if not force and _any_local_commits(b, possible_transports):
                raise errors.BzrCommandError(
                    'Cannot switch as local commits found in the checkout. '
                    'Commit these to the bound branch or use --force to '
                    'throw them away.')
            b.set_bound_location(None)
            b.pull(to_branch, overwrite=True,
                possible_transports=possible_transports)
            b.set_bound_location(to_branch.base)
        else:
            raise errors.BzrCommandError('Cannot switch a branch, '
                'only a checkout.')


def _any_local_commits(this_branch, possible_transports):
    """Does this branch have any commits not in the master branch?"""
    last_rev = revision.ensure_null(this_branch.last_revision())
    if last_rev != revision.NULL_REVISION:
        other_branch = this_branch.get_master_branch(possible_transports)
        this_branch.lock_read()
        other_branch.lock_read()
        try:
            other_last_rev = other_branch.last_revision()
            graph = this_branch.repository.get_graph(
                other_branch.repository)
            if not graph.is_ancestor(last_rev, other_last_rev):
                return True
        finally:
            other_branch.unlock()
            this_branch.unlock()
    return False


def _update(tree, source_repository):
    """Update a working tree to the latest revision of its branch.

    :param tree: the working tree
    :param source_repository: repository holding the revisions
    """
    tree.lock_tree_write()
    try:
        to_branch = tree.branch
        if tree.last_revision() == to_branch.last_revision():
            note("Tree is up to date at revision %d.", to_branch.revno())
            return
        base_tree = source_repository.revision_tree(tree.last_revision())
        merge.Merge3Merger(tree, tree, base_tree, to_branch.basis_tree())
        tree.set_last_revision(to_branch.last_revision())
        note('Updated to revision %d.' % to_branch.revno())
    finally:
        tree.unlock()
