# Copyright (C) 2007, 2009-2012 Canonical Ltd.
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# Original author: David Allouche

from . import (
    errors,
    lock,
    merge,
    revision
    )
from .branch import Branch
from .i18n import gettext
from .trace import note


def _run_post_switch_hooks(control_dir, to_branch, force, revision_id):
    from .branch import SwitchHookParams
    hooks = Branch.hooks['post_switch']
    if not hooks:
        return
    params = SwitchHookParams(control_dir, to_branch, force, revision_id)
    for hook in hooks:
        hook(params)


def switch(control_dir, to_branch, force=False, quiet=False, revision_id=None,
           store_uncommitted=False, possible_transports=None):
    """Switch the branch associated with a checkout.

    :param control_dir: ControlDir of the checkout to change
    :param to_branch: branch that the checkout is to reference
    :param force: skip the check for local commits in a heavy checkout
    :param revision_id: revision ID to switch to.
    :param store_uncommitted: If True, store uncommitted changes in the
        branch.
    """
    try:
        tree = control_dir.open_workingtree()
    except errors.NotBranchError as ex:
        # Lightweight checkout and branch is no longer there
        if not force or store_uncommitted:
            raise ex
        else:
            tree = None
    else:
        if store_uncommitted or tree.branch.get_bound_location():
            tree.lock_write()
        else:
            tree.lock_tree_write()
    try:
        if tree is not None:
            parent_ids = tree.get_parent_ids()
            if len(parent_ids) > 1:
                raise errors.CommandError(
                    gettext('Pending merges must be '
                            'committed or reverted before using switch.'))

        if store_uncommitted:
            tree.store_uncommitted()
        if tree is None:
            source_repository = to_branch.repository
            base_revision_id = None
        else:
            source_repository = tree.branch.repository
            # Attempt to retrieve the base_revision_id now, since some
            # working tree formats (i.e. git) don't have their own
            # last_revision but just use that of the currently active branch.
            base_revision_id = tree.last_revision()
    finally:
        if tree is not None:
            tree.unlock()
    with to_branch.lock_read():
        _set_branch_location(control_dir, to_branch, tree.branch if tree else None, force)
    tree = control_dir.open_workingtree()
    if store_uncommitted:
        tree.lock_write()
    else:
        tree.lock_tree_write()
    try:
        if base_revision_id is None:
            # If we couldn't get to the tree's last_revision earlier, perhaps
            # we can now.
            base_revision_id = tree.last_revision()
        if revision_id is None:
            revision_id = to_branch.last_revision()
        if base_revision_id == revision_id:
            if not quiet:
                note(gettext("Tree is up to date at revision %d."),
                     to_branch.revno())
        else:
            base_tree = source_repository.revision_tree(base_revision_id)
            target_tree = to_branch.repository.revision_tree(revision_id)
            merge.Merge3Merger(tree, tree, base_tree, target_tree)
            tree.set_last_revision(revision_id)
            if not quiet:
                note(gettext('Updated to revision %d.') % to_branch.revno())
        if store_uncommitted:
            tree.restore_uncommitted()
        _run_post_switch_hooks(control_dir, to_branch, force, revision_id)
    finally:
        tree.unlock()


def _set_branch_location(control, to_branch, current_branch, force=False):
    """Set location value of a branch reference.

    :param control: ControlDir of the checkout to change
    :param to_branch: branch that the checkout is to reference
    :param force: skip the check for local commits in a heavy checkout
    """
    branch_format = control.find_branch_format()
    if branch_format.get_reference(control) is not None:
        # Lightweight checkout: update the branch reference
        branch_format.set_reference(control, None, to_branch)
    else:
        b = current_branch
        bound_branch = b.get_bound_location()
        if bound_branch is not None:
            # Heavyweight checkout: check all local commits
            # have been pushed to the current bound branch then
            # synchronise the local branch with the new remote branch
            # and bind to it
            possible_transports = []
            try:
                if not force and _any_local_commits(b, possible_transports):
                    raise errors.CommandError(gettext(
                        'Cannot switch as local commits found in the checkout. '
                        'Commit these to the bound branch or use --force to '
                        'throw them away.'))
            except errors.BoundBranchConnectionFailure as e:
                raise errors.CommandError(gettext(
                    'Unable to connect to current master branch %(target)s: '
                    '%(error)s To switch anyway, use --force.') %
                    e.__dict__)
            with b.lock_write():
                b.set_bound_location(None)
                b.pull(to_branch, overwrite=True,
                       possible_transports=possible_transports)
                b.set_bound_location(to_branch.base)
                b.set_parent(b.get_master_branch().get_parent())
        else:
            # If this is a standalone tree and the new branch
            # is derived from this one, create a lightweight checkout.
            with b.lock_read():
                graph = b.repository.get_graph(to_branch.repository)
                if (b.controldir._format.colocated_branches and
                    (force or graph.is_ancestor(
                        b.last_revision(), to_branch.last_revision()))):
                    b.controldir.destroy_branch()
                    b.controldir.set_branch_reference(to_branch, name="")
                else:
                    raise errors.CommandError(
                        gettext('Cannot switch a branch, only a checkout.'))


def _any_local_commits(this_branch, possible_transports):
    """Does this branch have any commits not in the master branch?"""
    last_rev = revision.ensure_null(this_branch.last_revision())
    if last_rev != revision.NULL_REVISION:
        other_branch = this_branch.get_master_branch(possible_transports)
        with this_branch.lock_read(), other_branch.lock_read():
            other_last_rev = other_branch.last_revision()
            graph = this_branch.repository.get_graph(
                other_branch.repository)
            if not graph.is_ancestor(last_rev, other_last_rev):
                return True
    return False
