"""Bundle serializer for format version 4.

This module implements the version 4 bundle format, which uses bzip2 compression
and multi-parent diffs for efficient storage and transmission of revision data.
The format supports both legacy weave-based repositories and newer formats with
rich root support.
"""

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

import bz2
import contextlib
import re
from io import BytesIO

import fastbencode as bencode

from .... import errors, lru_cache, multiparent, osutils, trace, ui
from .... import repository as _mod_repository
from .... import revision as _mod_revision
from ....i18n import ngettext
from ... import pack, serializer
from ... import versionedfile as _mod_versionedfile
from ...inventory import _make_delta
from .. import bundle_data
from .. import serializer as bundle_serializer


class _MPDiffInventoryGenerator(_mod_versionedfile._MPDiffGenerator):
    """Generate multi-parent diffs for serialized inventories.

    This class extends the base MPDiffGenerator to handle inventory-specific
    diff generation, including SHA1 computation for inventory texts.
    """

    def __init__(self, repo, inventory_keys):
        """Initialize the inventory diff generator.

        Args:
            repo: The repository containing the inventories.
            inventory_keys: List of inventory keys to generate diffs for.
        """
        super().__init__(repo.inventories, inventory_keys)
        self.repo = repo
        self.sha1s = {}

    def iter_diffs(self):
        """Compute the diffs one at a time.

        Yields:
            Tuple[bytes, List[bytes], str, MultiParentDiff]: A tuple containing
                revision_id, parent_ids, sha1, and the computed diff.
        """
        # This is instead of compute_diffs() since we guarantee our ordering of
        # inventories, we don't have to do any buffering
        self._find_needed_keys()
        # We actually use a slightly different ordering. We grab all of the
        # parents first, and then grab the ordered requests.
        needed_ids = [k[-1] for k in self.present_parents]
        needed_ids.extend([k[-1] for k in self.ordered_keys])
        inv_to_lines = self.repo._inventory_serializer.write_inventory_to_chunks
        for inv in self.repo.iter_inventories(needed_ids):
            revision_id = inv.revision_id
            key = (revision_id,)
            if key in self.present_parents:
                # Not a key we will transmit, which is a shame, since because
                # of that bundles don't work with stacked branches
                parent_ids = None
            else:
                parent_ids = [k[-1] for k in self.parent_map[key]]
            as_chunks = inv_to_lines(inv)
            self._process_one_record(key, as_chunks)
            if parent_ids is None:
                continue
            diff = self.diffs.pop(key)
            sha1 = osutils.sha_strings(as_chunks)
            yield revision_id, parent_ids, sha1, diff


