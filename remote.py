# Copyright (C) 2007-2009 Jelmer Vernooij <jelmer@samba.org>
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
from bzrlib import (
    branch,
    tag,
    urlutils,
    )
from bzrlib.bzrdir import (
    BzrDir,
    BzrDirFormat,
    )
from bzrlib.errors import (
    BzrError,
    NoSuchFile,
    NotLocalUrl,
    )
from bzrlib.foreign import (
    ForeignBranch,
    )
from bzrlib.lockable_files import (
    TransportLock,
    )
from bzrlib.repository import (
    Repository,
    )
from bzrlib.trace import (
    info,
    )
from bzrlib.transport import (
    Transport,
    )

from bzrlib.plugins.git import (
    lazy_check_versions,
    )
lazy_check_versions()

from bzrlib.plugins.git.branch import (
    GitBranch,
    )
from bzrlib.plugins.git.errors import (
    GitSmartRemoteNotSupported,
    NoSuchRef,
    )
from bzrlib.plugins.git.dir import (
    GitDir,
    )
from bzrlib.plugins.git.repository import (
    GitRepositoryFormat,
    GitRepository,
    )

import dulwich as git
from dulwich.errors import (
    GitProtocolError,
    )
from dulwich.pack import (
    Pack,
    PackData,
    )
import os
import tempfile
import urllib
import urlparse

try:
    from dulwich.pack import load_pack_index
except ImportError:
    from dulwich.pack import PackIndex as load_pack_index


# Don't run any tests on GitSmartTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []


class GitSmartTransport(Transport):

    def __init__(self, url, _client=None):
        Transport.__init__(self, url)
        (scheme, _, loc, _, _) = urlparse.urlsplit(url)
        hostport, self._path = urllib.splithost(loc)
        (self._host, self._port) = urllib.splitnport(hostport, git.protocol.TCP_GIT_PORT)
        self._client = _client

    def has(self, relpath):
        return False

    def _get_client(self):
        raise NotImplementedError(self._get_client)

    def fetch_pack(self, determine_wants, graph_walker, pack_data, progress=None):
        if progress is None:
            def progress(text):
                info("git: %s" % text)
        client = self._get_client()
        try:
            client.fetch_pack(self._path, determine_wants, 
                graph_walker, pack_data, progress)
        except GitProtocolError, e:
            raise BzrError(e)

    def get(self, path):
        raise NoSuchFile(path)

    def abspath(self, relpath):
        return urlutils.join(self.base, relpath)

    def clone(self, offset=None):
        """See Transport.clone()."""
        if offset is None:
            newurl = self.base
        else:
            newurl = urlutils.join(self.base, offset)

        return self.__class__(newurl, self._client)


class TCPGitSmartTransport(GitSmartTransport):

    def _get_client(self):
        if self._client is not None:
            ret = self._client
            self._client = None
            return ret
        return git.client.TCPGitClient(self._host, self._port, thin_packs=False)


class SSHGitSmartTransport(GitSmartTransport):

    def _get_client(self):
        if self._client is not None:
            ret = self._client
            self._client = None
            return ret
        return git.client.SSHGitClient(self._host, self._port, thin_packs=False)


class RemoteGitDir(GitDir):

    def __init__(self, transport, lockfiles, format):
        self._format = format
        self.root_transport = transport
        self.transport = transport
        self._lockfiles = lockfiles

    def open_repository(self):
        return RemoteGitRepository(self, self._lockfiles)

    def open_branch(self, ignore_fallbacks=False):
        repo = self.open_repository()
        # TODO: Support for multiple branches in one bzrdir in bzrlib!
        return RemoteGitBranch(self, repo, "HEAD", self._lockfiles)

    def open_workingtree(self):
        raise NotLocalUrl(self.transport.base)


class EmptyObjectStoreIterator(dict):

    def iterobjects(self):
        return []


class TemporaryPackIterator(Pack):

    def __init__(self, path, resolve_ext_ref):
        super(TemporaryPackIterator, self).__init__(path)
        self.resolve_ext_ref = resolve_ext_ref

    @property
    def idx(self):
        if self._idx is None:
            if self._data is None:
                self._data = PackData(self._data_path)
            self._data.create_index_v2(self._idx_path, self.resolve_ext_ref)
            self._idx = load_pack_index(self._idx_path)
        return self._idx

    def __del__(self):
        os.remove(self._data_path)
        os.remove(self._idx_path)


class RemoteGitRepository(GitRepository):

    def __init__(self, gitdir, lockfiles):
        GitRepository.__init__(self, gitdir, lockfiles)
        self._refs = None

    @property
    def inventories(self):
        raise GitSmartRemoteNotSupported()

    @property
    def revisions(self):
        raise GitSmartRemoteNotSupported()

    @property
    def texts(self):
        raise GitSmartRemoteNotSupported()

    def get_refs(self):
        if self._refs is not None:
            return self._refs
        def determine_wants(heads):
            self._refs = heads
            return []
        self.bzrdir.root_transport.fetch_pack(determine_wants, None, 
            lambda x: None, lambda x: mutter("git: %s" % x))
        return self._refs

    def fetch_pack(self, determine_wants, graph_walker, pack_data, 
                   progress=None):
        self._transport.fetch_pack(determine_wants, graph_walker, pack_data, 
            progress)

    def fetch_objects(self, determine_wants, graph_walker, resolve_ext_ref, progress=None):
        fd, path = tempfile.mkstemp(suffix=".pack")
        self.fetch_pack(determine_wants, graph_walker, lambda x: os.write(fd, x), progress)
        os.close(fd)
        if os.path.getsize(path) == 0:
            return EmptyObjectStoreIterator()
        return TemporaryPackIterator(path[:-len(".pack")], resolve_ext_ref)


class RemoteGitTagDict(tag.BasicTags):

    def __init__(self, branch):
        self.branch = branch
        self.repository = branch.repository

    def get_tag_dict(self):
        ret = {}
        refs = self.repository.get_refs()
        for k,v in refs.iteritems():
            if k.startswith("refs/tags/") and not k.endswith("^{}"):
                v = refs.get(k+"^{}", v)
                ret[k[len("refs/tags/"):]] = self.branch.mapping.revision_id_foreign_to_bzr(v)
        return ret

    def set_tag(self, name, revid):
        # FIXME: Not supported yet, should do a push of a new ref
        raise NotImplementedError(self.set_tag)


class RemoteGitBranch(GitBranch):

    def __init__(self, bzrdir, repository, name, lockfiles):
        heads = repository.get_refs()
        if not name in heads:
            raise NoSuchRef(name)
        self._ref = heads[name]
        super(RemoteGitBranch, self).__init__(bzrdir, repository, name, self._ref, lockfiles)

    def last_revision(self):
        return self.mapping.revision_id_foreign_to_bzr(self._ref)

    def _synchronize_history(self, destination, revision_id):
        """See Branch._synchronize_history()."""
        destination.generate_revision_history(self.last_revision())
 
