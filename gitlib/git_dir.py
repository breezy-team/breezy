# Copyright (C) 2007 Canonical Ltd
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

"""An adapter between a Git control dir and a Bazaar BzrDir"""

from bzrlib.lazy_import import lazy_import
from bzrlib import (
    bzrdir,
    lockable_files,
    urlutils,
    )

lazy_import(globals(), """
from bzrlib.plugins.git.gitlib import (
    errors,
    git_branch,
    git_repository,
    )
""")


class GitLock(object):
    """A lock that thunks through to Git."""

    def lock_write(self):
        pass

    def lock_read(self):
        pass

    def unlock(self):
        pass


class GitLockableFiles(lockable_files.LockableFiles):
    """Git specific lockable files abstraction."""

    def __init__(self, lock):
        self._lock = lock
        self._transaction = None
        self._lock_mode = None
        self._lock_count = 0


class GitDir(bzrdir.BzrDir):
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
        raise errors.bzr_errors.IncompatibleFormat(branch_format, self._format)

    get_repository_transport = get_branch_transport
    get_workingtree_transport = get_branch_transport

    def is_supported(self):
        return True

    def open_branch(self, ignored=None):
        """'crate' a branch for this dir."""
        return git_branch.GitBranch(self, self._lockfiles)

    def open_repository(self, shared=False):
        """'open' a repository for this dir."""
        return git_repository.GitRepository(self, self._lockfiles)

    def open_workingtree(self):
        loc = urlutils.unescape_for_display(self.root_transport.base, 'ascii')
        raise errors.bzr_errors.NoWorkingTree(loc)


class GitBzrDirFormat(bzrdir.BzrDirFormat):
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
        path = urlutils.local_path_from_url(url)
        if not transport.has('.git'):
            raise errors.bzr_errors.NotBranchError(path=transport.base)
        lockfiles = GitLockableFiles(GitLock())
        return GitDir(transport, lockfiles, self)

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in '.not/'."""
        # little ugly, but works
        format = klass()
        # delegate to the main opening code. This pays a double rtt cost at the
        # moment, so perhaps we want probe_transport to return the opened thing
        # rather than an openener ? or we could return a curried thing with the
        # dir to open already instantiated ? Needs more thought.
        try:
            format.open(transport)
            return format
        except Exception, e:
            raise errors.bzr_errors.NotBranchError(path=transport.base)
        raise errors.bzr_errors.NotBranchError(path=transport.base)


bzrdir.BzrDirFormat.register_control_format(GitBzrDirFormat)
