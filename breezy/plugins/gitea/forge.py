# Copyright (C) 2021 Breezy Developers
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

"""Support for Gitea."""

from typing import Optional

from ... import errors, urlutils

from ...forge import (
    determine_title,
    Forge,
    UnsupportedForge,
    PrerequisiteBranchUnsupported,
    MergeProposal,
    MergeProposalBuilder,
    )

from breezy.transport import get_transport


class NotGiteaUrl(errors.BzrError):

    _fmt = "Not a Gitea URL: %(url)s"

    def __init__(self, url):
        errors.BzrError.__init__(self)
        self.url = url


class DifferentGiteaInstances(errors.BzrError):

    _fmt = ("Can't create merge proposals across Gitea instances: "
            "%(source_host)s and %(target_host)s")

    def __init__(self, source_host, target_host):
        self.source_host = source_host
        self.target_host = target_host


def store_gitea_token(name, url, private_token):
    """Store a gitea token in a configuration file."""
    from breezy.config import AuthenticationConfig
    auth_config = AuthenticationConfig()
    auth_config._set_option(name, 'url', url)
    auth_config._set_option(name, 'private_token', private_token)


def iter_tokens():
    from breezy.config import AuthenticationConfig
    auth_config = AuthenticationConfig()
    yield from auth_config._get_config().iteritems()


def get_credentials_by_url(url):
    for name, credentials in iter_tokens():
        if 'url' not in credentials:
            continue
        if credentials['url'].rstrip('/') == url.rstrip('/'):
            return credentials
    else:
        return None


def parse_gitea_url(url):
    (scheme, user, password, host, port, path) = urlutils.parse_url(
        url)
    if scheme not in ('git+ssh', 'https', 'http'):
        raise NotGiteaUrl(url)
    if not host:
        raise NotGiteaUrl(url)
    path = path.strip('/')
    if path.endswith('.git'):
        path = path[:-4]
    return host, path


def parse_gitea_branch_url(branch):
    url = urlutils.strip_segment_parameters(branch.user_url)
    host, path = parse_gitea_url(url)
    return host, path, branch.name


class Gitea(Forge):
    """Gitea hoster implementation."""

    supports_merge_proposal_title = True
    supports_merge_proposal_labels = False
    supports_merge_proposal_commit_message = False
    supports_allow_collaboration = False
    merge_proposal_description_format = 'markdown'

    def __init__(self, transport, private_token):
        self.transport = transport
        self.headers = {"Private-Token": private_token}
        self._current_user = None

    def __repr__(self):
        return "<Gitea(%r)>" % self.base_url

    @property
    def base_url(self):
        return self.transport.base

    @property
    def base_hostname(self):
        return urlutils.parse_url(self.base_url)[3]

    def hosts(self, branch):
        try:
            (host, _project, _branch_name) = parse_gitea_branch_url(branch)
        except NotGiteaUrl:
            return False
        return self.base_hostname == host

    def iter_my_proposals(self, status='open', author=None):
        # TODO(jelmer): It's not clear to me how to list all 
        raise NotImplementedError(self.iter_my_proposals)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        try:
            (host, _project) = parse_gitea_url(url)
        except NotGiteaUrl as e:
            raise UnsupportedForge(url) from e
        transport = get_transport(
            f'https://{host}', possible_transports=possible_transports)
        credentials = get_credentials_by_url(transport.base)
        if credentials is not None:
            return cls(transport, credentials.get('private_token'))
        raise UnsupportedForge(url)

    @classmethod
    def iter_instances(cls):
        for _name, credentials in iter_tokens():
            if 'url' not in credentials:
                continue
            yield cls(
                get_transport(credentials['url']),
                private_token=credentials.get('private_token'))


class GiteaMergeProposal(MergeProposal):

    supports_auto_merge = True

    def __init__(self, gitea, pr):
        self._gitea = gitea
        self._pr = pr

    def __repr__(self):
        return "<{} at {!r}>".format(type(self).__name__, self.url)

    def get_web_url(self):
        return self._pr['html_url']

    @property
    def url(self):
        return self._pr['html_url']

    def is_merged(self):
        return bool(self._pr.get('merged_at'))

    def is_closed(self):
        return self._pr['state'] == 'closed' and not bool(self._pr.get('merged_at'))


class GiteaMergeProposalBuilder(MergeProposalBuilder):

    def __init__(self, gitea, source_branch, target_branch):
        self.gitea = gitea
        self.source_branch = source_branch
        (self.source_host, self.source_project_name, self.source_branch_name) = (
            parse_gitea_branch_url(source_branch))
        self.target_branch = target_branch
        (self.target_host, self.target_project_name, self.target_branch_name) = (
            parse_gitea_branch_url(target_branch))
        if self.source_host != self.target_host:
            raise DifferentGiteaInstances(self.source_host, self.target_host)

    def create_proposal(self, description, title=None, reviewers=None,
                        labels=None, prerequisite_branch=None,
                        commit_message=None, work_in_progress=False,
                        allow_collaboration=False,
                        delete_source_after_merge: Optional[bool] = None):
        """Perform the submission."""
        # https://docs.gitlab.com/ee/api/merge_requests.html#create-mr
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        # Note that commit_message is ignored, since Gitlab doesn't support it.
        source_project = self.gitea._get_project(self.source_project_name)
        target_project = self.gitea._get_project(self.target_project_name)
        if title is None:
            title = determine_title(description)
        if work_in_progress:
            title = 'WIP: %s' % title
        # TODO(jelmer): Allow setting milestone field
        # TODO(jelmer): Allow setting squash field
        kwargs = {
            'title': title,
            'head': head,
            'base': base,
            'body': description,
        }
        if labels:
            # TODO(jelmer): Labels are apparently integers
            raise NotImplementedError
        if reviewers:
            kwargs['assignees'] = reviewers
        # TODO(jelmer): add milestone
        # TODO(jelmer): add due_date
        merge_request = self.gitea._create_pullrequest(
            title=title,
            assignees=reviewers,
            head="{}:{}".format(self.source_owner, self.source_branch_name),
            base=self.target_branch_name)

        return GiteaMergeProposal(self.gitea, merge_request)
