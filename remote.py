# Copyright (C) 2007-2010 Jelmer Vernooij <jelmer@samba.org>
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

from bzrlib import (
    config,
    debug,
    trace,
    ui,
    urlutils,
    )
from bzrlib.errors import (
    BzrError,
    InvalidRevisionId,
    NoSuchFile,
    NoSuchRevision,
    NotLocalUrl,
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
    GitTags,
    )
from bzrlib.plugins.git.errors import (
    GitSmartRemoteNotSupported,
    NoSuchRef,
    )
from bzrlib.plugins.git.dir import (
    GitDir,
    )
from bzrlib.plugins.git.mapping import (
    mapping_registry,
    )
from bzrlib.plugins.git.repository import (
    GitRepository,
    )
from bzrlib.plugins.git.refs import (
    extract_tags,
    branch_name_to_ref,
    )

import dulwich as git
from dulwich.errors import (
    GitProtocolError,
    )
from dulwich.pack import (
    Pack,
    ThinPackData,
    )
import os
import tempfile
import urllib
import urlparse
urlparse.uses_netloc.extend(['git', 'git+ssh'])

from dulwich.pack import load_pack_index


# Don't run any tests on GitSmartTransport as it is not intended to be
# a full implementation of Transport
def get_test_permutations():
    return []


def split_git_url(url):
    """Split a Git URL.

    :param url: Git URL
    :return: Tuple with host, port, username, path.
    """
    (scheme, netloc, loc, _, _) = urlparse.urlsplit(url)
    path = urllib.unquote(loc)
    if path.startswith("/~"):
        path = path[1:]
    (username, hostport) = urllib.splituser(netloc)
    (host, port) = urllib.splitnport(hostport, None)
    return (host, port, username, path)


class GitSmartTransport(Transport):

    def __init__(self, url, _client=None):
        Transport.__init__(self, url)
        (self._host, self._port, self._username, self._path) = \
            split_git_url(url)
        if 'transport' in debug.debug_flags:
            trace.mutter('host: %r, user: %r, port: %r, path: %r',
                         self._host, self._username, self._port, self._path)
        self._client = _client

    def external_url(self):
        return self.base

    def has(self, relpath):
        return False

    def _get_client(self, thin_packs):
        raise NotImplementedError(self._get_client)

    def _get_path(self):
        return self._path

    def fetch_pack(self, determine_wants, graph_walker, pack_data, progress=None):
        if progress is None:
            def progress(text):
                trace.info("git: %s" % text)
        client = self._get_client(thin_packs=False)
        try:
            return client.fetch_pack(self._get_path(), determine_wants,
                graph_walker, pack_data, progress)
        except GitProtocolError, e:
            raise BzrError(e)

    def send_pack(self, get_changed_refs, generate_pack_contents):
        client = self._get_client(thin_packs=False)
        try:
            return client.send_pack(self._get_path(), get_changed_refs,
                generate_pack_contents)
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

    _scheme = 'git'

    def _get_client(self, thin_packs):
        if self._client is not None:
            ret = self._client
            self._client = None
            return ret
        return git.client.TCPGitClient(self._host, self._port,
            thin_packs=thin_packs, report_activity=self._report_activity)


class SSHGitSmartTransport(GitSmartTransport):

    _scheme = 'git+ssh'

    def _get_path(self):
        if self._path.startswith("/~/"):
            return self._path[3:]
        return self._path

    def _get_client(self, thin_packs):
        if self._client is not None:
            ret = self._client
            self._client = None
            return ret
        location_config = config.LocationConfig(self.base)
        client = git.client.SSHGitClient(self._host, self._port, self._username,
            thin_packs=thin_packs, report_activity=self._report_activity)
        # Set up alternate pack program paths
        upload_pack = location_config.get_user_option('git_upload_pack')
        if upload_pack:
            client.alternative_paths["upload-pack"] = upload_pack
        receive_pack = location_config.get_user_option('git_receive_pack')
        if receive_pack:
            client.alternative_paths["receive-pack"] = receive_pack
        return client


class RemoteGitDir(GitDir):

    def __init__(self, transport, lockfiles, format):
        self._format = format
        self.root_transport = transport
        self.transport = transport
        self._lockfiles = lockfiles
        self._mode_check_done = None

    def _branch_name_to_ref(self, name, default=None):
        return branch_name_to_ref(name, default=default)

    def open_repository(self):
        return RemoteGitRepository(self, self._lockfiles)

    def _open_branch(self, name=None, ignore_fallbacks=False, 
                    unsupported=False):
        repo = self.open_repository()
        refname = self._branch_name_to_ref(name)
        return RemoteGitBranch(self, repo, refname, self._lockfiles)

    def open_workingtree(self, recommend_upgrade=False):
        raise NotLocalUrl(self.transport.base)


