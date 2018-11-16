# Copyright (C) 2007-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Remote dirs, repositories and branches."""

from __future__ import absolute_import

import gzip
import re

from .. import (
    config,
    debug,
    errors,
    osutils,
    trace,
    ui,
    urlutils,
    )
from ..push import (
    PushResult,
    )
from ..errors import (
    AlreadyBranchError,
    BzrError,
    DivergedBranches,
    InProcessTransport,
    InvalidRevisionId,
    NoSuchFile,
    NoSuchRevision,
    NoSuchTag,
    NotBranchError,
    NotLocalUrl,
    PermissionDenied,
    UninitializableFormat,
    )
from ..revisiontree import RevisionTree
from ..sixish import text_type
from ..transport import (
    Transport,
    register_urlparse_netloc_protocol,
    )

from . import (
    lazy_check_versions,
    user_agent_for_github,
    )
lazy_check_versions()

from .branch import (
    GitBranch,
    GitBranchFormat,
    GitBranchPushResult,
    GitTags,
    _quick_lookup_revno,
    )
from .dir import (
    GitControlDirFormat,
    GitDir,
    )
from .errors import (
    GitSmartRemoteNotSupported,
    NoSuchRef,
    )
from .mapping import (
    mapping_registry,
    )
from .object_store import (
    get_object_store,
    )
from .push import (
    remote_divergence,
    )
from .repository import (
    GitRepository,
    )
from .refs import (
    branch_name_to_ref,
    is_peeled,
    ref_to_tag_name,
    tag_name_to_ref,
    )

import dulwich
import dulwich.client
from dulwich.errors import (
    GitProtocolError,
    HangupException,
    )
from dulwich.pack import (
    Pack,
    pack_objects_to_data,
    )
from dulwich.protocol import ZERO_SHA
from dulwich.refs import (
    DictRefsContainer,
    SYMREF,
    )
from dulwich.repo import (
    NotGitRepository,
    )
import os
import select
import tempfile

try:
    import urllib.parse as urlparse
    from urllib.parse import splituser, splitnport
except ImportError:
    import urlparse
    from urllib import splituser, splitnport

# urlparse only supports a limited number of schemes by default
register_urlparse_netloc_protocol('git')
register_urlparse_netloc_protocol('git+ssh')

from dulwich.pack import load_pack_index


class GitPushResult(PushResult):

    def _lookup_revno(self, revid):
        try:
            return _quick_lookup_revno(self.source_branch, self.target_branch,
                                       revid)
        except GitSmartRemoteNotSupported:
            return None

    @property
    def old_revno(self):
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        return self._lookup_revno(self.new_revid)


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
    path = urlparse.unquote(loc)
    if path.startswith("/~"):
        path = path[1:]
    (username, hostport) = splituser(netloc)
    (host, port) = splitnport(hostport, None)
    return (host, port, username, path)


class RemoteGitError(BzrError):

    _fmt = "Remote server error: %(msg)s"


class HeadUpdateFailed(BzrError):

    _fmt = ("Unable to update remote HEAD branch. To update the master "
            "branch, specify the URL %(base_url)s,branch=master.")

    def __init__(self, base_url):
        super(HeadUpdateFailed, self).__init__()
        self.base_url = base_url


def parse_git_error(url, message):
    """Parse a remote git server error and return a bzr exception.

    :param url: URL of the remote repository
    :param message: Message sent by the remote git server
    """
    message = str(message).strip()
    if (message.startswith("Could not find Repository ")
        or message == 'Repository not found.'
            or (message.startswith('Repository ') and
                message.endswith(' not found.'))):
        return NotBranchError(url, message)
    if message == "HEAD failed to update":
        base_url, _ = urlutils.split_segment_parameters(url)
        return HeadUpdateFailed(base_url)
    if message.startswith('access denied or repository not exported:'):
        extra, path = message.split(': ', 1)
        return PermissionDenied(path, extra)
    if message.endswith('You are not allowed to push code to this project.'):
        return PermissionDenied(url, message)
    if message.endswith(' does not appear to be a git repository'):
        return NotBranchError(url, message)
    m = re.match(r'Permission to ([^ ]+) denied to ([^ ]+)\.', message)
    if m:
        return PermissionDenied(m.group(1), 'denied to %s' % m.group(2))
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

    def _get_client(self):
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

    def _get_client(self):
        if self._client is not None:
            ret = self._client
            self._client = None
            return ret
        if self._host == '':
            # return dulwich.client.LocalGitClient()
            return dulwich.client.SubprocessGitClient()
        return dulwich.client.TCPGitClient(
            self._host, self._port, report_activity=self._report_activity)


