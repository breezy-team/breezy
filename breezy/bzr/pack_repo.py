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

import re
import sys

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import contextlib
import time

from breezy import (
    config,
    debug,
    graph,
    osutils,
    transactions,
    ui,
    )
from breezy.bzr import (
    pack,
    )
from breezy.bzr.index import (
    CombinedGraphIndex,
    )
""",
)
from .. import errors, lockable_files, lockdir
from .. import transport as _mod_transport
from ..bzr import btree_index
from ..bzr import index as _mod_index
from ..decorators import only_raises
from ..lock import LogicalLockResult
from ..repository import RepositoryWriteLockResult, _LazyListJoin
from ..trace import mutter, note, warning
from .repository import MetaDirRepository, RepositoryFormatMetaDir
from .serializer import Serializer
from .vf_repository import (
    MetaDirVersionedFileRepository,
    MetaDirVersionedFileRepositoryFormat,
    VersionedFileCommitBuilder,
)


class RetryWithNewPacks(errors.BzrError):
    """Raised when we realize that the packs on disk have changed.

    This is meant as more of a signaling exception, to trap between where a
    local error occurred and the code that can actually handle the error and
    code that can retry appropriately.
    """

    internal_error = True

    _fmt = (
        "Pack files have changed, reload and retry. context: %(context)s %(orig_error)s"
    )

    def __init__(self, context, reload_occurred, exc_info):
        """Create a new RetryWithNewPacks error.

        :param reload_occurred: Set to True if we know that the packs have
            already been reloaded, and we are failing because of an in-memory
            cache miss. If set to True then we will ignore if a reload says
            nothing has changed, because we assume it has already reloaded. If
            False, then a reload with nothing changed will force an error.
        :param exc_info: The original exception traceback, so if there is a
            problem we can raise the original error (value from sys.exc_info())
        """
        errors.BzrError.__init__(self)
        self.context = context
        self.reload_occurred = reload_occurred
        self.exc_info = exc_info
        self.orig_error = exc_info[1]
        # TODO: The global error handler should probably treat this by
        #       raising/printing the original exception with a bit about
        #       RetryWithNewPacks also not being caught


class RetryAutopack(RetryWithNewPacks):
    """Raised when we are autopacking and we find a missing file.

    Meant as a signaling exception, to tell the autopack code it should try
    again.
    """

    internal_error = True

    _fmt = (
        "Pack files have changed, reload and try autopack again."
        " context: %(context)s %(orig_error)s"
    )


class PackCommitBuilder(VersionedFileCommitBuilder):
    """Subclass of VersionedFileCommitBuilder to add texts with pack semantics.

    Specifically this uses one knit object rather than one knit object per
    added text, reducing memory and object pressure.
    """

    def __init__(
        self,
        repository,
        parents,
        config,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
        owns_transaction=True,
    ):
        VersionedFileCommitBuilder.__init__(
            self,
            repository,
            parents,
            config,
            timestamp=timestamp,
            timezone=timezone,
            committer=committer,
            revprops=revprops,
            revision_id=revision_id,
            lossy=lossy,
            owns_transaction=owns_transaction,
        )
        self._file_graph = graph.Graph(
            repository._pack_collection.text_index.combined_index
        )

    def _heads(self, file_id, revision_ids):
        keys = [(file_id, revision_id) for revision_id in revision_ids]
        return {key[1] for key in self._file_graph.heads(keys)}


class Pack:
    """An in memory proxy for a pack and its indices.

    This is a base class that is not directly used, instead the classes
    ExistingPack and NewPack are used.
    """

    # A map of index 'type' to the file extension and position in the
    # index_sizes array.
    index_definitions = {
        "chk": (".cix", 4),
        "revision": (".rix", 0),
        "inventory": (".iix", 1),
        "text": (".tix", 2),
        "signature": (".six", 3),
    }

    def __init__(
        self,
        revision_index,
        inventory_index,
        text_index,
        signature_index,
        chk_index=None,
    ):
        """Create a pack instance.

        :param revision_index: A GraphIndex for determining what revisions are
            present in the Pack and accessing the locations of their texts.
        :param inventory_index: A GraphIndex for determining what inventories are
            present in the Pack and accessing the locations of their
            texts/deltas.
        :param text_index: A GraphIndex for determining what file texts
            are present in the pack and accessing the locations of their
            texts/deltas (via (fileid, revisionid) tuples).
        :param signature_index: A GraphIndex for determining what signatures are
            present in the Pack and accessing the locations of their texts.
        :param chk_index: A GraphIndex for accessing content by CHK, if the
            pack has one.
        """
        self.revision_index = revision_index
        self.inventory_index = inventory_index
        self.text_index = text_index
        self.signature_index = signature_index
        self.chk_index = chk_index

    def access_tuple(self):
        """Return a tuple (transport, name) for the pack content."""
        return self.pack_transport, self.file_name()

    def _check_references(self):
        """Make sure our external references are present.

        Packs are allowed to have deltas whose base is not in the pack, but it
        must be present somewhere in this collection.  It is not allowed to
        have deltas based on a fallback repository.
        (See <https://bugs.launchpad.net/bzr/+bug/288751>)
        """
        missing_items = {}
        for index_name, external_refs, index in [
            (
                "texts",
                self._get_external_refs(self.text_index),
                self._pack_collection.text_index.combined_index,
            ),
            (
                "inventories",
                self._get_external_refs(self.inventory_index),
                self._pack_collection.inventory_index.combined_index,
            ),
        ]:
            missing = external_refs.difference(
                k for (idx, k, v, r) in index.iter_entries(external_refs)
            )
            if missing:
                missing_items[index_name] = sorted(missing)
        if missing_items:
            from pprint import pformat

            raise errors.BzrCheckError(
                "Newly created pack file {!r} has delta references to "
                "items not in its repository:\n{}".format(self, pformat(missing_items))
            )

    def file_name(self):
        """Get the file name for the pack on disk."""
        return self.name + ".pack"

    def get_revision_count(self):
        return self.revision_index.key_count()

    def index_name(self, index_type, name):
        """Get the disk name of an index type for pack name 'name'."""
        return name + Pack.index_definitions[index_type][0]

    def index_offset(self, index_type):
        """Get the position in a index_size array for a given index type."""
        return Pack.index_definitions[index_type][1]

    def inventory_index_name(self, name):
        """The inv index is the name + .iix."""
        return self.index_name("inventory", name)

    def revision_index_name(self, name):
        """The revision index is the name + .rix."""
        return self.index_name("revision", name)

    def signature_index_name(self, name):
        """The signature index is the name + .six."""
        return self.index_name("signature", name)

    def text_index_name(self, name):
        """The text index is the name + .tix."""
        return self.index_name("text", name)

    def _replace_index_with_readonly(self, index_type):
        unlimited_cache = False
        if index_type == "chk":
            unlimited_cache = True
        index = self.index_class(
            self.index_transport,
            self.index_name(index_type, self.name),
            self.index_sizes[self.index_offset(index_type)],
            unlimited_cache=unlimited_cache,
        )
        if index_type == "chk":
            index._leaf_factory = btree_index._gcchk_factory
        setattr(self, index_type + "_index", index)

    def __lt__(self, other):
        if not isinstance(other, Pack):
            raise TypeError(other)
        return id(self) < id(other)

    def __hash__(self):
        return hash(
            (
                type(self),
                self.revision_index,
                self.inventory_index,
                self.text_index,
                self.signature_index,
                self.chk_index,
            )
        )


class ExistingPack(Pack):
    """An in memory proxy for an existing .pack and its disk indices."""

    def __init__(
        self,
        pack_transport,
        name,
        revision_index,
        inventory_index,
        text_index,
        signature_index,
        chk_index=None,
    ):
        """Create an ExistingPack object.

        :param pack_transport: The transport where the pack file resides.
        :param name: The name of the pack on disk in the pack_transport.
        """
        Pack.__init__(
            self,
            revision_index,
            inventory_index,
            text_index,
            signature_index,
            chk_index,
        )
        self.name = name
        self.pack_transport = pack_transport
        if None in (
            revision_index,
            inventory_index,
            text_index,
            signature_index,
            name,
            pack_transport,
        ):
            raise AssertionError()

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "<{}.{} object at 0x{:x}, {}, {}".format(
            self.__class__.__module__,
            self.__class__.__name__,
            id(self),
            self.pack_transport,
            self.name,
        )

    def __hash__(self):
        return hash((type(self), self.name))


class ResumedPack(ExistingPack):
    def __init__(
        self,
        name,
        revision_index,
        inventory_index,
        text_index,
        signature_index,
        upload_transport,
        pack_transport,
        index_transport,
        pack_collection,
        chk_index=None,
    ):
        """Create a ResumedPack object."""
        ExistingPack.__init__(
            self,
            pack_transport,
            name,
            revision_index,
            inventory_index,
            text_index,
            signature_index,
            chk_index=chk_index,
        )
        self.upload_transport = upload_transport
        self.index_transport = index_transport
        self.index_sizes = [None, None, None, None]
        indices = [
            ("revision", revision_index),
            ("inventory", inventory_index),
            ("text", text_index),
            ("signature", signature_index),
        ]
        if chk_index is not None:
            indices.append(("chk", chk_index))
            self.index_sizes.append(None)
        for index_type, index in indices:
            offset = self.index_offset(index_type)
            self.index_sizes[offset] = index._size
        self.index_class = pack_collection._index_class
        self._pack_collection = pack_collection
        self._state = "resumed"
        # XXX: perhaps check that the .pack file exists?

    def access_tuple(self):
        if self._state == "finished":
            return Pack.access_tuple(self)
        elif self._state == "resumed":
            return self.upload_transport, self.file_name()
        else:
            raise AssertionError(self._state)

    def abort(self):
        self.upload_transport.delete(self.file_name())
        indices = [
            self.revision_index,
            self.inventory_index,
            self.text_index,
            self.signature_index,
        ]
        if self.chk_index is not None:
            indices.append(self.chk_index)
        for index in indices:
            index._transport.delete(index._name)

    def finish(self):
        self._check_references()
        index_types = ["revision", "inventory", "text", "signature"]
        if self.chk_index is not None:
            index_types.append("chk")
        for index_type in index_types:
            old_name = self.index_name(index_type, self.name)
            new_name = "../indices/" + old_name
            self.upload_transport.move(old_name, new_name)
            self._replace_index_with_readonly(index_type)
        new_name = "../packs/" + self.file_name()
        self.upload_transport.move(self.file_name(), new_name)
        self._state = "finished"

    def _get_external_refs(self, index):
        """Return compression parents for this index that are not present.

        This returns any compression parents that are referenced by this index,
        which are not contained *in* this index. They may be present elsewhere.
        """
        return index.external_references(1)


class NewPack(Pack):
    """An in memory proxy for a pack which is being created."""

    def __init__(self, pack_collection, upload_suffix="", file_mode=None):
        """Create a NewPack instance.

        :param pack_collection: A PackCollection into which this is being inserted.
        :param upload_suffix: An optional suffix to be given to any temporary
            files created during the pack creation. e.g '.autopack'
        :param file_mode: Unix permissions for newly created file.
        """
        # The relative locations of the packs are constrained, but all are
        # passed in because the caller has them, so as to avoid object churn.
        index_builder_class = pack_collection._index_builder_class
        if pack_collection.chk_index is not None:
            chk_index = index_builder_class(reference_lists=0)
        else:
            chk_index = None
        Pack.__init__(
            self,
            # Revisions: parents list, no text compression.
            index_builder_class(reference_lists=1),
            # Inventory: We want to map compression only, but currently the
            # knit code hasn't been updated enough to understand that, so we
            # have a regular 2-list index giving parents and compression
            # source.
            index_builder_class(reference_lists=2),
            # Texts: compression and per file graph, for all fileids - so two
            # reference lists and two elements in the key tuple.
            index_builder_class(reference_lists=2, key_elements=2),
            # Signatures: Just blobs to store, no compression, no parents
            # listing.
            index_builder_class(reference_lists=0),
            # CHK based storage - just blobs, no compression or parents.
            chk_index=chk_index,
        )
        self._pack_collection = pack_collection
        # When we make readonly indices, we need this.
        self.index_class = pack_collection._index_class
        # where should the new pack be opened
        self.upload_transport = pack_collection._upload_transport
        # where are indices written out to
        self.index_transport = pack_collection._index_transport
        # where is the pack renamed to when it is finished?
        self.pack_transport = pack_collection._pack_transport
        # What file mode to upload the pack and indices with.
        self._file_mode = file_mode
        # tracks the content written to the .pack file.
        self._hash = osutils.md5()
        # a tuple with the length in bytes of the indices, once the pack
        # is finalised. (rev, inv, text, sigs, chk_if_in_use)
        self.index_sizes = None
        # How much data to cache when writing packs. Note that this is not
        # synchronised with reads, because it's not in the transport layer, so
        # is not safe unless the client knows it won't be reading from the pack
        # under creation.
        self._cache_limit = 0
        # the temporary pack file name.
        self.random_name = osutils.rand_chars(20) + upload_suffix
        # when was this pack started ?
        self.start_time = time.time()
        # open an output stream for the data added to the pack.
        self.write_stream = self.upload_transport.open_write_stream(
            self.random_name, mode=self._file_mode
        )
        if "pack" in debug.debug_flags:
            mutter(
                "%s: create_pack: pack stream open: %s%s t+%6.3fs",
                time.ctime(),
                self.upload_transport.base,
                self.random_name,
                time.time() - self.start_time,
            )
        # A list of byte sequences to be written to the new pack, and the
        # aggregate size of them.  Stored as a list rather than separate
        # variables so that the _write_data closure below can update them.
        self._buffer = [[], 0]
        # create a callable for adding data
        #
        # robertc says- this is a closure rather than a method on the object
        # so that the variables are locals, and faster than accessing object
        # members.

        def _write_data(
            bytes,
            flush=False,
            _buffer=self._buffer,
            _write=self.write_stream.write,
            _update=self._hash.update,
        ):
            _buffer[0].append(bytes)
            _buffer[1] += len(bytes)
            # buffer cap
            if _buffer[1] > self._cache_limit or flush:
                bytes = b"".join(_buffer[0])
                _write(bytes)
                _update(bytes)
                _buffer[:] = [[], 0]

        # expose this on self, for the occasion when clients want to add data.
        self._write_data = _write_data
        # a pack writer object to serialise pack records.
        self._writer = pack.ContainerWriter(self._write_data)
        self._writer.begin()
        # what state is the pack in? (open, finished, aborted)
        self._state = "open"
        # no name until we finish writing the content
        self.name = None

    def abort(self):
        """Cancel creating this pack."""
        self._state = "aborted"
        self.write_stream.close()
        # Remove the temporary pack file.
        self.upload_transport.delete(self.random_name)
        # The indices have no state on disk.

    def access_tuple(self):
        """Return a tuple (transport, name) for the pack content."""
        if self._state == "finished":
            return Pack.access_tuple(self)
        elif self._state == "open":
            return self.upload_transport, self.random_name
        else:
            raise AssertionError(self._state)

    def data_inserted(self):
        """True if data has been added to this pack."""
        return bool(
            self.get_revision_count()
            or self.inventory_index.key_count()
            or self.text_index.key_count()
            or self.signature_index.key_count()
            or (self.chk_index is not None and self.chk_index.key_count())
        )

    def finish_content(self):
        if self.name is not None:
            return
        self._writer.end()
        if self._buffer[1]:
            self._write_data(b"", flush=True)
        self.name = self._hash.hexdigest()

    def finish(self, suspend=False):
        """Finish the new pack.

        This:
         - finalises the content
         - assigns a name (the md5 of the content, currently)
         - writes out the associated indices
         - renames the pack into place.
         - stores the index size tuple for the pack in the index_sizes
           attribute.
        """
        self.finish_content()
        if not suspend:
            self._check_references()
        # write indices
        # XXX: It'd be better to write them all to temporary names, then
        # rename them all into place, so that the window when only some are
        # visible is smaller.  On the other hand none will be seen until
        # they're in the names list.
        self.index_sizes = [None, None, None, None]
        self._write_index("revision", self.revision_index, "revision", suspend)
        self._write_index("inventory", self.inventory_index, "inventory", suspend)
        self._write_index("text", self.text_index, "file texts", suspend)
        self._write_index(
            "signature", self.signature_index, "revision signatures", suspend
        )
        if self.chk_index is not None:
            self.index_sizes.append(None)
            self._write_index("chk", self.chk_index, "content hash bytes", suspend)
        self.write_stream.close(
            want_fdatasync=self._pack_collection.config_stack.get(
                "repository.fdatasync"
            )
        )
        # Note that this will clobber an existing pack with the same name,
        # without checking for hash collisions. While this is undesirable this
        # is something that can be rectified in a subsequent release. One way
        # to rectify it may be to leave the pack at the original name, writing
        # its pack-names entry as something like 'HASH: index-sizes
        # temporary-name'. Allocate that and check for collisions, if it is
        # collision free then rename it into place. If clients know this scheme
        # they can handle missing-file errors by:
        #  - try for HASH.pack
        #  - try for temporary-name
        #  - refresh the pack-list to see if the pack is now absent
        new_name = self.name + ".pack"
        if not suspend:
            new_name = "../packs/" + new_name
        self.upload_transport.move(self.random_name, new_name)
        self._state = "finished"
        if "pack" in debug.debug_flags:
            # XXX: size might be interesting?
            mutter(
                "%s: create_pack: pack finished: %s%s->%s t+%6.3fs",
                time.ctime(),
                self.upload_transport.base,
                self.random_name,
                new_name,
                time.time() - self.start_time,
            )

    def flush(self):
        """Flush any current data."""
        if self._buffer[1]:
            bytes = b"".join(self._buffer[0])
            self.write_stream.write(bytes)
            self._hash.update(bytes)
            self._buffer[:] = [[], 0]

    def _get_external_refs(self, index):
        return index._external_references()

    def set_write_cache_size(self, size):
        self._cache_limit = size

    def _write_index(self, index_type, index, label, suspend=False):
        """Write out an index.

        :param index_type: The type of index to write - e.g. 'revision'.
        :param index: The index object to serialise.
        :param label: What label to give the index e.g. 'revision'.
        """
        index_name = self.index_name(index_type, self.name)
        if suspend:
            transport = self.upload_transport
        else:
            transport = self.index_transport
        index_tempfile = index.finish()
        index_bytes = index_tempfile.read()
        write_stream = transport.open_write_stream(index_name, mode=self._file_mode)
        write_stream.write(index_bytes)
        write_stream.close(
            want_fdatasync=self._pack_collection.config_stack.get(
                "repository.fdatasync"
            )
        )
        self.index_sizes[self.index_offset(index_type)] = len(index_bytes)
        if "pack" in debug.debug_flags:
            # XXX: size might be interesting?
            mutter(
                "%s: create_pack: wrote %s index: %s%s t+%6.3fs",
                time.ctime(),
                label,
                self.upload_transport.base,
                self.random_name,
                time.time() - self.start_time,
            )
        # Replace the writable index on this object with a readonly,
        # presently unloaded index. We should alter
        # the index layer to make its finish() error if add_node is
        # subsequently used. RBC
        self._replace_index_with_readonly(index_type)


class AggregateIndex:
    """An aggregated index for the RepositoryPackCollection.

    AggregateIndex is reponsible for managing the PackAccess object,
    Index-To-Pack mapping, and all indices list for a specific type of index
    such as 'revision index'.

    A CombinedIndex provides an index on a single key space built up
    from several on-disk indices.  The AggregateIndex builds on this
    to provide a knit access layer, and allows having up to one writable
    index within the collection.
    """

    # XXX: Probably 'can be written to' could/should be separated from 'acts
    # like a knit index' -- mbp 20071024

    def __init__(self, reload_func=None, flush_func=None):
        """Create an AggregateIndex.

        :param reload_func: A function to call if we find we are missing an
            index. Should have the form reload_func() => True if the list of
            active pack files has changed.
        """
        self._reload_func = reload_func
        self.index_to_pack = {}
        self.combined_index = CombinedGraphIndex([], reload_func=reload_func)
        self.data_access = _DirectPackAccess(
            self.index_to_pack, reload_func=reload_func, flush_func=flush_func
        )
        self.add_callback = None

    def add_index(self, index, pack):
        """Add index to the aggregate, which is an index for Pack pack.

        Future searches on the aggregate index will seach this new index
        before all previously inserted indices.

        :param index: An Index for the pack.
        :param pack: A Pack instance.
        """
        # expose it to the index map
        self.index_to_pack[index] = pack.access_tuple()
        # put it at the front of the linear index list
        self.combined_index.insert_index(0, index, pack.name)

    def add_writable_index(self, index, pack):
        """Add an index which is able to have data added to it.

        There can be at most one writable index at any time.  Any
        modifications made to the knit are put into this index.

        :param index: An index from the pack parameter.
        :param pack: A Pack instance.
        """
        if self.add_callback is not None:
            raise AssertionError(
                "{} already has a writable index through {}".format(
                    self, self.add_callback
                )
            )
        # allow writing: queue writes to a new index
        self.add_index(index, pack)
        # Updates the index to packs mapping as a side effect,
        self.data_access.set_writer(pack._writer, index, pack.access_tuple())
        self.add_callback = index.add_nodes

    def clear(self):
        """Reset all the aggregate data to nothing."""
        self.data_access.set_writer(None, None, (None, None))
        self.index_to_pack.clear()
        del self.combined_index._indices[:]
        del self.combined_index._index_names[:]
        self.add_callback = None

    def remove_index(self, index):
        """Remove index from the indices used to answer queries.

        :param index: An index from the pack parameter.
        """
        del self.index_to_pack[index]
        pos = self.combined_index._indices.index(index)
        del self.combined_index._indices[pos]
        del self.combined_index._index_names[pos]
        if (
            self.add_callback is not None
            and getattr(index, "add_nodes", None) == self.add_callback
        ):
            self.add_callback = None
            self.data_access.set_writer(None, None, (None, None))


class Packer:
    """Create a pack from packs."""

    def __init__(
        self, pack_collection, packs, suffix, revision_ids=None, reload_func=None
    ):
        """Create a Packer.

        :param pack_collection: A RepositoryPackCollection object where the
            new pack is being written to.
        :param packs: The packs to combine.
        :param suffix: The suffix to use on the temporary files for the pack.
        :param revision_ids: Revision ids to limit the pack to.
        :param reload_func: A function to call if a pack file/index goes
            missing. The side effect of calling this function should be to
            update self.packs. See also AggregateIndex
        """
        self.packs = packs
        self.suffix = suffix
        self.revision_ids = revision_ids
        # The pack object we are creating.
        self.new_pack = None
        self._pack_collection = pack_collection
        self._reload_func = reload_func
        # The index layer keys for the revisions being copied. None for 'all
        # objects'.
        self._revision_keys = None
        # What text keys to copy. None for 'all texts'. This is set by
        # _copy_inventory_texts
        self._text_filter = None

    def pack(self, pb=None):
        """Create a new pack by reading data from other packs.

        This does little more than a bulk copy of data. One key difference
        is that data with the same item key across multiple packs is elided
        from the output. The new pack is written into the current pack store
        along with its indices, and the name added to the pack names. The
        source packs are not altered and are not required to be in the current
        pack collection.

        :param pb: An optional progress bar to use. A nested bar is created if
            this is None.
        :return: A Pack object, or None if nothing was copied.
        """
        # open a pack - using the same name as the last temporary file
        # - which has already been flushed, so it's safe.
        # XXX: - duplicate code warning with start_write_group; fix before
        #      considering 'done'.
        if self._pack_collection._new_pack is not None:
            raise errors.BzrError(
                "call to {}.pack() while another pack is being written.".format(
                    self.__class__.__name__
                )
            )
        if self.revision_ids is not None:
            if len(self.revision_ids) == 0:
                # silly fetch request.
                return None
            else:
                self.revision_ids = frozenset(self.revision_ids)
                self.revision_keys = frozenset((revid,) for revid in self.revision_ids)
        if pb is None:
            self.pb = ui.ui_factory.nested_progress_bar()
        else:
            self.pb = pb
        try:
            return self._create_pack_from_packs()
        finally:
            if pb is None:
                self.pb.finished()

    def open_pack(self):
        """Open a pack for the pack we are creating."""
        new_pack = self._pack_collection.pack_factory(
            self._pack_collection,
            upload_suffix=self.suffix,
            file_mode=self._pack_collection.repo.controldir._get_file_mode(),
        )
        # We know that we will process all nodes in order, and don't need to
        # query, so don't combine any indices spilled to disk until we are done
        new_pack.revision_index.set_optimize(combine_backing_indices=False)
        new_pack.inventory_index.set_optimize(combine_backing_indices=False)
        new_pack.text_index.set_optimize(combine_backing_indices=False)
        new_pack.signature_index.set_optimize(combine_backing_indices=False)
        return new_pack

    def _copy_revision_texts(self):
        """Copy revision data to the new pack."""
        raise NotImplementedError(self._copy_revision_texts)

    def _copy_inventory_texts(self):
        """Copy the inventory texts to the new pack.

        self._revision_keys is used to determine what inventories to copy.

        Sets self._text_filter appropriately.
        """
        raise NotImplementedError(self._copy_inventory_texts)

    def _copy_text_texts(self):
        raise NotImplementedError(self._copy_text_texts)

    def _create_pack_from_packs(self):
        raise NotImplementedError(self._create_pack_from_packs)

    def _log_copied_texts(self):
        if "pack" in debug.debug_flags:
            mutter(
                "%s: create_pack: file texts copied: %s%s %d items t+%6.3fs",
                time.ctime(),
                self._pack_collection._upload_transport.base,
                self.new_pack.random_name,
                self.new_pack.text_index.key_count(),
                time.time() - self.new_pack.start_time,
            )

    def _use_pack(self, new_pack):
        """Return True if new_pack should be used.

        :param new_pack: The pack that has just been created.
        :return: True if the pack should be used.
        """
        return new_pack.data_inserted()


class RepositoryPackCollection:
    """Management of packs within a repository.

    :ivar _names: map of {pack_name: (index_size,)}
    """

    pack_factory: type[NewPack]
    resumed_pack_factory: type[ResumedPack]
    normal_packer_class: type[Packer]
    optimising_packer_class: type[Packer]

    def __init__(
        self,
        repo,
        transport,
        index_transport,
        upload_transport,
        pack_transport,
        index_builder_class,
        index_class,
        use_chk_index,
    ):
        """Create a new RepositoryPackCollection.

        :param transport: Addresses the repository base directory
            (typically .bzr/repository/).
        :param index_transport: Addresses the directory containing indices.
        :param upload_transport: Addresses the directory into which packs are written
            while they're being created.
        :param pack_transport: Addresses the directory of existing complete packs.
        :param index_builder_class: The index builder class to use.
        :param index_class: The index class to use.
        :param use_chk_index: Whether to setup and manage a CHK index.
        """
        # XXX: This should call self.reset()
        self.repo = repo
        self.transport = transport
        self._index_transport = index_transport
        self._upload_transport = upload_transport
        self._pack_transport = pack_transport
        self._index_builder_class = index_builder_class
        self._index_class = index_class
        self._suffix_offsets = {".rix": 0, ".iix": 1, ".tix": 2, ".six": 3, ".cix": 4}
        self.packs = []
        # name:Pack mapping
        self._names = None
        self._packs_by_name = {}
        # the previous pack-names content
        self._packs_at_load = None
        # when a pack is being created by this object, the state of that pack.
        self._new_pack = None
        # aggregated revision index data
        flush = self._flush_new_pack
        self.revision_index = AggregateIndex(self.reload_pack_names, flush)
        self.inventory_index = AggregateIndex(self.reload_pack_names, flush)
        self.text_index = AggregateIndex(self.reload_pack_names, flush)
        self.signature_index = AggregateIndex(self.reload_pack_names, flush)
        all_indices = [
            self.revision_index,
            self.inventory_index,
            self.text_index,
            self.signature_index,
        ]
        if use_chk_index:
            self.chk_index = AggregateIndex(self.reload_pack_names, flush)
            all_indices.append(self.chk_index)
        else:
            # used to determine if we're using a chk_index elsewhere.
            self.chk_index = None
        # Tell all the CombinedGraphIndex objects about each other, so they can
        # share hints about which pack names to search first.
        all_combined = [agg_idx.combined_index for agg_idx in all_indices]
        for combined_idx in all_combined:
            combined_idx.set_sibling_indices(
                set(all_combined).difference([combined_idx])
            )
        # resumed packs
        self._resumed_packs = []
        self.config_stack = config.LocationStack(self.transport.base)

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, self.repo)

    def add_pack_to_memory(self, pack):
        """Make a Pack object available to the repository to satisfy queries.

        :param pack: A Pack object.
        """
        if pack.name in self._packs_by_name:
            raise AssertionError("pack {} already in _packs_by_name".format(pack.name))
        self.packs.append(pack)
        self._packs_by_name[pack.name] = pack
        self.revision_index.add_index(pack.revision_index, pack)
        self.inventory_index.add_index(pack.inventory_index, pack)
        self.text_index.add_index(pack.text_index, pack)
        self.signature_index.add_index(pack.signature_index, pack)
        if self.chk_index is not None:
            self.chk_index.add_index(pack.chk_index, pack)

    def all_packs(self):
        """Return a list of all the Pack objects this repository has.

        Note that an in-progress pack being created is not returned.

        :return: A list of Pack objects for all the packs in the repository.
        """
        result = []
        for name in self.names():
            result.append(self.get_pack_by_name(name))
        return result

    def autopack(self):
        """Pack the pack collection incrementally.

        This will not attempt global reorganisation or recompression,
        rather it will just ensure that the total number of packs does
        not grow without bound. It uses the _max_pack_count method to
        determine if autopacking is needed, and the pack_distribution
        method to determine the number of revisions in each pack.

        If autopacking takes place then the packs name collection will have
        been flushed to disk - packing requires updating the name collection
        in synchronisation with certain steps. Otherwise the names collection
        is not flushed.

        :return: Something evaluating true if packing took place.
        """
        while True:
            try:
                return self._do_autopack()
            except RetryAutopack:
                # If we get a RetryAutopack exception, we should abort the
                # current action, and retry.
                pass

    def _do_autopack(self):
        # XXX: Should not be needed when the management of indices is sane.
        total_revisions = self.revision_index.combined_index.key_count()
        total_packs = len(self._names)
        if self._max_pack_count(total_revisions) >= total_packs:
            return None
        # determine which packs need changing
        pack_distribution = self.pack_distribution(total_revisions)
        existing_packs = []
        for pack in self.all_packs():
            revision_count = pack.get_revision_count()
            if revision_count == 0:
                # revision less packs are not generated by normal operation,
                # only by operations like sign-my-commits, and thus will not
                # tend to grow rapdily or without bound like commit containing
                # packs do - leave them alone as packing them really should
                # group their data with the relevant commit, and that may
                # involve rewriting ancient history - which autopack tries to
                # avoid. Alternatively we could not group the data but treat
                # each of these as having a single revision, and thus add
                # one revision for each to the total revision count, to get
                # a matching distribution.
                continue
            existing_packs.append((revision_count, pack))
        pack_operations = self.plan_autopack_combinations(
            existing_packs, pack_distribution
        )
        num_new_packs = len(pack_operations)
        num_old_packs = sum([len(po[1]) for po in pack_operations])
        num_revs_affected = sum([po[0] for po in pack_operations])
        mutter(
            "Auto-packing repository %s, which has %d pack files, "
            "containing %d revisions. Packing %d files into %d affecting %d"
            " revisions",
            str(self),
            total_packs,
            total_revisions,
            num_old_packs,
            num_new_packs,
            num_revs_affected,
        )
        result = self._execute_pack_operations(
            pack_operations,
            packer_class=self.normal_packer_class,
            reload_func=self._restart_autopack,
        )
        mutter("Auto-packing repository %s completed", str(self))
        return result

    def _execute_pack_operations(self, pack_operations, packer_class, reload_func=None):
        """Execute a series of pack operations.

        :param pack_operations: A list of [revision_count, packs_to_combine].
        :param packer_class: The class of packer to use
        :return: The new pack names.
        """
        for _revision_count, packs in pack_operations:
            # we may have no-ops from the setup logic
            if len(packs) == 0:
                continue
            packer = packer_class(self, packs, ".autopack", reload_func=reload_func)
            try:
                result = packer.pack()
            except RetryWithNewPacks:
                # An exception is propagating out of this context, make sure
                # this packer has cleaned up. Packer() doesn't set its new_pack
                # state into the RepositoryPackCollection object, so we only
                # have access to it directly here.
                if packer.new_pack is not None:
                    packer.new_pack.abort()
                raise
            if result is None:
                return
            for pack in packs:
                self._remove_pack_from_memory(pack)
        # record the newly available packs and stop advertising the old
        # packs
        to_be_obsoleted = []
        for _, packs in pack_operations:
            to_be_obsoleted.extend(packs)
        result = self._save_pack_names(
            clear_obsolete_packs=True, obsolete_packs=to_be_obsoleted
        )
        return result

    def _flush_new_pack(self):
        if self._new_pack is not None:
            self._new_pack.flush()

    def lock_names(self):
        """Acquire the mutex around the pack-names index.

        This cannot be used in the middle of a read-only transaction on the
        repository.
        """
        self.repo.control_files.lock_write()

    def _already_packed(self):
        """Is the collection already packed?"""
        return not (self.repo._format.pack_compresses or (len(self._names) > 1))

    def pack(self, hint=None, clean_obsolete_packs=False):
        """Pack the pack collection totally."""
        self.ensure_loaded()
        total_packs = len(self._names)
        if self._already_packed():
            return
        total_revisions = self.revision_index.combined_index.key_count()
        # XXX: the following may want to be a class, to pack with a given
        # policy.
        mutter(
            "Packing repository %s, which has %d pack files, "
            "containing %d revisions with hint %r.",
            str(self),
            total_packs,
            total_revisions,
            hint,
        )
        while True:
            try:
                self._try_pack_operations(hint)
            except RetryPackOperations:
                continue
            break

        if clean_obsolete_packs:
            self._clear_obsolete_packs()

    def _try_pack_operations(self, hint):
        """Calculate the pack operations based on the hint (if any), and
        execute them.
        """
        # determine which packs need changing
        pack_operations = [[0, []]]
        for pack in self.all_packs():
            if hint is None or pack.name in hint:
                # Either no hint was provided (so we are packing everything),
                # or this pack was included in the hint.
                pack_operations[-1][0] += pack.get_revision_count()
                pack_operations[-1][1].append(pack)
        self._execute_pack_operations(
            pack_operations,
            packer_class=self.optimising_packer_class,
            reload_func=self._restart_pack_operations,
        )

    def plan_autopack_combinations(self, existing_packs, pack_distribution):
        """Plan a pack operation.

        :param existing_packs: The packs to pack. (A list of (revcount, Pack)
            tuples).
        :param pack_distribution: A list with the number of revisions desired
            in each pack.
        """
        if len(existing_packs) <= len(pack_distribution):
            return []
        existing_packs.sort(reverse=True)
        pack_operations = [[0, []]]
        # plan out what packs to keep, and what to reorganise
        while len(existing_packs):
            # take the largest pack, and if it's less than the head of the
            # distribution chart we will include its contents in the new pack
            # for that position. If it's larger, we remove its size from the
            # distribution chart
            next_pack_rev_count, next_pack = existing_packs.pop(0)
            if next_pack_rev_count >= pack_distribution[0]:
                # this is already packed 'better' than this, so we can
                # not waste time packing it.
                while next_pack_rev_count > 0:
                    next_pack_rev_count -= pack_distribution[0]
                    if next_pack_rev_count >= 0:
                        # more to go
                        del pack_distribution[0]
                    else:
                        # didn't use that entire bucket up
                        pack_distribution[0] = -next_pack_rev_count
            else:
                # add the revisions we're going to add to the next output pack
                pack_operations[-1][0] += next_pack_rev_count
                # allocate this pack to the next pack sub operation
                pack_operations[-1][1].append(next_pack)
                if pack_operations[-1][0] >= pack_distribution[0]:
                    # this pack is used up, shift left.
                    del pack_distribution[0]
                    pack_operations.append([0, []])
        # Now that we know which pack files we want to move, shove them all
        # into a single pack file.
        final_rev_count = 0
        final_pack_list = []
        for num_revs, pack_files in pack_operations:
            final_rev_count += num_revs
            final_pack_list.extend(pack_files)
        if len(final_pack_list) == 1:
            raise AssertionError(
                "We somehow generated an autopack with a single pack file being moved."
            )
            return []
        return [[final_rev_count, final_pack_list]]

    def ensure_loaded(self):
        """Ensure we have read names from disk.

        :return: True if the disk names had not been previously read.
        """
        # NB: if you see an assertion error here, it's probably access against
        # an unlocked repo. Naughty.
        if not self.repo.is_locked():
            raise errors.ObjectNotLocked(self.repo)
        if self._names is None:
            self._names = {}
            self._packs_at_load = set()
            for _index, key, value in self._iter_disk_pack_index():
                name = key[0].decode("ascii")
                self._names[name] = self._parse_index_sizes(value)
                self._packs_at_load.add((name, value))
            result = True
        else:
            result = False
        # populate all the metadata.
        self.all_packs()
        return result

    def _parse_index_sizes(self, value):
        """Parse a string of index sizes."""
        return tuple(int(digits) for digits in value.split(b" "))

    def get_pack_by_name(self, name):
        """Get a Pack object by name.

        :param name: The name of the pack - e.g. '123456'
        :return: A Pack object.
        """
        try:
            return self._packs_by_name[name]
        except KeyError:
            rev_index = self._make_index(name, ".rix")
            inv_index = self._make_index(name, ".iix")
            txt_index = self._make_index(name, ".tix")
            sig_index = self._make_index(name, ".six")
            if self.chk_index is not None:
                chk_index = self._make_index(name, ".cix", is_chk=True)
            else:
                chk_index = None
            result = ExistingPack(
                self._pack_transport,
                name,
                rev_index,
                inv_index,
                txt_index,
                sig_index,
                chk_index,
            )
            self.add_pack_to_memory(result)
            return result

    def _resume_pack(self, name):
        """Get a suspended Pack object by name.

        :param name: The name of the pack - e.g. '123456'
        :return: A Pack object.
        """
        if not re.match("[a-f0-9]{32}", name):
            # Tokens should be md5sums of the suspended pack file, i.e. 32 hex
            # digits.
            raise errors.UnresumableWriteGroup(
                self.repo, [name], "Malformed write group token"
            )
        try:
            rev_index = self._make_index(name, ".rix", resume=True)
            inv_index = self._make_index(name, ".iix", resume=True)
            txt_index = self._make_index(name, ".tix", resume=True)
            sig_index = self._make_index(name, ".six", resume=True)
            if self.chk_index is not None:
                chk_index = self._make_index(name, ".cix", resume=True, is_chk=True)
            else:
                chk_index = None
            result = self.resumed_pack_factory(
                name,
                rev_index,
                inv_index,
                txt_index,
                sig_index,
                self._upload_transport,
                self._pack_transport,
                self._index_transport,
                self,
                chk_index=chk_index,
            )
        except _mod_transport.NoSuchFile as e:
            raise errors.UnresumableWriteGroup(self.repo, [name], str(e)) from e
        self.add_pack_to_memory(result)
        self._resumed_packs.append(result)
        return result

    def allocate(self, a_new_pack):
        """Allocate name in the list of packs.

        :param a_new_pack: A NewPack instance to be added to the collection of
            packs for this repository.
        """
        self.ensure_loaded()
        if a_new_pack.name in self._names:
            raise errors.BzrError(
                "Pack {!r} already exists in {}".format(a_new_pack.name, self)
            )
        self._names[a_new_pack.name] = tuple(a_new_pack.index_sizes)
        self.add_pack_to_memory(a_new_pack)

    def _iter_disk_pack_index(self):
        """Iterate over the contents of the pack-names index.

        This is used when loading the list from disk, and before writing to
        detect updates from others during our write operation.
        :return: An iterator of the index contents.
        """
        return self._index_class(self.transport, "pack-names", None).iter_all_entries()

    def _make_index(self, name, suffix, resume=False, is_chk=False):
        size_offset = self._suffix_offsets[suffix]
        index_name = name + suffix
        if resume:
            transport = self._upload_transport
            index_size = transport.stat(index_name).st_size
        else:
            transport = self._index_transport
            index_size = self._names[name][size_offset]
        index = self._index_class(
            transport, index_name, index_size, unlimited_cache=is_chk
        )
        if is_chk and self._index_class is btree_index.BTreeGraphIndex:
            index._leaf_factory = btree_index._gcchk_factory
        return index

    def _max_pack_count(self, total_revisions):
        """Return the maximum number of packs to use for total revisions.

        :param total_revisions: The total number of revisions in the
            repository.
        """
        if not total_revisions:
            return 1
        digits = str(total_revisions)
        result = 0
        for digit in digits:
            result += int(digit)
        return result

    def names(self):
        """Provide an order to the underlying names."""
        return sorted(self._names.keys())

    def _obsolete_packs(self, packs):
        """Move a number of packs which have been obsoleted out of the way.

        Each pack and its associated indices are moved out of the way.

        Note: for correctness this function should only be called after a new
        pack names index has been written without these pack names, and with
        the names of packs that contain the data previously available via these
        packs.

        :param packs: The packs to obsolete.
        :param return: None.
        """
        for pack in packs:
            try:
                try:
                    pack.pack_transport.move(
                        pack.file_name(), "../obsolete_packs/" + pack.file_name()
                    )
                except _mod_transport.NoSuchFile:
                    # perhaps obsolete_packs was removed? Let's create it and
                    # try again
                    try:
                        pack.pack_transport.mkdir("../obsolete_packs/")
                    except _mod_transport.FileExists:
                        pass
                    pack.pack_transport.move(
                        pack.file_name(), "../obsolete_packs/" + pack.file_name()
                    )
            except (errors.PathError, errors.TransportError) as e:
                # TODO: Should these be warnings or mutters?
                mutter("couldn't rename obsolete pack, skipping it:\n{}".format(e))
            # TODO: Probably needs to know all possible indices for this pack
            # - or maybe list the directory and move all indices matching this
            # name whether we recognize it or not?
            suffixes = [".iix", ".six", ".tix", ".rix"]
            if self.chk_index is not None:
                suffixes.append(".cix")
            for suffix in suffixes:
                try:
                    self._index_transport.move(
                        pack.name + suffix, "../obsolete_packs/" + pack.name + suffix
                    )
                except (errors.PathError, errors.TransportError) as e:
                    mutter("couldn't rename obsolete index, skipping it:\n{}".format(e))

    def pack_distribution(self, total_revisions):
        """Generate a list of the number of revisions to put in each pack.

        :param total_revisions: The total number of revisions in the
            repository.
        """
        if total_revisions == 0:
            return [0]
        digits = reversed(str(total_revisions))
        result = []
        for exponent, count in enumerate(digits):
            size = 10**exponent
            for _pos in range(int(count)):
                result.append(size)
        return list(reversed(result))

    def _pack_tuple(self, name):
        """Return a tuple with the transport and file name for a pack name."""
        return self._pack_transport, name + ".pack"

    def _remove_pack_from_memory(self, pack):
        """Remove pack from the packs accessed by this repository.

        Only affects memory state, until self._save_pack_names() is invoked.
        """
        self._names.pop(pack.name)
        self._packs_by_name.pop(pack.name)
        self._remove_pack_indices(pack)
        self.packs.remove(pack)

    def _remove_pack_indices(self, pack, ignore_missing=False):
        """Remove the indices for pack from the aggregated indices.

        :param ignore_missing: Suppress KeyErrors from calling remove_index.
        """
        for index_type in Pack.index_definitions:
            attr_name = index_type + "_index"
            aggregate_index = getattr(self, attr_name)
            if aggregate_index is not None:
                pack_index = getattr(pack, attr_name)
                try:
                    aggregate_index.remove_index(pack_index)
                except KeyError:
                    if ignore_missing:
                        continue
                    raise

    def reset(self):
        """Clear all cached data."""
        # cached revision data
        self.revision_index.clear()
        # cached signature data
        self.signature_index.clear()
        # cached file text data
        self.text_index.clear()
        # cached inventory data
        self.inventory_index.clear()
        # cached chk data
        if self.chk_index is not None:
            self.chk_index.clear()
        # remove the open pack
        self._new_pack = None
        # information about packs.
        self._names = None
        self.packs = []
        self._packs_by_name = {}
        self._packs_at_load = None

    def _unlock_names(self):
        """Release the mutex around the pack-names index."""
        self.repo.control_files.unlock()

    def _diff_pack_names(self):
        """Read the pack names from disk, and compare it to the one in memory.

        :return: (disk_nodes, deleted_nodes, new_nodes)
            disk_nodes    The final set of nodes that should be referenced
            deleted_nodes Nodes which have been removed from when we started
            new_nodes     Nodes that are newly introduced
        """
        # load the disk nodes across
        disk_nodes = set()
        for _index, key, value in self._iter_disk_pack_index():
            disk_nodes.add((key[0].decode("ascii"), value))
        orig_disk_nodes = set(disk_nodes)

        # do a two-way diff against our original content
        current_nodes = set()
        for name, sizes in self._names.items():
            current_nodes.add((name, b" ".join(b"%d" % size for size in sizes)))

        # Packs no longer present in the repository, which were present when we
        # locked the repository
        deleted_nodes = self._packs_at_load - current_nodes
        # Packs which this process is adding
        new_nodes = current_nodes - self._packs_at_load

        # Update the disk_nodes set to include the ones we are adding, and
        # remove the ones which were removed by someone else
        disk_nodes.difference_update(deleted_nodes)
        disk_nodes.update(new_nodes)

        return disk_nodes, deleted_nodes, new_nodes, orig_disk_nodes

    def _syncronize_pack_names_from_disk_nodes(self, disk_nodes):
        """Given the correct set of pack files, update our saved info.

        :return: (removed, added, modified)
            removed     pack names removed from self._names
            added       pack names added to self._names
            modified    pack names that had changed value
        """
        removed = []
        added = []
        modified = []
        ## self._packs_at_load = disk_nodes
        new_names = dict(disk_nodes)
        # drop no longer present nodes
        for pack in self.all_packs():
            if pack.name not in new_names:
                removed.append(pack.name)
                self._remove_pack_from_memory(pack)
        # add new nodes/refresh existing ones
        for name, value in disk_nodes:
            sizes = self._parse_index_sizes(value)
            if name in self._names:
                # existing
                if sizes != self._names[name]:
                    # the pack for name has had its indices replaced - rare but
                    # important to handle. XXX: probably can never happen today
                    # because the three-way merge code above does not handle it
                    # - you may end up adding the same key twice to the new
                    # disk index because the set values are the same, unless
                    # the only index shows up as deleted by the set difference
                    # - which it may. Until there is a specific test for this,
                    # assume it's broken. RBC 20071017.
                    self._remove_pack_from_memory(self.get_pack_by_name(name))
                    self._names[name] = sizes
                    self.get_pack_by_name(name)
                    modified.append(name)
            else:
                # new
                self._names[name] = sizes
                self.get_pack_by_name(name)
                added.append(name)
        return removed, added, modified

    def _save_pack_names(self, clear_obsolete_packs=False, obsolete_packs=None):
        """Save the list of packs.

        This will take out the mutex around the pack names list for the
        duration of the method call. If concurrent updates have been made, a
        three-way merge between the current list and the current in memory list
        is performed.

        :param clear_obsolete_packs: If True, clear out the contents of the
            obsolete_packs directory.
        :param obsolete_packs: Packs that are obsolete once the new pack-names
            file has been written.
        :return: A list of the names saved that were not previously on disk.
        """
        already_obsolete = []
        self.lock_names()
        try:
            builder = self._index_builder_class()
            (disk_nodes, _deleted_nodes, new_nodes, _orig_disk_nodes) = (
                self._diff_pack_names()
            )
            # TODO: handle same-name, index-size-changes here -
            # e.g. use the value from disk, not ours, *unless* we're the one
            # changing it.
            for name, value in disk_nodes:
                builder.add_node((name.encode("ascii"),), value)
            self.transport.put_file(
                "pack-names",
                builder.finish(),
                mode=self.repo.controldir._get_file_mode(),
            )
            self._packs_at_load = disk_nodes
            if clear_obsolete_packs:
                to_preserve = None
                if obsolete_packs:
                    to_preserve = {o.name for o in obsolete_packs}
                already_obsolete = self._clear_obsolete_packs(to_preserve)
        finally:
            self._unlock_names()
        # synchronise the memory packs list with what we just wrote:
        self._syncronize_pack_names_from_disk_nodes(disk_nodes)
        if obsolete_packs:
            # TODO: We could add one more condition here. "if o.name not in
            #       orig_disk_nodes and o != the new_pack we haven't written to
            #       disk yet. However, the new pack object is not easily
            #       accessible here (it would have to be passed through the
            #       autopacking code, etc.)
            obsolete_packs = [
                o for o in obsolete_packs if o.name not in already_obsolete
            ]
            self._obsolete_packs(obsolete_packs)
        return [new_node[0] for new_node in new_nodes]

    def reload_pack_names(self):
        """Sync our pack listing with what is present in the repository.

        This should be called when we find out that something we thought was
        present is now missing. This happens when another process re-packs the
        repository, etc.

        :return: True if the in-memory list of packs has been altered at all.
        """
        # The ensure_loaded call is to handle the case where the first call
        # made involving the collection was to reload_pack_names, where we
        # don't have a view of disk contents. It's a bit of a bandaid, and
        # causes two reads of pack-names, but it's a rare corner case not
        # struck with regular push/pull etc.
        first_read = self.ensure_loaded()
        if first_read:
            return True
        # out the new value.
        (disk_nodes, _deleted_nodes, _new_nodes, orig_disk_nodes) = (
            self._diff_pack_names()
        )
        # _packs_at_load is meant to be the explicit list of names in
        # 'pack-names' at then start. As such, it should not contain any
        # pending names that haven't been written out yet.
        self._packs_at_load = orig_disk_nodes
        (removed, added, modified) = self._syncronize_pack_names_from_disk_nodes(
            disk_nodes
        )
        return bool(removed or added or modified)

    def _restart_autopack(self):
        """Reload the pack names list, and restart the autopack code."""
        if not self.reload_pack_names():
            # Re-raise the original exception, because something went missing
            # and a restart didn't find it
            raise
        raise RetryAutopack(self.repo, False, sys.exc_info())

    def _restart_pack_operations(self):
        """Reload the pack names list, and restart the autopack code."""
        if not self.reload_pack_names():
            # Re-raise the original exception, because something went missing
            # and a restart didn't find it
            raise
        raise RetryPackOperations(self.repo, False, sys.exc_info())

    def _clear_obsolete_packs(self, preserve=None):
        """Delete everything from the obsolete-packs directory.

        :return: A list of pack identifiers (the filename without '.pack') that
            were found in obsolete_packs.
        """
        found = []
        obsolete_pack_transport = self.transport.clone("obsolete_packs")
        if preserve is None:
            preserve = set()
        try:
            obsolete_pack_files = obsolete_pack_transport.list_dir(".")
        except _mod_transport.NoSuchFile:
            return found
        for filename in obsolete_pack_files:
            name, ext = osutils.splitext(filename)
            if ext == ".pack":
                found.append(name)
            if name in preserve:
                continue
            try:
                obsolete_pack_transport.delete(filename)
            except (errors.PathError, errors.TransportError) as e:
                warning("couldn't delete obsolete pack, skipping it:\n{}".format(e))
        return found

    def _start_write_group(self):
        # Do not permit preparation for writing if we're not in a 'write lock'.
        if not self.repo.is_write_locked():
            raise errors.NotWriteLocked(self)
        self._new_pack = self.pack_factory(
            self, upload_suffix=".pack", file_mode=self.repo.controldir._get_file_mode()
        )
        # allow writing: queue writes to a new index
        self.revision_index.add_writable_index(
            self._new_pack.revision_index, self._new_pack
        )
        self.inventory_index.add_writable_index(
            self._new_pack.inventory_index, self._new_pack
        )
        self.text_index.add_writable_index(self._new_pack.text_index, self._new_pack)
        self._new_pack.text_index.set_optimize(combine_backing_indices=False)
        self.signature_index.add_writable_index(
            self._new_pack.signature_index, self._new_pack
        )
        if self.chk_index is not None:
            self.chk_index.add_writable_index(self._new_pack.chk_index, self._new_pack)
            self.repo.chk_bytes._index._add_callback = self.chk_index.add_callback
            self._new_pack.chk_index.set_optimize(combine_backing_indices=False)

        self.repo.inventories._index._add_callback = self.inventory_index.add_callback
        self.repo.revisions._index._add_callback = self.revision_index.add_callback
        self.repo.signatures._index._add_callback = self.signature_index.add_callback
        self.repo.texts._index._add_callback = self.text_index.add_callback

    def _abort_write_group(self):
        # FIXME: just drop the transient index.
        # forget what names there are
        if self._new_pack is not None:
            with contextlib.ExitStack() as stack:
                stack.callback(setattr, self, "_new_pack", None)
                # If we aborted while in the middle of finishing the write
                # group, _remove_pack_indices could fail because the indexes are
                # already gone.  But they're not there we shouldn't fail in this
                # case, so we pass ignore_missing=True.
                stack.callback(
                    self._remove_pack_indices, self._new_pack, ignore_missing=True
                )
                self._new_pack.abort()
        for resumed_pack in self._resumed_packs:
            with contextlib.ExitStack() as stack:
                # See comment in previous finally block.
                stack.callback(
                    self._remove_pack_indices, resumed_pack, ignore_missing=True
                )
                resumed_pack.abort()
        del self._resumed_packs[:]

    def _remove_resumed_pack_indices(self):
        for resumed_pack in self._resumed_packs:
            self._remove_pack_indices(resumed_pack)
        del self._resumed_packs[:]

    def _check_new_inventories(self):
        """Detect missing inventories in this write group.

        :returns: list of strs, summarising any problems found.  If the list is
            empty no problems were found.
        """
        # The base implementation does no checks.  GCRepositoryPackCollection
        # overrides this.
        return []

    def _commit_write_group(self):
        all_missing = set()
        for prefix, versioned_file in (
            ("revisions", self.repo.revisions),
            ("inventories", self.repo.inventories),
            ("texts", self.repo.texts),
            ("signatures", self.repo.signatures),
        ):
            missing = versioned_file.get_missing_compression_parent_keys()
            all_missing.update([(prefix,) + key for key in missing])
        if all_missing:
            raise errors.BzrCheckError(
                "Repository {} has missing compression parent(s) {!r} ".format(
                    self.repo, sorted(all_missing)
                )
            )
        problems = self._check_new_inventories()
        if problems:
            problems_summary = "\n".join(problems)
            raise errors.BzrCheckError(
                "Cannot add revision(s) to repository: " + problems_summary
            )
        self._remove_pack_indices(self._new_pack)
        any_new_content = False
        if self._new_pack.data_inserted():
            # get all the data to disk and read to use
            self._new_pack.finish()
            self.allocate(self._new_pack)
            self._new_pack = None
            any_new_content = True
        else:
            self._new_pack.abort()
            self._new_pack = None
        for resumed_pack in self._resumed_packs:
            # XXX: this is a pretty ugly way to turn the resumed pack into a
            # properly committed pack.
            self._names[resumed_pack.name] = None
            self._remove_pack_from_memory(resumed_pack)
            resumed_pack.finish()
            self.allocate(resumed_pack)
            any_new_content = True
        del self._resumed_packs[:]
        if any_new_content:
            result = self.autopack()
            if not result:
                # when autopack takes no steps, the names list is still
                # unsaved.
                return self._save_pack_names()
            return result
        return []

    def _suspend_write_group(self):
        tokens = [pack.name for pack in self._resumed_packs]
        self._remove_pack_indices(self._new_pack)
        if self._new_pack.data_inserted():
            # get all the data to disk and read to use
            self._new_pack.finish(suspend=True)
            tokens.append(self._new_pack.name)
            self._new_pack = None
        else:
            self._new_pack.abort()
            self._new_pack = None
        self._remove_resumed_pack_indices()
        return tokens

    def _resume_write_group(self, tokens):
        for token in tokens:
            self._resume_pack(token)


class PackRepository(MetaDirVersionedFileRepository):
    """Repository with knit objects stored inside pack containers.

    The layering for a KnitPackRepository is:

    Graph        |  HPSS    | Repository public layer |
    ===================================================
    Tuple based apis below, string based, and key based apis above
    ---------------------------------------------------
    VersionedFiles
      Provides .texts, .revisions etc
      This adapts the N-tuple keys to physical knit records which only have a
      single string identifier (for historical reasons), which in older formats
      was always the revision_id, and in the mapped code for packs is always
      the last element of key tuples.
    ---------------------------------------------------
    GraphIndex
      A separate GraphIndex is used for each of the
      texts/inventories/revisions/signatures contained within each individual
      pack file. The GraphIndex layer works in N-tuples and is unaware of any
      semantic value.
    ===================================================

    """

    # These attributes are inherited from the Repository base class. Setting
    # them to None ensures that if the constructor is changed to not initialize
    # them, or a subclass fails to call the constructor, that an error will
    # occur rather than the system working but generating incorrect data.
    _commit_builder_class: type[VersionedFileCommitBuilder]
    _serializer: Serializer

    def __init__(
        self, _format, a_controldir, control_files, _commit_builder_class, _serializer
    ):
        MetaDirRepository.__init__(self, _format, a_controldir, control_files)
        self._commit_builder_class = _commit_builder_class
        self._serializer = _serializer
        self._reconcile_fixes_text_parents = True
        if self._format.supports_external_lookups:
            self._unstacked_provider = graph.CachingParentsProvider(
                self._make_parents_provider_unstacked()
            )
        else:
            self._unstacked_provider = graph.CachingParentsProvider(self)
        self._unstacked_provider.disable_cache()

    def _all_revision_ids(self):
        """See Repository.all_revision_ids()."""
        with self.lock_read():
            return [key[0] for key in self.revisions.keys()]

    def _abort_write_group(self):
        self.revisions._index._key_dependencies.clear()
        self._pack_collection._abort_write_group()

    def _make_parents_provider(self):
        if not self._format.supports_external_lookups:
            return self._unstacked_provider
        return graph.StackedParentsProvider(
            _LazyListJoin([self._unstacked_provider], self._fallback_repositories)
        )

    def _refresh_data(self):
        if not self.is_locked():
            return
        self._pack_collection.reload_pack_names()
        self._unstacked_provider.disable_cache()
        self._unstacked_provider.enable_cache()

    def _start_write_group(self):
        self._pack_collection._start_write_group()

    def _commit_write_group(self):
        hint = self._pack_collection._commit_write_group()
        self.revisions._index._key_dependencies.clear()
        # The commit may have added keys that were previously cached as
        # missing, so reset the cache.
        self._unstacked_provider.disable_cache()
        self._unstacked_provider.enable_cache()
        return hint

    def suspend_write_group(self):
        # XXX check self._write_group is self.get_transaction()?
        tokens = self._pack_collection._suspend_write_group()
        self.revisions._index._key_dependencies.clear()
        self._write_group = None
        return tokens

    def _resume_write_group(self, tokens):
        self._start_write_group()
        try:
            self._pack_collection._resume_write_group(tokens)
        except errors.UnresumableWriteGroup:
            self._abort_write_group()
            raise
        for pack in self._pack_collection._resumed_packs:
            self.revisions._index.scan_unvalidated_index(pack.revision_index)

    def get_transaction(self):
        if self._write_lock_count:
            return self._transaction
        else:
            return self.control_files.get_transaction()

    def is_locked(self):
        return self._write_lock_count or self.control_files.is_locked()

    def is_write_locked(self):
        return self._write_lock_count

    def lock_write(self, token=None):
        """Lock the repository for writes.

        :return: A breezy.repository.RepositoryWriteLockResult.
        """
        locked = self.is_locked()
        if not self._write_lock_count and locked:
            raise errors.ReadOnlyError(self)
        self._write_lock_count += 1
        if self._write_lock_count == 1:
            self._transaction = transactions.WriteTransaction()
        if not locked:
            if "relock" in debug.debug_flags and self._prev_lock == "w":
                note("%r was write locked again", self)
            self._prev_lock = "w"
            self._unstacked_provider.enable_cache()
            for repo in self._fallback_repositories:
                # Writes don't affect fallback repos
                repo.lock_read()
            self._refresh_data()
        return RepositoryWriteLockResult(self.unlock, None)

    def lock_read(self):
        """Lock the repository for reads.

        :return: A breezy.lock.LogicalLockResult.
        """
        locked = self.is_locked()
        if self._write_lock_count:
            self._write_lock_count += 1
        else:
            self.control_files.lock_read()
        if not locked:
            if "relock" in debug.debug_flags and self._prev_lock == "r":
                note("%r was read locked again", self)
            self._prev_lock = "r"
            self._unstacked_provider.enable_cache()
            for repo in self._fallback_repositories:
                repo.lock_read()
            self._refresh_data()
        return LogicalLockResult(self.unlock)

    def leave_lock_in_place(self):
        # not supported - raise an error
        raise NotImplementedError(self.leave_lock_in_place)

    def dont_leave_lock_in_place(self):
        # not supported - raise an error
        raise NotImplementedError(self.dont_leave_lock_in_place)

    def pack(self, hint=None, clean_obsolete_packs=False):
        """Compress the data within the repository.

        This will pack all the data to a single pack. In future it may
        recompress deltas or do other such expensive operations.
        """
        with self.lock_write():
            self._pack_collection.pack(
                hint=hint, clean_obsolete_packs=clean_obsolete_packs
            )

    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from .reconcile import PackReconciler

        with self.lock_write():
            reconciler = PackReconciler(self, thorough=thorough)
            return reconciler.reconcile()

    def _reconcile_pack(self, collection, packs, extension, revs, pb):
        raise NotImplementedError(self._reconcile_pack)

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        if self._write_lock_count == 1 and self._write_group is not None:
            self.abort_write_group()
            self._unstacked_provider.disable_cache()
            self._transaction = None
            self._write_lock_count = 0
            raise errors.BzrError(
                "Must end write group before releasing write lock on {}".format(self)
            )
        if self._write_lock_count:
            self._write_lock_count -= 1
            if not self._write_lock_count:
                transaction = self._transaction
                self._transaction = None
                transaction.finish()
        else:
            self.control_files.unlock()

        if not self.is_locked():
            self._unstacked_provider.disable_cache()
            for repo in self._fallback_repositories:
                repo.unlock()


class RepositoryFormatPack(MetaDirVersionedFileRepositoryFormat):
    """Format logic for pack structured repositories.

    This repository format has:
     - a list of packs in pack-names
     - packs in packs/NAME.pack
     - indices in indices/NAME.{iix,six,tix,rix}
     - knit deltas in the packs, knit indices mapped to the indices.
     - thunk objects to support the knits programming API.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
    """

    # Set this attribute in derived classes to control the repository class
    # created by open and initialize.
    repository_class: type[PackRepository]
    # Set this attribute in derived classes to control the
    # _commit_builder_class that the repository objects will have passed to
    # their constructor.
    _commit_builder_class: type[VersionedFileCommitBuilder]
    # Set this attribute in derived clases to control the _serializer that the
    # repository objects will have passed to their constructor.
    _serializer: Serializer
    # Packs are not confused by ghosts.
    supports_ghosts: bool = True
    # External references are not supported in pack repositories yet.
    supports_external_lookups: bool = False
    # Most pack formats do not use chk lookups.
    supports_chks: bool = False
    # What index classes to use
    index_builder_class: type[_mod_index.GraphIndexBuilder]
    index_class: type[object]
    _fetch_uses_deltas: bool = True
    fast_deltas: bool = False
    supports_funky_characters: bool = True
    revision_graph_can_have_wrong_parents: bool = True

    def initialize(self, a_controldir, shared=False):
        """Create a pack based repository.

        :param a_controldir: bzrdir to contain the new repository; must already
            be initialized.
        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        mutter("creating repository in %s.", a_controldir.transport.base)
        dirs = ["indices", "obsolete_packs", "packs", "upload"]
        builder = self.index_builder_class()
        files = [("pack-names", builder.finish())]
        utf8_files = [("format", self.get_format_string())]

        self._upload_blank_content(a_controldir, dirs, files, utf8_files, shared)
        repository = self.open(a_controldir=a_controldir, _found=True)
        self._run_post_repo_init_hooks(repository, a_controldir, shared)
        return repository

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
        return self.repository_class(
            _format=self,
            a_controldir=a_controldir,
            control_files=control_files,
            _commit_builder_class=self._commit_builder_class,
            _serializer=self._serializer,
        )


class RetryPackOperations(RetryWithNewPacks):
    """Raised when we are packing and we find a missing file.

    Meant as a signaling exception, to tell the RepositoryPackCollection.pack
    code it should try again.
    """

    internal_error = True

    _fmt = (
        "Pack files have changed, reload and try pack again."
        " context: %(context)s %(orig_error)s"
    )


class _DirectPackAccess:
    """Access to data in one or more packs with less translation."""

    def __init__(self, index_to_packs, reload_func=None, flush_func=None):
        """Create a _DirectPackAccess object.

        :param index_to_packs: A dict mapping index objects to the transport
            and file names for obtaining data.
        :param reload_func: A function to call if we determine that the pack
            files have moved and we need to reload our caches. See
            breezy.repo_fmt.pack_repo.AggregateIndex for more details.
        """
        self._container_writer = None
        self._write_index = None
        self._indices = index_to_packs
        self._reload_func = reload_func
        self._flush_func = flush_func

    def add_raw_record(self, key, size, raw_data):
        """Add raw knit bytes to a storage area.

        The data is spooled to the container writer in one bytes-record per
        raw data item.

        :param key: key of the data segment
        :param size: length of the data segment
        :param raw_data: A bytestring containing the data.
        :return: An opaque index memo For _DirectPackAccess the memo is
            (index, pos, length), where the index field is the write_index
            object supplied to the PackAccess object.
        """
        p_offset, p_length = self._container_writer.add_bytes_record(raw_data, size, [])
        return (self._write_index, p_offset, p_length)

    def add_raw_records(self, key_sizes, raw_data):
        """Add raw knit bytes to a storage area.

        The data is spooled to the container writer in one bytes-record per
        raw data item.

        :param sizes: An iterable of tuples containing the key and size of each
            raw data segment.
        :param raw_data: A bytestring containing the data.
        :return: A list of memos to retrieve the record later. Each memo is an
            opaque index memo. For _DirectPackAccess the memo is (index, pos,
            length), where the index field is the write_index object supplied
            to the PackAccess object.
        """
        raw_data = b"".join(raw_data)
        if not isinstance(raw_data, bytes):
            raise AssertionError(
                "data must be plain bytes was {}".format(type(raw_data))
            )
        result = []
        offset = 0
        for key, size in key_sizes:
            result.append(
                self.add_raw_record(key, size, [raw_data[offset : offset + size]])
            )
            offset += size
        return result

    def flush(self):
        """Flush pending writes on this access object.

        This will flush any buffered writes to a NewPack.
        """
        if self._flush_func is not None:
            self._flush_func()

    def get_raw_records(self, memos_for_retrieval):
        """Get the raw bytes for a records.

        :param memos_for_retrieval: An iterable containing the (index, pos,
            length) memo for retrieving the bytes. The Pack access method
            looks up the pack to use for a given record in its index_to_pack
            map.
        :return: An iterator over the bytes of the records.
        """
        # first pass, group into same-index requests
        request_lists = []
        current_index = None
        for index, offset, length in memos_for_retrieval:
            if current_index == index:
                current_list.append((offset, length))
            else:
                if current_index is not None:
                    request_lists.append((current_index, current_list))
                current_index = index
                current_list = [(offset, length)]
        # handle the last entry
        if current_index is not None:
            request_lists.append((current_index, current_list))
        for index, offsets in request_lists:
            try:
                transport, path = self._indices[index]
            except KeyError as e:
                # A KeyError here indicates that someone has triggered an index
                # reload, and this index has gone missing, we need to start
                # over.
                if self._reload_func is None:
                    # If we don't have a _reload_func there is nothing that can
                    # be done
                    raise
                raise RetryWithNewPacks(
                    index, reload_occurred=True, exc_info=sys.exc_info()
                ) from e
            try:
                reader = pack.make_readv_reader(transport, path, offsets)
                for _names, read_func in reader.iter_records():
                    yield read_func(None)
            except _mod_transport.NoSuchFile as e:
                # A NoSuchFile error indicates that a pack file has gone
                # missing on disk, we need to trigger a reload, and start over.
                if self._reload_func is None:
                    raise
                raise RetryWithNewPacks(
                    transport.abspath(path),
                    reload_occurred=False,
                    exc_info=sys.exc_info(),
                ) from e

    def set_writer(self, writer, index, transport_packname):
        """Set a writer to use for adding data."""
        if index is not None:
            self._indices[index] = transport_packname
        self._container_writer = writer
        self._write_index = index

    def reload_or_raise(self, retry_exc):
        """Try calling the reload function, or re-raise the original exception.

        This should be called after _DirectPackAccess raises a
        RetryWithNewPacks exception. This function will handle the common logic
        of determining when the error is fatal versus being temporary.
        It will also make sure that the original exception is raised, rather
        than the RetryWithNewPacks exception.

        If this function returns, then the calling function should retry
        whatever operation was being performed. Otherwise an exception will
        be raised.

        :param retry_exc: A RetryWithNewPacks exception.
        """
        is_error = False
        if self._reload_func is None:
            is_error = True
        elif not self._reload_func():
            # The reload claimed that nothing changed
            if not retry_exc.reload_occurred:
                # If there wasn't an earlier reload, then we really were
                # expecting to find changes. We didn't find them, so this is a
                # hard error
                is_error = True
        if is_error:
            # GZ 2017-03-27: No real reason this needs the original traceback.
            raise retry_exc.exc_info[1]