class BundleWriter:
    """Writer for bundle-format files.

    This serves roughly the same purpose as ContainerReader, but acts as a
    layer on top of it.

    Provides ways of writing the specific record types supported this bundle
    format.
    """

    def __init__(self, fileobj):
        """Initialize the bundle writer.

        Args:
            fileobj: File-like object to write the bundle to.
        """
        self._container = pack.ContainerWriter(self._write_encoded)
        self._fileobj = fileobj
        self._compressor = bz2.BZ2Compressor()

    def _write_encoded(self, bytes):
        """Write bzip2-encoded bytes to the file.

        Args:
            bytes: Raw bytes to compress and write.
        """
        self._fileobj.write(self._compressor.compress(bytes))

    def begin(self):
        """Start writing the bundle.

        Writes the bundle format header and initializes the container.
        """
        self._fileobj.write(bundle_serializer._get_bundle_header("4"))
        self._fileobj.write(b"#\n")
        self._container.begin()

    def end(self):
        """Finish writing the bundle.

        Finalizes the container and flushes any remaining compressed data.
        """
        self._container.end()
        self._fileobj.write(self._compressor.flush())

    def add_multiparent_record(
        self, mp_bytes, sha1, parents, repo_kind, revision_id, file_id
    ):
        """Add a record for a multi-parent diff.

        Args:
            mp_bytes: A multi-parent diff, as a bytestring.
            sha1: The sha1 hash of the fulltext.
            parents: A list of revision-ids of the parents.
            repo_kind: The kind of object in the repository. May be 'file' or
                'inventory'.
            revision_id: The revision id of the mpdiff being added.
            file_id: The file-id of the file, or None for inventories.
        """
        metadata = {b"parents": parents, b"storage_kind": b"mpdiff", b"sha1": sha1}
        self._add_record(mp_bytes, metadata, repo_kind, revision_id, file_id)

    def add_fulltext_record(self, bytes, parents, repo_kind, revision_id):
        """Add a record for a fulltext.

        Args:
            bytes: The fulltext, as a bytestring.
            parents: A list of revision-ids of the parents.
            repo_kind: The kind of object in the repository. May be 'revision' or
                'signature'.
            revision_id: The revision id of the fulltext being added.
        """
        self._add_record(
            bytes,
            {b"parents": parents, b"storage_kind": b"fulltext"},
            repo_kind,
            revision_id,
            None,
        )

    def add_info_record(self, kwargs):
        """Add an info record to the bundle.

        Args:
            kwargs: Dictionary of metadata to include in the info record.
                Any parameters may be supplied, except 'self' and 'storage_kind'.
                Values must be lists, strings, integers, dicts, or a combination.
        """
        kwargs[b"storage_kind"] = b"header"
        self._add_record(None, kwargs, "info", None, None)

    @staticmethod
    def encode_name(content_kind, revision_id, file_id=None):
        """Encode semantic ids as a container name.

        Args:
            content_kind: Type of content ('revision', 'file', 'inventory',
                'signature', or 'info').
            revision_id: The revision identifier.
            file_id: The file identifier (required for 'file' content_kind,
                None otherwise).

        Returns:
            bytes: The encoded container name.

        Raises:
            ValueError: If content_kind is not recognized.
            AssertionError: If file_id requirements don't match content_kind.
        """
        if content_kind not in ("revision", "file", "inventory", "signature", "info"):
            raise ValueError(content_kind)
        if content_kind == "file":
            if file_id is None:
                raise AssertionError()
        else:
            if file_id is not None:
                raise AssertionError()
        if content_kind == "info":
            if revision_id is not None:
                raise AssertionError()
        elif revision_id is None:
            raise AssertionError()
        names = [
            n.replace(b"/", b"//")
            for n in (content_kind.encode("ascii"), revision_id, file_id)
            if n is not None
        ]
        return b"/".join(names)

    def _add_record(self, bytes, metadata, repo_kind, revision_id, file_id):
        """Add a bundle record to the container.

        Most bundle records are recorded as header/body pairs, with the
        body being nameless. Records with storage_kind 'header' have no
        body.

        Args:
            bytes: The record content data.
            metadata: Dictionary of metadata for the record.
            repo_kind: The kind of repository object.
            revision_id: The revision identifier.
            file_id: The file identifier, if applicable.
        """
        name = self.encode_name(repo_kind, revision_id, file_id)
        encoded_metadata = bencode.bencode(metadata)
        self._container.add_bytes_record(
            [encoded_metadata], len(encoded_metadata), [(name,)]
        )
        if metadata[b"storage_kind"] != b"header":
            self._container.add_bytes_record([bytes], len(bytes), [])


