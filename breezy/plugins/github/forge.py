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
from typing import Any

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
    """Parse a GitHub timestamp string into a datetime object.

    Args:
        ts: A timestamp string in GitHub's ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ).

    Returns:
        A datetime object representing the parsed timestamp.

    Example:
        >>> parse_timestring("2023-01-15T10:30:45Z")
        datetime.datetime(2023, 1, 15, 10, 30, 45)
    """
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def store_github_token(token):
    """Store a GitHub personal access token in the authentication configuration.

    Args:
        token: The GitHub personal access token to store.

    This function saves the token to the Breezy authentication configuration
    for future use in API requests.
    """
    auth_config = AuthenticationConfig()
    auth_config._set_option("Github", "scheme", "https")
    auth_config._set_option("Github", "url", API_GITHUB_URL)
    auth_config._set_option("Github", "private_token", token)


def retrieve_github_token():
    """Retrieve the stored GitHub personal access token.

    Returns:
        The GitHub personal access token if found, None otherwise.

    This function first checks the Breezy authentication configuration,
    then falls back to a legacy github.conf file for backwards compatibility.
    """
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
    """Exception raised when GitHub API validation fails.

    This error is raised when GitHub returns a 422 status code,
    indicating that the request was well-formed but contained
    invalid data or parameters.
    """

    _fmt = "GitHub validation failed: %(error)s"

    def __init__(self, error):
        """Initialize the ValidationFailed exception.

        Args:
            error: The validation error details from GitHub's API response.
        """
        errors.BzrError.__init__(self)
        self.error = error


class NotGitHubUrl(errors.BzrError):
    """Exception raised when a URL is not a valid GitHub URL.

    This error is raised when attempting to parse a URL that
    doesn't match GitHub's expected format or hostname.
    """

    _fmt = "Not a GitHub URL: %(url)s"

    def __init__(self, url):
        """Initialize the NotGitHubUrl exception.

        Args:
            url: The URL that was not recognized as a GitHub URL.
        """
        errors.BzrError.__init__(self)
        self.url = url


class GitHubLoginRequired(ForgeLoginRequired):
    """Exception raised when a GitHub operation requires authentication.

    This error is raised when attempting to perform an action that
    requires a valid GitHub authentication token, but none is available
    or the provided token is invalid.
    """

    _fmt = "Action requires GitHub login."


