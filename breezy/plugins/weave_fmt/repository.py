# Copyright (C) 2007-2011 Canonical Ltd
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

"""Deprecated weave-based repository formats.

Weave based formats scaled linearly with history size and could not represent
ghosts.
"""

import contextlib
import gzip
import os
from io import BytesIO

from ...lazy_import import lazy_import

lazy_import(
    globals(),
    """
import itertools

from breezy import (
    ui,
    )
from vcsgraph import (
    graph as _mod_graph,
    known_graph as _mod_known_graph,
)
""",
)
from ... import debug, errors, lockdir, osutils, trace, urlutils
from ... import transport as _mod_transport
from ...bzr import lockable_files, tuned_gzip, versionedfile, weave, weavefile
from ...bzr.repository import RepositoryFormatMetaDir
from ...bzr.versionedfile import (
    AbsentContentFactory,
    FulltextContentFactory,
    VersionedFiles,
)
from ...bzr.vf_repository import (
    InterSameDataRepository,
    MetaDirVersionedFileRepository,
    MetaDirVersionedFileRepositoryFormat,
    VersionedFileCommitBuilder,
    VersionedFileRepository,
    VersionedFileRepositoryFormat,
)
from ...repository import InterRepository
from . import bzrdir as weave_bzrdir
from .store.text import TextStore


