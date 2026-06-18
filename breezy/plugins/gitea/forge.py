# Copyright (C) 2021 Jelmer Vernooij <jelmer@jelmer.uk>
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

from dromedary import errors as transport_errors

from ... import bedding, controldir, errors, urlutils
from ... import branch as _mod_branch
from ...forge import (
    Forge,
    ForgeLoginRequired,
    MergeProposal,
    MergeProposalBuilder,
    NoSuchProject,
    PrerequisiteBranchUnsupported,
    UnsupportedForge,
    determine_title,
)
from ...git.urls import git_url_to_bzr_url
from ...transport import get_transport

DEFAULT_PAGE_SIZE = 50
DEFAULT_PREFERRED_SCHEMES = ["ssh", "http"]
SCHEME_MAP = {
    "git+ssh": "ssh_url",
    "ssh": "ssh_url",
    "http": "clone_url",
    "https": "clone_url",
}


def parse_timestring(ts):
    """Parse a Gitea ISO 8601 timestamp into a datetime object.

    Gitea returns timestamps such as ``2018-09-07T11:16:17+02:00`` or with a
    ``Z`` suffix. The trailing timezone is dropped, as the rest of the forge
    API works with naive timestamps.
    """
    if ts.endswith("Z"):
        ts = ts[:-1]
    elif len(ts) > 6 and ts[-6] in "+-" and ts[-3] == ":":
        ts = ts[:-6]
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")


class NotGiteaUrl(errors.BzrError):
    """Raised when a URL is not recognized as a Gitea URL."""

    _fmt = "Not a Gitea URL: %(url)s"

    def __init__(self, url):
        """Initialize with the offending URL."""
        errors.BzrError.__init__(self)
        self.url = url


class NotMergeRequestUrl(errors.BzrError):
    """Raised when a URL is not recognized as a Gitea pull request URL."""

    _fmt = "Not a merge proposal URL: %(url)s"

    def __init__(self, host, url):
        """Initialize with the host and offending URL."""
        errors.BzrError.__init__(self)
        self.host = host
        self.url = url


class DifferentGiteaInstances(errors.BzrError):
    """Raised when source and target branches live on different Gitea instances."""

    _fmt = (
        "Can't create merge proposals across Gitea instances: "
        "%(source_host)s and %(target_host)s"
    )

    def __init__(self, source_host, target_host):
        """Initialize with the two differing instance hostnames."""
        self.source_host = source_host
        self.target_host = target_host


class GiteaLoginMissing(ForgeLoginRequired):
    """Raised when authentication is required but no credentials are available."""

    _fmt = "Please log into Gitea instance at %(forge)s"


def store_gitea_token(name, url, private_token):
    """Store a Gitea token in the authentication configuration."""
    from ...config import AuthenticationConfig

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
    """Iterate over all available Gitea tokens from configuration.

    Yields (name, credentials) tuples, where credentials is a mapping that at
    least contains a ``url`` key.
    """
    import configparser

    config = configparser.ConfigParser()
    config.read([os.path.join(bedding.config_dir(), "gitea.conf")])
    for name, creds in config.items():
        if "url" not in creds:
            continue
        yield name, creds

    from ...config import AuthenticationConfig

    auth_config = AuthenticationConfig()
    for name, creds in auth_config._get_config().iteritems():
        if creds.get("forge") == "gitea":
            yield name, creds


def get_credentials_by_url(url):
    """Find Gitea credentials for a specific URL, or None if not found."""
    for _name, credentials in iter_tokens():
        if credentials["url"].rstrip("/") == url.rstrip("/"):
            return credentials
    return None


def parse_gitea_url(url):
    """Parse a Gitea repository URL into (hostname, owner/repo).

    Raises:
        NotGiteaUrl: If the URL scheme is unsupported or the host is missing.
    """
    (scheme, _user, _password, host, _port, path) = urlutils.parse_url(url)
    if scheme not in ("git+ssh", "https", "http"):
        raise NotGiteaUrl(url)
    if not host:
        raise NotGiteaUrl(url)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return host, path


