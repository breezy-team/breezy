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

import json
import os

from ...propose import (
    determine_title,
    Hoster,
    HosterLoginRequired,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    NoSuchProject,
    PrerequisiteBranchUnsupported,
    ReopenFailed,
    UnsupportedHoster,
    )

from ... import (
    bedding,
    branch as _mod_branch,
    controldir,
    errors,
    hooks,
    urlutils,
    version_string as breezy_version,
    )
from ...config import AuthenticationConfig, GlobalStack
from ...errors import InvalidHttpResponse, PermissionDenied
from ...git.urls import git_url_to_bzr_url
from ...i18n import gettext
from ...sixish import PY3
from ...trace import note
from ...transport import get_transport
from ...transport.http import default_user_agent


GITHUB_HOST = 'github.com'
WEB_GITHUB_URL = 'https://github.com'
API_GITHUB_URL = 'https://api.github.com'
DEFAULT_PER_PAGE = 50


def store_github_token(scheme, host, token):
    with open(os.path.join(bedding.config_dir(), 'github.conf'), 'w') as f:
        f.write(token)


def retrieve_github_token(scheme, host):
    path = os.path.join(bedding.config_dir(), 'github.conf')
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return f.read().strip()


class ValidationFailed(errors.BzrError):

    _fmt = "GitHub validation failed: %(error)s"

    def __init__(self, error):
        errors.BzrError.__init__(self)
        self.error = error


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
    user_agent = default_user_agent()
    auth = AuthenticationConfig()

    credentials = auth.get_credentials('https', GITHUB_HOST)
    if credentials is not None:
        return Github(credentials['user'], credentials['password'],
                      user_agent=user_agent)

    # TODO(jelmer): token = auth.get_token('https', GITHUB_HOST)
    if token is not None:
        return Github(token, user_agent=user_agent)
    else:
        note('Accessing GitHub anonymously. To log in, run \'brz gh-login\'.')
        return Github(user_agent=user_agent)


class GitHubMergeProposal(MergeProposal):

    def __init__(self, gh, pr):
        self._gh = gh
        self._pr = pr

    def __repr__(self):
        return "<%s at %r>" % (type(self).__name__, self.url)

    @property
    def url(self):
        return self._pr['html_url']

    def _branch_from_part(self, part):
        if part['repo'] is None:
            return None
        return github_url_to_bzr_url(part['repo']['html_url'], part['ref'])

    def get_source_branch_url(self):
        return self._branch_from_part(self._pr['head'])

    def get_target_branch_url(self):
        return self._branch_from_part(self._pr['base'])

    def get_source_project(self):
        return self._pr['head']['repo']['full_name']

    def get_target_project(self):
        return self._pr['base']['repo']['full_name']

    def get_description(self):
        return self._pr['body']

    def get_commit_message(self):
        return None

    def set_commit_message(self, message):
        raise errors.UnsupportedOperation(self.set_commit_message, self)

    def _patch(self, data):
        response = self._gh._api_request(
            'PATCH', self._pr['url'], body=json.dumps(data).encode('utf-8'))
        if response.status == 422:
            raise ValidationFailed(json.loads(response.text))
        if response.status != 200:
            raise InvalidHttpResponse(self._pr['url'], response.text)
        self._pr = json.loads(response.text)

    def set_description(self, description):
        self._patch({
            'body': description,
            'title': determine_title(description),
            })

    def is_merged(self):
        return bool(self._pr.get('merged_at'))

    def is_closed(self):
        return self._pr['state'] == 'closed' and not bool(self._pr.get('merged_at'))

    def reopen(self):
        try:
            self._patch({'state': 'open'})
        except ValidationFailed as e:
            raise ReopenFailed(e.error['errors'][0]['message'])

    def close(self):
        self._patch({'state': 'closed'})

    def can_be_merged(self):
        return self._pr['mergeable']

    def merge(self, commit_message=None):
        # https://developer.github.com/v3/pulls/#merge-a-pull-request-merge-button
        self._pr.merge(commit_message=commit_message)

    def get_merged_by(self):
        merged_by = self._pr.get('merged_by')
        if merged_by is None:
            return None
        return merged_by['login']

    def get_merged_at(self):
        merged_at = self._pr.get('merged_at')
        if merged_at is None:
            return None
        import iso8601
        return iso8601.parse_date(merged_at)