class AllInOneRepository(VersionedFileRepository):
    """Legacy support - the repository behaviour for all-in-one branches."""

    @property
    def _revision_serializer(self):
        from ...bzr.xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from ...bzr.xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    def _escape(self, file_or_path):
        """Escape a file or path for use in a URL.

        Args:
            file_or_path: Either a string path or a list of path components.

        Returns:
            URL-escaped string representation of the path.
        """
        if not isinstance(file_or_path, str):
            file_or_path = "/".join(file_or_path)
        if file_or_path == "":
            return ""
        return urlutils.escape(osutils.safe_unicode(file_or_path))

    def __init__(self, _format, a_controldir):
        """Initialize an all-in-one repository.

        Args:
            _format: The repository format.
            a_controldir: The control directory containing this repository.
        """
        # we reuse one control files instance.
        dir_mode = a_controldir._get_dir_mode()
        file_mode = a_controldir._get_file_mode()

        def get_store(name, compressed=True, prefixed=False):
            # FIXME: This approach of assuming stores are all entirely compressed
            # or entirely uncompressed is tidy, but breaks upgrade from
            # some existing branches where there's a mixture; we probably
            # still want the option to look for both.
            relpath = self._escape(name)
            store = TextStore(
                a_controldir.transport.clone(relpath),
                prefixed=prefixed,
                compressed=compressed,
                dir_mode=dir_mode,
                file_mode=file_mode,
            )
            return store

        # not broken out yet because the controlweaves|inventory_store
        # and texts bits are still different.
        if isinstance(_format, RepositoryFormat4):
            # cannot remove these - there is still no consistent api
            # which allows access to this old info.
            self.inventory_store = get_store("inventory-store")
            self._text_store = get_store("text-store")
        super().__init__(_format, a_controldir, a_controldir._control_files)

    def _all_possible_ids(self):
        """Return all the possible revisions that we could find."""
        if debug.debug_flag_enabled("evil"):
            trace.mutter_callsite(3, "_all_possible_ids scales with size of history.")
        with self.lock_read():
            return [key[-1] for key in self.inventories.keys()]

    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        These are in as much topological order as the underlying store can
        present: for weaves ghosts may lead to a lack of correctness until
        the reweave updates the parents list.
        """
        with self.lock_read():
            return [key[-1] for key in self.revisions.keys()]

    def _activate_new_inventory(self):
        """Put a replacement inventory.new into use as inventories.

        This method copies the new inventory weave file over the existing one
        and validates that the new weave can be parsed correctly.
        """
        # Copy the content across
        t = self.controldir._control_files._transport
        t.copy("inventory.new.weave", "inventory.weave")
        # delete the temp inventory
        t.delete("inventory.new.weave")
        # Check we can parse the new weave properly as a sanity check
        self.inventories.keys()

    def _backup_inventory(self):
        """Create a backup copy of the current inventory weave.

        The backup is stored as 'inventory.backup.weave' in the control files
        transport.
        """
        t = self.controldir._control_files._transport
        t.copy("inventory.weave", "inventory.backup.weave")

    def _temp_inventories(self):
        """Get a temporary inventory weave for modifications.

        Returns:
            A new inventory weave that can be modified without affecting the
            main inventory.
        """
        t = self.controldir._control_files._transport
        return self._format._get_inventories(t, self, "inventory.new")

    def get_commit_builder(
        self,
        branch,
        parents,
        config,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
    ):
        """Obtain a CommitBuilder for this repository.

        Args:
            branch: The branch being committed to.
            parents: List of parent revision IDs.
            config: Configuration to use for the commit.
            timestamp: Optional timestamp for the commit.
            timezone: Optional timezone for the commit.
            committer: Optional committer identity.
            revprops: Optional revision properties.
            revision_id: Optional specific revision ID to use.
            lossy: Whether to allow lossy conversion.

        Returns:
            A VersionedFileCommitBuilder instance.
        """
        self._check_ascii_revisionid(revision_id, self.get_commit_builder)
        result = VersionedFileCommitBuilder(
            self,
            parents,
            config,
            timestamp,
            timezone,
            committer,
            revprops,
            revision_id,
            lossy=lossy,
        )
        self.start_write_group()
        return result

    def _inventory_add_lines(self, revision_id, parents, lines, check_content=True):
        """Store lines in inv_vf and return the sha1 of the inventory.

        Args:
            revision_id: The revision ID for this inventory.
            parents: Parent revision IDs.
            lines: The inventory lines to store.
            check_content: Whether to check content validity.

        Returns:
            The SHA1 hash of the stored inventory.
        """
        present_parents = self.get_graph().get_parent_map(parents)
        final_parents = []
        for parent in parents:
            if parent in present_parents:
                final_parents.append((parent,))
        return self.inventories.add_lines(
            (revision_id,), final_parents, lines, check_content=check_content
        )[0]

    def is_shared(self):
        """Check if this repository is shared.

        Returns:
            bool: Always False, as all-in-one repositories cannot be shared.
        """
        return False

    def set_make_working_trees(self, new_value):
        """Set the policy flag for making working trees when creating branches.

        This only applies to branches that use this repository.

        Args:
            new_value: True to restore the default, False to disable making
                      working trees.

        Raises:
            RepositoryUpgradeRequired: Always raised as this format doesn't
                                      support this operation.
        """
        raise errors.RepositoryUpgradeRequired(self.user_url)

    def make_working_trees(self):
        """Check if working trees should be created for new branches.

        Returns:
            bool: Always True for this format.
        """
        return True


class WeaveMetaDirRepository(MetaDirVersionedFileRepository):
    """A subclass of MetaDirRepository to set weave specific policy."""

    def __init__(self, _format, a_controldir, control_files):
        """Initialize a weave meta-directory repository.

        Args:
            _format: The repository format.
            a_controldir: The control directory containing this repository.
            control_files: The lockable files instance for this repository.
        """
        super().__init__(_format, a_controldir, control_files)
        self._revision_serializer = _format._revision_serializer
        self._inventory_serializer = _format._inventory_serializer

    def _all_possible_ids(self):
        """Return all the possible revisions that we could find."""
        if debug.debug_flag_enabled("evil"):
            trace.mutter_callsite(3, "_all_possible_ids scales with size of history.")
        with self.lock_read():
            return [key[-1] for key in self.inventories.keys()]

    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        These are in as much topological order as the underlying store can
        present: for weaves ghosts may lead to a lack of correctness until
        the reweave updates the parents list.
        """
        with self.lock_read():
            return [key[-1] for key in self.revisions.keys()]

    def _activate_new_inventory(self):
        """Put a replacement inventory.new into use as inventories.

        This method copies the new inventory weave file over the existing one
        and validates that the new weave can be parsed correctly.
        """
        # Copy the content across
        t = self._transport
        t.copy("inventory.new.weave", "inventory.weave")
        # delete the temp inventory
        t.delete("inventory.new.weave")
        # Check we can parse the new weave properly as a sanity check
        self.inventories.keys()

    def _backup_inventory(self):
        """Create a backup copy of the current inventory weave.

        The backup is stored as 'inventory.backup.weave' in the transport.
        """
        t = self._transport
        t.copy("inventory.weave", "inventory.backup.weave")

    def _temp_inventories(self):
        """Get a temporary inventory weave for modifications.

        Returns:
            A new inventory weave that can be modified without affecting the
            main inventory.
        """
        t = self._transport
        return self._format._get_inventories(t, self, "inventory.new")

    def get_commit_builder(
        self,
        branch,
        parents,
        config,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
    ):
        """Obtain a CommitBuilder for this repository.

        Args:
            branch: The branch being committed to.
            parents: List of parent revision IDs.
            config: Configuration to use for the commit.
            timestamp: Optional timestamp for the commit.
            timezone: Optional timezone for the commit.
            committer: Optional committer identity.
            revprops: Optional revision properties.
            revision_id: Optional specific revision ID to use.
            lossy: Whether to allow lossy conversion.

        Returns:
            A VersionedFileCommitBuilder instance.
        """
        self._check_ascii_revisionid(revision_id, self.get_commit_builder)
        result = VersionedFileCommitBuilder(
            self,
            parents,
            config,
            timestamp,
            timezone,
            committer,
            revprops,
            revision_id,
            lossy=lossy,
        )
        self.start_write_group()
        return result

    def get_revision(self, revision_id):
        """Return the Revision object for a named revision."""
        with self.lock_read():
            return self.get_revision_reconcile(revision_id)

    def _inventory_add_lines(self, revision_id, parents, lines, check_content=True):
        """Store lines in inv_vf and return the sha1 of the inventory.

        Args:
            revision_id: The revision ID for this inventory.
            parents: Parent revision IDs.
            lines: The inventory lines to store.
            check_content: Whether to check content validity.

        Returns:
            The SHA1 hash of the stored inventory.
        """
        present_parents = self.get_graph().get_parent_map(parents)
        final_parents = []
        for parent in parents:
            if parent in present_parents:
                final_parents.append((parent,))
        return self.inventories.add_lines(
            (revision_id,), final_parents, lines, check_content=check_content
        )[0]