class BundleReader:
    """Reader for bundle-format files.

    This serves roughly the same purpose as ContainerReader, but acts as a
    layer on top of it, providing metadata, a semantic name, and a record
    body
    """

    def __init__(self, fileobj, stream_input=True):
        """Initialize the bundle reader.

        Args:
            fileobj: A file containing a bzip-encoded container.
            stream_input: If True, the BundleReader streams input rather than
                reading it all into memory at once. Reading it into memory all at
                once is (currently) faster.
        """
        line = fileobj.readline()
        if line != "\n":
            fileobj.readline()
        self.patch_lines = []
        if stream_input:
            source_file = osutils.IterableFile(self.iter_decode(fileobj))
        else:
            source_file = BytesIO(bz2.decompress(fileobj.read()))
        self._container_file = source_file

    @staticmethod
    def iter_decode(fileobj):
        """Iterate through decoded fragments of the file.

        Args:
            fileobj: File-like object containing bzip2-compressed data.

        Yields:
            bytes: Decompressed data fragments.
        """
        decompressor = bz2.BZ2Decompressor()
        for line in fileobj:
            try:
                yield decompressor.decompress(line)
            except EOFError:
                return

    @staticmethod
    def decode_name(name):
        """Decode a name from its container form into a semantic form.

        Args:
            name: The encoded container name as bytes.

        Returns:
            Tuple[str, bytes, bytes]: A tuple of (content_kind, revision_id, file_id).
        """
        segments = re.split(b"(//?)", name)
        names = [b""]
        for segment in segments:
            if segment == b"//":
                names[-1] += b"/"
            elif segment == b"/":
                names.append(b"")
            else:
                names[-1] += segment
        content_kind = names[0]
        revision_id = None
        file_id = None
        if len(names) > 1:
            revision_id = names[1]
        if len(names) > 2:
            file_id = names[2]
        return content_kind.decode("ascii"), revision_id, file_id

    def iter_records(self):
        """Iterate through bundle records.

        Yields:
            Tuple[bytes, dict, str, bytes, bytes]: A tuple of (bytes, metadata,
                content_kind, revision_id, file_id).

        Raises:
            errors.BadBundle: If a record has an unexpected number of names.
        """
        iterator = pack.iter_records_from_file(self._container_file)
        for names, bytes in iterator:
            if len(names) != 1:
                raise errors.BadBundle(f"Record has {len(names)} names instead of 1")
            metadata = bencode.bdecode(bytes)
            if metadata[b"storage_kind"] == b"header":
                bytes = None
            else:
                _unused, bytes = next(iterator)
            yield (bytes, metadata) + self.decode_name(names[0][0])


class BundleSerializerV4(bundle_serializer.BundleSerializer):
    """Bundle serializer for format version 4.

    This class implements the high-level bundle interface for creating and
    reading bundle format version 4 files, which use bzip2 compression and
    multi-parent diffs for efficient storage.
    """

    def write_bundle(self, repository, target, base, fileobj):
        """Write a bundle to a file object.

        Args:
            repository: The repository to retrieve revision data from.
            target: The head revision to include ancestors of.
            base: The ancestor of the target to stop including ancestors at.
            fileobj: The file-like object to write to.

        Returns:
            List[bytes]: The revision IDs that were bundled.
        """
        write_op = BundleWriteOperation(base, target, repository, fileobj)
        return write_op.do_write()

    def read(self, file):
        """Return a reader object for a given file.

        Args:
            file: File-like object containing a bundle.

        Returns:
            BundleInfoV4: A bundle info object for reading the bundle.
        """
        bundle = BundleInfoV4(file, self)
        return bundle

    @staticmethod
    def get_source_serializer(info):
        """Retrieve the serializer for a given info object.

        Args:
            info: Dictionary containing serializer format information.

        Returns:
            Tuple[serializer, serializer]: Revision and inventory serializers.
        """
        format_name = info[b"serializer"].decode("ascii")
        inventory_serializer = serializer.inventory_format_registry.get(format_name)
        revision_serializer = serializer.revision_format_registry.get(
            {"7": "5", "6": "5"}.get(format_name, format_name)
        )
        return (revision_serializer, inventory_serializer)


