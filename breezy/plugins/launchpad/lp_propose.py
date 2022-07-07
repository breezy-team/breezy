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

from ... import (
    errors,
    hooks,
    )
from ...lazy_import import lazy_import
lazy_import(globals(), """
import webbrowser

from breezy import (
    msgeditor,
    )
from breezy.i18n import gettext
from breezy.plugins.launchpad import (
    lp_api,
    )
""")


class ProposeMergeHooks(hooks.Hooks):
    """Hooks for proposing a merge on Launchpad."""

    def __init__(self):
        hooks.Hooks.__init__(self, "breezy.plugins.launchpad.lp_propose",
                             "Proposer.hooks")
        self.add_hook('get_prerequisite',
                      "Return the prerequisite branch for proposing as merge.", (2, 1))
        self.add_hook('merge_proposal_body',
                      "Return an initial body for the merge proposal message.", (2, 1))


class Proposer(object):

    hooks = ProposeMergeHooks()

    def __init__(self, tree, source_branch, target_branch, message, reviews,
                 staging=False, approve=False, fixes=None):
        """Constructor.

        :param tree: The working tree for the source branch.
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
        self.tree = tree
        if staging:
            lp_base_url = lp_api.uris.STAGING_SERVICE_ROOT
        else:
            lp_base_url = lp_api.uris.LPNET_SERVICE_ROOT
        self.launchpad = lp_api.connect_launchpad(lp_base_url)
        self.source_branch = lp_api.LaunchpadBranch.from_bzr(
            self.launchpad, source_branch)
        if target_branch is None:
            self.target_branch = self.source_branch.get_target()
        else:
            self.target_branch = lp_api.LaunchpadBranch.from_bzr(
                self.launchpad, target_branch)
        self.commit_message = message
        # XXX: this is where bug lp:583638 could be tackled.
        if reviews == []:
            self.reviews = []
        else:
            self.reviews = [(self.launchpad.people[reviewer], review_type)
                            for reviewer, review_type in
                            reviews]
        self.approve = approve
        self.fixes = fixes

    def get_comment(self, prerequisite_branch):
        """Determine the initial comment for the merge proposal."""
        if self.commit_message is not None:
            return self.commit_message.strip().encode('utf-8')
        info = ["Source: %s\n" % self.source_branch.lp.bzr_identity]
        info.append("Target: %s\n" % self.target_branch.lp.bzr_identity)
        if prerequisite_branch is not None:
            info.append("Prereq: %s\n" % prerequisite_branch.lp.bzr_identity)
        for rdata in self.reviews:
            uniquename = "%s (%s)" % (rdata[0].display_name, rdata[0].name)
            info.append('Reviewer: %s, type "%s"\n' % (uniquename, rdata[1]))
        with self.source_branch.bzr.lock_read(), \
                self.target_branch.bzr.lock_read():
            body = self.get_initial_body()
        initial_comment = msgeditor.edit_commit_message(''.join(info),
                                                        start_message=body)
        return initial_comment.strip().encode('utf-8')

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
        target_loc = ('bzr+ssh://bazaar.launchpad.net/%s' %
                      self.target_branch.lp.unique_name)
        body = None
        for hook in self.hooks['merge_proposal_body']:
            body = hook({
                'tree': self.tree,
                'target_branch': target_loc,
                'modified_files_callback': list_modified_files,
                'old_body': body,
            })
        return body

    def get_source_revid(self):
        """Get the revision ID of the source branch."""
        source_branch = self.source_branch.bzr
        with source_branch.lock_read():
            return source_branch.last_revision()

    def check_proposal(self):
        """Check that the submission is sensible."""
        if self.source_branch.lp.self_link == self.target_branch.lp.self_link:
            raise errors.CommandError(
                'Source and target branches must be different.')
        for mp in self.source_branch.lp.landing_targets:
            if mp.queue_status in ('Merged', 'Rejected'):
                continue
            if mp.target_branch.self_link == self.target_branch.lp.self_link:
                raise errors.CommandError(gettext(
                    'There is already a branch merge proposal: %s') %
                    lp_api.canonical_url(mp))

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

    def call_webservice(self, call, *args, **kwargs):
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
        revid = self.get_source_revid()
        self.call_webservice(
            mp.createComment,
            vote=u'Approve',
            subject='',  # Use the default subject.
            content=u"Rubberstamp! Proposer approves of own proposal.")
        self.call_webservice(mp.setStatus, status=u'Approved', revid=revid)

    def create_proposal(self):
        """Perform the submission."""
        prerequisite_branch = self._get_prerequisite_branch()
        if prerequisite_branch is None:
            prereq = None
        else:
            prereq = prerequisite_branch.lp
            prerequisite_branch.update_lp()
        self.source_branch.update_lp()
        reviewers = []
        review_types = []
        for reviewer, review_type in self.reviews:
            review_types.append(review_type)
            reviewers.append(reviewer.self_link)
        initial_comment = self.get_comment(prerequisite_branch)
        mp = self.call_webservice(
            self.source_branch.lp.createMergeProposal,
            target_branch=self.target_branch.lp,
            prerequisite_branch=prereq,
            initial_comment=initial_comment,
            commit_message=self.commit_message, reviewers=reviewers,
            review_types=review_types)
        if self.approve:
            self.approve_proposal(mp)
        if self.fixes:
            if self.fixes.startswith('lp:'):
                self.fixes = self.fixes[3:]
            self.call_webservice(
                self.source_branch.lp.linkBug,
                bug=self.launchpad.bugs[int(self.fixes)])
        webbrowser.open(lp_api.canonical_url(mp))


def modified_files(old_tree, new_tree):
    """Return a list of paths in the new tree with modified contents."""
    for change in new_tree.iter_changes(old_tree):
        if change.changed_content and change.kind[1] == 'file':
            yield str(path)
