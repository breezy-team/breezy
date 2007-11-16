# Copyright (C) 2007 Canonical Ltd.
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

from bzrlib import errors, merge
from bzrlib.branch import Branch, BranchFormat, BranchReferenceFormat
from bzrlib.bzrdir import BzrDir
from bzrlib.trace import note


def switch(control_dir, to_branch):
    try:
        source_repository = control_dir.open_branch().repository
    except errors.NotBranchError:
        source_repository = to_branch.repository
    set_branch_location(control_dir, to_branch)
    tree = control_dir.open_workingtree()
    _update(tree, source_repository, to_branch)


def _update(tree, source_repository, to_branch):
    tree.lock_tree_write()
    try:
        if tree.last_revision() == tree.branch.last_revision():
            note("Tree is up to date.")
            return
        base_tree = source_repository.revision_tree(tree.last_revision())
        merge.Merge3Merger(tree, tree, base_tree, to_branch.basis_tree())
        tree.set_last_revision(to_branch.last_revision())
        note('Updated to revision %d' % tree.branch.revno())
    finally:
        tree.unlock()


def _check_switch_branch_format(control):
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


def set_branch_location(control, to_branch):
    """Set location value of a branch reference.

    :param control: BzrDir containing the branch reference
    :param location: value to write to the branch reference location.
    """
    _check_switch_branch_format(control)
    branch_format = BranchFormat.find_format(control)
    transport = control.get_branch_transport(None)
    location = transport.put_bytes('location', to_branch.base)