def parse_gitea_branch_url(branch):
    """Parse a branch into (hostname, owner/repo, branch_name)."""
    url = urlutils.strip_segment_parameters(branch.user_url)
    host, path = parse_gitea_url(url)
    return host, path, branch.name


def parse_gitea_merge_request_url(url):
    """Parse a Gitea pull request URL into (hostname, owner/repo, pr_index).

    Gitea pull request URLs are of the form
    ``https://host/owner/repo/pulls/123``.

    Raises:
        NotGiteaUrl: If the URL scheme is unsupported or the host is missing.
        NotMergeRequestUrl: If the URL is not a pull request URL.
    """
    (scheme, _user, _password, host, _port, path) = urlutils.parse_url(url)
    if scheme not in ("git+ssh", "https", "http"):
        raise NotGiteaUrl(url)
    if not host:
        raise NotGiteaUrl(url)
    path = path.strip("/")
    parts = path.split("/")
    if len(parts) != 4 or parts[2] != "pulls":
        raise NotMergeRequestUrl(host, url)
    return host, f"{parts[0]}/{parts[1]}", int(parts[3])


def _unexpected_status(path, response):
    raise transport_errors.UnexpectedHttpStatus(
        path,
        response.status,
        response.data.decode("utf-8", "replace"),
        headers=response.getheaders(),
    )


def gitea_url_to_bzr_url(url, name):
    """Convert a Gitea clone URL plus branch name into a Breezy URL."""
    return git_url_to_bzr_url(url, branch=name)


class GiteaMergeProposal(MergeProposal):
    """A Gitea pull request, exposed through the common MergeProposal interface."""

    def __init__(self, gitea, pr):
        """Wrap a Gitea pull request dict."""
        self.gitea = gitea
        self._pr = pr

    def __repr__(self):
        """Return a string representation including the web URL."""
        return f"<{type(self).__name__} at {self._pr['html_url']!r}>"

    @property
    def url(self):
        """The web URL of the pull request."""
        return self._pr["html_url"]

    def get_web_url(self):
        """Return the web URL for viewing this pull request."""
        return self._pr["html_url"]

    def get_description(self):
        """Return the body text of the pull request."""
        return self._pr["body"]

    def set_description(self, description):
        """Set the body text of the pull request."""
        self._pr = self.gitea._patch_pull(
            self._pr["base"]["repo"]["full_name"],
            self._pr["number"],
            {"body": description},
        )

    def get_commit_message(self):
        """Return the merge commit message (unsupported by Gitea)."""
        return None

    def set_commit_message(self, commit_message):
        """Raise, as Gitea does not support setting a commit message."""
        raise errors.UnsupportedOperation(self.set_commit_message, self)

    def get_title(self):
        """Return the title of the pull request."""
        return self._pr.get("title")

    def set_title(self, title):
        """Set the title of the pull request."""
        self._pr = self.gitea._patch_pull(
            self._pr["base"]["repo"]["full_name"],
            self._pr["number"],
            {"title": title},
        )

    def _branch_from_part(self, part, *, preferred_schemes=None):
        repo = part["repo"]
        if repo is None:
            return None
        if preferred_schemes is None:
            preferred_schemes = DEFAULT_PREFERRED_SCHEMES
        for scheme in preferred_schemes:
            if scheme in SCHEME_MAP:
                return gitea_url_to_bzr_url(repo[SCHEME_MAP[scheme]], part["ref"])
        raise KeyError

    def get_source_branch_url(self, *, preferred_schemes=None):
        """Return the URL of the source branch."""
        return self._branch_from_part(
            self._pr["head"], preferred_schemes=preferred_schemes
        )

    def get_source_revision(self):
        """Return the revision id of the source branch head, or None."""
        from ...git.mapping import default_mapping

        sha = self._pr["head"].get("sha")
        if not sha:
            return None
        return default_mapping.revision_id_foreign_to_bzr(sha.encode("ascii"))

    def get_target_branch_url(self, *, preferred_schemes=None):
        """Return the URL of the target branch."""
        return self._branch_from_part(
            self._pr["base"], preferred_schemes=preferred_schemes
        )

    def set_target_branch_name(self, name):
        """Set the target branch of the pull request."""
        self._pr = self.gitea._patch_pull(
            self._pr["base"]["repo"]["full_name"],
            self._pr["number"],
            {"base": name},
        )

    def get_source_project(self):
        """Return the source repository name, or None if it was deleted."""
        repo = self._pr["head"]["repo"]
        return repo["full_name"] if repo else None

    def get_target_project(self):
        """Return the target repository name."""
        return self._pr["base"]["repo"]["full_name"]

    def is_merged(self):
        """Return whether the pull request has been merged."""
        return bool(self._pr.get("merged"))

    def is_closed(self):
        """Return whether the pull request was closed without merging."""
        return self._pr["state"] == "closed" and not self._pr.get("merged")

    def reopen(self):
        """Reopen a closed pull request."""
        self._pr = self.gitea._patch_pull(
            self._pr["base"]["repo"]["full_name"],
            self._pr["number"],
            {"state": "open"},
        )

    def close(self):
        """Close the pull request without merging."""
        self._pr = self.gitea._patch_pull(
            self._pr["base"]["repo"]["full_name"],
            self._pr["number"],
            {"state": "closed"},
        )

    def merge(self, commit_message=None, auto=False):
        """Merge the pull request."""
        self.gitea._merge_pull(
            self._pr["base"]["repo"]["full_name"],
            self._pr["number"],
            commit_message=commit_message,
        )
        self._pr = self.gitea._get_pull(
            self._pr["base"]["repo"]["full_name"], self._pr["number"]
        )

    def can_be_merged(self):
        """Return whether the pull request can currently be merged."""
        return self._pr.get("mergeable")

    def get_merged_by(self):
        """Return the username that merged the pull request, or None."""
        user = self._pr.get("merged_by")
        if user is None:
            return None
        return user["login"]

    def get_merged_at(self):
        """Return when the pull request was merged, or None."""
        merged_at = self._pr.get("merged_at")
        if merged_at is None:
            return None
        return parse_timestring(merged_at)

    def post_comment(self, body):
        """Post a comment on the pull request."""
        self.gitea._post_issue_comment(
            self._pr["base"]["repo"]["full_name"], self._pr["number"], body
        )


