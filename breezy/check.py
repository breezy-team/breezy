# Copyright (C) 2005, 2006 Canonical Ltd
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

# TODO: Perhaps have a way to record errors other than by raising exceptions;
# would perhaps be enough to accumulate exception objects in a list without
# raising them.  If there's more than one exception it'd be good to see them
# all.

"""Checking of bzr objects.

check_refs is a concept used for optimising check. Objects that depend on other
objects (e.g. tree on repository) can list the objects they would be requesting
so that when the dependent object is checked, matches can be pulled out and
evaluated in-line rather than re-reading the same data many times.
check_refs are tuples (kind, value). Currently defined kinds are:

* 'trees', where value is a revid and the looked up objects are revision trees.
* 'lefthand-distance', where value is a revid and the looked up objects are the
  distance along the lefthand path to NULL for that revid.
* 'revision-existence', where value is a revid, and the result is True or False
  indicating that the revision was found/not found.
"""

import contextlib

from . import errors
from .controldir import ControlDir
from .i18n import gettext
from .trace import note


class Check:
    """Check a repository."""

    def __init__(self, repository, check_repo=True):
        """Initialize a Check instance.

        Args:
            repository: The repository to check.
            check_repo: Whether to check the repository itself. Defaults to True.
        """
        self.repository = repository

    def report_results(self, verbose):
        """Report the results of the check operation.

        This is an abstract method that must be implemented by subclasses.

        Args:
            verbose: Whether to provide verbose output.

        Raises:
            NotImplementedError: Always raised as this is an abstract method.
        """
        raise NotImplementedError(self.report_results)


def scan_branch(branch, needed_refs, exit_stack):
    """Scan a branch for refs.

    :param branch:  The branch to schedule for checking.
    :param needed_refs: Refs we are accumulating.
    :param exit_stack: The exit stack accumulating.
    """
    note(gettext("Checking branch at '%s'.") % (branch.base,))
    exit_stack.enter_context(branch.lock_read())
    branch_refs = branch._get_check_refs()
    for ref in branch_refs:
        reflist = needed_refs.setdefault(ref, [])
        reflist.append(branch)


def scan_tree(base_tree, tree, needed_refs, exit_stack):
    """Scan a tree for refs.

    :param base_tree: The original tree check opened, used to detect duplicate
        tree checks.
    :param tree:  The tree to schedule for checking.
    :param needed_refs: Refs we are accumulating.
    :param exit_stack: The exit stack accumulating.
    """
    if base_tree is not None and tree.basedir == base_tree.basedir:
        return
    note(gettext("Checking working tree at '%s'.") % (tree.basedir,))
    exit_stack.enter_context(tree.lock_read())
    tree_refs = tree._get_check_refs()
    for ref in tree_refs:
        reflist = needed_refs.setdefault(ref, [])
        reflist.append(tree)


def check_dwim(path, verbose, do_branch=False, do_repo=False, do_tree=False):
    """Check multiple objects.

    If errors occur they are accumulated and reported as far as possible, and
    an exception raised at the end of the process.
    """
    try:
        (
            base_tree,
            branch,
            repo,
            relpath,
        ) = ControlDir.open_containing_tree_branch_or_repository(path)
    except errors.NotBranchError:
        base_tree = branch = repo = None

    with contextlib.ExitStack() as exit_stack:
        needed_refs = {}
        if base_tree is not None:
            # If the tree is a lightweight checkout we won't see it in
            # repo.find_branches - add now.
            if do_tree:
                scan_tree(None, base_tree, needed_refs, exit_stack)
            branch = base_tree.branch
        if branch is not None:
            # We have a branch
            if repo is None:
                # The branch is in a shared repository
                repo = branch.repository
        if repo is not None:
            exit_stack.enter_context(repo.lock_read())
            branches = list(repo.find_branches(using=True))
            saw_tree = False
            if do_branch or do_tree:
                for branch in branches:
                    if do_tree:
                        try:
                            tree = branch.controldir.open_workingtree()
                            saw_tree = True
                        except (errors.NotLocalUrl, errors.NoWorkingTree):
                            pass
                        else:
                            scan_tree(base_tree, tree, needed_refs, exit_stack)
                    if do_branch:
                        scan_branch(branch, needed_refs, exit_stack)
            if do_branch and not branches:
                note(gettext("No branch found at specified location."))
            if do_tree and base_tree is None and not saw_tree:
                note(gettext("No working tree found at specified location."))
            if do_repo or do_branch or do_tree:
                if do_repo:
                    note(gettext("Checking repository at '%s'.") % (repo.user_url,))
                result = repo.check(None, callback_refs=needed_refs, check_repo=do_repo)
                result.report_results(verbose)
        else:
            if do_tree:
                note(gettext("No working tree found at specified location."))
            if do_branch:
                note(gettext("No branch found at specified location."))
            if do_repo:
                note(gettext("No repository found at specified location."))
