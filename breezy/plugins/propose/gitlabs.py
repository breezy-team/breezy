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

import os

from ... import (
    branch as _mod_branch,
    controldir,
    errors,
    urlutils,
    )
from ...git.urls import git_url_to_bzr_url
from ...sixish import PY3
from ...transport import get_transport

from .propose import (
    Hoster,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    NoSuchProject,
    PrerequisiteBranchUnsupported,
    UnsupportedHoster,
    )


_DEFAULT_FILES = ['/etc/python-gitlab.cfg', '~/.python-gitlab.cfg']


def mp_status_to_status(status):
    return {
        'all': 'all',
        'open': 'opened',
        'merged': 'merged',
        'closed': 'closed'}[status]


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


class GitlabLoginError(errors.BzrError):

    _fmt = ("Error logging in: %(error)s")

    def __init__(self, error):
        self.error = error


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


def iter_tokens():
    import configparser
    config = configparser.ConfigParser()
    config.read(
        [os.path.expanduser(p) for p in _DEFAULT_FILES] +
        [default_config_path()])
    for name, section in config.items():
        yield name, section


def parse_gitlab_url(url):
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


def parse_gitlab_branch_url(branch):
    url = urlutils.split_segment_parameters(branch.user_url)[0]
    host, path = parse_gitlab_url(url)
    return host, path, branch.name


class GitLabMergeProposal(MergeProposal):

    def __init__(self, gl, mr):
        self.gl = gl
        self._mr = mr

    @property
    def url(self):
        return self._mr['web_url']

    def get_description(self):
        return self._mr['description']

    def set_description(self, description):
        self._mr['description'] = description
        self.gl._update_merge_requests(self._mr)

    def _branch_url_from_project(self, project_id, branch_name):
        project = self.gl._get_project(project_id)
        return gitlab_url_to_bzr_url(project.http_url_to_repo, branch_name)

    def get_source_branch_url(self):
        return self._branch_url_from_project(
            self._mr['source_project_id'], self._mr['source_branch'])

    def get_target_branch_url(self):
        return self._branch_url_from_project(
            self._mr['target_project_id'], self._mr['target_branch'])

    def is_merged(self):
        return (self._mr['state'] == 'merged')

    def close(self):
        self._mr['state_event'] = 'close'
        self.gl._update_merge_requests(self._mr)


def gitlab_url_to_bzr_url(url, name):
    if not PY3:
        name = name.encode('utf-8')
    return urlutils.join_segment_parameters(
        git_url_to_bzr_url(url), {"branch": name})


