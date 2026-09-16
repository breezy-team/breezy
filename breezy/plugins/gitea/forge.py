# Copyright (C) 2026 Breezy Developers
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

"""Support for Gitea."""

import json
import os
from datetime import datetime
from typing import Any

from dromedary.errors import (
    ConnectionError as TransportConnectionError,
)
from dromedary.errors import (
    PermissionDenied,
    UnexpectedHttpStatus,
)

from ... import bedding, controldir, errors, urlutils
from ... import branch as _mod_branch
from ...config import AuthenticationConfig
from ...forge import (
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

API_PATH = "api/v1/"
DEFAULT_PER_PAGE = 50

SCHEME_FIELD_MAP = {
    "ssh": "ssh_url",
    "git+ssh": "ssh_url",
    "http": "clone_url",
    "https": "clone_url",
}
DEFAULT_PREFERRED_SCHEMES = ["ssh", "http"]


def parse_timestring(ts):
    """Parse a Gitea timestamp string into a datetime object.

    Args:
        ts: A timestamp string in Gitea's ISO 8601 format
            (YYYY-MM-DDTHH:MM:SSZ or with a UTC offset).

    Returns:
        A datetime object representing the parsed timestamp.

    Example:
        >>> parse_timestring("2023-01-15T10:30:45Z")
        datetime.datetime(2023, 1, 15, 10, 30, 45)
    """
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def store_gitea_token(name, url, private_token):
    """Store a Gitea personal access token in the authentication configuration.

    Args:
        name: The configuration name/identifier for this token.
        url: The base URL of the Gitea instance.
        private_token: The Gitea personal access token to store.
    """
    (scheme, _user, _password, host, _port, _path) = urlutils.parse_url(url)
    auth_config = AuthenticationConfig()
    auth_config._set_option(name, "url", url)
    auth_config._set_option(name, "forge", "gitea")
    auth_config._set_option(name, "scheme", scheme or "https")
    if host:
        auth_config._set_option(name, "host", host)
    auth_config._set_option(name, "token", private_token)
    auth_config._set_option(name, "private_token", private_token)


def iter_tokens():
    """Iterate over all available Gitea tokens from configuration files.

    This function searches for Gitea credentials in multiple configuration
    sources:
    1. Legacy gitea.conf in the Breezy config directory
    2. Breezy authentication configuration with forge="gitea"

    Yields:
        tuple: A (name, credentials) tuple where name is the configuration
               name and credentials is a dict containing 'url' and other
               credential fields.
    """
    import configparser

    config = configparser.ConfigParser()
    config.read([os.path.join(bedding.config_dir(), "gitea.conf")])
    for name, creds in config.items():
        if "url" not in creds:
            continue
        yield name, creds

    auth_config = AuthenticationConfig()
    for name, creds in auth_config._get_config().iteritems():
        if creds.get("forge") == "gitea":
            yield name, creds


def get_credentials_by_hostname(hostname):
    """Find Gitea credentials for a specific hostname.

    Matching is done on the hostname alone, without assuming a scheme or
    port, since self-hosted Gitea instances are commonly reached over
    plain http and/or a non-standard port.

    Args:
        hostname: The hostname to find credentials for.

    Returns:
        A dictionary containing the credentials for the hostname, or None
        if not found.
    """
    for _name, credentials in iter_tokens():
        (_scheme, _user, _password, host, _port, _path) = urlutils.parse_url(
            credentials["url"]
        )
        if host == hostname:
            return credentials
    return None


class NotGiteaUrl(errors.BzrError):
    """Exception raised when a URL is not recognized as a Gitea URL.

    Raised by parse_gitea_url and parse_gitea_pr_url when the URL's scheme
    isn't one of git+ssh, https or http, when the URL has no host, or when
    its path doesn't split into an owner and a repository name.
    """

    _fmt = "Not a Gitea URL: %(url)s"

    def __init__(self, url):
        """Initialize the NotGiteaUrl exception.

        Args:
            url: The URL that was not recognized as a Gitea URL.
        """
        errors.BzrError.__init__(self)
        self.url = url


class NotMergeRequestUrl(errors.BzrError):
    """Exception raised when a URL is not a valid Gitea pull request URL.

    Raised by parse_gitea_pr_url when the URL passes the general Gitea URL
    checks but its path doesn't match the owner/repo/pulls/number shape
    Gitea uses for pull request URLs.
    """

    _fmt = "Not a Gitea merge request URL: %(host)s, %(url)s"

    def __init__(self, host, url):
        """Initialize the NotMergeRequestUrl exception.

        Args:
            host: The Gitea instance hostname.
            url: The URL that was not recognized as a pull request URL.
        """
        errors.BzrError.__init__(self)
        self.host = host
        self.url = url


class ValidationFailed(errors.BzrError):
    """Exception raised when Gitea API validation fails.

    Raised when Gitea returns a 422 status code, indicating that the
    request was well-formed but contained invalid data or parameters,
    or a 412 status code, indicating that a state change was rejected
    given the pull request's current state (for example, reopening a
    pull request that has already been merged).
    """

    _fmt = "Gitea validation failed: %(error)s"

    def __init__(self, error):
        """Initialize the ValidationFailed exception.

        Args:
            error: The validation error details from Gitea's API response.
        """
        errors.BzrError.__init__(self)
        self.error = error


class GiteaLoginRequired(ForgeLoginRequired):
    """Exception raised when a Gitea operation requires authentication.

    Raised by Gitea._api_request when a request comes back with a 401
    response, either because no token was supplied or because the stored
    token has been revoked or expired.
    """

    _fmt = "Action requires Gitea login at %(forge)s."


def parse_gitea_url(url):
    """Parse a Gitea repository URL to extract hostname, owner, and repository name.

    Args:
        url: The Gitea repository URL to parse.

    Returns:
        A tuple of (host, owner, repo_name) extracted from the URL.

    Raises:
        NotGiteaUrl: If the URL is not a valid Gitea URL.

    Example:
        >>> parse_gitea_url("https://gitea.example.com/owner/repo.git")
        ('gitea.example.com', 'owner', 'repo')
    """
    (scheme, _user, _password, host, _port, path) = urlutils.parse_url(url)
    if scheme not in ("git+ssh", "https", "http"):
        raise NotGiteaUrl(url)
    if not host:
        raise NotGiteaUrl(url)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    try:
        (owner, repo_name) = path.split("/")
    except ValueError as e:
        raise NotGiteaUrl(url) from e
    return host, owner, repo_name


def parse_gitea_branch_url(branch):
    """Parse a Gitea branch URL to extract hostname, owner, repository name, and branch name.

    Args:
        branch: A branch object with user_url and name attributes.

    Returns:
        A tuple of (host, owner, repo_name, branch_name) extracted from the branch.

    Raises:
        NotGiteaUrl: If the branch URL is not a valid Gitea URL.
    """
    url = urlutils.strip_segment_parameters(branch.user_url)
    host, owner, repo_name = parse_gitea_url(url)
    return host, owner, repo_name, branch.name


def parse_gitea_pr_url(url):
    """Parse a Gitea pull request URL to extract hostname, owner, repository name, and PR number.

    Args:
        url: The Gitea pull request URL to parse.

    Returns:
        A tuple of (host, owner, repo_name, pr_number) extracted from the URL.

    Raises:
        NotGiteaUrl: If the URL is not a valid Gitea URL.
        NotMergeRequestUrl: If the URL is not a valid pull request URL.

    Example:
        >>> parse_gitea_pr_url("https://gitea.example.com/owner/repo/pulls/123")
        ('gitea.example.com', 'owner', 'repo', 123)
    """
    (scheme, _user, _password, host, _port, path) = urlutils.parse_url(url)
    if scheme not in ("git+ssh", "https", "http"):
        raise NotGiteaUrl(url)
    if not host:
        raise NotGiteaUrl(url)
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[2] != "pulls":
        raise NotMergeRequestUrl(host, url)
    (owner, repo_name, _pulls, pr_number) = parts
    return host, owner, repo_name, int(pr_number)


def gitea_url_to_bzr_url(url, branch_name):
    """Convert a Gitea repository URL to a Breezy-compatible URL.

    Args:
        url: The Gitea repository URL.
        branch_name: The name of the branch.

    Returns:
        A Breezy-compatible URL for the specified branch.
    """
    return git_url_to_bzr_url(url, branch_name)


def status_to_gitea_state(status):
    """Convert a merge proposal status to a Gitea pull request state.

    Args:
        status: A status string from the common forge API ("all", "open", "merged", "closed")

    Returns:
        The corresponding Gitea pull request state string

    Raises:
        KeyError: If the status is not recognized
    """
    return {"open": "open", "merged": "closed", "closed": "closed", "all": "all"}[
        status
    ]


class GiteaMergeProposal(MergeProposal):
    """Represents a Gitea pull request as a merge proposal.

    This class wraps Gitea's pull request API and provides a consistent
    interface for interacting with merge proposals across different forges.

    Attributes:
        supports_auto_merge: Gitea's merge endpoint accepts a
            ``merge_when_checks_succeed`` flag that schedules the merge
            once checks pass, so this is always True.
        name: The display name for this forge type.
    """

    supports_auto_merge = True

    def __init__(self, gt, pr):
        """Initialize a GiteaMergeProposal.

        Args:
            gt: The Gitea forge instance.
            pr: The pull request data from Gitea's API.
        """
        self._gt = gt
        self._pr = pr

    def __repr__(self):
        """Return a string representation of the merge proposal."""
        return f"<{type(self).__name__} at {self.url!r}>"

    name = "Gitea"

    def get_web_url(self):
        """Get the web URL for this pull request.

        Returns:
            The Gitea web URL where users can view the pull request.
        """
        return self._pr["html_url"]

    @property
    def url(self):
        """The web URL for this pull request.

        Returns:
            The Gitea web URL where users can view the pull request.
        """
        return self._pr["html_url"]

    def _branch_from_part(self, part, preferred_schemes=None):
        """Convert a Gitea pull request head/base part to a Breezy branch URL.

        Args:
            part: A Gitea pull request head or base section containing repo
                and ref info.
            preferred_schemes: List of preferred URL schemes in order of
                preference. Defaults to DEFAULT_PREFERRED_SCHEMES.

        Returns:
            A Breezy-compatible branch URL, or None if the repo is None.
        """
        if part.get("repo") is None:
            return None
        if preferred_schemes is None:
            preferred_schemes = DEFAULT_PREFERRED_SCHEMES
        for scheme in preferred_schemes:
            if scheme in SCHEME_FIELD_MAP:
                return gitea_url_to_bzr_url(
                    part["repo"][SCHEME_FIELD_MAP[scheme]], part["ref"]
                )
        raise AssertionError

    def get_source_branch_url(self, *, preferred_schemes=None):
        """Get the source branch URL for this pull request.

        Args:
            preferred_schemes: List of preferred URL schemes in order of
                preference. Defaults to DEFAULT_PREFERRED_SCHEMES.

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
            preferred_schemes: List of preferred URL schemes in order of
                preference. Defaults to DEFAULT_PREFERRED_SCHEMES.

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
        """Get the source project name for this pull request."""
        if self._pr["head"].get("repo") is None:
            return None
        return self._pr["head"]["repo"]["full_name"]

    def get_target_project(self):
        """Get the target project name for this pull request."""
        if self._pr["base"].get("repo") is None:
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

        Gitea doesn't support custom commit messages for pull requests, so
        this always returns None.
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

        Gitea doesn't support custom commit messages for pull requests, so
        this operation is not supported.
        """
        raise errors.UnsupportedOperation(self.set_commit_message, self)

    def _patch(self, **data):
        """Update this pull request with new data via Gitea's API.

        Args:
            **data: Key-value pairs of pull request fields to update.
        """
        path = (
            f"repos/{self._pr['base']['repo']['full_name']}/pulls/{self._pr['number']}"
        )
        response = self._gt._api_request(
            "PATCH", path, body=json.dumps(data).encode("utf-8")
        )
        if response.status in (412, 422):
            raise ValidationFailed(json.loads(response.text))
        if response.status != 201:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        self._pr = json.loads(response.text)

    def set_description(self, description):
        """Set the description (body) of this pull request."""
        self._patch(body=description, title=determine_title(description))

    def is_merged(self):
        """Check if this pull request has been merged.

        Returns:
            True if the pull request has been merged, False otherwise.
        """
        return bool(self._pr.get("merged"))

    def is_closed(self):
        """Check if this pull request has been closed without merging.

        Returns:
            True if the pull request is closed but not merged, False otherwise.
        """
        return self._pr["state"] == "closed" and not bool(self._pr.get("merged"))

    def reopen(self):
        """Reopen this pull request if it was previously closed."""
        try:
            self._patch(state="open")
        except ValidationFailed as e:
            raise ReopenFailed(str(e.error)) from e

    def close(self):
        """Close this pull request without merging it."""
        self._patch(state="closed")

    def can_be_merged(self):
        """Check if this pull request can be merged.

        Returns:
            True if the pull request is mergeable, False otherwise.
        """
        return bool(self._pr.get("mergeable"))

    def merge(self, commit_message=None, auto=False):
        """Merge this pull request.

        Args:
            commit_message: Optional custom commit message for the merge.
            auto: If True, schedule the merge to happen automatically once
                checks succeed, via Gitea's merge_when_checks_succeed flag,
                instead of merging immediately.

        Raises:
            ValidationFailed: If Gitea rejects the (scheduled) merge.
        """
        path = (
            f"repos/{self._pr['base']['repo']['full_name']}"
            f"/pulls/{self._pr['number']}/merge"
        )
        data = {"Do": "merge"}
        if commit_message:
            data["MergeMessageField"] = commit_message
        if auto:
            data["merge_when_checks_succeed"] = True
        response = self._gt._api_request(
            "POST", path, body=json.dumps(data).encode("utf-8")
        )
        if response.status == 405:
            raise ValidationFailed(json.loads(response.text))
        if response.status != 200:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        # Merge response carries no PR body, so re-fetch for is_merged()/is_closed().
        pr_path = (
            f"repos/{self._pr['base']['repo']['full_name']}/pulls/{self._pr['number']}"
        )
        refreshed = self._gt._api_request("GET", pr_path)
        self._pr = json.loads(refreshed.text)

    def get_merged_by(self):
        """Get the username who merged this pull request.

        Returns:
            The Gitea username of the person who merged the pull request,
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

        Gitea pull requests are backed by issues, so comments are posted
        through the issue comments endpoint.

        Args:
            body: The comment text to post.
        """
        path = (
            f"repos/{self._pr['base']['repo']['full_name']}"
            f"/issues/{self._pr['number']}/comments"
        )
        data = {"body": body}
        response = self._gt._api_request(
            "POST", path, body=json.dumps(data).encode("utf-8")
        )
        if response.status == 422:
            raise ValidationFailed(json.loads(response.text))
        if response.status != 201:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )


