# Copyright (C) 2007-2012 Jelmer Vernooij <jelmer@samba.org>
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

from __future__ import absolute_import

from bzrlib import (
    config,
    debug,
    trace,
    ui,
    urlutils,
    )
from bzrlib.errors import (
    BzrError,
    InProcessTransport,
    InvalidRevisionId,
    NoSuchFile,
    NoSuchRevision,
    NotBranchError,
    NotLocalUrl,
    UninitializableFormat,
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
from bzrlib.plugins.git.dir import (
    GitControlDirFormat,
    GitDir,
    )
from bzrlib.plugins.git.errors import (
    GitSmartRemoteNotSupported,
    NoSuchRef,
    )
from bzrlib.plugins.git.mapping import (
    mapping_registry,
    )
from bzrlib.plugins.git.repository import (
    GitRepository,
    )
from bzrlib.plugins.git.refs import (
    branch_name_to_ref,
    is_peeled,
    )

import dulwich
import dulwich.client
from dulwich.errors import (
    GitProtocolError,
    )
from dulwich.pack import (
    Pack,
    PackData,
    )
from dulwich.repo import DictRefsContainer
import os
import tempfile
import urllib
import urlparse

# urlparse only supports a limited number of schemes by default

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


class RemoteGitError(BzrError):

    _fmt = "Remote server error: %(message)s"


def parse_git_error(url, message):
    """Parse a remote git server error and return a bzr exception.

    :param url: URL of the remote repository
    :param message: Message sent by the remote git server
    """
    message = str(message).strip()
    if message.startswith("Could not find Repository "):
        return NotBranchError(url, message)
    if message == "HEAD failed to update":
        base_url, _ = urlutils.split_segment_parameters(url)
        raise BzrError(
            ("Unable to update remote HEAD branch. To update the master "
             "branch, specify the URL %s,branch=master.") % base_url)
    # Don't know, just return it to the user as-is
    return RemoteGitError(message)


class GitSmartTransport(Transport):

    def __init__(self, url, _client=None):
        Transport.__init__(self, url)
        (self._host, self._port, self._username, self._path) = \
            split_git_url(url)
        if 'transport' in debug.debug_flags:
            trace.mutter('host: %r, user: %r, port: %r, path: %r',
                         self._host, self._username, self._port, self._path)
        self._client = _client
        self._stripped_path = self._path.rsplit(",", 1)[0]

    def external_url(self):
        return self.base

    def has(self, relpath):
        return False

    def _get_client(self, thin_packs):
        raise NotImplementedError(self._get_client)

    def _get_path(self):
        return self._stripped_path

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
        return dulwich.client.TCPGitClient(self._host, self._port,
            thin_packs=thin_packs, report_activity=self._report_activity)


class SSHGitSmartTransport(GitSmartTransport):

    _scheme = 'git+ssh'

    def _get_path(self):
        path = self._stripped_path
        if path.startswith("/~/"):
            return path[3:]
        return path

    def _get_client(self, thin_packs):
        if self._client is not None:
            ret = self._client
            self._client = None
            return ret
        location_config = config.LocationConfig(self.base)
        client = dulwich.client.SSHGitClient(self._host, self._port, self._username,
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

    def __init__(self, transport, format, get_client, client_path):
        self._format = format
        self.root_transport = transport
        self.transport = transport
        self._mode_check_done = None
        self._get_client = get_client
        self._client_path = client_path
        self.base = self.root_transport.base
        self._refs = None

    def fetch_pack(self, determine_wants, graph_walker, pack_data, progress=None):
        if progress is None:
            def progress(text):
                trace.info("git: %s" % text)
        def wrap_determine_wants(refs_dict):
            return determine_wants(remote_refs_dict_to_container(refs_dict))
        client = self._get_client(thin_packs=False)
        try:
            refs_dict = client.fetch_pack(self._client_path, wrap_determine_wants,
                graph_walker, pack_data, progress)
            self._refs = remote_refs_dict_to_container(refs_dict)
            return refs_dict
        except GitProtocolError, e:
            raise parse_git_error(self.transport.external_url(), e)

    def send_pack(self, get_changed_refs, generate_pack_contents):
        client = self._get_client(thin_packs=False)
        try:
            return client.send_pack(self._client_path, get_changed_refs,
                generate_pack_contents)
        except GitProtocolError, e:
            raise parse_git_error(self.transport.external_url(), e)

    def _get_default_ref(self):
        return "refs/heads/master"

    def destroy_branch(self, name=None):
        refname = self._get_selected_ref(name)
        def get_changed_refs(old_refs):
            ret = dict(old_refs)
            if not refname in ret:
                raise NotBranchError(self.user_url)
            ret[refname] = "00" * 20
            return ret
        self.send_pack(get_changed_refs, lambda have, want: [])

    @property
    def user_url(self):
        return self.control_url

    @property
    def user_transport(self):
        return self.root_transport

    @property
    def control_url(self):
        return self.control_transport.base

    @property
    def control_transport(self):
        return self.root_transport

    def open_repository(self):
        return RemoteGitRepository(self)

    def open_branch(self, name=None, unsupported=False,
            ignore_fallbacks=False, ref=None, possible_transports=None):
        repo = self.open_repository()
        refname = self._get_selected_ref(name, ref)
        return RemoteGitBranch(self, repo, refname)

    def open_workingtree(self, recommend_upgrade=False):
        raise NotLocalUrl(self.transport.base)

    def get_peeled(self, name):
        return self.get_refs_container().get_peeled(name)

    def get_refs_container(self):
        if self._refs is not None:
            return self._refs
        refs_dict = self.fetch_pack(lambda x: [], None,
            lambda x: None, lambda x: trace.mutter("git: %s" % x))
        self._refs = remote_refs_dict_to_container(refs_dict)
        return self._refs


class EmptyObjectStoreIterator(dict):

    def iterobjects(self):
        return []


class TemporaryPackIterator(Pack):

    def __init__(self, path, resolve_ext_ref):
        super(TemporaryPackIterator, self).__init__(path)
        self.resolve_ext_ref = resolve_ext_ref
        self._idx_load = lambda: self._idx_load_or_generate(self._idx_path)

    def _idx_load_or_generate(self, path):
        if not os.path.exists(path):
            pb = ui.ui_factory.nested_progress_bar()
            try:
                def report_progress(cur, total):
                    pb.update("generating index", cur, total)
                self.data.create_index(path,
                    progress=report_progress)
            finally:
                pb.finished()
        return load_pack_index(path)

    def __del__(self):
        if self._idx is not None:
            self._idx.close()
            os.remove(self._idx_path)
        if self._data is not None:
            self._data.close()
            os.remove(self._data_path)


class BzrGitHttpClient(dulwich.client.HttpGitClient):

    def __init__(self, transport, *args, **kwargs):
        self.transport = transport
        super(BzrGitHttpClient, self).__init__(transport.external_url(), *args, **kwargs)
        import urllib2
        self._http_perform = getattr(self.transport, "_perform", urllib2.urlopen)

    def _perform(self, req):
        req.accepted_errors = (200, 404)
        req.follow_redirections = True
        req.redirected_to = None
        return self._http_perform(req)


class RemoteGitControlDirFormat(GitControlDirFormat):
    """The .git directory control format."""

    supports_workingtrees = False

    @classmethod
    def _known_formats(self):
        return set([RemoteGitControlDirFormat()])

    def is_initializable(self):
        return False

    def is_supported(self):
        return True

    def open(self, transport, _found=None):
        """Open this directory.

        """
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]
        if isinstance(transport, GitSmartTransport):
            get_client = transport._get_client
            client_path = transport._get_path()
        elif urlparse.urlsplit(transport.external_url())[0] in ("http", "https"):
            def get_client(thin_packs=False):
                return BzrGitHttpClient(transport, thin_packs=thin_packs)
            client_path, _ = urlutils.split_segment_parameters(transport._path)
        else:
            raise NotBranchError(transport.base)
        return RemoteGitDir(transport, self, get_client, client_path)

    def get_format_description(self):
        return "Remote Git Repository"

    def initialize_on_transport(self, transport):
        raise UninitializableFormat(self)

    def supports_transport(self, transport):
        try:
            external_url = transport.external_url()
        except InProcessTransport:
            raise NotBranchError(path=transport.base)
        return (external_url.startswith("http:") or
                external_url.startswith("https:") or
                external_url.startswith("git+") or
                external_url.startswith("git:"))


class RemoteGitRepository(GitRepository):

    @property
    def user_url(self):
        return self.control_url

    def get_parent_map(self, revids):
        raise GitSmartRemoteNotSupported(self.get_parent_map, self)

    def fetch_pack(self, determine_wants, graph_walker, pack_data,
                   progress=None):
        return self.bzrdir.fetch_pack(determine_wants, graph_walker,
                                          pack_data, progress)

    def send_pack(self, get_changed_refs, generate_pack_contents):
        return self.bzrdir.send_pack(get_changed_refs, generate_pack_contents)

    def fetch_objects(self, determine_wants, graph_walker, resolve_ext_ref,
                      progress=None):
        fd, path = tempfile.mkstemp(suffix=".pack")
        try:
            self.fetch_pack(determine_wants, graph_walker,
                lambda x: os.write(fd, x), progress)
        finally:
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

    def revision_tree(self, revid):
        raise GitSmartRemoteNotSupported(self.revision_tree, self)

    def get_revisions(self, revids):
        raise GitSmartRemoteNotSupported(self.get_revisions, self)

    def has_revisions(self, revids):
        raise GitSmartRemoteNotSupported(self.get_revisions, self)


class RemoteGitTagDict(GitTags):

    def get_refs_container(self):
        return self.repository.bzrdir.get_refs_container()

    def set_tag(self, name, revid):
        # FIXME: Not supported yet, should do a push of a new ref
        raise NotImplementedError(self.set_tag)


class RemoteGitBranch(GitBranch):

    def __init__(self, bzrdir, repository, name):
        self._sha = None
        super(RemoteGitBranch, self).__init__(bzrdir, repository, name)

    def last_revision_info(self):
        raise GitSmartRemoteNotSupported(self.last_revision_info, self)

    @property
    def user_url(self):
        return self.control_url

    @property
    def control_url(self):
        return self.base

    def revision_id_to_revno(self, revision_id):
        raise GitSmartRemoteNotSupported(self.revision_id_to_revno, self)

    def last_revision(self):
        return self.lookup_foreign_revision_id(self.head)

    @property
    def head(self):
        if self._sha is not None:
            return self._sha
        refs = self.bzrdir.get_refs_container()
        name = branch_name_to_ref(self.name)
        try:
            self._sha = refs[name]
        except KeyError:
            raise NoSuchRef(name, self.repository.user_url, refs)
        return self._sha

    def _synchronize_history(self, destination, revision_id):
        """See Branch._synchronize_history()."""
        destination.generate_revision_history(self.last_revision())

    def get_push_location(self):
        return None

    def set_push_location(self, url):
        pass


def remote_refs_dict_to_container(refs_dict):
    base = {}
    peeled = {}
    for k, v in refs_dict.iteritems():
        if is_peeled(k):
            peeled[k[:-3]] = v
        else:
            base[k] = v
            peeled[k] = v
    ret = DictRefsContainer(base)
    ret._peeled = peeled
    return ret
