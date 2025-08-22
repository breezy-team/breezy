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

import json
import os
import re
import time
from datetime import datetime
from typing import Optional

from ... import bedding, controldir, errors, urlutils
from ... import branch as _mod_branch
from ...forge import (
    Forge,
    ForgeLoginRequired,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    NoSuchProject,
    PrerequisiteBranchUnsupported,
    SourceNotDerivedFromTarget,
    UnsupportedForge,
    determine_title,
)
from ...git.urls import git_url_to_bzr_url
from ...trace import mutter
from ...transport import get_transport

_DEFAULT_FILES = ["/etc/python-gitlab.cfg", "~/.python-gitlab.cfg"]
DEFAULT_PAGE_SIZE = 50
DEFAULT_PREFERRED_SCHEMES = ["ssh", "http"]
SCHEME_MAP = {
    "git+ssh": "ssh_url_to_repo",
    "ssh": "ssh_url_to_repo",
    "http": "http_url_to_repo",
    "https": "http_url_to_repo",
}


def mp_status_to_status(status):
    """Convert merge proposal status to GitLab merge request status.

    Args:
        status: A status string from the common forge API ("all", "open", "merged", "closed")

    Returns:
        The corresponding GitLab merge request state string

    Raises:
        KeyError: If the status is not recognized
    """
    return {"all": "all", "open": "opened", "merged": "merged", "closed": "closed"}[
        status
    ]


def parse_timestring(ts):
    """Parse a GitLab ISO timestamp string into a datetime object.

    Args:
        ts: A timestamp string in the format "YYYY-MM-DDTHH:MM:SS.fZ"

    Returns:
        A datetime object representing the parsed timestamp

    Raises:
        ValueError: If the timestamp string is not in the expected format
    """
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")


class NotGitLabUrl(errors.BzrError):
    """Raised when a URL is not recognized as a GitLab URL.

    This exception is raised when trying to parse a URL that doesn't match
    the expected GitLab URL format or uses an unsupported scheme.
    """

    _fmt = "Not a GitLab URL: %(url)s"

    def __init__(self, url):
        """Initialize the exception.

        Args:
            url: The URL that is not a valid GitLab URL
        """
        errors.BzrError.__init__(self)
        self.url = url


class NotMergeRequestUrl(errors.BzrError):
    """Raised when a URL is not recognized as a GitLab merge request URL.

    This exception is raised when trying to parse a URL that doesn't match
    the expected GitLab merge request URL format.
    """

    _fmt = "Not a merge proposal URL: %(url)s"

    def __init__(self, host, url):
        """Initialize the exception.

        Args:
            host: The hostname from the URL
            url: The URL that is not a valid merge request URL
        """
        errors.BzrError.__init__(self)
        self.host = host
        self.url = url


class GitLabError(errors.BzrError):
    """Raised when GitLab API returns an error response.

    This exception wraps GitLab API error responses, typically from
    HTTP 400 Bad Request responses.
    """

    _fmt = "GitLab error: %(error)s"

    def __init__(self, error, full_response):
        """Initialize the exception.

        Args:
            error: The error message from GitLab
            full_response: The complete HTTP response object
        """
        errors.BzrError.__init__(self)
        self.error = error
        self.full_response = full_response


class GitLabUnprocessable(errors.BzrError):
    """Raised when GitLab API returns HTTP 422 Unprocessable Entity.

    This exception is raised when GitLab cannot process a request due to
    semantic errors in the request data.
    """

    _fmt = "GitLab can not process request: %(error)s."

    def __init__(self, error, full_response):
        """Initialize the exception.

        Args:
            error: The error message from GitLab
            full_response: The complete HTTP response object
        """
        errors.BzrError.__init__(self)
        self.error = error
        self.full_response = full_response


class DifferentGitLabInstances(errors.BzrError):
    """Raised when attempting to create merge proposals across different GitLab instances.

    GitLab merge requests can only be created between projects on the same GitLab instance.
    This exception is raised when the source and target branches are on different instances.
    """

    _fmt = (
        "Can't create merge proposals across GitLab instances: "
        "%(source_host)s and %(target_host)s"
    )

    def __init__(self, source_host, target_host):
        """Initialize the exception.

        Args:
            source_host: The hostname of the source branch's GitLab instance
            target_host: The hostname of the target branch's GitLab instance
        """
        self.source_host = source_host
        self.target_host = target_host


class GitLabLoginMissing(ForgeLoginRequired):
    """Raised when authentication is required but no credentials are available.

    This exception is raised when attempting to access GitLab API endpoints that
    require authentication, but no valid credentials (private token) are found.
    """

    _fmt = "Please log into GitLab instance at %(forge)s"


class GitlabLoginError(errors.BzrError):
    """Raised when GitLab login fails.

    This exception is raised when authentication to GitLab fails,
    typically due to invalid credentials or authentication errors.
    """

    _fmt = "Error logging in: %(error)s"

    def __init__(self, error):
        """Initialize the exception.

        Args:
            error: The error message describing the login failure
        """
        self.error = error


class GitLabConflict(errors.BzrError):
    """Raised when GitLab API returns HTTP 409 Conflict.

    This exception is raised when a requested operation conflicts with
    the current state of the resource on GitLab.
    """

    _fmt = "Conflict during operation: %(reason)s"

    def __init__(self, reason):
        """Initialize the exception.

        Args:
            reason: The reason for the conflict from GitLab
        """
        errors.BzrError.__init__(self)
        self.reason = reason


class ForkingDisabled(errors.BzrError):
    """Raised when attempting to fork a project that has forking disabled.

    This exception is raised when trying to fork a GitLab project that
    has been configured to disallow forking.
    """

    _fmt = "Forking on project %(project)s is disabled."

    def __init__(self, project):
        """Initialize the exception.

        Args:
            project: The project name that cannot be forked
        """
        self.project = project


class MergeRequestConflict(Exception):
    """Raised when a merge request operation conflicts.

    This exception is raised when a merge request operation cannot be
    completed due to conflicts, such as duplicate merge requests or
    validation failures.
    """

    def __init__(self, reason):
        """Initialize the exception.

        Args:
            reason: The reason for the merge request conflict
        """
        self.reason = reason


class ProjectCreationTimeout(errors.BzrError):
    """Raised when project creation or forking times out.

    This exception is raised when waiting for a GitLab project to be created
    or imported (such as when forking) exceeds the specified timeout period.
    """

    _fmt = "Timeout (%(timeout)ds) while waiting for project %(project)s to be created."

    def __init__(self, project, timeout):
        """Initialize the exception.

        Args:
            project: The name of the project that timed out during creation
            timeout: The timeout duration in seconds
        """
        self.project = project
        self.timeout = timeout


def store_gitlab_token(name, url, private_token):
    """Store a GitLab token in a configuration file.

    Args:
        name: The configuration name/identifier for this token
        url: The base URL of the GitLab instance
        private_token: The GitLab private access token
    """
    from ...config import AuthenticationConfig

    auth_config = AuthenticationConfig()
    auth_config._set_option(name, "url", url)
    auth_config._set_option(name, "forge", "gitlab")
    auth_config._set_option(name, "private_token", private_token)


