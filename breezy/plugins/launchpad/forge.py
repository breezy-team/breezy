# Copyright (C) 2010, 2011 Canonical Ltd
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

"""Support for Launchpad."""

import re
import shutil
import tempfile

from ... import branch as _mod_branch
from ... import controldir, errors, urlutils
from ...forge import (
    AutoMergeUnsupported,
    Forge,
    LabelsUnsupported,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    TitleUnsupported,
    UnsupportedForge,
)
from ...git.urls import git_url_to_bzr_url
from ...lazy_import import lazy_import
from ...trace import mutter

lazy_import(
    globals(),
    """
from breezy.plugins.launchpad import (
    uris as lp_uris,
    )

""",
)
from ...transport import get_transport

DEFAULT_PREFERRED_SCHEMES = ["ssh", "http"]

GIT_SCHEME_MAP = {
    "ssh": "git+ssh://git.launchpad.net/",
    "http": "https://git.launchpad.net/",
    "https": "https://git.launchpad.net/",
}


# TODO(jelmer): Make selection of launchpad staging a configuration option.


def status_to_lp_mp_statuses(status):
    """Convert a general status to Launchpad-specific merge proposal statuses.

    Args:
        status: A status string, one of 'open', 'closed', 'merged', or 'all'.

    Returns:
        A list of Launchpad merge proposal status strings corresponding to
        the input status.
    """
    statuses = []
    if status in ("open", "all"):
        statuses.extend(
            [
                "Work in progress",
                "Needs review",
                "Approved",
                "Code failed to merge",
                "Queued",
            ]
        )
    if status in ("closed", "all"):
        statuses.extend(["Rejected", "Superseded"])
    if status in ("merged", "all"):
        statuses.append("Merged")
    return statuses


def plausible_launchpad_url(url):
    """Check if a URL appears to be a Launchpad URL.

    Args:
        url: The URL string to check, or None.

    Returns:
        True if the URL appears to be a Launchpad URL (either lp: scheme
        or a URL pointing to bazaar/git.launchpad.net), False otherwise.
    """
    if url is None:
        return False
    if url.startswith("lp:"):
        return True
    regex = re.compile(
        r"([a-z]*\+)*(bzr\+ssh|http|ssh|git|https)" r"://(bazaar|git).*\.launchpad\.net"
    )
    return bool(regex.match(url))


class WebserviceFailure(Exception):
    """Exception raised when a webservice call fails.

    This exception wraps failures from Launchpad webservice API calls,
    providing cleaner error handling.
    """

    def __init__(self, message):
        """Initialize the WebserviceFailure exception.

        Args:
            message: The error message describing the failure.
        """
        self.message = message


def _call_webservice(call, *args, **kwargs):
    """Make a call to the webservice, wrapping failures.

    :param call: The call to make.
    :param *args: *args for the call.
    :param **kwargs: **kwargs for the call.
    :return: The result of calling call(*args, *kwargs).
    """
    from lazr.restfulclient import errors as restful_errors

    try:
        return call(*args, **kwargs)
    except restful_errors.HTTPError as e:
        error_lines = []
        for line in e.content.splitlines():
            if line.startswith(b"Traceback (most recent call last):"):
                break
            error_lines.append(line)
        raise WebserviceFailure(b"".join(error_lines)) from e


