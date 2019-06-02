# Copyright (C) 2018 Breezy Developers
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

"""Support for GitHub."""

from __future__ import absolute_import

import os

from .propose import (
    Hoster,
    HosterLoginRequired,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    PrerequisiteBranchUnsupported,
    UnsupportedHoster,
    )

from ... import (
    branch as _mod_branch,
    controldir,
    errors,
    hooks,
    urlutils,
    version_string as breezy_version,
    )
from ...config import AuthenticationConfig, GlobalStack, config_dir
from ...git.urls import git_url_to_bzr_url
from ...i18n import gettext
from ...sixish import PY3
from ...trace import note
from ...lazy_import import lazy_import
lazy_import(globals(), """
from github import Github
""")


def store_github_token(scheme, host, token):
    with open(os.path.join(config_dir(), 'github.conf'), 'w') as f:
        f.write(token)


def retrieve_github_token(scheme, host):
    path = os.path.join(config_dir(), 'github.conf')
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return f.read().strip()


def determine_title(description):
    return description.splitlines()[0]


class NotGitHubUrl(errors.BzrError):

    _fmt = "Not a GitHub URL: %(url)s"

    def __init__(self, url):
        errors.BzrError.__init__(self)
        self.url = url


class GitHubLoginRequired(HosterLoginRequired):

    _fmt = "Action requires GitHub login."


def connect_github():
    """Connect to GitHub.
    """
    user_agent = "Breezy/%s" % breezy_version

    auth = AuthenticationConfig()

    credentials = auth.get_credentials('https', 'github.com')
    if credentials is not None:
        return Github(credentials['user'], credentials['password'],
                      user_agent=user_agent)

    # TODO(jelmer): token = auth.get_token('https', 'github.com')
    token = retrieve_github_token('https', 'github.com')
    if token is not None:
        return Github(token, user_agent=user_agent)
    else:
        note('Accessing GitHub anonymously. To log in, run \'brz gh-login\'.')
        return Github(user_agent=user_agent)


class GitHubMergeProposal(MergeProposal):

    def __init__(self, pr):
        self._pr = pr

    @property
    def url(self):
        return self._pr.html_url

    def _branch_from_part(self, part):
        return github_url_to_bzr_url(part.repo.html_url, part.ref)

    def get_source_branch_url(self):
        return self._branch_from_part(self._pr.head)

    def get_target_branch_url(self):
        return self._branch_from_part(self._pr.base)

    def get_description(self):
        return self._pr.body

    def set_description(self, description):
        self._pr.edit(body=description, title=determine_title(description))

    def is_merged(self):
        return self._pr.merged

    def close(self):
        self._pr.edit(state='closed')


def parse_github_url(url):
    (scheme, user, password, host, port, path) = urlutils.parse_url(
        url)
    if host != 'github.com':
        raise NotGitHubUrl(url)
    (owner, repo_name) = path.strip('/').split('/')
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    return owner, repo_name


def parse_github_branch_url(branch):
    url = urlutils.split_segment_parameters(branch.user_url)[0]
    owner, repo_name = parse_github_url(url)
    return owner, repo_name, branch.name


def github_url_to_bzr_url(url, branch_name):
    if not PY3:
        branch_name = branch_name.encode('utf-8')
    return urlutils.join_segment_parameters(
        git_url_to_bzr_url(url), {"branch": branch_name})


def convert_github_error(fn):
    def convert(self, *args, **kwargs):
        import github
        try:
            return fn(self, *args, **kwargs)
        except github.GithubException as e:
            if e.args[0] == 401:
                raise GitHubLoginRequired(self)
            raise
    return convert