def iter_tokens():
    """Iterate over all available GitLab tokens from configuration files.

    This function searches for GitLab credentials in multiple configuration sources:
    1. python-gitlab configuration files (/etc/python-gitlab.cfg, ~/.python-gitlab.cfg)
    2. Legacy gitlab.conf in the Breezy config directory
    3. Breezy authentication configuration with forge="gitlab"
    4. Breezy authentication configuration for gitlab.com URLs (for backwards compatibility)

    Yields:
        tuple: A (name, credentials) tuple where name is the configuration name
               and credentials is a dict containing 'url' and other credential fields
    """
    import configparser

    config = configparser.ConfigParser()
    config.read(
        [os.path.expanduser(p) for p in _DEFAULT_FILES]
        +
        # backwards compatibility
        [os.path.join(bedding.config_dir(), "gitlab.conf")]
    )
    for name, creds in config.items():
        if "url" not in creds:
            continue
        yield name, creds

    from ...config import AuthenticationConfig

    auth_config = AuthenticationConfig()
    for name, creds in auth_config._get_config().iteritems():
        if creds.get("forge") == "gitlab":
            yield name, creds
        else:
            url = creds.get("url")
            # Hack for those without forge set
            if url and url.startswith("https://gitlab.com/"):
                yield name, creds


def get_credentials_by_url(url):
    """Find GitLab credentials for a specific URL.

    Args:
        url: The GitLab instance URL to find credentials for

    Returns:
        A dictionary containing the credentials for the URL, or None if not found.
        The dictionary may contain keys like 'private_token', 'url', etc.
    """
    for _name, credentials in iter_tokens():
        if credentials["url"].rstrip("/") == url.rstrip("/"):
            return credentials
    else:
        return None


def parse_gitlab_url(url):
    """Parse a GitLab URL to extract hostname and project path.

    Args:
        url: A GitLab repository URL (http, https, or git+ssh)

    Returns:
        tuple: A (hostname, project_path) tuple where hostname is the GitLab
               instance hostname and project_path is the project path without .git suffix

    Raises:
        NotGitLabUrl: If the URL scheme is not supported or hostname is missing
    """
    (scheme, user, password, host, port, path) = urlutils.parse_url(url)
    if scheme not in ("git+ssh", "https", "http"):
        raise NotGitLabUrl(url)
    if not host:
        raise NotGitLabUrl(url)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return host, path


def parse_gitlab_branch_url(branch):
    """Parse a branch object to extract GitLab hostname, project path, and branch name.

    Args:
        branch: A Breezy branch object with a user_url and name

    Returns:
        tuple: A (hostname, project_path, branch_name) tuple

    Raises:
        NotGitLabUrl: If the branch URL is not a valid GitLab URL
    """
    url = urlutils.strip_segment_parameters(branch.user_url)
    host, path = parse_gitlab_url(url)
    return host, path, branch.name


def parse_gitlab_merge_request_url(url):
    """Parse a GitLab merge request URL to extract components.

    Args:
        url: A GitLab merge request URL (e.g., https://gitlab.com/project/repo/-/merge_requests/123)

    Returns:
        tuple: A (hostname, project_name, merge_request_id) tuple where:
               - hostname is the GitLab instance hostname
               - project_name is the full project path
               - merge_request_id is the numeric merge request ID

    Raises:
        NotGitLabUrl: If the URL scheme is not supported or hostname is missing
        NotMergeRequestUrl: If the URL is not a valid merge request URL
    """
    (scheme, user, password, host, port, path) = urlutils.parse_url(url)
    if scheme not in ("git+ssh", "https", "http"):
        raise NotGitLabUrl(url)
    if not host:
        raise NotGitLabUrl(url)
    path = path.strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        raise NotMergeRequestUrl(host, url)
    if parts[-2] != "merge_requests":
        raise NotMergeRequestUrl(host, url)
    project_name = "/".join(parts[:-3]) if parts[-3] == "-" else "/".join(parts[:-2])
    return host, project_name, int(parts[-1])


def _unexpected_status(path, response):
    """Raise an UnexpectedHttpStatus error for an API response.

    Args:
        path: The API path that was accessed
        response: The HTTP response object with unexpected status

    Raises:
        UnexpectedHttpStatus: Always raised with details from the response
    """
    raise errors.UnexpectedHttpStatus(
        path,
        response.status,
        response.data.decode("utf-8", "replace"),
        headers=response.getheaders(),
    )