class BundleWriteOperation:
    """Perform the operation of writing revisions to a bundle.

    This class encapsulates all the logic needed to write a bundle file,
    including determining which revisions to include, generating diffs,
    and writing the various record types to the bundle.
    """

    def __init__(self, base, target, repository, fileobj, revision_ids=None):
        """Initialize the bundle write operation.

        Args:
            base: The base revision to start from.
            target: The target revision to bundle up to.
            repository: The repository containing the revisions.
            fileobj: File-like object to write the bundle to.
            revision_ids: Optional explicit list of revision IDs to bundle.
                If None, will be computed from base and target.
        """
        self.base = base
        self.target = target
        self.repository = repository
        bundle = BundleWriter(fileobj)
        self.bundle = bundle
        if revision_ids is not None:
            self.revision_ids = revision_ids
        else:
            graph = repository.get_graph()
            revision_ids = graph.find_unique_ancestors(target, [base])
            # Strip ghosts
            parents = graph.get_parent_map(revision_ids)
            self.revision_ids = [r for r in revision_ids if r in parents]
        self.revision_keys = {(revid,) for revid in self.revision_ids}

    def do_write(self):
        """Write all data to the bundle.

        Returns:
            List[bytes]: The revision IDs that were bundled.
        """
        trace.note(
            ngettext(
                "Bundling %d revision.",
                "Bundling %d revisions.",
                len(self.revision_ids),
            ),
            len(self.revision_ids),
        )
        with self.repository.lock_read():
            self.bundle.begin()
            self.write_info()
            self.write_files()
            self.write_revisions()
            self.bundle.end()
        return self.revision_ids

    def write_info(self):
        """Write format information to the bundle.

        Writes metadata about the repository format, including serializer
        format and rich root support information.
        """
        serializer_format = self.repository.get_serializer_format()
        supports_rich_root = {True: 1, False: 0}[self.repository.supports_rich_root()]
        self.bundle.add_info_record(
            {
                b"serializer": serializer_format,
                b"supports_rich_root": supports_rich_root,
            }
        )

    def write_files(self):
        """Write bundle records for all revisions of all files.

        Determines which files were altered by the revisions being bundled
        and writes multi-parent diff records for each file revision.
        """
        text_keys = []
        altered_fileids = self.repository.fileids_altered_by_revision_ids(
            self.revision_ids
        )
        for file_id, revision_ids in altered_fileids.items():
            for revision_id in revision_ids:
                text_keys.append((file_id, revision_id))
        self._add_mp_records_keys("file", self.repository.texts, text_keys)

    def write_revisions(self):
        """Write bundle records for all revisions and signatures.

        Writes inventory diffs and revision texts in topological order,
        with special handling for different repository formats.
        """
        inv_vf = self.repository.inventories
        topological_order = [
            key[-1] for key in multiparent.topo_iter_keys(inv_vf, self.revision_keys)
        ]
        revision_order = topological_order
        if self.target is not None and self.target in self.revision_ids:
            # Make sure the target revision is always the last entry
            revision_order = list(topological_order)
            revision_order.remove(self.target)
            revision_order.append(self.target)
        if self.repository._inventory_serializer.support_altered_by_hack:
            # Repositories that support_altered_by_hack means that
            # inventories.make_mpdiffs() contains all the data about the tree
            # shape. Formats without support_altered_by_hack require
            # chk_bytes/etc, so we use a different code path.
            self._add_mp_records_keys(
                "inventory", inv_vf, [(revid,) for revid in topological_order]
            )
        else:
            # Inventories should always be added in pure-topological order, so
            # that we can apply the mpdiff for the child to the parent texts.
            self._add_inventory_mpdiffs_from_serializer(topological_order)
        self._add_revision_texts(revision_order)

    def _add_inventory_mpdiffs_from_serializer(self, revision_order):
        """Generate multi-parent diffs by serializing inventories.

        The current repository only has part of the tree shape information in
        the 'inventories' vf. So we use serializer.write_inventory_to_lines to
        get a 'full' representation of the tree shape, and then generate
        mpdiffs on that data stream. This stream can then be reconstructed on
        the other side.

        Args:
            revision_order: List of revision IDs in the order to process them.
        """
        inventory_key_order = [(r,) for r in revision_order]
        generator = _MPDiffInventoryGenerator(self.repository, inventory_key_order)
        for revision_id, parent_ids, sha1, diff in generator.iter_diffs():
            text = b"".join(diff.to_patch())
            self.bundle.add_multiparent_record(
                text, sha1, parent_ids, "inventory", revision_id, None
            )

    def _add_revision_texts(self, revision_order):
        """Add revision text records to the bundle.

        Args:
            revision_order: List of revision IDs to add in order.
        """
        parent_map = self.repository.get_parent_map(revision_order)
        revision_to_bytes = (
            self.repository._revision_serializer.write_revision_to_string
        )
        revisions = self.repository.get_revisions(revision_order)
        for revision in revisions:
            revision_id = revision.revision_id
            parents = parent_map.get(revision_id, None)
            revision_text = revision_to_bytes(revision)
            self.bundle.add_fulltext_record(
                revision_text, parents, "revision", revision_id
            )
            with contextlib.suppress(errors.NoSuchRevision):
                self.bundle.add_fulltext_record(
                    self.repository.get_signature_text(revision_id),
                    parents,
                    "signature",
                    revision_id,
                )

    @staticmethod
    def get_base_target(revision_ids, forced_bases, repository):
        """Determine the base and target from old-style revision ids.

        Args:
            revision_ids: List of revision IDs to process.
            forced_bases: Dictionary of forced base revisions.
            repository: The repository containing the revisions.

        Returns:
            Tuple[bytes, bytes]: The base and target revision IDs.
        """
        if len(revision_ids) == 0:
            return None, None
        target = revision_ids[0]
        base = forced_bases.get(target)
        if base is None:
            parents = repository.get_revision(target).parent_ids
            base = _mod_revision.NULL_REVISION if len(parents) == 0 else parents[0]
        return base, target

    def _add_mp_records_keys(self, repo_kind, vf, keys):
        """Add multi-parent diff records to a bundle.

        Args:
            repo_kind: The kind of repository objects ('file' or 'inventory').
            vf: The versioned file containing the data.
            keys: List of keys to generate diffs for.
        """
        ordered_keys = list(multiparent.topo_iter_keys(vf, keys))
        mpdiffs = vf.make_mpdiffs(ordered_keys)
        sha1s = vf.get_sha1s(ordered_keys)
        parent_map = vf.get_parent_map(ordered_keys)
        for (
            mpdiff,
            item_key,
        ) in zip(mpdiffs, ordered_keys):
            sha1 = sha1s[item_key]
            parents = [key[-1] for key in parent_map[item_key]]
            text = b"".join(mpdiff.to_patch())
            # Infer file id records as appropriate.
            file_id = item_key[0] if len(item_key) == 2 else None
            self.bundle.add_multiparent_record(
                text, sha1, parents, repo_kind, item_key[-1], file_id
            )