class LaunchpadMergeProposal(MergeProposal):
    """A merge proposal on Launchpad.

    This class provides an interface to interact with Launchpad merge proposals,
    supporting both Bazaar branches and Git repositories.
    """

    supports_auto_merge = False

    def __init__(self, mp):
        """Initialize a LaunchpadMergeProposal.

        Args:
            mp: The Launchpad merge proposal object from the API.
        """
        self._mp = mp

    def get_web_url(self):
        """Get the web URL for this merge proposal.

        Returns:
            The web URL where this merge proposal can be viewed.
        """
        return self._mp.web_link

    def get_source_branch_url(self, *, preferred_schemes=None):
        """Get the URL of the source branch for this merge proposal.

        Args:
            preferred_schemes: Optional list of preferred URL schemes (ignored for now).

        Returns:
            The URL of the source branch.
        """
        # TODO(jelmer): Honor preferred_schemes
        if self._mp.source_branch:
            return self._mp.source_branch.bzr_identity
        else:
            return git_url_to_bzr_url(
                self._mp.source_git_repository.git_identity,
                ref=self._mp.source_git_path.encode("utf-8"),
            )

    def get_source_revision(self):
        """Get the revision ID of the source branch tip.

        Returns:
            The revision ID (bytes) of the source branch tip, or None
            if no revision is available.
        """
        if self._mp.source_branch:
            last_scanned_id = self._mp.source_branch.last_scanned_id
            if last_scanned_id:
                return last_scanned_id.encode("utf-8")
            else:
                return None
        else:
            from ...git.mapping import default_mapping

            git_repo = self._mp.source_git_repository
            git_ref = git_repo.getRefByPath(path=self._mp.source_git_path)
            sha = git_ref.commit_sha1
            if sha is None:
                return None
            return default_mapping.revision_id_foreign_to_bzr(sha.encode("ascii"))

    def get_target_branch_url(self, *, preferred_schemes=None):
        """Get the URL of the target branch for this merge proposal.

        Args:
            preferred_schemes: Optional list of preferred URL schemes (ignored for now).

        Returns:
            The URL of the target branch.
        """
        # TODO(jelmer): Honor preferred_schemes
        if self._mp.target_branch:
            return self._mp.target_branch.bzr_identity
        else:
            return git_url_to_bzr_url(
                self._mp.target_git_repository.git_identity,
                ref=self._mp.target_git_path.encode("utf-8"),
            )

    def set_target_branch_name(self, name):
        """Set the name of the target branch.

        Args:
            name: The new name for the target branch.

        Raises:
            NotImplementedError: The Launchpad API doesn't support changing
                branch names.
        """
        # The launchpad API doesn't support changing branch names today.
        raise NotImplementedError(self.set_target_branch_name)

    @property
    def url(self):
        """Get the canonical URL for this merge proposal.

        Returns:
            The canonical URL for this merge proposal.
        """
        return lp_uris.canonical_url(self._mp)

    def is_merged(self):
        """Check if this merge proposal has been merged.

        Returns:
            True if the merge proposal has been merged, False otherwise.
        """
        return self._mp.queue_status == "Merged"

    def is_closed(self):
        """Check if this merge proposal has been closed without merging.

        Returns:
            True if the merge proposal has been rejected or superseded, False otherwise.
        """
        return self._mp.queue_status in ("Rejected", "Superseded")

    def reopen(self):
        """Reopen this merge proposal for review.

        Changes the status to 'Needs review' to reopen the merge proposal.
        """
        self._mp.setStatus(status="Needs review")

    def get_description(self):
        """Get the description of this merge proposal.

        Returns:
            The description text of the merge proposal.
        """
        return self._mp.description

    def set_description(self, description):
        """Set the description of this merge proposal.

        Args:
            description: The new description text for the merge proposal.
        """
        self._mp.description = description
        self._mp.lp_save()

    def get_commit_message(self):
        """Get the commit message for this merge proposal.

        Returns:
            The commit message that will be used when merging.
        """
        return self._mp.commit_message

    def get_title(self):
        """Get the title of this merge proposal.

        Raises:
            TitleUnsupported: Launchpad doesn't support merge proposal titles.
        """
        raise TitleUnsupported(self)

    def set_title(self):
        """Set the title of this merge proposal.

        Raises:
            TitleUnsupported: Launchpad doesn't support merge proposal titles.
        """
        raise TitleUnsupported(self)

    def set_commit_message(self, commit_message):
        """Set the commit message for this merge proposal.

        Args:
            commit_message: The commit message to use when merging.
        """
        self._mp.commit_message = commit_message
        self._mp.lp_save()

    def close(self):
        """Close this merge proposal without merging.

        Sets the status to 'Rejected' to close the merge proposal.
        """
        self._mp.setStatus(status="Rejected")

    def can_be_merged(self):
        """Check if this merge proposal can be merged cleanly.

        Returns:
            True if the merge proposal can be merged without conflicts,
            False if there are conflicts. If no preview diff is available,
            assumes it can be merged.
        """
        if not self._mp.preview_diff:
            # Maybe?
            return True
        return not bool(self._mp.preview_diff.conflicts)

    def get_merged_by(self):
        """Get the name of who merged this merge proposal.

        Returns:
            The name of the person who merged the proposal, or None
            if the proposal hasn't been merged or the information
            is not available.
        """
        merge_reporter = self._mp.merge_reporter
        if merge_reporter is None:
            return None
        return merge_reporter.name

    def get_merged_at(self):
        """Get the date and time when this merge proposal was merged.

        Returns:
            A datetime object representing when the merge proposal was merged,
            or None if it hasn't been merged.
        """
        return self._mp.date_merged

    def merge(self, commit_message=None, auto=False):
        """Merge the source branch into the target branch.

        Args:
            commit_message: Optional commit message to use. If None, uses
                the merge proposal's commit message.
            auto: If True, attempt auto-merge (not supported by Launchpad).

        Raises:
            AutoMergeUnsupported: If auto=True, as Launchpad doesn't support auto-merge.
        """
        if auto:
            raise AutoMergeUnsupported(self)
        target_branch = _mod_branch.Branch.open(self.get_target_branch_url())
        source_branch = _mod_branch.Branch.open(self.get_source_branch_url())
        # TODO(jelmer): Ideally this would use a memorytree, but merge doesn't
        # support that yet.
        # tree = target_branch.create_memorytree()
        tmpdir = tempfile.mkdtemp()
        try:
            tree = target_branch.create_checkout(to_location=tmpdir, lightweight=True)
            tree.merge_from_branch(source_branch)
            tree.commit(commit_message or self._mp.commit_message)
        finally:
            shutil.rmtree(tmpdir)

    def post_comment(self, body):
        """Post a comment on this merge proposal.

        Args:
            body: The text content of the comment to post.
        """
        self._mp.createComment(content=body)


