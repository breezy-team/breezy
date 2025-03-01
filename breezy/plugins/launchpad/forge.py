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
from typing import Any, List, Optional

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
    lp_api,
    uris as lp_uris,
    )

""",
)
from ...transport import get_transport

DEFAULT_PREFERRED_SCHEMES = ["ssh", "http"]

BZR_SCHEME_MAP = {
    "ssh": "bzr+ssh://bazaar.launchpad.net/",
    "http": "https://bazaar.launchpad.net/",
    "https": "https://bazaar.launchpad.net/",
}

GIT_SCHEME_MAP = {
    "ssh": "git+ssh://git.launchpad.net/",
    "http": "https://git.launchpad.net/",
    "https": "https://git.launchpad.net/",
}


# TODO(jelmer): Make selection of launchpad staging a configuration option.


def status_to_lp_mp_statuses(status):
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
    if url is None:
        return False
    if url.startswith("lp:"):
        return True
    regex = re.compile(
        r"([a-z]*\+)*(bzr\+ssh|http|ssh|git|https)" r"://(bazaar|git).*\.launchpad\.net"
    )
    return bool(regex.match(url))


class WebserviceFailure(Exception):
    def __init__(self, message):
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
        raise WebserviceFailure(b"".join(error_lines))


class LaunchpadMergeProposal(MergeProposal):
    supports_auto_merge = False

    def __init__(self, mp):
        self._mp = mp

    def get_web_url(self):
        return self._mp.web_link

    def get_source_branch_url(self, *, preferred_schemes=None):
        # TODO(jelmer): Honor preferred_schemes
        if self._mp.source_branch:
            return self._mp.source_branch.bzr_identity
        else:
            return git_url_to_bzr_url(
                self._mp.source_git_repository.git_identity,
                ref=self._mp.source_git_path.encode("utf-8"),
            )

    def get_source_revision(self):
        if self._mp.source_branch:
            last_scanned_id = self._mp.source_branch.last_scanned_id
            if last_scanned_id:
                return last_scanned_id.encode("utf-8")
            else:
                return None
        else:
            from breezy.git.mapping import default_mapping

            git_repo = self._mp.source_git_repository
            git_ref = git_repo.getRefByPath(path=self._mp.source_git_path)
            sha = git_ref.commit_sha1
            if sha is None:
                return None
            return default_mapping.revision_id_foreign_to_bzr(sha.encode("ascii"))

    def get_target_branch_url(self, *, preferred_schemes=None):
        # TODO(jelmer): Honor preferred_schemes
        if self._mp.target_branch:
            return self._mp.target_branch.bzr_identity
        else:
            return git_url_to_bzr_url(
                self._mp.target_git_repository.git_identity,
                ref=self._mp.target_git_path.encode("utf-8"),
            )

    def set_target_branch_name(self, name):
        # The launchpad API doesn't support changing branch names today.
        raise NotImplementedError(self.set_target_branch_name)

    @property
    def url(self):
        return lp_uris.canonical_url(self._mp)

    def is_merged(self):
        return self._mp.queue_status == "Merged"

    def is_closed(self):
        return self._mp.queue_status in ("Rejected", "Superseded")

    def reopen(self):
        self._mp.setStatus(status="Needs review")

    def get_description(self):
        return self._mp.description

    def set_description(self, description):
        self._mp.description = description
        self._mp.lp_save()

    def get_commit_message(self):
        return self._mp.commit_message

    def get_title(self):
        raise TitleUnsupported(self)

    def set_title(self):
        raise TitleUnsupported(self)

    def set_commit_message(self, commit_message):
        self._mp.commit_message = commit_message
        self._mp.lp_save()

    def close(self):
        self._mp.setStatus(status="Rejected")

    def can_be_merged(self):
        if not self._mp.preview_diff:
            # Maybe?
            return True
        return not bool(self._mp.preview_diff.conflicts)

    def get_merged_by(self):
        merge_reporter = self._mp.merge_reporter
        if merge_reporter is None:
            return None
        return merge_reporter.name

    def get_merged_at(self):
        return self._mp.date_merged

    def merge(self, commit_message=None, auto=False):
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
        self._api_base_url = service_root
        self._launchpad = None

    @property
    def name(self):
        if self._api_base_url == lp_uris.LPNET_SERVICE_ROOT:
            return "Launchpad"
        return "Launchpad at {}".format(self.base_url)

    @property
    def launchpad(self):
        if self._launchpad is None:
            self._launchpad = lp_api.connect_launchpad(
                self._api_base_url, version="devel"
            )
        return self._launchpad

    @property
    def base_url(self):
        return lp_uris.web_root_for_service_root(self._api_base_url)

    def __repr__(self):
        return "Launchpad(service_root={})".format(self._api_base_url)

    def get_current_user(self):
        return self.launchpad.me.name

    def get_user_url(self, username):
        return self.launchpad.people[username].web_link

    def hosts(self, branch):
        # TODO(jelmer): staging vs non-staging?
        return plausible_launchpad_url(branch.user_url)

    @classmethod
    def probe_from_hostname(cls, hostname, possible_transports=None):
        if re.match(hostname, r"(bazaar|git).*\.launchpad\.net"):
            return Launchpad(lp_uris.LPNET_SERVICE_ROOT)
        raise UnsupportedForge(hostname)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        if plausible_launchpad_url(url):
            return Launchpad(lp_uris.LPNET_SERVICE_ROOT)
        raise UnsupportedForge(url)

    def _get_lp_git_ref_from_branch(self, branch):
        url, params = urlutils.split_segment_parameters(branch.user_url)
        (scheme, user, password, host, port, path) = urlutils.parse_url(url)
        repo_lp = self.launchpad.git_repositories.getByPath(path=path.strip("/"))
        try:
            ref_path = params["ref"]
        except KeyError:
            branch_name = params.get("branch", branch.name)
            if branch_name:
                ref_path = "refs/heads/{}".format(branch_name)
            else:
                ref_path = repo_lp.default_branch
        ref_lp = repo_lp.getRefByPath(path=ref_path)
        return (repo_lp, ref_lp)

    def _get_lp_bzr_branch_from_branch(self, branch):
        return self.launchpad.branches.getByUrl(url=urlutils.unescape(branch.user_url))

    def _get_derived_git_path(self, base_path, owner, project):
        base_repo = self.launchpad.git_repositories.getByPath(path=base_path)
        if project is None:
            project = urlutils.parse_url(base_repo.git_ssh_url)[-1].strip("/")
        if project.startswith("~"):
            project = "/".join(base_path.split("/")[1:])
        # TODO(jelmer): Surely there is a better way of creating one of these
        # URLs?
        return "~{}/{}".format(owner, project)

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
        return br_to, ("https://git.launchpad.net/{}/+ref/{}".format(to_path, name))

    def _get_derived_bzr_path(self, base_branch, name, owner, project):
        if project is None:
            base_branch_lp = self._get_lp_bzr_branch_from_branch(base_branch)
            project = "/".join(base_branch_lp.unique_name.split("/")[1:-1])
        # TODO(jelmer): Surely there is a better way of creating one of these
        # URLs?
        return "~{}/{}/{}".format(owner, project, name)

    def get_push_url(self, branch):
        (vcs, user, password, path, params) = self._split_url(branch.user_url)
        if vcs == "bzr":
            branch_lp = self._get_lp_bzr_branch_from_branch(branch)
            return branch_lp.bzr_identity
        elif vcs == "git":
            return urlutils.join_segment_parameters(
                GIT_SCHEME_MAP["ssh"] + path, params
            )
        else:
            raise AssertionError

    def _publish_bzr(
        self,
        local_branch,
        base_branch,
        name,
        owner,
        project=None,
        revision_id=None,
        overwrite=False,
        allow_lossy=True,
        tag_selector=None,
    ):
        to_path = self._get_derived_bzr_path(base_branch, name, owner, project)
        to_transport = get_transport(BZR_SCHEME_MAP["ssh"] + to_path)
        try:
            dir_to = controldir.ControlDir.open_from_transport(to_transport)
        except errors.NotBranchError:
            # Didn't find anything
            dir_to = None

        if dir_to is None:
            br_to = local_branch.create_clone_on_transport(
                to_transport, revision_id=revision_id, tag_selector=tag_selector
            )
        else:
            br_to = dir_to.push_branch(
                local_branch,
                revision_id,
                overwrite=overwrite,
                tag_selector=tag_selector,
            ).target_branch
        return br_to, ("https://code.launchpad.net/" + to_path)

    def _split_url(self, url):
        url, params = urlutils.split_segment_parameters(url)
        (scheme, user, password, host, port, path) = urlutils.parse_url(url)
        path = path.strip("/")
        if host.startswith("bazaar."):
            vcs = "bzr"
        elif host.startswith("git."):
            vcs = "git"
        else:
            raise ValueError("unknown host {}".format(host))
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
        (base_vcs, base_user, base_password, base_path, base_params) = self._split_url(
            base_branch.user_url
        )
        # TODO(jelmer): Prevent publishing to development focus
        if base_vcs == "bzr":
            return self._publish_bzr(
                local_branch,
                base_branch,
                name,
                project=project,
                owner=owner,
                revision_id=revision_id,
                overwrite=overwrite,
                allow_lossy=allow_lossy,
                tag_selector=tag_selector,
            )
        elif base_vcs == "git":
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
            raise AssertionError("not a valid Launchpad URL")

    def get_derived_branch(
        self, base_branch, name, project=None, owner=None, preferred_schemes=None
    ):
        if preferred_schemes is None:
            preferred_schemes = DEFAULT_PREFERRED_SCHEMES
        if owner is None:
            owner = self.launchpad.me.name
        (base_vcs, base_user, base_password, base_path, base_params) = self._split_url(
            base_branch.user_url
        )
        if base_vcs == "bzr":
            to_path = self._get_derived_bzr_path(base_branch, name, owner, project)
            for scheme in preferred_schemes:
                try:
                    prefix = BZR_SCHEME_MAP[scheme]
                except KeyError:
                    continue
                return _mod_branch.Branch.open(prefix + to_path)
            raise AssertionError("no supported schemes: {!r}".format(preferred_schemes))
        elif base_vcs == "git":
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
            raise AssertionError("no supported schemes: {!r}".format(preferred_schemes))
        else:
            raise AssertionError("not a valid Launchpad URL")

    def iter_proposals(self, source_branch, target_branch, status="open"):
        (base_vcs, base_user, base_password, base_path, base_params) = self._split_url(
            target_branch.user_url
        )
        statuses = status_to_lp_mp_statuses(status)
        if base_vcs == "bzr":
            target_branch_lp = self.launchpad.branches.getByUrl(
                url=target_branch.user_url
            )
            source_branch_lp = self.launchpad.branches.getByUrl(
                url=source_branch.user_url
            )
            for mp in target_branch_lp.getMergeProposals(status=statuses):
                if mp.source_branch_link != source_branch_lp.self_link:
                    continue
                yield LaunchpadMergeProposal(mp)
        elif base_vcs == "git":
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
            raise AssertionError("not a valid Launchpad URL")

    def get_proposer(self, source_branch, target_branch):
        (base_vcs, base_user, base_password, base_path, base_params) = self._split_url(
            target_branch.user_url
        )
        if base_vcs == "bzr":
            return LaunchpadBazaarMergeProposalBuilder(
                self, source_branch, target_branch
            )
        elif base_vcs == "git":
            return LaunchpadGitMergeProposalBuilder(self, source_branch, target_branch)
        else:
            raise AssertionError("not a valid Launchpad URL")

    @classmethod
    def iter_instances(cls):
        credential_store = lp_api.get_credential_store()
        for service_root in set(lp_uris.service_roots.values()):
            auth_engine = lp_api.get_auth_engine(service_root)
            creds = credential_store.load(auth_engine.unique_consumer_id)
            if creds is not None:
                yield cls(service_root)

    def iter_my_proposals(self, status="open", author=None):
        statuses = status_to_lp_mp_statuses(status)
        if author is None:
            author_obj = self.launchpad.me
        else:
            author_obj = self._getPerson(author)
        for mp in author_obj.getMergeProposals(status=statuses):
            yield LaunchpadMergeProposal(mp)

    def iter_my_forks(self, owner=None):
        # Launchpad doesn't really have the concept of "forks"
        return iter([])

    def _getPerson(self, person):
        if "@" in person:
            return self.launchpad.people.getByEmail(email=person)
        else:
            return self.launchpad.people[person]

    def get_web_url(self, branch):
        (vcs, user, password, path, params) = self._split_url(branch.user_url)
        if vcs == "bzr":
            branch_lp = self._get_lp_bzr_branch_from_branch(branch)
            return branch_lp.web_link
        elif vcs == "git":
            (repo_lp, ref_lp) = self._get_lp_git_ref_from_branch(branch)
            return ref_lp.web_link
        else:
            raise AssertionError

    def get_proposal_by_url(self, url):
        # Launchpad doesn't have a way to find a merge proposal by URL.
        (scheme, user, password, host, port, path) = urlutils.parse_url(url)
        LAUNCHPAD_CODE_DOMAINS = [
            ("code.{}".format(domain)) for domain in lp_uris.LAUNCHPAD_DOMAINS.values()
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
        self.launchpad.projects.new_project(
            display_name=path, name=path, summary=summary, title=path
        )


class LaunchpadBazaarMergeProposalBuilder(MergeProposalBuilder):
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
        self.source_branch_lp = self.launchpad.branches.getByUrl(
            url=source_branch.user_url
        )
        if target_branch is None:
            self.target_branch_lp = self.source_branch_lp.get_target()
            self.target_branch = _mod_branch.Branch.open(
                self.target_branch_lp.bzr_identity
            )
        else:
            self.target_branch = target_branch
            self.target_branch_lp = self.launchpad.branches.getByUrl(
                url=target_branch.user_url
            )
        self.approve = approve
        self.fixes = fixes

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        info = ["Source: {}\n".format(self.source_branch_lp.bzr_identity)]
        info.append("Target: {}\n".format(self.target_branch_lp.bzr_identity))
        return "".join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
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
                        "target_branch": self.target_branch_lp.bzr_identity,
                        "modified_files_callback": list_modified_files,
                        "old_body": body,
                    }
                )
            return body

    def check_proposal(self):
        """Check that the submission is sensible."""
        if self.source_branch_lp.self_link == self.target_branch_lp.self_link:
            raise errors.CommandError("Source and target branches must be different.")
        for mp in self.source_branch_lp.landing_targets:
            if mp.queue_status in ("Merged", "Rejected"):
                continue
            if mp.target_branch.self_link == self.target_branch_lp.self_link:
                raise MergeProposalExists(lp_uris.canonical_url(mp))

    def approve_proposal(self, mp):
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
        delete_source_after_merge: Optional[bool] = None,
    ):
        """Perform the submission."""
        if labels:
            raise LabelsUnsupported(self)
        if title:
            raise TitleUnsupported(self)
        if prerequisite_branch is not None:
            prereq = self.launchpad.branches.getByUrl(url=prerequisite_branch.user_url)
        else:
            prereq = None
        if reviewers is None:
            reviewer_objs: List[Any] = []
        else:
            reviewer_objs = []
            for reviewer in reviewers:
                reviewer_objs.append(self.lp_host._getPerson(reviewer))
        if delete_source_after_merge is True:
            mutter(
                "Ignoring request to delete source after merge, "
                "which launchpad does not support"
            )
        try:
            mp = _call_webservice(
                self.source_branch_lp.createMergeProposal,
                target_branch=self.target_branch_lp,
                prerequisite_branch=prereq,
                initial_comment=description.strip(),
                commit_message=commit_message,
                needs_review=(not work_in_progress),
                reviewers=[reviewer.self_link for reviewer in reviewer_objs],
                review_types=["" for reviewer in reviewer_objs],
            )
        except WebserviceFailure as e:
            # Urgh.
            if (
                b"There is already a branch merge proposal registered for branch "
            ) in e.message:
                raise MergeProposalExists(self.source_branch.user_url)
            raise

        if self.approve:
            self.approve_proposal(mp)
        if self.fixes:
            if self.fixes.startswith("lp:"):
                self.fixes = self.fixes[3:]
            _call_webservice(mp.linkBug, bug=self.launchpad.bugs[int(self.fixes)])
        return LaunchpadMergeProposal(mp)


class LaunchpadGitMergeProposalBuilder(MergeProposalBuilder):
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
        (self.source_repo_lp, self.source_branch_lp) = (
            self.lp_host._get_lp_git_ref_from_branch(source_branch)
        )
        if target_branch is None:
            self.target_branch_lp = self.source_branch.get_target()
            self.target_branch = _mod_branch.Branch.open(
                self.target_branch_lp.git_https_url
            )
        else:
            self.target_branch = target_branch
            (self.target_repo_lp, self.target_branch_lp) = (
                self.lp_host._get_lp_git_ref_from_branch(target_branch)
            )
        self.approve = approve
        self.fixes = fixes

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        info = ["Source: {}\n".format(self.source_branch.user_url)]
        info.append("Target: {}\n".format(self.target_branch.user_url))
        return "".join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
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
        """Check that the submission is sensible."""
        if self.source_branch_lp.self_link == self.target_branch_lp.self_link:
            raise errors.CommandError("Source and target branches must be different.")
        for mp in self.source_branch_lp.landing_targets:
            if mp.queue_status in ("Merged", "Rejected"):
                continue
            if mp.target_branch.self_link == self.target_branch_lp.self_link:
                raise MergeProposalExists(lp_uris.canonical_url(mp))

    def approve_proposal(self, mp):
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
        reviewers=None,
        labels=None,
        prerequisite_branch=None,
        commit_message=None,
        work_in_progress=False,
        allow_collaboration=False,
    ):
        """Perform the submission."""
        if labels:
            raise LabelsUnsupported(self)
        if prerequisite_branch is not None:
            (prereq_repo_lp, prereq_branch_lp) = (
                self.lp_host._get_lp_git_ref_from_branch(prerequisite_branch)
            )
        else:
            prereq_branch_lp = None
        if reviewers is None:
            reviewers = []
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
                raise MergeProposalExists(self.source_branch.user_url)
            raise
        if self.approve:
            self.approve_proposal(mp)
        if self.fixes:
            if self.fixes.startswith("lp:"):
                self.fixes = self.fixes[3:]
            _call_webservice(mp.linkBug, bug=self.launchpad.bugs[int(self.fixes)])
        return LaunchpadMergeProposal(mp)


def modified_files(old_tree, new_tree):
    """Return a list of paths in the new tree with modified contents."""
    for change in new_tree.iter_changes(old_tree):
        if change.changed_content and change.kind[1] == "file":
            yield str(path)
