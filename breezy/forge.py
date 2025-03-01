# Copyright (C) 2018-2019 Breezy Developers
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

"""Helper functions for proposing merges."""

from typing import Optional, Type

from . import errors, hooks, registry, urlutils


class NoSuchProject(errors.BzrError):
    _fmt = "Project does not exist: %(project)s."

    def __init__(self, project):
        errors.BzrError.__init__(self)
        self.project = project


class MergeProposalExists(errors.BzrError):
    _fmt = "A merge proposal already exists: %(url)s."

    def __init__(self, url, existing_proposal=None):
        errors.BzrError.__init__(self)
        self.url = url
        self.existing_proposal = existing_proposal


class UnsupportedForge(errors.BzrError):
    _fmt = "No supported forge for %(branch)s."

    def __init__(self, branch):
        errors.BzrError.__init__(self)
        self.branch = branch


class ReopenFailed(errors.BzrError):
    _fmt = "Reopening the merge proposal failed: %(error)s."


class TitleUnsupported(errors.BzrError):
    _fmt = "The merge proposal %(mp)s does not support a title."


class AutoMergeUnsupported(errors.BzrError):
    _fmt = "The merge proposal %(mp)s does not support automerge."


class ProposeMergeHooks(hooks.Hooks):
    """Hooks for proposing a merge on Launchpad."""

    def __init__(self):
        hooks.Hooks.__init__(self, __name__, "Proposer.hooks")
        self.add_hook(
            "get_prerequisite",
            "Return the prerequisite branch for proposing as merge.",
            (3, 0),
        )
        self.add_hook(
            "merge_proposal_body",
            "Return an initial body for the merge proposal message.",
            (3, 0),
        )


class LabelsUnsupported(errors.BzrError):
    """Labels not supported by this forge."""

    _fmt = "Labels are not supported by %(forge)r."

    def __init__(self, forge):
        errors.BzrError.__init__(self)
        self.forge = forge


class PrerequisiteBranchUnsupported(errors.BzrError):
    """Prerequisite branch not supported by this forge."""

    def __init__(self, forge):
        errors.BzrError.__init__(self)
        self.forge = forge


class ForgeLoginRequired(errors.BzrError):
    """Action requires forge login credentials."""

    _fmt = "Action requires credentials for hosting site %(forge)r."

    def __init__(self, forge):
        errors.BzrError.__init__(self)
        self.forge = forge


class SourceNotDerivedFromTarget(errors.BzrError):
    """Source branch is not derived from target branch."""

    _fmt = "Source %(source_branch)r not derived from target %(target_branch)r."

    def __init__(self, source_branch, target_branch):
        errors.BzrError.__init__(
            self, source_branch=source_branch, target_branch=target_branch
        )


class MergeProposal:
    """A merge proposal.

    :ivar url: URL for the merge proposal
    """

    supports_auto_merge: bool

    def __init__(self, url=None):
        self.url = url

    def __str__(self):
        return self.url

    def __repr__(self):
        return "<{}({!r})>".format(self.__class__.__name__, self.url)

    def get_web_url(self):
        raise NotImplementedError(self.get_web_url)

    def get_description(self):
        """Get the description of the merge proposal."""
        raise NotImplementedError(self.get_description)

    def set_description(self, description):
        """Set the description of the merge proposal."""
        raise NotImplementedError(self.set_description)

    def get_title(self):
        """Get the title."""
        raise NotImplementedError(self.get_title)

    def set_title(self, title):
        """Get the title."""
        raise NotImplementedError(self.set_title)

    def get_commit_message(self):
        """Get the proposed commit message."""
        raise NotImplementedError(self.get_commit_message)

    def set_commit_message(self, commit_message):
        """Set the propose commit message."""
        raise NotImplementedError(self.set_commit_message)

    def get_source_branch_url(self, *, preferred_schemes=None):
        """Return the source branch."""
        raise NotImplementedError(self.get_source_branch_url)

    def get_source_revision(self):
        """Return the latest revision for the source branch."""
        raise NotImplementedError(self.get_source_revision)

    def get_target_branch_url(self, *, preferred_schemes=None):
        """Return the target branch."""
        raise NotImplementedError(self.get_target_branch_url)

    def set_target_branch_name(self):
        """Set the target branch name."""
        raise NotImplementedError(self.set_target_branch_name)

    def get_source_project(self):
        raise NotImplementedError(self.get_source_project)

    def get_target_project(self):
        raise NotImplementedError(self.get_target_project)

    def close(self):
        """Close the merge proposal (without merging it)."""
        raise NotImplementedError(self.close)

    def is_merged(self):
        """Check whether this merge proposal has been merged."""
        raise NotImplementedError(self.is_merged)

    def is_closed(self):
        """Check whether this merge proposal is closed.

        This can either mean that it is merged or rejected.
        """
        raise NotImplementedError(self.is_closed)

    def merge(self, commit_message=None, auto=False):
        """Merge this merge proposal."""
        raise NotImplementedError(self.merge)

    def can_be_merged(self):
        """Can this merge proposal be merged?

        The answer to this can be no if e.g. it has conflics.
        """
        raise NotImplementedError(self.can_be_merged)

    def get_merged_by(self):
        """If this proposal was merged, who merged it."""
        raise NotImplementedError(self.get_merged_by)

    def get_merged_at(self):
        """If this proposal was merged, when it was merged."""
        raise NotImplementedError(self.get_merged_at)

    def post_comment(self, body):
        """Post a comment on the merge proposal.

        Args:
          body: Body of the comment
        """
        raise NotImplementedError(self.post_comment)

    def reopen(self):
        """Reopen this merge proposal."""
        raise NotImplementedError(self.reopen)


