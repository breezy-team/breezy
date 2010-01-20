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


_lp = None
def lp(staging=False):
    if staging:
        service_root = launchpad.STAGING_SERVICE_ROOT
    else:
        service_root = launchpad.EDGE_SERVICE_ROOT
    global _lp
    if _lp is not None:
        return _lp
    _lp = lp_api.login(service_root)
    return _lp


class MegaBranch(object):

    def __init__(self, lp_branch, bzr_url, bzr_branch=None, check_update=True):
        self.bzr_url = bzr_url
        self._bzr = bzr_branch
        self._push_bzr = None
        self._check_update = False
        self.lp = lp_branch

    @property
    def bzr(self):
        if self._bzr is None:
            self._bzr = branch.Branch.open(self.bzr_url)
        return self._bzr

    @property
    def push_bzr(self):
        if self._push_bzr is None:
            self._push_bzr = branch.Branch.open(self.lp.bzr_identity)
        return self._push_bzr

    @staticmethod
    def plausible_launchpad_url(url):
        if url is None:
            return False
        if url.startswith('lp:'):
            return True
        regex = re.compile('([a-z]*\+)*(bzr\+ssh|http)'
                           '://bazaar.*.launchpad.net')
        return bool(regex.match(url))

    @staticmethod
    def candidate_urls(bzr_branch):
        url = bzr_branch.get_public_branch()
        if url is not None:
            yield url
        url = bzr_branch.get_push_location()
        if url is not None:
            yield url
        yield bzr_branch.base

    @staticmethod
    def tweak_url(url, staging):
        if not staging:
            return url
        if url is None:
            return None
        return url.replace('bazaar.launchpad.net',
                           'bazaar.staging.launchpad.net')

    @classmethod
    def from_bzr(cls, bzr_branch, staging=False):
        check_update = True
        for url in cls.candidate_urls(bzr_branch):
            url = cls.tweak_url(url, staging)
            if not cls.plausible_launchpad_url(url):
                continue
            lp_branch = lp(staging).branches.getByUrl(url=url)
            if lp_branch is not None:
                break
        else:
            lp_branch = cls.create_now(bzr_branch, staging)
            check_update = False
        return cls(lp_branch, bzr_branch.base, bzr_branch, check_update)

    @classmethod
    def create_now(cls, bzr_branch, staging):
        url = cls.tweak_url(bzr_branch.get_push_location(), staging)
        if not cls.plausible_launchpad_url(url):
            raise errors.BzrError('%s is not registered on Launchpad' %
                                  bzr_branch.base)
        bzr_branch.create_clone_on_transport(transport.get_transport(url))
        lp_branch = lp(staging).branches.getByUrl(url=url)
        if lp_branch is None:
            raise errors.BzrError('%s is not registered on Launchpad' % url)
        return lp_branch

    @classmethod
    def from_dev_focus(cls, lp_branch):
        if lp_branch.project is None:
            raise errors.BzrError('%s has no product.' %
                                  lp_branch.bzr_identity)
        dev_focus = lp_branch.project.development_focus.branch
        if dev_focus is None:
            raise errors.BzrError('%s has no development focus.' %
                                  lp_branch.bzr_identity)
        return cls(dev_focus, dev_focus.bzr_identity)

    def update_lp(self):
        if not self._check_update:
            return
        self.bzr.lock_read()
        try:
            if self.lp.last_scanned_id is not None:
                if self.bzr.last_revision() == self.lp.last_scanned_id:
                    trace.note('%s is already up-to-date.' %
                               self.lp.bzr_identity)
                    return
                graph = self.bzr.repository.get_graph()
                if not graph.is_ancestor(self.bzr.last_revision(),
                                         self.lp.last_scanned_id):
                    raise errors.DivergedBranches(self.bzr, self.push_bzr)
                trace.note('Pushing to %s' % self.lp.bzr_identity)
            self.bzr.push(self.push_bzr)
        finally:
            self.bzr.unlock()

    def find_lca_tree(self, other):
        graph = self.bzr.repository.get_graph(other.bzr.repository)
        lca = graph.find_unique_lca(self.bzr.last_revision(),
                                    other.bzr.last_revision())
        return self.bzr.repository.revision_tree(lca)


class Submitter(object):

    def __init__(self, tree, manager, target_branch, message, reviews,
                 staging=False):
        self.tree = tree
        self.manager = manager
        self.staging = staging
        self.source_branch = MegaBranch.from_bzr(self.manager.storage.branch,
                                                 self.staging)
        if target_branch is None:
            self.target_branch = MegaBranch.from_dev_focus(
                self.source_branch.lp)
        else:
            self.target_branch = MegaBranch.from_bzr(target_branch,
                                                     self.staging)
        self.commit_message = message
        if reviews == []:
            target_reviewer = self.target_branch.lp.reviewer
            if target_reviewer is None:
                raise errors.BzrCommandError('No reviewer specified')
            self.reviews = [(target_reviewer, '')]
        else:
            self.reviews = [(lp(self.staging).people[reviewer], review_type)
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
            prerequisite_branch = MegaBranch.from_bzr(prev_pipe)
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