class PreSplitOutRepositoryFormat(VersionedFileRepositoryFormat):
    """Base class for the pre split out repository formats."""

    rich_root_data = False
    supports_tree_reference = False
    supports_ghosts = False
    supports_external_lookups = False
    supports_chks = False
    supports_nesting_repositories = True
    _fetch_order = "topological"
    _fetch_reconcile = True
    fast_deltas = False
    supports_leaving_lock = False
    supports_overriding_transport = False
    # XXX: This is an old format that we don't support full checking on, so
    # just claim that checking for this inconsistency is not required.
    revision_graph_can_have_wrong_parents = False

    def initialize(self, a_controldir, shared=False, _internal=False):
        """Create a weave repository."""
        if shared:
            raise errors.IncompatibleFormat(self, a_controldir._format)

        if not _internal:
            # always initialized when the bzrdir is.
            return self.open(a_controldir, _found=True)

        # Create an empty weave
        sio = BytesIO()
        weavefile.write_weave_v5(weave.Weave(), sio)
        empty_weave = sio.getvalue()

        trace.mutter("creating repository in %s.", a_controldir.transport.base)

        # FIXME: RBC 20060125 don't peek under the covers
        # NB: no need to escape relative paths that are url safe.
        control_files = lockable_files.LockableFiles(
            a_controldir.transport, "branch-lock", lockable_files.TransportLock
        )
        control_files.create_lock()
        control_files.lock_write()
        transport = a_controldir.transport
        try:
            transport.mkdir("revision-store", mode=a_controldir._get_dir_mode())
            transport.mkdir("weaves", mode=a_controldir._get_dir_mode())
            transport.put_bytes_non_atomic(
                "inventory.weave", empty_weave, mode=a_controldir._get_file_mode()
            )
        finally:
            control_files.unlock()
        repository = self.open(a_controldir, _found=True)
        self._run_post_repo_init_hooks(repository, a_controldir, shared)
        return repository

    def open(self, a_controldir, _found=False):
        """See RepositoryFormat.open()."""
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError

        repo_transport = a_controldir.get_repository_transport(None)
        result = AllInOneRepository(_format=self, a_controldir=a_controldir)
        result.revisions = self._get_revisions(repo_transport, result)
        result.signatures = self._get_signatures(repo_transport, result)
        result.inventories = self._get_inventories(repo_transport, result)
        result.texts = self._get_texts(repo_transport, result)
        result.chk_bytes = None
        return result

    def is_deprecated(self):
        """Check if this format is deprecated.

        Returns:
            bool: Always True, as all pre-split-out formats are deprecated.
        """
        return True


