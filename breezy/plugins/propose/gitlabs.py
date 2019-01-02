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

"""Support for GitLab."""

from __future__ import absolute_import

from ... import (
    branch as _mod_branch,
    controldir,
    errors,
    urlutils,
    )
from ...config import AuthenticationConfig
from ...git.urls import git_url_to_bzr_url
from ...sixish import PY3

from .propose import (
    Hoster,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    NoMergeProposal,
    NoSuchProject,
    PrerequisiteBranchUnsupported,
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


def default_config_path():
    from breezy.config import config_dir
    import os
    return os.path.join(config_dir(), 'gitlab.conf')


def store_gitlab_token(name, url, private_token):
    """Store a GitLab token in a configuration file."""
    import configparser
    config = configparser.ConfigParser()
    path = default_config_path()
    config.read([path])
    config.add_section(name)
    config[name]['url'] = url
    config[name]['private_token'] = private_token
    with open(path, 'w') as f:
        config.write(f)


def connect_gitlab(host):
    from gitlab import Gitlab
    auth = AuthenticationConfig()

    url = 'https://%s' % host
    credentials = auth.get_credentials('https', host)
    if credentials is None:
        import gitlab
        import configparser
        from gitlab.config import _DEFAULT_FILES
        config = configparser.ConfigParser()
        config.read(_DEFAULT_FILES + [default_config_path()])
        for name, section in config.items():
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


class GitLabMergeProposal(MergeProposal):

    def __init__(self, mr):
        self._mr = mr

    @property
    def url(self):
        return self._mr.web_url

    def get_description(self):
        return self._mr.description

    def set_description(self, description):
        self._mr.description = description

    def is_merged(self):
        return (self._mr.attributes['state'] == 'merged')


def gitlab_url_to_bzr_url(url, name):
    if not PY3:
        name = name.encode('utf-8')
    return urlutils.join_segment_parameters(
        git_url_to_bzr_url(url), {"branch": name})


class GitLab(Hoster):
    """GitLab hoster implementation."""

    supports_merge_proposal_labels = True

    def __repr__(self):
        return "<GitLab(%r)>" % self.gl.url

    def __init__(self, gl):
        self.gl = gl

    def get_push_url(self, branch):
        (host, project_name, branch_name) = parse_gitlab_url(branch)
        project = self.gl.projects.get(project_name)
        return gitlab_url_to_bzr_url(
            project.attributes['ssh_url_to_repo'], branch_name)

    def publish_derived(self, local_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False,
                        allow_lossy=True):
        import gitlab
        (host, base_project, base_branch_name) = parse_gitlab_url(base_branch)
        self.gl.auth()
        try:
            base_project = self.gl.projects.get(base_project)
        except gitlab.GitlabGetError as e:
            if e.response_code == 404:
                raise NoSuchProject(base_project)
            else:
                raise
        if owner is None:
            owner = self.gl.user.username
        if project is None:
            project = base_project.path
        try:
            target_project = self.gl.projects.get('%s/%s' % (owner, project))
        except gitlab.GitlabGetError as e:
            if e.response_code == 404:
                target_project = base_project.forks.create({})
            else:
                raise
        remote_repo_url = git_url_to_bzr_url(target_project.attributes['ssh_url_to_repo'])
        remote_dir = controldir.ControlDir.open(remote_repo_url)
        try:
            push_result = remote_dir.push_branch(
                local_branch, revision_id=revision_id, overwrite=overwrite,
                name=name)
        except errors.NoRoundtrippingSupport:
            if not allow_lossy:
                raise
            push_result = remote_dir.push_branch(
                local_branch, revision_id=revision_id, overwrite=overwrite,
                name=name, lossy=True)
        public_url = gitlab_url_to_bzr_url(
            target_project.attributes['http_url_to_repo'], name)
        return push_result.target_branch, public_url

    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        import gitlab
        (host, base_project, base_branch_name) = parse_gitlab_url(base_branch)
        self.gl.auth()
        try:
            base_project = self.gl.projects.get(base_project)
        except gitlab.GitlabGetError as e:
            if e.response_code == 404:
                raise NoSuchProject(base_project)
            else:
                raise
        if owner is None:
            owner = self.gl.user.username
        if project is None:
            project = base_project.path
        try:
            target_project = self.gl.projects.get('%s/%s' % (owner, project))
        except gitlab.GitlabGetError as e:
            if e.response_code == 404:
                raise errors.NotBranchError('%s/%s/%s' % (self.gl.url, owner, project))
            raise
        return _mod_branch.Branch.open(gitlab_url_to_bzr_url(
            target_project.attributes['ssh_url_to_repo'], name))

    def get_proposer(self, source_branch, target_branch):
        return GitlabMergeProposalBuilder(self.gl, source_branch, target_branch)

    def get_proposal(self, source_branch, target_branch):
        (source_host, source_project_name, source_branch_name) = (
            parse_gitlab_url(source_branch))
        (target_host, target_project_name, target_branch_name) = (
            parse_gitlab_url(target_branch))
        if source_host != target_host:
            raise DifferentGitLabInstances(source_host, target_host)
        self.gl.auth()
        source_project = self.gl.projects.get(source_project_name)
        target_project = self.gl.projects.get(target_project_name)
        try:
            for mr in target_project.mergerequests.list(state='all'):
                attrs = mr.attributes
                if (attrs['source_project_id'] != source_project.id or
                        attrs['source_branch'] != source_branch_name or
                        attrs['target_project_id'] != target_project.id or
                        attrs['target_branch'] != target_branch_name):
                    continue
                return GitLabMergeProposal(mr)
        except gitlab.GitlabListError as e:
            if e.response_code == 403:
                raise PermissionDenied(e.error_message)
        raise NoMergeProposal()

    def hosts(self, branch):
        try:
            (host, project, branch_name) = parse_gitlab_url(branch)
        except NotGitLabUrl:
            return False
        return (self.gl.url == ('https://%s' % host))

    @classmethod
    def probe(cls, branch):
        try:
            (host, project, branch_name) = parse_gitlab_url(branch)
        except NotGitLabUrl:
            raise UnsupportedHoster(branch)
        import gitlab
        import requests.exceptions
        try:
            gl = connect_gitlab(host)
            gl.auth()
        except requests.exceptions.SSLError:
            # Well, I guess it could be..
            raise UnsupportedHoster(branch)
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

    def create_proposal(self, description, reviewers=None, labels=None,
                        prerequisite_branch=None):
        """Perform the submission."""
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
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
            if e.response_code == 403:
                raise PermissionDenied(e.error_message)
            if e.response_code == 409:
                raise MergeProposalExists(self.source_branch.user_url)
            raise
        return GitLabMergeProposal(merge_request)
