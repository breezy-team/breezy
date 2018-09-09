# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Propose command implementations."""

import webbrowser

from ... import (
    branch as _mod_branch,
    controldir,
    errors,
    msgeditor,
    )
from ...i18n import gettext
from ...commands import Command
from ...option import (
    ListOption,
    RegistryOption,
    )
from ...sixish import text_type
from . import (
    propose as _mod_propose,
    )


class cmd_publish(Command):
    __doc__ = """Publish a branch.

    Try to create a public copy of a local branch.
    How this is done depends on the submit branch and where it is
    hosted.
    """

    def run(self, submit_branch=None, directory='.'):
        pass


class cmd_propose_merge(Command):
    __doc__ = """Propose a branch for merging.

    This command creates a merge proposal for the local
    branch to the target branch. The format of the merge
    proposal depends on the submit branch.
    """

    takes_options = ['directory',
            RegistryOption(
                'mechanism',
                help='Use the specified proposal mechanism.',
                lazy_registry=('breezy.plugins.propose.propose', 'proposers')),
            ListOption('reviewers', short_name='R', type=text_type,
                help='Requested reviewers.'),
            ]
    takes_args = ['submit_branch?']

    aliases = ['propose']

    def run(self, submit_branch=None, directory='.', mechanism=None, reviewers=None):
        tree, branch, relpath = controldir.ControlDir.open_containing_tree_or_branch(
            directory)
        public_branch = branch.get_public_branch()
        if public_branch:
            # TODO(jelmer): Verify that the public branch is up to date
            branch = _mod_branch.Branch.open(public_branch)
        if submit_branch is None:
            submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            raise errors.BzrCommandError(gettext("No location specified or remembered"))
        else:
            target = _mod_branch.Branch.open(submit_branch)
        if mechanism is None:
            proposer = _mod_propose.get_proposer(branch, target)
        else:
            proposer = mechanism(branch, target)
        body = proposer.get_initial_body()
        info = proposer.get_infotext()
        description = msgeditor.edit_commit_message(info, start_message=body)
        try:
            proposal = proposer.create_proposal(
                description=description, reviewers=reviewers)
        except _mod_propose.MergeProposalExists as e:
            raise errors.BzrCommandError(gettext(
                'There is already a branch merge proposal: %s') % e.url)
        webbrowser.open(proposal.url)