class RepositoryFormat4(PreSplitOutRepositoryFormat):
    """Bzr repository format 4.

    This repository format has:
     - flat stores
     - TextStores for texts, inventories,revisions.

    This format is deprecated: it indexes texts using a text id which is
    removed in format 5; initialization and write support for this format
    has been removed.
    """

    supports_funky_characters = False

    _matchingcontroldir = weave_bzrdir.BzrDirFormat4()

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Repository format 4"

    def initialize(self, url, shared=False, _internal=False):
        """Format 4 branches cannot be created."""
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Format 4 is not supported.

        It is not supported because the model changed from 4 to 5 and the
        conversion logic is expensive - so doing it on the fly was not
        feasible.
        """
        return False

    def _get_inventories(self, repo_transport, repo, name="inventory"):
        # No inventories store written so far.
        return None

    def _get_revisions(self, repo_transport, repo):
        from .xml4 import revision_serializer_v4

        return RevisionTextStore(
            repo_transport.clone("revision-store"),
            revision_serializer_v4,
            True,
            versionedfile.PrefixMapper(),
            repo.is_locked,
            repo.is_write_locked,
        )

    def _get_signatures(self, repo_transport, repo):
        return SignatureTextStore(
            repo_transport.clone("revision-store"),
            False,
            versionedfile.PrefixMapper(),
            repo.is_locked,
            repo.is_write_locked,
        )

    def _get_texts(self, repo_transport, repo):
        return None


class RepositoryFormat5(PreSplitOutRepositoryFormat):
    """Bzr control format 5.

    This repository format has:
     - weaves for file texts and inventory
     - flat stores
     - TextStores for revisions and signatures.
    """

    _versionedfile_class = weave.WeaveFile
    _matchingcontroldir = weave_bzrdir.BzrDirFormat5()
    supports_funky_characters = False

    @property
    def _revision_serializer(self):
        from ...bzr.xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from ...bzr.xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 5"

    def network_name(self):
        """The network name for this format is the control dirs disk label."""
        return self._matchingcontroldir.get_format_string()

    def _get_inventories(self, repo_transport, repo, name="inventory"):
        mapper = versionedfile.ConstantMapper(name)
        return versionedfile.ThunkedVersionedFiles(
            repo_transport, weave.WeaveFile, mapper, repo.is_locked
        )

    def _get_revisions(self, repo_transport, repo):
        from ...bzr.xml5 import revision_serializer_v5

        return RevisionTextStore(
            repo_transport.clone("revision-store"),
            revision_serializer_v5,
            False,
            versionedfile.PrefixMapper(),
            repo.is_locked,
            repo.is_write_locked,
        )

    def _get_signatures(self, repo_transport, repo):
        return SignatureTextStore(
            repo_transport.clone("revision-store"),
            False,
            versionedfile.PrefixMapper(),
            repo.is_locked,
            repo.is_write_locked,
        )

    def _get_texts(self, repo_transport, repo):
        mapper = versionedfile.PrefixMapper()
        base_transport = repo_transport.clone("weaves")
        return versionedfile.ThunkedVersionedFiles(
            base_transport, weave.WeaveFile, mapper, repo.is_locked
        )


class RepositoryFormat6(PreSplitOutRepositoryFormat):
    """Bzr control format 6.

    This repository format has:
     - weaves for file texts and inventory
     - hash subdirectory based stores.
     - TextStores for revisions and signatures.
    """

    _versionedfile_class = weave.WeaveFile
    _matchingcontroldir = weave_bzrdir.BzrDirFormat6()
    supports_funky_characters = False

    @property
    def _revision_serializer(self):
        from ...bzr.xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from ...bzr.xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 6"

    def network_name(self):
        """The network name for this format is the control dirs disk label."""
        return self._matchingcontroldir.get_format_string()

    def _get_inventories(self, repo_transport, repo, name="inventory"):
        mapper = versionedfile.ConstantMapper(name)
        return versionedfile.ThunkedVersionedFiles(
            repo_transport, weave.WeaveFile, mapper, repo.is_locked
        )

    def _get_revisions(self, repo_transport, repo):
        from ...bzr.xml5 import revision_serializer_v5

        return RevisionTextStore(
            repo_transport.clone("revision-store"),
            revision_serializer_v5,
            False,
            versionedfile.HashPrefixMapper(),
            repo.is_locked,
            repo.is_write_locked,
        )

    def _get_signatures(self, repo_transport, repo):
        return SignatureTextStore(
            repo_transport.clone("revision-store"),
            False,
            versionedfile.HashPrefixMapper(),
            repo.is_locked,
            repo.is_write_locked,
        )

    def _get_texts(self, repo_transport, repo):
        mapper = versionedfile.HashPrefixMapper()
        base_transport = repo_transport.clone("weaves")
        return versionedfile.ThunkedVersionedFiles(
            base_transport, weave.WeaveFile, mapper, repo.is_locked
        )


class RepositoryFormat7(MetaDirVersionedFileRepositoryFormat):
    """Bzr repository 7.

    This repository format has:
     - weaves for file texts and inventory
     - hash subdirectory based stores.
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
    """

    _versionedfile_class = weave.WeaveFile
    supports_ghosts = False
    supports_chks = False
    supports_funky_characters = False
    revision_graph_can_have_wrong_parents = False

    _fetch_order = "topological"
    _fetch_reconcile = True
    fast_deltas = False

    @property
    def _revision_serializer(self):
        from ...bzr.xml5 import revision_serializer_v5

        return revision_serializer_v5

    @property
    def _inventory_serializer(self):
        from ...bzr.xml5 import inventory_serializer_v5

        return inventory_serializer_v5

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Bazaar-NG Repository format 7"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 7"

    def _get_inventories(self, repo_transport, repo, name="inventory"):
        mapper = versionedfile.ConstantMapper(name)
        return versionedfile.ThunkedVersionedFiles(
            repo_transport, weave.WeaveFile, mapper, repo.is_locked
        )

    def _get_revisions(self, repo_transport, repo):
        from ...bzr.xml5 import revision_serializer_v5

        return RevisionTextStore(
            repo_transport.clone("revision-store"),
            revision_serializer_v5,
            True,
            versionedfile.HashPrefixMapper(),
            repo.is_locked,
            repo.is_write_locked,
        )

    def _get_signatures(self, repo_transport, repo):
        return SignatureTextStore(
            repo_transport.clone("revision-store"),
            True,
            versionedfile.HashPrefixMapper(),
            repo.is_locked,
            repo.is_write_locked,
        )

    def _get_texts(self, repo_transport, repo):
        mapper = versionedfile.HashPrefixMapper()
        base_transport = repo_transport.clone("weaves")
        return versionedfile.ThunkedVersionedFiles(
            base_transport, weave.WeaveFile, mapper, repo.is_locked
        )

    def initialize(self, a_controldir, shared=False):
        """Create a weave repository.

        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        # Create an empty weave
        sio = BytesIO()
        weavefile.write_weave_v5(weave.Weave(), sio)
        empty_weave = sio.getvalue()

        trace.mutter("creating repository in %s.", a_controldir.transport.base)
        dirs = ["revision-store", "weaves"]
        files = [
            ("inventory.weave", BytesIO(empty_weave)),
        ]
        utf8_files = [("format", self.get_format_string())]

        self._upload_blank_content(a_controldir, dirs, files, utf8_files, shared)
        return self.open(a_controldir=a_controldir, _found=True)

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
        result = WeaveMetaDirRepository(
            _format=self, a_controldir=a_controldir, control_files=control_files
        )
        result.revisions = self._get_revisions(repo_transport, result)
        result.signatures = self._get_signatures(repo_transport, result)
        result.inventories = self._get_inventories(repo_transport, result)
        result.texts = self._get_texts(repo_transport, result)
        result.chk_bytes = None
        result._transport = repo_transport
        return result

    def is_deprecated(self):
        """Check if this format is deprecated.

        Returns:
            bool: Always True, as all pre-split-out formats are deprecated.
        """
        return True


