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

import re

from .propose import (
    Hoster,
    LabelsUnsupported,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    UnsupportedHoster,
    )

from ... import (
    branch as _mod_branch,
    controldir,
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
from ...transport import get_transport


# TODO(jelmer): Make selection of launchpad staging a configuration option.


def plausible_launchpad_url(url):
    if url is None:
        return False
    if url.startswith('lp:'):
        return True
    regex = re.compile('([a-z]*\+)*(bzr\+ssh|http|ssh|git|https)'
                       '://(bazaar|git).*.launchpad.net')
    return bool(regex.match(url))


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
            if line.startswith('Traceback (most recent call last):'):
                break
            error_lines.append(line)
        raise Exception(''.join(error_lines))


class Launchpad(Hoster):
    """The Launchpad hosting service."""

    supports_merge_proposal_labels = False

    def __init__(self, staging=False):
        if staging:
            lp_instance = 'staging'
        else:
            lp_instance = 'production'
        self.launchpad = connect_launchpad(lp_instance)

    @classmethod
    def probe(cls, branch):
        if plausible_launchpad_url(branch.user_url):
            return Launchpad()
        raise UnsupportedHoster(branch)

    def _get_derived_git_path(self, base_path, owner, project):
        base_repo = self.launchpad.git_repositories.getByPath(path=base_path)
        if project is None:
            project = '/'.join(base_repo.unique_name.split('/')[1:])
        # TODO(jelmer): Surely there is a better way of creating one of these URLs?
        return "~%s/%s" % (owner, project)

    def _publish_git(self, local_branch, base_path, name, owner, project=None,
                     revision_id=None, overwrite=False):
        to_path = self._get_derived_git_path(base_path, owner, project)
        to_transport = get_transport("git+ssh://git.launchpad.net/" + to_path)
        try:
            dir_to = controldir.ControlDir.open_from_transport(to_transport)
        except errors.NotBranchError:
            # Didn't find anything
            dir_to = None

        if dir_to is None:
            br_to = local_branch.create_clone_on_transport(to_transport, revision_id=revision_id, name=name)
        else:
            br_to = dir_to.push_branch(local_branch, revision_id, overwrite=overwrite, name=name).target_branch
        return br_to, ("https://git.launchpad.net/%s/+ref/%s" % (to_path, name))

    def _get_derived_bzr_path(self, base_url, name, owner, project):
        if project is None:
            base_branch_lp = self.launchpad.branches.getByUrl(url=base_url)
            project = '/'.join(base_branch_lp.unique_name.split('/')[1:-1])
        # TODO(jelmer): Surely there is a better way of creating one of these URLs?
        return "~%s/%s/%s" % (owner, project, name)

    def _publish_bzr(self, local_branch, base_url, name, owner, project=None,
                revision_id=None, overwrite=False):
        to_path = self._get_derived_bzr_path(base_url, name, owner, project)
        to_transport = get_transport("lp:" + to_path)
        try:
            dir_to = controldir.ControlDir.open_from_transport(to_transport)
        except errors.NotBranchError:
            # Didn't find anything
            dir_to = None

        if dir_to is None:
            br_to = local_branch.create_clone_on_transport(to_transport, revision_id=revision_id)
        else:
            br_to = dir_to.push_branch(local_branch, revision_id, overwrite=overwrite).target_branch
        return br_to, ("https://code.launchpad.net/" + to_path)

    def publish_derived(self, local_branch, base_branch, name, project=None, owner=None,
                        revision_id=None, overwrite=False):
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
        base_url, base_params = urlutils.split_segment_parameters(base_branch.user_url)
        (base_scheme, base_user, base_password, base_host, base_port, base_path) = urlutils.parse_url(
            base_url)
        base_path = base_path.strip('/')
        # TODO(jelmer): Prevent publishing to development focus
        if base_host.startswith('bazaar.'):
            return self._publish_bzr(local_branch, base_url, name,
                    project=project, owner=owner, revision_id=revision_id,
                    overwrite=overwrite)
        elif base_host.startswith('git.'):
            return self._publish_git(local_branch, base_path, name,
                    project=project, owner=owner, revision_id=revision_id,
                    overwrite=overwrite)
        else:
            raise AssertionError('not a valid Launchpad URL')

    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        if owner is None:
            owner = self.launchpad.me.name
        base_url, base_params = urlutils.split_segment_parameters(base_branch.user_url)
        (base_scheme, base_user, base_password, base_host, base_port, base_path) = urlutils.parse_url(
            base_url)
        if base_host.startswith('bazaar.'):
            to_path = self._get_derived_bzr_path(base_url, name, owner, project)
            return _mod_branch.Branch.open("lp:" + to_path)
        elif base_host.startswith('git.'):
            to_path = self._get_derived_git_path(base_path.strip('/'), owner, project)
            return _mod_branch.Branch.open_from_transport(
                    "git+ssh://git.launchpad.net/" + to_path, name)
        else:
            raise AssertionError('not a valid Launchpad URL')

    def get_proposer(self, source_branch, target_branch):
        (base_scheme, base_user, base_password, base_host, base_port, base_path) = urlutils.parse_url(
            target_branch.user_url)
        if base_host.startswith('bazaar.'):
            return LaunchpadBazaarMergeProposalBuilder(
                    self.launchpad, source_branch, target_branch)
        elif base_host.startswith('git.'):
            return LaunchpadGitMergeProposalBuilder(
                    self.launchpad, source_branch, target_branch)
        else:
            raise AssertionError('not a valid Launchpad URL')


def connect_launchpad(lp_instance='production'):
    service = lp_registration.LaunchpadService(lp_instance=lp_instance)
    return lp_api.login(service, version='devel')


class LaunchpadBazaarMergeProposalBuilder(MergeProposalBuilder):

    def __init__(self, launchpad, source_branch, target_branch, message=None,
                 staging=None, approve=None, fixes=None):
        """Constructor.

        :param source_branch: The branch to propose for merging.
        :param target_branch: The branch to merge into.
        :param message: The commit message to use.  (May be None.)
        :param staging: If True, propose the merge against staging instead of
            production.
        :param approve: If True, mark the new proposal as approved immediately.
            This is useful when a project permits some things to be approved
            by the submitter (e.g. merges between release and deployment
            branches).
        """
        self.launchpad = launchpad
        self.source_branch = source_branch
        self.source_branch_lp = self.launchpad.branches.getByUrl(url=source_branch.user_url)
        if target_branch is None:
            self.target_branch_lp = self.source_branch_lp.get_target()
            self.target_branch = _mod_branch.Branch.open(self.target_branch_lp.bzr_identity)
        else:
            self.target_branch = target_branch
            self.target_branch_lp = self.launchpad.branches.getByUrl(url=target_branch.user_url)
        self.prerequisite_branch = self._get_prerequisite_branch()
        self.commit_message = message
        self.approve = approve
        self.fixes = fixes

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        if self.commit_message is not None:
            return self.commit_message.strip().encode('utf-8')
        info = ["Source: %s\n" % self.source_branch_lp.bzr_identity]
        info.append("Target: %s\n" % self.target_branch_lp.bzr_identity)
        if self.prerequisite_branch is not None:
            info.append("Prereq: %s\n" % self.prerequisite_branch.bzr_identity)
        return ''.join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        if not self.hooks['merge_proposal_body']:
            return None

        def list_modified_files():
            lca_tree = self.source_branch_lp.find_lca_tree(
                self.target_branch_lp)
            source_tree = self.source_branch.basis_tree()
            files = modified_files(lca_tree, source_tree)
            return list(files)
        with self.target_branch.lock_read(), \
                self.source_branch.lock_read():
            body = None
            for hook in self.hooks['merge_proposal_body']:
                body = hook({
                    'target_branch': self.target_branch_lp.bzr_identity,
                    'modified_files_callback': list_modified_files,
                    'old_body': body,
                })
            return body

    def check_proposal(self):
        """Check that the submission is sensible."""
        if self.source_branch_lp.self_link == self.target_branch_lp.self_link:
            raise errors.BzrCommandError(
                'Source and target branches must be different.')
        for mp in self.source_branch_lp.landing_targets:
            if mp.queue_status in ('Merged', 'Rejected'):
                continue
            if mp.target_branch.self_link == self.target_branch_lp.self_link:
                raise MergeProposalExists(lp_api.canonical_url(mp))

    def _get_prerequisite_branch(self):
        hooks = self.hooks['get_prerequisite']
        prerequisite_branch = None
        for hook in hooks:
            prerequisite_branch = hook(
                {'launchpad': self.launchpad,
                 'source_branch': self.source_branch_lp,
                 'target_branch': self.target_branch_lp,
                 'prerequisite_branch': prerequisite_branch})
        return prerequisite_branch

    def approve_proposal(self, mp):
        with self.source_branch.lock_read():
            _call_webservice(
                mp.createComment,
                vote=u'Approve',
                subject='', # Use the default subject.
                content=u"Rubberstamp! Proposer approves of own proposal.")
            _call_webservice(mp.setStatus, status=u'Approved', revid=source_branch.last_revision())

    def create_proposal(self, description, reviewers=None, labels=None):
        """Perform the submission."""
        if labels:
            raise LabelsUnsupported()
        if self.prerequisite_branch is None:
            prereq = None
        else:
            prereq = self.prerequisite_branch.lp
            self.prerequisite_branch.update_lp()
        if reviewers is None:
            reviewers = []
        mp = _call_webservice(
            self.source_branch_lp.createMergeProposal,
            target_branch=self.target_branch_lp,
            prerequisite_branch=prereq,
            initial_comment=description.strip().encode('utf-8'),
            commit_message=self.commit_message,
            reviewers=[self.launchpad.people[reviewer].self_link
                       for reviewer in reviewers],
            review_types=[None for reviewer in reviewers])
        if self.approve:
            self.approve_proposal(mp)
        if self.fixes:
            if self.fixes.startswith('lp:'):
                self.fixes = self.fixes[3:]
            _call_webservice(
                mp.linkBug,
                bug=self.launchpad.bugs[int(self.fixes)])
        return MergeProposal(lp_api.canonical_url(mp))


class LaunchpadGitMergeProposalBuilder(MergeProposalBuilder):

    def _get_lp_ref_from_branch(self, branch):
        url, params = urlutils.split_segment_parameters(branch.user_url)
        (scheme, user, password, host, port, path) = urlutils.parse_url(
            url)
        repo_lp = self.launchpad.git_repositories.getByPath(path=path.strip('/'))
        ref_lp = repo_lp.getRefByPath(path=params.get('branch', repo_lp.default_branch))
        return (repo_lp, ref_lp)

    def __init__(self, launchpad, source_branch, target_branch, message=None,
                 staging=None, approve=None, fixes=None):
        """Constructor.

        :param source_branch: The branch to propose for merging.
        :param target_branch: The branch to merge into.
        :param message: The commit message to use.  (May be None.)
        :param staging: If True, propose the merge against staging instead of
            production.
        :param approve: If True, mark the new proposal as approved immediately.
            This is useful when a project permits some things to be approved
            by the submitter (e.g. merges between release and deployment
            branches).
        """
        self.launchpad = launchpad
        self.source_branch = source_branch
        (self.source_repo_lp, self.source_branch_lp) = self._get_lp_ref_from_branch(source_branch)
        if target_branch is None:
            self.target_branch_lp = self.source_branch.get_target()
            self.target_branch = _mod_branch.Branch.open(self.target_branch_lp.bzr_identity)
        else:
            self.target_branch = target_branch
            (self.target_repo_lp, self.target_branch_lp) = self._get_lp_ref_from_branch(target_branch)
        self.prerequisite_branch = self._get_prerequisite_branch()
        self.commit_message = message
        self.approve = approve
        self.fixes = fixes

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        if self.commit_message is not None:
            return self.commit_message.strip().encode('utf-8')
        info = ["Source: %s\n" % self.source_branch.user_url]
        info.append("Target: %s\n" % self.target_branch.user_url)
        if self.prerequisite_branch is not None:
            info.append("Prereq: %s\n" % self.prerequisite_branch.user_url)
        return ''.join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        if not self.hooks['merge_proposal_body']:
            return None

        def list_modified_files():
            lca_tree = self.source_branch_lp.find_lca_tree(
                self.target_branch_lp)
            source_tree = self.source_branch.basis_tree()
            files = modified_files(lca_tree, source_tree)
            return list(files)
        with self.target_branch.lock_read(), \
                self.source_branch.lock_read():
            body = None
            for hook in self.hooks['merge_proposal_body']:
                body = hook({
                    'target_branch': self.target_branch,
                    'modified_files_callback': list_modified_files,
                    'old_body': body,
                })
            return body

    def check_proposal(self):
        """Check that the submission is sensible."""
        if self.source_branch_lp.self_link == self.target_branch_lp.self_link:
            raise errors.BzrCommandError(
                'Source and target branches must be different.')
        for mp in self.source_branch_lp.landing_targets:
            if mp.queue_status in ('Merged', 'Rejected'):
                continue
            if mp.target_branch.self_link == self.target_branch_lp.self_link:
                raise MergeProposalExists(lp_api.canonical_url(mp))

    def _get_prerequisite_branch(self):
        hooks = self.hooks['get_prerequisite']
        prerequisite_branch = None
        for hook in hooks:
            prerequisite_branch = hook(
                {'launchpad': self.launchpad,
                 'source_branch': self.source_branch_lp,
                 'target_branch': self.target_branch_lp,
                 'prerequisite_branch': prerequisite_branch})
        return prerequisite_branch

    def approve_proposal(self, mp):
        with self.source_branch.lock_read():
            _call_webservice(
                mp.createComment,
                vote=u'Approve',
                subject='', # Use the default subject.
                content=u"Rubberstamp! Proposer approves of own proposal.")
            _call_webservice(mp.setStatus, status=u'Approved', revid=source_branch.last_revision())

    def create_proposal(self, description, reviewers=None, labels=None):
        """Perform the submission."""
        if labels:
            raise LabelsUnsupported()
        if self.prerequisite_branch is None:
            prereq = None
        else:
            prereq = self.prerequisite_branch.lp
            self.prerequisite_branch.update_lp()
        if reviewers is None:
            reviewers = []
        try:
            mp = _call_webservice(
                self.source_branch_lp.createMergeProposal,
                merge_target=self.target_branch_lp,
                merge_prerequisite=prereq,
                initial_comment=description.strip().encode('utf-8'),
                commit_message=self.commit_message,
                needs_review=True,
                reviewers=[self.launchpad.people[reviewer].self_link
                           for reviewer in reviewers],
                review_types=[None for reviewer in reviewers])
        except Exception as e:
            # Urgh.
            if ('There is already a branch merge proposal '
                'registered for branch ') in e.message:
                raise MergeProposalExists(self.source_branch.user_url)
            raise
        if self.approve:
            self.approve_proposal(mp)
        if self.fixes:
            if self.fixes.startswith('lp:'):
                self.fixes = self.fixes[3:]
            _call_webservice(
                mp.linkBug,
                bug=self.launchpad.bugs[int(self.fixes)])
        return MergeProposal(lp_api.canonical_url(mp))
