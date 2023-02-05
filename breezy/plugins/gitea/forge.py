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

"""Support for GitLab."""

from __future__ import absolute_import

from ...propose import (
    determine_title,
    Forge,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    NoSuchProject,
    PrerequisiteBranchUnsupported,
    SourceNotDerivedFromTarget,
    UnsupportedForge,
    )


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
        raise NotGitLabUrl(url)
    if not host:
        raise NotGitLabUrl(url)
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
            (host, project, branch_name) = parse_gitea_branch_url(branch)
        except NotGitLabUrl:
            return False
        return self.base_hostname == host

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        try:
            (host, project) = parse_gitea_url(url)
        except NotGitLabUrl:
            raise UnsupportedForge(url)
        transport = get_transport(
            'https://%s' % host, possible_transports=possible_transports)
        credentials = get_credentials_by_url(transport.base)
        if credentials is not None:
            return cls(transport, credentials.get('private_token'))
        raise UnsupportedForge(url)

    @classmethod
    def iter_instances(cls):
        for name, credentials in iter_tokens():
            if 'url' not in credentials:
                continue
            yield cls(
                get_transport(credentials['url']),
                private_token=credentials.get('private_token'))