class Launchpad(Forge):
    """The Launchpad hosting service."""

    # https://bugs.launchpad.net/launchpad/+bug/397676
    supports_merge_proposal_labels = False

    supports_merge_proposal_title = False

    supports_merge_proposal_commit_message = True

    supports_allow_collaboration = False

    merge_proposal_description_format = "plain"

    def __init__(self, service_root):
        """Initialize the Launchpad forge.

        Args:
            service_root: The service root URL for the Launchpad API.
        """
        self._api_base_url = service_root
        self._launchpad = None

    @property
    def name(self):
        """Get the display name of this Launchpad instance.

        Returns:
            'Launchpad' for the main instance, or 'Launchpad at <url>' for others.
        """
        if self._api_base_url == lp_uris.LPNET_SERVICE_ROOT:
            return "Launchpad"
        return f"Launchpad at {self.base_url}"

    @property
    def launchpad(self):
        """Get the Launchpad API client.

        Returns:
            A lazily-initialized Launchpad API client instance.
        """
        if self._launchpad is None:
            from .lp_api import connect_launchpad

            self._launchpad = connect_launchpad(self._api_base_url, version="devel")
        return self._launchpad

    @property
    def base_url(self):
        """Get the base web URL for this Launchpad instance.

        Returns:
            The base web URL corresponding to the service root.
        """
        return lp_uris.web_root_for_service_root(self._api_base_url)

    def __repr__(self):
        """Return a string representation of this Launchpad instance.

        Returns:
            A string representation showing the service root URL.
        """
        return f"Launchpad(service_root={self._api_base_url})"

    def get_current_user(self):
        """Get the name of the current authenticated user.

        Returns:
            The username of the current authenticated user.
        """
        return self.launchpad.me.name

    def get_user_url(self, username):
        """Get the web URL for a user profile.

        Args:
            username: The username to get the profile URL for.

        Returns:
            The web URL of the user's Launchpad profile.
        """
        return self.launchpad.people[username].web_link

    def hosts(self, branch):
        """Check if this forge hosts the given branch.

        Args:
            branch: The branch to check.

        Returns:
            True if this Launchpad instance hosts the branch, False otherwise.
        """
        # TODO(jelmer): staging vs non-staging?
        return plausible_launchpad_url(branch.user_url)

    @classmethod
    def probe_from_hostname(cls, hostname, possible_transports=None):
        """Probe if the given hostname is supported by Launchpad.

        Args:
            hostname: The hostname to check.
            possible_transports: Optional list of possible transports (unused).

        Returns:
            A Launchpad forge instance if the hostname is supported.

        Raises:
            UnsupportedForge: If the hostname is not a Launchpad hostname.
        """
        if re.match(hostname, r"(bazaar|git).*\.launchpad\.net"):
            return Launchpad(lp_uris.LPNET_SERVICE_ROOT)
        raise UnsupportedForge(hostname)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        """Probe if the given URL is supported by Launchpad.

        Args:
            url: The URL to check.
            possible_transports: Optional list of possible transports (unused).

        Returns:
            A Launchpad forge instance if the URL is supported.

        Raises:
            UnsupportedForge: If the URL is not a Launchpad URL.
        """
        if plausible_launchpad_url(url):
            return Launchpad(lp_uris.LPNET_SERVICE_ROOT)
        raise UnsupportedForge(url)

    def _get_lp_git_ref_from_branch(self, branch):
        """Get the Launchpad Git repository and reference from a branch.

        Args:
            branch: The branch to get the Git reference for.

        Returns:
            A tuple of (repository, reference) Launchpad objects.
        """
        url, params = urlutils.split_segment_parameters(branch.user_url)
        (_scheme, _user, _password, _host, _port, path) = urlutils.parse_url(url)
        repo_lp = self.launchpad.git_repositories.getByPath(path=path.strip("/"))
        try:
            ref_path = params["ref"]
        except KeyError:
            branch_name = params.get("branch", branch.name)
            if branch_name:
                ref_path = f"refs/heads/{branch_name}"
            else:
                ref_path = repo_lp.default_branch
        ref_lp = repo_lp.getRefByPath(path=ref_path)
        return (repo_lp, ref_lp)

    def _get_derived_git_path(self, base_path, owner, project):
        """Generate a Git repository path for a derived branch.

        Args:
            base_path: The path of the base repository.
            owner: The owner of the derived repository.
            project: The project name, or None to derive from base_path.

        Returns:
            A path string for the derived Git repository.
        """
        base_repo = self.launchpad.git_repositories.getByPath(path=base_path)
        if project is None:
            project = urlutils.parse_url(base_repo.git_ssh_url)[-1].strip("/")
        if project.startswith("~"):
            project = "/".join(base_path.split("/")[1:])
        # TODO(jelmer): Surely there is a better way of creating one of these
        # URLs?
        return f"~{owner}/{project}"

    def _publish_git(
        self,
        local_branch,
        base_path,
        name,
        owner,
        project=None,
        revision_id=None,
        overwrite=False,
        allow_lossy=True,
        tag_selector=None,
    ):
        if tag_selector is None:

            def tag_selector(t):
                return False

        to_path = self._get_derived_git_path(base_path, owner, project)
        to_transport = get_transport(GIT_SCHEME_MAP["ssh"] + to_path)
        try:
            dir_to = controldir.ControlDir.open_from_transport(to_transport)
        except errors.NotBranchError:
            # Didn't find anything
            dir_to = None

        if dir_to is None:
            try:
                br_to = local_branch.create_clone_on_transport(
                    to_transport,
                    revision_id=revision_id,
                    name=name,
                    tag_selector=tag_selector,
                )
            except errors.NoRoundtrippingSupport:
                br_to = local_branch.create_clone_on_transport(
                    to_transport,
                    revision_id=revision_id,
                    name=name,
                    lossy=True,
                    tag_selector=tag_selector,
                )
        else:
            try:
                dir_to = dir_to.push_branch(
                    local_branch,
                    revision_id,
                    overwrite=overwrite,
                    name=name,
                    tag_selector=tag_selector,
                )
            except errors.NoRoundtrippingSupport:
                if not allow_lossy:
                    raise
                dir_to = dir_to.push_branch(
                    local_branch,
                    revision_id,
                    overwrite=overwrite,
                    name=name,
                    lossy=True,
                    tag_selector=tag_selector,
                )
            br_to = dir_to.target_branch
        return br_to, (f"https://git.launchpad.net/{to_path}/+ref/{name}")

    def get_push_url(self, branch):
        """Get the URL for pushing to the given branch.

        Args:
            branch: The branch to get the push URL for.

        Returns:
            The URL that should be used for pushing to this branch.

        Raises:
            AssertionError: If the branch URL doesn't match a known VCS pattern.
        """
        (vcs, _user, _password, path, params) = self._split_url(branch.user_url)
        if vcs == "git":
            return urlutils.join_segment_parameters(
                GIT_SCHEME_MAP["ssh"] + path, params
            )
        else:
            raise AssertionError("Only git repositories are supported")

    def _split_url(self, url):
        """Split a Launchpad URL into its components.

        Args:
            url: The URL to split.

        Returns:
            A tuple of (vcs, user, password, path, params) where vcs is
            either 'bzr' or 'git'.

        Raises:
            ValueError: If the host doesn't match a known VCS pattern.
        """
        url, params = urlutils.split_segment_parameters(url)
        (_scheme, user, password, host, _port, path) = urlutils.parse_url(url)
        path = path.strip("/")
        if host.startswith("git."):
            vcs = "git"
        else:
            raise ValueError(f"unknown host {host}")
        return (vcs, user, password, path, params)

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
        """Publish a branch to the site, derived from base_branch.

        :param base_branch: branch to derive the new branch from
        :param new_branch: branch to publish
        :param name: Name of the new branch on the remote host
        :param project: Optional project name
        :param owner: Optional owner
        :return: resulting branch
        """
        if owner is None:
            owner = self.launchpad.me.name
        (base_vcs, _base_user, _base_password, base_path, _base_params) = (
            self._split_url(base_branch.user_url)
        )
        # TODO(jelmer): Prevent publishing to development focus
        if base_vcs == "git":
            return self._publish_git(
                local_branch,
                base_path,
                name,
                project=project,
                owner=owner,
                revision_id=revision_id,
                overwrite=overwrite,
                allow_lossy=allow_lossy,
                tag_selector=tag_selector,
            )
        else:
            raise AssertionError("Only git repositories are supported")

    def get_derived_branch(
        self, base_branch, name, project=None, owner=None, preferred_schemes=None
    ):
        """Get a derived branch that has been previously published.

        Args:
            base_branch: The base branch to derive from.
            name: The name of the derived branch.
            project: The project name, or None to derive from base_branch.
            owner: The owner of the derived branch, or None to use current user.
            preferred_schemes: List of preferred URL schemes.

        Returns:
            The derived branch object.

        Raises:
            AssertionError: If no supported schemes are available or URL is invalid.
        """
        if preferred_schemes is None:
            preferred_schemes = DEFAULT_PREFERRED_SCHEMES
        if owner is None:
            owner = self.launchpad.me.name
        (base_vcs, _base_user, _base_password, base_path, _base_params) = (
            self._split_url(base_branch.user_url)
        )
        if base_vcs == "git":
            to_path = self._get_derived_git_path(base_path.strip("/"), owner, project)
            for scheme in preferred_schemes:
                try:
                    prefix = GIT_SCHEME_MAP[scheme]
                except KeyError:
                    continue
                to_url = urlutils.join_segment_parameters(
                    prefix + to_path, {"branch": name}
                )
                return _mod_branch.Branch.open(to_url)
            raise AssertionError(f"no supported schemes: {preferred_schemes!r}")
        else:
            raise AssertionError("Only git repositories are supported")

    def iter_proposals(self, source_branch, target_branch, status="open"):
        """Iterate over merge proposals between the given branches.

        Args:
            source_branch: The source branch of the merge proposals.
            target_branch: The target branch of the merge proposals.
            status: The status filter ('open', 'closed', 'merged', or 'all').

        Yields:
            LaunchpadMergeProposal objects matching the criteria.

        Raises:
            AssertionError: If the target branch URL is not a valid Launchpad URL.
        """
        (base_vcs, _base_user, _base_password, _base_path, _base_params) = (
            self._split_url(target_branch.user_url)
        )
        statuses = status_to_lp_mp_statuses(status)
        if base_vcs == "git":
            (source_repo_lp, source_branch_lp) = self._get_lp_git_ref_from_branch(
                source_branch
            )
            (target_repo_lp, target_branch_lp) = self._get_lp_git_ref_from_branch(
                target_branch
            )
            for mp in target_branch_lp.getMergeProposals(status=statuses):
                if (
                    target_branch_lp.path != mp.target_git_path
                    or target_repo_lp != mp.target_git_repository
                    or source_branch_lp.path != mp.source_git_path
                    or source_repo_lp != mp.source_git_repository
                ):
                    continue
                yield LaunchpadMergeProposal(mp)
        else:
            raise AssertionError("Only git repositories are supported")

    def get_proposer(self, source_branch, target_branch):
        """Get a merge proposal builder for the given branches.

        Args:
            source_branch: The source branch for the merge proposal.
            target_branch: The target branch for the merge proposal.

        Returns:
            A merge proposal builder appropriate for the VCS type.

        Raises:
            AssertionError: If the target branch URL is not a valid Launchpad URL.
        """
        (base_vcs, _base_user, _base_password, _base_path, _base_params) = (
            self._split_url(target_branch.user_url)
        )
        if base_vcs == "git":
            return LaunchpadGitMergeProposalBuilder(self, source_branch, target_branch)
        else:
            raise AssertionError("Only git repositories are supported")

    @classmethod
    def iter_instances(cls):
        """Iterate over available Launchpad instances with credentials.

        Yields:
            Launchpad forge instances for which credentials are available.
        """
        from . import lp_api

        credential_store = lp_api.get_credential_store()
        for service_root in set(lp_uris.service_roots.values()):
            auth_engine = lp_api.get_auth_engine(service_root)
            creds = credential_store.load(auth_engine.unique_consumer_id)
            if creds is not None:
                yield cls(service_root)

    def iter_my_proposals(self, status="open", author=None):
        """Iterate over merge proposals authored by current user or specified author.

        Args:
            status: The status filter ('open', 'closed', 'merged', or 'all').
            author: The author to filter by, or None for current user.

        Yields:
            LaunchpadMergeProposal objects matching the criteria.
        """
        statuses = status_to_lp_mp_statuses(status)
        author_obj = self.launchpad.me if author is None else self._getPerson(author)
        for mp in author_obj.getMergeProposals(status=statuses):
            yield LaunchpadMergeProposal(mp)

    def iter_my_forks(self, owner=None):
        """Iterate over forks owned by the current user or specified owner.

        Args:
            owner: The owner to filter by, or None for current user.

        Returns:
            An empty iterator, as Launchpad doesn't have the concept of "forks".
        """
        # Launchpad doesn't really have the concept of "forks"
        return iter([])

    def _getPerson(self, person):
        """Get a Launchpad person object by name or email.

        Args:
            person: A person name or email address.

        Returns:
            The corresponding Launchpad person object.
        """
        if "@" in person:
            return self.launchpad.people.getByEmail(email=person)
        else:
            return self.launchpad.people[person]

    def get_web_url(self, branch):
        """Get the web URL for viewing a branch.

        Args:
            branch: The branch to get the web URL for.

        Returns:
            The web URL where the branch can be viewed.

        Raises:
            AssertionError: If the branch URL doesn't match a known VCS pattern.
        """
        (vcs, _user, _password, _path, _params) = self._split_url(branch.user_url)
        if vcs == "git":
            (_repo_lp, ref_lp) = self._get_lp_git_ref_from_branch(branch)
            return ref_lp.web_link
        else:
            raise AssertionError("Only git repositories are supported")

    def get_proposal_by_url(self, url):
        """Get a merge proposal by its URL.

        Args:
            url: The URL of the merge proposal.

        Returns:
            A LaunchpadMergeProposal object.

        Raises:
            UnsupportedForge: If the URL is not a Launchpad code domain.
        """
        # Launchpad doesn't have a way to find a merge proposal by URL.
        (_scheme, _user, _password, host, _port, path) = urlutils.parse_url(url)
        LAUNCHPAD_CODE_DOMAINS = [
            f"code.{domain}" for domain in lp_uris.LAUNCHPAD_DOMAINS.values()
        ]
        if host not in LAUNCHPAD_CODE_DOMAINS:
            raise UnsupportedForge(url)
        # TODO(jelmer): Check if this is a launchpad URL. Otherwise, raise
        # UnsupportedForge
        # See https://api.launchpad.net/devel/#branch_merge_proposal
        # the syntax is:
        # https://api.launchpad.net/devel/~<author.name>/<project.name>/<branch.name>/+merge/<id>
        api_url = str(self.launchpad._root_uri) + path
        mp = self.launchpad.load(api_url)
        return LaunchpadMergeProposal(mp)

    def create_project(self, path, summary=None):
        """Create a new project on Launchpad.

        Args:
            path: The project name/path.
            summary: Optional project summary.
        """
        self.launchpad.projects.new_project(
            display_name=path, name=path, summary=summary, title=path
        )


