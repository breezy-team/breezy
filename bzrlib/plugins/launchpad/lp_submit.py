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
from bzrlib.hooks import HookPoint, Hooks
from bzrlib.plugins.launchpad import lp_api
from bzrlib.plugins.launchpad import lp_registration

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


class LaunchpadSubmitterHooks(Hooks):
    """Hooks for submitting a branch to Launchpad for review."""

    def __init__(self):
        Hooks.__init__(self)
        self.create_hook(
            HookPoint(
                'get_prerequisite',
                "Return the prerequisite branch for proposing as merge.",
                (2, 1), None))


class Submitter(object):

    hooks = LaunchpadSubmitterHooks()

    def __init__(self, tree, source_branch, target_branch, message, reviews,
                 staging=False):
        self.tree = tree
        if staging:
            lp_instance = 'staging'
        else:
            lp_instance = 'edge'
        service = lp_registration.LaunchpadService(lp_instance=lp_instance)
        self.launchpad = lp_api.login(service)
        self.source_branch = lp_api.LaunchpadBranch.from_bzr(
            self.launchpad, source_branch)
        if target_branch is None:
            self.target_branch = self.source_branch.get_dev_focus()
        else:
            self.target_branch = lp_api.LaunchpadBranch.from_bzr(
                self.launchpad, target_branch)
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

    def submit(self):
        prerequisite_branch = self._get_prerequisite_branch()
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
                prerequisite_branch=prereq,
                initial_comment=initial_comment,
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