class GitLabMergeProposal(MergeProposal):
    """A GitLab merge request implementation of the MergeProposal interface.

    This class provides access to GitLab merge requests through the common
    Breezy forge merge proposal interface. It supports auto-merge functionality.

    Attributes:
        supports_auto_merge: Boolean indicating that this forge supports auto-merge
    """

    supports_auto_merge = True

    def __init__(self, gl, mr):
        """Initialize a GitLab merge proposal.

        Args:
            gl: The GitLab forge instance
            mr: The merge request data dictionary from GitLab API
        """
        self.gl = gl
        self._mr = mr

    def _update(self, **kwargs):
        """Update the merge request with the given parameters.

        Args:
            **kwargs: Parameters to update on the merge request

        Raises:
            GitLabConflict: If the update conflicts with current state
        """
        try:
            self.gl._update_merge_request(
                self._mr["project_id"], self._mr["iid"], kwargs
            )
        except GitLabConflict as e:
            self.gl._handle_merge_request_conflict(
                e.reason, self.get_source_branch_url(), self._mr["target_project_id"]
            )

    def __repr__(self):
        """Return a string representation of the merge proposal.

        Returns:
            A string showing the class name and web URL of the merge request
        """
        return f"<{type(self).__name__} at {self._mr['web_url']!r}>"

    @property
    def url(self):
        """Get the web URL of the merge request.

        Returns:
            The web URL string for this merge request on GitLab
        """
        return self._mr["web_url"]

    def get_web_url(self):
        """Get the web URL for viewing this merge request.

        Returns:
            The web URL string for this merge request on GitLab
        """
        return self._mr["web_url"]

    def get_description(self):
        """Get the description/body text of the merge request.

        Returns:
            The description text of the merge request, or None if not set
        """
        return self._mr["description"]

    def set_description(self, description):
        """Set the description/body text of the merge request.

        Args:
            description: The new description text for the merge request

        Raises:
            UnexpectedHttpStatus: If the update fails with an unhandled HTTP error

        Note:
            This method includes a workaround for GitLab versions (like 15.5.6) that
            apply changes but return HTTP 500. In such cases, it verifies the change
            was actually applied before raising the error.
        """
        try:
            self._update(description=description)
        except errors.UnexpectedHttpStatus as e:
            # HACK: Some versions of GitLab apply the changes but fail with a 500
            # This appears to happen at least with version 15.5.6
            if e.code != 500:
                raise
            self._mr = self.gl._get_merge_request(
                self._mr["project_id"], self._mr["iid"]
            )
            if self._mr["description"] != description:
                raise

    def get_commit_message(self):
        """Get the commit message that will be used when merging.

        Returns:
            The merge commit message string, or None if not set
        """
        return self._mr.get("merge_commit_message")

    def set_commit_message(self, message):
        """Set the commit message for merging.

        Args:
            message: The commit message to use when merging

        Raises:
            UnsupportedOperation: Always raised as GitLab doesn't support
                                 setting commit messages via the API
        """
        raise errors.UnsupportedOperation(self.set_commit_message, self)

    def get_title(self):
        """Get the title of the merge request.

        Returns:
            The title string of the merge request, or None if not set
        """
        return self._mr.get("title")

    def set_title(self, title):
        """Set the title of the merge request.

        Args:
            title: The new title for the merge request

        Raises:
            GitLabConflict: If the update conflicts with current state
        """
        self._update(title=title)

    def _branch_url_from_project(
        self, project_id, branch_name, *, preferred_schemes=None
    ):
        """Get a branch URL from a project ID and branch name.

        Args:
            project_id: The GitLab project ID, or None
            branch_name: The name of the branch
            preferred_schemes: List of preferred URL schemes to try (defaults to DEFAULT_PREFERRED_SCHEMES)

        Returns:
            A Breezy-compatible URL for the branch, or None if project_id is None

        Raises:
            KeyError: If none of the preferred schemes are supported
        """
        if project_id is None:
            return None
        project = self.gl._get_project(project_id)
        if preferred_schemes is None:
            preferred_schemes = DEFAULT_PREFERRED_SCHEMES
        for scheme in preferred_schemes:
            if scheme in SCHEME_MAP:
                return gitlab_url_to_bzr_url(project[SCHEME_MAP[scheme]], branch_name)
        raise KeyError

    def get_source_branch_url(self, *, preferred_schemes=None):
        """Get the URL for the source branch of this merge request.

        Args:
            preferred_schemes: List of preferred URL schemes to try

        Returns:
            A Breezy-compatible URL for the source branch
        """
        return self._branch_url_from_project(
            self._mr["source_project_id"],
            self._mr["source_branch"],
            preferred_schemes=preferred_schemes,
        )

    def get_source_revision(self):
        """Get the revision ID for the source branch head.

        Returns:
            A Breezy revision ID for the source branch head commit,
            or None if no SHA is available
        """
        from ...git.mapping import default_mapping

        sha = self._mr["sha"]
        if sha is None:
            return None
        return default_mapping.revision_id_foreign_to_bzr(sha.encode("ascii"))

    def get_target_branch_url(self, *, preferred_schemes=None):
        """Get the URL for the target branch of this merge request.

        Args:
            preferred_schemes: List of preferred URL schemes to try

        Returns:
            A Breezy-compatible URL for the target branch
        """
        return self._branch_url_from_project(
            self._mr["target_project_id"],
            self._mr["target_branch"],
            preferred_schemes=preferred_schemes,
        )

    def set_target_branch_name(self, name):
        """Set the target branch name for this merge request.

        Args:
            name: The new target branch name

        Raises:
            GitLabConflict: If the update conflicts with current state
        """
        self._update(target_branch=name)

    def _get_project_name(self, project_id):
        """Get the full project name from a project ID.

        Args:
            project_id: The GitLab project ID

        Returns:
            The project path with namespace (e.g., "namespace/project")
        """
        source_project = self.gl._get_project(project_id)
        return source_project["path_with_namespace"]

    def get_source_project(self):
        """Get the source project name for this merge request.

        Returns:
            The source project path with namespace (e.g., "namespace/project")
        """
        return self._get_project_name(self._mr["source_project_id"])

    def get_target_project(self):
        """Get the target project name for this merge request.

        Returns:
            The target project path with namespace (e.g., "namespace/project")
        """
        return self._get_project_name(self._mr["target_project_id"])

    def is_merged(self):
        """Check if this merge request has been merged.

        Returns:
            True if the merge request has been merged, False otherwise
        """
        return self._mr["state"] == "merged"

    def is_closed(self):
        """Check if this merge request has been closed without merging.

        Returns:
            True if the merge request has been closed, False otherwise
        """
        return self._mr["state"] == "closed"

    def reopen(self):
        """Reopen a closed merge request.

        Raises:
            GitLabConflict: If the update conflicts with current state
        """
        return self._update(state_event="reopen")

    def close(self):
        """Close this merge request without merging.

        Raises:
            GitLabConflict: If the update conflicts with current state
        """
        self._update(state_event="close")

    def merge(self, commit_message=None, auto=False):
        """Merge this merge request.

        Args:
            commit_message: Optional commit message for the merge commit
            auto: If True, merge automatically when pipeline succeeds

        Raises:
            PermissionDenied: If user lacks permission to merge
            UnexpectedHttpStatus: If the merge operation fails

        Note:
            Updates the internal merge request data with the response from GitLab.
            See GitLab API documentation: https://docs.gitlab.com/ee/api/merge_requests.html#accept-mr
        """
        # https://docs.gitlab.com/ee/api/merge_requests.html#accept-mr
        ret = self.gl._merge_mr(
            self._mr["project_id"],
            self._mr["iid"],
            kwargs={
                "merge_commit_message": commit_message,
                "merge_when_pipeline_succeeds": auto,
            },
        )
        self._mr.update(ret)

    def can_be_merged(self):
        """Check if this merge request can be merged.

        Returns:
            True if the merge request can be merged,
            False if it cannot be merged,
            None if the merge status is still being determined

        Raises:
            ValueError: If the merge status value is unrecognized

        Note:
            GitLab has several merge status values:
            - "can_be_merged": Ready to merge
            - "cannot_be_merged": Has conflicts
            - "unchecked": Not yet checked
            - "cannot_be_merged_recheck": Needs recheck after changes
            - "checking": Currently being checked
            See GitLab commit 7517105303c for more details on status distinctions.
        """
        if self._mr["merge_status"] == "cannot_be_merged":
            return False
        elif self._mr["merge_status"] == "can_be_merged":
            return True
        elif self._mr["merge_status"] in (
            "unchecked",
            "cannot_be_merged_recheck",
            "checking",
        ):
            # See https://gitlab.com/gitlab-org/gitlab/-/commit/7517105303c for
            # an explanation of the distinction between unchecked and
            # cannot_be_merged_recheck
            return None
        else:
            raise ValueError(self._mr["merge_status"])

    def get_merged_by(self):
        """Get the username of who merged this merge request.

        Returns:
            The username of the user who merged this merge request,
            or None if not merged or user information unavailable
        """
        user = self._mr.get("merge_user")
        if user is None:
            return None
        return user["username"]

    def get_merged_at(self):
        """Get the timestamp when this merge request was merged.

        Returns:
            A datetime object representing when the merge request was merged,
            or None if not merged or timestamp unavailable
        """
        merged_at = self._mr.get("merged_at")
        if merged_at is None:
            return None
        return parse_timestring(merged_at)

    def post_comment(self, body):
        """Post a comment to this merge request.

        Args:
            body: The comment text to post

        Raises:
            PermissionDenied: If user lacks permission to comment
            UnexpectedHttpStatus: If the comment posting fails
        """
        kwargs = {"body": body}
        self.gl._post_merge_request_note(
            self._mr["project_id"], self._mr["iid"], kwargs
        )