class GitHub(Hoster):

    name = 'github'

    supports_merge_proposal_labels = True

    def __repr__(self):
        return "GitHub()"

    @property
    def base_url(self):
        # TODO(jelmer): Can we get the default URL from the Python API package
        # somehow?
        return "https://github.com"

    def __init__(self):
        self.gh = connect_github()

    @convert_github_error
    def publish_derived(self, local_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False,
                        allow_lossy=True):
        import github
        base_owner, base_project, base_branch_name = parse_github_branch_url(base_branch)
        base_repo = self.gh.get_repo('%s/%s' % (base_owner, base_project))
        if owner is None:
            owner = self.gh.get_user().login
        if project is None:
            project = base_repo.name
        try:
            remote_repo = self.gh.get_repo('%s/%s' % (owner, project))
            remote_repo.id
        except github.UnknownObjectException:
            base_repo = self.gh.get_repo('%s/%s' % (base_owner, base_project))
            if owner == self.gh.get_user().login:
                owner_obj = self.gh.get_user()
            else:
                owner_obj = self.gh.get_organization(owner)
            remote_repo = owner_obj.create_fork(base_repo)
            note(gettext('Forking new repository %s from %s') %
                 (remote_repo.html_url, base_repo.html_url))
        else:
            note(gettext('Reusing existing repository %s') % remote_repo.html_url)
        remote_dir = controldir.ControlDir.open(git_url_to_bzr_url(remote_repo.ssh_url))
        try:
            push_result = remote_dir.push_branch(
                local_branch, revision_id=revision_id, overwrite=overwrite,
                name=name)
        except errors.NoRoundtrippingSupport:
            if not allow_lossy:
                raise
            push_result = remote_dir.push_branch(
                local_branch, revision_id=revision_id,
                overwrite=overwrite, name=name, lossy=True)
        return push_result.target_branch, github_url_to_bzr_url(
            remote_repo.html_url, name)

    @convert_github_error
    def get_push_url(self, branch):
        owner, project, branch_name = parse_github_branch_url(branch)
        repo = self.gh.get_repo('%s/%s' % (owner, project))
        return github_url_to_bzr_url(repo.ssh_url, branch_name)

    @convert_github_error
    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        import github
        base_owner, base_project, base_branch_name = parse_github_branch_url(base_branch)
        base_repo = self.gh.get_repo('%s/%s' % (base_owner, base_project))
        if owner is None:
            owner = self.gh.get_user().login
        if project is None:
            project = base_repo.name
        try:
            remote_repo = self.gh.get_repo('%s/%s' % (owner, project))
            full_url = github_url_to_bzr_url(remote_repo.ssh_url, name)
            return _mod_branch.Branch.open(full_url)
        except github.UnknownObjectException:
            raise errors.NotBranchError('https://github.com/%s/%s' % (owner, project))

    @convert_github_error
    def get_proposer(self, source_branch, target_branch):
        return GitHubMergeProposalBuilder(self.gh, source_branch, target_branch)

    @convert_github_error
    def iter_proposals(self, source_branch, target_branch, status='open'):
        (source_owner, source_repo_name, source_branch_name) = (
            parse_github_branch_url(source_branch))
        (target_owner, target_repo_name, target_branch_name) = (
            parse_github_branch_url(target_branch))
        target_repo = self.gh.get_repo(
            "%s/%s" % (target_owner, target_repo_name))
        state = {
            'open': 'open',
            'merged': 'closed',
            'closed': 'closed',
            'all': 'all'}
        for pull in target_repo.get_pulls(
                head=target_branch_name,
                state=state[status]):
            if (status == 'closed' and pull.merged or
                    status == 'merged' and not pull.merged):
                continue
            if pull.head.ref != source_branch_name:
                continue
            if pull.head.repo is None:
                # Repo has gone the way of the dodo
                continue
            if (pull.head.repo.owner.login != source_owner or
                    pull.head.repo.name != source_repo_name):
                continue
            yield GitHubMergeProposal(pull)

    def hosts(self, branch):
        try:
            parse_github_branch_url(branch)
        except NotGitHubUrl:
            return False
        else:
            return True

    @classmethod
    def probe_from_url(cls, url):
        try:
            parse_github_url(url)
        except NotGitHubUrl:
            raise UnsupportedHoster(url)
        return cls()

    @classmethod
    def iter_instances(cls):
        yield cls()

    @convert_github_error
    def iter_my_proposals(self, status='open'):
        query = ['is:pr']
        if status == 'open':
            query.append('is:open')
        elif status == 'closed':
            query.append('is:unmerged')
            # Also use "is:closed" otherwise unmerged open pull requests are
            # also included.
            query.append('is:closed')
        elif status == 'merged':
            query.append('is:merged')
        query.append('author:%s' % self.gh.get_user().login)
        for issue in self.gh.search_issues(query=' '.join(query)):
            yield GitHubMergeProposal(issue.as_pull_request())


class GitHubMergeProposalBuilder(MergeProposalBuilder):

    def __init__(self, gh, source_branch, target_branch):
        self.gh = gh
        self.source_branch = source_branch
        self.target_branch = target_branch
        (self.target_owner, self.target_repo_name, self.target_branch_name) = (
            parse_github_branch_url(self.target_branch))
        (self.source_owner, self.source_repo_name, self.source_branch_name) = (
            parse_github_branch_url(self.source_branch))

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        info = []
        info.append("Merge %s into %s:%s\n" % (
            self.source_branch_name, self.target_owner,
            self.target_branch_name))
        info.append("Source: %s\n" % self.source_branch.user_url)
        info.append("Target: %s\n" % self.target_branch.user_url)
        return ''.join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        return None

    def create_proposal(self, description, reviewers=None, labels=None,
                        prerequisite_branch=None):
        """Perform the submission."""
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        import github
        # TODO(jelmer): Probe for right repo name
        if self.target_repo_name.endswith('.git'):
            self.target_repo_name = self.target_repo_name[:-4]
        target_repo = self.gh.get_repo("%s/%s" % (self.target_owner, self.target_repo_name))
        # TODO(jelmer): Allow setting title explicitly?
        title = determine_title(description)
        # TOOD(jelmer): Set maintainers_can_modify?
        try:
            pull_request = target_repo.create_pull(
                title=title, body=description,
                head="%s:%s" % (self.source_owner, self.source_branch_name),
                base=self.target_branch_name)
        except github.GithubException as e:
            if e.status == 422:
                raise MergeProposalExists(self.source_branch.user_url)
            raise
        if reviewers:
            for reviewer in reviewers:
                pull_request.assignees.append(
                    self.gh.get_user(reviewer))
        if labels:
            for label in labels:
                pull_request.issue.labels.append(label)
        return GitHubMergeProposal(pull_request)
