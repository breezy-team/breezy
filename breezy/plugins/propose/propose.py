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

"""Helper functions for proposing merges."""

from __future__ import absolute_import

from ... import (
    errors,
    hooks,
    registry,
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


class NoMergeProposal(errors.BzrError):

    _fmt = "No merge proposal exists."

    def __init__(self):
        errors.BzrError.__init__(self)


class UnsupportedHoster(errors.BzrError):

    _fmt = "No supported hoster for %(branch)s."

    def __init__(self, branch):
        errors.BzrError.__init__(self)
        self.branch = branch


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

    def close(self):
        """Close the merge proposal (without merging it)."""
        raise NotImplementedError(self.close)

    def is_merged(self):
        """Check whether this merge proposal has been merged."""
        raise NotImplementedError(self.is_merged)


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
                        prerequisite_branch=None):
        """Create a proposal to merge a branch for merging.

        :param description: Description for the merge proposal
        :param reviewers: Optional list of people to ask reviews from
        :param labels: Labels to attach to the proposal
        :param prerequisite_branch: Optional prerequisite branch
        :return: A `MergeProposal` object
        """
        raise NotImplementedError(self.create_proposal)


class Hoster(object):
    """A hosting site manager.
    """

    supports_merge_proposal_labels = None

    def publish_derived(self, new_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False,
                        allow_lossy=True):
        """Publish a branch to the site, derived from base_branch.

        :param base_branch: branch to derive the new branch from
        :param new_branch: branch to publish
        :return: resulting branch, public URL
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

    def get_proposal(self, source_branch, target_branch):
        """Get a merge proposal for a specified branch tuple.

        :param source_branch: Source branch
        :param target_branch: Target branch
        :raise NoMergeProposal: if no merge proposal can be found
        :return: A MergeProposal object
        """
        raise NotImplementedError(self.get_proposal)

    def hosts(self, branch):
        """Return true if this hoster hosts given branch."""
        raise NotImplementedError(self.hosts)

    @classmethod
    def probe(cls, branch):
        """Create a Hoster object if this hoster knows about a branch."""
        raise NotImplementedError(cls.probe)

    # TODO(jelmer): Some way of cleaning up old branch proposals/branches
    # TODO(jelmer): Some way of checking up on outstanding merge proposals


def get_hoster(branch, possible_hosters=None):
    """Find the hoster for a branch."""
    if possible_hosters:
        for hoster in possible_hosters:
            if hoster.hosts(branch):
                return hoster
    for name, hoster_cls in hosters.items():
        try:
            hoster = hoster_cls.probe(branch)
        except UnsupportedHoster:
            pass
        else:
            if possible_hosters is not None:
                possible_hosters.append(hoster)
            return hoster
    raise UnsupportedHoster(branch)


hosters = registry.Registry()
hosters.register_lazy(
    "launchpad", "breezy.plugins.propose.launchpad",
    "Launchpad")
hosters.register_lazy(
    "github", "breezy.plugins.propose.github",
    "GitHub")
hosters.register_lazy(
    "gitlab", "breezy.plugins.propose.gitlabs",
    "GitLab")
