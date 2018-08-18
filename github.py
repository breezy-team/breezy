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

from __future__ import absolute_import

from .propose import (
    MergeProposal,
    MergeProposer,
    MergeProposalExists,
    )

from ... import (
    version_string as breezy_version,
    errors,
    hooks,
    urlutils,
    )
from ...lazy_import import lazy_import
lazy_import(globals(), """
from github import Github
""")


class NotGitHubUrl(errors.BzrError):

    _fmt = "Not a GitHub URL: %(url)s"

    def __init__(self, url):
        errors.BzrError.__init__(self)
        self.url = url


def connect_github():
    user_agent = user_agent="Breezy/%s" % breezy_version
    # TODO(jelmer): using username and password
    # g = Github("user", "password", user_agent=user_agent)

    # TODO(jelmer): or using an access token
    #return Github("token", user_agent=user_agent)
    return Github(user_agent=user_agent)


def parse_github_url(branch):
    url = urlutils.split_segment_parameters(branch.user_url)[0]
    (scheme, user, password, host, port, path) = urlutils.parse_url(
        url)
    if host != 'github.com':
        raise NotGitHubUrl(url)
    (owner, repo_name) = path.strip('/').split('/')
    return owner, repo_name, branch.name


class GitHubMergeProposer(MergeProposer):

    def __init__(self, source_branch, target_branch):
        self.source_branch = source_branch
        self.target_branch = target_branch

    @classmethod
    def is_compatible(cls, target_branch, source_branch):
        try:
            parse_github_url(target_branch)
        except NotGitHubUrl:
            return False
        else:
            return True

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        info = ["Source: %s\n" % self.source_branch.user_url]
        info.append("Target: %s\n" % self.target_branch.user_url)
        return ''.join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        return None

    def create_proposal(self, description):
        """Perform the submission."""
        gh = connect_github()
        (target_owner, target_repo_name, target_branch_name) = parse_github_url(self.target_branch)
        (source_owner, source_repo_name, source_branch_name) = parse_github_url(self.source_branch)
        source_repo = gh.get_repo("%s/%s" % (source_owner, source_repo_name))
        # TODO(jelmer): Allow setting title explicitly?
        title = description.splitlines()[0]
        # TOOD(jelmer): Set maintainers_can_modify?
        pull_request= source_repo.create_pull(
            title=title, body=description,
            head=source_branch_name, base=target_branch_name)
        return MergeProposal(pull_request.html_url)