class SSHSocketWrapper(object):

    def __init__(self, sock):
        self.sock = sock

    def read(self, len=None):
        return self.sock.recv(len)

    def write(self, data):
        return self.sock.write(data)

    def can_read(self):
        return len(select.select([self.sock.fileno()], [], [], 0)[0]) > 0


class DulwichSSHVendor(dulwich.client.SSHVendor):

    def __init__(self):
        from ..transport import ssh
        self.bzr_ssh_vendor = ssh._get_ssh_vendor()

    def run_command(self, host, command, username=None, port=None):
        connection = self.bzr_ssh_vendor.connect_ssh(
            username=username, password=None, port=port, host=host,
            command=command)
        (kind, io_object) = connection.get_sock_or_pipes()
        if kind == 'socket':
            return SSHSocketWrapper(io_object)
        else:
            raise AssertionError("Unknown io object kind %r'" % kind)


# dulwich.client.get_ssh_vendor = DulwichSSHVendor


class SSHGitSmartTransport(GitSmartTransport):

    _scheme = 'git+ssh'

    def _get_path(self):
        path = self._stripped_path
        if path.startswith("/~/"):
            return path[3:]
        return path

    def _get_client(self):
        if self._client is not None:
            ret = self._client
            self._client = None
            return ret
        location_config = config.LocationConfig(self.base)
        client = dulwich.client.SSHGitClient(
            self._host, self._port, self._username,
            report_activity=self._report_activity)
        # Set up alternate pack program paths
        upload_pack = location_config.get_user_option('git_upload_pack')
        if upload_pack:
            client.alternative_paths["upload-pack"] = upload_pack
        receive_pack = location_config.get_user_option('git_receive_pack')
        if receive_pack:
            client.alternative_paths["receive-pack"] = receive_pack
        return client


class RemoteGitBranchFormat(GitBranchFormat):

    def get_format_description(self):
        return 'Remote Git Branch'

    @property
    def _matchingcontroldir(self):
        return RemoteGitControlDirFormat()

    def initialize(self, a_controldir, name=None, repository=None,
                   append_revisions_only=None):
        raise UninitializableFormat(self)


class DefaultProgressReporter(object):

    _GIT_PROGRESS_PARTIAL_RE = re.compile(r"(.*?): +(\d+)% \((\d+)/(\d+)\)")
    _GIT_PROGRESS_TOTAL_RE = re.compile(r"(.*?): (\d+)")

    def __init__(self, pb):
        self.pb = pb

    def progress(self, text):
        text = text.rstrip(b"\r\n")
        text = text.decode('utf-8')
        if text.lower().startswith('error: '):
            trace.show_error('git: %s', text[len(b'error: '):])
        else:
            trace.mutter("git: %s", text)
            g = self._GIT_PROGRESS_PARTIAL_RE.match(text)
            if g is not None:
                (text, pct, current, total) = g.groups()
                self.pb.update(text, int(current), int(total))
            else:
                g = self._GIT_PROGRESS_TOTAL_RE.match(text)
                if g is not None:
                    (text, total) = g.groups()
                    self.pb.update(text, None, int(total))
                else:
                    trace.note("%s", text)