class Gitea(Forge):
    """Gitea forge implementation."""

    supports_merge_proposal_labels = True
    supports_merge_proposal_title = True
    supports_merge_proposal_commit_message = False
    supports_allow_collaboration = False
    merge_proposal_description_format = "markdown"

    def __repr__(self):
        """Return a string representation including the base URL."""
        return f"<Gitea({self.base_url!r})>"

    @property
    def base_url(self):
        """The base URL of the Gitea instance."""
        return self.transport.base

    @property
    def base_hostname(self):
        """The hostname of the Gitea instance."""
        return urlutils.parse_url(self.base_url)[3]

    def __init__(self, transport, private_token):
        """Initialize with a transport and access token."""
        self.transport = transport
        self.headers = {"Authorization": f"token {private_token}"}
        self._current_user = None

    def _api_request(self, method, path, fields=None, body=None):
        return self.transport.request(
            method,
            urlutils.join(self.base_url, "api", "v1", path),
            headers=self.headers,
            fields=fields,
            body=body,
        )

    def _api_json_request(self, method, path, data):
        headers = dict(self.headers)
        headers["Content-Type"] = "application/json"
        return self.transport.request(
            method,
            urlutils.join(self.base_url, "api", "v1", path),
            headers=headers,
            body=json.dumps(data).encode("utf-8"),
        )

    def _get_repo(self, full_name):
        """Get repository metadata for an ``owner/repo`` path.

        Raises:
            NoSuchProject: If the repository does not exist.
        """
        path = f"repos/{full_name}"
        response = self._api_request("GET", path)
        if response.status == 404:
            raise NoSuchProject(full_name)
        if response.status == 200:
            return json.loads(response.data)
        _unexpected_status(path, response)

    def _get_pull(self, full_name, index):
        path = f"repos/{full_name}/pulls/{index}"
        response = self._api_request("GET", path)
        if response.status == 403:
            raise transport_errors.PermissionDenied(response.text)
        if response.status != 200:
            _unexpected_status(path, response)
        return json.loads(response.data)

    def _patch_pull(self, full_name, index, data):
        path = f"repos/{full_name}/pulls/{index}"
        response = self._api_json_request("PATCH", path, data)
        if response.status == 403:
            raise transport_errors.PermissionDenied(response.text)
        if response.status not in (200, 201):
            _unexpected_status(path, response)
        return json.loads(response.data)

    def _merge_pull(self, full_name, index, commit_message=None):
        path = f"repos/{full_name}/pulls/{index}/merge"
        data = {"Do": "merge"}
        if commit_message is not None:
            data["MergeMessageField"] = commit_message
        response = self._api_json_request("POST", path, data)
        if response.status == 403:
            raise transport_errors.PermissionDenied(response.text)
        if response.status not in (200, 405):
            _unexpected_status(path, response)

    def _post_issue_comment(self, full_name, index, body):
        path = f"repos/{full_name}/issues/{index}/comments"
        response = self._api_json_request("POST", path, {"body": body})
        if response.status == 403:
            raise transport_errors.PermissionDenied(response.text)
        if response.status not in (200, 201):
            _unexpected_status(path, response)

    def _create_pull(
        self,
        base_full_name,
        title,
        head,
        base,
        body,
        labels=None,
        assignees=None,
    ):
        path = f"repos/{base_full_name}/pulls"
        data = {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
        }
        if assignees:
            data["assignees"] = assignees
        response = self._api_json_request("POST", path, data)
        if response.status == 403:
            raise transport_errors.PermissionDenied(response.text)
        if response.status not in (200, 201):
            _unexpected_status(path, response)
        return json.loads(response.data)

    def _list_paged(self, path, parameters=None):
        parameters = {} if parameters is None else dict(parameters.items())
        parameters["limit"] = str(DEFAULT_PAGE_SIZE)
        page = 1
        while True:
            parameters["page"] = str(page)
            query = "&".join("{}={}".format(*item) for item in parameters.items())
            response = self._api_request("GET", f"{path}?{query}")
            if response.status == 403:
                raise transport_errors.PermissionDenied(response.text)
            if response.status != 200:
                _unexpected_status(path, response)
            batch = json.loads(response.data)
            # The pull request listing endpoint wraps results in an object.
            if isinstance(batch, dict):
                batch = batch.get("issues") or batch.get("data") or []
            if not batch:
                return
            yield from batch
            if len(batch) < DEFAULT_PAGE_SIZE:
                return
            page += 1

    def fork_repo(self, full_name, owner=None):
        """Fork a repository, returning the metadata for the new fork."""
        path = f"repos/{full_name}/forks"
        data = {}
        if owner is not None:
            data["organization"] = owner
        response = self._api_json_request("POST", path, data)
        if response.status == 403:
            raise transport_errors.PermissionDenied(response.text)
        if response.status not in (200, 201, 202):
            _unexpected_status(path, response)
        return json.loads(response.data)

    def _retrieve_user(self):
        if self._current_user:
            return
        try:
            response = self._api_request("GET", "user")
        except transport_errors.UnexpectedHttpStatus as e:
            if e.code == 401:
                raise GiteaLoginMissing(self.base_url) from e
            raise
        if response.status == 200:
            self._current_user = json.loads(response.data)
            return
        if response.status == 401:
            raise GiteaLoginMissing(self.base_url)
        raise UnsupportedForge(self.base_url)

    def get_current_user(self):
        """Return the login of the authenticated user."""
        if not self._current_user:
            self._retrieve_user()
        return self._current_user["login"]

    def get_user_url(self, username):
        """Return the web URL for a user's profile page."""
        return urlutils.join(self.base_url, username)

    def hosts(self, branch):
        """Return whether this instance hosts the given branch."""
        try:
            (host, _project, _branch_name) = parse_gitea_branch_url(branch)
        except NotGiteaUrl:
            return False
        return self.base_hostname == host

    def get_push_url(self, branch):
        """Return the SSH push URL for a branch."""
        (_host, full_name, branch_name) = parse_gitea_branch_url(branch)
        repo = self._get_repo(full_name)
        return gitea_url_to_bzr_url(repo["ssh_url"], branch_name)

    def get_web_url(self, branch):
        """Return the web URL for viewing a branch."""
        (_host, full_name, branch_name) = parse_gitea_branch_url(branch)
        repo = self._get_repo(full_name)
        if branch_name:
            return repo["html_url"] + "/src/branch/" + branch_name
        return repo["html_url"]

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
        """Push ``local_branch`` to a fork of ``base_branch``, forking if needed."""
        if tag_selector is None:

            def tag_selector(t):
                return False

        (_host, base_full_name, _base_branch_name) = parse_gitea_branch_url(base_branch)
        base_repo = self._get_repo(base_full_name)
        if owner is None:
            owner = base_branch.get_config_stack().get("fork-namespace")
        if owner is None:
            owner = self.get_current_user()
        if project is None:
            project = base_repo["name"]
        try:
            target_repo = self._get_repo(f"{owner}/{project}")
        except NoSuchProject:
            target_repo = self.fork_repo(base_full_name, owner=owner)
        remote_repo_url = git_url_to_bzr_url(target_repo["ssh_url"])
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
        public_url = gitea_url_to_bzr_url(target_repo["clone_url"], name)
        return push_result.target_branch, public_url

    def get_derived_branch(
        self, base_branch, name, project=None, owner=None, preferred_schemes=None
    ):
        """Open a derived branch from an existing fork."""
        (_host, base_full_name, _base_branch_name) = parse_gitea_branch_url(base_branch)
        base_repo = self._get_repo(base_full_name)
        if owner is None:
            owner = self.get_current_user()
        if project is None:
            project = base_repo["name"]
        try:
            target_repo = self._get_repo(f"{owner}/{project}")
        except NoSuchProject as e:
            raise errors.NotBranchError(f"{self.base_url}/{owner}/{project}") from e
        if preferred_schemes is None:
            preferred_schemes = ["git+ssh"]
        for scheme in preferred_schemes:
            if scheme in SCHEME_MAP:
                gitea_url = target_repo[SCHEME_MAP[scheme]]
                break
        else:
            raise AssertionError
        return _mod_branch.Branch.open(
            gitea_url_to_bzr_url(gitea_url, name),
            possible_transports=[base_branch.user_transport],
        )

    def get_proposer(self, source_branch, target_branch):
        """Return a builder for creating a pull request between two branches."""
        return GiteaMergeProposalBuilder(self, source_branch, target_branch)

    def _list_pulls(self, full_name, state):
        return self._list_paged(f"repos/{full_name}/pulls", {"state": state})

    def iter_proposals(self, source_branch, target_branch, status):
        """Iterate over pull requests between two branches with the given status."""
        (
            source_host,
            source_full_name,
            source_branch_name,
        ) = parse_gitea_branch_url(source_branch)
        (
            target_host,
            target_full_name,
            target_branch_name,
        ) = parse_gitea_branch_url(target_branch)
        if source_host != target_host:
            raise DifferentGiteaInstances(source_host, target_host)
        state = "all" if status == "all" else "open"
        for pr in self._list_pulls(target_full_name, state):
            head_repo = pr["head"]["repo"]
            if (
                head_repo is None
                or head_repo["full_name"] != source_full_name
                or pr["head"]["ref"] != source_branch_name
                or pr["base"]["ref"] != target_branch_name
            ):
                continue
            if status == "merged" and not pr.get("merged"):
                continue
            if status == "closed" and (pr["state"] != "closed" or pr.get("merged")):
                continue
            if status == "open" and pr["state"] != "open":
                continue
            yield GiteaMergeProposal(self, pr)

    def iter_my_proposals(self, status="open", author=None):
        """Iterate over pull requests opened by the current user."""
        if author is None:
            author = self.get_current_user()
        state = "all" if status in ("all", "merged", "closed") else "open"
        parameters = {
            "type": "pulls",
            "state": state,
            "poster": author,
        }
        for issue in self._list_paged("repos/issues/search", parameters):
            pr = self._get_pull(issue["repository"]["full_name"], issue["number"])
            if status == "merged" and not pr.get("merged"):
                continue
            if status == "closed" and (pr["state"] != "closed" or pr.get("merged")):
                continue
            yield GiteaMergeProposal(self, pr)

    def get_proposal_by_url(self, url):
        """Return the pull request identified by a Gitea pull request URL."""
        try:
            (host, full_name, index) = parse_gitea_merge_request_url(url)
        except NotGiteaUrl as e:
            raise UnsupportedForge(url) from e
        except NotMergeRequestUrl as e:
            if self.base_hostname == e.host:
                raise
            raise UnsupportedForge(url) from e
        if self.base_hostname != host:
            raise UnsupportedForge(url)
        return GiteaMergeProposal(self, self._get_pull(full_name, index))

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        """Create a Gitea instance from a project URL, if credentials exist."""
        try:
            (host, _project) = parse_gitea_url(url)
        except NotGiteaUrl as e:
            raise UnsupportedForge(url) from e
        transport = get_transport(
            f"https://{host}", possible_transports=possible_transports
        )
        credentials = get_credentials_by_url(transport.base)
        if credentials is not None:
            instance = cls(transport, credentials.get("private_token"))
            instance._retrieve_user()
            return instance
        raise UnsupportedForge(url)

    @classmethod
    def iter_instances(cls):
        """Iterate over Gitea instances for all stored credentials."""
        for _name, credentials in iter_tokens():
            yield cls(
                get_transport(credentials["url"]),
                private_token=credentials.get("private_token"),
            )


