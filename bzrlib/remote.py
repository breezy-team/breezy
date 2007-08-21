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

from bzrlib import (
    branch,
    errors,
    lockdir,
    repository,
)
from bzrlib.branch import Branch, BranchReferenceFormat
from bzrlib.bzrdir import BzrDir, RemoteBzrDirFormat
from bzrlib.config import BranchConfig, TreeConfig
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.errors import NoSuchRevision
from bzrlib.lockable_files import LockableFiles
from bzrlib.revision import NULL_REVISION
from bzrlib.smart import client, vfs
from bzrlib.symbol_versioning import (
    deprecated_method,
    zero_ninetyone,
    )
from bzrlib.trace import note

# Note: RemoteBzrDirFormat is in bzrdir.py

class RemoteBzrDir(BzrDir):
    """Control directory on a remote server, accessed via bzr:// or similar."""

    def __init__(self, transport, _client=None):
        """Construct a RemoteBzrDir.

        :param _client: Private parameter for testing. Disables probing and the
            use of a real bzrdir.
        """
        BzrDir.__init__(self, transport, RemoteBzrDirFormat())
        # this object holds a delegated bzrdir that uses file-level operations
        # to talk to the other side
        self._real_bzrdir = None

        if _client is None:
            self._shared_medium = transport.get_shared_medium()
            self._client = client._SmartClient(self._shared_medium)
        else:
            self._client = _client
            self._shared_medium = None
            return

        path = self._path_for_remote_call(self._client)
        response = self._client.call('BzrDir.open', path)
        if response not in [('yes',), ('no',)]:
            raise errors.UnexpectedSmartServerResponse(response)
        if response == ('no',):
            raise errors.NotBranchError(path=transport.base)

    def _ensure_real(self):
        """Ensure that there is a _real_bzrdir set.

        Used before calls to self._real_bzrdir.
        """
        if not self._real_bzrdir:
            self._real_bzrdir = BzrDir.open_from_transport(
                self.root_transport, _server_formats=False)

    def create_repository(self, shared=False):
        self._ensure_real()
        self._real_bzrdir.create_repository(shared=shared)
        return self.open_repository()

    def create_branch(self):
        self._ensure_real()
        real_branch = self._real_bzrdir.create_branch()
        return RemoteBranch(self, self.find_repository(), real_branch)

    def create_workingtree(self, revision_id=None):
        raise errors.NotLocalUrl(self.transport.base)

    def find_branch_format(self):
        """Find the branch 'format' for this bzrdir.

        This might be a synthetic object for e.g. RemoteBranch and SVN.
        """
        b = self.open_branch()
        return b._format

    def get_branch_reference(self):
        """See BzrDir.get_branch_reference()."""
        path = self._path_for_remote_call(self._client)
        response = self._client.call('BzrDir.open_branch', path)
        if response[0] == 'ok':
            if response[1] == '':
                # branch at this location.
                return None
            else:
                # a branch reference, use the existing BranchReference logic.
                return response[1]
        elif response == ('nobranch',):
            raise errors.NotBranchError(path=self.root_transport.base)
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def open_branch(self, _unsupported=False):
        assert _unsupported == False, 'unsupported flag support not implemented yet.'
        reference_url = self.get_branch_reference()
        if reference_url is None:
            # branch at this location.
            return RemoteBranch(self, self.find_repository())
        else:
            # a branch reference, use the existing BranchReference logic.
            format = BranchReferenceFormat()
            return format.open(self, _found=True, location=reference_url)
                
    def open_repository(self):
        path = self._path_for_remote_call(self._client)
        response = self._client.call('BzrDir.find_repository', path)
        assert response[0] in ('ok', 'norepository'), \
            'unexpected response code %s' % (response,)
        if response[0] == 'norepository':
            raise errors.NoRepositoryPresent(self)
        assert len(response) == 4, 'incorrect response length %s' % (response,)
        if response[1] == '':
            format = RemoteRepositoryFormat()
            format.rich_root_data = (response[2] == 'yes')
            format.supports_tree_reference = (response[3] == 'yes')
            return RemoteRepository(self, format)
        else:
            raise errors.NoRepositoryPresent(self)

    def open_workingtree(self, recommend_upgrade=True):
        self._ensure_real()
        if self._real_bzrdir.has_workingtree():
            raise errors.NotLocalUrl(self.root_transport)
        else:
            raise errors.NoWorkingTree(self.root_transport.base)

    def _path_for_remote_call(self, client):
        """Return the path to be used for this bzrdir in a remote call."""
        return client.remote_path_from_transport(self.root_transport)

    def get_branch_transport(self, branch_format):
        self._ensure_real()
        return self._real_bzrdir.get_branch_transport(branch_format)

    def get_repository_transport(self, repository_format):
        self._ensure_real()
        return self._real_bzrdir.get_repository_transport(repository_format)

    def get_workingtree_transport(self, workingtree_format):
        self._ensure_real()
        return self._real_bzrdir.get_workingtree_transport(workingtree_format)

    def can_convert_format(self):
        """Upgrading of remote bzrdirs is not supported yet."""
        return False

    def needs_format_conversion(self, format=None):
        """Upgrading of remote bzrdirs is not supported yet."""
        return False

    def clone(self, url, revision_id=None, force_new_repo=False):
        self._ensure_real()
        return self._real_bzrdir.clone(url, revision_id=revision_id,
            force_new_repo=force_new_repo)