def gitlab_url_to_bzr_url(url, name):
    """Convert a GitLab repository URL to a Breezy URL with branch name.

    Args:
        url: The GitLab repository URL (git clone URL)
        name: The branch name to append to the URL

    Returns:
        A Breezy-compatible URL string that includes the branch reference
    """
    return git_url_to_bzr_url(url, branch=name)


class GitLab(Forge):
    """GitLab forge implementation."""

    supports_merge_proposal_labels = True
    supports_merge_proposal_title = True
    supports_merge_proposal_commit_message = False
    supports_allow_collaboration = True
    merge_proposal_description_format = "markdown"

    def __repr__(self):
        """Return a string representation of the GitLab instance.

        Returns:
            A string showing the class name and base URL
        """
        return f"<GitLab({self.base_url!r})>"

    @property
    def base_url(self):
        """Get the base URL of the GitLab instance.

        Returns:
            The base URL string of the GitLab instance
        """
        return self.transport.base

    @property
    def base_hostname(self):
        """Get the hostname of the GitLab instance.

        Returns:
            The hostname string extracted from the base URL
        """
        return urlutils.parse_url(self.base_url)[3]

    def _find_correct_project_name(self, path):
        """Find the correct project name by following redirects.

        GitLab may redirect project requests to the canonical project path.
        This method attempts to discover the correct project name by making
        a request and following any redirects.

        Args:
            path: The project path to check

        Returns:
            The correct project path from redirect target, or None if no redirect

        Raises:
            UnexpectedHttpStatus: If the response has an unexpected status
        """
        try:
            resp = self.transport.request(
                "GET", urlutils.join(self.base_url, path), headers=self.headers
            )
        except errors.RedirectRequested as e:
            return urlutils.parse_url(e.target)[-1].strip("/")
        if resp.status != 200:
            _unexpected_status(path, resp)
        return None

    def _api_request(self, method, path, fields=None, body=None):
        """Make an API request to GitLab.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            path: API path relative to /api/v4/
            fields: Optional dictionary of form fields to send
            body: Optional request body

        Returns:
            The HTTP response object from the GitLab API
        """
        return self.transport.request(
            method,
            urlutils.join(self.base_url, "api", "v4", path),
            headers=self.headers,
            fields=fields,
            body=body,
        )

    def __init__(self, transport, private_token):
        """Initialize a GitLab forge instance.

        Args:
            transport: The transport object for making HTTP requests
            private_token: GitLab private access token for authentication
        """
        self.transport = transport
        self.headers = {"Private-Token": private_token}
        self._current_user = None

    def _get_user(self, username):
        """Get user information by username.

        Args:
            username: The GitLab username to look up

        Returns:
            A dictionary containing user information from GitLab API

        Raises:
            KeyError: If the user does not exist
            UnexpectedHttpStatus: If the API request fails
        """
        path = f"users/{urlutils.quote(str(username), '')}"
        response = self._api_request("GET", path)
        if response.status == 404:
            raise KeyError(f"no such user {username}")
        if response.status == 200:
            return json.loads(response.data)
        _unexpected_status(path, response)

    def _get_user_by_email(self, email):
        """Get user information by email address.

        Args:
            email: The email address to search for

        Returns:
            A dictionary containing user information from GitLab API

        Raises:
            KeyError: If no user with the email exists
            ValueError: If multiple users match the email
            UnexpectedHttpStatus: If the API request fails
        """
        path = f"users?search={urlutils.quote(str(email), '')}"
        response = self._api_request("GET", path)
        if response.status == 404:
            raise KeyError(f"no such user {email}")
        if response.status == 200:
            ret = json.loads(response.data)
            if len(ret) != 1:
                raise ValueError(f"unexpected number of results; {ret!r}")
            return ret[0]
        _unexpected_status(path, response)

    def _get_project(self, project_name, _redirect_checked=False):
        """Get project information by name.

        Args:
            project_name: The project path (namespace/project) or project ID
            _redirect_checked: Internal flag to prevent infinite redirect loops

        Returns:
            A dictionary containing project information from GitLab API

        Raises:
            NoSuchProject: If the project does not exist
            UnexpectedHttpStatus: If the API request fails

        Note:
            This method automatically handles redirects to find the correct
            project name if the initial request returns a 404.
        """
        path = f"projects/{urlutils.quote(str(project_name), '')}"
        response = self._api_request("GET", path)
        if response.status == 404:
            if not _redirect_checked:
                project_name = self._find_correct_project_name(project_name)
                if project_name is not None:
                    return self._get_project(project_name, _redirect_checked=True)
            raise NoSuchProject(project_name)
        if response.status == 200:
            return json.loads(response.data)
        _unexpected_status(path, response)

    def _get_namespace(self, namespace):
        """Get namespace information by name.

        Args:
            namespace: The namespace name to look up

        Returns:
            A dictionary containing namespace information from GitLab API,
            or None if the namespace does not exist

        Raises:
            UnexpectedHttpStatus: If the API request fails
        """
        path = "namespaces/" + urlutils.quote(str(namespace), "")
        response = self._api_request("GET", path)
        if response.status == 200:
            return json.loads(response.data)
        if response.status == 404:
            return None
        _unexpected_status(path, response)

    def create_project(self, project_name, summary=None):
        """Create a new project on GitLab.

        Args:
            project_name: The project name, optionally with namespace (namespace/project)
            summary: Optional project description

        Returns:
            A dictionary containing the created project information from GitLab API

        Raises:
            Exception: If the namespace does not exist
            AlreadyControlDirError: If a project with the same name already exists
            PermissionDenied: If user lacks permission to create projects in the namespace
            UnexpectedHttpStatus: If the API request fails
        """
        if project_name.endswith(".git"):
            project_name = project_name[:-4]
        if "/" in project_name:
            namespace_path, path = project_name.lstrip("/").rsplit("/", 1)
        else:
            namespace_path = ""
            path = project_name

        namespace = self._get_namespace(namespace_path)
        if namespace is None:
            raise Exception(f"namespace {namespace_path} does not exist")

        fields = {
            "path": path,
            "namespace_id": namespace["id"],
        }
        if summary is not None:
            fields["description"] = summary
        response = self._api_request("POST", "projects", fields=fields)
        if response.status == 400:
            ret = json.loads(response.data)
            if ret.get("message", {}).get("path") == ["has already been taken"]:
                raise errors.AlreadyControlDirError(project_name)
            raise
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        if response.status not in (200, 201):
            _unexpected_status("projects", response)
        project = json.loads(response.data)
        return project

    def fork_project(self, project_name, timeout=50, interval=5, owner=None):
        """Fork a project on GitLab.

        Args:
            project_name: The project path to fork (namespace/project)
            timeout: Maximum time in seconds to wait for fork completion (default: 50)
            interval: Time in seconds between status checks (default: 5)
            owner: Optional namespace to fork into (defaults to current user)

        Returns:
            A dictionary containing the forked project information from GitLab API

        Raises:
            ForkingDisabled: If forking is disabled for the project
            GitLabConflict: If there's a conflict (e.g., fork already exists)
            ProjectCreationTimeout: If fork creation exceeds the timeout
            UnexpectedHttpStatus: If the API request fails

        Note:
            This method waits for the fork import process to complete before returning.
            The import status is checked at regular intervals until it reaches
            "finished" or "none" state.
        """
        path = f"projects/{urlutils.quote(str(project_name), '')}/fork"
        fields = {}
        if owner is not None:
            fields["namespace"] = owner
        response = self._api_request("POST", path, fields=fields)
        if response.status == 404:
            raise ForkingDisabled(project_name)
        if response.status == 409:
            resp = json.loads(response.data)
            raise GitLabConflict(resp.get("message"))
        if response.status not in (200, 201):
            _unexpected_status(path, response)
        # The response should be valid JSON, but let's ignore it
        project = json.loads(response.data)
        # Spin and wait until import_status for new project
        # is complete.
        deadline = time.time() + timeout
        while project["import_status"] not in ("finished", "none"):
            mutter("import status is %s", project["import_status"])
            if time.time() > deadline:
                raise ProjectCreationTimeout(project["path_with_namespace"], timeout)
            time.sleep(interval)
            project = self._get_project(project["path_with_namespace"])
        return project

    def _handle_merge_request_conflict(self, message, source_url, target_project):
        """Handle merge request conflict errors by providing more specific exceptions.

        Args:
            message: The conflict message from GitLab
            source_url: The URL of the source branch
            target_project: The target project path

        Raises:
            MergeProposalExists: If the conflict is due to an existing merge request
            MergeRequestConflict: For other types of conflicts

        Note:
            This method parses GitLab conflict messages to detect when a merge
            request already exists for the same source branch, and provides
            a reference to the existing merge request.
        """
        m = re.fullmatch(
            r"Another open merge request already exists for "
            r"this source branch: \!([0-9]+)",
            message[0],
        )
        if m:
            merge_id = int(m.group(1))
            mr = self._get_merge_request(target_project, merge_id)
            raise MergeProposalExists(source_url, GitLabMergeProposal(self, mr))
        raise MergeRequestConflict(message)

    def get_current_user(self):
        """Get the username of the currently authenticated user.

        Returns:
            The username string of the current user

        Note:
            This method caches the user information after the first call.
        """
        if not self._current_user:
            self._retrieve_user()
        return self._current_user["username"]

    def get_user_url(self, username):
        """Get the web URL for a user's profile page.

        Args:
            username: The username to get the URL for

        Returns:
            The web URL string for the user's profile page
        """
        return urlutils.join(self.base_url, username)

    def _list_paged(self, path, parameters=None, per_page=None):
        """Iterate through paginated GitLab API results.

        Args:
            path: The API path to request
            parameters: Optional dictionary of query parameters
            per_page: Optional number of items per page

        Yields:
            Individual items from all pages of results

        Raises:
            PermissionDenied: If access is denied to the resource
            UnexpectedHttpStatus: If the API request fails

        Note:
            This method automatically handles GitLab's pagination by following
            the X-Next-Page header until all results are retrieved.
        """
        parameters = {} if parameters is None else dict(parameters.items())
        if per_page:
            parameters["per_page"] = str(per_page)
        page = "1"
        while page:
            parameters["page"] = page
            response = self._api_request(
                "GET",
                path
                + "?"
                + "&".join(["{}={}".format(*item) for item in parameters.items()]),
            )
            if response.status == 403:
                raise errors.PermissionDenied(response.text)
            if response.status != 200:
                _unexpected_status(path, response)
            page = response.getheader("X-Next-Page")
            yield from json.loads(response.data)

    def _list_merge_requests(self, author=None, project=None, state=None):
        """List merge requests with optional filtering.

        Args:
            author: Optional username to filter by author
            project: Optional project ID/path to filter by project
            state: Optional state to filter by (opened, closed, merged, all)

        Returns:
            A generator yielding merge request dictionaries from GitLab API

        Note:
            If project is specified, returns merge requests for that project only.
            Otherwise, returns merge requests accessible to the current user.
        """
        if project is not None:
            path = f"projects/{urlutils.quote(str(project), '')}/merge_requests"
        else:
            path = "merge_requests"
        parameters = {}
        if state:
            parameters["state"] = state
        if author:
            parameters["author_username"] = urlutils.quote(author, "")
        return self._list_paged(path, parameters, per_page=DEFAULT_PAGE_SIZE)

    def _get_merge_request(self, project, merge_id):
        """Get detailed information about a specific merge request.

        Args:
            project: The project path or ID
            merge_id: The merge request IID (internal ID)

        Returns:
            A dictionary containing merge request information from GitLab API

        Raises:
            PermissionDenied: If access is denied to the merge request
            UnexpectedHttpStatus: If the API request fails
        """
        path = "projects/%s/merge_requests/%d" % (
            urlutils.quote(str(project), ""),
            merge_id,
        )
        response = self._api_request("GET", path)
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        if response.status != 200:
            _unexpected_status(path, response)
        return json.loads(response.data)

    def _list_projects(self, owner):
        """List projects for a specific user.

        Args:
            owner: The username to list projects for

        Returns:
            A generator yielding project dictionaries from GitLab API
        """
        path = f"users/{urlutils.quote(str(owner), '')}/projects"
        parameters = {}
        return self._list_paged(path, parameters, per_page=DEFAULT_PAGE_SIZE)

    def _update_merge_request(self, project_id, iid, mr):
        """Update a merge request.

        Args:
            project_id: The project ID or path
            iid: The merge request IID (internal ID)
            mr: Dictionary of fields to update

        Returns:
            A dictionary containing the updated merge request information

        Raises:
            GitLabConflict: If the update conflicts with current state
            PermissionDenied: If user lacks permission to update the merge request
            UnexpectedHttpStatus: If the API request fails
        """
        path = f"projects/{urlutils.quote(str(project_id), '')}/merge_requests/{iid}"
        response = self._api_request("PUT", path, fields=mr)
        if response.status == 200:
            return json.loads(response.data)
        if response.status == 409:
            raise GitLabConflict(json.loads(response.data).get("message"))
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        _unexpected_status(path, response)

    def _merge_mr(self, project_id, iid, kwargs):
        """Merge a merge request.

        Args:
            project_id: The project ID or path
            iid: The merge request IID (internal ID)
            kwargs: Dictionary of merge parameters (merge_commit_message, etc.)

        Returns:
            A dictionary containing the merged merge request information

        Raises:
            PermissionDenied: If user lacks permission to merge the merge request
            UnexpectedHttpStatus: If the API request fails
        """
        path = "projects/{}/merge_requests/{}/merge".format(
            urlutils.quote(str(project_id), ""), iid
        )
        response = self._api_request("PUT", path, fields=kwargs)
        if response.status == 200:
            return json.loads(response.data)
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        _unexpected_status(path, response)

    def _post_merge_request_note(self, project_id, iid, kwargs):
        """Post a note/comment to a merge request.

        Args:
            project_id: The project ID or path
            iid: The merge request IID (internal ID)
            kwargs: Dictionary containing note parameters (body, etc.)

        Raises:
            PermissionDenied: If user lacks permission to comment on the merge request
            UnexpectedHttpStatus: If the API request fails
        """
        path = "projects/{}/merge_requests/{}/notes".format(
            urlutils.quote(str(project_id), ""), iid
        )
        response = self._api_request("POST", path, fields=kwargs)
        if response.status == 201:
            json.loads(response.data)
            return
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        _unexpected_status(path, response)

    def _create_mergerequest(
        self,
        title,
        source_project_id,
        target_project_id,
        source_branch_name,
        target_branch_name,
        description,
        labels=None,
        allow_collaboration=False,
    ):
        """Create a new merge request.

        Args:
            title: The merge request title
            source_project_id: The ID of the source project
            target_project_id: The ID of the target project
            source_branch_name: The name of the source branch
            target_branch_name: The name of the target branch
            description: The merge request description/body
            labels: Optional list/string of labels to assign
            allow_collaboration: Whether to allow collaboration from target project maintainers

        Returns:
            A dictionary containing the created merge request information

        Raises:
            GitLabError: If GitLab returns a 400 Bad Request error
            PermissionDenied: If user lacks permission to create merge requests
            GitLabConflict: If the merge request conflicts (e.g., already exists)
            GitLabUnprocessable: If GitLab cannot process the request (422 error)
            UnexpectedHttpStatus: If the API request fails with other errors
        """
        path = f"projects/{source_project_id}/merge_requests"
        fields = {
            "title": title,
            "source_branch": source_branch_name,
            "target_branch": target_branch_name,
            "target_project_id": target_project_id,
            "description": description,
            "allow_collaboration": allow_collaboration,
        }
        if labels:
            fields["labels"] = labels
        response = self._api_request("POST", path, fields=fields)
        if response.status == 400:
            data = json.loads(response.data)
            raise GitLabError(data.get("message"), response)
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        if response.status == 409:
            raise GitLabConflict(json.loads(response.data).get("message"))
        if response.status == 422:
            data = json.loads(response.data)
            raise GitLabUnprocessable(data.get("error") or data.get("message"), data)
        if response.status != 201:
            _unexpected_status(path, response)
        return json.loads(response.data)

    def get_push_url(self, branch):
        """Get the push URL for a branch.

        Args:
            branch: A Breezy branch object

        Returns:
            A Breezy-compatible URL for pushing to the branch using SSH

        Raises:
            NotGitLabUrl: If the branch URL is not a valid GitLab URL
            NoSuchProject: If the project does not exist
        """
        (host, project_name, branch_name) = parse_gitlab_branch_url(branch)
        project = self._get_project(project_name)
        return gitlab_url_to_bzr_url(project["ssh_url_to_repo"], branch_name)

    def get_web_url(self, branch):
        """Get the web URL for viewing a branch.

        Args:
            branch: A Breezy branch object

        Returns:
            The web URL for viewing the branch on GitLab. If no specific branch
            is specified, returns the project's main page URL.

        Raises:
            NotGitLabUrl: If the branch URL is not a valid GitLab URL
            NoSuchProject: If the project does not exist

        Note:
            The branch-specific URL is constructed manually as GitLab doesn't
            provide an API endpoint for this information.
        """
        (host, project_name, branch_name) = parse_gitlab_branch_url(branch)
        project = self._get_project(project_name)
        if branch_name:
            # TODO(jelmer): Use API to get this URL
            return project["web_url"] + "/-/tree/" + branch_name
        else:
            return project["web_url"]

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
        """Publish a derived branch to GitLab.

        This method creates a fork if necessary and pushes the local branch to it.

        Args:
            local_branch: The local Breezy branch to publish
            base_branch: The base Breezy branch being forked from
            name: The name for the branch in the remote repository
            project: Optional project name (defaults to base project name)
            owner: Optional owner namespace (defaults to current user)
            revision_id: Optional specific revision to push
            overwrite: Whether to overwrite existing branch
            allow_lossy: Whether to allow lossy conversion if needed
            tag_selector: Optional function to select which tags to push

        Returns:
            A tuple of (target_branch, public_url) where target_branch is the
            pushed branch object and public_url is the public HTTP URL

        Raises:
            NotGitLabUrl: If the base branch URL is not a valid GitLab URL
            NoSuchProject: If the base project does not exist
            NoRoundtrippingSupport: If lossy conversion is needed but not allowed
            PermissionDenied: If user lacks permission to fork or push

        Note:
            If the target project (fork) doesn't exist, it will be created automatically.
            The method tries normal push first, then falls back to lossy push if needed
            and allowed.
        """
        if tag_selector is None:

            def tag_selector(t):
                return False

        (host, base_project_name, base_branch_name) = parse_gitlab_branch_url(
            base_branch
        )
        if owner is None:
            owner = base_branch.get_config_stack().get("fork-namespace")
        if owner is None:
            owner = self.get_current_user()
        base_project = self._get_project(base_project_name)
        if project is None:
            project = base_project["path"]
        try:
            target_project = self._get_project(f"{owner}/{project}")
        except NoSuchProject:
            target_project = self.fork_project(
                base_project["path_with_namespace"], owner=owner
            )
        remote_repo_url = git_url_to_bzr_url(target_project["ssh_url_to_repo"])
        remote_dir = controldir.ControlDir.open(remote_repo_url)
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
        public_url = gitlab_url_to_bzr_url(target_project["http_url_to_repo"], name)
        return push_result.target_branch, public_url

    def get_derived_branch(
        self, base_branch, name, project=None, owner=None, preferred_schemes=None
    ):
        """Get a derived branch from a fork.

        Args:
            base_branch: The base branch that was forked
            name: The name of the branch in the fork
            project: Optional project name (defaults to base project name)
            owner: Optional owner namespace (defaults to current user)
            preferred_schemes: Optional list of preferred URL schemes

        Returns:
            A Breezy branch object for the derived branch

        Raises:
            NotGitLabUrl: If the base branch URL is not a valid GitLab URL
            NotBranchError: If the derived project/branch does not exist
            AssertionError: If no supported URL scheme is found

        Note:
            This method assumes the fork already exists and tries to open
            the specified branch within it.
        """
        (host, base_project, base_branch_name) = parse_gitlab_branch_url(base_branch)
        if owner is None:
            owner = self.get_current_user()
        if project is None:
            project = self._get_project(base_project)["path"]
        try:
            target_project = self._get_project(f"{owner}/{project}")
        except NoSuchProject as e:
            raise errors.NotBranchError(f"{self.base_url}/{owner}/{project}") from e
        if preferred_schemes is None:
            preferred_schemes = ["git+ssh"]
        for scheme in preferred_schemes:
            if scheme == "git+ssh":
                gitlab_url = target_project["ssh_url_to_repo"]
                break
            elif scheme == "https":
                gitlab_url = target_project["http_url_to_repo"]
                break
        else:
            raise AssertionError
        return _mod_branch.Branch.open(
            gitlab_url_to_bzr_url(gitlab_url, name),
            possible_transports=[base_branch.user_transport],
        )

    def get_proposer(self, source_branch, target_branch):
        """Get a merge proposal builder for creating merge requests.

        Args:
            source_branch: The source Breezy branch for the merge request
            target_branch: The target Breezy branch for the merge request

        Returns:
            A GitlabMergeProposalBuilder instance for creating merge requests
        """
        return GitlabMergeProposalBuilder(self, source_branch, target_branch)

    def iter_proposals(self, source_branch, target_branch, status):
        """Iterate over merge proposals between two branches.

        Args:
            source_branch: The source Breezy branch
            target_branch: The target Breezy branch
            status: The status to filter by ("open", "closed", "merged", "all")

        Yields:
            GitLabMergeProposal objects for each matching merge request

        Raises:
            NotGitLabUrl: If either branch URL is not a valid GitLab URL
            DifferentGitLabInstances: If source and target branches are on different GitLab instances
            NoSuchProject: If either project doesn't exist

        Note:
            This method finds merge requests from the source branch to the target branch,
            filtering by the specified status.
        """
        (
            source_host,
            source_project_name,
            source_branch_name,
        ) = parse_gitlab_branch_url(source_branch)
        (
            target_host,
            target_project_name,
            target_branch_name,
        ) = parse_gitlab_branch_url(target_branch)
        if source_host != target_host:
            raise DifferentGitLabInstances(source_host, target_host)
        source_project = self._get_project(source_project_name)
        target_project = self._get_project(target_project_name)
        state = mp_status_to_status(status)
        for mr in self._list_merge_requests(project=target_project["id"], state=state):
            if (
                mr["source_project_id"] != source_project["id"]
                or mr["source_branch"] != source_branch_name
                or mr["target_project_id"] != target_project["id"]
                or mr["target_branch"] != target_branch_name
            ):
                continue
            yield GitLabMergeProposal(self, mr)

    def hosts(self, branch):
        """Check if this GitLab instance hosts the given branch.

        Args:
            branch: A Breezy branch object to check

        Returns:
            True if this GitLab instance hosts the branch, False otherwise
        """
        try:
            (host, project, branch_name) = parse_gitlab_branch_url(branch)
        except NotGitLabUrl:
            return False
        return self.base_hostname == host

    def _retrieve_user(self):
        """Retrieve and cache current user information.

        This method fetches the current user's information from GitLab and caches it
        for future use. It also validates that the authentication credentials are valid.

        Raises:
            GitLabLoginMissing: If authentication is required but credentials are invalid
            GitlabLoginError: If there's an authentication error
            UnsupportedForge: If this is not a supported GitLab instance
            UnexpectedHttpStatus: If the API request fails

        Note:
            This method is called automatically when user information is needed
            and has not been cached yet.
        """
        if self._current_user:
            return
        try:
            response = self._api_request("GET", "user")
        except errors.UnexpectedHttpStatus as e:
            if e.code == 401:
                raise GitLabLoginMissing(self.base_url) from e
            raise
        if response.status == 200:
            self._current_user = json.loads(response.data)
            return
        if response.status == 401:
            if json.loads(response.data) == {"message": "401 Unauthorized"}:
                raise GitLabLoginMissing(self.base_url)
            else:
                raise GitlabLoginError(response.text)
        raise UnsupportedForge(self.base_url)

    @classmethod
    def probe_from_hostname(cls, hostname, possible_transports=None):
        """Create a GitLab forge instance by probing a hostname.

        Args:
            hostname: The hostname of the GitLab instance (e.g., "gitlab.com")
            possible_transports: Optional list of transport objects to reuse

        Returns:
            A GitLab instance if credentials are found and valid

        Raises:
            UnsupportedForge: If no credentials are found or authentication fails

        Note:
            This method looks for stored credentials for the hostname and attempts
            to authenticate. GitLab doesn't provide unauthenticated APIs for probing,
            so credentials are required.
        """
        base_url = f"https://{hostname}"
        credentials = get_credentials_by_url(base_url)
        if credentials is not None:
            transport = get_transport(base_url, possible_transports=possible_transports)
            instance = cls(transport, credentials.get("private_token"))
            instance._retrieve_user()
            return instance
        # We could potentially probe for e.g. /api/v4/metadata here
        # But none of the non-project APIs appear to be accessible without
        # authentication :-(
        raise UnsupportedForge(hostname)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        """Create a GitLab forge instance by probing a project URL.

        Args:
            url: A GitLab project URL to probe
            possible_transports: Optional list of transport objects to reuse

        Returns:
            A GitLab instance if the URL is a valid GitLab project and credentials are available

        Raises:
            UnsupportedForge: If the URL is not a GitLab URL or authentication fails
            GitLabLoginMissing: If the URL is a GitLab instance but no credentials are available
            NotGitLabUrl: If the URL format is not recognized as GitLab

        Note:
            This method first tries to use stored credentials. If none are found,
            it attempts to probe the GitLab API to detect if it's a GitLab instance
            by checking for the X-Gitlab-Feature-Category header.
        """
        try:
            (host, project) = parse_gitlab_url(url)
        except NotGitLabUrl as e:
            raise UnsupportedForge(url) from e
        transport = get_transport(
            f"https://{host}", possible_transports=possible_transports
        )
        credentials = get_credentials_by_url(transport.base)
        if credentials is not None:
            instance = cls(transport, credentials.get("private_token"))
            instance._retrieve_user()
            return instance
        try:
            resp = transport.request(
                "GET",
                f"https://{host}/api/v4/projects/{urlutils.quote(str(project), '')}",
            )
        except errors.UnexpectedHttpStatus as e:
            raise UnsupportedForge(url) from e
        except errors.RedirectRequested as e:
            # GitLab doesn't send redirects for these URLs
            raise UnsupportedForge(url) from e
        else:
            if not resp.getheader("X-Gitlab-Feature-Category"):
                raise UnsupportedForge(url)
            if resp.status in (200, 401):
                raise GitLabLoginMissing(f"https://{host}/")
            raise UnsupportedForge(url)

    @classmethod
    def iter_instances(cls):
        """Iterate over all configured GitLab instances.

        Yields:
            GitLab forge instances for each set of stored credentials

        Note:
            This method creates GitLab instances for all stored credentials
            found in configuration files, without validating the credentials.
        """
        for _name, credentials in iter_tokens():
            yield cls(
                get_transport(credentials["url"]),
                private_token=credentials.get("private_token"),
            )

    def iter_my_proposals(self, status="open", author=None):
        """Iterate over merge requests for the current user.

        Args:
            status: The status to filter by ("open", "closed", "merged", "all")
            author: Optional specific author (defaults to current user)

        Yields:
            GitLabMergeProposal objects for each matching merge request
        """
        if author is None:
            author = self.get_current_user()
        state = mp_status_to_status(status)
        for mp in self._list_merge_requests(author=author, state=state):
            yield GitLabMergeProposal(self, mp)

    def iter_my_forks(self, owner: Optional[str] = None):
        """Iterate over forked projects for a user.

        Args:
            owner: Optional specific owner (defaults to current user)

        Yields:
            Project path strings (namespace/project) for each forked project

        Note:
            Only returns projects that are forks of other projects, not original projects.
        """
        if owner is None:
            owner = self.get_current_user()
        for project in self._list_projects(owner=owner):
            base_project = project.get("forked_from_project")
            if not base_project:
                continue
            yield project["path_with_namespace"]

    def get_proposal_by_url(self, url: str) -> GitLabMergeProposal:
        """Get a merge proposal object from a GitLab merge request URL.

        Args:
            url: The GitLab merge request URL

        Returns:
            A GitLabMergeProposal object for the merge request

        Raises:
            UnsupportedForge: If the URL is not for this GitLab instance or not a merge request URL
            NotMergeRequestUrl: If the URL is not a valid merge request URL
            NoSuchProject: If the project does not exist
            UnexpectedHttpStatus: If the API request fails
        """
        try:
            (host, project, merge_id) = parse_gitlab_merge_request_url(url)
        except NotGitLabUrl as e:
            raise UnsupportedForge(url) from e
        except NotMergeRequestUrl as e:
            if self.base_hostname == e.host:
                raise
            else:
                raise UnsupportedForge(url) from e
        if self.base_hostname != host:
            raise UnsupportedForge(url)
        project = self._get_project(project)
        mr = self._get_merge_request(project["path_with_namespace"], merge_id)
        return GitLabMergeProposal(self, mr)

    def delete_project(self, project):
        """Delete a project from GitLab.

        Args:
            project: The project path or ID to delete

        Raises:
            NoSuchProject: If the project does not exist
            UnexpectedHttpStatus: If the API request fails

        Warning:
            This operation is irreversible and will permanently delete the project
            and all its data including repositories, issues, and merge requests.
        """
        path = f"projects/{urlutils.quote(str(project), '')}"
        response = self._api_request("DELETE", path)
        if response.status == 404:
            raise NoSuchProject(project)
        if response.status != 202:
            _unexpected_status(path, response)