class TextVersionedFiles(VersionedFiles):
    """Just-a-bunch-of-files based VersionedFile stores."""

    def __init__(self, transport, compressed, mapper, is_locked, can_write):
        """Initialize a text-based versioned files store.

        Args:
            transport: Transport for accessing the store.
            compressed: Whether files should be gzip compressed.
            mapper: Mapper for converting keys to file paths.
            is_locked: Callable that returns whether the store is locked.
            can_write: Callable that returns whether writing is allowed.
        """
        self._compressed = compressed
        self._transport = transport
        self._mapper = mapper
        if self._compressed:
            self._ext = ".gz"
        else:
            self._ext = ""
        self._is_locked = is_locked
        self._can_write = can_write

    def add_lines(self, key, parents, lines):
        """Add a revision to the store.

        Args:
            key: The key for the content.
            parents: Parent keys (unused in this implementation).
            lines: The lines of content to store.

        Raises:
            ObjectNotLocked: If the store is not locked.
            ReadOnlyError: If the store is read-only.
            ValueError: If the key contains invalid characters.
        """
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        if not self._can_write():
            raise errors.ReadOnlyError(self)
        if b"/" in key[-1]:
            raise ValueError(f"bad idea to put / in {key!r}")
        chunks = lines
        if self._compressed:
            chunks = tuned_gzip.chunks_to_gzip(chunks)
        path = self._map(key)
        self._transport.put_file_non_atomic(
            path, BytesIO(b"".join(chunks)), create_parent_dir=True
        )

    def insert_record_stream(self, stream):
        """Insert records from a stream into the store.

        Args:
            stream: Iterator of records to insert.

        Raises:
            RevisionNotPresent: If a record is marked as absent.
        """
        adapters = {}
        for record in stream:
            # Raise an error when a record is missing.
            if record.storage_kind == "absent":
                raise errors.RevisionNotPresent([record.key[0]], self)
            # adapt to non-tuple interface
            if record.storage_kind in ("fulltext", "chunks", "lines"):
                self.add_lines(record.key, None, record.get_bytes_as("lines"))
            else:
                adapter_key = record.storage_kind, "lines"
                try:
                    adapter = adapters[adapter_key]
                except KeyError:
                    adapter_factory = adapter_registry.get(adapter_key)
                    adapter = adapter_factory(self)
                    adapters[adapter_key] = adapter
                lines = adapter.get_bytes(
                    record, record.get_bytes_as(record.storage_kind)
                )
                with contextlib.suppress(errors.RevisionAlreadyPresent):
                    self.add_lines(record.key, None, lines)

    def _load_text(self, key):
        """Load text content for a given key.

        Args:
            key: The key to load content for.

        Returns:
            The text content, or None if not found.

        Raises:
            ObjectNotLocked: If the store is not locked.
        """
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        path = self._map(key)
        try:
            text = self._transport.get_bytes(path)
            compressed = self._compressed
        except _mod_transport.NoSuchFile:
            if self._compressed:
                # try without the .gz
                path = path[:-3]
                try:
                    text = self._transport.get_bytes(path)
                    compressed = False
                except _mod_transport.NoSuchFile:
                    return None
            else:
                return None
        if compressed:
            text = gzip.GzipFile(mode="rb", fileobj=BytesIO(text)).read()
        return text

    def _map(self, key):
        """Map a key to a file path.

        Args:
            key: The key to map.

        Returns:
            The file path including extension.
        """
        return self._mapper.map(key) + self._ext


