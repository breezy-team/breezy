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

import bzrlib
from bzrlib import urlutils
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.errors import NoSuchFile, NotLocalUrl
from bzrlib.lockable_files import TransportLock
from bzrlib.repository import Repository
from bzrlib.trace import info
from bzrlib.transport import Transport

from bzrlib.plugins.git import git
from bzrlib.plugins.git.branch import GitBranch
from bzrlib.plugins.git.dir import GitDir
from bzrlib.plugins.git.foreign import ForeignBranch
from bzrlib.plugins.git.repository import GitFormat, GitRepository

import urllib
import urlparse

from dulwich.pack import PackData


class GitSmartTransport(Transport):

    def __init__(self, url, _client=None):
        Transport.__init__(self, url)
        (scheme, _, loc, _, _) = urlparse.urlsplit(url)
        assert scheme == "git"
        hostport, self._path = urllib.splithost(loc)
        (self._host, self._port) = urllib.splitnport(hostport, git.protocol.TCP_GIT_PORT)
        if _client is not None:
            self._client = _client
        else:
            self._client = git.client.TCPGitClient(self._host, self._port)

    def fetch_pack(self, determine_wants, graph_walker, pack_data, progress=None):
        if progress is None:
            def progress(text):
                info("git: %s" % text)
        self._client.fetch_pack(self._path, determine_wants, graph_walker, 
                pack_data, progress)

    def fetch_objects(self, determine_wants, graph_walker, progress=None):
        fd, path = tempfile.mkstemp(dir=self.pack_dir(), suffix=".pack")
        self.fetch_pack(determine_wants, graph_walker, lambda x: os.write(fd, x), progress)
        os.close(fd)
        try:
            p = PackData(path)
            for o in p.iterobjects():
                yield o
        finally:
            os.remove(path)

    def get(self, path):
        raise NoSuchFile(path)

    def clone(self, offset=None):
        """See Transport.clone()."""
        if offset is None:
            newurl = self.base
        else:
            newurl = urlutils.join(self.base, offset)

        return GitSmartTransport(newurl, self._client)


class RemoteGitDir(GitDir):

    def __init__(self, transport, lockfiles, format):
        self._format = format
        self.root_transport = transport
        self.transport = transport
        self._lockfiles = lockfiles

    def open_repository(self):
        return RemoteGitRepository(self, self._lockfiles)

    def open_branch(self):
        repo = self.open_repository()
        # TODO: Support for multiple branches in one bzrdir in bzrlib!
        return RemoteGitBranch(self, repo, "HEAD", self._lockfiles)

    def open_workingtree(self):
        raise NotLocalUrl(self.transport.base)


class RemoteGitRepository(GitRepository):

    def __init__(self, gitdir, lockfiles):
        GitRepository.__init__(self, gitdir, lockfiles)

    def fetch_pack(self, determine_wants, graph_walker, pack_data, 
                   progress=None):
        self._transport.fetch_pack(determine_wants, graph_walker, pack_data, 
            progress)


class RemoteGitBranch(GitBranch):

    def __init__(self, bzrdir, repository, name, lockfiles):
        def determine_wants(heads):
            self._ref = heads[name]
        bzrdir.root_transport.fetch_pack(determine_wants, None, lambda x: None, 
                             lambda x: mutter("git: %s" % x))
        super(RemoteGitBranch, self).__init__(bzrdir, repository, name, self._ref, lockfiles)

    def last_revision(self):
        return self.mapping.revision_id_foreign_to_bzr(self._ref)