class RemoteGitDir(GitDir):

    def __init__(self, transport, format, client, client_path):
        self._format = format
        self.root_transport = transport
        self.transport = transport
        self._mode_check_done = None
        self._client = client
        self._client_path = client_path
        self.base = self.root_transport.base
        self._refs = None

    @property
    def _gitrepository_class(self):
        return RemoteGitRepository

    def archive(self, format, committish, write_data, progress=None,
                write_error=None, subdirs=None, prefix=None):
        if progress is None:
            pb = ui.ui_factory.nested_progress_bar()
            progress = DefaultProgressReporter(pb).progress
        else:
            pb = None
        def progress_wrapper(message):
            if message.startswith(b"fatal: Unknown archive format \'"):
                format = message.strip()[len(b"fatal: Unknown archive format '"):-1]
                raise errors.NoSuchExportFormat(format.decode('ascii'))
            return progress(message)
        try:
            self._client.archive(
                self._client_path, committish, write_data, progress_wrapper,
                write_error,
                format=(format.encode('ascii') if format else None),
                subdirs=subdirs,
                prefix=(prefix.encode('utf-8') if prefix else None))
        except GitProtocolError as e:
            raise parse_git_error(self.transport.external_url(), e)
        finally:
            if pb is not None:
                pb.finished()

    def fetch_pack(self, determine_wants, graph_walker, pack_data,
                   progress=None):
        if progress is None:
            pb = ui.ui_factory.nested_progress_bar()
            progress = DefaultProgressReporter(pb).progress
        else:
            pb = None
        try:
            result = self._client.fetch_pack(
                self._client_path, determine_wants, graph_walker, pack_data,
                progress)
            if result.refs is None:
                result.refs = {}
            self._refs = remote_refs_dict_to_container(
                result.refs, result.symrefs)
            return result
        except GitProtocolError as e:
            raise parse_git_error(self.transport.external_url(), e)
        finally:
            if pb is not None:
                pb.finished()

    def send_pack(self, get_changed_refs, generate_pack_data, progress=None):
        if progress is None:
            pb = ui.ui_factory.nested_progress_bar()
            progress = DefaultProgressReporter(pb).progress
        else:
            pb = None

        def get_changed_refs_wrapper(refs):
            # TODO(jelmer): This drops symref information
            self._refs = remote_refs_dict_to_container(refs)
            return get_changed_refs(refs)
        try:
            return self._client.send_pack(
                self._client_path, get_changed_refs_wrapper,
                generate_pack_data, progress)
        except GitProtocolError as e:
            raise parse_git_error(self.transport.external_url(), e)
        finally:
            if pb is not None:
                pb.finished()

    def create_branch(self, name=None, repository=None,
                      append_revisions_only=None, ref=None):
        refname = self._get_selected_ref(name, ref)
        if refname != b'HEAD' and refname in self.get_refs_container():
            raise AlreadyBranchError(self.user_url)
        if refname in self.get_refs_container():
            ref_chain, unused_sha = self.get_refs_container().follow(
                self._get_selected_ref(None))
            if ref_chain[0] == b'HEAD':
                refname = ref_chain[1]
        repo = self.open_repository()
        return RemoteGitBranch(self, repo, refname)

    def destroy_branch(self, name=None):
        refname = self._get_selected_ref(name)

        def get_changed_refs(old_refs):
            ret = dict(old_refs)
            if refname not in ret:
                raise NotBranchError(self.user_url)
            ret[refname] = dulwich.client.ZERO_SHA
            return ret

        def generate_pack_data(have, want, ofs_delta=False):
            return pack_objects_to_data([])
        self.send_pack(get_changed_refs, generate_pack_data)

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

    def get_branch_reference(self, name=None):
        ref = branch_name_to_ref(name)
        val = self.get_refs_container().read_ref(ref)
        if val.startswith(SYMREF):
            return val[len(SYMREF):]
        return None

    def open_branch(self, name=None, unsupported=False,
                    ignore_fallbacks=False, ref=None, possible_transports=None,
                    nascent_ok=False):
        repo = self.open_repository()
        ref = self._get_selected_ref(name, ref)
        try:
            if not nascent_ok and ref not in self.get_refs_container():
                raise NotBranchError(
                    self.root_transport.base, controldir=self)
        except NotGitRepository:
            raise NotBranchError(self.root_transport.base,
                                 controldir=self)
        ref_chain, unused_sha = self.get_refs_container().follow(ref)
        return RemoteGitBranch(self, repo, ref_chain[-1])

    def open_workingtree(self, recommend_upgrade=False):
        raise NotLocalUrl(self.transport.base)

    def has_workingtree(self):
        return False

    def get_peeled(self, name):
        return self.get_refs_container().get_peeled(name)

    def get_refs_container(self):
        if self._refs is not None:
            return self._refs
        result = self.fetch_pack(lambda x: None, None,
                                 lambda x: None,
                                 lambda x: trace.mutter("git: %s" % x))
        self._refs = remote_refs_dict_to_container(
            result.refs, result.symrefs)
        return self._refs

    def push_branch(self, source, revision_id=None, overwrite=False,
                    remember=False, create_prefix=False, lossy=False,
                    name=None):
        """Push the source branch into this ControlDir."""
        if revision_id is None:
            # No revision supplied by the user, default to the branch
            # revision
            revision_id = source.last_revision()

        push_result = GitPushResult()
        push_result.workingtree_updated = None
        push_result.master_branch = None
        push_result.source_branch = source
        push_result.stacked_on = None
        push_result.branch_push_result = None
        repo = self.find_repository()
        refname = self._get_selected_ref(name)
        if isinstance(source, GitBranch) and lossy:
            raise errors.LossyPushToSameVCS(source.controldir, self)
        source_store = get_object_store(source.repository)
        with source_store.lock_read():
            def get_changed_refs(refs):
                self._refs = remote_refs_dict_to_container(refs)
                ret = dict(refs)
                # TODO(jelmer): Unpeel if necessary
                push_result.new_original_revid = revision_id
                if lossy:
                    new_sha = source_store._lookup_revision_sha1(revision_id)
                else:
                    try:
                        new_sha = repo.lookup_bzr_revision_id(revision_id)[0]
                    except errors.NoSuchRevision:
                        raise errors.NoRoundtrippingSupport(
                            source, self.open_branch(name=name, nascent_ok=True))
                if not overwrite:
                    if remote_divergence(ret.get(refname), new_sha,
                                         source_store):
                        raise DivergedBranches(
                            source, self.open_branch(name, nascent_ok=True))
                ret[refname] = new_sha
                return ret
            if lossy:
                generate_pack_data = source_store.generate_lossy_pack_data
            else:
                generate_pack_data = source_store.generate_pack_data
            new_refs = self.send_pack(get_changed_refs, generate_pack_data)
        push_result.new_revid = repo.lookup_foreign_revision_id(
            new_refs[refname])
        try:
            old_remote = self._refs[refname]
        except KeyError:
            old_remote = ZERO_SHA
        push_result.old_revid = repo.lookup_foreign_revision_id(old_remote)
        self._refs = remote_refs_dict_to_container(new_refs)
        push_result.target_branch = self.open_branch(name)
        if old_remote != ZERO_SHA:
            push_result.branch_push_result = GitBranchPushResult()
            push_result.branch_push_result.source_branch = source
            push_result.branch_push_result.target_branch = (
                push_result.target_branch)
            push_result.branch_push_result.local_branch = None
            push_result.branch_push_result.master_branch = (
                push_result.target_branch)
            push_result.branch_push_result.old_revid = push_result.old_revid
            push_result.branch_push_result.new_revid = push_result.new_revid
            push_result.branch_push_result.new_original_revid = (
                push_result.new_original_revid)
        if source.get_push_location() is None or remember:
            source.set_push_location(push_result.target_branch.base)
        return push_result

    def _find_commondir(self):
        # There is no way to find the commondir, if there is any.
        return self


