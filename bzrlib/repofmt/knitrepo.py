# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    debug,
    )
from bzrlib.store import revision
from bzrlib.store.revision.knit import KnitRevisionStore
""")
from bzrlib import (
    bzrdir,
    deprecated_graph,
    errors,
    knit,
    lockable_files,
    lockdir,
    osutils,
    symbol_versioning,
    transactions,
    xml5,
    xml6,
    xml7,
    )

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.repository import (
    CommitBuilder,
    MetaDirRepository,
    MetaDirRepositoryFormat,
    RepositoryFormat,
    RootCommitBuilder,
    )
import bzrlib.revision as _mod_revision
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.trace import mutter, mutter_callsite
from bzrlib.util import bencode


class _KnitParentsProvider(object):

    def __init__(self, knit):
        self._knit = knit

    def __repr__(self):
        return 'KnitParentsProvider(%r)' % self._knit

    @symbol_versioning.deprecated_method(symbol_versioning.one_one)
    def get_parents(self, revision_ids):
        """See graph._StackedParentsProvider.get_parents"""
        parent_map = self.get_parent_map(revision_ids)
        return [parent_map.get(r, None) for r in revision_ids]

    def get_parent_map(self, keys):
        """See graph._StackedParentsProvider.get_parent_map"""
        parent_map = {}
        for revision_id in keys:
            if revision_id is None:
                raise ValueError('get_parent_map(None) is not valid')
            if revision_id == _mod_revision.NULL_REVISION:
                parent_map[revision_id] = ()
            else:
                try:
                    parents = tuple(
                        self._knit.get_parents_with_ghosts(revision_id))
                except errors.RevisionNotPresent:
                    continue
                else:
                    if len(parents) == 0:
                        parents = (_mod_revision.NULL_REVISION,)
                parent_map[revision_id] = parents
        return parent_map


class KnitRepository(MetaDirRepository):
    """Knit format repository."""

    # These attributes are inherited from the Repository base class. Setting
    # them to None ensures that if the constructor is changed to not initialize
    # them, or a subclass fails to call the constructor, that an error will
    # occur rather than the system working but generating incorrect data.
    _commit_builder_class = None
    _serializer = None

    def __init__(self, _format, a_bzrdir, control_files, _revision_store,
        control_store, text_store, _commit_builder_class, _serializer):
        MetaDirRepository.__init__(self, _format, a_bzrdir, control_files,
            _revision_store, control_store, text_store)
        self._commit_builder_class = _commit_builder_class
        self._serializer = _serializer
        self._reconcile_fixes_text_parents = True
        control_store.get_scope = self.get_transaction
        text_store.get_scope = self.get_transaction
        _revision_store.get_scope = self.get_transaction

    def _warn_if_deprecated(self):
        # This class isn't deprecated
        pass

    def _inventory_add_lines(self, inv_vf, revid, parents, lines, check_content):
        return inv_vf.add_lines_with_ghosts(revid, parents, lines,
            check_content=check_content)[0]

    @needs_read_lock
    def _all_revision_ids(self):
        """See Repository.all_revision_ids()."""
        # Knits get the revision graph from the index of the revision knit, so
        # it's always possible even if they're on an unlistable transport.
        return self._revision_store.all_revision_ids(self.get_transaction())

    def fileid_involved_between_revs(self, from_revid, to_revid):
        """Find file_id(s) which are involved in the changes between revisions.

        This determines the set of revisions which are involved, and then
        finds all file ids affected by those revisions.
        """
        vf = self._get_revision_vf()
        from_set = set(vf.get_ancestry(from_revid))
        to_set = set(vf.get_ancestry(to_revid))
        changed = to_set.difference(from_set)
        return self._fileid_involved_by_set(changed)

    def fileid_involved(self, last_revid=None):
        """Find all file_ids modified in the ancestry of last_revid.

        :param last_revid: If None, last_revision() will be used.
        """
        if not last_revid:
            changed = set(self.all_revision_ids())
        else:
            changed = set(self.get_ancestry(last_revid))
        if None in changed:
            changed.remove(None)
        return self._fileid_involved_by_set(changed)

    @needs_read_lock
    def get_ancestry(self, revision_id, topo_sorted=True):
        """Return a list of revision-ids integrated by a revision.
        
        This is topologically sorted, unless 'topo_sorted' is specified as
        False.
        """
        if _mod_revision.is_null(revision_id):
            return [None]
        vf = self._get_revision_vf()
        try:
            return [None] + vf.get_ancestry(revision_id, topo_sorted)
        except errors.RevisionNotPresent:
            raise errors.NoSuchRevision(self, revision_id)

    @symbol_versioning.deprecated_method(symbol_versioning.one_two)
    @needs_read_lock
    def get_data_stream(self, revision_ids):
        """See Repository.get_data_stream.
        
        Deprecated in 1.2 for get_data_stream_for_search.
        """
        search_result = self.revision_ids_to_search_result(set(revision_ids))
        return self.get_data_stream_for_search(search_result)

    @needs_read_lock
    def get_data_stream_for_search(self, search):
        """See Repository.get_data_stream_for_search."""
        item_keys = self.item_keys_introduced_by(search.get_keys())
        for knit_kind, file_id, versions in item_keys:
            name = (knit_kind,)
            if knit_kind == 'file':
                name = ('file', file_id)
                knit = self.weave_store.get_weave_or_empty(
                    file_id, self.get_transaction())
            elif knit_kind == 'inventory':
                knit = self.get_inventory_weave()
            elif knit_kind == 'revisions':
                knit = self._revision_store.get_revision_file(
                    self.get_transaction())
            elif knit_kind == 'signatures':
                knit = self._revision_store.get_signature_file(
                    self.get_transaction())
            else:
                raise AssertionError('Unknown knit kind %r' % (knit_kind,))
            yield name, _get_stream_as_bytes(knit, versions)

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        revision_id = osutils.safe_revision_id(revision_id)
        return self.get_revision_reconcile(revision_id)

    @symbol_versioning.deprecated_method(symbol_versioning.one_four)
    @needs_read_lock
    def get_revision_graph(self, revision_id=None):
        """Return a dictionary containing the revision graph.

        :param revision_id: The revision_id to get a graph from. If None, then
        the entire revision graph is returned. This is a deprecated mode of
        operation and will be removed in the future.
        :return: a dictionary of revision_id->revision_parents_list.
        """
        if 'evil' in debug.debug_flags:
            mutter_callsite(3,
                "get_revision_graph scales with size of history.")
        # special case NULL_REVISION
        if revision_id == _mod_revision.NULL_REVISION:
            return {}
        a_weave = self._get_revision_vf()
        if revision_id is None:
            return a_weave.get_graph()
        if revision_id not in a_weave:
            raise errors.NoSuchRevision(self, revision_id)
        else:
            # add what can be reached from revision_id
            return a_weave.get_graph([revision_id])

    @needs_read_lock
    @symbol_versioning.deprecated_method(symbol_versioning.one_three)
    def get_revision_graph_with_ghosts(self, revision_ids=None):
        """Return a graph of the revisions with ghosts marked as applicable.

        :param revision_ids: an iterable of revisions to graph or None for all.
        :return: a Graph object with the graph reachable from revision_ids.
        """
        if 'evil' in debug.debug_flags:
            mutter_callsite(3,
                "get_revision_graph_with_ghosts scales with size of history.")
        result = deprecated_graph.Graph()
        vf = self._get_revision_vf()
        versions = set(vf.versions())
        if not revision_ids:
            pending = set(self.all_revision_ids())
            required = set([])
        else:
            pending = set(revision_ids)
            # special case NULL_REVISION
            if _mod_revision.NULL_REVISION in pending:
                pending.remove(_mod_revision.NULL_REVISION)
            required = set(pending)
        done = set([])
        while len(pending):
            revision_id = pending.pop()
            if not revision_id in versions:
                if revision_id in required:
                    raise errors.NoSuchRevision(self, revision_id)
                # a ghost
                result.add_ghost(revision_id)
                # mark it as done so we don't try for it again.
                done.add(revision_id)
                continue
            parent_ids = vf.get_parents_with_ghosts(revision_id)
            for parent_id in parent_ids:
                # is this queued or done ?
                if (parent_id not in pending and
                    parent_id not in done):
                    # no, queue it.
                    pending.add(parent_id)
            result.add_node(revision_id, parent_ids)
            done.add(revision_id)
        return result

    def _get_revision_vf(self):
        """:return: a versioned file containing the revisions."""
        vf = self._revision_store.get_revision_file(self.get_transaction())
        return vf

    def has_revisions(self, revision_ids):
        """See Repository.has_revisions()."""
        result = set()
        transaction = self.get_transaction()
        for revision_id in revision_ids:
            if self._revision_store.has_revision_id(revision_id, transaction):
                result.add(revision_id)
        return result

    @needs_write_lock
    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from bzrlib.reconcile import KnitReconciler
        reconciler = KnitReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler
    
    def revision_parents(self, revision_id):
        return self._get_revision_vf().get_parents(revision_id)

    def _make_parents_provider(self):
        return _KnitParentsProvider(self._get_revision_vf())

    def _find_inconsistent_revision_parents(self):
        """Find revisions with different parent lists in the revision object
        and in the index graph.

        :returns: an iterator yielding tuples of (revison-id, parents-in-index,
            parents-in-revision).
        """
        assert self.is_locked()
        vf = self._get_revision_vf()
        for index_version in vf.versions():
            parents_according_to_index = tuple(vf.get_parents_with_ghosts(
                index_version))
            revision = self.get_revision(index_version)
            parents_according_to_revision = tuple(revision.parent_ids)
            if parents_according_to_index != parents_according_to_revision:
                yield (index_version, parents_according_to_index,
                    parents_according_to_revision)

    def _check_for_inconsistent_revision_parents(self):
        inconsistencies = list(self._find_inconsistent_revision_parents())
        if inconsistencies:
            raise errors.BzrCheckError(
                "Revision knit has inconsistent parents.")

    def revision_graph_can_have_wrong_parents(self):
        # The revision.kndx could potentially claim a revision has a different
        # parent to the revision text.
        return True


class RepositoryFormatKnit(MetaDirRepositoryFormat):
    """Bzr repository knit format (generalized). 

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
    """

    # Set this attribute in derived classes to control the repository class
    # created by open and initialize.
    repository_class = None
    # Set this attribute in derived classes to control the
    # _commit_builder_class that the repository objects will have passed to
    # their constructor.
    _commit_builder_class = None
    # Set this attribute in derived clases to control the _serializer that the
    # repository objects will have passed to their constructor.
    _serializer = xml5.serializer_v5
    # Knit based repositories handle ghosts reasonably well.
    supports_ghosts = True
    # External lookups are not supported in this format.
    supports_external_lookups = False

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        return VersionedFileStore(
            repo_transport,
            prefixed=False,
            file_mode=control_files._file_mode,
            versionedfile_class=knit.make_file_knit,
            versionedfile_kwargs={'factory':knit.KnitPlainFactory()},
            )

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        versioned_file_store = VersionedFileStore(
            repo_transport,
            file_mode=control_files._file_mode,
            prefixed=False,
            precious=True,
            versionedfile_class=knit.make_file_knit,
            versionedfile_kwargs={'delta':False,
                                  'factory':knit.KnitPlainFactory(),
                                 },
            escaped=True,
            )
        return KnitRevisionStore(versioned_file_store)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('knits',
                                  transport,
                                  control_files,
                                  versionedfile_class=knit.make_file_knit,
                                  versionedfile_kwargs={
                                      'create_parent_dir':True,
                                      'delay_create':True,
                                      'dir_mode':control_files._dir_mode,
                                  },
                                  escaped=True)

    def initialize(self, a_bzrdir, shared=False):
        """Create a knit format 1 repository.

        :param a_bzrdir: bzrdir to contain the new repository; must already
            be initialized.
        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['knits']
        files = []
        utf8_files = [('format', self.get_format_string())]
        
        self._upload_blank_content(a_bzrdir, dirs, files, utf8_files, shared)
        repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport,
                                'lock', lockdir.LockDir)
        control_store = self._get_control_store(repo_transport, control_files)
        transaction = transactions.WriteTransaction()
        # trigger a write of the inventory store.
        control_store.get_weave_or_empty('inventory', transaction)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        # the revision id here is irrelevant: it will not be stored, and cannot
        # already exist.
        _revision_store.has_revision_id('A', transaction)
        _revision_store.get_signature_file(transaction)
        return self.open(a_bzrdir=a_bzrdir, _found=True)

    def open(self, a_bzrdir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().
        
        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            format = RepositoryFormat.find_format(a_bzrdir)
            assert format.__class__ ==  self.__class__
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport,
                                'lock', lockdir.LockDir)
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return self.repository_class(_format=self,
                              a_bzrdir=a_bzrdir,
                              control_files=control_files,
                              _revision_store=_revision_store,
                              control_store=control_store,
                              text_store=text_store,
                              _commit_builder_class=self._commit_builder_class,
                              _serializer=self._serializer)


