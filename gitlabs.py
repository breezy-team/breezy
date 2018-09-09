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

from ... import (
    controldir,
    errors,
    urlutils,
    )
from ...config import AuthenticationConfig
from ...git.urls import git_url_to_bzr_url

from .propose import (
    Hoster,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    UnsupportedHoster,
    )


class DifferentGitLabInstances(errors.BzrError):

    _fmt = ("Can't create merge proposals across GitLab instances: "
            "%(source_host)s and %(target_host)s")

    def __init__(self, source_host, target_host):
        self.source_host = source_host
        self.target_host = target_host


def connect_gitlab(url):
    from gitlab import Gitlab
    # TODO(jelmer): Support authentication
    auth = AuthenticationConfig()

    credentials = auth.get_credentials('https', url)
    if credentials is None:
        credentials = {}
    return Gitlab('https://%s' % url, **credentials)
    # return Gitlab.from_config('gitlab')


def parse_gitlab_url(branch):
    url = urlutils.split_segment_parameters(branch.user_url)[0]
    (scheme, user, password, host, port, path) = urlutils.parse_url(
        url)
    return host, path.strip('/'), branch.name


class GitLab(Hoster):
    """GitLab hoster implementation."""

    def __init__(self, gl):
        self.gl = gl

    def publish(self, local_branch, base_branch, name, project=None,
                owner=None, revision_id=None, overwrite=False):
        import gitlab
        (host, base_project, base_branch_name) = parse_gitlab_url(base_branch)
        gl.auth()
        # TODO(jelmer): This is a hack; we should just support catching redirections for git access.
        # https://bugs.launchpad.net/brz/+bug/1791535
        base_project = base_project.rstrip('.git')
        base_project = gl.projects.get(base_project)
        if owner is None:
            owner = gl.user.username
        if project is None:
            project = base_project.name
        try:
            target_project = gl.projects.get('%s/%s' % (owner, project))
        except gitlab.GitlabGetError:
            target_project = base_project.forks.create()
        remote_repo_url = git_url_to_bzr_url(target_project.attributes['ssh_url_to_repo'])
        remote_dir = controldir.ControlDir.open(remote_repo_url)
        push_result = remote_dir.push_branch(local_branch, revision_id=revision_id,
            overwrite=overwrite, name=name)
        public_url = urlutils.join_segment_parameters(
                target_project.attributes['http_url_to_repo'],
                {"branch": name})
        return push_result.target_branch, public_url

    def get_proposer(self, source_branch, target_branch):
        return GitlabMergeProposalBuilder(self.gl, source_branch, target_branch)

    @classmethod
    def probe(cls, branch):
        try:
            (host, project, branch_name) = parse_gitlab_url(branch)
        except ValueError:
            raise UnsupportedHoster(branch)
        import gitlab
        try:
            gl = connect_gitlab(host)
        except gitlab.GitlabGetError:
            raise UnsupportedHoster(branch)
        return cls(gl)


class GitlabMergeProposalBuilder(MergeProposalBuilder):

    def __init__(self, gl, source_branch, target_branch):
        self.gl = gl
        self.source_branch = source_branch
        (self.source_host, self.source_project_name, self.source_branch_name) = (
            parse_gitlab_url(source_branch))
        self.target_branch = target_branch
        (self.target_host, self.target_project_name, self.target_branch_name) = (
            parse_gitlab_url(target_branch))
        if self.source_host != self.target_host:
            raise DifferentGitLabInstances(self.source_host, self.target_host)

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        info = []
        info.append("Gitlab instance: %s\n" % self.target_host)
        info.append("Source: %s\n" % self.source_branch.user_url)
        info.append("Target: %s\n" % self.target_branch.user_url)
        return ''.join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        return None

    def create_proposal(self, description, reviewers=None):
        """Perform the submission."""
        # TODO(jelmer): Support reviewers
        gl.auth()
        source_project = gl.projects.get(self.source_project_name)
        target_project = gl.projects.get(self.target_project_name)
        # TODO(jelmer): Allow setting title explicitly
        title = description.splitlines()[0]
        # TODO(jelmer): Allow setting allow_collaboration field
        # TODO(jelmer): Allow setting milestone field
        # TODO(jelmer): Allow setting squash field
        merge_request = source_project.mergerequests.create({
            'title': title,
            'target_project_id': target_project.id,
            'source_branch': self.source_branch_name,
            'target_branch': self.target_branch_name,
            'description': description})
        return MergeProposal(merge_request.web_url)
