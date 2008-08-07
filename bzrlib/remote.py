# Copyright (C) 2006, 2007, 2008 Canonical Ltd
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

import bz2
from cStringIO import StringIO

from bzrlib import (
    branch,
    debug,
    errors,
    graph,
    lockdir,
    repository,
    revision,
    symbol_versioning,
)
from bzrlib.branch import BranchReferenceFormat
from bzrlib.bzrdir import BzrDir, RemoteBzrDirFormat
from bzrlib.config import BranchConfig, TreeConfig
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.errors import (
    NoSuchRevision,
    SmartProtocolError,
    )
from bzrlib.lockable_files import LockableFiles
from bzrlib.pack import ContainerPushParser
from bzrlib.smart import client, vfs
from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )
from bzrlib.revision import ensure_null, NULL_REVISION
from bzrlib.trace import mutter, note, warning


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
            medium = transport.get_smart_medium()
            self._client = client._SmartClient(medium)
        else:
            self._client = _client
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

    def cloning_metadir(self):
        self._ensure_real()
        return self._real_bzrdir.cloning_metadir()

    def _translate_error(self, err, **context):
        _translate_error(err, bzrdir=self, **context)
        
    def create_repository(self, shared=False):
        self._ensure_real()
        self._real_bzrdir.create_repository(shared=shared)
        return self.open_repository()

    def destroy_repository(self):
        """See BzrDir.destroy_repository"""
        self._ensure_real()
        self._real_bzrdir.destroy_repository()

    def create_branch(self):
        self._ensure_real()
        real_branch = self._real_bzrdir.create_branch()
        return RemoteBranch(self, self.find_repository(), real_branch)

    def destroy_branch(self):
        """See BzrDir.destroy_branch"""
        self._ensure_real()
        self._real_bzrdir.destroy_branch()

    def create_workingtree(self, revision_id=None, from_branch=None):
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
        try:
            response = self._client.call('BzrDir.open_branch', path)
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err)
        if response[0] == 'ok':
            if response[1] == '':
                # branch at this location.
                return None
            else:
                # a branch reference, use the existing BranchReference logic.
                return response[1]
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def _get_tree_branch(self):
        """See BzrDir._get_tree_branch()."""
        return None, self.open_branch()

    def open_branch(self, _unsupported=False):
        if _unsupported:
            raise NotImplementedError('unsupported flag support not implemented yet.')
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
        verb = 'BzrDir.find_repositoryV2'
        try:
            try:
                response = self._client.call(verb, path)
            except errors.UnknownSmartMethod:
                verb = 'BzrDir.find_repository'
                response = self._client.call(verb, path)
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err)
        if response[0] != 'ok':
            raise errors.UnexpectedSmartServerResponse(response)
        if verb == 'BzrDir.find_repository':
            # servers that don't support the V2 method don't support external
            # references either.
            response = response + ('no', )
        if not (len(response) == 5):
            raise SmartProtocolError('incorrect response length %s' % (response,))
        if response[1] == '':
            format = RemoteRepositoryFormat()
            format.rich_root_data = (response[2] == 'yes')
            format.supports_tree_reference = (response[3] == 'yes')
            # No wire format to check this yet.
            format.supports_external_lookups = (response[4] == 'yes')
            # Used to support creating a real format instance when needed.
            format._creating_bzrdir = self
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

    def clone(self, url, revision_id=None, force_new_repo=False,
              preserve_stacking=False):
        self._ensure_real()
        return self._real_bzrdir.clone(url, revision_id=revision_id,
            force_new_repo=force_new_repo, preserve_stacking=preserve_stacking)

    def get_config(self):
        self._ensure_real()
        return self._real_bzrdir.get_config()