class RevisionTextStore(TextVersionedFiles):
    """Legacy thunk for format 4 repositories."""

    def __init__(self, transport, serializer, compressed, mapper, is_locked, can_write):
        """Create a RevisionTextStore at transport with serializer.

        Args:
            transport: Transport for accessing the store.
            serializer: Serializer for revision objects.
            compressed: Whether files should be gzip compressed.
            mapper: Mapper for converting keys to file paths.
            is_locked: Callable that returns whether the store is locked.
            can_write: Callable that returns whether writing is allowed.
        """
        TextVersionedFiles.__init__(
            self, transport, compressed, mapper, is_locked, can_write
        )
        self._revision_serializer = serializer

    def _load_text_parents(self, key):
        """Load text and parent information for a revision.

        Args:
            key: The revision key to load.

        Returns:
            Tuple of (text, parent_keys) or (None, None) if not found.
        """
        text = self._load_text(key)
        if text is None:
            return None, None
        parents = self._revision_serializer.read_revision_from_string(text).parent_ids
        return text, tuple((parent,) for parent in parents)

    def get_parent_map(self, keys):
        """Get a map of keys to their parents.

        Args:
            keys: Iterable of keys to get parents for.

        Returns:
            Dict mapping keys to their parent keys.
        """
        result = {}
        for key in keys:
            parents = self._load_text_parents(key)[1]
            if parents is None:
                continue
            result[key] = parents
        return result

    def get_known_graph_ancestry(self, keys):
        """Get a KnownGraph instance with the ancestry of keys.

        Args:
            keys: Keys to include in the ancestry graph.

        Returns:
            KnownGraph instance containing the ancestry.
        """
        keys = self.keys()
        parent_map = self.get_parent_map(keys)
        kg = _mod_known_graph.KnownGraph(parent_map)
        return kg

    def get_record_stream(self, keys, sort_order, include_delta_closure):
        """Get a stream of records for the given keys.

        Args:
            keys: Keys to get records for.
            sort_order: Ordering for the returned records (ignored).
            include_delta_closure: Whether to include delta closure (ignored).

        Yields:
            ContentFactory instances for each key.
        """
        for key in keys:
            text, parents = self._load_text_parents(key)
            if text is None:
                yield AbsentContentFactory(key)
            else:
                yield FulltextContentFactory(key, parents, None, text)

    def keys(self):
        """Get all keys in the store.

        Returns:
            Set of all keys in the store.

        Raises:
            ObjectNotLocked: If the store is not locked.
        """
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        relpaths = set()
        for quoted_relpath in self._transport.iter_files_recursive():
            relpath = urlutils.unquote(quoted_relpath)
            path, ext = os.path.splitext(relpath)
            if ext == ".gz":
                relpath = path
            if not relpath.endswith(".sig"):
                relpaths.add(relpath)
        paths = list(relpaths)
        return {self._mapper.unmap(path) for path in paths}