class Gitea(Forge):
    """Gitea forge implementation for Breezy."""

    supports_merge_proposal_labels = True
    supports_merge_proposal_commit_message = False
    supports_merge_proposal_title = True
    supports_allow_collaboration = True
    merge_proposal_description_format = "markdown"

    def __repr__(self):
        """Return a string representation of the Gitea forge."""
        return f"<Gitea({self.base_url!r})>"

    def __init__(self, transport, base_url, private_token=None):
        """Initialize the Gitea forge.

        Args:
            transport: The transport object for making HTTP requests to the
                instance's API (rooted at ``<base_url>/api/v1/``).
            base_url: The web-facing base URL of the Gitea instance, e.g.
                ``https://gitea.example.com/``.
            private_token: Optional personal access token to authenticate
                with.
        """
        self.transport = transport
        self._base_url = base_url.rstrip("/") + "/"
        self._token = private_token
        if self._token is None:
            note(
                gettext(
                    "Accessing %s anonymously. To log in, run 'brz gitea-login %s'."
                )
                % (self._base_url, self._base_url)
            )
        self._current_user = None

    @property
    def base_url(self):
        """The base web URL for this Gitea instance."""
        return self._base_url

    def _api_request(self, method, path, body=None):
        """Make a REST API request to this Gitea instance.

        Args:
            method: The HTTP method (GET, POST, PATCH, DELETE, etc.).
            path: The API path relative to the instance's API root.
            body: Optional request body data.

        Returns:
            The HTTP response object.

        Raises:
            GiteaLoginRequired: If the request requires authentication and
                the user is not logged in or the token is invalid.
        """
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
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
                raise GiteaLoginRequired(self.base_url) from e
            raise
        if response.status == 401:
            raise GiteaLoginRequired(self.base_url)
        return response

    def _get_repo(self, owner, repo):
        """Get repository information from Gitea's API.

        Args:
            owner: The repository owner (user or organization).
            repo: The repository name.

        Returns:
            A dictionary containing the repository information.

        Raises:
            NoSuchProject: If the repository doesn't exist or isn't accessible.
            UnexpectedHttpStatus: For other HTTP errors.
        """
        path = f"repos/{owner}/{repo}"
        response = self._api_request("GET", path)
        if response.status == 404:
            raise NoSuchProject(path)
        if response.status == 200:
            return json.loads(response.text)
        raise UnexpectedHttpStatus(path, response.status, headers=response.getheaders())

    def _get_repo_pulls(self, owner, repo, state=None, base_branch=None):
        """Get pull requests for a repository.

        Args:
            owner: The repository owner.
            repo: The repository name.
            state: Optional filter by pull request state (open, closed, all).
            base_branch: Optional target branch name to filter by
                server-side, narrowing the result set before pagination.

        Yields:
            Pull request objects, paged through Gitea's page/limit query
            parameters until an empty page is returned.

        Raises:
            NoSuchProject: If the repository doesn't exist or isn't accessible.
            UnexpectedHttpStatus: For other HTTP errors.
        """
        path = f"repos/{owner}/{repo}/pulls"
        params = {}
        if state is not None:
            params["state"] = state
        if base_branch is not None:
            params["base_branch"] = base_branch
        try:
            for page in self._list_paged(path, params, per_page=DEFAULT_PER_PAGE):
                yield from page
        except UnexpectedHttpStatus as e:
            if e.code == 404:
                raise NoSuchProject(path) from e
            raise

    def _create_pull(
        self,
        owner,
        repo,
        title,
        head,
        base,
        body=None,
        labels=None,
        assignees=None,
        reviewers=None,
        draft=False,
        allow_maintainer_edit=False,
    ):
        """Create a new pull request via Gitea's API.

        Args:
            owner: The target repository owner.
            repo: The target repository name.
            title: The pull request title.
            head: The head branch, either ``branch`` or ``owner:branch`` if
                the source lives in a fork.
            base: The base branch (target) name.
            body: Optional pull request description.
            labels: Optional list of numeric label IDs to apply.
            assignees: Optional list of usernames to assign.
            reviewers: Optional list of usernames to request review from.
            draft: Whether to create as a draft pull request.
            allow_maintainer_edit: Whether to allow maintainer modifications.

        Returns:
            A dictionary containing the created pull request data.

        Raises:
            PermissionDenied: If the user lacks permission to create the PR.
            ValidationFailed: If Gitea returns validation errors, or a pull
                request already exists for the same head/base pair (Gitea
                returns 409 for that case, not 422, but both map to this
                same exception since create_proposal translates it to
                MergeProposalExists either way).
        """
        path = f"repos/{owner}/{repo}/pulls"
        data: dict[str, Any] = {
            "title": title,
            "head": head,
            "base": base,
            "allow_maintainer_edit": allow_maintainer_edit,
        }
        if labels:
            data["labels"] = labels
        if assignees:
            data["assignees"] = assignees
        if reviewers:
            data["reviewers"] = reviewers
        if body:
            data["body"] = body
        # No draft flag on creation; Gitea signals draft via a "WIP:" title
        # prefix, like its own web UI.
        if draft and not data["title"].startswith("WIP:"):
            data["title"] = "WIP: " + data["title"]
        response = self._api_request(
            "POST", path, body=json.dumps(data).encode("utf-8")
        )
        if response.status == 403:
            raise PermissionDenied(path, response.text)
        if response.status in (409, 422):
            raise ValidationFailed(json.loads(response.text))
        if response.status != 201:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    def _get_user(self, username=None):
        """Get user information from Gitea's API.

        Args:
            username: Optional username. If None, gets the authenticated
                user's info.

        Returns:
            A dictionary containing user information.

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

    def _list_paged(self, path, parameters=None, per_page=None):
        """Make paginated requests to Gitea's API.

        Args:
            path: The API endpoint path.
            parameters: Optional dictionary of query parameters.
            per_page: Optional number of items per page.

        Yields:
            Each page of results.

        Raises:
            UnexpectedHttpStatus: If any API request fails.
        """
        parameters = {} if parameters is None else dict(parameters.items())
        if per_page:
            parameters["limit"] = str(per_page)
        page = 1
        while path:
            parameters["page"] = str(page)
            response = self._api_request(
                "GET",
                path
                + "?"
                + "&".join(f"{k}={urlutils.quote(v)}" for k, v in parameters.items()),
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

    def _create_fork(self, owner, repo, organization=None):
        """Create a fork of a repository.

        Args:
            owner: The owner of the repository to fork.
            repo: The name of the repository to fork.
            organization: Optional organization to create the fork under.
                If None, creates under the current user.

        Returns:
            A dictionary containing the created fork's repository info.

        Raises:
            UnexpectedHttpStatus: If the API request fails.
        """
        path = f"repos/{owner}/{repo}/forks"
        data = {}
        if organization:
            data["organization"] = organization
        response = self._api_request(
            "POST", path, body=json.dumps(data).encode("utf-8")
        )
        if response.status != 202:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    @property
    def current_user(self):
        """Get information about the currently authenticated user."""
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
        """Publish a derived branch to Gitea, creating a fork if necessary.

        Args:
            local_branch: The local branch to publish.
            base_branch: The base branch this is derived from.
            name: The name for the published branch.
            project: Optional project name. If None, uses the base project
                name.
            owner: Optional owner. If None, uses the current user.
            revision_id: Optional specific revision to publish.
            overwrite: Whether to overwrite the remote branch if it exists.
            allow_lossy: Whether to allow lossy pushes if roundtrip fails.
            tag_selector: Optional function to select which tags to push.

        Returns:
            A tuple of (remote_branch, public_branch_url) for the published
            branch.

        Raises:
            NoRoundtrippingSupport: If lossy pushing is needed but not
                allowed.
        """
        if tag_selector is None:

            def tag_selector(t):
                return False

        _base_host, base_owner, base_project, _base_branch_name = (
            parse_gitea_branch_url(base_branch)
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
            remote_repo = self._create_fork(
                base_owner,
                base_project,
                organization=owner if owner != self.current_user["login"] else None,
            )
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
        return push_result.target_branch, gitea_url_to_bzr_url(
            remote_repo["clone_url"], name
        )

    def get_push_url(self, branch):
        """Get the push URL for a branch.

        Args:
            branch: A branch object to get the push URL for.

        Returns:
            The SSH URL suitable for pushing to the branch.
        """
        _host, owner, project, branch_name = parse_gitea_branch_url(branch)
        repo = self._get_repo(owner, project)
        return gitea_url_to_bzr_url(repo["ssh_url"], branch_name)

    def get_web_url(self, branch):
        """Get the web URL for a branch.

        Args:
            branch: A branch object to get the web URL for.

        Returns:
            The Gitea web URL for viewing the branch or repository.
        """
        _host, owner, project, branch_name = parse_gitea_branch_url(branch)
        repo = self._get_repo(owner, project)
        if branch_name:
            # TODO(jelmer): Don't hardcode this
            return repo["html_url"] + "/src/branch/" + branch_name
        return repo["html_url"]

    def get_derived_branch(
        self, base_branch, name, project=None, owner=None, preferred_schemes=None
    ):
        """Get a derived branch from a Gitea repository.

        Args:
            base_branch: The base branch to derive from.
            name: The derived branch name.
            project: Optional project name. If None, uses the base project
                name.
            owner: Optional owner. If None, uses the current user.
            preferred_schemes: Optional list of preferred URL schemes.

        Returns:
            A Branch object for the derived branch.

        Raises:
            NotBranchError: If the derived repository doesn't exist.
        """
        _base_host, base_owner, base_project, _base_branch_name = (
            parse_gitea_branch_url(base_branch)
        )
        base_repo = self._get_repo(base_owner, base_project)
        if owner is None:
            owner = self.current_user["login"]
        if project is None:
            project = base_repo["name"]
        try:
            remote_repo = self._get_repo(owner, project)
        except NoSuchProject as e:
            raise errors.NotBranchError(f"{self.base_url}{owner}/{project}") from e
        if preferred_schemes is None:
            preferred_schemes = DEFAULT_PREFERRED_SCHEMES
        for scheme in preferred_schemes:
            if scheme in SCHEME_FIELD_MAP:
                gitea_url = remote_repo[SCHEME_FIELD_MAP[scheme]]
                break
        else:
            raise AssertionError
        full_url = gitea_url_to_bzr_url(gitea_url, name)
        return _mod_branch.Branch.open(full_url)

    def get_proposer(self, source_branch, target_branch):
        """Get a merge proposal builder for creating pull requests.

        Args:
            source_branch: The source branch for the merge proposal.
            target_branch: The target branch for the merge proposal.

        Returns:
            A GiteaMergeProposalBuilder instance for creating pull requests.
        """
        return GiteaMergeProposalBuilder(self, source_branch, target_branch)

    def iter_proposals(self, source_branch, target_branch, status="open"):
        """Iterate over pull requests between specific source and target branches.

        Args:
            source_branch: The source branch to filter by.
            target_branch: The target branch to filter by.
            status: The status filter ('open', 'closed', 'merged', or 'all').

        Yields:
            GiteaMergeProposal instances matching the criteria.
        """
        (_source_host, source_owner, source_repo_name, source_branch_name) = (
            parse_gitea_branch_url(source_branch)
        )
        (_target_host, target_owner, target_repo_name, target_branch_name) = (
            parse_gitea_branch_url(target_branch)
        )
        pulls = self._get_repo_pulls(
            target_owner,
            target_repo_name,
            state=status_to_gitea_state(status),
            base_branch=target_branch_name,
        )
        for pull in pulls:
            if (status == "closed" and pull["merged"]) or (
                status == "merged" and not pull["merged"]
            ):
                continue
            if pull["head"]["ref"] != source_branch_name:
                continue
            if pull["head"].get("repo") is None:
                continue
            if (
                pull["head"]["repo"]["owner"]["login"] != source_owner
                or pull["head"]["repo"]["name"] != source_repo_name
            ):
                continue
            yield GiteaMergeProposal(self, pull)

    def hosts(self, branch):
        """Check if this forge instance hosts the given branch.

        Args:
            branch: A branch object to check.

        Returns:
            True if this Gitea instance hosts the branch, False otherwise.
        """
        try:
            host, _owner, _project, _branch_name = parse_gitea_branch_url(branch)
        except NotGiteaUrl:
            return False
        return host == urlutils.URL.from_string(self.base_url).host

    @classmethod
    def probe_from_hostname(cls, hostname, possible_transports=None):
        """Create a Gitea forge instance if this hostname is a known/valid Gitea instance.

        Configured hostnames (with stored credentials) are trusted
        directly. Unconfigured hostnames are probed by requesting the
        unauthenticated ``/api/v1/version`` endpoint that every Gitea
        instance exposes; a successful JSON response containing a
        ``version`` field is treated as sufficient evidence.

        Args:
            hostname: The hostname to check for Gitea support.
            possible_transports: Optional list of existing transports to
                reuse.

        Returns:
            A Gitea forge instance if the hostname is recognized.

        Raises:
            UnsupportedForge: If the hostname is not a Gitea instance.
        """
        credentials = get_credentials_by_hostname(hostname)
        if credentials is not None:
            base_url = credentials["url"]
            transport = get_transport(
                urlutils.join(base_url, API_PATH),
                possible_transports=possible_transports,
            )
            return cls(transport, base_url, credentials.get("private_token"))
        base_url = f"https://{hostname}/"
        transport = get_transport(
            urlutils.join(base_url, API_PATH), possible_transports=possible_transports
        )
        try:
            response = transport.request(
                "GET", urlutils.join(transport.base, "version")
            )
        except (UnexpectedHttpStatus, TransportConnectionError) as e:
            raise UnsupportedForge(hostname) from e
        if response.status != 200:
            raise UnsupportedForge(hostname)
        try:
            data = json.loads(response.text)
        except ValueError as e:
            raise UnsupportedForge(hostname) from e
        if "version" not in data:
            raise UnsupportedForge(hostname)
        mutter("Detected Gitea instance at %s (version %s)", base_url, data["version"])
        return cls(transport, base_url)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        """Create a Gitea forge instance if this URL belongs to a Gitea instance.

        Args:
            url: The URL to check for Gitea support.
            possible_transports: Optional list of existing transports to
                reuse.

        Returns:
            A Gitea forge instance if the URL is recognized.

        Raises:
            UnsupportedForge: If the URL is not a Gitea URL.
        """
        try:
            host, _owner, _repo = parse_gitea_url(url)
        except NotGiteaUrl as e:
            raise UnsupportedForge(url) from e
        return cls.probe_from_hostname(host, possible_transports=possible_transports)

    @classmethod
    def iter_instances(cls):
        """Iterate over all Gitea instances with stored credentials.

        Yields:
            Gitea forge instances for each set of stored credentials.
        """
        for _name, credentials in iter_tokens():
            base_url = credentials["url"]
            yield cls(
                get_transport(urlutils.join(base_url, API_PATH)),
                base_url,
                private_token=credentials.get("private_token"),
            )

    def iter_my_proposals(self, status="open", author=None):
        """Iterate over pull requests authored by a user.

        Gitea's search API does not offer GitHub-style ``is:pr
        author:...`` query syntax, so this walks pull requests via the
        issue search endpoint instead. Gitea's ``created`` search
        parameter means "created by the currently authenticated user"
        and overrides ``created_by``, so it is only sent when searching
        for the current user's own pull requests; a different author is
        searched for via ``created_by`` instead.

        Args:
            status: The status filter ('open', 'closed', 'merged', or
                'all').
            author: Optional author username. If None, uses the current
                authenticated user.

        Yields:
            GiteaMergeProposal instances representing the user's pull
            requests.
        """
        if author is None:
            author = self.current_user["login"]
        state = status_to_gitea_state(status)
        params = {"type": "pulls", "state": state}
        if author == self.current_user["login"]:
            params["created"] = "true"
        else:
            params["created_by"] = author
        for page in self._list_paged(
            "repos/issues/search",
            params,
            per_page=DEFAULT_PER_PAGE,
        ):
            for issue in page:
                if issue["user"]["login"] != author:
                    continue
                merged = issue.get("pull_request", {}).get("merged")
                if (status == "closed" and merged) or (
                    status == "merged" and not merged
                ):
                    continue
                repo_path = issue["repository"]["full_name"]
                pr_response = self._api_request(
                    "GET", f"repos/{repo_path}/pulls/{issue['number']}"
                )
                if pr_response.status != 200:
                    continue
                yield GiteaMergeProposal(self, json.loads(pr_response.text))

    def get_proposal_by_url(self, url):
        """Get a merge proposal by its Gitea pull request URL.

        Args:
            url: The Gitea pull request URL.

        Returns:
            A GiteaMergeProposal instance representing the pull request.

        Raises:
            UnsupportedForge: If the URL is not a Gitea pull request URL.
            UnexpectedHttpStatus: If the API request fails.
        """
        try:
            (host, owner, repo, pr_number) = parse_gitea_pr_url(url)
        except (NotGiteaUrl, NotMergeRequestUrl) as e:
            raise UnsupportedForge(url) from e
        if host != urlutils.URL.from_string(self.base_url).host:
            raise UnsupportedForge(url)
        path = f"repos/{owner}/{repo}/pulls/{pr_number}"
        response = self._api_request("GET", path)
        if response.status != 200:
            raise UnexpectedHttpStatus(
                path, response.status, headers=response.getheaders()
            )
        return GiteaMergeProposal(self, json.loads(response.text))

    def iter_my_forks(self, owner=None):
        """Iterate over repositories that are forks owned by a user.

        Args:
            owner: The owner username. If None, uses the current
                authenticated user.

        Yields:
            Full repository names (owner/repo) of repositories that are
            forks.
        """
        path = f"users/{owner}/repos" if owner else "user/repos"
        for page in self._list_paged(path, per_page=DEFAULT_PER_PAGE):
            for project in page:
                if not project.get("fork"):
                    continue
                yield project["full_name"]

    def delete_project(self, path):
        """Delete a Gitea repository.

        Args:
            path: The repository path in format 'owner/repo'.

        Returns:
            None for successful deletion.

        Raises:
            NoSuchProject: If the repository doesn't exist.
            UnexpectedHttpStatus: For other HTTP errors.
        """
        api_path = "repos/" + path
        response = self._api_request("DELETE", api_path)
        if response.status == 404:
            raise NoSuchProject(api_path)
        if response.status == 204:
            return
        raise UnexpectedHttpStatus(
            api_path, response.status, headers=response.getheaders()
        )

    def create_project(
        self, path, *, private=False, has_issues=True, has_wiki=False, summary=None
    ):
        """Create a new Gitea repository.

        Args:
            path: The repository path in format 'owner/repo'.
            private: Whether to create a private repository.
            has_issues: Whether to enable the issues feature.
            has_wiki: Whether to enable the wiki feature.
            summary: Optional repository description.

        Returns:
            A dictionary containing the created repository information.

        Raises:
            UnexpectedHttpStatus: If the API request fails with an unexpected status.
        """
        owner, name = path.split("/")
        data = {
            "name": name,
            "description": summary,
            "private": private,
            "has_issues": has_issues,
            "has_wiki": has_wiki,
        }
        if owner == self.current_user["login"]:
            api_path = "user/repos"
        else:
            api_path = f"orgs/{owner}/repos"
        response = self._api_request(
            "POST", api_path, body=json.dumps(data).encode("utf-8")
        )
        if response.status != 201:
            raise UnexpectedHttpStatus(
                api_path, response.status, headers=response.getheaders()
            )
        return json.loads(response.text)

    def get_current_user(self):
        """Get the username of the currently authenticated user."""
        if self._token is not None:
            return self.current_user["login"]
        return None

    def get_user_url(self, username):
        """Get the web URL for a Gitea user profile."""
        return urlutils.join(self.base_url, username)


class GiteaMergeProposalBuilder(MergeProposalBuilder):
    """Builder for creating Gitea pull requests (merge proposals)."""

    def __init__(self, gt, source_branch, target_branch):
        """Initialize the merge proposal builder.

        Args:
            gt: The Gitea forge instance.
            source_branch: The source branch for the pull request.
            target_branch: The target branch for the pull request.
        """
        self.gt = gt
        self.source_branch = source_branch
        self.target_branch = target_branch
        (
            _target_host,
            self.target_owner,
            self.target_repo_name,
            self.target_branch_name,
        ) = parse_gitea_branch_url(self.target_branch)
        (
            _source_host,
            self.source_owner,
            self.source_repo_name,
            self.source_branch_name,
        ) = parse_gitea_branch_url(self.source_branch)

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

        Returns:
            None, as Gitea doesn't provide a default body template.
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
        """Create a pull request on Gitea.

        Args:
            description: The pull request description/body.
            title: Optional custom title. If None, determined from
                description.
            reviewers: Optional list of reviewer usernames to request
                review from.
            labels: Optional list of numeric label IDs to apply. Gitea's
                API expects label IDs rather than names; resolving names
                to IDs needs a per-repository lookup that callers must do
                themselves.
            prerequisite_branch: Not supported by Gitea.
            commit_message: Ignored; Gitea doesn't support a custom squash
                commit message set at PR-creation time.
            work_in_progress: Whether to create as a draft pull request
                (Gitea marks this with a ``WIP:`` title prefix).
            allow_collaboration: Whether to allow maintainer modifications.
            delete_source_after_merge: Ignored; Gitea does not expose this
                as a per-PR creation option.

        Returns:
            A GiteaMergeProposal instance representing the created pull
            request.

        Raises:
            PrerequisiteBranchUnsupported: If prerequisite_branch is
                provided.
            MergeProposalExists: If a pull request already exists for
                these branches.
        """
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        if self.target_repo_name.endswith(".git"):
            self.target_repo_name = self.target_repo_name[:-4]
        if title is None:
            title = determine_title(description)
        if self.source_owner == self.target_owner:
            head = self.source_branch_name
        else:
            head = f"{self.source_owner}:{self.source_branch_name}"
        if delete_source_after_merge:
            mutter(
                "Ignoring request to delete source after merge, "
                "which gitea does not support"
            )
        try:
            pull_request = self.gt._create_pull(
                self.target_owner,
                self.target_repo_name,
                title=title,
                body=description,
                head=head,
                base=self.target_branch_name,
                labels=labels,
                reviewers=reviewers,
                draft=work_in_progress,
                allow_maintainer_edit=allow_collaboration,
            )
        except ValidationFailed as e:
            raise MergeProposalExists(self.source_branch.user_url) from e
        return GiteaMergeProposal(self.gt, pull_request)
