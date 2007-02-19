# Copyright (C) 2006, 2007 Canonical Ltd
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

# TODO: At some point, handle upgrades by just passing the whole request
# across to run on the server.

from cStringIO import StringIO
from urlparse import urlparse

from bzrlib import branch, errors, repository
from bzrlib.branch import BranchReferenceFormat
from bzrlib.bzrdir import BzrDir, BzrDirFormat, RemoteBzrDirFormat
from bzrlib.errors import NoSuchRevision
from bzrlib.revision import NULL_REVISION
from bzrlib.smart import client, vfs
from bzrlib.urlutils import unescape

# Note: RemoteBzrDirFormat is in bzrdir.py

class RemoteBzrDir(BzrDir):
    """Control directory on a remote server, accessed by HPSS."""

    def __init__(self, transport, _client=None):
        """Construct a RemoteBzrDir.

        :param _client: Private parameter for testing. Disables probing and the
            use of a real bzrdir.
        """
        BzrDir.__init__(self, transport, RemoteBzrDirFormat())
        if _client is not None:
            self.client = _client
            return

        self.client = transport.get_smart_client()
        # this object holds a delegated bzrdir that uses file-level operations
        # to talk to the other side
        # XXX: We should go into find_format, but not allow it to find
        # RemoteBzrDirFormat and make sure it finds the real underlying format.
        self._real_bzrdir = None
        
        self._ensure_real()
        smartclient = client.SmartClient(self.client)
        path = self._path_for_remote_call(smartclient)
        #self._real_bzrdir._format.probe_transport(transport)
        response = smartclient.call('probe_dont_use', path)
        if response == ('no',):
            raise errors.NotBranchError(path=transport.base)

    def _ensure_real(self):
        """Ensure that there is a _real_bzrdir set.

        used before calls to self._real_bzrdir.
        """
        if not self._real_bzrdir:
            default_format = BzrDirFormat.get_default_format()
            self._real_bzrdir = default_format.open(self.root_transport,
                _found=True)

    def create_repository(self, shared=False):
        return RemoteRepository(
            self, self._real_bzrdir.create_repository(shared=shared))

    def create_branch(self):
        real_branch = self._real_bzrdir.create_branch()
        return RemoteBranch(self, self.find_repository(), real_branch)

    def create_workingtree(self, revision_id=None):
        real_workingtree = self._real_bzrdir.create_workingtree(revision_id=revision_id)
        return RemoteWorkingTree(self, real_workingtree)

    def open_branch(self, _unsupported=False):
        assert _unsupported == False, 'unsupported flag support not implemented yet.'
        smartclient = client.SmartClient(self.client)
        path = self._path_for_remote_call(smartclient)
        response = smartclient.call('BzrDir.open_branch', path)
        assert response[0] == 'ok', 'unexpected response code %s' % (response,)
        if response[0] != 'ok':
            # this should probably be a regular translate no ?
            raise errors.NotBranchError(path=self.root_transport.base)
        if response[1] == '':
            # branch at this location.
            return RemoteBranch(self, self.find_repository())
        else:
            # a branch reference, use the existing BranchReference logic.
            format = BranchReferenceFormat()
            return format.open(self, _found=True, location=response[1])

    def open_repository(self):
        smartclient = client.SmartClient(self.client)
        path = self._path_for_remote_call(smartclient)
        response = smartclient.call('BzrDir.find_repository', path)
        assert response[0] in ('ok', 'norepository'), \
            'unexpected response code %s' % (response,)
        if response[0] == 'norepository':
            raise errors.NoRepositoryPresent(self)
        if response[1] == '':
            return RemoteRepository(self)
        else:
            raise errors.NoRepositoryPresent(self)

    def open_workingtree(self):
        return RemoteWorkingTree(self, self._real_bzrdir.open_workingtree())

    def _path_for_remote_call(self, client):
        """Return the path to be used for this bzrdir in a remote call."""
        return client.remote_path_from_transport(self.root_transport)

    def get_branch_transport(self, branch_format):
        return self._real_bzrdir.get_branch_transport(branch_format)

    def get_repository_transport(self, repository_format):
        return self._real_bzrdir.get_repository_transport(repository_format)

    def get_workingtree_transport(self, workingtree_format):
        return self._real_bzrdir.get_workingtree_transport(workingtree_format)

    def can_convert_format(self):
        """Upgrading of remote bzrdirs is not supported yet."""
        return False

    def needs_format_conversion(self, format=None):
        """Upgrading of remote bzrdirs is not supported yet."""
        return False


