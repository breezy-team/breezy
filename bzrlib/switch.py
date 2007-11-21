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

from bzrlib import errors, merge
from bzrlib.branch import Branch, BranchFormat, BranchReferenceFormat
from bzrlib.bzrdir import BzrDir
from bzrlib.trace import note


def switch(control_dir, to_branch):
    """Switch the branch associated with a checkout.

    :param control_dir: BzrDir of the checkout to change
    :param to_branch: branch that the checkout is to be bound to
    """
    _check_switch_branch_format(control_dir)
    _check_pending_merges(control_dir)
    try:
        source_repository = control_dir.open_branch().repository
    except errors.NotBranchError:
        source_repository = to_branch.repository
    _set_branch_location(control_dir, to_branch)
    tree = control_dir.open_workingtree()
    _update(tree, source_repository)


def _check_switch_branch_format(control):
    """Check that the branch format supports the switch operation.

    Note: Only lightweight checkouts are currently supported.
    This may change in the future though.

    :param control: BzrDir of the branch to check
    """
    branch_format = BranchFormat.find_format(control)
    format_string = branch_format.get_format_string()
    if not format_string.startswith("Bazaar-NG Branch Reference Format "):
        raise errors.BzrCommandError(
            'The switch command can only be used on a lightweight checkout.\n'
            'Expected branch reference, found %s at %s' % (
            format_string.strip(), control.root_transport.base))
    if not format_string == BranchReferenceFormat().get_format_string():
        raise errors.BzrCommandError(
            'Unsupported: %r' % (format_string.strip(),))        


def _check_pending_merges(control):
    """Check that there are no outstanding pending merges before switching.

    :param control: BzrDir of the branch to check
    """
    try:
        tree = control.open_workingtree()
        # XXX: Should the tree be locked for get_parent_ids?
        existing_pending_merges = tree.get_parent_ids()[1:]
    except errors.NotBranchError:
        # no tree, so can't be any pending merges???
        return
    if len(existing_pending_merges) > 0:
        raise errors.BzrCommandError('Pending merges must be '
            'committed or reverted before using switch.')


def _set_branch_location(control, to_branch):
    """Set location value of a branch reference.

    :param control: BzrDir of the checkout to change
    :param to_branch: branch that the checkout is to be bound to.
    """
    transport = control.get_branch_transport(None)
    location = transport.put_bytes('location', to_branch.base)


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
