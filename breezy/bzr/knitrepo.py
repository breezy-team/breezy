# Copyright (C) 2007-2010 Canonical Ltd
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

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    transactions,
    )
from breezy.bzr import (
    knit as _mod_knit,
    lockable_files,
    versionedfile,
    )
""",
)
import contextlib

from .. import controldir, errors, lockdir, trace
from .. import revision as _mod_revision
from .. import transport as _mod_transport
from ..repository import InterRepository, IsInWriteGroupError, Repository
from .repository import RepositoryFormatMetaDir
from .serializer import InventorySerializer, RevisionSerializer
from .vf_repository import (
    InterSameDataRepository,
    MetaDirVersionedFileRepository,
    MetaDirVersionedFileRepositoryFormat,
    VersionedFileCommitBuilder,
)


class _KnitParentsProvider:
    def __init__(self, knit):
        self._knit = knit

    def __repr__(self):
        return f"KnitParentsProvider({self._knit!r})"

    def get_parent_map(self, keys):
        """See graph.StackedParentsProvider.get_parent_map."""
        parent_map = {}
        for revision_id in keys:
            if revision_id is None:
                raise ValueError("get_parent_map(None) is not valid")
            if revision_id == _mod_revision.NULL_REVISION:
                parent_map[revision_id] = ()
            else:
                try:
                    parents = tuple(self._knit.get_parents_with_ghosts(revision_id))
                except errors.RevisionNotPresent:
                    continue
                else:
                    if len(parents) == 0:
                        parents = (_mod_revision.NULL_REVISION,)
                parent_map[revision_id] = parents
        return parent_map


class _KnitsParentsProvider:
    def __init__(self, knit, prefix=()):
        """Create a parent provider for string keys mapped to tuple keys."""
        self._knit = knit
        self._prefix = prefix

    def __repr__(self):
        return f"KnitsParentsProvider({self._knit!r})"

    def get_parent_map(self, keys):
        """See graph.StackedParentsProvider.get_parent_map."""
        parent_map = self._knit.get_parent_map([self._prefix + (key,) for key in keys])
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


class KnitRepository(MetaDirVersionedFileRepository):
    """Knit format repository."""

    # These attributes are inherited from the Repository base class. Setting
    # them to None ensures that if the constructor is changed to not initialize
    # them, or a subclass fails to call the constructor, that an error will
    # occur rather than the system working but generating incorrect data.
    _commit_builder_class: type[VersionedFileCommitBuilder]
    _revision_serializer: RevisionSerializer
    _inventory_serializer: InventorySerializer

    def __init__(
        self,
        _format,
        a_controldir,
        control_files,
        _commit_builder_class,
        _revision_serializer,
        _inventory_serializer,
    ):
        super().__init__(_format, a_controldir, control_files)
        self._commit_builder_class = _commit_builder_class
        self._revision_serializer = _revision_serializer
        self._inventory_serializer = _inventory_serializer
        self._reconcile_fixes_text_parents = True

    def _all_revision_ids(self):
        """See Repository.all_revision_ids()."""
        with self.lock_read():
            return [key[0] for key in self.revisions.keys()]

    def _activate_new_inventory(self):
        """Put a replacement inventory.new into use as inventories."""
        # Copy the content across
        t = self._transport
        t.copy("inventory.new.kndx", "inventory.kndx")
        try:
            t.copy("inventory.new.knit", "inventory.knit")
        except _mod_transport.NoSuchFile:
            # empty inventories knit
            t.delete("inventory.knit")
        # delete the temp inventory
        t.delete("inventory.new.kndx")
        try:
            t.delete("inventory.new.knit")
        except _mod_transport.NoSuchFile:
            # empty inventories knit
            pass
        # Force index reload (sanity check)
        self.inventories._index._reset_cache()
        self.inventories.keys()

    def _backup_inventory(self):
        t = self._transport
        t.copy("inventory.kndx", "inventory.backup.kndx")
        t.copy("inventory.knit", "inventory.backup.knit")

    def _move_file_id(self, from_id, to_id):
        t = self._transport.clone("knits")
        from_rel_url = self.texts._index._mapper.map((from_id, None))
        to_rel_url = self.texts._index._mapper.map((to_id, None))
        # We expect both files to always exist in this case.
        for suffix in (".knit", ".kndx"):
            t.rename(from_rel_url + suffix, to_rel_url + suffix)

    def _remove_file_id(self, file_id):
        t = self._transport.clone("knits")
        rel_url = self.texts._index._mapper.map((file_id, None))
        for suffix in (".kndx", ".knit"):
            with contextlib.suppress(_mod_transport.NoSuchFile):
                t.delete(rel_url + suffix)

    def _temp_inventories(self):
        result = self._format._get_inventories(self._transport, self, "inventory.new")
        # Reconciling when the output has no revisions would result in no
        # writes - but we want to ensure there is an inventory for
        # compatibility with older clients that don't lazy-load.
        result.get_parent_map([(b"A",)])
        return result

    def get_revision(self, revision_id):
        """Return the Revision object for a named revision."""
        with self.lock_read():
            return self.get_revision_reconcile(revision_id)

    def _refresh_data(self):
        if not self.is_locked():
            return
        if self.is_in_write_group():
            raise IsInWriteGroupError(self)
        # Create a new transaction to force all knits to see the scope change.
        # This is safe because we're outside a write group.
        self.control_files._finish_transaction()
        if self.is_write_locked():
            self.control_files._set_write_transaction()
        else:
            self.control_files._set_read_transaction()

    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from .reconcile import KnitReconciler

        with self.lock_write():
            reconciler = KnitReconciler(self, thorough=thorough)
            return reconciler.reconcile()

    def _make_parents_provider(self):
        return _KnitsParentsProvider(self.revisions)


class RepositoryFormatKnit(MetaDirVersionedFileRepositoryFormat):
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
    repository_class: type[Repository]
    # Set this attribute in derived classes to control the
    # _commit_builder_class that the repository objects will have passed to
    # their constructor.
    _commit_builder_class: type[VersionedFileCommitBuilder]
    # Set this attribute in derived clases to control the _serializer that the
    # repository objects will have passed to their constructor.

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    # Knit based repositories handle ghosts reasonably well.
    supports_ghosts = True
    # External lookups are not supported in this format.
    supports_external_lookups = False
    # No CHK support.
    supports_chks = False
    _fetch_order = "topological"
    _fetch_uses_deltas = True
    fast_deltas = False
    supports_funky_characters = True
    # The revision.kndx could potentially claim a revision has a different
    # parent to the revision text.
    revision_graph_can_have_wrong_parents = True

    def _get_inventories(self, repo_transport, repo, name="inventory"):
        mapper = versionedfile.ConstantMapper(name)
        index = _mod_knit._KndxIndex(
            repo_transport,
            mapper,
            repo.get_transaction,
            repo.is_write_locked,
            repo.is_locked,
        )
        access = _mod_knit._KnitKeyAccess(repo_transport, mapper)
        return _mod_knit.KnitVersionedFiles(index, access, annotated=False)

    def _get_revisions(self, repo_transport, repo):
        mapper = versionedfile.ConstantMapper("revisions")
        index = _mod_knit._KndxIndex(
            repo_transport,
            mapper,
            repo.get_transaction,
            repo.is_write_locked,
            repo.is_locked,
        )
        access = _mod_knit._KnitKeyAccess(repo_transport, mapper)
        return _mod_knit.KnitVersionedFiles(
            index, access, max_delta_chain=0, annotated=False
        )

    def _get_signatures(self, repo_transport, repo):
        mapper = versionedfile.ConstantMapper("signatures")
        index = _mod_knit._KndxIndex(
            repo_transport,
            mapper,
            repo.get_transaction,
            repo.is_write_locked,
            repo.is_locked,
        )
        access = _mod_knit._KnitKeyAccess(repo_transport, mapper)
        return _mod_knit.KnitVersionedFiles(
            index, access, max_delta_chain=0, annotated=False
        )

    def _get_texts(self, repo_transport, repo):
        mapper = versionedfile.HashEscapedPrefixMapper()
        base_transport = repo_transport.clone("knits")
        index = _mod_knit._KndxIndex(
            base_transport,
            mapper,
            repo.get_transaction,
            repo.is_write_locked,
            repo.is_locked,
        )
        access = _mod_knit._KnitKeyAccess(base_transport, mapper)
        return _mod_knit.KnitVersionedFiles(
            index, access, max_delta_chain=200, annotated=True
        )

    def initialize(self, a_controldir, shared=False):
        """Create a knit format 1 repository.

        :param a_controldir: bzrdir to contain the new repository; must already
            be initialized.
        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        trace.mutter("creating repository in %s.", a_controldir.transport.base)
        dirs = ["knits"]
        files = []
        utf8_files = [("format", self.get_format_string())]

        self._upload_blank_content(a_controldir, dirs, files, utf8_files, shared)
        repo_transport = a_controldir.get_repository_transport(None)
        lockable_files.LockableFiles(repo_transport, "lock", lockdir.LockDir)
        transactions.WriteTransaction()
        result = self.open(a_controldir=a_controldir, _found=True)
        result.lock_write()
        # the revision id here is irrelevant: it will not be stored, and cannot
        # already exist, we do this to create files on disk for older clients.
        result.inventories.get_parent_map([(b"A",)])
        result.revisions.get_parent_map([(b"A",)])
        result.signatures.get_parent_map([(b"A",)])
        result.unlock()
        self._run_post_repo_init_hooks(result, a_controldir, shared)
        return result

    def open(self, a_controldir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().

        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            RepositoryFormatMetaDir.find_format(a_controldir)
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_controldir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(
            repo_transport, "lock", lockdir.LockDir
        )
        repo = self.repository_class(
            _format=self,
            a_controldir=a_controldir,
            control_files=control_files,
            _commit_builder_class=self._commit_builder_class,
            _revision_serializer=self._revision_serializer,
            _inventory_serializer=self._inventory_serializer,
        )
        repo.revisions = self._get_revisions(repo_transport, repo)
        repo.signatures = self._get_signatures(repo_transport, repo)
        repo.inventories = self._get_inventories(repo_transport, repo)
        repo.texts = self._get_texts(repo_transport, repo)
        repo.chk_bytes = None
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
    _commit_builder_class = VersionedFileCommitBuilder

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    def __ne__(self, other):
        return self.__class__ is not other.__class__

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar-NG Knit Repository Format 1"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 1"


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
    _commit_builder_class = VersionedFileCommitBuilder
    rich_root_data = True
    experimental = True
    supports_tree_reference = True

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml7 import inventory_serializer_v7

        return inventory_serializer_v7

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("dirstate-with-subtree")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar Knit Repository Format 3 (bzr 0.15)\n"

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
    _commit_builder_class = VersionedFileCommitBuilder
    rich_root_data = True
    supports_tree_reference = False

    @property
    def _revision_serializer(self):
        from .xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from .xml6 import inventory_serializer_v6

        return inventory_serializer_v6

    def _get_matching_bzrdir(self):
        return controldir.format_registry.make_controldir("rich-root")

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingcontroldir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar Knit Repository Format 4 (bzr 1.0)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 4"


class InterKnitRepo(InterSameDataRepository):
    """Optimised code paths between Knit based repositories."""

    @classmethod
    def _get_repo_format_to_test(cls):
        return RepositoryFormatKnit1()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with known Knit formats.

        We don't test for the stores being of specific types because that
        could lead to confusing results, and there is no need to be
        overly general.
        """
        try:
            are_knits = isinstance(source._format, RepositoryFormatKnit) and isinstance(
                target._format, RepositoryFormatKnit
            )
        except AttributeError:
            return False
        return are_knits and InterRepository._same_model(source, target)

    def search_missing_revision_ids(
        self, find_ghosts=True, revision_ids=None, if_present_ids=None, limit=None
    ):
        """See InterRepository.search_missing_revision_ids()."""
        import itertools

        with self.lock_read():
            source_ids_set = self._present_source_revisions_for(
                revision_ids, if_present_ids
            )
            # source_ids is the worst possible case we may need to pull.
            # now we want to filter source_ids against what we actually
            # have in target, but don't try to check for existence where we know
            # we do not have a revision as that would be pointless.
            target_ids = set(self.target.all_revision_ids())
            possibly_present_revisions = target_ids.intersection(source_ids_set)
            actually_present_revisions = set(
                self.target._eliminate_revisions_not_present(possibly_present_revisions)
            )
            required_revisions = source_ids_set.difference(actually_present_revisions)
            if revision_ids is not None:
                # we used get_ancestry to determine source_ids then we are assured all
                # revisions referenced are present as they are installed in topological order.
                # and the tip revision was validated by get_ancestry.
                result_set = required_revisions
            else:
                # if we just grabbed the possibly available ids, then
                # we only have an estimate of whats available and need to validate
                # that against the revision records.
                result_set = set(
                    self.source._eliminate_revisions_not_present(required_revisions)
                )
            if limit is not None:
                topo_ordered = self.source.get_graph().iter_topo_order(result_set)
                result_set = set(itertools.islice(topo_ordered, limit))
            return self.source.revision_ids_to_search_result(result_set)


InterRepository.register_optimiser(InterKnitRepo)
