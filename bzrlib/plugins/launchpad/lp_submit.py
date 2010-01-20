import errno, re, webbrowser

from bzrlib import (
    branch,
    config,
    errors,
    msgeditor,
    osutils,
    trace,
    transport,
)
from bzrlib.plugins.launchpad import lp_api

class NoLaunchpadLib(errors.BzrCommandError):

    _fmt = "LaunchpadLib must be installed for this operation."


try:
    from launchpadlib import (
        credentials,
        launchpad,
    )
except ImportError:
    raise NoLaunchpadLib()

from lazr.restfulclient import errors as restful_errors


class Submitter(object):

    def __init__(self, tree, manager, target_branch, message, reviews,
                 staging=False):
        self.tree = tree
        self.manager = manager
        if staging:
            service_root = launchpad.STAGING_SERVICE_ROOT
        else:
            service_root = launchpad.EDGE_SERVICE_ROOT
        self.launchpad = lp_api.login(service_root)
        self.source_branch = lp_api.LaunchpadBranch.from_bzr(
            self.manager.storage.branch, self.launchpad)
        if target_branch is None:
            # XXX: Change this to get_dev_Focus on the source branch.
            self.target_branch = lp_api.LaunchpadBranch.from_dev_focus(
                self.source_branch.lp)
        else:
            self.target_branch = lp_api.LaunchpadBranch.from_bzr(
                target_branch, self.launchpad)
        self.commit_message = message
        if reviews == []:
            target_reviewer = self.target_branch.lp.reviewer
            if target_reviewer is None:
                raise errors.BzrCommandError('No reviewer specified')
            self.reviews = [(target_reviewer, '')]
        else:
            self.reviews = [(self.launchpad.people[reviewer], review_type)
                            for reviewer, review_type in
                            reviews]

    def get_comment(self, prerequisite_branch):
        info = ["Source: %s\n" % self.source_branch.lp.bzr_identity]
        info.append("Target: %s\n" % self.target_branch.lp.bzr_identity)
        if prerequisite_branch is not None:
            info.append("Prereq: %s\n" % prerequisite_branch.lp.bzr_identity)
        for rdata in self.reviews:
            uniquename = "%s (%s)" % (rdata[0].display_name, rdata[0].name)
            info.append('Reviewer: %s, type "%s"\n' % (uniquename, rdata[1]))
        self.source_branch.bzr.lock_read()
        try:
            self.target_branch.bzr.lock_read()
            try:
                body = self.try_get_body()
            finally:
                self.target_branch.bzr.unlock()
        finally:
            self.source_branch.bzr.unlock()
        initial_comment = msgeditor.edit_commit_message(''.join(info),
                                                        start_message=body)
        return initial_comment.strip().encode('utf-8')

    def try_get_body(self):
        try:
            from bzrlib.plugins.lpreview_body.body_callback import (
                get_body,
                modified_files,
            )
        except ImportError:
            return ''
        def list_modified_files():
            lca_tree = self.source_branch.find_lca_tree(
                self.target_branch)
            source_tree = self.source_branch.bzr.basis_tree()
            files = modified_files(lca_tree, source_tree)
            return list(files)
        target_loc = ('bzr+ssh://bazaar.launchpad.net/%s' %
                       self.target_branch.lp.unique_name)
        return get_body(self.tree, target_loc, list_modified_files, '')

    def check_submission(self):
        if self.source_branch.lp.self_link == self.target_branch.lp.self_link:
            raise errors.BzrCommandError(
                'Source and target branches must be different.')
        for mp in self.source_branch.lp.landing_targets:
            if mp.queue_status in ('Merged', 'Rejected'):
                continue
            if mp.target_branch.self_link == self.target_branch.lp.self_link:
                raise errors.BzrCommandError(
                    'There is already a branch merge proposal: %s' %
                    canonical_url(mp))

    def submit(self):
        prev_pipe = self.manager.get_prev_pipe()
        if prev_pipe is not None:
            prerequisite_branch = lp_api.LaunchpadBranch.from_bzr(self.launchpad, prev_pipe)
        else:
            prerequisite_branch = None
        self.source_branch.update_lp()
        if prerequisite_branch is not None:
            prerequisite_branch.update_lp()
        if prerequisite_branch is None:
            prereq = None
        else:
            prereq = prerequisite_branch.lp
        reviewers = []
        review_types = []
        for reviewer, review_type in self.reviews:
            review_types.append(review_type)
            reviewers.append(reviewer.self_link)
        initial_comment = self.get_comment(prerequisite_branch)
        try:
            mp = self.source_branch.lp.createMergeProposal(
                target_branch=self.target_branch.lp,
                prerequisite_branch=prereq, initial_comment=initial_comment,
                commit_message=self.commit_message, reviewers=reviewers,
                review_types=review_types)
        except restful_errors.HTTPError, e:
            for line in e.content.splitlines():
                if line.startswith('Traceback (most recent call last):'):
                    break
                print line
        else:
            webbrowser.open(canonical_url(mp))

def canonical_url(object):
    url = object.self_link.replace('https://api.', 'https://code.')
    return url.replace('/beta/', '/')

