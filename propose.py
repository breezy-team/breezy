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


class ProposerUnavailable(errors.BzrError):

    _fmt = "Unable to determine how to propose a merge to %(branch)s."

    def __init__(self, branch):
        errors.BzrError.__init__(self)
        self.branch = branch


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


class ProposeMergeHooks(hooks.Hooks):
    """Hooks for proposing a merge on Launchpad."""

    def __init__(self):
        hooks.Hooks.__init__(self, __name__, "Proposer.hooks")
        self.add_hook('get_prerequisite',
            "Return the prerequisite branch for proposing as merge.", (3, 0))
        self.add_hook('merge_proposal_body',
            "Return an initial body for the merge proposal message.", (3, 0))


class MergeProposal(object):
    """A merge proposal.

    :ivar url: URL for the merge proposal
    """

    def __init__(self, url=None):
        self.url = url


class MergeProposalBuilder(object):
    """Merge proposal creator.

    :param source_branch: Branch to propose for merging
    :param target_branch: Target branch
    """

    hooks = ProposeMergeHooks()

    def __init__(self, source_branch, target_branch):
        self.source_branch = source_branch
        self.target_branch = target_branch

    @classmethod
    def is_compatible(cls, target_branch, source_branch):
        raise NotImplementedError(cls.is_compatible)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        raise NotImplementedError(self.get_initial_body)

    def get_infotext(self):
        """Determine the initial comment for the merge proposal.
        """
        raise NotImplementedError(self.get_infotext)

    def create_proposal(self, description, reviewers=None):
        """Create a proposal to merge a branch for merging.

        :param description: Description for the merge proposal
        :param reviewers: Optional list of people to ask reviews from
        :return: A `MergeProposal` object
        """
        raise NotImplementedError(self.create_proposal)


class Hoster(object):
    """A hosting site manager.
    """

    def publish(self, new_branch, base_branch, name, project=None, owner=None,
                revision_id=None, overwrite=False):
        """Publish a branch to the site, derived from base_branch.

        :param base_branch: branch to derive the new branch from
        :param new_branch: branch to publish
        :return: resulting branch, public URL
        """
        raise NotImplementedError(self.publish)

    def get_proposer(self, source_branch, target_branch):
        """Get a merge proposal creator.

        :param source_branch: Source branch
        :param target_branch: Target branch
        :return: A MergeProposalBuilder object
        """
        raise NotImplementedError(self.get_proposer)

    @classmethod
    def is_compatible(cls, branch):
        """Checks whether this hoster hosts the specified branch."""
        raise NotImplementedError(cls.is_compatible)

    # TODO(jelmer): Some way of cleaning up old branch proposals/branches


def get_hoster(branch):
    """Find the hoster for a branch."""
    for name, hoster_cls in hosters.items():
        if hoster_cls.is_compatible(branch):
            return hoster_cls()
    raise UnsupportedHoster(branch)


def get_proposer(branch, target_branch):
    """Create a merge proposal for branch to target_branch.

    :param branch: A branch object
    :param target_branch: Target branch object
    """
    for name, proposer_cls in proposers.items():
        if proposer_cls.is_compatible(target_branch, branch):
            break
    else:
        raise ProposerUnavailable(target_branch.user_url)

    return proposer_cls(branch, target_branch)


proposers = registry.Registry()
proposers.register_lazy(
        "launchpad", "breezy.plugins.propose.launchpad",
        "LaunchpadMergeProposalBuilder")
proposers.register_lazy(
        "github", "breezy.plugins.propose.github",
        "GitHubMergeProposalBuilder")
proposers.register_lazy(
        "gitlab", "breezy.plugins.propose.gitlabs",
        "GitlabMergeProposalBuilder")

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
