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

from ... import (
    branch as _mod_branch,
    controldir,
    errors,
    msgeditor,
    urlutils,
    )
from ...i18n import gettext
from ...commands import Command
from ...option import (
    ListOption,
    Option,
    RegistryOption,
    )
from ...sixish import text_type
from ...trace import note
from . import (
    propose as _mod_propose,
    )


def branch_name(branch):
    if branch.name:
        return branch.name
    return urlutils.basename(branch.user_url)


class cmd_publish_derived(Command):
    __doc__ = """Publish a derived branch.

    Try to create a public copy of a local branch on a hosting site,
    derived from the specified base branch.

    Reasonable defaults are picked for owner name, branch name and project
    name, but they can also be overridden from the command-line.
    """

    takes_options = [
            'directory',
            Option('owner', help='Owner of the new remote branch.', type=str),
            Option('project', help='Project name for the new remote branch.', type=str),
            Option('name', help='Name of the new remote branch.', type=str),
            ]
    takes_args = ['submit_branch?']

    def run(self, submit_branch=None, owner=None, name=None, project=None,
            directory='.'):
        local_branch = _mod_branch.Branch.open_containing(directory)[0]
        self.add_cleanup(local_branch.lock_write().unlock)
        if submit_branch is None:
            submit_branch = local_branch.get_submit_branch()
            note(gettext('Using submit branch %s') % submit_branch)
        if submit_branch is None:
            submit_branch = local_branch.get_parent()
            note(gettext('Using parent branch %s') % submit_branch)
        submit_branch = _mod_branch.Branch.open(submit_branch)
        if name is None:
            name = branch_name(local_branch)
        hoster = _mod_propose.get_hoster(submit_branch)
        remote_branch, public_url = hoster.publish_derived(
                local_branch, submit_branch, name=name, project=project,
                owner=owner)
        local_branch.set_push_location(remote_branch.user_url)
        local_branch.set_public_branch(public_url)
        note(gettext("Pushed to %s") % public_url)


class cmd_propose_merge(Command):
    __doc__ = """Propose a branch for merging.

    This command creates a merge proposal for the local
    branch to the target branch. The format of the merge
    proposal depends on the submit branch.
    """

    takes_options = ['directory',
            RegistryOption(
                'hoster',
                help='Use the hoster.',
                lazy_registry=('breezy.plugins.propose.propose', 'hosters')),
            ListOption('reviewers', short_name='R', type=text_type,
                help='Requested reviewers.'),
            Option('name', help='Name of the new remote branch.', type=str),
            Option('description', help='Description of the change.', type=str),
            ListOption('labels', short_name='l', type=text_type,
                help='Labels to apply.'),
            ]
    takes_args = ['submit_branch?']

    aliases = ['propose']

    def run(self, submit_branch=None, directory='.', hoster=None, reviewers=None, name=None,
            description=None, labels=None):
        tree, branch, relpath = controldir.ControlDir.open_containing_tree_or_branch(
            directory)
        if submit_branch is None:
            submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            submit_branch = branch.get_parent()
        if submit_branch is None:
            raise errors.BzrCommandError(gettext("No target location specified or remembered"))
        else:
            target = _mod_branch.Branch.open(submit_branch)
        if hoster is None:
            hoster = _mod_propose.get_hoster(target)
        else:
            hoster = hoster.probe(target)
        if name is None:
            name = branch_name(branch)
        remote_branch, public_branch_url = hoster.publish_derived(
                branch, target, name=name)
        branch.set_push_location(remote_branch.user_url)
        note(gettext('Published branch to %s') % public_branch_url)
        proposal_builder = hoster.get_proposer(remote_branch, target)
        if description is None:
            body = proposal_builder.get_initial_body()
            info = proposal_builder.get_infotext()
            description = msgeditor.edit_commit_message(info, start_message=body)
        try:
            proposal = proposal_builder.create_proposal(
                description=description, reviewers=reviewers, labels=labels)
        except _mod_propose.MergeProposalExists as e:
            raise errors.BzrCommandError(gettext(
                'There is already a branch merge proposal: %s') % e.url)
        note(gettext('Merge proposal created: %s') % proposal.url)


class cmd_find_merge_proposal(Command):
    __doc__ = """Find a merge proposal.

    """

    takes_options = ['directory']
    takes_args = ['submit_branch?']
    aliases = ['find-proposal']

    def run(self, directory='.', submit_branch=None):
        tree, branch, relpath = controldir.ControlDir.open_containing_tree_or_branch(
            directory)
        public_location = branch.get_public_branch()
        if public_location:
            branch = _mod_branch.Branch.open(public_location)
        if submit_branch is None:
            submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            submit_branch = branch.get_parent()
        if submit_branch is None:
            raise errors.BzrCommandError(gettext("No target location specified or remembered"))
        else:
            target = _mod_branch.Branch.open(submit_branch)
        hoster = _mod_propose.get_hoster(branch)
        mp = hoster.get_proposal(branch, target)
        self.outf.write(gettext('Merge proposal: %s\n') % mp.url)
