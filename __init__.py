# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""A GIT branch and repository format implementation for bzr."""


from StringIO import StringIO

import stgit
import stgit.git as git

from bzrlib import urlutils
from bzrlib.decorators import *
import bzrlib.branch
import bzrlib.bzrdir
import bzrlib.errors as errors
import bzrlib.repository
from bzrlib.revision import Revision


class GitTransport(object):

    def __init__(self):
        self.base = object()

    def get(self, relpath):
        assert relpath == 'branch.conf'
        return StringIO()


def gitrevid_from_bzr(revision_id):
    return revision_id[4:]


def bzrrevid_from_git(revision_id):
    return "git:" + revision_id


class GitLock(object):
    """A lock that thunks through to Git."""

    def lock_write(self):
        pass

    def lock_read(self):
        pass

    def unlock(self):
        pass


class GitLockableFiles(bzrlib.lockable_files.LockableFiles):
    """Git specific lockable files abstraction."""

    def __init__(self, lock):
        self._lock = lock
        self._transaction = None
        self._lock_mode = None
        self._lock_count = 0
        self._transport = GitTransport() 


class GitDir(bzrlib.bzrdir.BzrDir):
    """An adapter to the '.git' dir used by git."""

    def __init__(self, transport, lockfiles, format):
        self._format = format
        self.root_transport = transport
        self.transport = transport.clone('.git')
        self._lockfiles = lockfiles

    def get_branch_transport(self, branch_format):
        if branch_format is None:
            return self.transport
        if isinstance(branch_format, GitBzrDirFormat):
            return self.transport
        raise errors.IncompatibleFormat(branch_format, self._format)

    get_repository_transport = get_branch_transport
    get_workingtree_transport = get_branch_transport

    def is_supported(self):
        return True

    def open_branch(self, ignored=None):
        """'crate' a branch for this dir."""
        return GitBranch(self, self._lockfiles)

    def open_repository(self, shared=False):
        """'open' a repository for this dir."""
        return GitRepository(self._gitrepo, self, self._lockfiles)

    def open_workingtree(self):
        loc = urlutils.unescape_for_display(self.root_transport.base, 'ascii')
        raise errors.NoWorkingTree(loc)


class GitBzrDirFormat(bzrlib.bzrdir.BzrDirFormat):
    """The .git directory control format."""

    @classmethod
    def _known_formats(self):
        return set([GitBzrDirFormat()])

    def open(self, transport, _create=False, _found=None):
        """Open this directory.
        
        :param _create: create the git dir on the fly. private to GitDirFormat.
        """
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]
        if url.startswith('file://'):
            url = url[len('file://'):]
        url = url.encode('utf8')
        lockfiles = GitLockableFiles(GitLock())
        return GitDir(transport, lockfiles, self)

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in '.not/'."""
        # little ugly, but works
        format = klass() 
        # try a manual probe first, its a little faster perhaps ?
        if transport.has('.git'):
            return format
        # delegate to the main opening code. This pays a double rtt cost at the
        # moment, so perhaps we want probe_transport to return the opened thing
        # rather than an openener ? or we could return a curried thing with the
        # dir to open already instantiated ? Needs more thought.
        try:
            format.open(transport)
            return format
        except Exception, e:
            raise errors.NotBranchError(path=transport.base)
        raise errors.NotBranchError(path=transport.base)


bzrlib.bzrdir.BzrDirFormat.register_control_format(GitBzrDirFormat)


class GitBranch(bzrlib.branch.Branch):
    """An adapter to git repositories for bzr Branch objects."""

    def __init__(self, gitdir, lockfiles):
        self.bzrdir = gitdir
        self.control_files = lockfiles
        self.repository = GitRepository(gitdir, lockfiles)
        self.base = gitdir.root_transport.base

    def lock_write(self):
        self.control_files.lock_write()

    @needs_read_lock
    def last_revision(self):
        # perhaps should escape this ?
        return bzrrevid_from_git(git.get_head())

    def revision_history(self):
        history = [self.last_revision()]
        while True:
            revision = self.repository.get_revision(history[-1])
            if len(revision.parent_ids) == 0:
                break
            history.append(revision.parent_ids[0])
        return list(reversed(history))

    def lock_read(self):
        self.control_files.lock_read()

    def unlock(self):
        self.control_files.unlock()


class GitRepository(bzrlib.repository.Repository):
    """An adapter to git repositories for bzr."""

    def __init__(self, gitdir, lockfiles):
        self.bzrdir = gitdir
        self.control_files = lockfiles

    def get_revision(self, revision_id):
        raw = stgit.git._output_lines('git-rev-list --header --max-count=1 %s' % gitrevid_from_bzr(revision_id))
        # first field is the rev itself.
        # then its 'field value'
        # until the EOF??
        parents = []
        log = []
        in_log = False
        committer = None
        for field in raw[1:]:
            #if field.startswith('author '):
            #    committer = field[7:]
            if field.startswith('parent '):
                parents.append(bzrrevid_from_git(field.split()[1]))
            elif field.startswith('committer '):
                commit_fields = field.split()
                if committer is None:
                    committer = ' '.join(commit_fields[1:-3])
                timestamp = commit_fields[-2]
                timezone = commit_fields[-1]
            elif in_log:
                log.append(field)
            elif field == '\n':
                in_log = True

        log = ''.join(log)
        result = Revision(revision_id)
        result.parent_ids = parents
        result.message = log
        result.inventory_sha1 = ""
        result.timezone = timezone and int(timezone)
        result.timestamp = float(timestamp)
        result.committer = committer 
        return result
