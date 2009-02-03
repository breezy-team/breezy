# Copyright (C) 2008 Canonical Ltd
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

"""UI helper for the push command."""

from bzrlib import (builtins, branch, bzrdir, errors, revision as _mod_revision,
                    transport)
from bzrlib.trace import note, warning


def _show_push_branch(br_from, revision_id, location, to_file, verbose=False,
    overwrite=False, remember=False, stacked_on=None, create_prefix=False,
    use_existing_dir=False):
    """Push a branch to a location.

    :param br_from: the source branch
    :param revision_id: the revision-id to push up to
    :param location: the url of the destination
    :param to_file: the output stream
    :param verbose: if True, display more output than normal
    :param overwrite: if False, a current branch at the destination may not
        have diverged from the source, otherwise the push fails
    :param remember: if True, store the location as the push location for
        the source branch
    :param stacked_on: the url of the branch, if any, to stack on;
        if set, only the revisions not in that branch are pushed
    :param create_prefix: if True, create the necessary parent directories
        at the destination if they don't already exist
    :param use_existing_dir: if True, proceed even if the destination
        directory exists without a current .bzr directory in it
    """
    to_transport = transport.get_transport(location)
    br_to = repository_to = dir_to = None
    try:
        dir_to = bzrdir.BzrDir.open_from_transport(to_transport)
    except errors.NotBranchError:
        pass # Didn't find anything

    push_result = None
    if dir_to is None:
        # The destination doesn't exist; create it.
        # XXX: Refactor the create_prefix/no_create_prefix code into a
        #      common helper function

        def make_directory(transport):
            transport.mkdir('.')
            return transport

        def redirected(transport, e, redirection_notice):
            note(redirection_notice)
            return transport._redirected_to(e.source, e.target)

        try:
            to_transport = transport.do_catching_redirections(
                make_directory, to_transport, redirected)
        except errors.FileExists:
            if not use_existing_dir:
                raise errors.BzrCommandError("Target directory %s"
                     " already exists, but does not have a valid .bzr"
                     " directory. Supply --use-existing-dir to push"
                     " there anyway." % location)
        except errors.NoSuchFile:
            if not create_prefix:
                raise errors.BzrCommandError("Parent directory of %s"
                    " does not exist."
                    "\nYou may supply --create-prefix to create all"
                    " leading parent directories."
                    % location)
            builtins._create_prefix(to_transport)
        except errors.TooManyRedirections:
            raise errors.BzrCommandError("Too many redirections trying "
                                         "to make %s." % location)

        # Now the target directory exists, but doesn't have a .bzr
        # directory. So we need to create it, along with any work to create
        # all of the dependent branches, etc.
        dir_to = br_from.bzrdir.clone_on_transport(to_transport,
            revision_id=revision_id, stacked_on=stacked_on)
        br_to = dir_to.open_branch()
        # TODO: Some more useful message about what was copied
        try:
            finally_stacked_on = br_to.get_stacked_on_url()
        except (errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat,
                errors.NotStacked):
            finally_stacked_on = None
        if finally_stacked_on is not None:
            note('Created new stacked branch referring to %s.' %
                 finally_stacked_on)
        else:
            note('Created new branch.')
    else:
        if stacked_on is not None:
            warning("Ignoring request for a stacked branch as repository "
                    "already exists at the destination location.")
        inter = branch.InterBranchBzrDir.get(br_from, dir_to)
        try:
            push_result = inter.push(revision_id=revision_id, 
                overwrite=overwrite)
        except errors.NoRepositoryPresent:
            # we have a bzrdir but no branch or repository
            # XXX: Figure out what to do other than complain.
            raise errors.BzrCommandError("At %s you have a valid .bzr control"
                " directory, but not a branch or repository. This is an"
                " unsupported configuration. Please move the target directory"
                " out of the way and try again."
                % location)
        except errors.DivergedBranches:
            raise errors.BzrCommandError('These branches have diverged.'
                                    '  Try using "merge" and then "push".')
        if not push_result.workingtree_updated:
            warning("This transport does not update the working " 
                    "tree of: %s. See 'bzr help working-trees' for "
                    "more information." % push_result.target_branch.base)

        # We successfully pushed, remember it
        if push_result.source_branch.get_push_location() is None or remember:
            push_result.source_branch.set_push_location(push_result.target_branch.base)

    if push_result is not None:
        push_result.report(to_file)
        old_revid = push_result.old_revid
        old_revno = push_result.old_revno
        br_to = push_result.target_branch
    else:
        old_revid = _mod_revision.NULL_REVISION
        old_revno = 0
    if verbose:
        br_to.lock_read()
        try:
            from bzrlib.log import show_branch_change
            show_branch_change(br_to, to_file, old_revno, old_revid)
        finally:
            br_to.unlock()