class GitHubMergeProposal(MergeProposal):
    """Represents a GitHub pull request as a merge proposal.

    This class wraps GitHub's pull request API and provides a consistent
    interface for interacting with merge proposals across different forges.

    Attributes:
        supports_auto_merge: Indicates that this forge supports automatic merging.
        name: The display name for this forge type.
    """

    supports_auto_merge = True

    def __init__(self, gh, pr):
        """Initialize a GitHubMergeProposal.

        Args:
            gh: The GitHub forge instance.
            pr: The pull request data from GitHub's API.
        """
        self._gh = gh
        self._pr = pr

    def __repr__(self):
        """Return a string representation of the merge proposal.

        Returns:
            A string representation showing the class name and URL.
        """
        return f"<{type(self).__name__} at {self.url!r}>"

    name = "GitHub"

    def get_web_url(self):
        """Get the web URL for this pull request.

        Returns:
            The GitHub web URL where users can view the pull request.
        """
        return self._pr["html_url"]

    @property
    def url(self):
        """The web URL for this pull request.

        Returns:
            The GitHub web URL where users can view the pull request.
        """
        return self._pr["html_url"]

    def _branch_from_part(self, part, preferred_schemes=None):
        """Convert a GitHub pull request head/base part to a Breezy branch URL.

        Args:
            part: A GitHub pull request head or base section containing repo and ref info.
            preferred_schemes: List of preferred URL schemes in order of preference.
                             Defaults to DEFAULT_PREFERRED_SCHEMES.

        Returns:
            A Breezy-compatible branch URL, or None if the repo is None.

        Raises:
            AssertionError: If no suitable scheme is found in SCHEME_FIELD_MAP.
        """
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
        """Get the source branch URL for this pull request.

        Args:
            preferred_schemes: List of preferred URL schemes in order of preference.
                             Defaults to DEFAULT_PREFERRED_SCHEMES.

        Returns:
            The Breezy-compatible URL for the source branch.
        """
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
        """Get the target branch URL for this pull request.

        Args:
            preferred_schemes: List of preferred URL schemes in order of preference.
                             Defaults to DEFAULT_PREFERRED_SCHEMES.

        Returns:
            The Breezy-compatible URL for the target branch.
        """
        return self._branch_from_part(
            self._pr["base"], preferred_schemes=preferred_schemes
        )

    def set_target_branch_name(self, name):
        """Set the target branch name for this pull request.

        Args:
            name: The new target branch name.
        """
        self._patch(base=name)

    def get_source_project(self):
        """Get the source project name for this pull request.

        Returns:
            The full name (owner/repo) of the source repository, or None if unavailable.
        """
        if self._pr["head"]["repo"] is None:
            return None
        return self._pr["head"]["repo"]["full_name"]

    def get_target_project(self):
        """Get the target project name for this pull request.

        Returns:
            The full name (owner/repo) of the target repository, or None if unavailable.
        """
        if self._pr["base"]["repo"] is None:
            return None
        return self._pr["base"]["repo"]["full_name"]

    def get_description(self):
        """Get the description (body) of this pull request.

        Returns:
            The pull request description text.
        """
        return self._pr["body"]

    def get_commit_message(self):
        """Get the commit message for this pull request.

        GitHub doesn't support custom commit messages for pull requests,
        so this always returns None.

        Returns:
            None, as GitHub doesn't support custom commit messages.
        """
        return None

    def get_title(self):
        """Get the title of this pull request.

        Returns:
            The pull request title.
        """
        return self._pr.get("title")

    def set_title(self, title):
        """Set the title of this pull request.

        Args:
            title: The new title for the pull request.
        """
        self._patch(title=title)

    def set_commit_message(self, message):
        """Set the commit message for this pull request.

        GitHub doesn't support custom commit messages for pull requests,
        so this operation is not supported.

        Args:
            message: The commit message (ignored).

        Raises:
            UnsupportedOperation: Always raised as GitHub doesn't support this feature.
        """
        raise errors.UnsupportedOperation(self.set_commit_message, self)

    def _patch(self, **data):
        """Update this pull request with new data via GitHub's API.

        Args:
            **data: Key-value pairs of pull request fields to update.

        Raises:
            ValidationFailed: If GitHub returns a 422 status (validation error).
            UnexpectedHttpStatus: If GitHub returns an unexpected status code.
        """
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
        """Set the description (body) of this pull request.

        Args:
            description: The new description text for the pull request.
                        The title will be automatically determined from this description.
        """
        self._patch(body=description, title=determine_title(description))

    def is_merged(self):
        """Check if this pull request has been merged.

        Returns:
            True if the pull request has been merged, False otherwise.
        """
        return bool(self._pr.get("merged_at"))

    def is_closed(self):
        """Check if this pull request has been closed without merging.

        Returns:
            True if the pull request is closed but not merged, False otherwise.
        """
        return self._pr["state"] == "closed" and not bool(self._pr.get("merged_at"))

    def reopen(self):
        """Reopen this pull request if it was previously closed.

        Raises:
            ReopenFailed: If the pull request cannot be reopened.
        """
        try:
            self._patch(state="open")
        except ValidationFailed as e:
            raise ReopenFailed(e.error["errors"][0]["message"]) from e

    def close(self):
        """Close this pull request without merging it."""
        self._patch(state="closed")

    def can_be_merged(self):
        """Check if this pull request can be merged.

        Returns:
            True if the pull request is mergeable, False otherwise.
        """
        return self._pr["mergeable"]

    def merge(self, commit_message=None, auto=False):
        """Merge this pull request.

        Args:
            commit_message: Optional custom commit message for the merge.
            auto: If True, enable auto-merge instead of immediately merging.
                 Auto-merge will merge the PR automatically when all conditions are met.

        Raises:
            AutoMergeUnavailable: If auto-merge is requested but not available.
            PermissionDenied: If the user doesn't have permission to merge.
            ValidationFailed: If GitHub returns a 422 status (validation error).
            UnexpectedHttpStatus: If GitHub returns an unexpected status code.
        """
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
        """Get the username who merged this pull request.

        Returns:
            The GitHub username of the person who merged the pull request,
            or None if the pull request hasn't been merged.
        """
        merged_by = self._pr.get("merged_by")
        if merged_by is None:
            return None
        return merged_by["login"]

    def get_merged_at(self):
        """Get the timestamp when this pull request was merged.

        Returns:
            A datetime object representing when the pull request was merged,
            or None if the pull request hasn't been merged.
        """
        merged_at = self._pr.get("merged_at")
        if merged_at is None:
            return None
        return parse_timestring(merged_at)

    def post_comment(self, body):
        """Post a comment on this pull request.

        Args:
            body: The comment text to post.

        Raises:
            ValidationFailed: If GitHub returns a 422 status (validation error).
            UnexpectedHttpStatus: If GitHub returns an unexpected status code.
        """
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
    """Parse a GitHub repository URL to extract owner and repository name.

    Args:
        url: The GitHub repository URL to parse.

    Returns:
        A tuple of (owner, repo_name) extracted from the URL.

    Raises:
        NotGitHubUrl: If the URL is not a valid GitHub URL.

    Example:
        >>> parse_github_url("https://github.com/owner/repo.git")
        ('owner', 'repo')
    """
    (_scheme, _user, _password, host, _port, path) = urlutils.parse_url(url)
    if host != GITHUB_HOST:
        raise NotGitHubUrl(url)
    (owner, repo_name) = path.strip("/").split("/")
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    return owner, repo_name