class GitLab(Hoster):
    """GitLab hoster implementation."""

    supports_merge_proposal_labels = True

    def __repr__(self):
        return "<GitLab(%r)>" % self.base_url

    @property
    def base_url(self):
        return self.transport.base

    def _api_request(self, method, path):
        return self.transport.request(
            method, urlutils.join(self.base_url, 'api', 'v4', path),
            headers=self.headers)

    def __init__(self, transport, private_token):
        self.transport = transport
        self.headers = {"Private-Token": private_token}
        self.check()

    def _get_project(self, project_name):
        path = 'projects/:%s' % urlutils.quote(project_name, '')
        response = self._api_request('GET', path)
        if response.status == 404:
            raise NoSuchProject(project_name)
        if response.status == 200:
            return response.json
        raise InvalidHttpResponse(path, response.text)

    def _fork_project(self, project_name):
        path = 'projects/:%s/fork' % urlutils.quote(project_name, '')
        response = self._api_request('POST', path)
        if response != 200:
            raise InvalidHttpResponse(path, response.text)
        return response.json

    def _get_logged_in_username(self):
        return self._current_user['username']

    def _list_mergerequests(self, owner=None, project=None, state=None):
        if project is not None:
            path = 'projects/:%s/merge_requests' % urlutils.quote(project_name, '')
        else:
            path = 'merge_requests'
        parameters = {}
        if state:
            parameters['state'] = state
        if owner:
            parameters['owner_id'] = urlutils.quote(owner, '')
        response = self._api_request(
            'GET', path + '?' +
            ';'.join(['%s=%s' % item for item in parameters.items()]))
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        if response.status == 200:
            return response.json
        raise InvalidHttpResponse(path, response.text)

    def _create_mergerequest(
            self, title, source_project_id, target_project_id,
            source_branch_name, target_branch_name, description):
        path = 'projects/:%s/merge_requests' % source_project_id
        response = self._api_request(
            'POST', path, fields={
                'title': title,
                'source_branch': source_branch_name,
                'target_branch': target_branch_name,
                'target_project_id': target_project_id,
                'description': description})
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        if response.status == 409:
            raise MergeProposalExists(self.source_branch.user_url)
        if response.status == 200:
            raise InvalidHttpResponse(path, response.text)
        return response.json

    def get_push_url(self, branch):
        (host, project_name, branch_name) = parse_gitlab_branch_url(branch)
        project = self._get_project(project_name)
        return gitlab_url_to_bzr_url(
            project.ssh_url_to_repo, branch_name)

    def publish_derived(self, local_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False,
                        allow_lossy=True):
        import gitlab
        (host, base_project, base_branch_name) = parse_gitlab_branch_url(base_branch)
        base_project = self._get_project(base_project)
        if owner is None:
            owner = self._get_logged_in_username()
        if project is None:
            project = base_project.path
        try:
            target_project = self._get_project('%s/%s' % (owner, project))
        except NoSuchProject:
            target_project = self._fork_project(base_project)
            # TODO(jelmer): Spin and wait until import_status for new project
            # is complete.
        remote_repo_url = git_url_to_bzr_url(target_project.ssh_url_to_repo)
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
            target_project.http_url_to_repo, name)
        return push_result.target_branch, public_url

    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        (host, base_project, base_branch_name) = parse_gitlab_branch_url(base_branch)
        base_project = self._get_project(base_project)
        if owner is None:
            owner = self.gl.user.username
        if project is None:
            project = base_project.path
        try:
            target_project = self._get_project('%s/%s' % (owner, project))
        except NoSuchProject:
            raise errors.NotBranchError('%s/%s/%s' % (self.base_url, owner, project))
        return _mod_branch.Branch.open(gitlab_url_to_bzr_url(
            target_project.ssh_url_to_repo, name))

    def get_proposer(self, source_branch, target_branch):
        return GitlabMergeProposalBuilder(self, source_branch, target_branch)

    def iter_proposals(self, source_branch, target_branch, status):
        (source_host, source_project_name, source_branch_name) = (
            parse_gitlab_branch_url(source_branch))
        (target_host, target_project_name, target_branch_name) = (
            parse_gitlab_branch_url(target_branch))
        if source_host != target_host:
            raise DifferentGitLabInstances(source_host, target_host)
        source_project = self._get_project(source_project_name)
        target_project = self._get_project(target_project_name)
        state = mp_status_to_status(status)
        for mr in self.gl._list_mergerequests(project=target_project, state=state):
            if (mr.source_project_id != source_project.id or
                    mr.source_branch != source_branch_name or
                    mr.target_project_id != target_project.id or
                    mr.target_branch != target_branch_name):
                continue
            yield GitLabMergeProposal(self, mr)

    def hosts(self, branch):
        try:
            (host, project, branch_name) = parse_gitlab_branch_url(branch)
        except NotGitLabUrl:
            return False
        return (self.base_url == ('https://%s' % host))

    def check(self):
        response = self._api_request('GET', 'user')
        if response.status == 200:
            self._current_user = response.json
            return
        if response == 401:
            if response.json == {"message": "401 Unauthorized"}:
                raise GitLabLoginMissing()
            else:
                raise GitlabLoginError(response.text)
        raise UnsupportedHoster(url)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        try:
            (host, project) = parse_gitlab_url(url)
        except NotGitLabUrl:
            raise UnsupportedHoster(url)
        transport = get_transport(
            'https://%s' % host, possible_transports=possible_transports)
        return cls(transport)

    @classmethod
    def iter_instances(cls):
        for name, credentials in iter_tokens():
            if 'url' not in credentials:
                continue
            yield cls(
                get_transport(credentials['url']),
                private_token=credentials.get('private_token'))

    def iter_my_proposals(self, status='open'):
        state = mp_status_to_status(status)
        for mp in self._list_mergerequests(
                owner=self._get_logged_in_username(), state=state):
            yield GitLabMergeProposal(self, mp)


class GitlabMergeProposalBuilder(MergeProposalBuilder):

    def __init__(self, l, source_branch, target_branch):
        self.gl = gl
        self.source_branch = source_branch
        (self.source_host, self.source_project_name, self.source_branch_name) = (
            parse_gitlab_branch_url(source_branch))
        self.target_branch = target_branch
        (self.target_host, self.target_project_name, self.target_branch_name) = (
            parse_gitlab_branch_url(target_branch))
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
        # TODO(jelmer): Support reviewers
        source_project = self.gl._get_project(self.source_project_name)
        target_project = self.gl._get_project(self.target_project_name)
        # TODO(jelmer): Allow setting title explicitly
        title = description.splitlines()[0]
        # TODO(jelmer): Allow setting allow_collaboration field
        # TODO(jelmer): Allow setting milestone field
        # TODO(jelmer): Allow setting squash field
        kwargs = {
            'title': title,
            'source_project_id': source_project.id,
            'target_project_id': target_project.id,
            'source_branch': self.source_branch_name,
            'target_branch': self.target_branch_name,
            'description': description}
        if labels:
            kwargs['labels'] = ','.join(labels)
        merge_request = self.gl._create_mergerequest(**kwargs)
        return GitLabMergeProposal(self.gl, merge_request)


def register_gitlab_instance(shortname, url):
    """Register a gitlab instance.

    :param shortname: Short name (e.g. "gitlab")
    :param url: URL to the gitlab instance
    """
    from breezy.bugtracker import (
        tracker_registry,
        ProjectIntegerBugTracker,
        )
    tracker_registry.register(
        shortname, ProjectIntegerBugTracker(
            shortname, url + '/{project}/issues/{id}'))
