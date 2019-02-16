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

from __future__ import absolute_import

from io import StringIO

from ... import (
    branch as _mod_branch,
    controldir,
    errors,
    log as _mod_log,
    missing as _mod_missing,
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
        Option('project', help='Project name for the new remote branch.',
               type=str),
        Option('name', help='Name of the new remote branch.', type=str),
        Option('no-allow-lossy',
               help='Allow fallback to lossy push, if necessary.'),
        Option('overwrite', help="Overwrite existing commits."),
        ]
    takes_args = ['submit_branch?']

    def run(self, submit_branch=None, owner=None, name=None, project=None,
            no_allow_lossy=False, overwrite=False, directory='.'):
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
            owner=owner, allow_lossy=not no_allow_lossy,
            overwrite=overwrite)
        local_branch.set_push_location(remote_branch.user_url)
        local_branch.set_public_branch(public_url)
        note(gettext("Pushed to %s") % public_url)


def summarize_unmerged(local_branch, remote_branch, target,
                       prerequisite_branch=None):
    """Generate a text description of the unmerged revisions in branch.

    :param branch: The proposed branch
    :param target: Target branch
    :param prerequisite_branch: Optional prerequisite branch
    :return: A string
    """
    log_format = _mod_log.log_formatter_registry.get_default(local_branch)
    to_file = StringIO()
    lf = log_format(to_file=to_file, show_ids=False, show_timezone='original')
    if prerequisite_branch:
        local_extra = _mod_missing.find_unmerged(
            remote_branch, prerequisite_branch, restrict='local')[0]
    else:
        local_extra = _mod_missing.find_unmerged(
            remote_branch, target, restrict='local')[0]

    if remote_branch.supports_tags():
        rev_tag_dict = remote_branch.tags.get_reverse_tag_dict()
    else:
        rev_tag_dict = {}

    for revision in _mod_missing.iter_log_revisions(
            local_extra, local_branch.repository, False, rev_tag_dict):
        lf.log_revision(revision)
    return to_file.getvalue()


class cmd_propose_merge(Command):
    __doc__ = """Propose a branch for merging.

    This command creates a merge proposal for the local
    branch to the target branch. The format of the merge
    proposal depends on the submit branch.
    """

    takes_options = [
        'directory',
        RegistryOption(
            'hoster',
            help='Use the hoster.',
            lazy_registry=('breezy.plugins.propose.propose', 'hosters')),
        ListOption('reviewers', short_name='R', type=text_type,
                   help='Requested reviewers.'),
        Option('name', help='Name of the new remote branch.', type=str),
        Option('description', help='Description of the change.', type=str),
        Option('prerequisite', help='Prerequisite branch.', type=str),
        ListOption('labels', short_name='l', type=text_type,
                   help='Labels to apply.'),
        Option('no-allow-lossy',
               help='Allow fallback to lossy push, if necessary.'),
        ]
    takes_args = ['submit_branch?']

    aliases = ['propose']

    def run(self, submit_branch=None, directory='.', hoster=None,
            reviewers=None, name=None, no_allow_lossy=False, description=None,
            labels=None, prerequisite=None):
        tree, branch, relpath = (
            controldir.ControlDir.open_containing_tree_or_branch(directory))
        if submit_branch is None:
            submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            submit_branch = branch.get_parent()
        if submit_branch is None:
            raise errors.BzrCommandError(
                gettext("No target location specified or remembered"))
        else:
            target = _mod_branch.Branch.open(submit_branch)
        if hoster is None:
            hoster = _mod_propose.get_hoster(target)
        else:
            hoster = hoster.probe(target)
        if name is None:
            name = branch_name(branch)
        remote_branch, public_branch_url = hoster.publish_derived(
            branch, target, name=name, allow_lossy=not no_allow_lossy)
        branch.set_push_location(remote_branch.user_url)
        note(gettext('Published branch to %s') % public_branch_url)
        if prerequisite is not None:
            prerequisite_branch = _mod_branch.Branch.open(prerequisite)
        else:
            prerequisite_branch = None
        proposal_builder = hoster.get_proposer(remote_branch, target)
        if description is None:
            body = proposal_builder.get_initial_body()
            info = proposal_builder.get_infotext()
            info += "\n\n" + summarize_unmerged(
                branch, remote_branch, target, prerequisite_branch)
            description = msgeditor.edit_commit_message(
                info, start_message=body)
        try:
            proposal = proposal_builder.create_proposal(
                description=description, reviewers=reviewers,
                prerequisite_branch=prerequisite_branch, labels=labels)
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
            raise errors.BzrCommandError(
                gettext("No target location specified or remembered"))
        else:
            target = _mod_branch.Branch.open(submit_branch)
        hoster = _mod_propose.get_hoster(branch)
        for mp in hoster.iter_proposals(branch, target):
            self.outf.write(gettext('Merge proposal: %s\n') % mp.url)