def parse_github_branch_url(branch):
    """Parse a GitHub branch URL to extract owner, repository name, and branch name.

    Args:
        branch: A branch object with user_url and name attributes.

    Returns:
        A tuple of (owner, repo_name, branch_name) extracted from the branch.

    Raises:
        NotGitHubUrl: If the branch URL is not a valid GitHub URL.
    """
    url = urlutils.strip_segment_parameters(branch.user_url)
    owner, repo_name = parse_github_url(url)
    return owner, repo_name, branch.name


def parse_github_pr_url(url):
    """Parse a GitHub pull request URL to extract owner, repository name, and PR ID.

    Args:
        url: The GitHub pull request URL to parse.

    Returns:
        A tuple of (owner, repo_name, pr_id) extracted from the URL.

    Raises:
        NotGitHubUrl: If the URL is not a valid GitHub URL.
        ValueError: If the URL is not a valid pull request URL format.

    Example:
        >>> parse_github_pr_url("https://github.com/owner/repo/pull/123")
        ('owner', 'repo', '123')
    """
    (_scheme, _user, _password, host, _port, path) = urlutils.parse_url(url)
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
    """Convert a GitHub URL to a Breezy-compatible URL.

    Args:
        url: The GitHub repository URL.
        branch_name: The name of the branch.

    Returns:
        A Breezy-compatible URL for the specified branch.
    """
    return git_url_to_bzr_url(url, branch_name)


def strip_optional(url):
    """Strip optional URL template parameters from a GitHub API URL.

    GitHub API URLs often contain template parameters like {/key}.
    This function removes everything from the first '{' onward.

    Args:
        url: The URL to strip template parameters from.

    Returns:
        The URL with template parameters removed.

    Example:
        >>> strip_optional("https://api.github.com/repos/owner/repo/pulls{/number}")
        'https://api.github.com/repos/owner/repo/pulls'
    """
    return url.split("{")[0]


