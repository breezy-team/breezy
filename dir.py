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

import os

import bzrlib
from bzrlib.lazy_import import lazy_import
from bzrlib import (
    bzrdir,
    lockable_files,
    urlutils,
    )

lazy_import(globals(), """
from bzrlib.lockable_files import TransportLock
from bzrlib.plugins.git import (
    errors,
    branch,
    repository,
    workingtree,
    )
""")



class GitLock(object):
    """A lock that thunks through to Git."""

    def lock_write(self, token=None):
        pass

    def lock_read(self):
        pass

    def unlock(self):
        pass

    def peek(self):
        pass

    def validate_token(self, token):
        pass


class GitLockableFiles(lockable_files.LockableFiles):
    """Git specific lockable files abstraction."""

    def __init__(self, transport, lock):
        self._lock = lock
        self._transaction = None
        self._lock_mode = None
        self._lock_count = 0
        self._transport = transport


class GitDir(bzrdir.BzrDir):
    """An adapter to the '.git' dir used by git."""

    _gitrepository_class = repository.GitRepository

    def __init__(self, transport, lockfiles, gitrepo, format):
        self._format = format
        self.root_transport = transport
        self._git = gitrepo
        if gitrepo.bare:
            self.transport = transport
        else:
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
        """'create' a branch for this dir."""
        repo = self.open_repository()
        if repo._git.heads == []:
            head = None
        else:
            head = repo._git.head()
        return branch.GitBranch(self, repo, head, 
                                    self.root_transport.base, self._lockfiles)

    def open_repository(self, shared=False):
        """'open' a repository for this dir."""
        return self._gitrepository_class(self, self._lockfiles)

    def open_workingtree(self, recommend_upgrade=True):
        if self._git.bare:
            loc = urlutils.unescape_for_display(self.root_transport.base, 'ascii')
            raise errors.bzr_errors.NoWorkingTree(loc)
        else:
            return workingtree.GitWorkingTree(self, self.open_repository(), 
                                                  self.open_branch())

    def cloning_metadir(self, stacked=False):
        if stacked:
            return bzrlib.bzrdir.format_registry.make_bzrdir("pack-0.92")
        else:
            return bzrlib.bzrdir.format_registry.make_bzrdir("1.6")

    def create_repository(self, shared=False):
        return self.open_repository()


class GitBzrDirFormat(bzrdir.BzrDirFormat):
    """The .git directory control format."""

    _gitdir_class = GitDir
    _lock_class = TransportLock

    @classmethod
    def _known_formats(self):
        return set([GitBzrDirFormat()])

    def open(self, transport, _found=None):
        """Open this directory.

        """
        from bzrlib.plugins.git import git
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]

        try:
            gitrepo = git.repo.Repo(transport.local_abspath("."))
        except errors.bzr_errors.NotLocalUrl:
            raise errors.bzr_errors.NotBranchError(path=transport.base)
        lockfiles = GitLockableFiles(transport, GitLock())
        return self._gitdir_class(transport, lockfiles, gitrepo, self)

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

    def get_format_description(self):
        return "Local Git Repository"

    def get_format_string(self):
        return "Local Git Repository"

    def initialize_on_transport(self, transport):
        from bzrlib.transport.local import LocalTransport
        from bzrlib.plugins.git import git

        if not isinstance(transport, LocalTransport):
            raise NotImplementedError(self.initialize, 
                "Can't create Git Repositories/branches on "
                "non-local transports")

        git.repo.Repo.create(transport.local_abspath(".")) 
        return self.open(transport)


bzrdir.BzrDirFormat.register_control_format(GitBzrDirFormat)