class EmptyObjectStoreIterator(dict):

    def iterobjects(self):
        return []


class TemporaryPackIterator(Pack):

    def __init__(self, path, resolve_ext_ref):
        super(TemporaryPackIterator, self).__init__(path)
        self.resolve_ext_ref = resolve_ext_ref

    @property
    def data(self):
        if self._data is None:
            self._data = ThinPackData(self.resolve_ext_ref, self._data_path)
        return self._data

    @property
    def index(self):
        if self._idx is None:
            if not os.path.exists(self._idx_path):
                pb = ui.ui_factory.nested_progress_bar()
                try:
                    def report_progress(cur, total):
                        pb.update("generating index", cur, total)
                    self.data.create_index(self._idx_path, 
                        progress=report_progress)
                finally:
                    pb.finished()
            self._idx = load_pack_index(self._idx_path)
        return self._idx

    def __del__(self):
        if self._idx is not None:
            self._idx.close()
            os.remove(self._idx_path)
        if self._data is not None:
            self._data.close()
            os.remove(self._data_path)


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
        self._refs = self.bzrdir.root_transport.fetch_pack(lambda x: [], None,
            lambda x: None, lambda x: trace.mutter("git: %s" % x))
        return self._refs

    def fetch_pack(self, determine_wants, graph_walker, pack_data,
                   progress=None):
        return self._transport.fetch_pack(determine_wants, graph_walker,
                                          pack_data, progress)

    def send_pack(self, get_changed_refs, generate_pack_contents):
        return self._transport.send_pack(get_changed_refs, generate_pack_contents)

    def fetch_objects(self, determine_wants, graph_walker, resolve_ext_ref,
                      progress=None):
        fd, path = tempfile.mkstemp(suffix=".pack")
        self.fetch_pack(determine_wants, graph_walker,
            lambda x: os.write(fd, x), progress)
        os.close(fd)
        if os.path.getsize(path) == 0:
            return EmptyObjectStoreIterator()
        return TemporaryPackIterator(path[:-len(".pack")], resolve_ext_ref)

    def lookup_bzr_revision_id(self, bzr_revid):
        # This won't work for any round-tripped bzr revisions, but it's a start..
        try:
            return mapping_registry.revision_id_bzr_to_foreign(bzr_revid)
        except InvalidRevisionId:
            raise NoSuchRevision(self, bzr_revid)

    def lookup_foreign_revision_id(self, foreign_revid, mapping=None):
        """Lookup a revision id.

        """
        if mapping is None:
            mapping = self.get_mapping()
        # Not really an easy way to parse foreign revids here..
        return mapping.revision_id_foreign_to_bzr(foreign_revid)


class RemoteGitTagDict(GitTags):

    def get_tag_dict(self):
        tags = {}
        refs = self.repository.get_refs()
        for k, (peeled, unpeeled) in extract_tags(refs).iteritems():
            tags[k] = self.branch.mapping.revision_id_foreign_to_bzr(peeled)
        return tags

    def set_tag(self, name, revid):
        # FIXME: Not supported yet, should do a push of a new ref
        raise NotImplementedError(self.set_tag)


class RemoteGitBranch(GitBranch):

    def __init__(self, bzrdir, repository, name, lockfiles):
        self._sha = None
        super(RemoteGitBranch, self).__init__(bzrdir, repository, name,
                lockfiles)

    def revision_history(self):
        raise GitSmartRemoteNotSupported()

    def last_revision(self):
        return self.lookup_foreign_revision_id(self.head)

    def _get_config(self):
        class EmptyConfig(object):

            def _get_configobj(self):
                return config.ConfigObj()

        return EmptyConfig()

    @property
    def head(self):
        if self._sha is not None:
            return self._sha
        heads = self.repository.get_refs()
        name = self.bzrdir._branch_name_to_ref(self.name, "HEAD")
        if name in heads:
            self._sha = heads[name]
        else:
            raise NoSuchRef(self.name)
        return self._sha

    def _synchronize_history(self, destination, revision_id):
        """See Branch._synchronize_history()."""
        destination.generate_revision_history(self.last_revision())

    def get_push_location(self):
        return None

    def set_push_location(self, url):
        pass