class RemoteRepositoryFormat(repository.RepositoryFormat):
    """Format for repositories accessed over a _SmartClient.

    Instances of this repository are represented by RemoteRepository
    instances.

    The RemoteRepositoryFormat is parameterised during construction
    to reflect the capabilities of the real, remote format. Specifically
    the attributes rich_root_data and supports_tree_reference are set
    on a per instance basis, and are not set (and should not be) at
    the class level.
    """

    _matchingbzrdir = RemoteBzrDirFormat

    def initialize(self, a_bzrdir, shared=False):
        assert isinstance(a_bzrdir, RemoteBzrDir), \
            '%r is not a RemoteBzrDir' % (a_bzrdir,)
        return a_bzrdir.create_repository(shared=shared)
    
    def open(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.open_repository()

    def get_format_description(self):
        return 'bzr remote repository'

    def __eq__(self, other):
        return self.__class__ == other.__class__

    def check_conversion_target(self, target_format):
        if self.rich_root_data and not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)
        if (self.supports_tree_reference and
            not getattr(target_format, 'supports_tree_reference', False)):
            raise errors.BadConversionTarget(
                'Does not support nested trees', target_format)


class RemoteRepository(object):
    """Repository accessed over rpc.

    For the moment most operations are performed using local transport-backed
    Repository objects.
    """

    def __init__(self, remote_bzrdir, format, real_repository=None, _client=None):
        """Create a RemoteRepository instance.
        
        :param remote_bzrdir: The bzrdir hosting this repository.
        :param format: The RemoteFormat object to use.
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
            self._client = client._SmartClient(self.bzrdir._shared_medium)
        else:
            self._client = _client
        self._format = format
        self._lock_mode = None
        self._lock_token = None
        self._lock_count = 0
        self._leave_lock = False

    def abort_write_group(self):
        """Complete a write group on the decorated repository.
        
        Smart methods peform operations in a single step so this api
        is not really applicable except as a compatibility thunk
        for older plugins that don't use e.g. the CommitBuilder
        facility.
        """
        self._ensure_real()
        return self._real_repository.abort_write_group()

    def commit_write_group(self):
        """Complete a write group on the decorated repository.
        
        Smart methods peform operations in a single step so this api
        is not really applicable except as a compatibility thunk
        for older plugins that don't use e.g. the CommitBuilder
        facility.
        """
        self._ensure_real()
        return self._real_repository.commit_write_group()

    def _ensure_real(self):
        """Ensure that there is a _real_repository set.

        Used before calls to self._real_repository.
        """
        if not self._real_repository:
            self.bzrdir._ensure_real()
            #self._real_repository = self.bzrdir._real_bzrdir.open_repository()
            self._set_real_repository(self.bzrdir._real_bzrdir.open_repository())

    def get_revision_graph(self, revision_id=None):
        """See Repository.get_revision_graph()."""
        if revision_id is None:
            revision_id = ''
        elif revision_id == NULL_REVISION:
            return {}

        path = self.bzrdir._path_for_remote_call(self._client)
        assert type(revision_id) is str
        response = self._client.call_expecting_body(
            'Repository.get_revision_graph', path, revision_id)
        if response[0][0] not in ['ok', 'nosuchrevision']:
            raise errors.UnexpectedSmartServerResponse(response[0])
        if response[0][0] == 'ok':
            coded = response[1].read_body_bytes()
            if coded == '':
                # no revisions in this repository!
                return {}
            lines = coded.split('\n')
            revision_graph = {}
            for line in lines:
                d = tuple(line.split())
                revision_graph[d[0]] = d[1:]
                
            return revision_graph
        else:
            response_body = response[1].read_body_bytes()
            assert response_body == ''
            raise NoSuchRevision(self, revision_id)

    def has_revision(self, revision_id):
        """See Repository.has_revision()."""
        if revision_id is None:
            # The null revision is always present.
            return True
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Repository.has_revision', path, revision_id)
        assert response[0] in ('yes', 'no'), 'unexpected response code %s' % (response,)
        return response[0] == 'yes'

    def has_same_location(self, other):
        return (self.__class__ == other.__class__ and
                self.bzrdir.transport.base == other.bzrdir.transport.base)
        
    def get_graph(self, other_repository=None):
        """Return the graph for this repository format"""
        return self._real_repository.get_graph(other_repository)

    def gather_stats(self, revid=None, committers=None):
        """See Repository.gather_stats()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        if revid in (None, NULL_REVISION):
            fmt_revid = ''
        else:
            fmt_revid = revid
        if committers is None or not committers:
            fmt_committers = 'no'
        else:
            fmt_committers = 'yes'
        response = self._client.call_expecting_body(
            'Repository.gather_stats', path, fmt_revid, fmt_committers)
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

    def is_in_write_group(self):
        """Return True if there is an open write group.

        write groups are only applicable locally for the smart server..
        """
        if self._real_repository:
            return self._real_repository.is_in_write_group()

    def is_locked(self):
        return self._lock_count >= 1

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

    def _remote_lock_write(self, token):
        path = self.bzrdir._path_for_remote_call(self._client)
        if token is None:
            token = ''
        response = self._client.call('Repository.lock_write', path, token)
        if response[0] == 'ok':
            ok, token = response
            return token
        elif response[0] == 'LockContention':
            raise errors.LockContention('(remote lock)')
        elif response[0] == 'UnlockableTransport':
            raise errors.UnlockableTransport(self.bzrdir.root_transport)
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def lock_write(self, token=None):
        if not self._lock_mode:
            self._lock_token = self._remote_lock_write(token)
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
            raise errors.ReadOnlyError(self)
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
        assert not isinstance(repository, RemoteRepository)
        self._real_repository = repository
        if self._lock_mode == 'w':
            # if we are already locked, the real repository must be able to
            # acquire the lock with our token.
            self._real_repository.lock_write(self._lock_token)
        elif self._lock_mode == 'r':
            self._real_repository.lock_read()

    def start_write_group(self):
        """Start a write group on the decorated repository.
        
        Smart methods peform operations in a single step so this api
        is not really applicable except as a compatibility thunk
        for older plugins that don't use e.g. the CommitBuilder
        facility.
        """
        self._ensure_real()
        return self._real_repository.start_write_group()

    def _unlock(self, token):
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Repository.unlock', path, token)
        if response == ('ok',):
            return
        elif response[0] == 'TokenMismatch':
            raise errors.TokenMismatch(token, '(remote token)')
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def unlock(self):
        if self._lock_count == 1 and self._lock_mode == 'w':
            # don't unlock if inside a write group.
            if self.is_in_write_group():
                raise errors.BzrError(
                    'Must end write groups before releasing write locks.')
        self._lock_count -= 1
        if not self._lock_count:
            mode = self._lock_mode
            self._lock_mode = None
            if self._real_repository is not None:
                self._real_repository.unlock()
            if mode != 'w':
                # Only write-locked repositories need to make a remote method
                # call to perfom the unlock.
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

    def _get_tarball(self, compression):
        """Return a TemporaryFile containing a repository tarball"""
        import tempfile
        path = self.bzrdir._path_for_remote_call(self._client)
        response, protocol = self._client.call_expecting_body(
            'Repository.tarball', path, compression)
        assert response[0] in ('ok', 'failure'), \
            'unexpected response code %s' % (response,)
        if response[0] == 'ok':
            # Extract the tarball and return it
            t = tempfile.NamedTemporaryFile()
            # TODO: rpc layer should read directly into it...
            t.write(protocol.read_body_bytes())
            t.seek(0)
            return t
        else:
            raise errors.SmartServerError(error_code=response)

    def sprout(self, to_bzrdir, revision_id=None):
        # TODO: Option to control what format is created?
        to_repo = to_bzrdir.create_repository()
        self._copy_repository_tarball(to_repo, revision_id)
        return to_repo

    ### These methods are just thin shims to the VFS object for now.

    def revision_tree(self, revision_id):
        self._ensure_real()
        return self._real_repository.revision_tree(revision_id)

    def get_serializer_format(self):
        self._ensure_real()
        return self._real_repository.get_serializer_format()

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        # FIXME: It ought to be possible to call this without immediately
        # triggering _ensure_real.  For now it's the easiest thing to do.
        self._ensure_real()
        builder = self._real_repository.get_commit_builder(branch, parents,
                config, timestamp=timestamp, timezone=timezone,
                committer=committer, revprops=revprops, revision_id=revision_id)
        # Make the builder use this RemoteRepository rather than the real one.
        builder.repository = self
        return builder

    @needs_write_lock
    def add_inventory(self, revid, inv, parents):
        self._ensure_real()
        return self._real_repository.add_inventory(revid, inv, parents)

    @needs_write_lock
    def add_revision(self, rev_id, rev, inv=None, config=None):
        self._ensure_real()
        return self._real_repository.add_revision(
            rev_id, rev, inv=inv, config=config)

    @needs_read_lock
    def get_inventory(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_inventory(revision_id)

    @needs_read_lock
    def get_revision(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_revision(revision_id)

    @property
    def weave_store(self):
        self._ensure_real()
        return self._real_repository.weave_store

    def get_transaction(self):
        self._ensure_real()
        return self._real_repository.get_transaction()

    @needs_read_lock
    def clone(self, a_bzrdir, revision_id=None):
        self._ensure_real()
        return self._real_repository.clone(a_bzrdir, revision_id=revision_id)

    def make_working_trees(self):
        """RemoteRepositories never create working trees by default."""
        return False

    def fetch(self, source, revision_id=None, pb=None):
        self._ensure_real()
        return self._real_repository.fetch(
            source, revision_id=revision_id, pb=pb)

    def create_bundle(self, target, base, fileobj, format=None):
        self._ensure_real()
        self._real_repository.create_bundle(target, base, fileobj, format)

    @property
    def control_weaves(self):
        self._ensure_real()
        return self._real_repository.control_weaves

    @needs_read_lock
    def get_ancestry(self, revision_id, topo_sorted=True):
        self._ensure_real()
        return self._real_repository.get_ancestry(revision_id, topo_sorted)

    @needs_read_lock
    def get_inventory_weave(self):
        self._ensure_real()
        return self._real_repository.get_inventory_weave()

    def fileids_altered_by_revision_ids(self, revision_ids):
        self._ensure_real()
        return self._real_repository.fileids_altered_by_revision_ids(revision_ids)

    def iter_files_bytes(self, desired_files):
        """See Repository.iter_file_bytes.
        """
        self._ensure_real()
        return self._real_repository.iter_files_bytes(desired_files)

    @needs_read_lock
    def get_signature_text(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_signature_text(revision_id)

    @needs_read_lock
    def get_revision_graph_with_ghosts(self, revision_ids=None):
        self._ensure_real()
        return self._real_repository.get_revision_graph_with_ghosts(
            revision_ids=revision_ids)

    @needs_read_lock
    def get_inventory_xml(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_inventory_xml(revision_id)

    def deserialise_inventory(self, revision_id, xml):
        self._ensure_real()
        return self._real_repository.deserialise_inventory(revision_id, xml)

    def reconcile(self, other=None, thorough=False):
        self._ensure_real()
        return self._real_repository.reconcile(other=other, thorough=thorough)
        
    def all_revision_ids(self):
        self._ensure_real()
        return self._real_repository.all_revision_ids()
    
    @needs_read_lock
    def get_deltas_for_revisions(self, revisions):
        self._ensure_real()
        return self._real_repository.get_deltas_for_revisions(revisions)

    @needs_read_lock
    def get_revision_delta(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_revision_delta(revision_id)

    @needs_read_lock
    def revision_trees(self, revision_ids):
        self._ensure_real()
        return self._real_repository.revision_trees(revision_ids)

    @needs_read_lock
    def get_revision_reconcile(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_revision_reconcile(revision_id)

    @needs_read_lock
    def check(self, revision_ids):
        self._ensure_real()
        return self._real_repository.check(revision_ids)

    def copy_content_into(self, destination, revision_id=None):
        self._ensure_real()
        return self._real_repository.copy_content_into(
            destination, revision_id=revision_id)

    def _copy_repository_tarball(self, destination, revision_id=None):
        # get a tarball of the remote repository, and copy from that into the
        # destination
        from bzrlib import osutils
        import tarfile
        import tempfile
        from StringIO import StringIO
        # TODO: Maybe a progress bar while streaming the tarball?
        note("Copying repository content as tarball...")
        tar_file = self._get_tarball('bz2')
        try:
            tar = tarfile.open('repository', fileobj=tar_file,
                mode='r|bz2')
            tmpdir = tempfile.mkdtemp()
            try:
                _extract_tar(tar, tmpdir)
                tmp_bzrdir = BzrDir.open(tmpdir)
                tmp_repo = tmp_bzrdir.open_repository()
                tmp_repo.copy_content_into(destination, revision_id)
            finally:
                osutils.rmtree(tmpdir)
        finally:
            tar_file.close()
        # TODO: if the server doesn't support this operation, maybe do it the
        # slow way using the _real_repository?
        #
        # TODO: Suggestion from john: using external tar is much faster than
        # python's tarfile library, but it may not work on windows.

    @needs_write_lock
    def pack(self):
        """Compress the data within the repository.

        This is not currently implemented within the smart server.
        """
        self._ensure_real()
        return self._real_repository.pack()

    def set_make_working_trees(self, new_value):
        raise NotImplementedError(self.set_make_working_trees)

    @needs_write_lock
    def sign_revision(self, revision_id, gpg_strategy):
        self._ensure_real()
        return self._real_repository.sign_revision(revision_id, gpg_strategy)

    @needs_read_lock
    def get_revisions(self, revision_ids):
        self._ensure_real()
        return self._real_repository.get_revisions(revision_ids)

    def supports_rich_root(self):
        self._ensure_real()
        return self._real_repository.supports_rich_root()

    def iter_reverse_revision_history(self, revision_id):
        self._ensure_real()
        return self._real_repository.iter_reverse_revision_history(revision_id)

    @property
    def _serializer(self):
        self._ensure_real()
        return self._real_repository._serializer

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        self._ensure_real()
        return self._real_repository.store_revision_signature(
            gpg_strategy, plaintext, revision_id)

    def has_signature_for_revision_id(self, revision_id):
        self._ensure_real()
        return self._real_repository.has_signature_for_revision_id(revision_id)


class RemoteBranchLockableFiles(LockableFiles):
    """A 'LockableFiles' implementation that talks to a smart server.
    
    This is not a public interface class.
    """

    def __init__(self, bzrdir, _client):
        self.bzrdir = bzrdir
        self._client = _client
        self._need_find_modes = True
        LockableFiles.__init__(
            self, bzrdir.get_branch_transport(None),
            'lock', lockdir.LockDir)

    def _find_modes(self):
        # RemoteBranches don't let the client set the mode of control files.
        self._dir_mode = None
        self._file_mode = None

    def get(self, path):
        """'get' a remote path as per the LockableFiles interface.

        :param path: the file to 'get'. If this is 'branch.conf', we do not
             just retrieve a file, instead we ask the smart server to generate
             a configuration for us - which is retrieved as an INI file.
        """
        if path == 'branch.conf':
            path = self.bzrdir._path_for_remote_call(self._client)
            response = self._client.call_expecting_body(
                'Branch.get_config_file', path)
            assert response[0][0] == 'ok', \
                'unexpected response code %s' % (response[0],)
            return StringIO(response[1].read_body_bytes())
        else:
            # VFS fallback.
            return LockableFiles.get(self, path)


class RemoteBranchFormat(branch.BranchFormat):

    def __eq__(self, other):
        return (isinstance(other, RemoteBranchFormat) and 
            self.__dict__ == other.__dict__)

    def get_format_description(self):
        return 'Remote BZR Branch'

    def get_format_string(self):
        return 'Remote BZR Branch'

    def open(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.open_branch()

    def initialize(self, a_bzrdir):
        assert isinstance(a_bzrdir, RemoteBzrDir)
        return a_bzrdir.create_branch()

    def supports_tags(self):
        # Remote branches might support tags, but we won't know until we
        # access the real remote branch.
        return True


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
        # We intentionally don't call the parent class's __init__, because it
        # will try to assign to self.tags, which is a property in this subclass.
        # And the parent's __init__ doesn't do much anyway.
        self._revision_history_cache = None
        self.bzrdir = remote_bzrdir
        if _client is not None:
            self._client = _client
        else:
            self._client = client._SmartClient(self.bzrdir._shared_medium)
        self.repository = remote_repository
        if real_branch is not None:
            self._real_branch = real_branch
            # Give the remote repository the matching real repo.
            real_repo = self._real_branch.repository
            if isinstance(real_repo, RemoteRepository):
                real_repo._ensure_real()
                real_repo = real_repo._real_repository
            self.repository._set_real_repository(real_repo)
            # Give the branch the remote repository to let fast-pathing happen.
            self._real_branch.repository = self.repository
        else:
            self._real_branch = None
        # Fill out expected attributes of branch for bzrlib api users.
        self._format = RemoteBranchFormat()
        self.base = self.bzrdir.root_transport.base
        self._control_files = None
        self._lock_mode = None
        self._lock_token = None
        self._lock_count = 0
        self._leave_lock = False

    def __str__(self):
        return "%s(%s)" % (self.__class__.__name__, self.base)

    __repr__ = __str__

    def _ensure_real(self):
        """Ensure that there is a _real_branch set.

        Used before calls to self._real_branch.
        """
        if not self._real_branch:
            assert vfs.vfs_enabled()
            self.bzrdir._ensure_real()
            self._real_branch = self.bzrdir._real_bzrdir.open_branch()
            # Give the remote repository the matching real repo.
            real_repo = self._real_branch.repository
            if isinstance(real_repo, RemoteRepository):
                real_repo._ensure_real()
                real_repo = real_repo._real_repository
            self.repository._set_real_repository(real_repo)
            # Give the branch the remote repository to let fast-pathing happen.
            self._real_branch.repository = self.repository
            # XXX: deal with _lock_mode == 'w'
            if self._lock_mode == 'r':
                self._real_branch.lock_read()

    @property
    def control_files(self):
        # Defer actually creating RemoteBranchLockableFiles until its needed,
        # because it triggers an _ensure_real that we otherwise might not need.
        if self._control_files is None:
            self._control_files = RemoteBranchLockableFiles(
                self.bzrdir, self._client)
        return self._control_files

    def _get_checkout_format(self):
        self._ensure_real()
        return self._real_branch._get_checkout_format()

    def get_physical_lock_status(self):
        """See Branch.get_physical_lock_status()."""
        # should be an API call to the server, as branches must be lockable.
        self._ensure_real()
        return self._real_branch.get_physical_lock_status()

    def lock_read(self):
        if not self._lock_mode:
            self._lock_mode = 'r'
            self._lock_count = 1
            if self._real_branch is not None:
                self._real_branch.lock_read()
        else:
            self._lock_count += 1

    def _remote_lock_write(self, token):
        if token is None:
            branch_token = repo_token = ''
        else:
            branch_token = token
            repo_token = self.repository.lock_write()
            self.repository.unlock()
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Branch.lock_write', path, branch_token,
                                     repo_token)
        if response[0] == 'ok':
            ok, branch_token, repo_token = response
            return branch_token, repo_token
        elif response[0] == 'LockContention':
            raise errors.LockContention('(remote lock)')
        elif response[0] == 'TokenMismatch':
            raise errors.TokenMismatch(token, '(remote token)')
        elif response[0] == 'UnlockableTransport':
            raise errors.UnlockableTransport(self.bzrdir.root_transport)
        elif response[0] == 'ReadOnlyError':
            raise errors.ReadOnlyError(self)
        else:
            raise errors.UnexpectedSmartServerResponse(response)
            
    def lock_write(self, token=None):
        if not self._lock_mode:
            remote_tokens = self._remote_lock_write(token)
            self._lock_token, self._repo_lock_token = remote_tokens
            assert self._lock_token, 'Remote server did not return a token!'
            # TODO: We really, really, really don't want to call _ensure_real
            # here, but it's the easiest way to ensure coherency between the
            # state of the RemoteBranch and RemoteRepository objects and the
            # physical locks.  If we don't materialise the real objects here,
            # then getting everything in the right state later is complex, so
            # for now we just do it the lazy way.
            #   -- Andrew Bennetts, 2007-02-22.
            self._ensure_real()
            if self._real_branch is not None:
                self._real_branch.repository.lock_write(
                    token=self._repo_lock_token)
                try:
                    self._real_branch.lock_write(token=self._lock_token)
                finally:
                    self._real_branch.repository.unlock()
            if token is not None:
                self._leave_lock = True
            else:
                # XXX: this case seems to be unreachable; token cannot be None.
                self._leave_lock = False
            self._lock_mode = 'w'
            self._lock_count = 1
        elif self._lock_mode == 'r':
            raise errors.ReadOnlyTransaction
        else:
            if token is not None:
                # A token was given to lock_write, and we're relocking, so check
                # that the given token actually matches the one we already have.
                if token != self._lock_token:
                    raise errors.TokenMismatch(token, self._lock_token)
            self._lock_count += 1
        return self._lock_token

    def _unlock(self, branch_token, repo_token):
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Branch.unlock', path, branch_token,
                                     repo_token)
        if response == ('ok',):
            return
        elif response[0] == 'TokenMismatch':
            raise errors.TokenMismatch(
                str((branch_token, repo_token)), '(remote tokens)')
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def unlock(self):
        self._lock_count -= 1
        if not self._lock_count:
            self._clear_cached_state()
            mode = self._lock_mode
            self._lock_mode = None
            if self._real_branch is not None:
                if not self._leave_lock:
                    # If this RemoteBranch will remove the physical lock for the
                    # repository, make sure the _real_branch doesn't do it
                    # first.  (Because the _real_branch's repository is set to
                    # be the RemoteRepository.)
                    self._real_branch.repository.leave_lock_in_place()
                self._real_branch.unlock()
            if mode != 'w':
                # Only write-locked branched need to make a remote method call
                # to perfom the unlock.
                return
            assert self._lock_token, 'Locked, but no token!'
            branch_token = self._lock_token
            repo_token = self._repo_lock_token
            self._lock_token = None
            self._repo_lock_token = None
            if not self._leave_lock:
                self._unlock(branch_token, repo_token)

    def break_lock(self):
        self._ensure_real()
        return self._real_branch.break_lock()

    def leave_lock_in_place(self):
        self._leave_lock = True

    def dont_leave_lock_in_place(self):
        self._leave_lock = False

    def last_revision_info(self):
        """See Branch.last_revision_info()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Branch.last_revision_info', path)
        assert response[0] == 'ok', 'unexpected response code %s' % (response,)
        revno = int(response[1])
        last_revision = response[2]
        return (revno, last_revision)

    def _gen_revision_history(self):
        """See Branch._gen_revision_history()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call_expecting_body(
            'Branch.revision_history', path)
        assert response[0][0] == 'ok', ('unexpected response code %s'
                                        % (response[0],))
        result = response[1].read_body_bytes().split('\x00')
        if result == ['']:
            return []
        return result

    @needs_write_lock
    def set_revision_history(self, rev_history):
        # Send just the tip revision of the history; the server will generate
        # the full history from that.  If the revision doesn't exist in this
        # branch, NoSuchRevision will be raised.
        path = self.bzrdir._path_for_remote_call(self._client)
        if rev_history == []:
            rev_id = 'null:'
        else:
            rev_id = rev_history[-1]
        self._clear_cached_state()
        response = self._client.call('Branch.set_last_revision',
            path, self._lock_token, self._repo_lock_token, rev_id)
        if response[0] == 'NoSuchRevision':
            raise NoSuchRevision(self, rev_id)
        else:
            assert response == ('ok',), (
                'unexpected response code %r' % (response,))
        self._cache_revision_history(rev_history)

    def get_parent(self):
        self._ensure_real()
        return self._real_branch.get_parent()
        
    def set_parent(self, url):
        self._ensure_real()
        return self._real_branch.set_parent(url)
        
    def get_config(self):
        return RemoteBranchConfig(self)

    def sprout(self, to_bzrdir, revision_id=None):
        # Like Branch.sprout, except that it sprouts a branch in the default
        # format, because RemoteBranches can't be created at arbitrary URLs.
        # XXX: if to_bzrdir is a RemoteBranch, this should perhaps do
        # to_bzrdir.create_branch...
        result = branch.BranchFormat.get_default_format().initialize(to_bzrdir)
        self.copy_content_into(result, revision_id=revision_id)
        result.set_parent(self.bzrdir.root_transport.base)
        return result

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None,
             **kwargs):
        # FIXME: This asks the real branch to run the hooks, which means
        # they're called with the wrong target branch parameter. 
        # The test suite specifically allows this at present but it should be
        # fixed.  It should get a _override_hook_target branch,
        # as push does.  -- mbp 20070405
        self._ensure_real()
        self._real_branch.pull(
            source, overwrite=overwrite, stop_revision=stop_revision,
            **kwargs)

    @needs_read_lock
    def push(self, target, overwrite=False, stop_revision=None):
        self._ensure_real()
        return self._real_branch.push(
            target, overwrite=overwrite, stop_revision=stop_revision,
            _override_hook_source_branch=self)

    def is_locked(self):
        return self._lock_count >= 1

    def set_last_revision_info(self, revno, revision_id):
        self._ensure_real()
        self._clear_cached_state()
        return self._real_branch.set_last_revision_info(revno, revision_id)

    def generate_revision_history(self, revision_id, last_rev=None,
                                  other_branch=None):
        self._ensure_real()
        return self._real_branch.generate_revision_history(
            revision_id, last_rev=last_rev, other_branch=other_branch)

    @property
    def tags(self):
        self._ensure_real()
        return self._real_branch.tags

    def set_push_location(self, location):
        self._ensure_real()
        return self._real_branch.set_push_location(location)

    def update_revisions(self, other, stop_revision=None):
        self._ensure_real()
        return self._real_branch.update_revisions(
            other, stop_revision=stop_revision)


class RemoteBranchConfig(BranchConfig):

    def username(self):
        self.branch._ensure_real()
        return self.branch._real_branch.get_config().username()

    def _get_branch_data_config(self):
        self.branch._ensure_real()
        if self._branch_data_config is None:
            self._branch_data_config = TreeConfig(self.branch._real_branch)
        return self._branch_data_config


def _extract_tar(tar, to_dir):
    """Extract all the contents of a tarfile object.

    A replacement for extractall, which is not present in python2.4
    """
    for tarinfo in tar:
        tar.extract(tarinfo, to_dir)