class EmptyObjectStoreIterator(dict):

    def iterobjects(self):
        return []


class TemporaryPackIterator(Pack):

    def __init__(self, path, resolve_ext_ref):
        super(TemporaryPackIterator, self).__init__(
            path, resolve_ext_ref=resolve_ext_ref)
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
        super(BzrGitHttpClient, self).__init__(
            transport.external_url(), *args, **kwargs)

    def _http_request(self, url, headers=None, data=None,
                      allow_compression=False):
        """Perform HTTP request.

        :param url: Request URL.
        :param headers: Optional custom headers to override defaults.
        :param data: Request data.
        :param allow_compression: Allow GZipped communication.
        :return: Tuple (`response`, `read`), where response is an `urllib3`
            response object with additional `content_type` and
            `redirect_location` properties, and `read` is a consumable read
            method for the response data.
        """
        from breezy.transport.http._urllib2_wrappers import Request
        headers['User-agent'] = user_agent_for_github()
        headers["Pragma"] = "no-cache"
        if allow_compression:
            headers["Accept-Encoding"] = "gzip"
        else:
            headers["Accept-Encoding"] = "identity"

        request = Request(
            ('GET' if data is None else 'POST'),
            url, data, headers,
            accepted_errors=[200, 404])
        request.follow_redirections = True

        response = self.transport._perform(request)

        if response.code == 404:
            raise NotGitRepository()
        elif response.code != 200:
            raise GitProtocolError("unexpected http resp %d for %s" %
                                   (response.code, url))

        # TODO: Optimization available by adding `preload_content=False` to the
        # request and just passing the `read` method on instead of going via
        # `BytesIO`, if we can guarantee that the entire response is consumed
        # before issuing the next to still allow for connection reuse from the
        # pool.
        if response.getheader("Content-Encoding") == "gzip":
            read = gzip.GzipFile(fileobj=response).read
        else:
            read = response.read

        class WrapResponse(object):

            def __init__(self, response):
                self._response = response
                self.status = response.code
                self.content_type = response.getheader("Content-Type")
                self.redirect_location = response.geturl()

            def readlines(self):
                return self._response.readlines()

            def close(self):
                self._response.close()

        return WrapResponse(response), read


