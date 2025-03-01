# Copyright (C) 2008-2012 Canonical Ltd
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

"""UI helper for the push command."""

from . import branch as _mod_branch
from . import controldir, errors, transport
from . import revision as _mod_revision
from .i18n import gettext
from .trace import note, warning


class PushResult:
    """Result of a push operation.

    :ivar branch_push_result: Result of a push between branches
    :ivar target_branch: The target branch
    :ivar stacked_on: URL of the branch on which the result is stacked
    :ivar workingtree_updated: Whether or not the target workingtree was updated.
    """

    def __init__(self):
        self.branch_push_result = None
        self.stacked_on = None
        self.workingtree_updated = None
        self.target_branch = None

    def report(self, to_file):
        """Write a human-readable description of the result."""
        if self.branch_push_result is None:
            if self.stacked_on is not None:
                note(
                    gettext("Created new stacked branch referring to %s.")
                    % self.stacked_on
                )
            else:
                note(gettext("Created new branch."))
        else:
            self.branch_push_result.report(to_file)


def _show_push_branch(
    br_from,
    revision_id,
    location,
    to_file,
    verbose=False,
    overwrite=False,
    remember=False,
    stacked_on=None,
    create_prefix=False,
    use_existing_dir=False,
    no_tree=False,
    lossy=False,
):
    """Push a branch to a location.

    :param br_from: the source branch
    :param revision_id: the revision-id to push up to
    :param location: the url of the destination
    :param to_file: the output stream
    :param verbose: if True, display more output than normal
    :param overwrite: list of things to overwrite ("history", "tags")
        or boolean indicating for everything
    :param remember: if True, store the location as the push location for
        the source branch
    :param stacked_on: the url of the branch, if any, to stack on;
        if set, only the revisions not in that branch are pushed
    :param create_prefix: if True, create the necessary parent directories
        at the destination if they don't already exist
    :param use_existing_dir: if True, proceed even if the destination
        directory exists without a current control directory in it
    :param lossy: Allow lossy push
    """
    to_transport = transport.get_transport(location, purpose="write")
    try:
        dir_to = controldir.ControlDir.open_from_transport(to_transport)
    except errors.NotBranchError:
        # Didn't find anything
        dir_to = None

    if dir_to is None:
        try:
            br_to = br_from.create_clone_on_transport(
                to_transport,
                revision_id=revision_id,
                stacked_on=stacked_on,
                create_prefix=create_prefix,
                use_existing_dir=use_existing_dir,
                no_tree=no_tree,
            )
        except errors.AlreadyControlDirError:
            raise errors.CommandError(
                gettext(
                    "Target directory %s already contains a .bzr directory, "
                    "but it is not valid."
                )
                % (location,)
            )
        except transport.FileExists:
            if not use_existing_dir:
                raise errors.CommandError(
                    gettext(
                        "Target directory %s"
                        " already exists, but does not have a .bzr"
                        " directory. Supply --use-existing-dir to push"
                        " there anyway."
                    )
                    % location
                )
            # This shouldn't occur, but if it does the FileExists error will be
            # more informative than an UnboundLocalError for br_to.
            raise
        except transport.NoSuchFile:
            if not create_prefix:
                raise errors.CommandError(
                    gettext(
                        "Parent directory of %s"
                        " does not exist."
                        "\nYou may supply --create-prefix to create all"
                        " leading parent directories."
                    )
                    % location
                )
            # This shouldn't occur (because create_prefix is true, so
            # create_clone_on_transport should be catching NoSuchFile and
            # creating the missing directories) but if it does the original
            # NoSuchFile error will be more informative than an
            # UnboundLocalError for br_to.
            raise
        except errors.TooManyRedirections:
            raise errors.CommandError(
                gettext("Too many redirections trying to make %s.") % location
            )
        push_result = PushResult()
        # TODO: Some more useful message about what was copied
        try:
            push_result.stacked_on = br_to.get_stacked_on_url()
        except (
            _mod_branch.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat,
            errors.NotStacked,
        ):
            push_result.stacked_on = None
        push_result.target_branch = br_to
        push_result.old_revid = _mod_revision.NULL_REVISION
        push_result.old_revno = 0
        # Remembers if asked explicitly or no previous location is set
        if remember or (remember is None and br_from.get_push_location() is None):
            # FIXME: Should be done only if we succeed ? -- vila 2012-01-18
            br_from.set_push_location(br_to.base)
    else:
        if stacked_on is not None:
            warning(
                "Ignoring request for a stacked branch as repository "
                "already exists at the destination location."
            )
        try:
            push_result = dir_to.push_branch(
                br_from, revision_id, overwrite, remember, create_prefix, lossy=lossy
            )
        except errors.DivergedBranches:
            raise errors.CommandError(
                gettext(
                    "These branches have diverged."
                    '  See "brz help diverged-branches"'
                    " for more information."
                )
            )
        except errors.NoRoundtrippingSupport as e:
            raise errors.CommandError(
                gettext(
                    "It is not possible to losslessly "
                    "push to %s. You may want to use --lossy."
                )
                % e.target_branch.mapping.vcs.abbreviation
            )
        except errors.NoRepositoryPresent:
            # we have a controldir but no branch or repository
            # XXX: Figure out what to do other than complain.
            raise errors.CommandError(
                gettext(
                    "At %s you have a valid .bzr"
                    " control directory, but not a branch or repository. This"
                    " is an unsupported configuration. Please move the target"
                    " directory out of the way and try again."
                )
                % location
            )
        if push_result.workingtree_updated is False:
            warning(
                "This transport does not update the working "
                "tree of: {}. See 'brz help working-trees' for "
                "more information.".format(push_result.target_branch.base)
            )
    push_result.report(to_file)
    if verbose:
        br_to = push_result.target_branch
        with br_to.lock_read():
            from .log import show_branch_change

            show_branch_change(
                br_to, to_file, push_result.old_revno, push_result.old_revid
            )
