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

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from ... import bedding, controldir, errors, urlutils
from ... import branch as _mod_branch
from ...config import AuthenticationConfig
from ...errors import PermissionDenied, UnexpectedHttpStatus
from ...forge import (
    AutoMergeUnavailable,
    Forge,
    ForgeLoginRequired,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    NoSuchProject,
    PrerequisiteBranchUnsupported,
    ReopenFailed,
    UnsupportedForge,
    determine_title,
)
from ...git.urls import git_url_to_bzr_url
from ...i18n import gettext
from ...trace import mutter, note
from ...transport import get_transport

GITHUB_HOST = "github.com"
WEB_GITHUB_URL = "https://github.com"
API_GITHUB_URL = "https://api.github.com"
DEFAULT_PER_PAGE = 100

SCHEME_FIELD_MAP = {
    "ssh": "ssh_url",
    "git+ssh": "ssh_url",
    "http": "clone_url",
    "https": "clone_url",
    "git": "git_url",
}
DEFAULT_PREFERRED_SCHEMES = ["ssh", "http"]


def parse_timestring(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def store_github_token(token):
    auth_config = AuthenticationConfig()
    auth_config._set_option("Github", "scheme", "https")
    auth_config._set_option("Github", "url", API_GITHUB_URL)
    auth_config._set_option("Github", "private_token", token)


def retrieve_github_token():
    auth_config = AuthenticationConfig()
    section = auth_config._get_config().get("Github")
    if section and section.get("private_token"):
        return section.get("private_token")

    # Backwards compatibility
    path = os.path.join(bedding.config_dir(), "github.conf")
    if not os.path.exists(path):
        return None
    with open(path) as f:
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


class GitHubLoginRequired(ForgeLoginRequired):
    _fmt = "Action requires GitHub login."


class GitHubMergeProposal(MergeProposal):
    supports_auto_merge = True

    def __init__(self, gh, pr):
        self._gh = gh
        self._pr = pr

    def __repr__(self):
        return f"<{type(self).__name__} at {self.url!r}>"

    name = "GitHub"

    def get_web_url(self):
        return self._pr["html_url"]

    @property
    def url(self):
        return self._pr["html_url"]

    def _branch_from_part(self, part, preferred_schemes=None):
        if part["repo"] is None:
            return None
        if preferred_schemes is None:
            preferred_schemes = DEFAULT_PREFERRED_SCHEMES
        for scheme in preferred_schemes:
            if scheme in SCHEME_FIELD_MAP:
                return github_url_to_bzr_url(
                    part["repo"][SCHEME_FIELD_MAP[scheme]], part["ref"]
                )
        raise AssertionError

    def get_source_branch_url(self, *, preferred_schemes=None):
        return self._branch_from_part(
            self._pr["head"], preferred_schemes=preferred_schemes
        )

    def get_source_revision(self):
        """Return the latest revision for the source branch."""
        from ...git.mapping import default_mapping

        return default_mapping.revision_id_foreign_to_bzr(
            self._pr["head"]["sha"].encode("ascii")
        )

    def get_target_branch_url(self, *, preferred_schemes=None):
        return self._branch_from_part(
            self._pr["base"], preferred_schemes=preferred_schemes
        )

    def set_target_branch_name(self, name):
        self._patch(base=name)

    def get_source_project(self):
        if self._pr["head"]["repo"] is None:
            return None
        return self._pr["head"]["repo"]["full_name"]

    def get_target_project(self):
        if self._pr["base"]["repo"] is None:
            return None
        return self._pr["base"]["repo"]["full_name"]

    def get_description(self):
        return self._pr["body"]

    def get_commit_message(self):
        return None

    def get_title(self):
        return self._pr.get("title")

    def set_title(self, title):
        self._patch(title=title)

    def set_commit_message(self, message):
        raise errors.UnsupportedOperation(self.set_commit_message, self)

    def _patch(self, **data):
        response = self._gh._api_request(
            "PATCH", self._pr["url"], body=json.dumps(data).encode("utf-8")
        )
        if response.status == 422:
            raise ValidationFailed(json.loads(response.text))
        if response.status != 200:
            raise UnexpectedHttpStatus(
                self._pr["url"], response.status, headers=response.getheaders()
            )
        self._pr = json.loads(response.text)

    def set_description(self, description):
        self._patch(body=description, title=determine_title(description))

    def is_merged(self):
        return bool(self._pr.get("merged_at"))

    def is_closed(self):
        return self._pr["state"] == "closed" and not bool(self._pr.get("merged_at"))

    def reopen(self):
        try:
            self._patch(state="open")
        except ValidationFailed as e:
            raise ReopenFailed(e.error["errors"][0]["message"]) from e

    def close(self):
        self._patch(state="closed")

    def can_be_merged(self):
        return self._pr["mergeable"]

    def merge(self, commit_message=None, auto=False):
        if auto:
            graphql_query = """
mutation ($pullRequestId: ID!) {
  enablePullRequestAutoMerge(input: {
    pullRequestId: $pullRequestId,
    mergeMethod: MERGE
  }) {
    pullRequest {
      autoMergeRequest {
        enabledAt
        enabledBy {
          login
        }
      }
    }
  }
}
"""
            try:
                self._gh._graphql_request(
                    graphql_query, pullRequestId=self._pr["node_id"]
                )
            except GraphqlErrors as e:
                mutter("graphql errors: %r", e.errors)
                first_error = e.errors[0]
                if first_error["type"] == "UNPROCESSABLE" and first_error["path"] == [
                    "enablePullRequestAutoMerge"
                ]:
                    raise AutoMergeUnavailable(first_error["message"]) from e
                if first_error["type"] == "FORBIDDEN" and first_error["path"] == [
                    "enablePullRequestAutoMerge"
                ]:
                    raise PermissionDenied(
                        path=self.get_web_url(), extra=first_error["message"]
                    ) from e
                raise Exception(first_error["message"]) from e
        else:
            # https://developer.github.com/v3/pulls/#merge-a-pull-request-merge-button
            data = {}
            if commit_message:
                data["commit_message"] = commit_message
            response = self._gh._api_request(
                "PUT", self._pr["url"] + "/merge", body=json.dumps(data).encode("utf-8")
            )
            if response.status == 422:
                raise ValidationFailed(json.loads(response.text))
            if response.status != 200:
                raise UnexpectedHttpStatus(
                    self._pr["url"], response.status, headers=response.getheaders()
                )

    def get_merged_by(self):
        merged_by = self._pr.get("merged_by")
        if merged_by is None:
            return None
        return merged_by["login"]

    def get_merged_at(self):
        merged_at = self._pr.get("merged_at")
        if merged_at is None:
            return None
        return parse_timestring(merged_at)

    def post_comment(self, body):
        data = {"body": body}
        response = self._gh._api_request(
            "POST", self._pr["comments_url"], body=json.dumps(data).encode("utf-8")
        )
        if response.status == 422:
            raise ValidationFailed(json.loads(response.text))
        if response.status != 201:
            raise UnexpectedHttpStatus(
                self._pr["comments_url"], response.status, headers=response.getheaders()
            )
        json.loads(response.text)


def parse_github_url(url):
    (scheme, user, password, host, port, path) = urlutils.parse_url(url)
    if host != GITHUB_HOST:
        raise NotGitHubUrl(url)
    (owner, repo_name) = path.strip("/").split("/")
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    return owner, repo_name


def parse_github_branch_url(branch):
    url = urlutils.strip_segment_parameters(branch.user_url)
    owner, repo_name = parse_github_url(url)
    return owner, repo_name, branch.name


def parse_github_pr_url(url):
    (scheme, user, password, host, port, path) = urlutils.parse_url(url)
    if host != GITHUB_HOST:
        raise NotGitHubUrl(url)
    try:
        (owner, repo_name, pull, pr_id) = path.strip("/").split("/")
    except IndexError as e:
        raise ValueError("Not a PR URL") from e

    if pull != "pull":
        raise ValueError("Not a PR URL")

    return (owner, repo_name, pr_id)


def github_url_to_bzr_url(url, branch_name):
    return git_url_to_bzr_url(url, branch_name)


def strip_optional(url):
    return url.split("{")[0]


class _LazyDict(dict):
    def __init__(self, base, load_fn):
        self._load_fn = load_fn
        super().update(base)

    def _load_full(self):
        super().update(self._load_fn())
        self._load_fn = None

    def __getitem__(self, key):
        if self._load_fn is not None:
            try:
                return super().__getitem__(key)
            except KeyError:
                self._load_full()
        return super().__getitem__(key)

    def items(self):
        self._load_full()
        return super().items()

    def keys(self):
        self._load_full()
        return super().keys()

    def values(self):
        self._load_full()
        return super().values()

    def __contains__(self, key):
        if super().__contains__(key):
            return True
        if self._load_fn is not None:
            self._load_full()
            return super().__contains__(key)
        return False

    def __delitem__(self, name):
        raise NotImplementedError

    def __setitem__(self, name, value):
        raise NotImplementedError

    def get(self, name, default=None):
        if self._load_fn is not None:
            try:
                return super().get(name, default)
            except KeyError:
                self._load_full()
        return super().get(name, default)

    def pop(self):
        raise NotImplementedError

    def popitem(self):
        raise NotImplementedError

    def clear(self):
        raise NotImplementedError


class GraphqlErrors(Exception):
    def __init__(self, errors):
        self.errors = errors


class GitHub(Forge):
    name = "github"

    supports_merge_proposal_labels = True
    supports_merge_proposal_commit_message = False
    supports_merge_proposal_title = True
    supports_allow_collaboration = True
    merge_proposal_description_format = "markdown"

    def __repr__(self):
        return "GitHub()"

    def _graphql_request(self, body, **kwargs):
        headers = {}
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        url = urlutils.join(self.transport.base, "graphql")
        response = self.transport.request(
            "POST",
            url,
            headers=headers,
            body=json.dumps(
                {
                    "query": body,
                    "variables": kwargs,
                }
            ).encode("utf-8"),
        )
        if response.status != 200:
            raise UnexpectedHttpStatus(
                url, response.status, headers=response.getheaders()
            )
        data = json.loads(response.text)
        if data.get("errors"):
            raise GraphqlErrors(data.get("errors"))
        return data["data"]

    def _api_request(self, method, path, body=None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json",
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        try:
            response = self.transport.request(
                method,
                urlutils.join(self.transport.base, path),
                headers=headers,
                body=body,
                retries=3,
            )
        except UnexpectedHttpStatus as e:
            if e.code == 401:
                raise GitHubLoginRequired(self.base_url) from e
            else:
                raise
        if response.status == 401:
            raise GitHubLoginRequired(self.base_url)
        return response

    def _get_repo(self, owner, repo):
        path = f"repos/{owner}/{repo}"
        response = self._api_request("GET", path)
        if response.status == 404:
            raise NoSuchProject(path)
        if response.status == 200:
            return json.loads(response.text)
        raise UnexpectedHttpStatus(path, response.status, headers=response.getheaders())

    def _get_repo_pulls(self, path, head=None, state=None):
        path = path + "?"
        params = {}
        if head is not None:
            params["head"] = head
        if state is not None:
            params["state"] = state
        path += ";".join([f"{k}={urlutils.quote(v)}" for k, v in params.items()])
        response = self._api_request("GET", path)
        if response.status == 404:
            raise NoSuchProject(path)
        if response.status == 200:
            return json.loads(response.text)
        raise UnexpectedHttpStatus(path, response.status, headers=response.getheaders())

    def _create_pull(
        self,
        path,
        title,
        head,
        base,
        body=None,
        labels=None,
        assignee=None,
        draft=False,
        maintainer_can_modify=False,
    ):
        data = {
            "title": title,
            "head": head,
            "base": base,
            "draft": draft,
            "maintainer_can_modify": maintainer_can_modify,
        }
        if labels is not None:
            data["labels"] = labels
        if assignee is not None:
            data["assignee"] = assignee
        if body:
            data["body"] = body

        response = self._api_request(
            "POST", path, body=json.dumps(data).encode("utf-8")
        )
        if response.status == 403:
            raise PermissionDenied(path, response.text)
        if response.status == 422:
            raise ValidationFailed(json.loads(response.text))
        if response.status != 201:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    def _get_user_by_email(self, email):
        path = f"search/users?q={email}+in:email"
        response = self._api_request("GET", path)
        if response.status != 200:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        ret = json.loads(response.text)
        if ret["total_count"] == 0:
            raise KeyError(f"no user with email {email}")
        elif ret["total_count"] > 1:
            raise ValueError(f"more than one result for email {email}")
        return ret["items"][0]

    def _get_user(self, username=None):
        path = f"users/{username}" if username else "user"
        response = self._api_request("GET", path)
        if response.status != 200:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    def _get_organization(self, name):
        path = f"orgs/{name}"
        response = self._api_request("GET", path)
        if response.status != 200:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    def _list_paged(self, path, parameters=None, per_page=None):
        parameters = {} if parameters is None else dict(parameters.items())
        if per_page:
            parameters["per_page"] = str(per_page)
        page = 1
        while path:
            parameters["page"] = str(page)
            response = self._api_request(
                "GET",
                path
                + "?"
                + ";".join(
                    [f"{k}={urlutils.quote(v)}" for (k, v) in parameters.items()]
                ),
            )
            if response.status != 200:
                raise UnexpectedHttpStatus(
                    path, response.status, headers=response.getheaders()
                )
            data = json.loads(response.text)
            if not data:
                break
            yield data
            page += 1

    def _search_issues(self, query):
        path = "search/issues"
        for page in self._list_paged(path, {"q": query}, per_page=DEFAULT_PER_PAGE):
            if not page["items"]:
                break
            yield from page["items"]

    def _create_fork(self, path, owner=None):
        if owner and owner != self.current_user["login"]:
            path += f"?organization={owner}"
        response = self._api_request("POST", path)
        if response.status != 202:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    @property
    def base_url(self):
        return WEB_GITHUB_URL

    def __init__(self, transport):
        self._token = retrieve_github_token()
        if self._token is None:
            note("Accessing GitHub anonymously. To log in, run 'brz gh-login'.")
        self.transport = transport
        self._current_user = None

    @property
    def current_user(self):
        if self._current_user is None:
            self._current_user = self._get_user()
        return self._current_user

    def publish_derived(
        self,
        local_branch,
        base_branch,
        name,
        project=None,
        owner=None,
        revision_id=None,
        overwrite=False,
        allow_lossy=True,
        tag_selector=None,
    ):
        if tag_selector is None:

            def tag_selector(t):
                return False

        base_owner, base_project, base_branch_name = parse_github_branch_url(
            base_branch
        )
        base_repo = self._get_repo(base_owner, base_project)
        if owner is None:
            owner = self.current_user["login"]
        if project is None:
            project = base_repo["name"]
        try:
            remote_repo = self._get_repo(owner, project)
        except NoSuchProject:
            base_repo = self._get_repo(base_owner, base_project)
            remote_repo = self._create_fork(base_repo["forks_url"], owner)
            note(
                gettext("Forking new repository %s from %s")
                % (remote_repo["html_url"], base_repo["html_url"])
            )
        else:
            note(gettext("Reusing existing repository %s") % remote_repo["html_url"])
        remote_dir = controldir.ControlDir.open(
            git_url_to_bzr_url(remote_repo["ssh_url"])
        )
        try:
            push_result = remote_dir.push_branch(
                local_branch,
                revision_id=revision_id,
                overwrite=overwrite,
                name=name,
                tag_selector=tag_selector,
            )
        except errors.NoRoundtrippingSupport:
            if not allow_lossy:
                raise
            push_result = remote_dir.push_branch(
                local_branch,
                revision_id=revision_id,
                overwrite=overwrite,
                name=name,
                lossy=True,
                tag_selector=tag_selector,
            )
        return push_result.target_branch, github_url_to_bzr_url(
            remote_repo["clone_url"], name
        )

    def get_push_url(self, branch):
        owner, project, branch_name = parse_github_branch_url(branch)
        repo = self._get_repo(owner, project)
        return github_url_to_bzr_url(repo["ssh_url"], branch_name)

    def get_web_url(self, branch):
        owner, project, branch_name = parse_github_branch_url(branch)
        repo = self._get_repo(owner, project)
        if branch_name:
            # TODO(jelmer): Don't hardcode this
            return repo["html_url"] + "/tree/" + branch_name
        else:
            return repo["html_url"]

    def get_derived_branch(
        self, base_branch, name, project=None, owner=None, preferred_schemes=None
    ):
        base_owner, base_project, base_branch_name = parse_github_branch_url(
            base_branch
        )
        base_repo = self._get_repo(base_owner, base_project)
        if owner is None:
            owner = self.current_user["login"]
        if project is None:
            project = base_repo["name"]
        try:
            remote_repo = self._get_repo(owner, project)
        except NoSuchProject as e:
            raise errors.NotBranchError(f"{WEB_GITHUB_URL}/{owner}/{project}") from e
        if preferred_schemes is None:
            preferred_schemes = DEFAULT_PREFERRED_SCHEMES
        for scheme in preferred_schemes:
            if scheme in SCHEME_FIELD_MAP:
                github_url = remote_repo[SCHEME_FIELD_MAP[scheme]]
                break
        else:
            raise AssertionError
        full_url = github_url_to_bzr_url(github_url, name)
        return _mod_branch.Branch.open(full_url)

    def get_proposer(self, source_branch, target_branch):
        return GitHubMergeProposalBuilder(self, source_branch, target_branch)

    def iter_proposals(self, source_branch, target_branch, status="open"):
        (source_owner, source_repo_name, source_branch_name) = parse_github_branch_url(
            source_branch
        )
        (target_owner, target_repo_name, target_branch_name) = parse_github_branch_url(
            target_branch
        )
        target_repo = self._get_repo(target_owner, target_repo_name)
        state = {"open": "open", "merged": "closed", "closed": "closed", "all": "all"}
        pulls = self._get_repo_pulls(
            strip_optional(target_repo["pulls_url"]),
            head=target_branch_name,
            state=state[status],
        )
        for pull in pulls:
            if (
                status == "closed"
                and pull["merged"]
                or status == "merged"
                and not pull["merged"]
            ):
                continue
            if pull["head"]["ref"] != source_branch_name:
                continue
            if pull["head"]["repo"] is None:
                # Repo has gone the way of the dodo
                continue
            if (
                pull["head"]["repo"]["owner"]["login"] != source_owner
                or pull["head"]["repo"]["name"] != source_repo_name
            ):
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
    def probe_from_hostname(cls, hostname, possible_transports=None):
        if hostname == GITHUB_HOST:
            transport = get_transport(
                API_GITHUB_URL, possible_transports=possible_transports
            )
            return cls(transport)
        raise UnsupportedForge(hostname)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        try:
            parse_github_url(url)
        except NotGitHubUrl as e:
            raise UnsupportedForge(url) from e
        transport = get_transport(
            API_GITHUB_URL, possible_transports=possible_transports
        )
        return cls(transport)

    @classmethod
    def iter_instances(cls):
        yield cls(get_transport(API_GITHUB_URL))

    def iter_my_proposals(self, status="open", author=None):
        query = ["is:pr"]
        if status == "open":
            query.append("is:open")
        elif status == "closed":
            query.append("is:unmerged")
            # Also use "is:closed" otherwise unmerged open pull requests are
            # also included.
            query.append("is:closed")
        elif status == "merged":
            query.append("is:merged")
        if author is None:
            author = self.current_user["login"]
        query.append(f"author:{author}")
        for issue in self._search_issues(query=" ".join(query)):

            def retrieve_full():
                response = self._api_request("GET", issue["pull_request"]["url"])  # noqa: B023
                if response.status != 200:
                    raise UnexpectedHttpStatus(
                        issue["pull_request"]["url"],  # noqa: B023
                        response.status,
                        headers=response.getheaders(),
                    )
                return json.loads(response.text)

            yield GitHubMergeProposal(
                self, _LazyDict(issue["pull_request"], retrieve_full)
            )

    def get_proposal_by_url(self, url):
        try:
            (owner, repo, pr_id) = parse_github_pr_url(url)
        except NotGitHubUrl as e:
            raise UnsupportedForge(url) from e
        api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_id}"
        response = self._api_request("GET", api_url)
        if response.status != 200:
            raise UnexpectedHttpStatus(
                api_url, response.status, headers=response.getheaders()
            )
        data = json.loads(response.text)
        return GitHubMergeProposal(self, data)

    def iter_my_forks(self, owner=None):
        path = f"/users/{owner}/repos" if owner else "/user/repos"
        for page in self._list_paged(path, per_page=DEFAULT_PER_PAGE):
            for project in page:
                if not project["fork"]:
                    continue
                yield project["full_name"]

    def delete_project(self, path):
        path = "repos/" + path
        response = self._api_request("DELETE", path)
        if response.status == 404:
            raise NoSuchProject(path)
        if response.status == 204:
            return
        if response.status == 200:
            return json.loads(response.text)
        raise UnexpectedHttpStatus(path, response.status, headers=response.getheaders())

    def create_project(
        self,
        path,
        *,
        homepage=None,
        private=False,
        has_issues=True,
        has_projects=False,
        has_wiki=False,
        summary=None,
    ):
        owner, name = path.split("/")
        path = "repos"
        data = {
            "name": "name",
            "description": summary,
            "homepage": homepage,
            "private": private,
            "has_issues": has_issues,
            "has_projects": has_projects,
            "has_wiki": has_wiki,
        }
        response = self._api_request(
            "POST", path, body=json.dumps(data).encode("utf-8")
        )
        if response.status != 201:
            return json.loads(response.text)
        raise UnexpectedHttpStatus(path, response.status, headers=response.getheaders())

    def get_current_user(self):
        if self._token is not None:
            return self.current_user["login"]
        return None

    def get_user_url(self, username):
        return urlutils.join(self.base_url, username)


class GitHubMergeProposalBuilder(MergeProposalBuilder):
    def __init__(self, gh, source_branch, target_branch):
        self.gh = gh
        self.source_branch = source_branch
        self.target_branch = target_branch
        (
            self.target_owner,
            self.target_repo_name,
            self.target_branch_name,
        ) = parse_github_branch_url(self.target_branch)
        (
            self.source_owner,
            self.source_repo_name,
            self.source_branch_name,
        ) = parse_github_branch_url(self.source_branch)

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        info = []
        info.append(
            "Merge {} into {}:{}\n".format(
                self.source_branch_name, self.target_owner, self.target_branch_name
            )
        )
        info.append(f"Source: {self.source_branch.user_url}\n")
        info.append(f"Target: {self.target_branch.user_url}\n")
        return "".join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        return None

    def create_proposal(
        self,
        description,
        title=None,
        reviewers=None,
        labels=None,
        prerequisite_branch=None,
        commit_message=None,
        work_in_progress=False,
        allow_collaboration=False,
        delete_source_after_merge: Optional[bool] = None,
    ):
        """Perform the submission."""
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        # Note that commit_message is ignored, since github doesn't support it.
        # TODO(jelmer): Probe for right repo name
        if self.target_repo_name.endswith(".git"):
            self.target_repo_name = self.target_repo_name[:-4]
        if title is None:
            title = determine_title(description)
        target_repo = self.gh._get_repo(self.target_owner, self.target_repo_name)
        assignees: Optional[List[Dict[str, Any]]] = []
        if reviewers:
            assignees = []
            for reviewer in reviewers:
                if "@" in reviewer:
                    user = self.gh._get_user_by_email(reviewer)
                else:
                    user = self.gh._get_user(reviewer)
                assignees.append(user["login"])
        else:
            assignees = None
        kwargs: Dict[str, Any] = {}
        if delete_source_after_merge is not None:
            kwargs["delete_branch_on_merge"] = delete_source_after_merge
        try:
            pull_request = self.gh._create_pull(
                strip_optional(target_repo["pulls_url"]),
                title=title,
                body=description,
                head=f"{self.source_owner}:{self.source_branch_name}",
                base=self.target_branch_name,
                labels=labels,
                assignee=assignees,
                draft=work_in_progress,
                maintainer_can_modify=allow_collaboration,
                **kwargs,
            )
        except ValidationFailed as e:
            # TODO(jelmer): Check the actual error message rather than assuming
            # a merge proposal exists?
            raise MergeProposalExists(self.source_branch.user_url) from e
        return GitHubMergeProposal(self.gh, pull_request)