class cmd_github_login(Command):
    __doc__ = """Log into GitHub.

    When communicating with GitHub, some commands need to authenticate to
    GitHub.
    """

    takes_args = ['username?']

    def run(self, username=None):
        from github import Github, GithubException
        from breezy.config import AuthenticationConfig
        authconfig = AuthenticationConfig()
        if username is None:
            username = authconfig.get_user(
                'https', 'github.com', prompt=u'GitHub username', ask=True)
        password = authconfig.get_password('https', 'github.com', username)
        client = Github(username, password)
        user = client.get_user()
        try:
            authorization = user.create_authorization(
                scopes=['user', 'repo', 'delete_repo'], note='Breezy',
                note_url='https://github.com/breezy-team/breezy')
        except GithubException as e:
            errs = e.data.get('errors', [])
            if errs:
                err_code = errs[0].get('code')
                if err_code == u'already_exists':
                    raise errors.BzrCommandError('token already exists')
            raise errors.BzrCommandError(e.data['message'])
        # TODO(jelmer): This should really use something in
        # AuthenticationConfig
        from .github import store_github_token
        store_github_token(scheme='https', host='github.com',
                           token=authorization.token)


class cmd_gitlab_login(Command):
    __doc__ = """Log into a GitLab instance.

    This command takes a GitLab instance URL (e.g. https://gitlab.com)
    as well as an optional private token. Private tokens can be created via the
    web UI.

    :Examples:

      Log into GNOME's GitLab (prompts for a token):

         brz gitlab-login https://gitlab.gnome.org/

      Log into Debian's salsa, using a token created earlier:

         brz gitlab-login https://salsa.debian.org if4Theis6Eich7aef0zo
    """

    takes_args = ['url', 'private_token?']

    takes_options = [
        Option('name', help='Name for GitLab site in configuration.',
               type=str),
        Option('no-check',
               "Don't check that the token is valid."),
        ]

    def run(self, url, private_token=None, name=None, no_check=False):
        from breezy import ui
        from .gitlabs import store_gitlab_token
        if name is None:
            try:
                name = urlutils.parse_url(url)[3].split('.')[-2]
            except (ValueError, IndexError):
                raise errors.BzrCommandError(
                    'please specify a site name with --name')
        if private_token is None:
            note("Please visit %s to obtain a private token.",
                 urlutils.join(url, "profile/personal_access_tokens"))
            private_token = ui.ui_factory.get_password(u'Private token')
        if not no_check:
            from gitlab import Gitlab
            gl = Gitlab(url=url, private_token=private_token)
            gl.auth()
        store_gitlab_token(name=name, url=url, private_token=private_token)


class cmd_my_merge_proposals(Command):
    __doc__ = """List all merge proposals owned by the logged-in user.

    """

    hidden = True

    takes_options = [
        RegistryOption.from_kwargs(
            'status',
            title='Proposal Status',
            help='Only include proposals with specified status.',
            value_switches=True,
            enum_switch=True,
            all='All merge proposals',
            open='Open merge proposals',
            merged='Merged merge proposals',
            closed='Closed merge proposals')]

    def run(self, status='open'):
        from .propose import hosters
        for name, hoster_cls in hosters.items():
            for instance in hoster_cls.iter_instances():
                for mp in instance.iter_my_proposals(status=status):
                    self.outf.write('%s\n' % mp.url)