class GiteaMergeProposalBuilder(MergeProposalBuilder):
    """Builder for creating Gitea pull requests."""

    def __init__(self, gitea, source_branch, target_branch):
        """Initialize the builder for source and target branches."""
        self.gitea = gitea
        self.source_branch = source_branch
        (
            self.source_host,
            self.source_full_name,
            self.source_branch_name,
        ) = parse_gitea_branch_url(source_branch)
        self.target_branch = target_branch
        (
            self.target_host,
            self.target_full_name,
            self.target_branch_name,
        ) = parse_gitea_branch_url(target_branch)
        if self.source_host != self.target_host:
            raise DifferentGiteaInstances(self.source_host, self.target_host)

    def get_infotext(self):
        """Return informational text describing the proposal."""
        info = []
        info.append(f"Gitea instance: {self.target_host}\n")
        info.append(f"Source: {self.source_branch.user_url}\n")
        info.append(f"Target: {self.target_branch.user_url}\n")
        return "".join(info)

    def get_initial_body(self):
        """Return the initial body text (none, for Gitea)."""
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
        delete_source_after_merge=None,
    ):
        """Create a pull request on Gitea.

        Reviewers are assigned as assignees, since Gitea's pull request
        creation endpoint does not accept reviewers directly. ``commit_message``
        is ignored, as Gitea does not support setting it via the API.
        """
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        if title is None:
            title = determine_title(description)
        if work_in_progress:
            title = f"WIP: {title}"
        source_owner = self.source_full_name.split("/")[0]
        if source_owner == self.target_full_name.split("/")[0]:
            head = self.source_branch_name
        else:
            head = f"{source_owner}:{self.source_branch_name}"
        pr = self.gitea._create_pull(
            self.target_full_name,
            title=title,
            head=head,
            base=self.target_branch_name,
            body=description,
            assignees=reviewers,
        )
        return GiteaMergeProposal(self.gitea, pr)
