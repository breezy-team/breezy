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

import json
import os
import time

from ... import (
    bedding,
    branch as _mod_branch,
    controldir,
    errors,
    urlutils,
    )
from ...git.urls import git_url_to_bzr_url
from ...sixish import PY3
from ...trace import mutter
from ...transport import get_transport

from ...propose import (
    determine_title,
    Hoster,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    NoSuchProject,
    PrerequisiteBranchUnsupported,
    UnsupportedHoster,
    )


_DEFAULT_FILES = ['/etc/python-gitlab.cfg', '~/.python-gitlab.cfg']
DEFAULT_PAGE_SIZE = 50


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


class NotMergeRequestUrl(errors.BzrError):

    _fmt = "Not a merge proposal URL: %(url)s"

    def __init__(self, host, url):
        errors.BzrError.__init__(self)
        self.host = host
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


class MergeRequestExists(Exception):
    """Raised when a merge requests already exists."""


def default_config_path():
    return os.path.join(bedding.config_dir(), 'gitlab.conf')


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


def get_credentials_by_url(url):
    for name, credentials in iter_tokens():
        if 'url' not in credentials:
            continue
        if credentials['url'].rstrip('/') == url.rstrip('/'):
            return credentials
    else:
        return None


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
    url = urlutils.strip_segment_parameters(branch.user_url)
    host, path = parse_gitlab_url(url)
    return host, path, branch.name


def parse_gitlab_merge_request_url(url):
    (scheme, user, password, host, port, path) = urlutils.parse_url(
        url)
    if scheme not in ('git+ssh', 'https', 'http'):
        raise NotGitLabUrl(url)
    if not host:
        raise NotGitLabUrl(url)
    path = path.strip('/')
    parts = path.split('/')
    if len(parts) < 2:
        raise NotMergeRequestUrl(host, url)
    if parts[-2] != 'merge_requests':
        raise NotMergeRequestUrl(host, url)
    if parts[-3] == '-':
        project_name = '/'.join(parts[:-3])
    else:
        project_name = '/'.join(parts[:-2])
    return host, project_name, int(parts[-1])


class GitLabMergeProposal(MergeProposal):

    def __init__(self, gl, mr):
        self.gl = gl
        self._mr = mr

    def _update(self, **kwargs):
        self.gl._update_merge_request(self._mr['project_id'], self._mr['iid'], kwargs)

    def __repr__(self):
        return "<%s at %r>" % (type(self).__name__, self._mr['web_url'])

    @property
    def url(self):
        return self._mr['web_url']

    def get_description(self):
        return self._mr['description']

    def set_description(self, description):
        self._update(description=description, title=determine_title(description))

    def get_commit_message(self):
        return self._mr.get('merge_commit_message')

    def set_commit_message(self, message):
        raise errors.UnsupportedOperation(self.set_commit_message, self)

    def _branch_url_from_project(self, project_id, branch_name):
        if project_id is None:
            return None
        project = self.gl._get_project(project_id)
        return gitlab_url_to_bzr_url(project['http_url_to_repo'], branch_name)

    def get_source_branch_url(self):
        return self._branch_url_from_project(
            self._mr['source_project_id'], self._mr['source_branch'])

    def get_target_branch_url(self):
        return self._branch_url_from_project(
            self._mr['target_project_id'], self._mr['target_branch'])

    def _get_project_name(self, project_id):
        source_project = self.gl._get_project(project_id)
        return source_project['path_with_namespace']

    def get_source_project(self):
        return self._get_project_name(self._mr['source_project_id'])

    def get_target_project(self):
        return self._get_project_name(self._mr['target_project_id'])

    def is_merged(self):
        return (self._mr['state'] == 'merged')

    def is_closed(self):
        return (self._mr['state'] == 'closed')

    def reopen(self):
        return self._update(state_event='reopen')

    def close(self):
        self._update(state_event='close')

    def merge(self, commit_message=None):
        # https://docs.gitlab.com/ee/api/merge_requests.html#accept-mr
        self._mr.merge(merge_commit_message=commit_message)

    def can_be_merged(self):
        if self._mr['merge_status'] == 'cannot_be_merged':
            return False
        elif self._mr['merge_status'] == 'can_be_merged':
            return True
        elif self._mr['merge_status'] in (
                'unchecked', 'cannot_be_merged_recheck'):
            # See https://gitlab.com/gitlab-org/gitlab/-/commit/7517105303c for
            # an explanation of the distinction between unchecked and
            # cannot_be_merged_recheck
            return None
        else:
            raise ValueError(self._mr['merge_status'])

    def get_merged_by(self):
        user = self._mr.get('merged_by')
        if user is None:
            return None
        return user['username']

    def get_merged_at(self):
        merged_at = self._mr.get('merged_at')
        if merged_at is None:
            return None
        import iso8601
        return iso8601.parse_date(merged_at)