class RemoteGitControlDirFormat(GitControlDirFormat):
    """The .git directory control format."""

    supports_workingtrees = False

    @classmethod
    def _known_formats(self):
        return set([RemoteGitControlDirFormat()])

    def get_branch_format(self):
        return RemoteGitBranchFormat()

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
        scheme = urlparse.urlsplit(transport.external_url())[0]
        if isinstance(transport, GitSmartTransport):
            client = transport._get_client()
            client_path = transport._get_path()
        elif scheme in ("http", "https"):
            client = BzrGitHttpClient(transport)
            client_path, _ = urlutils.split_segment_parameters(transport._path)
        elif scheme == 'file':
            client = dulwich.client.LocalGitClient()
            client_path = transport.local_abspath('.')
        else:
            raise NotBranchError(transport.base)
        if not _found:
            pass  # TODO(jelmer): Actually probe for something
        return RemoteGitDir(transport, self, client, client_path)

    def get_format_description(self):
        return "Remote Git Repository"

    def initialize_on_transport(self, transport):
        raise UninitializableFormat(self)

    def supports_transport(self, transport):
        try:
            external_url = transport.external_url()
        except InProcessTransport:
            raise NotBranchError(path=transport.base)
        return (external_url.startswith("http:")
                or external_url.startswith("https:")
                or external_url.startswith("git+")
                or external_url.startswith("git:"))


class GitRemoteRevisionTree(RevisionTree):

    def archive(self, format, name, root=None, subdir=None, force_mtime=None):
        """Create an archive of this tree.

        :param format: Format name (e.g. 'tar')
        :param name: target file name
        :param root: Root directory name (or None)
        :param subdir: Subdirectory to export (or None)
        :return: Iterator over archive chunks
        """
        commit = self._repository.lookup_bzr_revision_id(
            self.get_revision_id())[0]
        f = tempfile.SpooledTemporaryFile()
        # git-upload-archive(1) generaly only supports refs. So let's see if we
        # can find one.
        reverse_refs = {
            v: k for (k, v) in
            self._repository.controldir.get_refs_container().as_dict().items()}
        try:
            committish = reverse_refs[commit]
        except KeyError:
            # No? Maybe the user has uploadArchive.allowUnreachable enabled.
            # Let's hope for the best.
            committish = commit
        self._repository.archive(
            format, committish, f.write,
            subdirs=([subdir] if subdir else None),
            prefix=(root + '/') if root else '')
        f.seek(0)
        return osutils.file_iterator(f)

    def is_versioned(self, path, file_id=None):
        raise GitSmartRemoteNotSupported(self.is_versioned, self)

    def has_filename(self, path):
        raise GitSmartRemoteNotSupported(self.has_filename, self)

    def get_file_text(self, path, file_id=None):
        raise GitSmartRemoteNotSupported(self.get_file_text, self)


