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

from bzrlib import builtins, bzrdir, errors, transport
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
    else:
        # If we can open a branch, use its direct repository, otherwise see
        # if there is a repository without a branch.
        try:
            br_to = dir_to.open_branch()
        except errors.NotBranchError:
            # Didn't find a branch, can we find a repository?
            try:
                repository_to = dir_to.find_repository()
            except errors.NoRepositoryPresent:
                pass
        else:
            # Found a branch, so we must have found a repository
            repository_to = br_to.repository

    push_result = None
    if verbose:
        old_rh = []
    if dir_to is None:
        # The destination doesn't exist; create it.
        # XXX: Refactor the create_prefix/no_create_prefix code into a
        #      common helper function

        def make_directory(transport):
            transport.mkdir('.')
            return transport

        def redirected(redirected_transport, e, redirection_notice):
            return transport.get_transport(e.get_target_url())

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
        if stacked_on is not None:
            # This should be buried in the clone method itself. TODO.
            try:
                # if the from format is stackable, this will either work or
                # trigger NotStacked. If it's not, an error will be given to
                # the user.
                br_from.get_stacked_on_url()
            except errors.NotStacked:
                pass
            # now we need to sprout the repository,
            dir_to = br_from.bzrdir._format.initialize_on_transport(to_transport)
            br_from.repository._format.initialize(dir_to)
            br_to = br_from._format.initialize(dir_to)
            br_to.set_stacked_on_url(stacked_on)
            # and copy the data up.
            br_from.push(br_to)
        else:
            dir_to = br_from.bzrdir.clone_on_transport(to_transport,
                revision_id=revision_id)
        br_to = dir_to.open_branch()
        # TODO: Some more useful message about what was copied
        if stacked_on is not None:
            note('Created new stacked branch referring to %s.' % stacked_on)
        else:
            note('Created new branch.')
        # We successfully created the target, remember it
        if br_from.get_push_location() is None or remember:
            br_from.set_push_location(br_to.base)
    elif repository_to is None:
        # we have a bzrdir but no branch or repository
        # XXX: Figure out what to do other than complain.
        raise errors.BzrCommandError("At %s you have a valid .bzr control"
            " directory, but not a branch or repository. This is an"
            " unsupported configuration. Please move the target directory"
            " out of the way and try again."
            % location)
    elif br_to is None:
        # We have a repository but no branch, copy the revisions, and then
        # create a branch.
        if stacked_on is not None:
            warning("Ignoring request for a stacked branch as repository "
                    "already exists at the destination location.")
        repository_to.fetch(br_from.repository, revision_id=revision_id)
        br_to = br_from.clone(dir_to, revision_id=revision_id)
        note('Created new branch.')
        if br_from.get_push_location() is None or remember:
            br_from.set_push_location(br_to.base)
    else: # We have a valid to branch
        if stacked_on is not None:
            warning("Ignoring request for a stacked branch as branch "
                    "already exists at the destination location.")
        # We were able to connect to the remote location, so remember it.
        # (We don't need to successfully push because of possible divergence.)
        if br_from.get_push_location() is None or remember:
            br_from.set_push_location(br_to.base)
        if verbose:
            old_rh = br_to.revision_history()
        try:
            try:
                tree_to = dir_to.open_workingtree()
            except errors.NotLocalUrl:
                warning("This transport does not update the working " 
                        "tree of: %s. See 'bzr help working-trees' for "
                        "more information." % br_to.base)
                push_result = br_from.push(br_to, overwrite,
                                           stop_revision=revision_id)
            except errors.NoWorkingTree:
                push_result = br_from.push(br_to, overwrite,
                                           stop_revision=revision_id)
            else:
                tree_to.lock_write()
                try:
                    push_result = br_from.push(tree_to.branch, overwrite,
                                               stop_revision=revision_id)
                    tree_to.update()
                finally:
                    tree_to.unlock()
        except errors.DivergedBranches:
            raise errors.BzrCommandError('These branches have diverged.'
                                    '  Try using "merge" and then "push".')
    if push_result is not None:
        push_result.report(to_file)
    elif verbose:
        new_rh = br_to.revision_history()
        if old_rh != new_rh:
            # Something changed
            from bzrlib.log import show_changed_revisions
            show_changed_revisions(br_to, old_rh, new_rh,
                                   to_file=to_file)
    else:
        # we probably did a clone rather than a push, so a message was
        # emitted above
        pass