class MergeProposalBuilder:
    """Merge proposal creator.

    :param source_branch: Branch to propose for merging
    :param target_branch: Target branch
    """

    hooks = ProposeMergeHooks()

    def __init__(self, source_branch, target_branch):
        self.source_branch = source_branch
        self.target_branch = target_branch

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        raise NotImplementedError(self.get_initial_body)

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        raise NotImplementedError(self.get_infotext)

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
        """Create a proposal to merge a branch for merging.

        Args:
          description: Description for the merge proposal
          reviewers: Optional list of people to ask reviews from
          labels: Labels to attach to the proposal
          prerequisite_branch: Optional prerequisite branch
          commit_message: Optional commit message
          work_in_progress:
            Whether this merge proposal is still a work-in-progress
          allow_collaboration:
            Whether to allow changes to the branch from the target branch
            maintainer(s)
          delete_after_merge: Whether to delete the source branch after it
            has been merged
        Returns: A `MergeProposal` object
        """
        raise NotImplementedError(self.create_proposal)


class Forge:
    """A hosting site manager."""

    # Does this forge support arbitrary labels being attached to merge
    # proposals?
    supports_merge_proposal_labels: bool

    supports_merge_proposal_title: bool

    @property
    def name(self):
        """Name of this instance."""
        return "{} at {}".format(type(self).__name__, self.base_url)

    # Does this forge support suggesting a commit message in the
    # merge proposal?
    supports_merge_proposal_commit_message: bool

    # The base_url that would be visible to users. I.e. https://github.com/
    # rather than https://api.github.com/
    base_url: str

    # The syntax to use for formatting merge proposal descriptions.
    # Common values: 'plain', 'markdown'
    merge_proposal_description_format: str

    # Does this forge support the allow_collaboration flag?
    supports_allow_collaboration: bool = False

    def publish_derived(
        self,
        new_branch,
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
        :return: resulting branch, public URL
        :raise ForgeLoginRequired: Action requires a forge login, but none is
            known.
        """
        raise NotImplementedError(self.publish_derived)

    def get_derived_branch(
        self, base_branch, name, project=None, owner=None, preferred_schemes=None
    ):
        """Get a derived branch ('a fork')."""
        raise NotImplementedError(self.get_derived_branch)

    def get_push_url(self, branch):
        """Get the push URL for a branch."""
        raise NotImplementedError(self.get_push_url)

    def get_web_url(self, branch):
        """Get the web viewing URL for a branch."""
        raise NotImplementedError(self.get_web_url)

    def get_proposer(self, source_branch, target_branch):
        """Get a merge proposal creator.

        :note: source_branch does not have to be hosted by the forge.

        :param source_branch: Source branch
        :param target_branch: Target branch
        :return: A MergeProposalBuilder object
        """
        raise NotImplementedError(self.get_proposer)

    def iter_proposals(self, source_branch, target_branch, status="open"):
        """Get the merge proposals for a specified branch tuple.

        :param source_branch: Source branch
        :param target_branch: Target branch
        :param status: Status of proposals to iterate over
        :return: Iterate over MergeProposal object
        """
        raise NotImplementedError(self.iter_proposals)

    def get_proposal_by_url(self, url):
        """Retrieve a branch proposal by URL.

        :param url: Merge proposal URL.
        :return: MergeProposal object
        :raise UnsupportedForge: Forge does not support this URL
        """
        raise NotImplementedError(self.get_proposal_by_url)

    def hosts(self, branch):
        """Return true if this forge hosts given branch."""
        raise NotImplementedError(self.hosts)

    @classmethod
    def probe_from_hostname(cls, hostname, possible_transports=None):
        """Create a Forge object if this forge knows about a hostname."""
        raise NotImplementedError(cls.probe_from_hostname)

    @classmethod
    def probe_from_branch(cls, branch):
        """Create a Forge object if this forge knows about a branch."""
        url = urlutils.strip_segment_parameters(branch.user_url)
        return cls.probe_from_url(url, possible_transports=[branch.control_transport])

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        """Create a Forge object if this forge knows about a URL."""
        hostname = urlutils.URL.from_string(url).host
        return cls.probe_from_hostname(
            hostname, possible_transports=possible_transports
        )

    def iter_my_proposals(self, status="open", author=None):
        """Iterate over the proposals created by the currently logged in user.

        :param status: Only yield proposals with this status
            (one of: 'open', 'closed', 'merged', 'all')
        :param author: Name of author to query (defaults to current user)
        :return: Iterator over MergeProposal objects
        :raise ForgeLoginRequired: Action requires a forge login, but none is
            known.
        """
        raise NotImplementedError(self.iter_my_proposals)

    def iter_my_forks(self, owner=None):
        """Iterate over the currently logged in users' forks.

        :param owner: Name of owner to query (defaults to current user)
        :return: Iterator over project_name
        """
        raise NotImplementedError(self.iter_my_forks)

    def delete_project(self, name):
        """Delete a project."""
        raise NotImplementedError(self.delete_project)

    def create_project(self, name, summary=None):
        """Create a project."""
        raise NotImplementedError(self.create_project)

    @classmethod
    def iter_instances(cls):
        """Iterate instances.

        :return: Forge instances
        """
        raise NotImplementedError(cls.iter_instances)

    def get_current_user(self):
        """Retrieve the name of the currently logged in user.

        :return: Username or None if not logged in
        """
        raise NotImplementedError(self.get_current_user)

    def get_user_url(self, user):
        """Rerieve the web URL for a user."""
        raise NotImplementedError(self.get_user_url)


def determine_title(description):
    """Determine the title for a merge proposal based on full description."""
    for firstline in description.splitlines():
        if firstline.strip():
            break
    else:
        raise ValueError
    try:
        i = firstline.index(". ")
    except ValueError:
        return firstline.rstrip(".")
    else:
        return firstline[:i]


def get_forge(branch, possible_forges=None):
    """Find the forge for a branch.

    :param branch: Branch to find forge for
    :param possible_forges: Optional list of forges to reuse
    :raise UnsupportedForge: if there is no forge that supports `branch`
    :return: A `Forge` object
    """
    if possible_forges:
        for forge in possible_forges:
            if forge.hosts(branch):
                return forge
    for _name, forge_cls in forges.items():
        try:
            forge = forge_cls.probe_from_branch(branch)
        except UnsupportedForge:
            pass
        else:
            if possible_forges is not None:
                possible_forges.append(forge)
            return forge
    raise UnsupportedForge(branch)


def get_forge_by_hostname(hostname: str):
    """Get a forge from a hostname."""
    for instance in iter_forge_instances():
        try:
            return instance.probe_from_hostname(hostname)
        except UnsupportedForge:
            pass
    raise UnsupportedForge(hostname)


def iter_forge_instances(forge: Optional[Type[Forge]] = None):
    """Iterate over all known forge instances.

    :return: Iterator over Forge instances
    """
    if forge is None:
        forge_clses = [forge_cls for name, forge_cls in forges.items()]
    else:
        forge_clses = [forge]
    for forge_cls in forge_clses:
        yield from forge_cls.iter_instances()


def get_proposal_by_url(url):
    """Get the proposal object associated with a URL.

    :param url: URL of the proposal
    :raise UnsupportedForge: if there is no forge that supports the URL
    :return: A `MergeProposal` object
    """
    for instance in iter_forge_instances():
        try:
            return instance.get_proposal_by_url(url)
        except UnsupportedForge:
            pass
    raise UnsupportedForge(url)


def create_project(url: str, *, summary=None) -> None:
    """Create a project.

    Args:
      url: URL of project to create
    """
    parsed_url = urlutils.URL.from_string(url)
    for _name, forge_cls in forges.items():
        try:
            hoster = forge_cls.probe_from_url(url)
        except UnsupportedForge:
            pass
        else:
            hoster.create_project(parsed_url.path, summary=summary)
            break
    else:
        raise UnsupportedForge(url)


forges = registry.Registry[str, Type[Forge]]()