class RemoteRepositoryFormat(repository.RepositoryFormat):
    """Format for repositories accessed over a _SmartClient.

    Instances of this repository are represented by RemoteRepository
    instances.

    The RemoteRepositoryFormat is parameterized during construction
    to reflect the capabilities of the real, remote format. Specifically
    the attributes rich_root_data and supports_tree_reference are set
    on a per instance basis, and are not set (and should not be) at
    the class level.
    """

    _matchingbzrdir = RemoteBzrDirFormat()

    def initialize(self, a_bzrdir, shared=False):
        if not isinstance(a_bzrdir, RemoteBzrDir):
            prior_repo = self._creating_bzrdir.open_repository()
            prior_repo._ensure_real()
            return prior_repo._real_repository._format.initialize(
                a_bzrdir, shared=shared)
        return a_bzrdir.create_repository(shared=shared)
    
    def open(self, a_bzrdir):
        if not isinstance(a_bzrdir, RemoteBzrDir):
            raise AssertionError('%r is not a RemoteBzrDir' % (a_bzrdir,))
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
            self._client = remote_bzrdir._client
        else:
            self._client = _client
        self._format = format
        self._lock_mode = None
        self._lock_token = None
        self._lock_count = 0
        self._leave_lock = False
        # A cache of looked up revision parent data; reset at unlock time.
        self._parents_map = None
        if 'hpss' in debug.debug_flags:
            self._requested_parents = None
        # For tests:
        # These depend on the actual remote format, so force them off for
        # maximum compatibility. XXX: In future these should depend on the
        # remote repository instance, but this is irrelevant until we perform
        # reconcile via an RPC call.
        self._reconcile_does_inventory_gc = False
        self._reconcile_fixes_text_parents = False
        self._reconcile_backsup_inventory = False
        self.base = self.bzrdir.transport.base
        # Additional places to query for data.
        self._fallback_repositories = []

    def __str__(self):
        return "%s(%s)" % (self.__class__.__name__, self.base)

    __repr__ = __str__

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

    def _translate_error(self, err, **context):
        self.bzrdir._translate_error(err, repository=self, **context)

    def find_text_key_references(self):
        """Find the text key references within the repository.

        :return: a dictionary mapping (file_id, revision_id) tuples to altered file-ids to an iterable of
        revision_ids. Each altered file-ids has the exact revision_ids that
        altered it listed explicitly.
        :return: A dictionary mapping text keys ((fileid, revision_id) tuples)
            to whether they were referred to by the inventory of the
            revision_id that they contain. The inventory texts from all present
            revision ids are assessed to generate this report.
        """
        self._ensure_real()
        return self._real_repository.find_text_key_references()

    def _generate_text_key_index(self):
        """Generate a new text key index for the repository.

        This is an expensive function that will take considerable time to run.

        :return: A dict mapping (file_id, revision_id) tuples to a list of
            parents, also (file_id, revision_id) tuples.
        """
        self._ensure_real()
        return self._real_repository._generate_text_key_index()

    @symbol_versioning.deprecated_method(symbol_versioning.one_four)
    def get_revision_graph(self, revision_id=None):
        """See Repository.get_revision_graph()."""
        return self._get_revision_graph(revision_id)

    def _get_revision_graph(self, revision_id):
        """Private method for using with old (< 1.2) servers to fallback."""
        if revision_id is None:
            revision_id = ''
        elif revision.is_null(revision_id):
            return {}

        path = self.bzrdir._path_for_remote_call(self._client)
        try:
            response = self._client.call_expecting_body(
                'Repository.get_revision_graph', path, revision_id)
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err)
        response_tuple, response_handler = response
        if response_tuple[0] != 'ok':
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        coded = response_handler.read_body_bytes()
        if coded == '':
            # no revisions in this repository!
            return {}
        lines = coded.split('\n')
        revision_graph = {}
        for line in lines:
            d = tuple(line.split())
            revision_graph[d[0]] = d[1:]
            
        return revision_graph

    def has_revision(self, revision_id):
        """See Repository.has_revision()."""
        if revision_id == NULL_REVISION:
            # The null revision is always present.
            return True
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call(
            'Repository.has_revision', path, revision_id)
        if response[0] not in ('yes', 'no'):
            raise errors.UnexpectedSmartServerResponse(response)
        return response[0] == 'yes'

    def has_revisions(self, revision_ids):
        """See Repository.has_revisions()."""
        result = set()
        for revision_id in revision_ids:
            if self.has_revision(revision_id):
                result.add(revision_id)
        return result

    def has_same_location(self, other):
        return (self.__class__ == other.__class__ and
                self.bzrdir.transport.base == other.bzrdir.transport.base)
        
    def get_graph(self, other_repository=None):
        """Return the graph for this repository format"""
        parents_provider = self
        if (other_repository is not None and
            other_repository.bzrdir.transport.base !=
            self.bzrdir.transport.base):
            parents_provider = graph._StackedParentsProvider(
                [parents_provider, other_repository._make_parents_provider()])
        return graph.Graph(parents_provider)

    def gather_stats(self, revid=None, committers=None):
        """See Repository.gather_stats()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        # revid can be None to indicate no revisions, not just NULL_REVISION
        if revid is None or revision.is_null(revid):
            fmt_revid = ''
        else:
            fmt_revid = revid
        if committers is None or not committers:
            fmt_committers = 'no'
        else:
            fmt_committers = 'yes'
        response_tuple, response_handler = self._client.call_expecting_body(
            'Repository.gather_stats', path, fmt_revid, fmt_committers)
        if response_tuple[0] != 'ok':
            raise errors.UnexpectedSmartServerResponse(response_tuple)

        body = response_handler.read_body_bytes()
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

    def find_branches(self, using=False):
        """See Repository.find_branches()."""
        # should be an API call to the server.
        self._ensure_real()
        return self._real_repository.find_branches(using=using)

    def get_physical_lock_status(self):
        """See Repository.get_physical_lock_status()."""
        # should be an API call to the server.
        self._ensure_real()
        return self._real_repository.get_physical_lock_status()

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
        if response[0] not in ('yes', 'no'):
            raise SmartProtocolError('unexpected response code %s' % (response,))
        return response[0] == 'yes'

    def is_write_locked(self):
        return self._lock_mode == 'w'

    def lock_read(self):
        # wrong eventually - want a local lock cache context
        if not self._lock_mode:
            self._lock_mode = 'r'
            self._lock_count = 1
            self._parents_map = {}
            if 'hpss' in debug.debug_flags:
                self._requested_parents = set()
            if self._real_repository is not None:
                self._real_repository.lock_read()
        else:
            self._lock_count += 1

    def _remote_lock_write(self, token):
        path = self.bzrdir._path_for_remote_call(self._client)
        if token is None:
            token = ''
        try:
            response = self._client.call('Repository.lock_write', path, token)
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err, token=token)

        if response[0] == 'ok':
            ok, token = response
            return token
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def lock_write(self, token=None):
        if not self._lock_mode:
            self._lock_token = self._remote_lock_write(token)
            # if self._lock_token is None, then this is something like packs or
            # svn where we don't get to lock the repo, or a weave style repository
            # where we cannot lock it over the wire and attempts to do so will
            # fail.
            if self._real_repository is not None:
                self._real_repository.lock_write(token=self._lock_token)
            if token is not None:
                self._leave_lock = True
            else:
                self._leave_lock = False
            self._lock_mode = 'w'
            self._lock_count = 1
            self._parents_map = {}
            if 'hpss' in debug.debug_flags:
                self._requested_parents = set()
        elif self._lock_mode == 'r':
            raise errors.ReadOnlyError(self)
        else:
            self._lock_count += 1
        return self._lock_token or None

    def leave_lock_in_place(self):
        if not self._lock_token:
            raise NotImplementedError(self.leave_lock_in_place)
        self._leave_lock = True

    def dont_leave_lock_in_place(self):
        if not self._lock_token:
            raise NotImplementedError(self.dont_leave_lock_in_place)
        self._leave_lock = False

    def _set_real_repository(self, repository):
        """Set the _real_repository for this repository.

        :param repository: The repository to fallback to for non-hpss
            implemented operations.
        """
        if isinstance(repository, RemoteRepository):
            raise AssertionError()
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
        if not token:
            # with no token the remote repository is not persistently locked.
            return
        try:
            response = self._client.call('Repository.unlock', path, token)
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err, token=token)
        if response == ('ok',):
            return
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def unlock(self):
        self._lock_count -= 1
        if self._lock_count > 0:
            return
        self._parents_map = None
        if 'hpss' in debug.debug_flags:
            self._requested_parents = None
        old_mode = self._lock_mode
        self._lock_mode = None
        try:
            # The real repository is responsible at present for raising an
            # exception if it's in an unfinished write group.  However, it
            # normally will *not* actually remove the lock from disk - that's
            # done by the server on receiving the Repository.unlock call.
            # This is just to let the _real_repository stay up to date.
            if self._real_repository is not None:
                self._real_repository.unlock()
        finally:
            # The rpc-level lock should be released even if there was a
            # problem releasing the vfs-based lock.
            if old_mode == 'w':
                # Only write-locked repositories need to make a remote method
                # call to perfom the unlock.
                old_token = self._lock_token
                self._lock_token = None
                if not self._leave_lock:
                    self._unlock(old_token)

    def break_lock(self):
        # should hand off to the network
        self._ensure_real()
        return self._real_repository.break_lock()

    def _get_tarball(self, compression):
        """Return a TemporaryFile containing a repository tarball.
        
        Returns None if the server does not support sending tarballs.
        """
        import tempfile
        path = self.bzrdir._path_for_remote_call(self._client)
        try:
            response, protocol = self._client.call_expecting_body(
                'Repository.tarball', path, compression)
        except errors.UnknownSmartMethod:
            protocol.cancel_read_body()
            return None
        if response[0] == 'ok':
            # Extract the tarball and return it
            t = tempfile.NamedTemporaryFile()
            # TODO: rpc layer should read directly into it...
            t.write(protocol.read_body_bytes())
            t.seek(0)
            return t
        raise errors.UnexpectedSmartServerResponse(response)

    def sprout(self, to_bzrdir, revision_id=None):
        # TODO: Option to control what format is created?
        self._ensure_real()
        dest_repo = self._real_repository._format.initialize(to_bzrdir,
                                                             shared=False)
        dest_repo.fetch(self, revision_id=revision_id)
        return dest_repo

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
        return builder

    def add_fallback_repository(self, repository):
        """Add a repository to use for looking up data not held locally.
        
        :param repository: A repository.
        """
        if not self._format.supports_external_lookups:
            raise errors.UnstackableRepositoryFormat(self._format, self.base)
        # We need to accumulate additional repositories here, to pass them in
        # on various RPC's.
        self._fallback_repositories.append(repository)

    def add_inventory(self, revid, inv, parents):
        self._ensure_real()
        return self._real_repository.add_inventory(revid, inv, parents)

    def add_revision(self, rev_id, rev, inv=None, config=None):
        self._ensure_real()
        return self._real_repository.add_revision(
            rev_id, rev, inv=inv, config=config)

    @needs_read_lock
    def get_inventory(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_inventory(revision_id)

    def iter_inventories(self, revision_ids):
        self._ensure_real()
        return self._real_repository.iter_inventories(revision_ids)

    @needs_read_lock
    def get_revision(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_revision(revision_id)

    def get_transaction(self):
        self._ensure_real()
        return self._real_repository.get_transaction()

    @needs_read_lock
    def clone(self, a_bzrdir, revision_id=None):
        self._ensure_real()
        return self._real_repository.clone(a_bzrdir, revision_id=revision_id)

    def make_working_trees(self):
        """See Repository.make_working_trees"""
        self._ensure_real()
        return self._real_repository.make_working_trees()

    def revision_ids_to_search_result(self, result_set):
        """Convert a set of revision ids to a graph SearchResult."""
        result_parents = set()
        for parents in self.get_graph().get_parent_map(
            result_set).itervalues():
            result_parents.update(parents)
        included_keys = result_set.intersection(result_parents)
        start_keys = result_set.difference(included_keys)
        exclude_keys = result_parents.difference(result_set)
        result = graph.SearchResult(start_keys, exclude_keys,
            len(result_set), result_set)
        return result

    @needs_read_lock
    def search_missing_revision_ids(self, other, revision_id=None, find_ghosts=True):
        """Return the revision ids that other has that this does not.
        
        These are returned in topological order.

        revision_id: only return revision ids included by revision_id.
        """
        return repository.InterRepository.get(
            other, self).search_missing_revision_ids(revision_id, find_ghosts)

    def fetch(self, source, revision_id=None, pb=None):
        if self.has_same_location(source):
            # check that last_revision is in 'from' and then return a
            # no-operation.
            if (revision_id is not None and
                not revision.is_null(revision_id)):
                self.get_revision(revision_id)
            return 0, []
        self._ensure_real()
        return self._real_repository.fetch(
            source, revision_id=revision_id, pb=pb)

    def create_bundle(self, target, base, fileobj, format=None):
        self._ensure_real()
        self._real_repository.create_bundle(target, base, fileobj, format)

    @needs_read_lock
    def get_ancestry(self, revision_id, topo_sorted=True):
        self._ensure_real()
        return self._real_repository.get_ancestry(revision_id, topo_sorted)

    def fileids_altered_by_revision_ids(self, revision_ids):
        self._ensure_real()
        return self._real_repository.fileids_altered_by_revision_ids(revision_ids)

    def _get_versioned_file_checker(self, revisions, revision_versions_cache):
        self._ensure_real()
        return self._real_repository._get_versioned_file_checker(
            revisions, revision_versions_cache)
        
    def iter_files_bytes(self, desired_files):
        """See Repository.iter_file_bytes.
        """
        self._ensure_real()
        return self._real_repository.iter_files_bytes(desired_files)

    @property
    def _fetch_order(self):
        """Decorate the real repository for now.

        In the long term getting this back from the remote repository as part
        of open would be more efficient.
        """
        self._ensure_real()
        return self._real_repository._fetch_order

    @property
    def _fetch_uses_deltas(self):
        """Decorate the real repository for now.

        In the long term getting this back from the remote repository as part
        of open would be more efficient.
        """
        self._ensure_real()
        return self._real_repository._fetch_uses_deltas

    @property
    def _fetch_reconcile(self):
        """Decorate the real repository for now.

        In the long term getting this back from the remote repository as part
        of open would be more efficient.
        """
        self._ensure_real()
        return self._real_repository._fetch_reconcile

    def get_parent_map(self, keys):
        """See bzrlib.Graph.get_parent_map()."""
        # Hack to build up the caching logic.
        ancestry = self._parents_map
        if ancestry is None:
            # Repository is not locked, so there's no cache.
            missing_revisions = set(keys)
            ancestry = {}
        else:
            missing_revisions = set(key for key in keys if key not in ancestry)
        if missing_revisions:
            parent_map = self._get_parent_map(missing_revisions)
            if 'hpss' in debug.debug_flags:
                mutter('retransmitted revisions: %d of %d',
                        len(set(ancestry).intersection(parent_map)),
                        len(parent_map))
            ancestry.update(parent_map)
        present_keys = [k for k in keys if k in ancestry]
        if 'hpss' in debug.debug_flags:
            if self._requested_parents is not None and len(ancestry) != 0:
                self._requested_parents.update(present_keys)
                mutter('Current RemoteRepository graph hit rate: %d%%',
                    100.0 * len(self._requested_parents) / len(ancestry))
        return dict((k, ancestry[k]) for k in present_keys)

    def _get_parent_map(self, keys):
        """Helper for get_parent_map that performs the RPC."""
        medium = self._client._medium
        if medium._is_remote_before((1, 2)):
            # We already found out that the server can't understand
            # Repository.get_parent_map requests, so just fetch the whole
            # graph.
            # XXX: Note that this will issue a deprecation warning. This is ok
            # :- its because we're working with a deprecated server anyway, and
            # the user will almost certainly have seen a warning about the
            # server version already.
            rg = self.get_revision_graph()
            # There is an api discrepency between get_parent_map and
            # get_revision_graph. Specifically, a "key:()" pair in
            # get_revision_graph just means a node has no parents. For
            # "get_parent_map" it means the node is a ghost. So fix up the
            # graph to correct this.
            #   https://bugs.launchpad.net/bzr/+bug/214894
            # There is one other "bug" which is that ghosts in
            # get_revision_graph() are not returned at all. But we won't worry
            # about that for now.
            for node_id, parent_ids in rg.iteritems():
                if parent_ids == ():
                    rg[node_id] = (NULL_REVISION,)
            rg[NULL_REVISION] = ()
            return rg

        keys = set(keys)
        if None in keys:
            raise ValueError('get_parent_map(None) is not valid')
        if NULL_REVISION in keys:
            keys.discard(NULL_REVISION)
            found_parents = {NULL_REVISION:()}
            if not keys:
                return found_parents
        else:
            found_parents = {}
        # TODO(Needs analysis): We could assume that the keys being requested
        # from get_parent_map are in a breadth first search, so typically they
        # will all be depth N from some common parent, and we don't have to
        # have the server iterate from the root parent, but rather from the
        # keys we're searching; and just tell the server the keyspace we
        # already have; but this may be more traffic again.

        # Transform self._parents_map into a search request recipe.
        # TODO: Manage this incrementally to avoid covering the same path
        # repeatedly. (The server will have to on each request, but the less
        # work done the better).
        parents_map = self._parents_map
        if parents_map is None:
            # Repository is not locked, so there's no cache.
            parents_map = {}
        start_set = set(parents_map)
        result_parents = set()
        for parents in parents_map.itervalues():
            result_parents.update(parents)
        stop_keys = result_parents.difference(start_set)
        included_keys = start_set.intersection(result_parents)
        start_set.difference_update(included_keys)
        recipe = (start_set, stop_keys, len(parents_map))
        body = self._serialise_search_recipe(recipe)
        path = self.bzrdir._path_for_remote_call(self._client)
        for key in keys:
            if type(key) is not str:
                raise ValueError(
                    "key %r not a plain string" % (key,))
        verb = 'Repository.get_parent_map'
        args = (path,) + tuple(keys)
        try:
            response = self._client.call_with_body_bytes_expecting_body(
                verb, args, self._serialise_search_recipe(recipe))
        except errors.UnknownSmartMethod:
            # Server does not support this method, so get the whole graph.
            # Worse, we have to force a disconnection, because the server now
            # doesn't realise it has a body on the wire to consume, so the
            # only way to recover is to abandon the connection.
            warning(
                'Server is too old for fast get_parent_map, reconnecting.  '
                '(Upgrade the server to Bazaar 1.2 to avoid this)')
            medium.disconnect()
            # To avoid having to disconnect repeatedly, we keep track of the
            # fact the server doesn't understand remote methods added in 1.2.
            medium._remember_remote_is_before((1, 2))
            return self.get_revision_graph(None)
        response_tuple, response_handler = response
        if response_tuple[0] not in ['ok']:
            response_handler.cancel_read_body()
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        if response_tuple[0] == 'ok':
            coded = bz2.decompress(response_handler.read_body_bytes())
            if coded == '':
                # no revisions found
                return {}
            lines = coded.split('\n')
            revision_graph = {}
            for line in lines:
                d = tuple(line.split())
                if len(d) > 1:
                    revision_graph[d[0]] = d[1:]
                else:
                    # No parents - so give the Graph result (NULL_REVISION,).
                    revision_graph[d[0]] = (NULL_REVISION,)
            return revision_graph

    @needs_read_lock
    def get_signature_text(self, revision_id):
        self._ensure_real()
        return self._real_repository.get_signature_text(revision_id)

    @needs_read_lock
    @symbol_versioning.deprecated_method(symbol_versioning.one_three)
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
    def check(self, revision_ids=None):
        self._ensure_real()
        return self._real_repository.check(revision_ids=revision_ids)

    def copy_content_into(self, destination, revision_id=None):
        self._ensure_real()
        return self._real_repository.copy_content_into(
            destination, revision_id=revision_id)

    def _copy_repository_tarball(self, to_bzrdir, revision_id=None):
        # get a tarball of the remote repository, and copy from that into the
        # destination
        from bzrlib import osutils
        import tarfile
        import tempfile
        # TODO: Maybe a progress bar while streaming the tarball?
        note("Copying repository content as tarball...")
        tar_file = self._get_tarball('bz2')
        if tar_file is None:
            return None
        destination = to_bzrdir.create_repository()
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
        return destination
        # TODO: Suggestion from john: using external tar is much faster than
        # python's tarfile library, but it may not work on windows.

    @property
    def inventories(self):
        """Decorate the real repository for now.

        In the long term a full blown network facility is needed to
        avoid creating a real repository object locally.
        """
        self._ensure_real()
        return self._real_repository.inventories

    @needs_write_lock
    def pack(self):
        """Compress the data within the repository.

        This is not currently implemented within the smart server.
        """
        self._ensure_real()
        return self._real_repository.pack()

    @property
    def revisions(self):
        """Decorate the real repository for now.

        In the short term this should become a real object to intercept graph
        lookups.

        In the long term a full blown network facility is needed.
        """
        self._ensure_real()
        return self._real_repository.revisions

    def set_make_working_trees(self, new_value):
        self._ensure_real()
        self._real_repository.set_make_working_trees(new_value)

    @property
    def signatures(self):
        """Decorate the real repository for now.

        In the long term a full blown network facility is needed to avoid
        creating a real repository object locally.
        """
        self._ensure_real()
        return self._real_repository.signatures

    @needs_write_lock
    def sign_revision(self, revision_id, gpg_strategy):
        self._ensure_real()
        return self._real_repository.sign_revision(revision_id, gpg_strategy)

    @property
    def texts(self):
        """Decorate the real repository for now.

        In the long term a full blown network facility is needed to avoid
        creating a real repository object locally.
        """
        self._ensure_real()
        return self._real_repository.texts

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

    def add_signature_text(self, revision_id, signature):
        self._ensure_real()
        return self._real_repository.add_signature_text(revision_id, signature)

    def has_signature_for_revision_id(self, revision_id):
        self._ensure_real()
        return self._real_repository.has_signature_for_revision_id(revision_id)

    def item_keys_introduced_by(self, revision_ids, _files_pb=None):
        self._ensure_real()
        return self._real_repository.item_keys_introduced_by(revision_ids,
            _files_pb=_files_pb)

    def revision_graph_can_have_wrong_parents(self):
        # The answer depends on the remote repo format.
        self._ensure_real()
        return self._real_repository.revision_graph_can_have_wrong_parents()

    def _find_inconsistent_revision_parents(self):
        self._ensure_real()
        return self._real_repository._find_inconsistent_revision_parents()

    def _check_for_inconsistent_revision_parents(self):
        self._ensure_real()
        return self._real_repository._check_for_inconsistent_revision_parents()

    def _make_parents_provider(self):
        return self

    def _serialise_search_recipe(self, recipe):
        """Serialise a graph search recipe.

        :param recipe: A search recipe (start, stop, count).
        :return: Serialised bytes.
        """
        start_keys = ' '.join(recipe[0])
        stop_keys = ' '.join(recipe[1])
        count = str(recipe[2])
        return '\n'.join((start_keys, stop_keys, count))


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


class RemoteBranchFormat(branch.BranchFormat):

    def __eq__(self, other):
        return (isinstance(other, RemoteBranchFormat) and 
            self.__dict__ == other.__dict__)

    def get_format_description(self):
        return 'Remote BZR Branch'

    def get_format_string(self):
        return 'Remote BZR Branch'

    def open(self, a_bzrdir):
        return a_bzrdir.open_branch()

    def initialize(self, a_bzrdir):
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
        self._revision_id_to_revno_cache = None
        self._revision_history_cache = None
        self._last_revision_info_cache = None
        self.bzrdir = remote_bzrdir
        if _client is not None:
            self._client = _client
        else:
            self._client = remote_bzrdir._client
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
        self._repo_lock_token = None
        self._lock_count = 0
        self._leave_lock = False

    def _get_real_transport(self):
        # if we try vfs access, return the real branch's vfs transport
        self._ensure_real()
        return self._real_branch._transport

    _transport = property(_get_real_transport)

    def __str__(self):
        return "%s(%s)" % (self.__class__.__name__, self.base)

    __repr__ = __str__

    def _ensure_real(self):
        """Ensure that there is a _real_branch set.

        Used before calls to self._real_branch.
        """
        if self._real_branch is None:
            if not vfs.vfs_enabled():
                raise AssertionError('smart server vfs must be enabled '
                    'to use vfs implementation')
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

    def _translate_error(self, err, **context):
        self.repository._translate_error(err, branch=self, **context)

    def _clear_cached_state(self):
        super(RemoteBranch, self)._clear_cached_state()
        if self._real_branch is not None:
            self._real_branch._clear_cached_state()

    def _clear_cached_state_of_remote_branch_only(self):
        """Like _clear_cached_state, but doesn't clear the cache of
        self._real_branch.

        This is useful when falling back to calling a method of
        self._real_branch that changes state.  In that case the underlying
        branch changes, so we need to invalidate this RemoteBranch's cache of
        it.  However, there's no need to invalidate the _real_branch's cache
        too, in fact doing so might harm performance.
        """
        super(RemoteBranch, self)._clear_cached_state()
        
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

    def get_stacked_on_url(self):
        """Get the URL this branch is stacked against.

        :raises NotStacked: If the branch is not stacked.
        :raises UnstackableBranchFormat: If the branch does not support
            stacking.
        :raises UnstackableRepositoryFormat: If the repository does not support
            stacking.
        """
        self._ensure_real()
        return self._real_branch.get_stacked_on_url()

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
        try:
            response = self._client.call(
                'Branch.lock_write', path, branch_token, repo_token or '')
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err, token=token)
        if response[0] != 'ok':
            raise errors.UnexpectedSmartServerResponse(response)
        ok, branch_token, repo_token = response
        return branch_token, repo_token
            
    def lock_write(self, token=None):
        if not self._lock_mode:
            remote_tokens = self._remote_lock_write(token)
            self._lock_token, self._repo_lock_token = remote_tokens
            if not self._lock_token:
                raise SmartProtocolError('Remote server did not return a token!')
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
        return self._lock_token or None

    def _unlock(self, branch_token, repo_token):
        path = self.bzrdir._path_for_remote_call(self._client)
        try:
            response = self._client.call('Branch.unlock', path, branch_token,
                                         repo_token or '')
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err, token=str((branch_token, repo_token)))
        if response == ('ok',):
            return
        raise errors.UnexpectedSmartServerResponse(response)

    def unlock(self):
        self._lock_count -= 1
        if not self._lock_count:
            self._clear_cached_state()
            mode = self._lock_mode
            self._lock_mode = None
            if self._real_branch is not None:
                if (not self._leave_lock and mode == 'w' and
                    self._repo_lock_token):
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
            if not self._lock_token:
                raise AssertionError('Locked, but no token!')
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
        if not self._lock_token:
            raise NotImplementedError(self.leave_lock_in_place)
        self._leave_lock = True

    def dont_leave_lock_in_place(self):
        if not self._lock_token:
            raise NotImplementedError(self.dont_leave_lock_in_place)
        self._leave_lock = False

    def _last_revision_info(self):
        path = self.bzrdir._path_for_remote_call(self._client)
        response = self._client.call('Branch.last_revision_info', path)
        if response[0] != 'ok':
            raise SmartProtocolError('unexpected response code %s' % (response,))
        revno = int(response[1])
        last_revision = response[2]
        return (revno, last_revision)

    def _gen_revision_history(self):
        """See Branch._gen_revision_history()."""
        path = self.bzrdir._path_for_remote_call(self._client)
        response_tuple, response_handler = self._client.call_expecting_body(
            'Branch.revision_history', path)
        if response_tuple[0] != 'ok':
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        result = response_handler.read_body_bytes().split('\x00')
        if result == ['']:
            return []
        return result

    def _set_last_revision_descendant(self, revision_id, other_branch,
            allow_diverged=False, allow_overwrite_descendant=False):
        path = self.bzrdir._path_for_remote_call(self._client)
        try:
            response = self._client.call('Branch.set_last_revision_ex',
                path, self._lock_token, self._repo_lock_token, revision_id,
                int(allow_diverged), int(allow_overwrite_descendant))
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err, other_branch=other_branch)
        self._clear_cached_state()
        if len(response) != 3 and response[0] != 'ok':
            raise errors.UnexpectedSmartServerResponse(response)
        new_revno, new_revision_id = response[1:]
        self._last_revision_info_cache = new_revno, new_revision_id
        self._real_branch._last_revision_info_cache = new_revno, new_revision_id

    def _set_last_revision(self, revision_id):
        path = self.bzrdir._path_for_remote_call(self._client)
        self._clear_cached_state()
        try:
            response = self._client.call('Branch.set_last_revision',
                path, self._lock_token, self._repo_lock_token, revision_id)
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err)
        if response != ('ok',):
            raise errors.UnexpectedSmartServerResponse(response)

    @needs_write_lock
    def set_revision_history(self, rev_history):
        # Send just the tip revision of the history; the server will generate
        # the full history from that.  If the revision doesn't exist in this
        # branch, NoSuchRevision will be raised.
        if rev_history == []:
            rev_id = 'null:'
        else:
            rev_id = rev_history[-1]
        self._set_last_revision(rev_id)
        self._cache_revision_history(rev_history)

    def get_parent(self):
        self._ensure_real()
        return self._real_branch.get_parent()
        
    def set_parent(self, url):
        self._ensure_real()
        return self._real_branch.set_parent(url)
        
    def set_stacked_on_url(self, stacked_location):
        """Set the URL this branch is stacked against.

        :raises UnstackableBranchFormat: If the branch does not support
            stacking.
        :raises UnstackableRepositoryFormat: If the repository does not support
            stacking.
        """
        self._ensure_real()
        return self._real_branch.set_stacked_on_url(stacked_location)

    def sprout(self, to_bzrdir, revision_id=None):
        # Like Branch.sprout, except that it sprouts a branch in the default
        # format, because RemoteBranches can't be created at arbitrary URLs.
        # XXX: if to_bzrdir is a RemoteBranch, this should perhaps do
        # to_bzrdir.create_branch...
        self._ensure_real()
        result = self._real_branch._format.initialize(to_bzrdir)
        self.copy_content_into(result, revision_id=revision_id)
        result.set_parent(self.bzrdir.root_transport.base)
        return result

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None,
             **kwargs):
        self._clear_cached_state_of_remote_branch_only()
        self._ensure_real()
        return self._real_branch.pull(
            source, overwrite=overwrite, stop_revision=stop_revision,
            _override_hook_target=self, **kwargs)

    @needs_read_lock
    def push(self, target, overwrite=False, stop_revision=None):
        self._ensure_real()
        return self._real_branch.push(
            target, overwrite=overwrite, stop_revision=stop_revision,
            _override_hook_source_branch=self)

    def is_locked(self):
        return self._lock_count >= 1

    @needs_write_lock
    def set_last_revision_info(self, revno, revision_id):
        revision_id = ensure_null(revision_id)
        path = self.bzrdir._path_for_remote_call(self._client)
        try:
            response = self._client.call('Branch.set_last_revision_info',
                path, self._lock_token, self._repo_lock_token, str(revno), revision_id)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            self._clear_cached_state_of_remote_branch_only()
            self._real_branch.set_last_revision_info(revno, revision_id)
            self._last_revision_info_cache = revno, revision_id
            return
        except errors.ErrorFromSmartServer, err:
            self._translate_error(err)
        if response == ('ok',):
            self._clear_cached_state()
            self._last_revision_info_cache = revno, revision_id
            # Update the _real_branch's cache too.
            if self._real_branch is not None:
                cache = self._last_revision_info_cache
                self._real_branch._last_revision_info_cache = cache
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    @needs_write_lock
    def generate_revision_history(self, revision_id, last_rev=None,
                                  other_branch=None):
        medium = self._client._medium
        if not medium._is_remote_before((1, 6)):
            try:
                self._set_last_revision_descendant(revision_id, other_branch,
                    allow_diverged=True, allow_overwrite_descendant=True)
                return
            except errors.UnknownSmartMethod:
                medium._remember_remote_is_before((1, 6))
        self._clear_cached_state_of_remote_branch_only()
        self._ensure_real()
        self._real_branch.generate_revision_history(
            revision_id, last_rev=last_rev, other_branch=other_branch)

    @property
    def tags(self):
        self._ensure_real()
        return self._real_branch.tags

    def set_push_location(self, location):
        self._ensure_real()
        return self._real_branch.set_push_location(location)

    @needs_write_lock
    def update_revisions(self, other, stop_revision=None, overwrite=False,
                         graph=None):
        """See Branch.update_revisions."""
        other.lock_read()
        try:
            if stop_revision is None:
                stop_revision = other.last_revision()
                if revision.is_null(stop_revision):
                    # if there are no commits, we're done.
                    return
            self.fetch(other, stop_revision)

            if overwrite:
                # Just unconditionally set the new revision.  We don't care if
                # the branches have diverged.
                self._set_last_revision(stop_revision)
            else:
                medium = self._client._medium
                if not medium._is_remote_before((1, 6)):
                    try:
                        self._set_last_revision_descendant(stop_revision, other)
                        return
                    except errors.UnknownSmartMethod:
                        medium._remember_remote_is_before((1, 6))
                # Fallback for pre-1.6 servers: check for divergence
                # client-side, then do _set_last_revision.
                last_rev = revision.ensure_null(self.last_revision())
                if graph is None:
                    graph = self.repository.get_graph()
                if self._check_if_descendant_or_diverged(
                        stop_revision, last_rev, graph, other):
                    # stop_revision is a descendant of last_rev, but we aren't
                    # overwriting, so we're done.
                    return
                self._set_last_revision(stop_revision)
        finally:
            other.unlock()


def _extract_tar(tar, to_dir):
    """Extract all the contents of a tarfile object.

    A replacement for extractall, which is not present in python2.4
    """
    for tarinfo in tar:
        tar.extract(tarinfo, to_dir)


def _translate_error(err, **context):
    """Translate an ErrorFromSmartServer into a more useful error.

    Possible context keys:
      - branch
      - repository
      - bzrdir
      - token
      - other_branch
    """
    def find(name):
        try:
            return context[name]
        except KeyError, keyErr:
            mutter('Missing key %r in context %r', keyErr.args[0], context)
            raise err
    if err.error_verb == 'NoSuchRevision':
        raise NoSuchRevision(find('branch'), err.error_args[0])
    elif err.error_verb == 'nosuchrevision':
        raise NoSuchRevision(find('repository'), err.error_args[0])
    elif err.error_tuple == ('nobranch',):
        raise errors.NotBranchError(path=find('bzrdir').root_transport.base)
    elif err.error_verb == 'norepository':
        raise errors.NoRepositoryPresent(find('bzrdir'))
    elif err.error_verb == 'LockContention':
        raise errors.LockContention('(remote lock)')
    elif err.error_verb == 'UnlockableTransport':
        raise errors.UnlockableTransport(find('bzrdir').root_transport)
    elif err.error_verb == 'LockFailed':
        raise errors.LockFailed(err.error_args[0], err.error_args[1])
    elif err.error_verb == 'TokenMismatch':
        raise errors.TokenMismatch(find('token'), '(remote token)')
    elif err.error_verb == 'Diverged':
        raise errors.DivergedBranches(find('branch'), find('other_branch'))
    elif err.error_verb == 'TipChangeRejected':
        raise errors.TipChangeRejected(err.error_args[0].decode('utf8'))
    raise

