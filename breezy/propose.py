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

from __future__ import absolute_import

from . import (
    errors,
    hooks,
    registry,
    urlutils,
    )


class NoSuchProject(errors.BzrError):

    _fmt = "Project does not exist: %(project)s."

    def __init__(self, project):
        errors.BzrError.__init__(self)
        self.project = project


class MergeProposalExists(errors.BzrError):

    _fmt = "A merge proposal already exists: %(url)s."

    def __init__(self, url):
        errors.BzrError.__init__(self)
        self.url = url


class UnsupportedHoster(errors.BzrError):

    _fmt = "No supported hoster for %(branch)s."

    def __init__(self, branch):
        errors.BzrError.__init__(self)
        self.branch = branch


class ReopenFailed(errors.BzrError):

    _fmt = "Reopening the merge proposal failed: %(error)s."


class ProposeMergeHooks(hooks.Hooks):
    """Hooks for proposing a merge on Launchpad."""

    def __init__(self):
        hooks.Hooks.__init__(self, __name__, "Proposer.hooks")
        self.add_hook(
            'get_prerequisite',
            "Return the prerequisite branch for proposing as merge.", (3, 0))
        self.add_hook(
            'merge_proposal_body',
            "Return an initial body for the merge proposal message.", (3, 0))


class LabelsUnsupported(errors.BzrError):
    """Labels not supported by this hoster."""

    _fmt = "Labels are not supported by %(hoster)r."

    def __init__(self, hoster):
        errors.BzrError.__init__(self)
        self.hoster = hoster


class PrerequisiteBranchUnsupported(errors.BzrError):
    """Prerequisite branch not supported by this hoster."""

    def __init__(self, hoster):
        errors.BzrError.__init__(self)
        self.hoster = hoster


class HosterLoginRequired(errors.BzrError):
    """Action requires hoster login credentials."""

    _fmt = "Action requires credentials for hosting site %(hoster)r."""

    def __init__(self, hoster):
        errors.BzrError.__init__(self)
        self.hoster = hoster


class MergeProposal(object):
    """A merge proposal.

    :ivar url: URL for the merge proposal
    """

    def __init__(self, url=None):
        self.url = url

    def get_description(self):
        """Get the description of the merge proposal."""
        raise NotImplementedError(self.get_description)

    def set_description(self, description):
        """Set the description of the merge proposal."""
        raise NotImplementedError(self.set_description)

    def get_commit_message(self):
        """Get the proposed commit message."""
        raise NotImplementedError(self.get_commit_message)

    def set_commit_message(self, commit_message):
        """Set the propose commit message."""
        raise NotImplementedError(self.set_commit_message)

    def get_source_branch_url(self):
        """Return the source branch."""
        raise NotImplementedError(self.get_source_branch_url)

    def get_target_branch_url(self):
        """Return the target branch."""
        raise NotImplementedError(self.get_target_branch_url)

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
        """Check whether this merge proposal is closed

        This can either mean that it is merged or rejected.
        """
        raise NotImplementedError(self.is_closed)

    def merge(self, commit_message=None):
        """Merge this merge proposal."""
        raise NotImplementedError(self.merge)

    def can_be_merged(self):
        """Can this merge proposal be merged?

        The answer to this can be no if e.g. it has conflics.
        """
        raise NotImplementedError(self.can_be_merged)

    def get_merged_by(self):
        """If this proposal was merged, who merged it.
        """
        raise NotImplementedError(self.get_merged_by)

    def get_merged_at(self):
        """If this proposal was merged, when it was merged.
        """
        raise NotImplementedError(self.get_merged_at)


class MergeProposalBuilder(object):
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
        """Determine the initial comment for the merge proposal.
        """
        raise NotImplementedError(self.get_infotext)

    def create_proposal(self, description, reviewers=None, labels=None,
                        prerequisite_branch=None, commit_message=None,
                        work_in_progress=False, allow_collaboration=False):
        """Create a proposal to merge a branch for merging.

        :param description: Description for the merge proposal
        :param reviewers: Optional list of people to ask reviews from
        :param labels: Labels to attach to the proposal
        :param prerequisite_branch: Optional prerequisite branch
        :param commit_message: Optional commit message
        :param work_in_progress:
            Whether this merge proposal is still a work-in-progress
        :param allow_collaboration:
            Whether to allow changes to the branch from the target branch
            maintainer(s)
        :return: A `MergeProposal` object
        """
        raise NotImplementedError(self.create_proposal)