class _LazyDict(dict):
    """A dictionary that lazily loads additional data on first access.

    This class is used to represent GitHub API objects that have partial data
    initially but can load complete data when needed. This allows for efficient
    handling of API responses that may not contain all fields by default.
    """

    def __init__(self, base, load_fn):
        """Initialize a lazy dictionary.

        Args:
            base: The initial dictionary data.
            load_fn: A callable that returns additional data to load.
        """
        self._load_fn = load_fn
        super().update(base)

    def _load_full(self):
        """Load the full data set and disable further lazy loading."""
        super().update(self._load_fn())
        self._load_fn = None

    def __getitem__(self, key):
        """Get an item, loading full data if the key is not found initially.

        Args:
            key: The dictionary key to retrieve.

        Returns:
            The value associated with the key.

        Raises:
            KeyError: If the key is not found even after loading full data.
        """
        if self._load_fn is not None:
            try:
                return super().__getitem__(key)
            except KeyError:
                self._load_full()
        return super().__getitem__(key)

    def items(self):
        """Return dictionary items, ensuring full data is loaded first.

        Returns:
            A view of the dictionary's key-value pairs.
        """
        self._load_full()
        return super().items()

    def keys(self):
        """Return dictionary keys, ensuring full data is loaded first.

        Returns:
            A view of the dictionary's keys.
        """
        self._load_full()
        return super().keys()

    def values(self):
        """Return dictionary values, ensuring full data is loaded first.

        Returns:
            A view of the dictionary's values.
        """
        self._load_full()
        return super().values()

    def __contains__(self, key):
        """Check if a key exists, loading full data if not found initially.

        Args:
            key: The key to check for.

        Returns:
            True if the key exists, False otherwise.
        """
        if super().__contains__(key):
            return True
        if self._load_fn is not None:
            self._load_full()
            return super().__contains__(key)
        return False

    def __delitem__(self, name):
        """Delete an item from the dictionary.

        This operation is not supported for lazy dictionaries.

        Raises:
            NotImplementedError: Always raised as deletion is not supported.
        """
        raise NotImplementedError

    def __setitem__(self, name, value):
        """Set an item in the dictionary.

        This operation is not supported for lazy dictionaries.

        Raises:
            NotImplementedError: Always raised as item assignment is not supported.
        """
        raise NotImplementedError

    def get(self, name, default=None):
        """Get a value with a default, loading full data if key not found initially.

        Args:
            name: The key to retrieve.
            default: The default value if the key is not found.

        Returns:
            The value associated with the key, or the default value.
        """
        if self._load_fn is not None:
            try:
                return super().get(name, default)
            except KeyError:
                self._load_full()
        return super().get(name, default)

    def pop(self):
        """Remove and return an item from the dictionary.

        This operation is not supported for lazy dictionaries.

        Raises:
            NotImplementedError: Always raised as pop is not supported.
        """
        raise NotImplementedError

    def popitem(self):
        """Remove and return an arbitrary key-value pair from the dictionary.

        This operation is not supported for lazy dictionaries.

        Raises:
            NotImplementedError: Always raised as popitem is not supported.
        """
        raise NotImplementedError

    def clear(self):
        """Remove all items from the dictionary.

        This operation is not supported for lazy dictionaries.

        Raises:
            NotImplementedError: Always raised as clear is not supported.
        """
        raise NotImplementedError


class GraphqlErrors(Exception):
    """Exception raised when GitHub GraphQL API returns errors.

    This exception is used to encapsulate GraphQL-specific errors
    returned by GitHub's GraphQL API.
    """

    def __init__(self, errors):
        """Initialize the GraphqlErrors exception.

        Args:
            errors: A list of error objects from the GraphQL API response.
        """
        self.errors = errors


