# Copyright (C) 2010, 2011 Canonical Ltd
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

from __future__ import absolute_import

from .propose import (
    MergeProposal,
    MergeProposer,
    MergeProposalExists,
    )

from ... import (
    errors,
    hooks,
    urlutils,
    )
from ...lazy_import import lazy_import
lazy_import(globals(), """
from breezy.plugins.launchpad import (
    lp_api,
    lp_registration,
    )
""")


# TODO(jelmer): Make selection of launchpad staging a configuration option.


class LaunchpadMergeProposer(MergeProposer):

    def __init__(self, source_branch, target_branch, message=None,
                 reviews=None, staging=None, approve=None, fixes=None):
        """Constructor.

        :param source_branch: The branch to propose for merging.
        :param target_branch: The branch to merge into.
        :param message: The commit message to use.  (May be None.)
        :param reviews: A list of tuples of reviewer, review type.
        :param staging: If True, propose the merge against staging instead of
            production.
        :param approve: If True, mark the new proposal as approved immediately.
            This is useful when a project permits some things to be approved
            by the submitter (e.g. merges between release and deployment
            branches).
        """
        if staging:
            lp_instance = 'staging'
        else:
            lp_instance = 'production'
        service = lp_registration.LaunchpadService(lp_instance=lp_instance)
        self.launchpad = lp_api.login(service)
        self.source_branch = lp_api.LaunchpadBranch.from_bzr(
            self.launchpad, source_branch)
        if target_branch is None:
            self.target_branch = self.source_branch.get_target()
        else:
            self.target_branch = lp_api.LaunchpadBranch.from_bzr(
                self.launchpad, target_branch)
        self.prerequisite_branch = self._get_prerequisite_branch()
        self.commit_message = message
        # XXX: this is where bug lp:583638 could be tackled.
        if not reviews:
            self.reviews = []
        else:
            self.reviews = [(self.launchpad.people[reviewer], review_type)
                            for reviewer, review_type in
                            reviews]
        self.approve = approve
        self.fixes = fixes

    @classmethod
    def is_compatible(cls, target_branch, source_branch):
        (scheme, user, password, host, port, path) = urlutils.parse_url(
            target_branch.user_url)
        return host in ('bazaar.launchpad.net', 'bazaar.staging.launchpad.net')

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        if self.commit_message is not None:
            return self.commit_message.strip().encode('utf-8')
        info = ["Source: %s\n" % self.source_branch.lp.bzr_identity]
        info.append("Target: %s\n" % self.target_branch.lp.bzr_identity)
        if self.prerequisite_branch is not None:
            info.append("Prereq: %s\n" % self.prerequisite_branch.lp.bzr_identity)
        for rdata in self.reviews:
            uniquename = "%s (%s)" % (rdata[0].display_name, rdata[0].name)
            info.append('Reviewer: %s, type "%s"\n' % (uniquename, rdata[1]))
        return ''.join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        def list_modified_files():
            lca_tree = self.source_branch.find_lca_tree(
                self.target_branch)
            source_tree = self.source_branch.bzr.basis_tree()
            files = modified_files(lca_tree, source_tree)
            return list(files)
        with self.target_branch.bzr.lock_read(), \
                self.source_branch.bzr.lock_read():
            target_loc = ('bzr+ssh://bazaar.launchpad.net/%s' %
                           self.target_branch.lp.unique_name)
            body = None
            for hook in self.hooks['merge_proposal_body']:
                body = hook({
                    'target_branch': target_loc,
                    'modified_files_callback': list_modified_files,
                    'old_body': body,
                })
            return body

    def check_proposal(self):
        """Check that the submission is sensible."""
        if self.source_branch.lp.self_link == self.target_branch.lp.self_link:
            raise errors.BzrCommandError(
                'Source and target branches must be different.')
        for mp in self.source_branch.lp.landing_targets:
            if mp.queue_status in ('Merged', 'Rejected'):
                continue
            if mp.target_branch.self_link == self.target_branch.lp.self_link:
                raise MergeProposalExists(lp_api.canonical_url(mp))

    def _get_prerequisite_branch(self):
        hooks = self.hooks['get_prerequisite']
        prerequisite_branch = None
        for hook in hooks:
            prerequisite_branch = hook(
                {'launchpad': self.launchpad,
                 'source_branch': self.source_branch,
                 'target_branch': self.target_branch,
                 'prerequisite_branch': prerequisite_branch})
        return prerequisite_branch

    def _call_webservice(self, call, *args, **kwargs):
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
                if line.startswith('Traceback (most recent call last):'):
                    break
                error_lines.append(line)
            raise Exception(''.join(error_lines))

    def approve_proposal(self, mp):
        with self.source_branch.bzr.lock_read():
            revid = source_branch.last_revision()
        self._call_webservice(
            mp.createComment,
            vote=u'Approve',
            subject='', # Use the default subject.
            content=u"Rubberstamp! Proposer approves of own proposal.")
        self._call_webservice(mp.setStatus, status=u'Approved', revid=revid)

    def create_proposal(self, description):
        """Perform the submission."""
        self.source_branch.update_lp()
        if self.prerequisite_branch is None:
            prereq = None
        else:
            prereq = self.prerequisite_branch.lp
            self.prerequisite_branch.update_lp()
        reviewers = []
        review_types = []
        for reviewer, review_type in self.reviews:
            review_types.append(review_type)
            reviewers.append(reviewer.self_link)
        mp = self._call_webservice(
            self.source_branch.lp.createMergeProposal,
            target_branch=self.target_branch.lp,
            prerequisite_branch=prereq,
            initial_comment=description.strip().encode('utf-8'),
            commit_message=self.commit_message, reviewers=reviewers,
            review_types=review_types)
        if self.approve:
            self.approve_proposal(mp)
        if self.fixes:
            if self.fixes.startswith('lp:'):
                self.fixes = self.fixes[3:]
            self._call_webservice(
                self.source_branch.lp.linkBug,
                bug=self.launchpad.bugs[int(self.fixes)])
        return MergeProposal(lp_api.canonical_url(mp))