def gitlab_url_to_bzr_url(url, name):
    if not PY3:
        name = name.encode('utf-8')
    return git_url_to_bzr_url(url, branch=name)


class GitLab(Hoster):
    """GitLab hoster implementation."""

    supports_merge_proposal_labels = True
    supports_merge_proposal_commit_message = False
    supports_allow_collaboration = True
    merge_proposal_description_format = 'markdown'

    def __repr__(self):
        return "<GitLab(%r)>" % self.base_url

    @property
    def base_url(self):
        return self.transport.base

    @property
    def base_hostname(self):
        return urlutils.parse_url(self.base_url)[3]

    def _api_request(self, method, path, fields=None, body=None):
        return self.transport.request(
            method, urlutils.join(self.base_url, 'api', 'v4', path),
            headers=self.headers, fields=fields, body=body)

    def __init__(self, transport, private_token):
        self.transport = transport
        self.headers = {"Private-Token": private_token}
        self.check()

    def _get_user(self, username):
        path = 'users/%s' % urlutils.quote(str(username), '')
        response = self._api_request('GET', path)
        if response.status == 404:
            raise KeyError('no such user %s' % username)
        if response.status == 200:
            return json.loads(response.data)
        raise errors.InvalidHttpResponse(path, response.text)

    def _get_user_by_email(self, email):
        path = 'users?search=%s' % urlutils.quote(str(email), '')
        response = self._api_request('GET', path)
        if response.status == 404:
            raise KeyError('no such user %s' % email)
        if response.status == 200:
            ret = json.loads(response.data)
            if len(ret) != 1:
                raise ValueError('unexpected number of results; %r' % ret)
            return ret[0]
        raise errors.InvalidHttpResponse(path, response.text)

    def _get_project(self, project_name):
        path = 'projects/%s' % urlutils.quote(str(project_name), '')
        response = self._api_request('GET', path)
        if response.status == 404:
            raise NoSuchProject(project_name)
        if response.status == 200:
            return json.loads(response.data)
        raise errors.InvalidHttpResponse(path, response.text)

    def _fork_project(self, project_name, timeout=50, interval=5):
        path = 'projects/%s/fork' % urlutils.quote(str(project_name), '')
        response = self._api_request('POST', path)
        if response.status not in (200, 201):
            raise errors.InvalidHttpResponse(path, response.text)
        # The response should be valid JSON, but let's ignore it
        project = json.loads(response.data)
        # Spin and wait until import_status for new project
        # is complete.
        deadline = time.time() + timeout
        while project['import_status'] not in ('finished', 'none'):
            mutter('import status is %s', project['import_status'])
            if time.time() > deadline:
                raise Exception('timeout waiting for project to become available')
            time.sleep(interval)
            project = self._get_project(project['path_with_namespace'])
        return project

    def _get_logged_in_username(self):
        return self._current_user['username']

    def _list_paged(self, path, parameters=None, per_page=None):
        if parameters is None:
            parameters = {}
        else:
            parameters = dict(parameters.items())
        if per_page:
            parameters['per_page'] = str(per_page)
        page = "1"
        while page:
            parameters['page'] = page
            response = self._api_request(
                'GET', path + '?' +
                ';'.join(['%s=%s' % item for item in parameters.items()]))
            if response.status == 403:
                raise errors.PermissionDenied(response.text)
            if response.status != 200:
                raise errors.InvalidHttpResponse(path, response.text)
            page = response.getheader("X-Next-Page")
            for entry in json.loads(response.data):
                yield entry

    def _list_merge_requests(self, owner=None, project=None, state=None):
        if project is not None:
            path = 'projects/%s/merge_requests' % urlutils.quote(str(project), '')
        else:
            path = 'merge_requests'
        parameters = {}
        if state:
            parameters['state'] = state
        if owner:
            parameters['owner_id'] = urlutils.quote(owner, '')
        return self._list_paged(path, parameters, per_page=DEFAULT_PAGE_SIZE)

    def _get_merge_request(self, project, merge_id):
        path = 'projects/%s/merge_requests/%d' % (urlutils.quote(str(project), ''), merge_id)
        response = self._api_request('GET', path)
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        if response.status != 200:
            raise errors.InvalidHttpResponse(path, response.text)
        return json.loads(response.data)

    def _list_projects(self, owner):
        path = 'users/%s/projects' % urlutils.quote(str(owner), '')
        parameters = {}
        return self._list_paged(path, parameters, per_page=DEFAULT_PAGE_SIZE)

    def _update_merge_request(self, project_id, iid, mr):
        path = 'projects/%s/merge_requests/%s' % (
            urlutils.quote(str(project_id), ''), iid)
        response = self._api_request('PUT', path, fields=mr)
        if response.status == 200:
            return json.loads(response.data)
        raise errors.InvalidHttpResponse(path, response.text)

    def _create_mergerequest(
            self, title, source_project_id, target_project_id,
            source_branch_name, target_branch_name, description,
            labels=None, allow_collaboration=False):
        path = 'projects/%s/merge_requests' % source_project_id
        fields = {
            'title': title,
            'source_branch': source_branch_name,
            'target_branch': target_branch_name,
            'target_project_id': target_project_id,
            'description': description,
            'allow_collaboration': allow_collaboration,
            }
        if labels:
            fields['labels'] = labels
        response = self._api_request('POST', path, fields=fields)
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        if response.status == 409:
            raise MergeRequestExists()
        if response.status != 201:
            raise errors.InvalidHttpResponse(path, response.text)
        return json.loads(response.data)

    def get_push_url(self, branch):
        (host, project_name, branch_name) = parse_gitlab_branch_url(branch)
        project = self._get_project(project_name)
        return gitlab_url_to_bzr_url(
            project['ssh_url_to_repo'], branch_name)

    def publish_derived(self, local_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False,
                        allow_lossy=True, tag_selector=None):
        (host, base_project, base_branch_name) = parse_gitlab_branch_url(base_branch)
        if owner is None:
            owner = self._get_logged_in_username()
        if project is None:
            project = self._get_project(base_project)['path']
        try:
            target_project = self._get_project('%s/%s' % (owner, project))
        except NoSuchProject:
            target_project = self._fork_project(base_project)
        remote_repo_url = git_url_to_bzr_url(target_project['ssh_url_to_repo'])
        remote_dir = controldir.ControlDir.open(remote_repo_url)
        try:
            push_result = remote_dir.push_branch(
                local_branch, revision_id=revision_id, overwrite=overwrite,
                name=name, tag_selector=tag_selector)
        except errors.NoRoundtrippingSupport:
            if not allow_lossy:
                raise
            push_result = remote_dir.push_branch(
                local_branch, revision_id=revision_id, overwrite=overwrite,
                name=name, lossy=True, tag_selector=tag_selector)
        public_url = gitlab_url_to_bzr_url(
            target_project['http_url_to_repo'], name)
        return push_result.target_branch, public_url

    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        (host, base_project, base_branch_name) = parse_gitlab_branch_url(base_branch)
        if owner is None:
            owner = self._get_logged_in_username()
        if project is None:
            project = self._get_project(base_project)['path']
        try:
            target_project = self._get_project('%s/%s' % (owner, project))
        except NoSuchProject:
            raise errors.NotBranchError('%s/%s/%s' % (self.base_url, owner, project))
        return _mod_branch.Branch.open(gitlab_url_to_bzr_url(
            target_project['ssh_url_to_repo'], name))

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
        for mr in self._list_merge_requests(
                project=target_project['id'], state=state):
            if (mr['source_project_id'] != source_project['id'] or
                    mr['source_branch'] != source_branch_name or
                    mr['target_project_id'] != target_project['id'] or
                    mr['target_branch'] != target_branch_name):
                continue
            yield GitLabMergeProposal(self, mr)

    def hosts(self, branch):
        try:
            (host, project, branch_name) = parse_gitlab_branch_url(branch)
        except NotGitLabUrl:
            return False
        return self.base_hostname == host

    def check(self):
        response = self._api_request('GET', 'user')
        if response.status == 200:
            self._current_user = json.loads(response.data)
            return
        if response == 401:
            if json.loads(response.data) == {"message": "401 Unauthorized"}:
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
        credentials = get_credentials_by_url(transport.base)
        if credentials is not None:
            return cls(transport, credentials.get('private_token'))
        raise UnsupportedHoster(url)

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
        for mp in self._list_merge_requests(
                owner=self._get_logged_in_username(), state=state):
            yield GitLabMergeProposal(self, mp)

    def iter_my_forks(self):
        for project in self._list_projects(owner=self._get_logged_in_username()):
            base_project = project.get('forked_from_project')
            if not base_project:
                continue
            yield project['path_with_namespace']

    def get_proposal_by_url(self, url):
        try:
            (host, project, merge_id) = parse_gitlab_merge_request_url(url)
        except NotGitLabUrl:
            raise UnsupportedHoster(url)
        except NotMergeRequestUrl as e:
            if self.base_hostname == e.host:
                raise
            else:
                raise UnsupportedHoster(url)
        if self.base_hostname != host:
            raise UnsupportedHoster(url)
        project = self._get_project(project)
        mr = self._get_merge_request(project['path_with_namespace'], merge_id)
        return GitLabMergeProposal(self, mr)

    def delete_project(self, project):
        path = 'projects/%s' % urlutils.quote(str(project), '')
        response = self._api_request('DELETE', path)
        if response.status == 404:
            raise NoSuchProject(project)
        if response.status != 202:
            raise errors.InvalidHttpResponse(path, response.text)