class GitHub(Forge):
    """GitHub forge implementation for Breezy.

    This class provides integration with GitHub's API, allowing Breezy to interact
    with GitHub repositories, pull requests, and other GitHub-specific features.

    Attributes:
        name: The name identifier for this forge type.
        supports_merge_proposal_labels: Indicates support for pull request labels.
        supports_merge_proposal_commit_message: Indicates if custom commit messages are supported.
        supports_merge_proposal_title: Indicates support for pull request titles.
        supports_allow_collaboration: Indicates support for maintainer collaboration.
        merge_proposal_description_format: The format used for pull request descriptions.
    """

    name = "github"

    supports_merge_proposal_labels = True
    supports_merge_proposal_commit_message = False
    supports_merge_proposal_title = True
    supports_allow_collaboration = True
    merge_proposal_description_format = "markdown"

    def __repr__(self):
        """Return a string representation of the GitHub forge.

        Returns:
            A string representation of this GitHub forge instance.
        """
        return "GitHub()"

    def _graphql_request(self, body, **kwargs):
        """Make a GraphQL request to GitHub's API.

        Args:
            body: The GraphQL query string.
            **kwargs: Variables to include in the GraphQL request.

        Returns:
            The 'data' portion of the GraphQL response.

        Raises:
            UnexpectedHttpStatus: If the request returns a non-200 status.
            GraphqlErrors: If the GraphQL response contains errors.
        """
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
        """Make a REST API request to GitHub's API.

        Args:
            method: The HTTP method (GET, POST, PATCH, DELETE, etc.).
            path: The API path relative to the base API URL.
            body: Optional request body data.

        Returns:
            The HTTP response object.

        Raises:
            GitHubLoginRequired: If the request requires authentication and
                               the user is not logged in or token is invalid.
            UnexpectedHttpStatus: For other HTTP errors.
        """
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
        """Get repository information from GitHub's API.

        Args:
            owner: The repository owner (user or organization).
            repo: The repository name.

        Returns:
            A dictionary containing the repository information from GitHub's API.

        Raises:
            NoSuchProject: If the repository doesn't exist or is not accessible.
            UnexpectedHttpStatus: For other HTTP errors.
        """
        path = f"repos/{owner}/{repo}"
        response = self._api_request("GET", path)
        if response.status == 404:
            raise NoSuchProject(path)
        if response.status == 200:
            return json.loads(response.text)
        raise UnexpectedHttpStatus(path, response.status, headers=response.getheaders())

    def _get_repo_pulls(self, path, head=None, state=None):
        """Get pull requests for a repository.

        Args:
            path: The API path for the repository's pulls endpoint.
            head: Optional filter by head branch name.
            state: Optional filter by pull request state (open, closed, all).

        Returns:
            A list of pull request objects from GitHub's API.

        Raises:
            NoSuchProject: If the repository doesn't exist or is not accessible.
            UnexpectedHttpStatus: For other HTTP errors.
        """
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
        """Create a new pull request via GitHub's API.

        Args:
            path: The API endpoint path for creating the pull request.
            title: The pull request title.
            head: The head branch (source) in format 'owner:branch'.
            base: The base branch (target) name.
            body: Optional pull request description.
            labels: Optional list of label names to apply.
            assignee: Optional username to assign the pull request to.
            draft: Whether to create as a draft pull request.
            maintainer_can_modify: Whether to allow maintainer modifications.

        Returns:
            A dictionary containing the created pull request data from GitHub's API.

        Raises:
            PermissionDenied: If the user lacks permission to create the pull request.
            ValidationFailed: If GitHub returns validation errors.
            UnexpectedHttpStatus: For other HTTP errors.
        """
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
        """Find a GitHub user by their email address.

        Args:
            email: The email address to search for.

        Returns:
            A dictionary containing user information from GitHub's API.

        Raises:
            KeyError: If no user is found with the given email.
            ValueError: If multiple users are found with the same email.
            UnexpectedHttpStatus: If the API request fails.
        """
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
        """Get user information from GitHub's API.

        Args:
            username: Optional username. If None, gets the authenticated user's info.

        Returns:
            A dictionary containing user information from GitHub's API.

        Raises:
            UnexpectedHttpStatus: If the API request fails.
        """
        path = f"users/{username}" if username else "user"
        response = self._api_request("GET", path)
        if response.status != 200:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    def _get_organization(self, name):
        """Get organization information from GitHub's API.

        Args:
            name: The organization name.

        Returns:
            A dictionary containing organization information from GitHub's API.

        Raises:
            UnexpectedHttpStatus: If the API request fails.
        """
        path = f"orgs/{name}"
        response = self._api_request("GET", path)
        if response.status != 200:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    def _list_paged(self, path, parameters=None, per_page=None):
        """Make paginated requests to GitHub's API.

        Args:
            path: The API endpoint path.
            parameters: Optional dictionary of query parameters.
            per_page: Optional number of items per page.

        Yields:
            Each page of results as returned by GitHub's API.

        Raises:
            UnexpectedHttpStatus: If any API request fails.
        """
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
        """Search for issues/pull requests using GitHub's search API.

        Args:
            query: The search query string.

        Yields:
            Individual issue/pull request objects from the search results.
        """
        path = "search/issues"
        for page in self._list_paged(path, {"q": query}, per_page=DEFAULT_PER_PAGE):
            if not page["items"]:
                break
            yield from page["items"]

    def _create_fork(self, path, owner=None):
        """Create a fork of a repository.

        Args:
            path: The API endpoint path for creating the fork.
            owner: Optional organization to create the fork under.
                  If None, creates under the current user.

        Returns:
            A dictionary containing the created fork information from GitHub's API.

        Raises:
            UnexpectedHttpStatus: If the API request fails.
        """
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
        """The base web URL for GitHub.

        Returns:
            The GitHub web URL (https://github.com).
        """
        return WEB_GITHUB_URL

    def __init__(self, transport):
        """Initialize the GitHub forge.

        Args:
            transport: The transport object for making HTTP requests to GitHub's API.
        """
        self._token = retrieve_github_token()
        if self._token is None:
            note("Accessing GitHub anonymously. To log in, run 'brz gh-login'.")
        self.transport = transport
        self._current_user = None

    @property
    def current_user(self):
        """Get information about the currently authenticated user.

        Returns:
            A dictionary containing the current user's information from GitHub's API.
            The result is cached after the first request.
        """
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
        """Publish a derived branch to GitHub, creating a fork if necessary.

        Args:
            local_branch: The local branch to publish.
            base_branch: The base branch this is derived from.
            name: The name for the published branch.
            project: Optional project name. If None, uses the base project name.
            owner: Optional owner. If None, uses the current user.
            revision_id: Optional specific revision to publish.
            overwrite: Whether to overwrite the remote branch if it exists.
            allow_lossy: Whether to allow lossy pushes if roundtrip fails.
            tag_selector: Optional function to select which tags to push.

        Returns:
            A tuple of (remote_branch, public_branch_url) for the published branch.

        Raises:
            NoRoundtrippingSupport: If lossy pushing is needed but not allowed.
        """
        if tag_selector is None:

            def tag_selector(t):
                return False

        base_owner, base_project, _base_branch_name = parse_github_branch_url(
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
        """Get the push URL for a branch.

        Args:
            branch: A branch object to get the push URL for.

        Returns:
            The SSH URL suitable for pushing to the branch.
        """
        owner, project, branch_name = parse_github_branch_url(branch)
        repo = self._get_repo(owner, project)
        return github_url_to_bzr_url(repo["ssh_url"], branch_name)

    def get_web_url(self, branch):
        """Get the web URL for a branch.

        Args:
            branch: A branch object to get the web URL for.

        Returns:
            The GitHub web URL for viewing the branch or repository.
        """
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
        """Get a derived branch from a GitHub repository.

        Args:
            base_branch: The base branch to derive from.
            name: The derived branch name.
            project: Optional project name. If None, uses the base project name.
            owner: Optional owner. If None, uses the current user.
            preferred_schemes: Optional list of preferred URL schemes.

        Returns:
            A Branch object for the derived branch.

        Raises:
            NotBranchError: If the derived repository doesn't exist.
        """
        base_owner, base_project, _base_branch_name = parse_github_branch_url(
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
        """Get a merge proposal builder for creating pull requests.

        Args:
            source_branch: The source branch for the merge proposal.
            target_branch: The target branch for the merge proposal.

        Returns:
            A GitHubMergeProposalBuilder instance for creating pull requests.
        """
        return GitHubMergeProposalBuilder(self, source_branch, target_branch)

    def iter_proposals(self, source_branch, target_branch, status="open"):
        """Iterate over pull requests between specific source and target branches.

        Args:
            source_branch: The source branch to filter by.
            target_branch: The target branch to filter by.
            status: The status filter ('open', 'closed', 'merged', or 'all').

        Yields:
            GitHubMergeProposal instances matching the criteria.
        """
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
            if (status == "closed" and pull["merged"]) or (
                status == "merged" and not pull["merged"]
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
        """Check if this forge hosts the given branch.

        Args:
            branch: A branch object to check.

        Returns:
            True if this GitHub forge hosts the branch, False otherwise.
        """
        try:
            parse_github_branch_url(branch)
        except NotGitHubUrl:
            return False
        else:
            return True

    @classmethod
    def probe_from_hostname(cls, hostname, possible_transports=None):
        """Probe for GitHub forge support based on hostname.

        Args:
            hostname: The hostname to check for GitHub support.
            possible_transports: Optional list of existing transports to reuse.

        Returns:
            A GitHub forge instance if the hostname is GitHub.

        Raises:
            UnsupportedForge: If the hostname is not GitHub.
        """
        if hostname == GITHUB_HOST:
            transport = get_transport(
                API_GITHUB_URL, possible_transports=possible_transports
            )
            return cls(transport)
        raise UnsupportedForge(hostname)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        """Probe for GitHub forge support based on URL.

        Args:
            url: The URL to check for GitHub support.
            possible_transports: Optional list of existing transports to reuse.

        Returns:
            A GitHub forge instance if the URL is a GitHub URL.

        Raises:
            UnsupportedForge: If the URL is not a GitHub URL.
        """
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
        """Iterate over available GitHub forge instances.

        Yields:
            GitHub forge instances. Only yields the main github.com instance.
        """
        yield cls(get_transport(API_GITHUB_URL))

    def iter_my_proposals(self, status="open", author=None):
        """Iterate over pull requests authored by a user.

        Args:
            status: The status filter ('open', 'closed', 'merged', or 'all').
            author: Optional author username. If None, uses the current authenticated user.

        Yields:
            GitHubMergeProposal instances representing the user's pull requests.
        """
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
                """Lazy loader function to retrieve full pull request data.

                Returns:
                    Complete pull request data from GitHub's API.

                Raises:
                    UnexpectedHttpStatus: If the API request fails.
                """
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
        """Get a merge proposal by its GitHub URL.

        Args:
            url: The GitHub pull request URL.

        Returns:
            A GitHubMergeProposal instance representing the pull request.

        Raises:
            UnsupportedForge: If the URL is not a GitHub pull request URL.
            UnexpectedHttpStatus: If the API request fails.
        """
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
        """Iterate over repositories that are forks owned by a user.

        Args:
            owner: The owner username. If None, uses the current authenticated user.

        Yields:
            Full repository names (owner/repo) of repositories that are forks.
        """
        path = f"/users/{owner}/repos" if owner else "/user/repos"
        for page in self._list_paged(path, per_page=DEFAULT_PER_PAGE):
            for project in page:
                if not project["fork"]:
                    continue
                yield project["full_name"]

    def delete_project(self, path):
        """Delete a GitHub repository.

        Args:
            path: The repository path in format 'owner/repo'.

        Returns:
            None for successful deletion (204), or parsed JSON for 200 responses.

        Raises:
            NoSuchProject: If the repository doesn't exist.
            UnexpectedHttpStatus: For other HTTP errors.
        """
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
        """Create a new GitHub repository.

        Args:
            path: The repository path in format 'owner/repo'.
            homepage: Optional homepage URL for the repository.
            private: Whether to create a private repository.
            has_issues: Whether to enable the issues feature.
            has_projects: Whether to enable the projects feature.
            has_wiki: Whether to enable the wiki feature.
            summary: Optional repository description.

        Returns:
            A dictionary containing the created repository information for non-201 responses.

        Raises:
            UnexpectedHttpStatus: If the API request fails with an unexpected status.
        """
        _owner, _name = path.split("/")
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
        """Get the username of the currently authenticated user.

        Returns:
            The GitHub username of the authenticated user, or None if not authenticated.
        """
        if self._token is not None:
            return self.current_user["login"]
        return None

    def get_user_url(self, username):
        """Get the web URL for a GitHub user profile.

        Args:
            username: The GitHub username.

        Returns:
            The GitHub web URL for the user's profile page.
        """
        return urlutils.join(self.base_url, username)


class GitHubMergeProposalBuilder(MergeProposalBuilder):
    """Builder for creating GitHub pull requests (merge proposals).

    This class handles the creation of pull requests on GitHub by gathering
    the necessary information and making the appropriate API calls.
    """

    def __init__(self, gh, source_branch, target_branch):
        """Initialize the merge proposal builder.

        Args:
            gh: The GitHub forge instance.
            source_branch: The source branch for the pull request.
            target_branch: The target branch for the pull request.
        """
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
        """Determine the initial comment for the merge proposal.

        Returns:
            A string containing information about the source and target branches.
        """
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

        Returns:
            A str or None. GitHub doesn't provide a default body template,
            so this always returns None.
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
        delete_source_after_merge: bool | None = None,
    ):
        """Create a pull request on GitHub.

        Args:
            description: The pull request description/body.
            title: Optional custom title. If None, determined from description.
            reviewers: Optional list of reviewer usernames or email addresses.
            labels: Optional list of label names to apply to the pull request.
            prerequisite_branch: Not supported by GitHub (raises PrerequisiteBranchUnsupported).
            commit_message: Ignored (GitHub doesn't support custom commit messages).
            work_in_progress: Whether to create as a draft pull request.
            allow_collaboration: Whether to allow maintainer modifications.
            delete_source_after_merge: Whether to delete the source branch after merge.

        Returns:
            A GitHubMergeProposal instance representing the created pull request.

        Raises:
            PrerequisiteBranchUnsupported: If prerequisite_branch is provided.
            MergeProposalExists: If a pull request already exists for these branches.
            ValidationFailed: If GitHub returns validation errors.
        """
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        # Note that commit_message is ignored, since github doesn't support it.
        # TODO(jelmer): Probe for right repo name
        if self.target_repo_name.endswith(".git"):
            self.target_repo_name = self.target_repo_name[:-4]
        if title is None:
            title = determine_title(description)
        target_repo = self.gh._get_repo(self.target_owner, self.target_repo_name)
        assignees: list[dict[str, Any]] | None = []
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
        kwargs: dict[str, Any] = {}
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