class SignatureTextStore(TextVersionedFiles):
    """Legacy thunk for format 4-7 repositories."""

    def __init__(self, transport, compressed, mapper, is_locked, can_write):
        """Initialize a signature text store.

        Args:
            transport: Transport for accessing the store.
            compressed: Whether files should be gzip compressed.
            mapper: Mapper for converting keys to file paths.
            is_locked: Callable that returns whether the store is locked.
            can_write: Callable that returns whether writing is allowed.
        """
        TextVersionedFiles.__init__(
            self, transport, compressed, mapper, is_locked, can_write
        )
        self._ext = ".sig" + self._ext

    def get_parent_map(self, keys):
        """Get a map of keys to their parents.

        Signatures don't have parents, so this returns None for all found keys.

        Args:
            keys: Iterable of keys to check.

        Returns:
            Dict mapping found keys to None.
        """
        result = {}
        for key in keys:
            text = self._load_text(key)
            if text is None:
                continue
            result[key] = None
        return result

    def get_record_stream(self, keys, sort_order, include_delta_closure):
        """Get a stream of signature records for the given keys.

        Args:
            keys: Keys to get records for.
            sort_order: Ordering for the returned records (ignored).
            include_delta_closure: Whether to include delta closure (ignored).

        Yields:
            ContentFactory instances for each key.
        """
        for key in keys:
            text = self._load_text(key)
            if text is None:
                yield AbsentContentFactory(key)
            else:
                yield FulltextContentFactory(key, None, None, text)

    def keys(self):
        """Get all signature keys in the store.

        Returns:
            Set of all signature keys in the store.

        Raises:
            ObjectNotLocked: If the store is not locked.
        """
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        relpaths = set()
        for quoted_relpath in self._transport.iter_files_recursive():
            relpath = urlutils.unquote(quoted_relpath)
            path, ext = os.path.splitext(relpath)
            if ext == ".gz":
                relpath = path
            if not relpath.endswith(".sig"):
                continue
            relpaths.add(relpath[:-4])
        paths = list(relpaths)
        return {self._mapper.unmap(path) for path in paths}


