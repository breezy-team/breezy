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
from bzrlib.knit import KnitVersionedFiles, _KndxIndex, _KnitKeyAccess
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
from bzrlib.versionedfile import ConstantMapper, HashEscapedPrefixMapper


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


class _KnitsParentsProvider(object):

    def __init__(self, knit, prefix=()):
        """Create a parent provider for string keys mapped to tuple keys."""
        self._knit = knit
        self._prefix = prefix

    def __repr__(self):
        return 'KnitsParentsProvider(%r)' % self._knit

    def get_parent_map(self, keys):
        """See graph._StackedParentsProvider.get_parent_map"""
        parent_map = self._knit.get_parent_map(
            [self._prefix + (key,) for key in keys])
        result = {}
        for key, parents in parent_map.items():
            revid = key[-1]
            if len(parents) == 0:
                parents = (_mod_revision.NULL_REVISION,)
            else:
                parents = tuple(parent[-1] for parent in parents)
            result[revid] = parents
        for revision_id in keys:
            if revision_id == _mod_revision.NULL_REVISION:
                result[revision_id] = ()
        return result


class KnitRepository(MetaDirRepository):
    """Knit format repository."""

    # These attributes are inherited from the Repository base class. Setting
    # them to None ensures that if the constructor is changed to not initialize
    # them, or a subclass fails to call the constructor, that an error will
    # occur rather than the system working but generating incorrect data.
    _commit_builder_class = None
    _serializer = None

    def __init__(self, _format, a_bzrdir, control_files, _commit_builder_class,
        _serializer):
        MetaDirRepository.__init__(self, _format, a_bzrdir, control_files)
        self._commit_builder_class = _commit_builder_class
        self._serializer = _serializer
        self._reconcile_fixes_text_parents = True
        self._fetch_uses_deltas = True
        self._fetch_order = 'topological'

    @needs_read_lock
    def _all_revision_ids(self):
        """See Repository.all_revision_ids()."""
        return [key[0] for key in self.revisions.keys()]

    def _activate_new_inventory(self):
        """Put a replacement inventory.new into use as inventories."""
        # Copy the content across
        t = self._transport
        t.copy('inventory.new.kndx', 'inventory.kndx')
        try:
            t.copy('inventory.new.knit', 'inventory.knit')
        except errors.NoSuchFile:
            # empty inventories knit
            t.delete('inventory.knit')
        # delete the temp inventory
        t.delete('inventory.new.kndx')
        try:
            t.delete('inventory.new.knit')
        except errors.NoSuchFile:
            # empty inventories knit
            pass
        # Force index reload (sanity check)
        self.inventories._index._reset_cache()
        self.inventories.keys()

    def _backup_inventory(self):
        t = self._transport
        t.copy('inventory.kndx', 'inventory.backup.kndx')
        t.copy('inventory.knit', 'inventory.backup.knit')

    def _move_file_id(self, from_id, to_id):
        t = self._transport.clone('knits')
        from_rel_url = self.texts._index._mapper.map((from_id, None))
        to_rel_url = self.texts._index._mapper.map((to_id, None))
        # We expect both files to always exist in this case.
        for suffix in ('.knit', '.kndx'):
            t.rename(from_rel_url + suffix, to_rel_url + suffix)

    def _remove_file_id(self, file_id):
        t = self._transport.clone('knits')
        rel_url = self.texts._index._mapper.map((file_id, None))
        for suffix in ('.kndx', '.knit'):
            try:
                t.delete(rel_url + suffix)
            except errors.NoSuchFile:
                pass

    def _temp_inventories(self):
        result = self._format._get_inventories(self._transport, self,
            'inventory.new')
        # Reconciling when the output has no revisions would result in no
        # writes - but we want to ensure there is an inventory for
        # compatibility with older clients that don't lazy-load.
        result.get_parent_map([('A',)])
        return result

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
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        revision_id = osutils.safe_revision_id(revision_id)
        return self.get_revision_reconcile(revision_id)

    @needs_write_lock
    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from bzrlib.reconcile import KnitReconciler
        reconciler = KnitReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler
    
    def _make_parents_provider(self):
        return _KnitsParentsProvider(self.revisions)

    def _find_inconsistent_revision_parents(self):
        """Find revisions with different parent lists in the revision object
        and in the index graph.

        :returns: an iterator yielding tuples of (revison-id, parents-in-index,
            parents-in-revision).
        """
        if not self.is_locked():
            raise AssertionError()
        vf = self.revisions
        for index_version in vf.keys():
            parent_map = vf.get_parent_map([index_version])
            parents_according_to_index = tuple(parent[-1] for parent in
                parent_map[index_version])
            revision = self.get_revision(index_version[-1])
            parents_according_to_revision = tuple(revision.parent_ids)
            if parents_according_to_index != parents_according_to_revision:
                yield (index_version[-1], parents_according_to_index,
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

    def _get_inventories(self, repo_transport, repo, name='inventory'):
        mapper = ConstantMapper(name)
        index = _KndxIndex(repo_transport, mapper, repo.get_transaction,
            repo.is_write_locked, repo.is_locked)
        access = _KnitKeyAccess(repo_transport, mapper)
        return KnitVersionedFiles(index, access, annotated=False)

    def _get_revisions(self, repo_transport, repo):
        mapper = ConstantMapper('revisions')
        index = _KndxIndex(repo_transport, mapper, repo.get_transaction,
            repo.is_write_locked, repo.is_locked)
        access = _KnitKeyAccess(repo_transport, mapper)
        return KnitVersionedFiles(index, access, max_delta_chain=0,
            annotated=False)

    def _get_signatures(self, repo_transport, repo):
        mapper = ConstantMapper('signatures')
        index = _KndxIndex(repo_transport, mapper, repo.get_transaction,
            repo.is_write_locked, repo.is_locked)
        access = _KnitKeyAccess(repo_transport, mapper)
        return KnitVersionedFiles(index, access, max_delta_chain=0,
            annotated=False)

    def _get_texts(self, repo_transport, repo):
        mapper = HashEscapedPrefixMapper()
        base_transport = repo_transport.clone('knits')
        index = _KndxIndex(base_transport, mapper, repo.get_transaction,
            repo.is_write_locked, repo.is_locked)
        access = _KnitKeyAccess(base_transport, mapper)
        return KnitVersionedFiles(index, access, max_delta_chain=200,
            annotated=True)

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
        transaction = transactions.WriteTransaction()
        result = self.open(a_bzrdir=a_bzrdir, _found=True)
        result.lock_write()
        # the revision id here is irrelevant: it will not be stored, and cannot
        # already exist, we do this to create files on disk for older clients.
        result.inventories.get_parent_map([('A',)])
        result.revisions.get_parent_map([('A',)])
        result.signatures.get_parent_map([('A',)])
        result.unlock()
        return result

    def open(self, a_bzrdir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().
        
        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            format = RepositoryFormat.find_format(a_bzrdir)
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport,
                                'lock', lockdir.LockDir)
        repo = self.repository_class(_format=self,
                              a_bzrdir=a_bzrdir,
                              control_files=control_files,
                              _commit_builder_class=self._commit_builder_class,
                              _serializer=self._serializer)
        repo.revisions = self._get_revisions(repo_transport, repo)
        repo.signatures = self._get_signatures(repo_transport, repo)
        repo.inventories = self._get_inventories(repo_transport, repo)
        repo.texts = self._get_texts(repo_transport, repo)
        repo._transport = repo_transport
        return repo


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
