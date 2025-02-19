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
    return {"all": "all", "open": "opened", "merged": "merged", "closed": "closed"}[
        status
    ]


def parse_timestring(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")


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


class GitLabError(errors.BzrError):
    _fmt = "GitLab error: %(error)s"

    def __init__(self, error, full_response):
        errors.BzrError.__init__(self)
        self.error = error
        self.full_response = full_response


class GitLabUnprocessable(errors.BzrError):
    _fmt = "GitLab can not process request: %(error)s."

    def __init__(self, error, full_response):
        errors.BzrError.__init__(self)
        self.error = error
        self.full_response = full_response


class DifferentGitLabInstances(errors.BzrError):
    _fmt = (
        "Can't create merge proposals across GitLab instances: "
        "%(source_host)s and %(target_host)s"
    )

    def __init__(self, source_host, target_host):
        self.source_host = source_host
        self.target_host = target_host


class GitLabLoginMissing(ForgeLoginRequired):
    _fmt = "Please log into GitLab instance at %(forge)s"


class GitlabLoginError(errors.BzrError):
    _fmt = "Error logging in: %(error)s"

    def __init__(self, error):
        self.error = error


class GitLabConflict(errors.BzrError):
    _fmt = "Conflict during operation: %(reason)s"

    def __init__(self, reason):
        errors.BzrError(self)
        self.reason = reason


class ForkingDisabled(errors.BzrError):
    _fmt = "Forking on project %(project)s is disabled."

    def __init__(self, project):
        self.project = project


class MergeRequestConflict(Exception):
    """Raised when a merge requests conflicts."""

    def __init__(self, reason):
        self.reason = reason


class ProjectCreationTimeout(errors.BzrError):
    _fmt = "Timeout (%(timeout)ds) while waiting for project %(project)s to be created."

    def __init__(self, project, timeout):
        self.project = project
        self.timeout = timeout


def store_gitlab_token(name, url, private_token):
    """Store a GitLab token in a configuration file."""
    from breezy.config import AuthenticationConfig

    auth_config = AuthenticationConfig()
    auth_config._set_option(name, "url", url)
    auth_config._set_option(name, "forge", "gitlab")
    auth_config._set_option(name, "private_token", private_token)


def iter_tokens():
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

    from breezy.config import AuthenticationConfig

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
    for name, credentials in iter_tokens():
        if credentials["url"].rstrip("/") == url.rstrip("/"):
            return credentials
    else:
        return None


def parse_gitlab_url(url):
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
    url = urlutils.strip_segment_parameters(branch.user_url)
    host, path = parse_gitlab_url(url)
    return host, path, branch.name


def parse_gitlab_merge_request_url(url):
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
    if parts[-3] == "-":
        project_name = "/".join(parts[:-3])
    else:
        project_name = "/".join(parts[:-2])
    return host, project_name, int(parts[-1])


def _unexpected_status(path, response):
    raise errors.UnexpectedHttpStatus(
        path,
        response.status,
        response.data.decode("utf-8", "replace"),
        headers=response.getheaders(),
    )


class GitLabMergeProposal(MergeProposal):
    supports_auto_merge = True

    def __init__(self, gl, mr):
        self.gl = gl
        self._mr = mr

    def _update(self, **kwargs):
        try:
            self.gl._update_merge_request(
                self._mr["project_id"], self._mr["iid"], kwargs
            )
        except GitLabConflict as e:
            self.gl._handle_merge_request_conflict(
                e.reason, self.get_source_branch_url(), self._mr["target_project_id"]
            )

    def __repr__(self):
        return "<{} at {!r}>".format(type(self).__name__, self._mr["web_url"])

    @property
    def url(self):
        return self._mr["web_url"]

    def get_web_url(self):
        return self._mr["web_url"]

    def get_description(self):
        return self._mr["description"]

    def set_description(self, description):
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
        return self._mr.get("merge_commit_message")

    def set_commit_message(self, message):
        raise errors.UnsupportedOperation(self.set_commit_message, self)

    def get_title(self):
        return self._mr.get("title")

    def set_title(self, title):
        self._update(title=title)

    def _branch_url_from_project(
        self, project_id, branch_name, *, preferred_schemes=None
    ):
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
        return self._branch_url_from_project(
            self._mr["source_project_id"],
            self._mr["source_branch"],
            preferred_schemes=preferred_schemes,
        )

    def get_source_revision(self):
        from breezy.git.mapping import default_mapping

        sha = self._mr["sha"]
        if sha is None:
            return None
        return default_mapping.revision_id_foreign_to_bzr(sha.encode("ascii"))

    def get_target_branch_url(self, *, preferred_schemes=None):
        return self._branch_url_from_project(
            self._mr["target_project_id"],
            self._mr["target_branch"],
            preferred_schemes=preferred_schemes,
        )

    def set_target_branch_name(self, name):
        self._update(target_branch=name)

    def _get_project_name(self, project_id):
        source_project = self.gl._get_project(project_id)
        return source_project["path_with_namespace"]

    def get_source_project(self):
        return self._get_project_name(self._mr["source_project_id"])

    def get_target_project(self):
        return self._get_project_name(self._mr["target_project_id"])

    def is_merged(self):
        return self._mr["state"] == "merged"

    def is_closed(self):
        return self._mr["state"] == "closed"

    def reopen(self):
        return self._update(state_event="reopen")

    def close(self):
        self._update(state_event="close")

    def merge(self, commit_message=None, auto=False):
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
        user = self._mr.get("merge_user")
        if user is None:
            return None
        return user["username"]

    def get_merged_at(self):
        merged_at = self._mr.get("merged_at")
        if merged_at is None:
            return None
        return parse_timestring(merged_at)

    def post_comment(self, body):
        kwargs = {"body": body}
        self.gl._post_merge_request_note(
            self._mr["project_id"], self._mr["iid"], kwargs
        )


def gitlab_url_to_bzr_url(url, name):
    return git_url_to_bzr_url(url, branch=name)


class GitLab(Forge):
    """GitLab forge implementation."""

    supports_merge_proposal_labels = True
    supports_merge_proposal_title = True
    supports_merge_proposal_commit_message = False
    supports_allow_collaboration = True
    merge_proposal_description_format = "markdown"

    def __repr__(self):
        return "<GitLab(%r)>" % self.base_url

    @property
    def base_url(self):
        return self.transport.base

    @property
    def base_hostname(self):
        return urlutils.parse_url(self.base_url)[3]

    def _find_correct_project_name(self, path):
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
        return self.transport.request(
            method,
            urlutils.join(self.base_url, "api", "v4", path),
            headers=self.headers,
            fields=fields,
            body=body,
        )

    def __init__(self, transport, private_token):
        self.transport = transport
        self.headers = {"Private-Token": private_token}
        self._current_user = None

    def _get_user(self, username):
        path = "users/%s" % urlutils.quote(str(username), "")
        response = self._api_request("GET", path)
        if response.status == 404:
            raise KeyError("no such user %s" % username)
        if response.status == 200:
            return json.loads(response.data)
        _unexpected_status(path, response)

    def _get_user_by_email(self, email):
        path = "users?search=%s" % urlutils.quote(str(email), "")
        response = self._api_request("GET", path)
        if response.status == 404:
            raise KeyError("no such user %s" % email)
        if response.status == 200:
            ret = json.loads(response.data)
            if len(ret) != 1:
                raise ValueError("unexpected number of results; %r" % ret)
            return ret[0]
        _unexpected_status(path, response)

    def _get_project(self, project_name, _redirect_checked=False):
        path = "projects/%s" % urlutils.quote(str(project_name), "")
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
        path = "namespaces/" + urlutils.quote(str(namespace), "")
        response = self._api_request("GET", path)
        if response.status == 200:
            return json.loads(response.data)
        if response.status == 404:
            return None
        _unexpected_status(path, response)

    def create_project(self, project_name, summary=None):
        if project_name.endswith(".git"):
            project_name = project_name[:-4]
        if "/" in project_name:
            namespace_path, path = project_name.lstrip("/").rsplit("/", 1)
        else:
            namespace_path = ""
            path = project_name

        namespace = self._get_namespace(namespace_path)
        if namespace is None:
            raise Exception("namespace %s does not exist" % namespace_path)

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
        path = "projects/%s/fork" % urlutils.quote(str(project_name), "")
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
        if not self._current_user:
            self._retrieve_user()
        return self._current_user["username"]

    def get_user_url(self, username):
        return urlutils.join(self.base_url, username)

    def _list_paged(self, path, parameters=None, per_page=None):
        if parameters is None:
            parameters = {}
        else:
            parameters = dict(parameters.items())
        if per_page:
            parameters["per_page"] = str(per_page)
        page = "1"
        while page:
            parameters["page"] = page
            response = self._api_request(
                "GET",
                path + "?" + "&".join(["%s=%s" % item for item in parameters.items()]),
            )
            if response.status == 403:
                raise errors.PermissionDenied(response.text)
            if response.status != 200:
                _unexpected_status(path, response)
            page = response.getheader("X-Next-Page")
            yield from json.loads(response.data)

    def _list_merge_requests(self, author=None, project=None, state=None):
        if project is not None:
            path = "projects/%s/merge_requests" % urlutils.quote(str(project), "")
        else:
            path = "merge_requests"
        parameters = {}
        if state:
            parameters["state"] = state
        if author:
            parameters["author_username"] = urlutils.quote(author, "")
        return self._list_paged(path, parameters, per_page=DEFAULT_PAGE_SIZE)

    def _get_merge_request(self, project, merge_id):
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
        path = "users/%s/projects" % urlutils.quote(str(owner), "")
        parameters = {}
        return self._list_paged(path, parameters, per_page=DEFAULT_PAGE_SIZE)

    def _update_merge_request(self, project_id, iid, mr):
        path = "projects/{}/merge_requests/{}".format(
            urlutils.quote(str(project_id), ""), iid
        )
        response = self._api_request("PUT", path, fields=mr)
        if response.status == 200:
            return json.loads(response.data)
        if response.status == 409:
            raise GitLabConflict(json.loads(response.data).get("message"))
        if response.status == 403:
            raise errors.PermissionDenied(response.text)
        _unexpected_status(path, response)

    def _merge_mr(self, project_id, iid, kwargs):
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
        path = "projects/%s/merge_requests" % source_project_id
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
        (host, project_name, branch_name) = parse_gitlab_branch_url(branch)
        project = self._get_project(project_name)
        return gitlab_url_to_bzr_url(project["ssh_url_to_repo"], branch_name)

    def get_web_url(self, branch):
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
        if tag_selector is None:
            tag_selector = lambda t: False
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
            target_project = self._get_project("{}/{}".format(owner, project))
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
        (host, base_project, base_branch_name) = parse_gitlab_branch_url(base_branch)
        if owner is None:
            owner = self.get_current_user()
        if project is None:
            project = self._get_project(base_project)["path"]
        try:
            target_project = self._get_project("{}/{}".format(owner, project))
        except NoSuchProject:
            raise errors.NotBranchError(
                "{}/{}/{}".format(self.base_url, owner, project)
            )
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
        return GitlabMergeProposalBuilder(self, source_branch, target_branch)

    def iter_proposals(self, source_branch, target_branch, status):
        (source_host, source_project_name, source_branch_name) = (
            parse_gitlab_branch_url(source_branch)
        )
        (target_host, target_project_name, target_branch_name) = (
            parse_gitlab_branch_url(target_branch)
        )
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
        try:
            (host, project, branch_name) = parse_gitlab_branch_url(branch)
        except NotGitLabUrl:
            return False
        return self.base_hostname == host

    def _retrieve_user(self):
        if self._current_user:
            return
        try:
            response = self._api_request("GET", "user")
        except errors.UnexpectedHttpStatus as e:
            if e.code == 401:
                raise GitLabLoginMissing(self.base_url)
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
        base_url = "https://%s" % hostname
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
        try:
            (host, project) = parse_gitlab_url(url)
        except NotGitLabUrl:
            raise UnsupportedForge(url)
        transport = get_transport(
            "https://%s" % host, possible_transports=possible_transports
        )
        credentials = get_credentials_by_url(transport.base)
        if credentials is not None:
            instance = cls(transport, credentials.get("private_token"))
            instance._retrieve_user()
            return instance
        try:
            resp = transport.request(
                "GET",
                "https://{}/api/v4/projects/{}".format(
                    host, urlutils.quote(str(project), "")
                ),
            )
        except errors.UnexpectedHttpStatus:
            raise UnsupportedForge(url)
        except errors.RedirectRequested:
            # GitLab doesn't send redirects for these URLs
            raise UnsupportedForge(url)
        else:
            if not resp.getheader("X-Gitlab-Feature-Category"):
                raise UnsupportedForge(url)
            if resp.status in (200, 401):
                raise GitLabLoginMissing("https://%s/" % host)
            raise UnsupportedForge(url)

    @classmethod
    def iter_instances(cls):
        for name, credentials in iter_tokens():
            yield cls(
                get_transport(credentials["url"]),
                private_token=credentials.get("private_token"),
            )

    def iter_my_proposals(self, status="open", author=None):
        if author is None:
            author = self.get_current_user()
        state = mp_status_to_status(status)
        for mp in self._list_merge_requests(author=author, state=state):
            yield GitLabMergeProposal(self, mp)

    def iter_my_forks(self, owner: Optional[str] = None):
        if owner is None:
            owner = self.get_current_user()
        for project in self._list_projects(owner=owner):
            base_project = project.get("forked_from_project")
            if not base_project:
                continue
            yield project["path_with_namespace"]

    def get_proposal_by_url(self, url: str) -> GitLabMergeProposal:
        try:
            (host, project, merge_id) = parse_gitlab_merge_request_url(url)
        except NotGitLabUrl:
            raise UnsupportedForge(url)
        except NotMergeRequestUrl as e:
            if self.base_hostname == e.host:
                raise
            else:
                raise UnsupportedForge(url)
        if self.base_hostname != host:
            raise UnsupportedForge(url)
        project = self._get_project(project)
        mr = self._get_merge_request(project["path_with_namespace"], merge_id)
        return GitLabMergeProposal(self, mr)

    def delete_project(self, project):
        path = "projects/%s" % urlutils.quote(str(project), "")
        response = self._api_request("DELETE", path)
        if response.status == 404:
            raise NoSuchProject(project)
        if response.status != 202:
            _unexpected_status(path, response)


class GitlabMergeProposalBuilder(MergeProposalBuilder):
    def __init__(self, gl, source_branch, target_branch):
        self.gl = gl
        self.source_branch = source_branch
        (self.source_host, self.source_project_name, self.source_branch_name) = (
            parse_gitlab_branch_url(source_branch)
        )
        self.target_branch = target_branch
        (self.target_host, self.target_project_name, self.target_branch_name) = (
            parse_gitlab_branch_url(target_branch)
        )
        if self.source_host != self.target_host:
            raise DifferentGitLabInstances(self.source_host, self.target_host)

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        info = []
        info.append("Gitlab instance: %s\n" % self.target_host)
        info.append("Source: %s\n" % self.source_branch.user_url)
        info.append("Target: %s\n" % self.target_branch.user_url)
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
        # https://docs.gitlab.com/ee/api/merge_requests.html#create-mr
        if prerequisite_branch is not None:
            raise PrerequisiteBranchUnsupported(self)
        # Note that commit_message is ignored, since Gitlab doesn't support it.
        source_project = self.gl._get_project(self.source_project_name)
        target_project = self.gl._get_project(self.target_project_name)
        if title is None:
            title = determine_title(description)
        if work_in_progress:
            title = "WIP: %s" % title
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
                raise SourceNotDerivedFromTarget(self.source_branch, self.target_branch)
            raise
        return GitLabMergeProposal(self.gl, merge_request)


def register_gitlab_instance(shortname, url):
    """Register a gitlab instance.

    :param shortname: Short name (e.g. "gitlab")
    :param url: URL to the gitlab instance
    """
    from breezy.bugtracker import ProjectIntegerBugTracker, tracker_registry

    tracker_registry.register(
        shortname, ProjectIntegerBugTracker(shortname, url + "/{project}/issues/{id}")
    )