class InterWeaveRepo(InterSameDataRepository):
    """Optimised code paths between Weave based repositories."""

    @classmethod
    def _get_repo_format_to_test(self):
        return RepositoryFormat7()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with known Weave formats.

        We don't test for the stores being of specific types because that
        could lead to confusing results, and there is no need to be
        overly general.
        """
        try:
            return isinstance(
                source._format,
                (RepositoryFormat5, RepositoryFormat6, RepositoryFormat7),
            ) and isinstance(
                target._format,
                (RepositoryFormat5, RepositoryFormat6, RepositoryFormat7),
            )
        except AttributeError:
            return False

    def copy_content(self, revision_id=None):
        """Copy repository content from source to target.

        This is an optimized implementation for weave repositories that
        directly copies the weave files when possible.

        Args:
            revision_id: Optional revision to limit the copy to.
        """
        with self.lock_write():
            # weave specific optimised path:
            with contextlib.suppress(
                errors.RepositoryUpgradeRequired, NotImplementedError
            ):
                self.target.set_make_working_trees(self.source.make_working_trees())
            # FIXME do not peek!
            if self.source._transport.listable():
                with ui.ui_factory.nested_progress_bar() as pb:
                    self.target.texts.insert_record_stream(
                        self.source.texts.get_record_stream(
                            self.source.texts.keys(), "topological", False
                        )
                    )
                    pb.update("Copying inventory", 0, 1)
                    self.target.inventories.insert_record_stream(
                        self.source.inventories.get_record_stream(
                            self.source.inventories.keys(), "topological", False
                        )
                    )
                    self.target.signatures.insert_record_stream(
                        self.source.signatures.get_record_stream(
                            self.source.signatures.keys(), "unordered", True
                        )
                    )
                    self.target.revisions.insert_record_stream(
                        self.source.revisions.get_record_stream(
                            self.source.revisions.keys(), "topological", True
                        )
                    )
            else:
                self.target.fetch(self.source, revision_id=revision_id)

    def search_missing_revision_ids(
        self, find_ghosts=True, revision_ids=None, if_present_ids=None, limit=None
    ):
        """Search for revision IDs missing from the target repository.

        Args:
            find_ghosts: Whether to find ghost revisions.
            revision_ids: Specific revision IDs to check.
            if_present_ids: Only return results if these IDs are present.
            limit: Maximum number of missing revisions to return.

        Returns:
            SearchResult of missing revision IDs.
        """
        with self.lock_read():
            # we want all revisions to satisfy revision_id in source.
            # but we don't want to stat every file here and there.
            # we want then, all revisions other needs to satisfy revision_id
            # checked, but not those that we have locally.
            # so the first thing is to get a subset of the revisions to
            # satisfy revision_id in source, and then eliminate those that
            # we do already have.
            # this is slow on high latency connection to self, but as this
            # disk format scales terribly for push anyway due to rewriting
            # inventory.weave, this is considered acceptable.
            # - RBC 20060209
            source_ids_set = self._present_source_revisions_for(
                revision_ids, if_present_ids
            )
            # source_ids is the worst possible case we may need to pull.
            # now we want to filter source_ids against what we actually
            # have in target, but don't try to check for existence where we
            # know we do not have a revision as that would be pointless.
            target_ids = set(self.target._all_possible_ids())
            possibly_present_revisions = target_ids.intersection(source_ids_set)
            actually_present_revisions = set(
                self.target._eliminate_revisions_not_present(possibly_present_revisions)
            )
            required_revisions = source_ids_set.difference(actually_present_revisions)
            if revision_ids is not None:
                # we used get_ancestry to determine source_ids then we are
                # assured all revisions referenced are present as they are
                # installed in topological order. and the tip revision was
                # validated by get_ancestry.
                result_set = required_revisions
            else:
                # if we just grabbed the possibly available ids, then
                # we only have an estimate of whats available and need to
                # validate that against the revision records.
                result_set = set(
                    self.source._eliminate_revisions_not_present(required_revisions)
                )
            if limit is not None:
                topo_ordered = self.source.get_graph().iter_topo_order(result_set)
                result_set = set(itertools.islice(topo_ordered, limit))
            return self.source.revision_ids_to_search_result(result_set)


InterRepository.register_optimiser(InterWeaveRepo)


def get_extra_interrepo_test_combinations():
    """Get extra test combinations for inter-repository operations.

    Returns:
        List of tuples containing (InterRepository class, source format, target format).
    """
    from ...bzr import knitrepo

    return [(InterRepository, RepositoryFormat5(), knitrepo.RepositoryFormatKnit3())]