class RepositoryFormatKnit1(RepositoryFormatKnit):
    """Bzr repository knit format 1.

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock

    This format was introduced in bzr 0.8.
    """

    repository_class = KnitRepository
    _commit_builder_class = CommitBuilder
    _serializer = xml5.serializer_v5

    def __ne__(self, other):
        return self.__class__ is not other.__class__

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar-NG Knit Repository Format 1"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 1"

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormatKnit3(RepositoryFormatKnit):
    """Bzr repository knit format 3.

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
     - support for recording full info about the tree root
     - support for recording tree-references
    """

    repository_class = KnitRepository
    _commit_builder_class = RootCommitBuilder
    rich_root_data = True
    supports_tree_reference = True
    _serializer = xml7.serializer_v7

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('dirstate-with-subtree')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)
        if not getattr(target_format, 'supports_tree_reference', False):
            raise errors.BadConversionTarget(
                'Does not support nested trees', target_format)
            
    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar Knit Repository Format 3 (bzr 0.15)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 3"


class RepositoryFormatKnit4(RepositoryFormatKnit):
    """Bzr repository knit format 4.

    This repository format has everything in format 3, except for
    tree-references:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
     - support for recording full info about the tree root
    """

    repository_class = KnitRepository
    _commit_builder_class = RootCommitBuilder
    rich_root_data = True
    supports_tree_reference = False
    _serializer = xml6.serializer_v6

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('rich-root')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return 'Bazaar Knit Repository Format 4 (bzr 1.0)\n'

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 4"


def _get_stream_as_bytes(knit, required_versions):
    """Generate a serialised data stream.

    The format is a bencoding of a list.  The first element of the list is a
    string of the format signature, then each subsequent element is a list
    corresponding to a record.  Those lists contain:

      * a version id
      * a list of options
      * a list of parents
      * the bytes

    :returns: a bencoded list.
    """
    knit_stream = knit.get_data_stream(required_versions)
    format_signature, data_list, callable = knit_stream
    data = []
    data.append(format_signature)
    for version, options, length, parents in data_list:
        data.append([version, options, parents, callable(length)])
    return bencode.bencode(data)