class LaunchpadGitMergeProposalBuilder(MergeProposalBuilder):
    """Merge proposal builder for Launchpad Git repositories.

    This class handles the creation of merge proposals between Git branches
    hosted on Launchpad.
    """

    def __init__(
        self,
        lp_host,
        source_branch,
        target_branch,
        staging=None,
        approve=None,
        fixes=None,
    ):
        """Constructor.

        :param source_branch: The branch to propose for merging.
        :param target_branch: The branch to merge into.
        :param staging: If True, propose the merge against staging instead of
            production.
        :param approve: If True, mark the new proposal as approved immediately.
            This is useful when a project permits some things to be approved
            by the submitter (e.g. merges between release and deployment
            branches).
        """
        self.lp_host = lp_host
        self.launchpad = lp_host.launchpad
        self.source_branch = source_branch
        (
            self.source_repo_lp,
            self.source_branch_lp,
        ) = self.lp_host._get_lp_git_ref_from_branch(source_branch)
        if target_branch is None:
            self.target_branch_lp = self.source_branch.get_target()
            self.target_branch = _mod_branch.Branch.open(
                self.target_branch_lp.git_https_url
            )
        else:
            self.target_branch = target_branch
            (
                self.target_repo_lp,
                self.target_branch_lp,
            ) = self.lp_host._get_lp_git_ref_from_branch(target_branch)
        self.approve = approve
        self.fixes = fixes

    def get_infotext(self):
        """Determine the initial comment for the merge proposal.

        Returns:
            A formatted string containing source and target branch URLs.
        """
        info = [f"Source: {self.source_branch.user_url}\n"]
        info.append(f"Target: {self.target_branch.user_url}\n")
        return "".join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        Uses hooks to generate an initial body based on the changes between
        the source and target branches.

        Returns:
            A string body for the merge proposal, or None if no hooks are configured.
        """
        if not self.hooks["merge_proposal_body"]:
            return None

        def list_modified_files():
            lca_tree = self.source_branch_lp.find_lca_tree(self.target_branch_lp)
            source_tree = self.source_branch.basis_tree()
            files = modified_files(lca_tree, source_tree)
            return list(files)

        with self.target_branch.lock_read(), self.source_branch.lock_read():
            body = None
            for hook in self.hooks["merge_proposal_body"]:
                body = hook(
                    {
                        "target_branch": self.target_branch,
                        "modified_files_callback": list_modified_files,
                        "old_body": body,
                    }
                )
            return body

    def check_proposal(self):
        """Check that the submission is sensible.

        Validates that the source and target branches are different and that
        a merge proposal doesn't already exist between them.

        Raises:
            CommandError: If source and target branches are the same.
            MergeProposalExists: If a merge proposal already exists.
        """
        if self.source_branch_lp.self_link == self.target_branch_lp.self_link:
            raise errors.CommandError("Source and target branches must be different.")
        for mp in self.source_branch_lp.landing_targets:
            if mp.queue_status in ("Merged", "Rejected"):
                continue
            if mp.target_branch.self_link == self.target_branch_lp.self_link:
                raise MergeProposalExists(lp_uris.canonical_url(mp))

    def approve_proposal(self, mp):
        """Approve the merge proposal.

        Creates an approval comment and sets the status to 'Approved'.

        Args:
            mp: The Launchpad merge proposal object to approve.
        """
        with self.source_branch.lock_read():
            _call_webservice(
                mp.createComment,
                vote="Approve",
                subject="",  # Use the default subject.
                content="Rubberstamp! Proposer approves of own proposal.",
            )
            _call_webservice(
                mp.setStatus,
                status="Approved",
                revid=self.source_branch.last_revision(),
            )

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
        delete_source_after_merge: bool | None = False,
    ):
        """Create a merge proposal on Launchpad for Git branches.

        Args:
            description: The description text for the merge proposal.
            title: The title (not supported by Launchpad, will raise exception
                if provided).
            reviewers: List of reviewer names.
            labels: Labels for the proposal (not supported by Launchpad).
            prerequisite_branch: Optional prerequisite branch that must be merged first.
            commit_message: Optional commit message for when the proposal is merged.
            work_in_progress: If True, mark as work in progress (not needing review).
            allow_collaboration: Allow collaboration (ignored by Launchpad).
            delete_source_after_merge: Delete source after merge (ignored by Launchpad).

        Returns:
            A LaunchpadMergeProposal object representing the created proposal.

        Raises:
            LabelsUnsupported: If labels are provided.
            MergeProposalExists: If a merge proposal already exists.
            WebserviceFailure: If the Launchpad API call fails.
        """
        if labels:
            raise LabelsUnsupported(self)
        if prerequisite_branch is not None:
            (
                _prereq_repo_lp,
                prereq_branch_lp,
            ) = self.lp_host._get_lp_git_ref_from_branch(prerequisite_branch)
        else:
            prereq_branch_lp = None
        if reviewers is None:
            reviewers = []
        if delete_source_after_merge:
            mutter(
                "Ignoring request to delete source after merge, "
                "which launchpad does not support"
            )
        try:
            mp = _call_webservice(
                self.source_branch_lp.createMergeProposal,
                merge_target=self.target_branch_lp,
                merge_prerequisite=prereq_branch_lp,
                initial_comment=description.strip(),
                commit_message=commit_message,
                needs_review=(not work_in_progress),
                reviewers=[
                    self.launchpad.people[reviewer].self_link for reviewer in reviewers
                ],
                review_types=[None for reviewer in reviewers],
            )
        except WebserviceFailure as e:
            # Urgh.
            if (
                "There is already a branch merge proposal registered for branch "
            ) in e.message:
                raise MergeProposalExists(self.source_branch.user_url) from e
            raise
        if self.approve:
            self.approve_proposal(mp)
        if self.fixes:
            if self.fixes.startswith("lp:"):
                self.fixes = self.fixes[3:]
            _call_webservice(mp.linkBug, bug=self.launchpad.bugs[int(self.fixes)])
        return LaunchpadMergeProposal(mp)


def modified_files(old_tree, new_tree):
    """Return a generator of paths in the new tree with modified contents.

    Args:
        old_tree: The old tree to compare against.
        new_tree: The new tree to find modifications in.

    Yields:
        File paths (as strings) for files that have modified contents
        between the old and new trees.
    """
    for change in new_tree.iter_changes(old_tree):
        if change.changed_content and change.kind[1] == "file":
            yield str(change.path[1])
