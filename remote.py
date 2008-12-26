# Copyright (C) 2007-2008 Canonical Ltd
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

from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.errors import NotLocalUrl
from bzrlib.foreign import ForeignRepository
from bzrlib.lockable_files import TransportLock

from bzrlib.plugins.git import git
from bzrlib.plugins.git.repository import GitFormat
from bzrlib.trace import info
from bzrlib.transport import Transport

from git.client import TCPGitClient, TCP_GIT_PORT

import urllib
import urlparse


class GitSmartTransport(Transport):

    def __init__(self, url):
        Transport.__init__(self, url)
        (scheme, netloc, self._path, _, _) = urlparse.urlsplit(url)
        assert scheme == "git"
        (self._host, self._port) = urllib.splitnport(netloc, TCP_GIT_PORT)
        self._client = TCPGitClient(self._host, self._port)

    def fetch_pack(self, determine_wants, graph_walker, pack_data):
        def progress(text):
            info("git: %s" % text)
        self._client.fetch_pack(self._path, determine_wants, graph_walker, 
                pack_data, progress)


class RemoteGitDir(BzrDir):

    _gitrepository_class = RemoteGitRepository

    def __init__(self, transport, lockfiles, gitrepo, format):
        self._format = format
        self.root_transport = transport
        self._git = gitrepo
        self.transport = transport
        self._lockfiles = lockfiles

    def is_supported(self):
        return True

    def open_repository(self):
        return RemoteGitRepository(self, self._lockfiles)

    def open_branch(self):
        repo = self.open_repository()
        # TODO: Support for multiple branches in one bzrdir in bzrlib!
        return RemoteGitBranch(repo, "HEAD")

    def open_workingtree(self):
        raise NotLocalUrl(self.transport.base)


class RemoteGitRepository(ForeignRepository):

    def __init__(self, gitdir, lockfiles):
        Repository.__init__(self, GitFormat(), gitdir, lockfiles)

    def fetch_pack(self, determine_wants, graph_walker, pack_data):
        self._transport.fetch_pack(determine_wants, graph_walker, pack_data)


def RemoteGitBranch(ForeignBranch):

    def __init__(self, repository, name):
        super(RemoteGitBranch, self).__init__(repository.get_mapping())
        self.repository = repository
        self.name = name


class RemoteGitBzrDirFormat(BzrDirFormat):
    """The .git directory control format."""

    _gitdir_class = RemoteGitDir
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
        return "Remote Git Repository"

    def get_format_string(self):
        return "Remote Git Repository"

    def initialize_on_transport(self, transport):
        raise UninitializableFormat(self)

    def is_supported(self):
        return True