class BundleInfoV4:
    """Provide bundle information and installation interface for format v4.

    This class implements most of the BundleInfo interface, providing
    methods to read bundle contents and install revisions into a repository.
    """

    def __init__(self, fileobj, serializer):
        """Initialize the bundle info object.

        Args:
            fileobj: File-like object containing the bundle.
            serializer: The serializer used to create the bundle.
        """
        self._fileobj = fileobj
        self._serializer = serializer
        self.__real_revisions = None
        self.__revisions = None

    def install(self, repository):
        """Install this bundle's revisions into the specified repository.

        Args:
            repository: The repository to install into.

        Returns:
            bytes: The target revision ID that was installed.
        """
        return self.install_revisions(repository)

    def install_revisions(self, repository, stream_input=True):
        """Install this bundle's revisions into the specified repository.

        Args:
            repository: The repository to install into.
            stream_input: If True, will stream input rather than reading it
                all into memory at once. Reading it into memory all at once is
                (currently) faster.

        Returns:
            bytes: The target revision ID that was installed.
        """
        with repository.lock_write():
            ri = RevisionInstaller(
                self.get_bundle_reader(stream_input), self._serializer, repository
            )
            return ri.install()

    def get_merge_request(self, target_repo):
        """Provide data for performing a merge.

        Args:
            target_repo: The target repository for the merge.

        Returns:
            Tuple[None, bytes, str]: Suggested base (None), suggested target,
                and patch verification status ('inapplicable').
        """
        return None, self.target, "inapplicable"

    def get_bundle_reader(self, stream_input=True):
        """Return a new BundleReader for the associated bundle.

        Args:
            stream_input: If True, the BundleReader streams input rather than
                reading it all into memory at once. Reading it into memory all at
                once is (currently) faster.

        Returns:
            BundleReader: A new reader for this bundle.
        """
        self._fileobj.seek(0)
        return BundleReader(self._fileobj, stream_input)

    def _get_real_revisions(self):
        """Extract and cache the real revision objects from the bundle.

        Returns:
            List[Revision]: The revision objects contained in the bundle.
        """
        if self.__real_revisions is None:
            self.__real_revisions = []
            bundle_reader = self.get_bundle_reader()
            for (
                bytes,
                metadata,
                repo_kind,
                _revision_id,
                _file_id,
            ) in bundle_reader.iter_records():
                if repo_kind == "info":
                    (
                        revision_serializer,
                        inventory_serializer,
                    ) = self._serializer.get_source_serializer(metadata)
                if repo_kind == "revision":
                    rev = revision_serializer.read_revision_from_string(bytes)
                    self.__real_revisions.append(rev)
        return self.__real_revisions

    real_revisions = property(_get_real_revisions)

    def _get_revisions(self):
        """Get RevisionInfo objects for all revisions in the bundle.

        Returns:
            List[RevisionInfo]: The revision info objects for the bundle.
        """
        if self.__revisions is None:
            self.__revisions = []
            for revision in self.real_revisions:
                self.__revisions.append(
                    bundle_data.RevisionInfo.from_revision(revision)
                )
        return self.__revisions

    revisions = property(_get_revisions)

    def _get_target(self):
        """Get the target revision ID from the bundle.

        Returns:
            bytes: The revision ID of the last revision in the bundle.
        """
        return self.revisions[-1].revision_id

    target = property(_get_target)