def parse_github_url(url):
    (scheme, user, password, host, port, path) = urlutils.parse_url(
        url)
    if host != GITHUB_HOST:
        raise NotGitHubUrl(url)
    (owner, repo_name) = path.strip('/').split('/')
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    return owner, repo_name


def parse_github_branch_url(branch):
    url = urlutils.strip_segment_parameters(branch.user_url)
    owner, repo_name = parse_github_url(url)
    return owner, repo_name, branch.name


def github_url_to_bzr_url(url, branch_name):
    if not PY3:
        branch_name = branch_name.encode('utf-8')
    return git_url_to_bzr_url(url, branch_name)


def strip_optional(url):
    return url.split('{')[0]


class GitHub(Hoster):

    name = 'github'

    supports_merge_proposal_labels = True
    supports_merge_proposal_commit_message = False
    supports_allow_collaboration = True
    merge_proposal_description_format = 'markdown'

    def __repr__(self):
        return "GitHub()"

    def _api_request(self, method, path, body=None):
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/vnd.github.v3+json'}
        if self._token:
            headers['Authorization'] = 'token %s' % self._token
        response = self.transport.request(
            method, urlutils.join(self.transport.base, path),
            headers=headers, body=body, retries=3)
        if response.status == 401:
            raise GitHubLoginRequired(self)
        return response

    def _get_repo(self, owner, repo):
        path = 'repos/%s/%s' % (owner, repo)
        response = self._api_request('GET', path)
        if response.status == 404:
            raise NoSuchProject(path)
        if response.status == 200:
            return json.loads(response.text)
        raise InvalidHttpResponse(path, response.text)

    def _get_repo_pulls(self, path, head=None, state=None):
        path = path + '?'
        params = {}
        if head is not None:
            params['head'] = head
        if state is not None:
            params['state'] = state
        path += ';'.join(['%s=%s' % (k, urlutils.quote(v))
                         for k, v in params.items()])
        response = self._api_request('GET', path)
        if response.status == 404:
            raise NoSuchProject(path)
        if response.status == 200:
            return json.loads(response.text)
        raise InvalidHttpResponse(path, response.text)

    def _create_pull(self, path, title, head, base, body=None, labels=None,
                     assignee=None, draft=False, maintainer_can_modify=False):
        data = {
            'title': title,
            'head': head,
            'base': base,
            'draft': draft,
            'maintainer_can_modify': maintainer_can_modify,
        }
        if labels is not None:
            data['labels'] = labels
        if assignee is not None:
            data['assignee'] = assignee
        if body:
            data['body'] = body

        response = self._api_request(
            'POST', path, body=json.dumps(data).encode('utf-8'))
        if response.status == 403:
            raise PermissionDenied(path, response.text)
        if response.status != 201:
            raise InvalidHttpResponse(path, 'req is invalid %d %r: %r' % (response.status, data, response.text))
        return json.loads(response.text)

    def _get_user_by_email(self, email):
        path = 'search/users?q=%s+in:email' % email
        response = self._api_request('GET', path)
        if response.status != 200:
            raise InvalidHttpResponse(path, response.text)
        ret = json.loads(response.text)
        if ret['total_count'] == 0:
            raise KeyError('no user with email %s' % email)
        elif ret['total_count'] > 1:
            raise ValueError('more than one result for email %s' % email)
        return ret['items'][0]

    def _get_user(self, username=None):
        if username:
            path = 'users/%s' % username
        else:
            path = 'user'
        response = self._api_request('GET', path)
        if response.status != 200:
            raise InvalidHttpResponse(path, response.text)
        return json.loads(response.text)

    def _get_organization(self, name):
        path = 'orgs/%s' % name
        response = self._api_request('GET', path)
        if response.status != 200:
            raise InvalidHttpResponse(path, response.text)
        return json.loads(response.text)

    def _list_paged(self, path, parameters=None, per_page=None):
        if parameters is None:
            parameters = {}
        else:
            parameters = dict(parameters.items())
        if per_page:
            parameters['per_page'] = str(per_page)
        page = 1
        i = 0
        while path:
            parameters['page'] = str(page)
            response = self._api_request(
                'GET', path + '?' +
                ';'.join(['%s=%s' % (k, urlutils.quote(v))
                          for (k, v) in parameters.items()]))
            if response.status != 200:
                raise InvalidHttpResponse(path, response.text)
            data = json.loads(response.text)
            for entry in data['items']:
                i += 1
                yield entry
            if i >= data['total_count']:
                break
            page += 1

    def _search_issues(self, query):
        path = 'search/issues'
        return self._list_paged(path, {'q': query}, per_page=DEFAULT_PER_PAGE)

    def _create_fork(self, path, owner=None):
        if owner and owner != self._current_user['login']:
            path += '?organization=%s' % owner
        response = self._api_request('POST', path)
        if response.status != 202:
            raise InvalidHttpResponse(path, 'status: %d, %r' % (response.status, response.text))
        return json.loads(response.text)

    @property
    def base_url(self):
        return WEB_GITHUB_URL

    def __init__(self, transport):
        self._token = retrieve_github_token('https', GITHUB_HOST)
        self.transport = transport
        self._current_user = self._get_user()

    def publish_derived(self, local_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False,
                        allow_lossy=True, tag_selector=None):
        base_owner, base_project, base_branch_name = parse_github_branch_url(base_branch)
        base_repo = self._get_repo(base_owner, base_project)
        if owner is None:
            owner = self._current_user['login']
        if project is None:
            project = base_repo['name']
        try:
            remote_repo = self._get_repo(owner, project)
        except NoSuchProject:
            base_repo = self._get_repo(base_owner, base_project)
            remote_repo = self._create_fork(base_repo['forks_url'], owner)
            note(gettext('Forking new repository %s from %s') %
                 (remote_repo['html_url'], base_repo['html_url']))
        else:
            note(gettext('Reusing existing repository %s') % remote_repo['html_url'])
        remote_dir = controldir.ControlDir.open(git_url_to_bzr_url(remote_repo['ssh_url']))
        try:
            push_result = remote_dir.push_branch(
                local_branch, revision_id=revision_id, overwrite=overwrite,
                name=name, tag_selector=tag_selector)
        except errors.NoRoundtrippingSupport:
            if not allow_lossy:
                raise
            push_result = remote_dir.push_branch(
                local_branch, revision_id=revision_id,
                overwrite=overwrite, name=name, lossy=True,
                tag_selector=tag_selector)
        return push_result.target_branch, github_url_to_bzr_url(
            remote_repo['html_url'], name)

    def get_push_url(self, branch):
        owner, project, branch_name = parse_github_branch_url(branch)
        repo = self._get_repo(owner, project)
        return github_url_to_bzr_url(repo['ssh_url'], branch_name)

    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        base_owner, base_project, base_branch_name = parse_github_branch_url(base_branch)
        base_repo = self._get_repo(base_owner, base_project)
        if owner is None:
            owner = self._current_user['login']
        if project is None:
            project = base_repo['name']
        try:
            remote_repo = self._get_repo(owner, project)
            full_url = github_url_to_bzr_url(remote_repo['ssh_url'], name)
            return _mod_branch.Branch.open(full_url)
        except NoSuchProject:
            raise errors.NotBranchError('%s/%s/%s' % (WEB_GITHUB_URL, owner, project))

    def get_proposer(self, source_branch, target_branch):
        return GitHubMergeProposalBuilder(self, source_branch, target_branch)

    def iter_proposals(self, source_branch, target_branch, status='open'):
        (source_owner, source_repo_name, source_branch_name) = (
            parse_github_branch_url(source_branch))
        (target_owner, target_repo_name, target_branch_name) = (
            parse_github_branch_url(target_branch))
        target_repo = self._get_repo(target_owner, target_repo_name)
        state = {
            'open': 'open',
            'merged': 'closed',
            'closed': 'closed',
            'all': 'all'}
        pulls = self._get_repo_pulls(
            strip_optional(target_repo['pulls_url']),
            head=target_branch_name,
            state=state[status])
        for pull in pulls:
            if (status == 'closed' and pull['merged'] or
                    status == 'merged' and not pull['merged']):
                continue
            if pull['head']['ref'] != source_branch_name:
                continue
            if pull['head']['repo'] is None:
                # Repo has gone the way of the dodo
                continue
            if (pull['head']['repo']['owner']['login'] != source_owner or
                    pull['head']['repo']['name'] != source_repo_name):
                continue
            yield GitHubMergeProposal(self, pull)

    def hosts(self, branch):
        try:
            parse_github_branch_url(branch)
        except NotGitHubUrl:
            return False
        else:
            return True

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        try:
            parse_github_url(url)
        except NotGitHubUrl:
            raise UnsupportedHoster(url)
        transport = get_transport(
            API_GITHUB_URL, possible_transports=possible_transports)
        return cls(transport)

    @classmethod
    def iter_instances(cls):
        yield cls(get_transport(API_GITHUB_URL))

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
        query.append('author:%s' % self._current_user['login'])
        for issue in self._search_issues(query=' '.join(query)):
            url = issue['pull_request']['url']
            response = self._api_request('GET', url)
            if response.status != 200:
                raise InvalidHttpResponse(url, response.text)
            yield GitHubMergeProposal(self, json.loads(response.text))

    def get_proposal_by_url(self, url):
        raise UnsupportedHoster(url)

    def iter_my_forks(self):
        response = self._api_request('GET', '/user/repos')
        if response.status != 200:
            raise InvalidHttpResponse(url, response.text)
        for project in json.loads(response.text):
            if not project['fork']:
                continue
            yield project['full_name']

    def delete_project(self, path):
        path = 'repos/' + path
        response = self._api_request('DELETE', path)
        if response.status == 404:
            raise NoSuchProject(path)
        if response.status == 204:
            return
        if response.status == 200:
            return json.loads(response.text)
        raise InvalidHttpResponse(path, response.text)


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
                        prerequisite_branch=None, commit_message=None,
                        work_in_progress=False, allow_collaboration=False):
        """Perform the submission."""
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        # Note that commit_message is ignored, since github doesn't support it.
        # TODO(jelmer): Probe for right repo name
        if self.target_repo_name.endswith('.git'):
            self.target_repo_name = self.target_repo_name[:-4]
        # TODO(jelmer): Allow setting title explicitly?
        title = determine_title(description)
        target_repo = self.gh._get_repo(
            self.target_owner, self.target_repo_name)
        assignees = []
        if reviewers:
            assignees = []
            for reviewer in reviewers:
                if '@' in reviewer:
                    user = self.gh._get_user_by_email(reviewer)
                else:
                    user = self.gh._get_user(reviewer)
                assignees.append(user['login'])
        else:
            assignees = None
        try:
            pull_request = self.gh._create_pull(
                strip_optional(target_repo['pulls_url']),
                title=title, body=description,
                head="%s:%s" % (self.source_owner, self.source_branch_name),
                base=self.target_branch_name,
                labels=labels, assignee=assignees,
                draft=work_in_progress,
                maintainer_can_modify=allow_collaboration,
                )
        except ValidationFailed:
            raise MergeProposalExists(self.source_branch.user_url)
        return GitHubMergeProposal(self.gh, pull_request)