class RemoteGitRepository(GitRepository):

    @property
    def user_url(self):
        return self.control_url

    def get_parent_map(self, revids):
        raise GitSmartRemoteNotSupported(self.get_parent_map, self)

    def archive(self, *args, **kwargs):
        return self.controldir.archive(*args, **kwargs)

    def fetch_pack(self, determine_wants, graph_walker, pack_data,
                   progress=None):
        return self.controldir.fetch_pack(
            determine_wants, graph_walker, pack_data, progress)

    def send_pack(self, get_changed_refs, generate_pack_data):
        return self.controldir.send_pack(get_changed_refs, generate_pack_data)

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

    def lookup_bzr_revision_id(self, bzr_revid, mapping=None):
        # This won't work for any round-tripped bzr revisions, but it's a
        # start..
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
        return GitRemoteRevisionTree(self, revid)

    def get_revisions(self, revids):
        raise GitSmartRemoteNotSupported(self.get_revisions, self)

    def has_revisions(self, revids):
        raise GitSmartRemoteNotSupported(self.get_revisions, self)


class RemoteGitTagDict(GitTags):

    def set_tag(self, name, revid):
        sha = self.branch.lookup_bzr_revision_id(revid)[0]
        self._set_ref(name, sha)

    def delete_tag(self, name):
        self._set_ref(name, dulwich.client.ZERO_SHA)

    def _set_ref(self, name, sha):
        ref = tag_name_to_ref(name)

        def get_changed_refs(old_refs):
            ret = dict(old_refs)
            if sha == dulwich.client.ZERO_SHA and ref not in ret:
                raise NoSuchTag(name)
            ret[ref] = sha
            return ret

        def generate_pack_data(have, want, ofs_delta=False):
            return pack_objects_to_data([])
        self.repository.send_pack(get_changed_refs, generate_pack_data)


class RemoteGitBranch(GitBranch):

    def __init__(self, controldir, repository, name):
        self._sha = None
        super(RemoteGitBranch, self).__init__(controldir, repository, name,
                                              RemoteGitBranchFormat())

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
        refs = self.controldir.get_refs_container()
        name = branch_name_to_ref(self.name)
        try:
            self._sha = refs[name]
        except KeyError:
            raise NoSuchRef(name, self.repository.user_url, refs)
        return self._sha

    def _synchronize_history(self, destination, revision_id):
        """See Branch._synchronize_history()."""
        if revision_id is None:
            revision_id = self.last_revision()
        destination.generate_revision_history(revision_id)

    def _get_parent_location(self):
        return None

    def get_push_location(self):
        return None

    def set_push_location(self, url):
        pass

    def _iter_tag_refs(self):
        """Iterate over the tag refs.

        :param refs: Refs dictionary (name -> git sha1)
        :return: iterator over (ref_name, tag_name, peeled_sha1, unpeeled_sha1)
        """
        refs = self.controldir.get_refs_container()
        for ref_name, unpeeled in refs.as_dict().items():
            try:
                tag_name = ref_to_tag_name(ref_name)
            except (ValueError, UnicodeDecodeError):
                continue
            peeled = refs.get_peeled(ref_name)
            if peeled is None:
                # Let's just hope it's a commit
                peeled = unpeeled
            if not isinstance(tag_name, text_type):
                raise TypeError(tag_name)
            yield (ref_name, tag_name, peeled, unpeeled)

    def set_last_revision_info(self, revno, revid):
        self.generate_revision_history(revid)

    def generate_revision_history(self, revision_id, last_rev=None,
                                  other_branch=None):
        sha = self.lookup_bzr_revision_id(revision_id)[0]
        def get_changed_refs(old_refs):
            return {self.ref: sha}
        def generate_pack_data(have, want, ofs_delta=False):
            return pack_objects_to_data([])
        self.repository.send_pack(get_changed_refs, generate_pack_data)
        self._sha = sha


def remote_refs_dict_to_container(refs_dict, symrefs_dict={}):
    base = {}
    peeled = {}
    for k, v in refs_dict.items():
        if is_peeled(k):
            peeled[k[:-3]] = v
        else:
            base[k] = v
    for name, target in symrefs_dict.items():
        base[name] = SYMREF + target
    ret = DictRefsContainer(base)
    ret._peeled = peeled
    return ret