class RevisionInstaller:
    """Installs revisions from a bundle into a repository.

    This class handles the complex process of reading bundle records and
    installing them into a repository, including format conversion and
    dependency resolution.
    """

    def __init__(self, container, serializer, repository):
        """Initialize the revision installer.

        Args:
            container: BundleReader containing the bundle records.
            serializer: The serializer to use for reading the bundle.
            repository: The target repository to install revisions into.
        """
        self._container = container
        self._serializer = serializer
        self._repository = repository
        self._info = None

    def install(self):
        """Perform the installation.

        Must be called with the Repository locked.

        Returns:
            bytes: The target revision ID that was installed.
        """
        with _mod_repository.WriteGroup(self._repository):
            return self._install_in_write_group()

    def _install_in_write_group(self):
        """Install all records within a write group.

        Returns:
            bytes: The target revision ID that was installed.
        """
        current_file = None
        pending_file_records = []
        pending_inventory_records = []
        target_revision = None
        for (
            bytes,
            metadata,
            repo_kind,
            revision_id,
            file_id,
        ) in self._container.iter_records():
            if repo_kind == "info":
                if self._info is not None:
                    raise AssertionError()
                self._handle_info(metadata)
            if pending_file_records and (repo_kind, file_id) != ("file", current_file):
                # Flush the data for a single file - prevents memory
                # spiking due to buffering all files in memory.
                self._install_mp_records_keys(
                    self._repository.texts, pending_file_records
                )
                current_file = None
                del pending_file_records[:]
            if len(pending_inventory_records) > 0 and repo_kind != "inventory":
                self._install_inventory_records(pending_inventory_records)
                pending_inventory_records = []
            if repo_kind == "inventory":
                pending_inventory_records.append(((revision_id,), metadata, bytes))
            if repo_kind == "revision":
                target_revision = revision_id
                self._install_revision(revision_id, metadata, bytes)
            if repo_kind == "signature":
                self._install_signature(revision_id, metadata, bytes)
            if repo_kind == "file":
                current_file = file_id
                pending_file_records.append(((file_id, revision_id), metadata, bytes))
        self._install_mp_records_keys(self._repository.texts, pending_file_records)
        return target_revision

    def _handle_info(self, info):
        """Extract data from an info record.

        Args:
            info: Dictionary containing bundle format information.
        """
        self._info = info
        (
            self._source_revision_serializer,
            self._source_inventory_serializer,
        ) = self._serializer.get_source_serializer(info)
        if info[b"supports_rich_root"] == 0 and self._repository.supports_rich_root():
            self.update_root = True
        else:
            self.update_root = False

    def _install_mp_records(self, versionedfile, records):
        """Install multi-parent diff records into a versioned file.

        Args:
            versionedfile: The versioned file to install records into.
            records: List of (key, metadata, text) tuples to install.
        """
        if len(records) == 0:
            return
        d_func = multiparent.MultiParent.from_patch
        vf_records = [
            (r, m["parents"], m["sha1"], d_func(t))
            for r, m, t in records
            if r not in versionedfile
        ]
        versionedfile.add_mpdiffs(vf_records)

    def _install_mp_records_keys(self, versionedfile, records):
        """Install multi-parent diff records with key-based interface.

        Args:
            versionedfile: The versioned file to install records into.
            records: List of (key, metadata, text) tuples to install.
        """
        d_func = multiparent.MultiParent.from_patch
        vf_records = []
        for key, meta, text in records:
            # Adapt to tuple interface: A length two key is a file_id,
            # revision_id pair, a length 1 key is a
            # revision/signature/inventory. We need to do this because
            # the metadata extraction from the bundle has not yet been updated
            # to use the consistent tuple interface itself.
            if len(key) == 2:
                prefix = key[:1]
            else:
                prefix = ()
            parents = [prefix + (parent,) for parent in meta[b"parents"]]
            vf_records.append((key, parents, meta[b"sha1"], d_func(text)))
        versionedfile.add_mpdiffs(vf_records)

    def _get_parent_inventory_texts(
        self, inventory_text_cache, inventory_cache, parent_ids
    ):
        """Retrieve parent inventory texts for diff application.

        Args:
            inventory_text_cache: Cache of serialized inventory texts.
            inventory_cache: Cache of inventory objects.
            parent_ids: List of parent revision IDs to retrieve.

        Returns:
            List[bytes]: Serialized parent inventory texts.
        """
        cached_parent_texts = {}
        remaining_parent_ids = []
        for parent_id in parent_ids:
            p_text = inventory_text_cache.get(parent_id, None)
            if p_text is None:
                remaining_parent_ids.append(parent_id)
            else:
                cached_parent_texts[parent_id] = p_text
        ghosts = ()
        # TODO: Use inventory_cache to grab inventories we already have in
        #       memory
        if remaining_parent_ids:
            # first determine what keys are actually present in the local
            # inventories object (don't use revisions as they haven't been
            # installed yet.)
            parent_keys = [(r,) for r in remaining_parent_ids]
            present_parent_map = self._repository.inventories.get_parent_map(
                parent_keys
            )
            present_parent_ids = []
            ghosts = set()
            for p_id in remaining_parent_ids:
                if (p_id,) in present_parent_map:
                    present_parent_ids.append(p_id)
                else:
                    ghosts.add(p_id)
            to_lines = self._source_inventory_serializer.write_inventory_to_chunks
            for parent_inv in self._repository.iter_inventories(present_parent_ids):
                p_text = b"".join(to_lines(parent_inv))
                inventory_cache[parent_inv.revision_id] = parent_inv
                cached_parent_texts[parent_inv.revision_id] = p_text
                inventory_text_cache[parent_inv.revision_id] = p_text

        parent_texts = [
            cached_parent_texts[parent_id]
            for parent_id in parent_ids
            if parent_id not in ghosts
        ]
        return parent_texts

    def _install_inventory_records(self, records):
        """Install inventory records into the repository.

        Args:
            records: List of (key, metadata, bytes) tuples containing
                inventory data to install.
        """
        if (
            self._info[b"serializer"]
            == self._repository._inventory_serializer.format_num
            and self._repository._inventory_serializer.support_altered_by_hack
        ):
            return self._install_mp_records_keys(self._repository.inventories, records)
        # Use a 10MB text cache, since these are string xml inventories. Note
        # that 10MB is fairly small for large projects (a single inventory can
        # be >5MB). Another possibility is to cache 10-20 inventory texts
        # instead
        inventory_text_cache = lru_cache.LRUSizeCache(10 * 1024 * 1024)
        # Also cache the in-memory representation. This allows us to create
        # inventory deltas to apply rather than calling add_inventory from
        # scratch each time.
        inventory_cache = lru_cache.LRUCache(10)
        with ui.ui_factory.nested_progress_bar() as pb:
            num_records = len(records)
            for idx, (key, metadata, bytes) in enumerate(records):
                pb.update("installing inventory", idx, num_records)
                revision_id = key[-1]
                parent_ids = metadata[b"parents"]
                # Note: This assumes the local ghosts are identical to the
                #       ghosts in the source, as the Bundle serialization
                #       format doesn't record ghosts.
                p_texts = self._get_parent_inventory_texts(
                    inventory_text_cache, inventory_cache, parent_ids
                )
                # Why does to_lines() take strings as the source, it seems that
                # it would have to cast to a list of lines, which we get back
                # as lines and then cast back to a string.
                target_lines = multiparent.MultiParent.from_patch(bytes).to_lines(
                    p_texts
                )
                sha1 = osutils.sha_strings(target_lines)
                if sha1 != metadata[b"sha1"]:
                    raise errors.BadBundle("Can't convert to target format")
                # Add this to the cache so we don't have to extract it again.
                inventory_text_cache[revision_id] = b"".join(target_lines)
                target_inv = (
                    self._source_inventory_serializer.read_inventory_from_lines(
                        target_lines
                    )
                )
                del target_lines
                self._handle_root(target_inv, parent_ids)
                parent_inv = None
                if parent_ids:
                    parent_inv = inventory_cache.get(parent_ids[0], None)
                try:
                    if parent_inv is None:
                        self._repository.add_inventory(
                            revision_id, target_inv, parent_ids
                        )
                    else:
                        delta = _make_delta(target_inv, parent_inv)
                        self._repository.add_inventory_by_delta(
                            parent_ids[0], delta, revision_id, parent_ids
                        )
                except serializer.UnsupportedInventoryKind as e:
                    raise errors.IncompatibleRevision(repr(self._repository)) from e
                inventory_cache[revision_id] = target_inv

    def _handle_root(self, target_inv, parent_ids):
        """Handle root directory entries for rich root support.

        Args:
            target_inv: The inventory being processed.
            parent_ids: List of parent revision IDs.

        Raises:
            errors.IncompatibleRevision: If root handling requirements aren't met.
        """
        revision_id = target_inv.revision_id
        if self.update_root:
            text_key = (target_inv.root.file_id, revision_id)
            parent_keys = [(target_inv.root.file_id, parent) for parent in parent_ids]
            self._repository.texts.add_lines(text_key, parent_keys, [])
        elif not self._repository.supports_rich_root():
            if target_inv.root.revision != revision_id:
                raise errors.IncompatibleRevision(repr(self._repository))

    def _install_revision(self, revision_id, metadata, text):
        """Install a revision record into the repository.

        Args:
            revision_id: The revision ID to install.
            metadata: Record metadata (currently unused).
            text: Serialized revision text.
        """
        if self._repository.has_revision(revision_id):
            return
        revision = self._source_revision_serializer.read_revision_from_string(text)
        self._repository.add_revision(revision.revision_id, revision)

    def _install_signature(self, revision_id, metadata, text):
        """Install a signature record into the repository.

        Args:
            revision_id: The revision ID the signature is for.
            metadata: Record metadata (currently unused).
            text: The signature text.
        """
        self._repository.get_transaction()
        if self._repository.has_signature_for_revision_id(revision_id):
            return
        self._repository.add_signature_text(revision_id, text)