class Hoster(object):
    """A hosting site manager.
    """

    # Does this hoster support arbitrary labels being attached to merge
    # proposals?
    supports_merge_proposal_labels = None

    # Does this hoster support suggesting a commit message in the
    # merge proposal?
    supports_merge_proposal_commit_message = None

    # The base_url that would be visible to users. I.e. https://github.com/
    # rather than https://api.github.com/
    base_url = None

    # The syntax to use for formatting merge proposal descriptions.
    # Common values: 'plain', 'markdown'
    merge_proposal_description_format = None

    # Does this hoster support the allow_collaboration flag?
    supports_allow_collaboration = False

    def publish_derived(self, new_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False,
                        allow_lossy=True, tag_selector=None):
        """Publish a branch to the site, derived from base_branch.

        :param base_branch: branch to derive the new branch from
        :param new_branch: branch to publish
        :return: resulting branch, public URL
        :raise HosterLoginRequired: Action requires a hoster login, but none is
            known.
        """
        raise NotImplementedError(self.publish)

    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        """Get a derived branch ('a fork').
        """
        raise NotImplementedError(self.get_derived_branch)

    def get_push_url(self, branch):
        """Get the push URL for a branch."""
        raise NotImplementedError(self.get_push_url)

    def get_proposer(self, source_branch, target_branch):
        """Get a merge proposal creator.

        :note: source_branch does not have to be hosted by the hoster.

        :param source_branch: Source branch
        :param target_branch: Target branch
        :return: A MergeProposalBuilder object
        """
        raise NotImplementedError(self.get_proposer)

    def iter_proposals(self, source_branch, target_branch, status='open'):
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
        :raise UnsupportedHoster: Hoster does not support this URL
        """
        raise NotImplementedError(self.get_proposal_by_url)

    def hosts(self, branch):
        """Return true if this hoster hosts given branch."""
        raise NotImplementedError(self.hosts)

    @classmethod
    def probe_from_branch(cls, branch):
        """Create a Hoster object if this hoster knows about a branch."""
        url = urlutils.strip_segment_parameters(branch.user_url)
        return cls.probe_from_url(
            url, possible_transports=[branch.control_transport])

    @classmethod
    def probe_from_url(cls, url, possible_hosters=None):
        """Create a Hoster object if this hoster knows about a URL."""
        raise NotImplementedError(cls.probe_from_url)

    def iter_my_proposals(self, status='open'):
        """Iterate over the proposals created by the currently logged in user.

        :param status: Only yield proposals with this status
            (one of: 'open', 'closed', 'merged', 'all')
        :return: Iterator over MergeProposal objects
        :raise HosterLoginRequired: Action requires a hoster login, but none is
            known.
        """
        raise NotImplementedError(self.iter_my_proposals)

    def iter_my_forks(self):
        """Iterate over the currently logged in users' forks.

        :return: Iterator over project_name
        """
        raise NotImplementedError(self.iter_my_forks)

    def delete_project(self, name):
        """Delete a project.
        """
        raise NotImplementedError(self.delete_project)

    @classmethod
    def iter_instances(cls):
        """Iterate instances.

        :return: Hoster instances
        """
        raise NotImplementedError(cls.iter_instances)


def determine_title(description):
    """Determine the title for a merge proposal based on full description."""
    return description.splitlines()[0].split('.')[0]


def get_hoster(branch, possible_hosters=None):
    """Find the hoster for a branch.

    :param branch: Branch to find hoster for
    :param possible_hosters: Optional list of hosters to reuse
    :raise UnsupportedHoster: if there is no hoster that supports `branch`
    :return: A `Hoster` object
    """
    if possible_hosters:
        for hoster in possible_hosters:
            if hoster.hosts(branch):
                return hoster
    for name, hoster_cls in hosters.items():
        try:
            hoster = hoster_cls.probe_from_branch(branch)
        except UnsupportedHoster:
            pass
        else:
            if possible_hosters is not None:
                possible_hosters.append(hoster)
            return hoster
    raise UnsupportedHoster(branch)


def get_proposal_by_url(url):
    """Get the proposal object associated with a URL.

    :param url: URL of the proposal
    :raise UnsupportedHoster: if there is no hoster that supports the URL
    :return: A `MergeProposal` object
    """
    for name, hoster_cls in hosters.items():
        for instance in hoster_cls.iter_instances():
            try:
                return instance.get_proposal_by_url(url)
            except UnsupportedHoster:
                pass
    raise UnsupportedHoster(url)


hosters = registry.Registry()