class GitlabMergeProposalBuilder(MergeProposalBuilder):
    """Builder class for creating GitLab merge requests.

    This class handles the creation of merge requests between GitLab branches,
    providing validation and setup for the merge request creation process.
    """

    def __init__(self, gl, source_branch, target_branch):
        """Initialize the merge proposal builder.

        Args:
            gl: The GitLab forge instance
            source_branch: The source Breezy branch for the merge request
            target_branch: The target Breezy branch for the merge request

        Raises:
            NotGitLabUrl: If either branch URL is not a valid GitLab URL
            DifferentGitLabInstances: If source and target branches are on different GitLab instances
        """
        self.gl = gl
        self.source_branch = source_branch
        (
            self.source_host,
            self.source_project_name,
            self.source_branch_name,
        ) = parse_gitlab_branch_url(source_branch)
        self.target_branch = target_branch
        (
            self.target_host,
            self.target_project_name,
            self.target_branch_name,
        ) = parse_gitlab_branch_url(target_branch)
        if self.source_host != self.target_host:
            raise DifferentGitLabInstances(self.source_host, self.target_host)

    def get_infotext(self):
        """Get informational text about the merge proposal.

        Returns:
            A formatted string containing information about the GitLab instance,
            source branch URL, and target branch URL
        """
        info = []
        info.append(f"Gitlab instance: {self.target_host}\n")
        info.append(f"Source: {self.source_branch.user_url}\n")
        info.append(f"Target: {self.target_branch.user_url}\n")
        return "".join(info)

    def get_initial_body(self):
        """Get an initial body text for the merge proposal.

        Returns:
            None, as GitLab merge requests don't have a default initial body template
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
        """Create a merge request on GitLab.

        Args:
            description: The description/body text for the merge request
            title: Optional title (auto-generated from description if not provided)
            reviewers: Optional list of reviewer usernames or email addresses
            labels: Optional list of label strings to assign
            prerequisite_branch: Not supported by GitLab (raises exception if provided)
            commit_message: Ignored (GitLab doesn't support setting commit messages via API)
            work_in_progress: Whether to mark as work-in-progress (adds "WIP:" prefix to title)
            allow_collaboration: Whether to allow target project maintainers to push to source branch
            delete_source_after_merge: Whether to delete source branch after merge

        Returns:
            A GitLabMergeProposal object representing the created merge request

        Raises:
            PrerequisiteBranchUnsupported: If prerequisite_branch is specified
            NoSuchProject: If source or target project doesn't exist
            GitLabConflict: If merge request conflicts (e.g., already exists)
            GitLabUnprocessable: If GitLab cannot process the request
            SourceNotDerivedFromTarget: If source project is not a fork of target
            KeyError: If a reviewer cannot be found
            PermissionDenied: If user lacks permission to create merge requests

        Note:
            - Reviewers are assigned as assignees since GitLab API doesn't have reviewers
            - Reviewers can be specified as usernames or email addresses
            - Labels are joined with commas for the GitLab API
            - See GitLab API docs: https://docs.gitlab.com/ee/api/merge_requests.html#create-mr
            - Future enhancements could include milestone and squash settings
        """
        # https://docs.gitlab.com/ee/api/merge_requests.html#create-mr
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        # Note that commit_message is ignored, since Gitlab doesn't support it.
        source_project = self.gl._get_project(self.source_project_name)
        target_project = self.gl._get_project(self.target_project_name)
        if title is None:
            title = determine_title(description)
        if work_in_progress:
            title = f"WIP: {title}"
        # TODO(jelmer): Allow setting milestone field
        # TODO(jelmer): Allow setting squash field
        kwargs = {
            "title": title,
            "source_project_id": source_project["id"],
            "target_project_id": target_project["id"],
            "source_branch_name": self.source_branch_name,
            "target_branch_name": self.target_branch_name,
            "description": description,
            "allow_collaboration": allow_collaboration,
        }
        if delete_source_after_merge is not None:
            kwargs["should_remove_source_branch"] = delete_source_after_merge
        if labels:
            kwargs["labels"] = ",".join(labels)
        if reviewers:
            kwargs["assignee_ids"] = []
            for reviewer in reviewers:
                if "@" in reviewer:
                    user = self.gl._get_user_by_email(reviewer)
                else:
                    user = self.gl._get_user(reviewer)
                kwargs["assignee_ids"].append(user["id"])
        try:
            merge_request = self.gl._create_mergerequest(**kwargs)
        except GitLabConflict as e:
            self.gl._handle_merge_request_conflict(
                e.reason,
                self.source_branch.user_url,
                target_project["path_with_namespace"],
            )
        except GitLabUnprocessable as e:
            if e.error == ["Source project is not a fork of the target project"]:
                raise SourceNotDerivedFromTarget(
                    self.source_branch, self.target_branch
                ) from e
            raise
        return GitLabMergeProposal(self.gl, merge_request)


def register_gitlab_instance(shortname, url):
    """Register a GitLab instance for bug tracking integration.

    Args:
        shortname: Short name identifier for the GitLab instance (e.g. "gitlab")
        url: Base URL of the GitLab instance (e.g. "https://gitlab.com")
    """
    from ...bugtracker import ProjectIntegerBugTracker, tracker_registry

    tracker_registry.register(
        shortname, ProjectIntegerBugTracker(shortname, url + "/{project}/issues/{id}")
    )