class GitlabMergeProposalBuilder(MergeProposalBuilder):

    def __init__(self, gl, source_branch, target_branch):
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
                        prerequisite_branch=None, commit_message=None,
                        work_in_progress=False, allow_collaboration=False):
        """Perform the submission."""
        # https://docs.gitlab.com/ee/api/merge_requests.html#create-mr
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        # Note that commit_message is ignored, since Gitlab doesn't support it.
        source_project = self.gl._get_project(self.source_project_name)
        target_project = self.gl._get_project(self.target_project_name)
        # TODO(jelmer): Allow setting title explicitly
        title = determine_title(description)
        if work_in_progress:
            title = 'WIP: %s' % title
        # TODO(jelmer): Allow setting milestone field
        # TODO(jelmer): Allow setting squash field
        kwargs = {
            'title': title,
            'source_project_id': source_project['id'],
            'target_project_id': target_project['id'],
            'source_branch_name': self.source_branch_name,
            'target_branch_name': self.target_branch_name,
            'description': description,
            'allow_collaboration': allow_collaboration}
        if labels:
            kwargs['labels'] = ','.join(labels)
        if reviewers:
            kwargs['assignee_ids'] = []
            for reviewer in reviewers:
                if '@' in reviewer:
                    user = self.gl._get_user_by_email(reviewer)
                else:
                    user = self.gl._get_user(reviewer)
                kwargs['assignee_ids'].append(user['id'])
        try:
            merge_request = self.gl._create_mergerequest(**kwargs)
        except MergeRequestExists:
            raise MergeProposalExists(self.source_branch.user_url)
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