class RemoteRepositoryFormat(repository.RepositoryFormat):
    """Format for repositories accessed over rpc.

    Instances of this repository are represented by RemoteRepository
    instances.
    """

    _matchingbzrdir = RemoteBzrDirFormat

    def initialize(self, a_bzrdir, shared=False):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.create_repository(shared=shared)
    
    def open(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.open_repository()

    def get_format_description(self):
        return 'bzr remote repository'

    def __eq__(self, other):
        return self.__class__ == other.__class__

    rich_root_data = False


class RemoteRepository(object):
    """Repository accessed over rpc.

    For the moment everything is delegated to IO-like operations over
    the transport.
    """

    def __init__(self, remote_bzrdir, real_repository=None, _client=None):
        """Create a RemoteRepository instance.
        
        :param remote_bzrdir: The bzrdir hosting this repository.
        :param real_repository: If not None, a local implementation of the
            repository logic for the repository, usually accessing the data
            via the VFS.
        :param _client: Private testing parameter - override the smart client
            to be used by the repository.
        """
        if real_repository:
            self._real_repository = real_repository
        else:
            self._real_repository = None
        self.bzrdir = remote_bzrdir
        if _client is None:
            self._client = client.SmartClient(self.bzrdir.client)
        else:
            self._client = _client
        self._format = RemoteRepositoryFormat()
        self._lock_mode = None
        self._lock_token = None
        self._lock_count = 0
        self._leave_lock = False

    def _ensure_real(self):
        """Ensure that there is a _real_repository set.

        used before calls to self._real_repository.
        """
        if not self._real_repository:
            self.bzrdir._ensure_real()
            self._real_repository = self.bzrdir._real_bzrdir.open_repository()

    def get_revision_graph(self, revision_id=None):
        """See Repository.get_revision_graph()."""
        if revision_id is None:
            revision_id = ''
        elif revision_id == NULL_REVISION:
            return {}

        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call2('Repository.get_revision_graph', path, revision_id.encode('utf8'))
        assert response[0][0] in ('ok', 'nosuchrevision'), 'unexpected response code %s' % (response[0],)
        if response[0][0] == 'ok':
            coded = response[1].read_body_bytes()
            lines = coded.decode('utf8').split('\n')
            revision_graph = {}
            # FIXME
            for line in lines:
                d = list(line.split())
                revision_graph[d[0]] = d[1:]
                
            return revision_graph
        else:
            assert response[1] != ''
            raise NoSuchRevision(self, revision_id)

    def has_revision(self, revision_id):
        """See Repository.has_revision()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Repository.has_revision', path, revision_id.encode('utf8'))
        assert response[0] in ('ok', 'no'), 'unexpected response code %s' % (response,)
        return response[0] == 'ok'

    def gather_stats(self, revid, committers=None):
        """See Repository.gather_stats()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        if revid in (None, NULL_REVISION):
            fmt_revid = ''
        else:
            fmt_revid = revid.encode('utf8')
        if committers is None:
            fmt_committers = 'no'
        else:
            fmt_committers = 'yes'
        response = self._client.call2('Repository.gather_stats', path,
                                      fmt_revid, fmt_committers)
        assert response[0][0] == 'ok', \
            'unexpected response code %s' % (response[0],)

        body = response[1].read_body_bytes()
        result = {}
        for line in body.split('\n'):
            if not line:
                continue
            key, val_text = line.split(':')
            if key in ('revisions', 'size', 'committers'):
                result[key] = int(val_text)
            elif key in ('firstrev', 'latestrev'):
                values = val_text.split(' ')[1:]
                result[key] = (float(values[0]), long(values[1]))

        return result

    def get_physical_lock_status(self):
        """See Repository.get_physical_lock_status()."""
        return False

    def is_shared(self):
        """See Repository.is_shared()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Repository.is_shared', path)
        assert response[0] in ('yes', 'no'), 'unexpected response code %s' % (response,)
        return response[0] == 'yes'

    def lock_read(self):
        # wrong eventually - want a local lock cache context
        if not self._lock_mode:
            self._lock_mode = 'r'
            self._lock_count = 1
            if self._real_repository is not None:
                self._real_repository.lock_read()
        else:
            self._lock_count += 1

    def _lock_write(self, token):
        path = self.bzrdir._path_for_remote_call(self._client)
        if token is None:
            token = ''
        response = self._client.call('Repository.lock_write', path, token)
        if response[0] == 'ok':
            ok, token = response
            return token
        elif response[0] == 'LockContention':
            raise errors.LockContention('(remote lock)')
        else:
            assert False, 'unexpected response code %s' % (response,)

    def lock_write(self, token=None):
        if not self._lock_mode:
            self._lock_token = self._lock_write(token)
            assert self._lock_token, 'Remote server did not return a token!'
            if self._real_repository is not None:
                self._real_repository.lock_write(token=self._lock_token)
            if token is not None:
                self._leave_lock = True
            else:
                self._leave_lock = False
            self._lock_mode = 'w'
            self._lock_count = 1
        elif self._lock_mode == 'r':
            raise errors.ReadOnlyTransaction
        else:
            self._lock_count += 1
        return self._lock_token

    def leave_lock_in_place(self):
        self._leave_lock = True

    def dont_leave_lock_in_place(self):
        self._leave_lock = False

    def _set_real_repository(self, repository):
        """Set the _real_repository for this repository.

        :param repository: The repository to fallback to for non-hpss
            implemented operations.
        """
        self._real_repository = repository
        if self._lock_mode == 'w':
            # if we are already locked, the real repository must be able to
            # acquire the lock with our token.
            self._real_repository.lock_write(self._lock_token)

    def _unlock(self, token):
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Repository.unlock', path, token)
        if response == ('ok',):
            return
        elif response[0] == 'TokenMismatch':
            raise errors.TokenMismatch(token, '(remote token)')
        else:
            assert False, 'unexpected response code %s' % (response,)

    def unlock(self):
        self._lock_count -= 1
        if not self._lock_count:
            mode = self._lock_mode
            self._lock_mode = None
            if self._real_repository is not None:
                self._real_repository.unlock()
            if mode != 'w':
                return
            assert self._lock_token, 'Locked, but no token!'
            token = self._lock_token
            self._lock_token = None
            if not self._leave_lock:
                self._unlock(token)

    def break_lock(self):
        # should hand off to the network
        self._ensure_real()
        return self._real_repository.break_lock()


class RemoteBranchLockableFiles(object):
    """A 'LockableFiles' implementation that talks to a smart server.
    
    This is not a public interface class.
    """

    def __init__(self, bzrdir, _client):
        self.bzrdir = bzrdir
        self._client = _client

    def get(self, path):
        """'get' a remote path as per the LockableFiles interface.

        :param path: the file to 'get'. If this is 'branch.conf', we do not
             just retrieve a file, instead we ask the smart server to generate
             a configuration for us - which is retrieved as an INI file.
        """
        assert path == 'branch.conf'
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call2('Branch.get_config_file', path)
        assert response[0][0] == 'ok', \
            'unexpected response code %s' % (response[0],)
        return StringIO(response[1].read_body_bytes())


class RemoteBranchFormat(branch.BranchFormat):

    def get_format_description(self):
        return 'Remote BZR Branch'

    def open(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.open_branch()

    def initialize(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.create_branch()


class RemoteBranch(branch.Branch):
    """Branch stored on a server accessed by HPSS RPC.

    At the moment most operations are mapped down to simple file operations.
    """

    def __init__(self, remote_bzrdir, remote_repository, real_branch=None,
        _client=None):
        """Create a RemoteBranch instance.

        :param real_branch: An optional local implementation of the branch
            format, usually accessing the data via the VFS.
        :param _client: Private parameter for testing.
        """
        self.bzrdir = remote_bzrdir
        if _client is not None:
            self._client = _client
        else:
            self._client = client.SmartClient(self.bzrdir.client)
        self.repository = remote_repository
        if real_branch is not None:
            self._real_branch = real_branch
        else:
            self._real_branch = None
        # Fill out expected attributes of branch for bzrlib api users.
        self._format = RemoteBranchFormat()
        self.base = self.bzrdir.root_transport.base
        self.control_files = RemoteBranchLockableFiles(self.bzrdir, self._client)

    def _ensure_real(self):
        """Ensure that there is a _real_branch set.

        used before calls to self._real_branch.
        """
        if not self._real_branch:
            assert vfs.vfs_enabled()
            self.bzrdir._ensure_real()
            self._real_branch = self.bzrdir._real_bzrdir.open_branch()
            # Give the remote repository the matching real repo.
            self.repository._set_real_repository(self._real_branch.repository)
            # Give the branch the remote repository to let fast-pathing happen.
            self._real_branch.repository = self.repository

    def get_physical_lock_status(self):
        """See Branch.get_physical_lock_status()."""
        # should be an API call to the server, as branches must be lockable.
        self._ensure_real()
        return self._real_branch.get_physical_lock_status()

    def lock_read(self):
        self._ensure_real()
        return self._real_branch.lock_read()

    def lock_write(self, token=None):
        self._ensure_real()
        return self._real_branch.lock_write(token=token)

    def unlock(self):
        self._ensure_real()
        return self._real_branch.unlock()

    def break_lock(self):
        self._ensure_real()
        return self._real_branch.break_lock()

    def last_revision_info(self):
        """See Branch.last_revision_info()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Branch.last_revision_info', path)
        assert response[0] == 'ok', 'unexpected response code %s' % (response,)
        revno = int(response[1])
        last_revision = response[2].decode('utf8')
        if last_revision == '':
            last_revision = NULL_REVISION
        return (revno, last_revision)

    def revision_history(self):
        """See Branch.revision_history()."""
        # XXX: TODO: this does not cache the revision history for the duration
        # of a lock, which is a bug - see the code for regular branches
        # for details.
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call2('Branch.revision_history', path)
        assert response[0][0] == 'ok', 'unexpected response code %s' % (response[0],)
        result = response[1].read_body_bytes().decode('utf8').split('\x00')
        if result == ['']:
            return []
        return result

    def set_revision_history(self, rev_history):
        # Send just the tip revision of the history; the server will generate
        # the full history from that.  If the revision doesn't exist in this
        # branch, NoSuchRevision will be raised.
        path = self.bzrdir._path_for_remote_call(self._client)
        if rev_history == []:
            rev_id = ''
        else:
            rev_id = rev_history[-1]
        response = self._client.call('Branch.set_last_revision', path, rev_id)
        if response[0] == 'NoSuchRevision':
            raise NoSuchRevision(self, rev_id)
        else:
            assert response == ('ok',), (
                'unexpected response code %r' % (response,))

    def get_parent(self):
        self._ensure_real()
        return self._real_branch.get_parent()
        
    def set_parent(self, url):
        self._ensure_real()
        return self._real_branch.set_parent(url)
        

class RemoteWorkingTree(object):

    def __init__(self, remote_bzrdir, real_workingtree):
        self.real_workingtree = real_workingtree
        self.bzrdir = remote_bzrdir

    def __getattr__(self, name):
        # XXX: temporary way to lazily delegate everything to the real
        # workingtree
        return getattr(self.real_workingtree, name)


