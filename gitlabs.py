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


class NotGitLabUrl(errors.BzrError):

    _fmt = "Not a GitLab URL: %(url)s"

    def __init__(self, url):
        errors.BzrError.__init__(self)
        self.url = url


class DifferentGitLabInstances(errors.BzrError):

    _fmt = ("Can't create merge proposals across GitLab instances: "
            "%(source_host)s and %(target_host)s")

    def __init__(self, source_host, target_host):
        self.source_host = source_host
        self.target_host = target_host


class GitLabLoginMissing(errors.BzrError):

    _fmt = ("Please log into GitLab")


def connect_gitlab(host):
    from gitlab import Gitlab
    auth = AuthenticationConfig()

    url = 'https://%s' % host
    credentials = auth.get_credentials('https', host)
    if credentials is None:
        import configparser
        import gitlab
        from gitlab.config import _DEFAULT_FILES
        config = configparser.ConfigParser()
        config.read(_DEFAULT_FILES)
        for name, section in config.iteritems():
            if section.get('url') == url:
                credentials = section
                break
        else:
            try:
                return Gitlab(url)
            except gitlab.GitlabGetError:
                raise GitLabLoginMissing()
    else:
        credentials['url'] = url
    return Gitlab(**credentials)


def parse_gitlab_url(branch):
    url = urlutils.split_segment_parameters(branch.user_url)[0]
    (scheme, user, password, host, port, path) = urlutils.parse_url(
        url)
    if scheme not in ('git+ssh', 'https', 'http'):
        raise NotGitLabUrl(branch.user_url)
    if not host:
        raise NotGitLabUrl(branch.user_url)
    path = path.strip('/')
    if path.endswith('.git'):
        path = path[:-4]
    return host, path, branch.name


class GitLab(Hoster):
    """GitLab hoster implementation."""

    supports_merge_proposal_labels = True

    def __init__(self, gl):
        self.gl = gl

    def publish_derived(self, local_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False):
        import gitlab
        (host, base_project, base_branch_name) = parse_gitlab_url(base_branch)
        self.gl.auth()
        base_project = self.gl.projects.get(base_project)
        if owner is None:
            owner = self.gl.user.username
        if project is None:
            project = base_project.name
        try:
            target_project = self.gl.projects.get('%s/%s' % (owner, project))
        except gitlab.GitlabGetError:
            target_project = base_project.forks.create({})
        remote_repo_url = git_url_to_bzr_url(target_project.attributes['ssh_url_to_repo'])
        remote_dir = controldir.ControlDir.open(remote_repo_url)
        push_result = remote_dir.push_branch(local_branch, revision_id=revision_id,
            overwrite=overwrite, name=name)
        public_url = urlutils.join_segment_parameters(
                target_project.attributes['http_url_to_repo'],
                {"branch": name.encode('utf-8')})
        return push_result.target_branch, public_url

    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        import gitlab
        (host, base_project, base_branch_name) = parse_gitlab_url(base_branch)
        self.gl.auth()
        base_project = self.gl.projects.get(base_project)
        if owner is None:
            owner = self.gl.user.username
        if project is None:
            project = base_project.name
        try:
            target_project = self.gl.projects.get('%s/%s' % (owner, project))
        except gitlab.GitlabGetError as e:
            if e.response_code == 404:
                raise errors.NotBranchError('%s/%s/%s' % (self.gl.url, owner, project))
            raise
        remote_repo_url = git_url_to_bzr_url(target_project.attributes['ssh_url_to_repo'])
        remote_dir = controldir.ControlDir.open(remote_repo_url)
        return remote_dir.open_branch(name=name)

    def get_proposer(self, source_branch, target_branch):
        return GitlabMergeProposalBuilder(self.gl, source_branch, target_branch)

    @classmethod
    def probe(cls, branch):
        try:
            (host, project, branch_name) = parse_gitlab_url(branch)
        except NotGitLabUrl:
            raise UnsupportedHoster(branch)
        import gitlab
        try:
            gl = connect_gitlab(host)
            gl.auth()
        except gitlab.GitlabGetError:
            raise UnsupportedHoster(branch)
        except gitlab.GitlabHttpError as e:
            if e.response_code in (404, 405, 503):
                raise UnsupportedHoster(branch)
            else:
                raise
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

    def create_proposal(self, description, reviewers=None, labels=None):
        """Perform the submission."""
        import gitlab
        # TODO(jelmer): Support reviewers
        self.gl.auth()
        source_project = self.gl.projects.get(self.source_project_name)
        target_project = self.gl.projects.get(self.target_project_name)
        # TODO(jelmer): Allow setting title explicitly
        title = description.splitlines()[0]
        # TODO(jelmer): Allow setting allow_collaboration field
        # TODO(jelmer): Allow setting milestone field
        # TODO(jelmer): Allow setting squash field
        kwargs = {
            'title': title,
            'target_project_id': target_project.id,
            'source_branch': self.source_branch_name,
            'target_branch': self.target_branch_name,
            'description': description}
        if labels:
            kwargs['labels'] = ','.join(labels)
        try:
            merge_request = source_project.mergerequests.create(kwargs)
        except gitlab.GitlabCreateError as e:
            if e.response_code == 409:
                raise MergeProposalExists(self.source_branch.user_url)
            raise
        return MergeProposal(merge_request.web_url)
