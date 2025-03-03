# Copyright (C) 2008-2011 Canonical Ltd
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

"""Core compression logic for compressing streams of related files."""

import time
import zlib

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    debug,
    tsort,
    )
from breezy.bzr import (
    knit,
    pack,
    pack_repo,
    static_tuple,
    )

from breezy.i18n import gettext
""",
)

from .. import errors, osutils, trace
from ..lru_cache import LRUSizeCache
from .btree_index import BTreeBuilder
from .versionedfile import (
    AbsentContentFactory,
    ChunkedContentFactory,
    ExistingContent,
    UnavailableRepresentation,
    VersionedFilesWithFallbacks,
    _KeyRefs,
    adapter_registry,
)

# Minimum number of uncompressed bytes to try fetch at once when retrieving
# groupcompress blocks.
BATCH_SIZE = 2**16

# osutils.sha_string(b'')
_null_sha1 = b"da39a3ee5e6b4b0d3255bfef95601890afd80709"


def sort_gc_optimal(parent_map):
    """Sort and group the keys in parent_map into groupcompress order.

    groupcompress is defined (currently) as reverse-topological order, grouped
    by the key prefix.

    :return: A sorted-list of keys
    """
    # groupcompress ordering is approximately reverse topological,
    # properly grouped by file-id.
    per_prefix_map = {}
    for key, value in parent_map.items():
        if isinstance(key, bytes) or len(key) == 1:
            prefix = b""
        else:
            prefix = key[0]
        try:
            per_prefix_map[prefix][key] = value
        except KeyError:
            per_prefix_map[prefix] = {key: value}

    present_keys = []
    for prefix in sorted(per_prefix_map):
        present_keys.extend(reversed(tsort.topo_sort(per_prefix_map[prefix])))
    return present_keys


class DecompressCorruption(errors.BzrError):
    _fmt = "Corruption while decompressing repository file%(orig_error)s"

    def __init__(self, orig_error=None):
        if orig_error is not None:
            self.orig_error = ", {}".format(orig_error)
        else:
            self.orig_error = ""
        errors.BzrError.__init__(self)


# The max zlib window size is 32kB, so if we set 'max_size' output of the
# decompressor to the requested bytes + 32kB, then we should guarantee
# num_bytes coming out.
_ZLIB_DECOMP_WINDOW = 32 * 1024


class GroupCompressBlock:
    """An object which maintains the internal structure of the compressed data.

    This tracks the meta info (start of text, length, type, etc.)
    """

    # Group Compress Block v1 Zlib
    GCB_HEADER = b"gcb1z\n"
    # Group Compress Block v1 Lzma
    GCB_LZ_HEADER = b"gcb1l\n"
    GCB_KNOWN_HEADERS = (GCB_HEADER, GCB_LZ_HEADER)

    def __init__(self):
        # map by key? or just order in file?
        self._compressor_name = None
        self._z_content_chunks = None
        self._z_content_decompressor = None
        self._z_content_length = None
        self._content_length = None
        self._content = None
        self._content_chunks = None

    def __len__(self):
        # This is the maximum number of bytes this object will reference if
        # everything is decompressed. However, if we decompress less than
        # everything... (this would cause some problems for LRUSizeCache)
        return self._content_length + self._z_content_length

    def _ensure_content(self, num_bytes=None):
        """Make sure that content has been expanded enough.

        :param num_bytes: Ensure that we have extracted at least num_bytes of
            content. If None, consume everything
        """
        if self._content_length is None:
            raise AssertionError("self._content_length should never be None")
        if num_bytes is None:
            num_bytes = self._content_length
        elif self._content_length is not None and num_bytes > self._content_length:
            raise AssertionError(
                f"requested num_bytes ({num_bytes}) > content length ({self._content_length})"
            )
        # Expand the content if required
        if self._content is None:
            if self._content_chunks is not None:
                self._content = b"".join(self._content_chunks)
                self._content_chunks = None
        if self._content is None:
            # We join self._z_content_chunks here, because if we are
            # decompressing, then it is *very* likely that we have a single
            # chunk
            if self._z_content_chunks is None:
                raise AssertionError("No content to decompress")
            z_content = b"".join(self._z_content_chunks)
            if z_content == b"":
                self._content = b""
            elif self._compressor_name == "lzma":
                # We don't do partial lzma decomp yet
                import pylzma

                self._content = pylzma.decompress(z_content)
            elif self._compressor_name == "zlib":
                # Start a zlib decompressor
                if num_bytes * 4 > self._content_length * 3:
                    # If we are requesting more that 3/4ths of the content,
                    # just extract the whole thing in a single pass
                    num_bytes = self._content_length
                    self._content = zlib.decompress(z_content)
                else:
                    self._z_content_decompressor = zlib.decompressobj()
                    # Seed the decompressor with the uncompressed bytes, so
                    # that the rest of the code is simplified
                    self._content = self._z_content_decompressor.decompress(
                        z_content, num_bytes + _ZLIB_DECOMP_WINDOW
                    )
                    if not self._z_content_decompressor.unconsumed_tail:
                        self._z_content_decompressor = None
            else:
                raise AssertionError(
                    "Unknown compressor: {!r}".format(self._compressor_name)
                )
        # Any bytes remaining to be decompressed will be in the decompressors
        # 'unconsumed_tail'

        # Do we have enough bytes already?
        if len(self._content) >= num_bytes:
            return
        # If we got this far, and don't have a decompressor, something is wrong
        if self._z_content_decompressor is None:
            raise AssertionError(f"No decompressor to decompress {num_bytes} bytes")
        remaining_decomp = self._z_content_decompressor.unconsumed_tail
        if not remaining_decomp:
            raise AssertionError("Nothing left to decompress")
        needed_bytes = num_bytes - len(self._content)
        # We always set max_size to 32kB over the minimum needed, so that
        # zlib will give us as much as we really want.
        # TODO: If this isn't good enough, we could make a loop here,
        #       that keeps expanding the request until we get enough
        self._content += self._z_content_decompressor.decompress(
            remaining_decomp, needed_bytes + _ZLIB_DECOMP_WINDOW
        )
        if len(self._content) < num_bytes:
            raise AssertionError(
                f"{num_bytes} bytes wanted, only {len(self._content)} available"
            )
        if not self._z_content_decompressor.unconsumed_tail:
            # The stream is finished
            self._z_content_decompressor = None

    def _parse_bytes(self, data, pos):
        """Read the various lengths from the header.

        This also populates the various 'compressed' buffers.

        :return: The position in bytes just after the last newline
        """
        # At present, we have 2 integers for the compressed and uncompressed
        # content. In base10 (ascii) 14 bytes can represent > 1TB, so to avoid
        # checking too far, cap the search to 14 bytes.
        pos2 = data.index(b"\n", pos, pos + 14)
        self._z_content_length = int(data[pos:pos2])
        pos = pos2 + 1
        pos2 = data.index(b"\n", pos, pos + 14)
        self._content_length = int(data[pos:pos2])
        pos = pos2 + 1
        if len(data) != (pos + self._z_content_length):
            # XXX: Define some GCCorrupt error ?
            raise AssertionError(
                f"Invalid bytes: ({len(data)}) != {pos} + {self._z_content_length}"
            )
        self._z_content_chunks = (data[pos:],)

    @property
    def _z_content(self):
        """Return z_content_chunks as a simple string.

        Meant only to be used by the test suite.
        """
        if self._z_content_chunks is not None:
            return b"".join(self._z_content_chunks)
        return None

    @classmethod
    def from_bytes(cls, bytes):
        out = cls()
        header = bytes[:6]
        if header not in cls.GCB_KNOWN_HEADERS:
            raise ValueError(
                "bytes did not start with any of {!r}".format(cls.GCB_KNOWN_HEADERS)
            )
        if header == cls.GCB_HEADER:
            out._compressor_name = "zlib"
        elif header == cls.GCB_LZ_HEADER:
            out._compressor_name = "lzma"
        else:
            raise ValueError("unknown compressor: {!r}".format(header))
        out._parse_bytes(bytes, 6)
        return out

    def extract(self, key, start, end, sha1=None):
        """Extract the text for a specific key.

        :param key: The label used for this content
        :param sha1: TODO (should we validate only when sha1 is supplied?)
        :return: The bytes for the content
        """
        if start == end == 0:
            return []
        self._ensure_content(end)
        # The bytes are 'f' or 'd' for the type, then a variable-length
        # base128 integer for the content size, then the actual content
        # We know that the variable-length integer won't be longer than 5
        # bytes (it takes 5 bytes to encode 2^32)
        c = self._content[start : start + 1]
        if c == b"f":
            pass
        else:
            if c != b"d":
                raise ValueError("Unknown content control code: {}".format(c))
        content_len, len_len = decode_base128_int(self._content[start + 1 : start + 6])
        content_start = start + 1 + len_len
        if end != content_start + content_len:
            raise ValueError(
                "end != len according to field header {} != {}".format(
                    end, content_start + content_len
                )
            )
        if c == b"f":
            return [self._content[content_start:end]]
        # Must be type delta as checked above
        return [apply_delta_to_source(self._content, content_start, end)]

    def set_chunked_content(self, content_chunks, length):
        """Set the content of this block to the given chunks."""
        # If we have lots of short lines, it is may be more efficient to join
        # the content ahead of time. If the content is <10MiB, we don't really
        # care about the extra memory consumption, so we can just pack it and
        # be done. However, timing showed 18s => 17.9s for repacking 1k revs of
        # mysql, which is below the noise margin
        self._content_length = length
        self._content_chunks = content_chunks
        self._content = None
        self._z_content_chunks = None

    def set_content(self, content):
        """Set the content of this block."""
        self._content_length = len(content)
        self._content = content
        self._z_content_chunks = None

    def _create_z_content_from_chunks(self, chunks):
        compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION)
        # Peak in this point is 1 fulltext, 1 compressed text, + zlib overhead
        # (measured peak is maybe 30MB over the above...)
        compressed_chunks = list(map(compressor.compress, chunks))
        compressed_chunks.append(compressor.flush())
        # Ignore empty chunks
        self._z_content_chunks = [c for c in compressed_chunks if c]
        self._z_content_length = sum(map(len, self._z_content_chunks))

    def _create_z_content(self):
        if self._z_content_chunks is not None:
            return
        if self._content_chunks is not None:
            chunks = self._content_chunks
        else:
            chunks = (self._content,)
        self._create_z_content_from_chunks(chunks)

    def to_chunks(self):
        """Create the byte stream as a series of 'chunks'."""
        self._create_z_content()
        header = self.GCB_HEADER
        chunks = [
            b"%s%d\n%d\n" % (header, self._z_content_length, self._content_length),
        ]
        chunks.extend(self._z_content_chunks)
        total_len = sum(map(len, chunks))
        return total_len, chunks

    def to_bytes(self):
        """Encode the information into a byte stream."""
        total_len, chunks = self.to_chunks()
        return b"".join(chunks)

    def _dump(self, include_text=False):
        """Take this block, and spit out a human-readable structure.

        :param include_text: Inserts also include text bits, chose whether you
            want this displayed in the dump or not.
        :return: A dump of the given block. The layout is something like:
            [('f', length), ('d', delta_length, text_length, [delta_info])]
            delta_info := [('i', num_bytes, text), ('c', offset, num_bytes),
            ...]
        """
        self._ensure_content()
        result = []
        pos = 0
        while pos < self._content_length:
            kind = self._content[pos : pos + 1]
            pos += 1
            if kind not in (b"f", b"d"):
                raise ValueError("invalid kind character: {!r}".format(kind))
            content_len, len_len = decode_base128_int(self._content[pos : pos + 5])
            pos += len_len
            if content_len + pos > self._content_length:
                raise ValueError(
                    f"invalid content_len {content_len} for record @ pos {pos - len_len - 1}"
                )
            if kind == b"f":  # Fulltext
                if include_text:
                    text = self._content[pos : pos + content_len]
                    result.append((b"f", content_len, text))
                else:
                    result.append((b"f", content_len))
            elif kind == b"d":  # Delta
                delta_content = self._content[pos : pos + content_len]
                delta_info = []
                # The first entry in a delta is the decompressed length
                decomp_len, delta_pos = decode_base128_int(delta_content)
                result.append((b"d", content_len, decomp_len, delta_info))
                measured_len = 0
                while delta_pos < content_len:
                    c = delta_content[delta_pos]
                    delta_pos += 1
                    if c & 0x80:  # Copy
                        (offset, length, delta_pos) = decode_copy_instruction(
                            delta_content, c, delta_pos
                        )
                        if include_text:
                            text = self._content[offset : offset + length]
                            delta_info.append((b"c", offset, length, text))
                        else:
                            delta_info.append((b"c", offset, length))
                        measured_len += length
                    else:  # Insert
                        if include_text:
                            txt = delta_content[delta_pos : delta_pos + c]
                        else:
                            txt = b""
                        delta_info.append((b"i", c, txt))
                        measured_len += c
                        delta_pos += c
                if delta_pos != content_len:
                    raise ValueError(
                        f"Delta consumed a bad number of bytes: {delta_pos} != {content_len}"
                    )
                if measured_len != decomp_len:
                    raise ValueError(
                        f"Delta claimed fulltext was {decomp_len} bytes, but extraction resulted in {measured_len} bytes"
                    )
            pos += content_len
        return result


class _LazyGroupCompressFactory:
    """Yield content from a GroupCompressBlock on demand."""

    def __init__(self, key, parents, manager, start, end, first):
        """Create a _LazyGroupCompressFactory.

        :param key: The key of just this record
        :param parents: The parents of this key (possibly None)
        :param gc_block: A GroupCompressBlock object
        :param start: Offset of the first byte for this record in the
            uncompressd content
        :param end: Offset of the byte just after the end of this record
            (ie, bytes = content[start:end])
        :param first: Is this the first Factory for the given block?
        """
        self.key = key
        self.parents = parents
        self.sha1 = None
        self.size = None
        # Note: This attribute coupled with Manager._factories creates a
        #       reference cycle. Perhaps we would rather use a weakref(), or
        #       find an appropriate time to release the ref. After the first
        #       get_bytes_as call? After Manager.get_record_stream() returns
        #       the object?
        self._manager = manager
        self._chunks = None
        self.storage_kind = "groupcompress-block"
        if not first:
            self.storage_kind = "groupcompress-block-ref"
        self._first = first
        self._start = start
        self._end = end

    def __repr__(self):
        return "{}({}, first={})".format(self.__class__.__name__, self.key, self._first)

    def _extract_bytes(self):
        # Grab and cache the raw bytes for this entry
        # and break the ref-cycle with _manager since we don't need it
        # anymore
        try:
            self._manager._prepare_for_extract()
        except zlib.error as value:
            raise DecompressCorruption(f"zlib: {value!s}") from value
        block = self._manager._block
        self._chunks = block.extract(self.key, self._start, self._end)
        # There are code paths that first extract as fulltext, and then
        # extract as storage_kind (smart fetch). So we don't break the
        # refcycle here, but instead in manager.get_record_stream()

    def get_bytes_as(self, storage_kind):
        if storage_kind == self.storage_kind:
            if self._first:
                # wire bytes, something...
                return self._manager._wire_bytes()
            else:
                return b""
        if storage_kind in ("fulltext", "chunked", "lines"):
            if self._chunks is None:
                self._extract_bytes()
            if storage_kind == "fulltext":
                return b"".join(self._chunks)
            elif storage_kind == "chunked":
                return self._chunks
            else:
                return osutils.chunks_to_lines(self._chunks)
        raise UnavailableRepresentation(self.key, storage_kind, self.storage_kind)

    def iter_bytes_as(self, storage_kind):
        if self._chunks is None:
            self._extract_bytes()
        if storage_kind == "chunked":
            return iter(self._chunks)
        elif storage_kind == "lines":
            return iter(osutils.chunks_to_lines(self._chunks))
        raise UnavailableRepresentation(self.key, storage_kind, self.storage_kind)


class _LazyGroupContentManager:
    """This manages a group of _LazyGroupCompressFactory objects."""

    _max_cut_fraction = 0.75  # We allow a block to be trimmed to 75% of
    # current size, and still be considered
    # resuable
    _full_block_size = 4 * 1024 * 1024
    _full_mixed_block_size = 2 * 1024 * 1024
    _full_enough_block_size = 3 * 1024 * 1024  # size at which we won't repack
    _full_enough_mixed_block_size = 2 * 768 * 1024  # 1.5MB

    def __init__(self, block, get_compressor_settings=None):
        self._block = block
        # We need to preserve the ordering
        self._factories = []
        self._last_byte = 0
        self._get_settings = get_compressor_settings
        self._compressor_settings = None

    def _get_compressor_settings(self):
        if self._compressor_settings is not None:
            return self._compressor_settings
        settings = None
        if self._get_settings is not None:
            settings = self._get_settings()
        if settings is None:
            vf = GroupCompressVersionedFiles
            settings = vf._DEFAULT_COMPRESSOR_SETTINGS
        self._compressor_settings = settings
        return self._compressor_settings

    def add_factory(self, key, parents, start, end):
        if not self._factories:
            first = True
        else:
            first = False
        # Note that this creates a reference cycle....
        factory = _LazyGroupCompressFactory(key, parents, self, start, end, first=first)
        # max() works here, but as a function call, doing a compare seems to be
        # significantly faster, timeit says 250ms for max() and 100ms for the
        # comparison
        if end > self._last_byte:
            self._last_byte = end
        self._factories.append(factory)

    def get_record_stream(self):
        """Get a record for all keys added so far."""
        for factory in self._factories:
            yield factory
            # Break the ref-cycle
            factory._bytes = None
            factory._manager = None
        # TODO: Consider setting self._factories = None after the above loop,
        #       as it will break the reference cycle

    def _trim_block(self, last_byte):
        """Create a new GroupCompressBlock, with just some of the content."""
        # None of the factories need to be adjusted, because the content is
        # located in an identical place. Just that some of the unreferenced
        # trailing bytes are stripped
        trace.mutter(
            "stripping trailing bytes from groupcompress block %d => %d",
            self._block._content_length,
            last_byte,
        )
        new_block = GroupCompressBlock()
        self._block._ensure_content(last_byte)
        new_block.set_content(self._block._content[:last_byte])
        self._block = new_block

    def _make_group_compressor(self):
        return GroupCompressor(self._get_compressor_settings())

    def _rebuild_block(self):
        """Create a new GroupCompressBlock with only the referenced texts."""
        compressor = self._make_group_compressor()
        tstart = time.time()
        old_length = self._block._content_length
        end_point = 0
        for factory in self._factories:
            chunks = factory.get_bytes_as("chunked")
            chunks_len = factory.size
            if chunks_len is None:
                chunks_len = sum(map(len, chunks))
            (found_sha1, start_point, end_point, type) = compressor.compress(
                factory.key, chunks, chunks_len, factory.sha1
            )
            # Now update this factory with the new offsets, etc
            factory.sha1 = found_sha1
            factory._start = start_point
            factory._end = end_point
        self._last_byte = end_point
        new_block = compressor.flush()
        # TODO: Should we check that new_block really *is* smaller than the old
        #       block? It seems hard to come up with a method that it would
        #       expand, since we do full compression again. Perhaps based on a
        #       request that ends up poorly ordered?
        # TODO: If the content would have expanded, then we would want to
        #       handle a case where we need to split the block.
        #       Now that we have a user-tweakable option
        #       (max_bytes_to_index), it is possible that one person set it
        #       to a very low value, causing poor compression.
        delta = time.time() - tstart
        self._block = new_block
        trace.mutter(
            "creating new compressed block on-the-fly in %.3fs %d bytes => %d bytes",
            delta,
            old_length,
            self._block._content_length,
        )

    def _prepare_for_extract(self):
        """A _LazyGroupCompressFactory is about to extract to fulltext."""
        # We expect that if one child is going to fulltext, all will be. This
        # helps prevent all of them from extracting a small amount at a time.
        # Which in itself isn't terribly expensive, but resizing 2MB 32kB at a
        # time (self._block._content) is a little expensive.
        self._block._ensure_content(self._last_byte)

    def _check_rebuild_action(self):
        """Check to see if our block should be repacked."""
        total_bytes_used = 0
        last_byte_used = 0
        for factory in self._factories:
            total_bytes_used += factory._end - factory._start
            if last_byte_used < factory._end:
                last_byte_used = factory._end
        # If we are using more than half of the bytes from the block, we have
        # nothing else to check
        if total_bytes_used * 2 >= self._block._content_length:
            return None, last_byte_used, total_bytes_used
        # We are using less than 50% of the content. Is the content we are
        # using at the beginning of the block? If so, we can just trim the
        # tail, rather than rebuilding from scratch.
        if total_bytes_used * 2 > last_byte_used:
            return "trim", last_byte_used, total_bytes_used

        # We are using a small amount of the data, and it isn't just packed
        # nicely at the front, so rebuild the content.
        # Note: This would be *nicer* as a strip-data-from-group, rather than
        #       building it up again from scratch
        #       It might be reasonable to consider the fulltext sizes for
        #       different bits when deciding this, too. As you may have a small
        #       fulltext, and a trivial delta, and you are just trading around
        #       for another fulltext. If we do a simple 'prune' you may end up
        #       expanding many deltas into fulltexts, as well.
        #       If we build a cheap enough 'strip', then we could try a strip,
        #       if that expands the content, we then rebuild.
        return "rebuild", last_byte_used, total_bytes_used

    def check_is_well_utilized(self):
        """Is the current block considered 'well utilized'?

        This heuristic asks if the current block considers itself to be a fully
        developed group, rather than just a loose collection of data.
        """
        if len(self._factories) == 1:
            # A block of length 1 could be improved by combining with other
            # groups - don't look deeper. Even larger than max size groups
            # could compress well with adjacent versions of the same thing.
            return False
        action, last_byte_used, total_bytes_used = self._check_rebuild_action()
        block_size = self._block._content_length
        if total_bytes_used < block_size * self._max_cut_fraction:
            # This block wants to trim itself small enough that we want to
            # consider it under-utilized.
            return False
        # TODO: This code is meant to be the twin of _insert_record_stream's
        #       'start_new_block' logic. It would probably be better to factor
        #       out that logic into a shared location, so that it stays
        #       together better
        # We currently assume a block is properly utilized whenever it is >75%
        # of the size of a 'full' block. In normal operation, a block is
        # considered full when it hits 4MB of same-file content. So any block
        # >3MB is 'full enough'.
        # The only time this isn't true is when a given block has large-object
        # content. (a single file >4MB, etc.)
        # Under these circumstances, we allow a block to grow to
        # 2 x largest_content.  Which means that if a given block had a large
        # object, it may actually be under-utilized. However, given that this
        # is 'pack-on-the-fly' it is probably reasonable to not repack large
        # content blobs on-the-fly. Note that because we return False for all
        # 1-item blobs, we will repack them; we may wish to reevaluate our
        # treatment of large object blobs in the future.
        if block_size >= self._full_enough_block_size:
            return True
        # If a block is <3MB, it still may be considered 'full' if it contains
        # mixed content. The current rule is 2MB of mixed content is considered
        # full. So check to see if this block contains mixed content, and
        # set the threshold appropriately.
        common_prefix = None
        for factory in self._factories:
            prefix = factory.key[:-1]
            if common_prefix is None:
                common_prefix = prefix
            elif prefix != common_prefix:
                # Mixed content, check the size appropriately
                if block_size >= self._full_enough_mixed_block_size:
                    return True
                break
        # The content failed both the mixed check and the single-content check
        # so obviously it is not fully utilized
        # TODO: there is one other constraint that isn't being checked
        #       namely, that the entries in the block are in the appropriate
        #       order. For example, you could insert the entries in exactly
        #       reverse groupcompress order, and we would think that is ok.
        #       (all the right objects are in one group, and it is fully
        #       utilized, etc.) For now, we assume that case is rare,
        #       especially since we should always fetch in 'groupcompress'
        #       order.
        return False

    def _check_rebuild_block(self):
        action, last_byte_used, total_bytes_used = self._check_rebuild_action()
        if action is None:
            return
        if action == "trim":
            self._trim_block(last_byte_used)
        elif action == "rebuild":
            self._rebuild_block()
        else:
            raise ValueError("unknown rebuild action: {!r}".format(action))

    def _wire_bytes(self):
        """Return a byte stream suitable for transmitting over the wire."""
        self._check_rebuild_block()
        # The outer block starts with:
        #   'groupcompress-block\n'
        #   <length of compressed key info>\n
        #   <length of uncompressed info>\n
        #   <length of gc block>\n
        #   <header bytes>
        #   <gc-block>
        lines = [b"groupcompress-block\n"]
        # The minimal info we need is the key, the start offset, and the
        # parents. The length and type are encoded in the record itself.
        # However, passing in the other bits makes it easier.  The list of
        # keys, and the start offset, the length
        # 1 line key
        # 1 line with parents, '' for ()
        # 1 line for start offset
        # 1 line for end byte
        header_lines = []
        for factory in self._factories:
            key_bytes = b"\x00".join(factory.key)
            parents = factory.parents
            if parents is None:
                parent_bytes = b"None:"
            else:
                parent_bytes = b"\t".join(b"\x00".join(key) for key in parents)
            record_header = b"%s\n%s\n%d\n%d\n" % (
                key_bytes,
                parent_bytes,
                factory._start,
                factory._end,
            )
            header_lines.append(record_header)
            # TODO: Can we break the refcycle at this point and set
            #       factory._manager = None?
        header_bytes = b"".join(header_lines)
        del header_lines
        header_bytes_len = len(header_bytes)
        z_header_bytes = zlib.compress(header_bytes)
        del header_bytes
        z_header_bytes_len = len(z_header_bytes)
        block_bytes_len, block_chunks = self._block.to_chunks()
        lines.append(
            b"%d\n%d\n%d\n" % (z_header_bytes_len, header_bytes_len, block_bytes_len)
        )
        lines.append(z_header_bytes)
        lines.extend(block_chunks)
        del z_header_bytes, block_chunks
        # TODO: This is a point where we will double the memory consumption. To
        #       avoid this, we probably have to switch to a 'chunked' api
        return b"".join(lines)

    @classmethod
    def from_bytes(cls, bytes):
        # TODO: This does extra string copying, probably better to do it a
        #       different way. At a minimum this creates 2 copies of the
        #       compressed content
        (storage_kind, z_header_len, header_len, block_len, rest) = bytes.split(
            b"\n", 4
        )
        del bytes
        if storage_kind != b"groupcompress-block":
            raise ValueError("Unknown storage kind: {}".format(storage_kind))
        z_header_len = int(z_header_len)
        if len(rest) < z_header_len:
            raise ValueError("Compressed header len shorter than all bytes")
        z_header = rest[:z_header_len]
        header_len = int(header_len)
        header = zlib.decompress(z_header)
        if len(header) != header_len:
            raise ValueError("invalid length for decompressed bytes")
        del z_header
        block_len = int(block_len)
        if len(rest) != z_header_len + block_len:
            raise ValueError("Invalid length for block")
        block_bytes = rest[z_header_len:]
        del rest
        # So now we have a valid GCB, we just need to parse the factories that
        # were sent to us
        header_lines = header.split(b"\n")
        del header
        last = header_lines.pop()
        if last != b"":
            raise ValueError("header lines did not end with a trailing newline")
        if len(header_lines) % 4 != 0:
            raise ValueError("The header was not an even multiple of 4 lines")
        block = GroupCompressBlock.from_bytes(block_bytes)
        del block_bytes
        result = cls(block)
        for start in range(0, len(header_lines), 4):
            # intern()?
            key = tuple(header_lines[start].split(b"\x00"))
            parents_line = header_lines[start + 1]
            if parents_line == b"None:":
                parents = None
            else:
                parents = tuple(
                    [
                        tuple(segment.split(b"\x00"))
                        for segment in parents_line.split(b"\t")
                        if segment
                    ]
                )
            start_offset = int(header_lines[start + 2])
            end_offset = int(header_lines[start + 3])
            result.add_factory(key, parents, start_offset, end_offset)
        return result


def network_block_to_records(storage_kind, bytes, line_end):
    if storage_kind != "groupcompress-block":
        raise ValueError("Unknown storage kind: {}".format(storage_kind))
    manager = _LazyGroupContentManager.from_bytes(bytes)
    return manager.get_record_stream()


class _CommonGroupCompressor:
    def __init__(self, settings=None):
        """Create a GroupCompressor."""
        self.chunks = []
        self._last = None
        self.endpoint = 0
        self.input_bytes = 0
        self.labels_deltas = {}
        self._delta_index = None  # Set by the children
        self._block = GroupCompressBlock()
        if settings is None:
            self._settings = {}
        else:
            self._settings = settings

    def compress(self, key, chunks, length, expected_sha, nostore_sha=None, soft=False):
        """Compress lines with label key.

        :param key: A key tuple. It is stored in the output
            for identification of the text during decompression. If the last
            element is b'None' it is replaced with the sha1 of the text -
            e.g. sha1:xxxxxxx.
        :param chunks: Chunks of bytes to be compressed
        :param length: Length of chunks
        :param expected_sha: If non-None, the sha the lines are believed to
            have. During compression the sha is calculated; a mismatch will
            cause an error.
        :param nostore_sha: If the computed sha1 sum matches, we will raise
            ExistingContent rather than adding the text.
        :param soft: Do a 'soft' compression. This means that we require larger
            ranges to match to be considered for a copy command.

        :return: The sha1 of lines, the start and end offsets in the delta, and
            the type ('fulltext' or 'delta').

        :seealso VersionedFiles.add_lines:
        """
        if length == 0:  # empty, like a dir entry, etc
            if nostore_sha == _null_sha1:
                raise ExistingContent()
            return _null_sha1, 0, 0, "fulltext"
        # we assume someone knew what they were doing when they passed it in
        if expected_sha is not None:
            sha1 = expected_sha
        else:
            sha1 = osutils.sha_strings(chunks)
        if nostore_sha is not None:
            if sha1 == nostore_sha:
                raise ExistingContent()
        if key[-1] is None:
            key = key[:-1] + (b"sha1:" + sha1,)

        start, end, type = self._compress(key, chunks, length, length / 2, soft)
        return sha1, start, end, type

    def _compress(self, key, chunks, input_len, max_delta_size, soft=False):
        """Compress lines with label key.

        :param key: A key tuple. It is stored in the output for identification
            of the text during decompression.

        :param chunks: The chunks of bytes to be compressed

        :param input_len: The length of the chunks

        :param max_delta_size: The size above which we issue a fulltext instead
            of a delta.

        :param soft: Do a 'soft' compression. This means that we require larger
            ranges to match to be considered for a copy command.

        :return: The sha1 of lines, the start and end offsets in the delta, and
            the type ('fulltext' or 'delta').
        """
        raise NotImplementedError(self._compress)

    def extract(self, key):
        """Extract a key previously added to the compressor.

        :param key: The key to extract.
        :return: An iterable over chunks and the sha1.
        """
        (start_byte, start_chunk, end_byte, end_chunk) = self.labels_deltas[key]
        delta_chunks = self.chunks[start_chunk:end_chunk]
        stored_bytes = b"".join(delta_chunks)
        kind = stored_bytes[:1]
        if kind == b"f":
            fulltext_len, offset = decode_base128_int(stored_bytes[1:10])
            data_len = fulltext_len + 1 + offset
            if data_len != len(stored_bytes):
                raise ValueError(
                    "Index claimed fulltext len, but stored bytes"
                    " claim {} != {}".format(len(stored_bytes), data_len)
                )
            data = [stored_bytes[offset + 1 :]]
        else:
            if kind != b"d":
                raise ValueError("Unknown content kind, bytes claim {}".format(kind))
            # XXX: This is inefficient at best
            source = b"".join(self.chunks[:start_chunk])
            delta_len, offset = decode_base128_int(stored_bytes[1:10])
            data_len = delta_len + 1 + offset
            if data_len != len(stored_bytes):
                raise ValueError(
                    "Index claimed delta len, but stored bytes claim {} != {}".format(
                        len(stored_bytes), data_len
                    )
                )
            data = [apply_delta(source, stored_bytes[offset + 1 :])]
        data_sha1 = osutils.sha_strings(data)
        return data, data_sha1

    def flush(self):
        """Finish this group, creating a formatted stream.

        After calling this, the compressor should no longer be used
        """
        self._block.set_chunked_content(self.chunks, self.endpoint)
        self.chunks = None
        self._delta_index = None
        return self._block

    def pop_last(self):
        """Call this if you want to 'revoke' the last compression.

        After this, the data structures will be rolled back, but you cannot do
        more compression.
        """
        self._delta_index = None
        del self.chunks[self._last[0] :]
        self.endpoint = self._last[1]
        self._last = None

    def ratio(self):
        """Return the overall compression ratio."""
        return float(self.input_bytes) / float(self.endpoint)


class PythonGroupCompressor(_CommonGroupCompressor):
    def __init__(self, settings=None):
        """Create a GroupCompressor.

        Used only if the pyrex version is not available.
        """
        super().__init__(settings)
        self._delta_index = LinesDeltaIndex([])
        # The actual content is managed by LinesDeltaIndex
        self.chunks = self._delta_index.lines

    def _compress(self, key, chunks, input_len, max_delta_size, soft=False):
        """See _CommonGroupCompressor._compress."""
        new_lines = osutils.chunks_to_lines(chunks)
        out_lines, index_lines = self._delta_index.make_delta(
            new_lines, bytes_length=input_len, soft=soft
        )
        delta_length = sum(map(len, out_lines))
        if delta_length > max_delta_size:
            # The delta is longer than the fulltext, insert a fulltext
            type = "fulltext"
            out_lines = [b"f", encode_base128_int(input_len)]
            out_lines.extend(new_lines)
            index_lines = [False, False]
            index_lines.extend([True] * len(new_lines))
        else:
            # this is a worthy delta, output it
            type = "delta"
            out_lines[0] = b"d"
            # Update the delta_length to include those two encoded integers
            out_lines[1] = encode_base128_int(delta_length)
        # Before insertion
        start = self.endpoint
        chunk_start = len(self.chunks)
        self._last = (chunk_start, self.endpoint)
        self._delta_index.extend_lines(out_lines, index_lines)
        self.endpoint = self._delta_index.endpoint
        self.input_bytes += input_len
        chunk_end = len(self.chunks)
        self.labels_deltas[key] = (start, chunk_start, self.endpoint, chunk_end)
        return start, self.endpoint, type


class PyrexGroupCompressor(_CommonGroupCompressor):
    """Produce a serialised group of compressed texts.

    It contains code very similar to SequenceMatcher because of having a similar
    task. However some key differences apply:

    * there is no junk, we want a minimal edit not a human readable diff.
    * we don't filter very common lines (because we don't know where a good
      range will start, and after the first text we want to be emitting minmal
      edits only.
    * we chain the left side, not the right side
    * we incrementally update the adjacency matrix as new lines are provided.
    * we look for matches in all of the left side, so the routine which does
      the analagous task of find_longest_match does not need to filter on the
      left side.
    """

    def __init__(self, settings=None):
        super().__init__(settings)
        max_bytes_to_index = self._settings.get("max_bytes_to_index", 0)
        self._delta_index = DeltaIndex(max_bytes_to_index=max_bytes_to_index)

    def _compress(self, key, chunks, input_len, max_delta_size, soft=False):
        """See _CommonGroupCompressor._compress."""
        # By having action/label/sha1/len, we can parse the group if the index
        # was ever destroyed, we have the key in 'label', we know the final
        # bytes are valid from sha1, and we know where to find the end of this
        # record because of 'len'. (the delta record itself will store the
        # total length for the expanded record)
        # 'len: %d\n' costs approximately 1% increase in total data
        # Having the labels at all costs us 9-10% increase, 38% increase for
        # inventory pages, and 5.8% increase for text pages
        # new_chunks = ['label:%s\nsha1:%s\n' % (label, sha1)]
        if self._delta_index._source_offset != self.endpoint:
            raise AssertionError(
                "_source_offset != endpoint"
                " somehow the DeltaIndex got out of sync with"
                " the output lines"
            )
        bytes = b"".join(chunks)
        delta = self._delta_index.make_delta(bytes, max_delta_size)
        if delta is None:
            type = "fulltext"
            enc_length = encode_base128_int(input_len)
            len_mini_header = 1 + len(enc_length)
            self._delta_index.add_source(bytes, len_mini_header)
            new_chunks = [b"f", enc_length] + chunks
        else:
            type = "delta"
            enc_length = encode_base128_int(len(delta))
            len_mini_header = 1 + len(enc_length)
            new_chunks = [b"d", enc_length, delta]
            self._delta_index.add_delta_source(delta, len_mini_header)
        # Before insertion
        start = self.endpoint
        chunk_start = len(self.chunks)
        # Now output these bytes
        self._output_chunks(new_chunks)
        self.input_bytes += input_len
        chunk_end = len(self.chunks)
        self.labels_deltas[key] = (start, chunk_start, self.endpoint, chunk_end)
        if not self._delta_index._source_offset == self.endpoint:
            raise AssertionError(
                "the delta index is out of syncwith the output lines {} != {}".format(
                    self._delta_index._source_offset, self.endpoint
                )
            )
        return start, self.endpoint, type

    def _output_chunks(self, new_chunks):
        """Output some chunks.

        :param new_chunks: The chunks to output.
        """
        self._last = (len(self.chunks), self.endpoint)
        endpoint = self.endpoint
        self.chunks.extend(new_chunks)
        endpoint += sum(map(len, new_chunks))
        self.endpoint = endpoint


def make_pack_factory(graph, delta, keylength, inconsistency_fatal=True):
    """Create a factory for creating a pack based groupcompress.

    This is only functional enough to run interface tests, it doesn't try to
    provide a full pack environment.

    :param graph: Store a graph.
    :param delta: Delta compress contents.
    :param keylength: How long should keys be.
    """
    from .pack import ContainerWriter
    from .pack_repo import _DirectPackAccess

    def factory(transport):
        parents = graph
        ref_length = 0
        if graph:
            ref_length = 1
        graph_index = BTreeBuilder(reference_lists=ref_length, key_elements=keylength)
        stream = transport.open_write_stream("newpack")
        writer = ContainerWriter(stream.write)
        writer.begin()
        index = _GCGraphIndex(
            graph_index,
            lambda: True,
            parents=parents,
            add_callback=graph_index.add_nodes,
            inconsistency_fatal=inconsistency_fatal,
        )
        access = _DirectPackAccess({})
        access.set_writer(writer, graph_index, (transport, "newpack"))
        result = GroupCompressVersionedFiles(index, access, delta)
        result.stream = stream
        result.writer = writer
        return result

    return factory


def cleanup_pack_group(versioned_files):
    versioned_files.writer.end()
    versioned_files.stream.close()


class _BatchingBlockFetcher:
    """Fetch group compress blocks in batches.

    :ivar total_bytes: int of expected number of bytes needed to fetch the
        currently pending batch.
    """

    def __init__(self, gcvf, locations, get_compressor_settings=None):
        self.gcvf = gcvf
        self.locations = locations
        self.keys = []
        self.batch_memos = {}
        self.memos_to_get = []
        self.total_bytes = 0
        self.last_read_memo = None
        self.manager = None
        self._get_compressor_settings = get_compressor_settings

    def add_key(self, key):
        """Add another to key to fetch.

        :return: The estimated number of bytes needed to fetch the batch so
            far.
        """
        self.keys.append(key)
        index_memo, _, _, _ = self.locations[key]
        read_memo = index_memo[0:3]
        # Three possibilities for this read_memo:
        #  - it's already part of this batch; or
        #  - it's not yet part of this batch, but is already cached; or
        #  - it's not yet part of this batch and will need to be fetched.
        if read_memo in self.batch_memos:
            # This read memo is already in this batch.
            return self.total_bytes
        try:
            cached_block = self.gcvf._group_cache[read_memo]
        except KeyError:
            # This read memo is new to this batch, and the data isn't cached
            # either.
            self.batch_memos[read_memo] = None
            self.memos_to_get.append(read_memo)
            byte_length = read_memo[2]
            self.total_bytes += byte_length
        else:
            # This read memo is new to this batch, but cached.
            # Keep a reference to the cached block in batch_memos because it's
            # certain that we'll use it when this batch is processed, but
            # there's a risk that it would fall out of _group_cache between now
            # and then.
            self.batch_memos[read_memo] = cached_block
        return self.total_bytes

    def _flush_manager(self):
        if self.manager is not None:
            yield from self.manager.get_record_stream()
            self.manager = None
            self.last_read_memo = None

    def yield_factories(self, full_flush=False):
        """Yield factories for keys added since the last yield.  They will be
        returned in the order they were added via add_key.

        :param full_flush: by default, some results may not be returned in case
            they can be part of the next batch.  If full_flush is True, then
            all results are returned.
        """
        if self.manager is None and not self.keys:
            return
        # Fetch all memos in this batch.
        blocks = self.gcvf._get_blocks(self.memos_to_get)
        # Turn blocks into factories and yield them.
        memos_to_get_stack = list(self.memos_to_get)
        memos_to_get_stack.reverse()
        for key in self.keys:
            index_memo, _, parents, _ = self.locations[key]
            read_memo = index_memo[:3]
            if self.last_read_memo != read_memo:
                # We are starting a new block. If we have a
                # manager, we have found everything that fits for
                # now, so yield records
                yield from self._flush_manager()
                # Now start a new manager.
                if memos_to_get_stack and memos_to_get_stack[-1] == read_memo:
                    # The next block from _get_blocks will be the block we
                    # need.
                    block_read_memo, block = next(blocks)
                    if block_read_memo != read_memo:
                        raise AssertionError(
                            "block_read_memo out of sync with read_memo"
                            "({!r} != {!r})".format(block_read_memo, read_memo)
                        )
                    self.batch_memos[read_memo] = block
                    memos_to_get_stack.pop()
                else:
                    block = self.batch_memos[read_memo]
                self.manager = _LazyGroupContentManager(
                    block, get_compressor_settings=self._get_compressor_settings
                )
                self.last_read_memo = read_memo
            start, end = index_memo[3:5]
            self.manager.add_factory(key, parents, start, end)
        if full_flush:
            yield from self._flush_manager()
        del self.keys[:]
        self.batch_memos.clear()
        del self.memos_to_get[:]
        self.total_bytes = 0


class GroupCompressVersionedFiles(VersionedFilesWithFallbacks):
    """A group-compress based VersionedFiles implementation."""

    # This controls how the GroupCompress DeltaIndex works. Basically, we
    # compute hash pointers into the source blocks (so hash(text) => text).
    # However each of these references costs some memory in trade against a
    # more accurate match result. For very large files, they either are
    # pre-compressed and change in bulk whenever they change, or change in just
    # local blocks. Either way, 'improved resolution' is not very helpful,
    # versus running out of memory trying to track everything. The default max
    # gives 100% sampling of a 1MB file.
    _DEFAULT_MAX_BYTES_TO_INDEX = 1024 * 1024
    _DEFAULT_COMPRESSOR_SETTINGS = {"max_bytes_to_index": _DEFAULT_MAX_BYTES_TO_INDEX}

    def __init__(
        self, index, access, delta=True, _unadded_refs=None, _group_cache=None
    ):
        """Create a GroupCompressVersionedFiles object.

        :param index: The index object storing access and graph data.
        :param access: The access object storing raw data.
        :param delta: Whether to delta compress or just entropy compress.
        :param _unadded_refs: private parameter, don't use.
        :param _group_cache: private parameter, don't use.
        """
        self._index = index
        self._access = access
        self._delta = delta
        if _unadded_refs is None:
            _unadded_refs = {}
        self._unadded_refs = _unadded_refs
        if _group_cache is None:
            _group_cache = LRUSizeCache(max_size=50 * 1024 * 1024)
        self._group_cache = _group_cache
        self._immediate_fallback_vfs = []
        self._max_bytes_to_index = None

    def without_fallbacks(self):
        """Return a clone of this object without any fallbacks configured."""
        return GroupCompressVersionedFiles(
            self._index,
            self._access,
            self._delta,
            _unadded_refs=dict(self._unadded_refs),
            _group_cache=self._group_cache,
        )

    def add_lines(
        self,
        key,
        parents,
        lines,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
    ):
        r"""Add a text to the store.

        :param key: The key tuple of the text to add.
        :param parents: The parents key tuples of the text to add.
        :param lines: A list of lines. Each line must be a bytestring. And all
            of them except the last must be terminated with \\n and contain no
            other \\n's. The last line may either contain no \\n's or a single
            terminating \\n. If the lines list does meet this constraint the
            add routine may error or may succeed - but you will be unable to
            read the data back accurately. (Checking the lines have been split
            correctly is expensive and extremely unlikely to catch bugs so it
            is not done at runtime unless check_content is True.)
        :param parent_texts: An optional dictionary containing the opaque
            representations of some or all of the parents of version_id to
            allow delta optimisations.  VERY IMPORTANT: the texts must be those
            returned by add_lines or data corruption can be caused.
        :param left_matching_blocks: a hint about which areas are common
            between the text and its left-hand-parent.  The format is
            the SequenceMatcher.get_matching_blocks format.
        :param nostore_sha: Raise ExistingContent and do not add the lines to
            the versioned file if the digest of the lines matches this.
        :param random_id: If True a random id has been selected rather than
            an id determined by some deterministic process such as a converter
            from a foreign VCS. When True the backend may choose not to check
            for uniqueness of the resulting key within the versioned file, so
            this should only be done when the result is expected to be unique
            anyway.
        :param check_content: If True, the lines supplied are verified to be
            bytestrings that are correctly formed lines.
        :return: The text sha1, the number of bytes in the text, and an opaque
                 representation of the inserted version which can be provided
                 back to future add_lines calls in the parent_texts dictionary.
        """
        self._index._check_write_ok()
        if check_content:
            self._check_lines_not_unicode(lines)
            self._check_lines_are_lines(lines)
        return self.add_content(
            ChunkedContentFactory(
                key, parents, osutils.sha_strings(lines), lines, chunks_are_lines=True
            ),
            parent_texts,
            left_matching_blocks,
            nostore_sha,
            random_id,
        )

    def add_content(
        self,
        factory,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
    ):
        """Add a text to the store.

        :param factory: A ContentFactory that can be used to retrieve the key,
            parents and contents.
        :param parent_texts: An optional dictionary containing the opaque
            representations of some or all of the parents of version_id to
            allow delta optimisations.  VERY IMPORTANT: the texts must be those
            returned by add_lines or data corruption can be caused.
        :param left_matching_blocks: a hint about which areas are common
            between the text and its left-hand-parent.  The format is
            the SequenceMatcher.get_matching_blocks format.
        :param nostore_sha: Raise ExistingContent and do not add the lines to
            the versioned file if the digest of the lines matches this.
        :param random_id: If True a random id has been selected rather than
            an id determined by some deterministic process such as a converter
            from a foreign VCS. When True the backend may choose not to check
            for uniqueness of the resulting key within the versioned file, so
            this should only be done when the result is expected to be unique
            anyway.
        :return: The text sha1, the number of bytes in the text, and an opaque
                 representation of the inserted version which can be provided
                 back to future add_lines calls in the parent_texts dictionary.
        """
        self._index._check_write_ok()
        parents = factory.parents
        self._check_add(factory.key, random_id)
        if parents is None:
            # The caller might pass None if there is no graph data, but kndx
            # indexes can't directly store that, so we give them
            # an empty tuple instead.
            parents = ()
        # double handling for now. Make it work until then.
        sha1, length = list(
            self._insert_record_stream(
                [factory], random_id=random_id, nostore_sha=nostore_sha
            )
        )[0]
        return sha1, length, None

    def add_fallback_versioned_files(self, a_versioned_files):
        """Add a source of texts for texts not present in this knit.

        :param a_versioned_files: A VersionedFiles object.
        """
        self._immediate_fallback_vfs.append(a_versioned_files)

    def annotate(self, key):
        """See VersionedFiles.annotate."""
        ann = self.get_annotator()
        return ann.annotate_flat(key)

    def get_annotator(self):
        from ..annotate import Annotator

        return Annotator(self)

    def check(self, progress_bar=None, keys=None):
        """See VersionedFiles.check()."""
        if keys is None:
            keys = self.keys()
            for record in self.get_record_stream(keys, "unordered", True):
                for _chunk in record.iter_bytes_as("chunked"):
                    pass
        else:
            return self.get_record_stream(keys, "unordered", True)

    def clear_cache(self):
        """See VersionedFiles.clear_cache()."""
        self._group_cache.clear()
        self._index._graph_index.clear_cache()
        self._index._int_cache.clear()

    def _check_add(self, key, random_id):
        """Check that version_id and lines are safe to add."""
        version_id = key[-1]
        if version_id is not None:
            if osutils.contains_whitespace(version_id):
                raise errors.InvalidRevisionId(version_id, self)
        self.check_not_reserved_id(version_id)
        # TODO: If random_id==False and the key is already present, we should
        # probably check that the existing content is identical to what is
        # being inserted, and otherwise raise an exception.  This would make
        # the bundle code simpler.

    def get_parent_map(self, keys):
        """Get a map of the graph parents of keys.

        :param keys: The keys to look up parents for.
        :return: A mapping from keys to parents. Absent keys are absent from
            the mapping.
        """
        return self._get_parent_map_with_sources(keys)[0]

    def _get_parent_map_with_sources(self, keys):
        """Get a map of the parents of keys.

        :param keys: The keys to look up parents for.
        :return: A tuple. The first element is a mapping from keys to parents.
            Absent keys are absent from the mapping. The second element is a
            list with the locations each key was found in. The first element
            is the in-this-knit parents, the second the first fallback source,
            and so on.
        """
        result = {}
        sources = [self._index] + self._immediate_fallback_vfs
        source_results = []
        missing = set(keys)
        for source in sources:
            if not missing:
                break
            new_result = source.get_parent_map(missing)
            source_results.append(new_result)
            result.update(new_result)
            missing.difference_update(set(new_result))
        return result, source_results

    def _get_blocks(self, read_memos):
        """Get GroupCompressBlocks for the given read_memos.

        :returns: a series of (read_memo, block) pairs, in the order they were
            originally passed.
        """
        cached = {}
        for read_memo in read_memos:
            try:
                block = self._group_cache[read_memo]
            except KeyError:
                pass
            else:
                cached[read_memo] = block
        not_cached = []
        not_cached_seen = set()
        for read_memo in read_memos:
            if read_memo in cached:
                # Don't fetch what we already have
                continue
            if read_memo in not_cached_seen:
                # Don't try to fetch the same data twice
                continue
            not_cached.append(read_memo)
            not_cached_seen.add(read_memo)
        raw_records = self._access.get_raw_records(not_cached)
        for read_memo in read_memos:
            try:
                yield read_memo, cached[read_memo]
            except KeyError:
                # Read the block, and cache it.
                zdata = next(raw_records)
                block = GroupCompressBlock.from_bytes(zdata)
                self._group_cache[read_memo] = block
                cached[read_memo] = block
                yield read_memo, block

    def get_missing_compression_parent_keys(self):
        """Return the keys of missing compression parents.

        Missing compression parents occur when a record stream was missing
        basis texts, or a index was scanned that had missing basis texts.
        """
        # GroupCompress cannot currently reference texts that are not in the
        # group, so this is valid for now
        return frozenset()

    def get_record_stream(self, keys, ordering, include_delta_closure):
        """Get a stream of records for keys.

        :param keys: The keys to include.
        :param ordering: Either 'unordered' or 'topological'. A topologically
            sorted stream has compression parents strictly before their
            children.
        :param include_delta_closure: If True then the closure across any
            compression parents will be included (in the opaque data).
        :return: An iterator of ContentFactory objects, each of which is only
            valid until the iterator is advanced.
        """
        # keys might be a generator
        orig_keys = list(keys)
        keys = set(keys)
        if not keys:
            return
        if not self._index.has_graph and ordering in ("topological", "groupcompress"):
            # Cannot topological order when no graph has been stored.
            # but we allow 'as-requested' or 'unordered'
            ordering = "unordered"

        remaining_keys = keys
        while True:
            try:
                keys = set(remaining_keys)
                for content_factory in self._get_remaining_record_stream(
                    keys, orig_keys, ordering, include_delta_closure
                ):
                    remaining_keys.discard(content_factory.key)
                    yield content_factory
                return
            except pack_repo.RetryWithNewPacks as e:
                self._access.reload_or_raise(e)

    def _find_from_fallback(self, missing):
        """Find whatever keys you can from the fallbacks.

        :param missing: A set of missing keys. This set will be mutated as keys
            are found from a fallback_vfs
        :return: (parent_map, key_to_source_map, source_results)
            parent_map  the overall key => parent_keys
            key_to_source_map   a dict from {key: source}
            source_results      a list of (source: keys)
        """
        parent_map = {}
        key_to_source_map = {}
        source_results = []
        for source in self._immediate_fallback_vfs:
            if not missing:
                break
            source_parents = source.get_parent_map(missing)
            parent_map.update(source_parents)
            source_parents = list(source_parents)
            source_results.append((source, source_parents))
            key_to_source_map.update((key, source) for key in source_parents)
            missing.difference_update(source_parents)
        return parent_map, key_to_source_map, source_results

    def _get_ordered_source_keys(self, ordering, parent_map, key_to_source_map):
        """Get the (source, [keys]) list.

        The returned objects should be in the order defined by 'ordering',
        which can weave between different sources.

        :param ordering: Must be one of 'topological' or 'groupcompress'
        :return: List of [(source, [keys])] tuples, such that all keys are in
            the defined order, regardless of source.
        """
        if ordering == "topological":
            present_keys = tsort.topo_sort(parent_map)
        else:
            # ordering == 'groupcompress'
            # XXX: This only optimizes for the target ordering. We may need
            #      to balance that with the time it takes to extract
            #      ordering, by somehow grouping based on
            #      locations[key][0:3]
            present_keys = sort_gc_optimal(parent_map)
        # Now group by source:
        source_keys = []
        current_source = None
        for key in present_keys:
            source = key_to_source_map.get(key, self)
            if source is not current_source:
                source_keys.append((source, []))
                current_source = source
            source_keys[-1][1].append(key)
        return source_keys

    def _get_as_requested_source_keys(
        self, orig_keys, locations, unadded_keys, key_to_source_map
    ):
        source_keys = []
        current_source = None
        for key in orig_keys:
            if key in locations or key in unadded_keys:
                source = self
            elif key in key_to_source_map:
                source = key_to_source_map[key]
            else:  # absent
                continue
            if source is not current_source:
                source_keys.append((source, []))
                current_source = source
            source_keys[-1][1].append(key)
        return source_keys

    def _get_io_ordered_source_keys(self, locations, unadded_keys, source_result):
        def get_group(key):
            # This is the group the bytes are stored in, followed by the
            # location in the group
            return locations[key][0]

        # We don't have an ordering for keys in the in-memory object, but
        # lets process the in-memory ones first.
        present_keys = list(unadded_keys)
        present_keys.extend(sorted(locations, key=get_group))
        # Now grab all of the ones from other sources
        source_keys = [(self, present_keys)]
        source_keys.extend(source_result)
        return source_keys

    def _get_remaining_record_stream(
        self, keys, orig_keys, ordering, include_delta_closure
    ):
        """Get a stream of records for keys.

        :param keys: The keys to include.
        :param ordering: one of 'unordered', 'topological', 'groupcompress' or
            'as-requested'
        :param include_delta_closure: If True then the closure across any
            compression parents will be included (in the opaque data).
        :return: An iterator of ContentFactory objects, each of which is only
            valid until the iterator is advanced.
        """
        # Cheap: iterate
        locations = self._index.get_build_details(keys)
        unadded_keys = set(self._unadded_refs).intersection(keys)
        missing = keys.difference(locations)
        missing.difference_update(unadded_keys)
        (fallback_parent_map, key_to_source_map, source_result) = (
            self._find_from_fallback(missing)
        )
        if ordering in ("topological", "groupcompress"):
            # would be better to not globally sort initially but instead
            # start with one key, recurse to its oldest parent, then grab
            # everything in the same group, etc.
            parent_map = {key: details[2] for key, details in locations.items()}
            for key in unadded_keys:
                parent_map[key] = self._unadded_refs[key]
            parent_map.update(fallback_parent_map)
            source_keys = self._get_ordered_source_keys(
                ordering, parent_map, key_to_source_map
            )
        elif ordering == "as-requested":
            source_keys = self._get_as_requested_source_keys(
                orig_keys, locations, unadded_keys, key_to_source_map
            )
        else:
            # We want to yield the keys in a semi-optimal (read-wise) ordering.
            # Otherwise we thrash the _group_cache and destroy performance
            source_keys = self._get_io_ordered_source_keys(
                locations, unadded_keys, source_result
            )
        for key in missing:
            yield AbsentContentFactory(key)
        # Batch up as many keys as we can until either:
        #  - we encounter an unadded ref, or
        #  - we run out of keys, or
        #  - the total bytes to retrieve for this batch > BATCH_SIZE
        batcher = _BatchingBlockFetcher(
            self, locations, get_compressor_settings=self._get_compressor_settings
        )
        for source, keys in source_keys:
            if source is self:
                for key in keys:
                    if key in self._unadded_refs:
                        # Flush batch, then yield unadded ref from
                        # self._compressor.
                        yield from batcher.yield_factories(full_flush=True)
                        chunks, sha1 = self._compressor.extract(key)
                        parents = self._unadded_refs[key]
                        yield ChunkedContentFactory(key, parents, sha1, chunks)
                        continue
                    if batcher.add_key(key) > BATCH_SIZE:
                        # Ok, this batch is big enough.  Yield some results.
                        yield from batcher.yield_factories()
            else:
                yield from batcher.yield_factories(full_flush=True)
                yield from source.get_record_stream(
                    keys, ordering, include_delta_closure
                )
        yield from batcher.yield_factories(full_flush=True)

    def get_sha1s(self, keys):
        """See VersionedFiles.get_sha1s()."""
        result = {}
        for record in self.get_record_stream(keys, "unordered", True):
            if record.sha1 is not None:
                result[record.key] = record.sha1
            else:
                if record.storage_kind != "absent":
                    result[record.key] = osutils.sha_strings(
                        record.iter_bytes_as("chunked")
                    )
        return result

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert.
        :return: None
        :seealso VersionedFiles.get_record_stream:
        """
        # XXX: Setting random_id=True makes
        # test_insert_record_stream_existing_keys fail for groupcompress and
        # groupcompress-nograph, this needs to be revisited while addressing
        # 'bzr branch' performance issues.
        for _, _ in self._insert_record_stream(stream, random_id=False):
            pass

    def _get_compressor_settings(self):
        from ..config import GlobalConfig

        if self._max_bytes_to_index is None:
            # TODO: VersionedFiles don't know about their containing
            #       repository, so they don't have much of an idea about their
            #       location. So for now, this is only a global option.
            c = GlobalConfig()
            val = c.get_user_option("bzr.groupcompress.max_bytes_to_index")
            if val is not None:
                try:
                    val = int(val)
                except ValueError:
                    trace.warning(
                        "Value for "
                        '"bzr.groupcompress.max_bytes_to_index"'
                        " {!r} is not an integer".format(val)
                    )
                    val = None
            if val is None:
                val = self._DEFAULT_MAX_BYTES_TO_INDEX
            self._max_bytes_to_index = val
        return {"max_bytes_to_index": self._max_bytes_to_index}

    def _make_group_compressor(self):
        return GroupCompressor(self._get_compressor_settings())

    def _insert_record_stream(
        self, stream, random_id=False, nostore_sha=None, reuse_blocks=True
    ):
        """Internal core to insert a record stream into this container.

        This helper function has a different interface than insert_record_stream
        to allow add_lines to be minimal, but still return the needed data.

        :param stream: A stream of records to insert.
        :param nostore_sha: If the sha1 of a given text matches nostore_sha,
            raise ExistingContent, rather than committing the new text.
        :param reuse_blocks: If the source is streaming from
            groupcompress-blocks, just insert the blocks as-is, rather than
            expanding the texts and inserting again.
        :return: An iterator over (sha1, length) of the inserted records.
        :seealso insert_record_stream:
        :seealso add_lines:
        """
        adapters = {}

        def get_adapter(adapter_key):
            try:
                return adapters[adapter_key]
            except KeyError:
                adapter_factory = adapter_registry.get(adapter_key)
                adapter = adapter_factory(self)
                adapters[adapter_key] = adapter
                return adapter

        # This will go up to fulltexts for gc to gc fetching, which isn't
        # ideal.
        self._compressor = self._make_group_compressor()
        self._unadded_refs = {}
        keys_to_add = []

        def flush():
            bytes_len, chunks = self._compressor.flush().to_chunks()
            self._compressor = self._make_group_compressor()
            # Note: At this point we still have 1 copy of the fulltext (in
            #       record and the var 'bytes'), and this generates 2 copies of
            #       the compressed text (one for bytes, one in chunks)
            # TODO: Figure out how to indicate that we would be happy to free
            #       the fulltext content at this point. Note that sometimes we
            #       will want it later (streaming CHK pages), but most of the
            #       time we won't (everything else)
            index, start, length = self._access.add_raw_record(None, bytes_len, chunks)
            nodes = []
            for key, reads, refs in keys_to_add:
                nodes.append((key, b"%d %d %s" % (start, length, reads), refs))
            self._index.add_records(nodes, random_id=random_id)
            self._unadded_refs = {}
            del keys_to_add[:]

        last_prefix = None
        max_fulltext_len = 0
        max_fulltext_prefix = None
        insert_manager = None
        block_start = None
        block_length = None
        # XXX: TODO: remove this, it is just for safety checking for now
        inserted_keys = set()
        reuse_this_block = reuse_blocks
        for record in stream:
            # Raise an error when a record is missing.
            if record.storage_kind == "absent":
                raise errors.RevisionNotPresent(record.key, self)
            if random_id:
                if record.key in inserted_keys:
                    trace.note(
                        gettext(
                            "Insert claimed random_id=True,"
                            " but then inserted %r two times"
                        ),
                        record.key,
                    )
                    continue
                inserted_keys.add(record.key)
            if reuse_blocks:
                # If the reuse_blocks flag is set, check to see if we can just
                # copy a groupcompress block as-is.
                # We only check on the first record (groupcompress-block) not
                # on all of the (groupcompress-block-ref) entries.
                # The reuse_this_block flag is then kept for as long as
                if record.storage_kind == "groupcompress-block":
                    # Check to see if we really want to re-use this block
                    insert_manager = record._manager
                    reuse_this_block = insert_manager.check_is_well_utilized()
            else:
                reuse_this_block = False
            if reuse_this_block:
                # We still want to reuse this block
                if record.storage_kind == "groupcompress-block":
                    # Insert the raw block into the target repo
                    insert_manager = record._manager
                    bytes_len, chunks = record._manager._block.to_chunks()
                    _, start, length = self._access.add_raw_record(
                        None, bytes_len, chunks
                    )
                    block_start = start
                    block_length = length
                if record.storage_kind in (
                    "groupcompress-block",
                    "groupcompress-block-ref",
                ):
                    if insert_manager is None:
                        raise AssertionError("No insert_manager set")
                    if insert_manager is not record._manager:
                        raise AssertionError(
                            "insert_manager does not match"
                            " the current record, we cannot be positive"
                            " that the appropriate content was inserted."
                        )
                    value = b"%d %d %d %d" % (
                        block_start,
                        block_length,
                        record._start,
                        record._end,
                    )
                    nodes = [(record.key, value, (record.parents,))]
                    # TODO: Consider buffering up many nodes to be added, not
                    #       sure how much overhead this has, but we're seeing
                    #       ~23s / 120s in add_records calls
                    self._index.add_records(nodes, random_id=random_id)
                    continue
            try:
                chunks = record.get_bytes_as("chunked")
            except UnavailableRepresentation:
                adapter_key = record.storage_kind, "chunked"
                adapter = get_adapter(adapter_key)
                chunks = adapter.get_bytes(record, "chunked")
            chunks_len = record.size
            if chunks_len is None:
                chunks_len = sum(map(len, chunks))
            if len(record.key) > 1:
                prefix = record.key[0]
                soft = prefix == last_prefix
            else:
                prefix = None
                soft = False
            if max_fulltext_len < chunks_len:
                max_fulltext_len = chunks_len
                max_fulltext_prefix = prefix
            (found_sha1, start_point, end_point, type) = self._compressor.compress(
                record.key,
                chunks,
                chunks_len,
                record.sha1,
                soft=soft,
                nostore_sha=nostore_sha,
            )
            # delta_ratio = float(chunks_len) / (end_point - start_point)
            # Check if we want to continue to include that text
            if prefix == max_fulltext_prefix and end_point < 2 * max_fulltext_len:
                # As long as we are on the same file_id, we will fill at least
                # 2 * max_fulltext_len
                start_new_block = False
            elif end_point > 4 * 1024 * 1024:
                start_new_block = True
            elif (
                prefix is not None
                and prefix != last_prefix
                and end_point > 2 * 1024 * 1024
            ):
                start_new_block = True
            else:
                start_new_block = False
            last_prefix = prefix
            if start_new_block:
                self._compressor.pop_last()
                flush()
                max_fulltext_len = chunks_len
                (found_sha1, start_point, end_point, type) = self._compressor.compress(
                    record.key, chunks, chunks_len, record.sha1
                )
            if record.key[-1] is None:
                key = record.key[:-1] + (b"sha1:" + found_sha1,)
            else:
                key = record.key
            self._unadded_refs[key] = record.parents
            yield found_sha1, chunks_len
            as_st = static_tuple.StaticTuple.from_sequence
            if record.parents is not None:
                parents = as_st([as_st(p) for p in record.parents])
            else:
                parents = None
            refs = static_tuple.StaticTuple(parents)
            keys_to_add.append((key, b"%d %d" % (start_point, end_point), refs))
        if len(keys_to_add):
            flush()
        self._compressor = None

    def iter_lines_added_or_present_in_keys(self, keys, pb=None):
        r"""Iterate over the lines in the versioned files from keys.

        This may return lines from other keys. Each item the returned
        iterator yields is a tuple of a line and a text version that that line
        is present in (not introduced in).

        Ordering of results is in whatever order is most suitable for the
        underlying storage format.

        If a progress bar is supplied, it may be used to indicate progress.
        The caller is responsible for cleaning up progress bars (because this
        is an iterator).

        Notes:
         * Lines are normalised by the underlying store: they will all have \n
           terminators.
         * Lines are returned in arbitrary order.

        :return: An iterator over (line, key).
        """
        keys = set(keys)
        total = len(keys)
        # we don't care about inclusions, the caller cares.
        # but we need to setup a list of records to visit.
        # we need key, position, length
        for key_idx, record in enumerate(
            self.get_record_stream(keys, "unordered", True)
        ):
            # XXX: todo - optimise to use less than full texts.
            key = record.key
            if pb is not None:
                pb.update("Walking content", key_idx, total)
            if record.storage_kind == "absent":
                raise errors.RevisionNotPresent(key, self)
            for line in record.iter_bytes_as("lines"):
                yield line, key
        if pb is not None:
            pb.update("Walking content", total, total)

    def keys(self):
        """See VersionedFiles.keys."""
        if "evil" in debug.debug_flags:
            trace.mutter_callsite(2, "keys scales with size of history")
        sources = [self._index] + self._immediate_fallback_vfs
        result = set()
        for source in sources:
            result.update(source.keys())
        return result


class _GCBuildDetails:
    """A blob of data about the build details.

    This stores the minimal data, which then allows compatibility with the old
    api, without taking as much memory.
    """

    __slots__ = (
        "_basis_end",
        "_delta_end",
        "_group_end",
        "_group_start",
        "_index",
        "_parents",
    )

    method = "group"
    compression_parent = None

    def __init__(self, parents, position_info):
        self._parents = parents
        (
            self._index,
            self._group_start,
            self._group_end,
            self._basis_end,
            self._delta_end,
        ) = position_info

    def __repr__(self):
        return "{}({}, {})".format(
            self.__class__.__name__, self.index_memo, self._parents
        )

    @property
    def index_memo(self):
        return (
            self._index,
            self._group_start,
            self._group_end,
            self._basis_end,
            self._delta_end,
        )

    @property
    def record_details(self):
        return static_tuple.StaticTuple(self.method, None)

    def __getitem__(self, offset):
        """Compatibility thunk to act like a tuple."""
        if offset == 0:
            return self.index_memo
        elif offset == 1:
            return self.compression_parent  # Always None
        elif offset == 2:
            return self._parents
        elif offset == 3:
            return self.record_details
        else:
            raise IndexError("offset out of range")

    def __len__(self):
        return 4


class _GCGraphIndex:
    """Mapper from GroupCompressVersionedFiles needs into GraphIndex storage."""

    def __init__(
        self,
        graph_index,
        is_locked,
        parents=True,
        add_callback=None,
        track_external_parent_refs=False,
        inconsistency_fatal=True,
        track_new_keys=False,
    ):
        """Construct a _GCGraphIndex on a graph_index.

        :param graph_index: An implementation of breezy.index.GraphIndex.
        :param is_locked: A callback, returns True if the index is locked and
            thus usable.
        :param parents: If True, record knits parents, if not do not record
            parents.
        :param add_callback: If not None, allow additions to the index and call
            this callback with a list of added GraphIndex nodes:
            [(node, value, node_refs), ...]
        :param track_external_parent_refs: As keys are added, keep track of the
            keys they reference, so that we can query get_missing_parents(),
            etc.
        :param inconsistency_fatal: When asked to add records that are already
            present, and the details are inconsistent with the existing
            record, raise an exception instead of warning (and skipping the
            record).
        """
        self._add_callback = add_callback
        self._graph_index = graph_index
        self._parents = parents
        self.has_graph = parents
        self._is_locked = is_locked
        self._inconsistency_fatal = inconsistency_fatal
        # GroupCompress records tend to have the same 'group' start + offset
        # repeated over and over, this creates a surplus of ints
        self._int_cache = {}
        if track_external_parent_refs:
            self._key_dependencies = _KeyRefs(track_new_keys=track_new_keys)
        else:
            self._key_dependencies = None

    def add_records(self, records, random_id=False):
        """Add multiple records to the index.

        This function does not insert data into the Immutable GraphIndex
        backing the KnitGraphIndex, instead it prepares data for insertion by
        the caller and checks that it is safe to insert then calls
        self._add_callback with the prepared GraphIndex nodes.

        :param records: a list of tuples:
                         (key, options, access_memo, parents).
        :param random_id: If True the ids being added were randomly generated
            and no check for existence will be performed.
        """
        if not self._add_callback:
            raise errors.ReadOnlyError(self)
        # we hope there are no repositories with inconsistent parentage
        # anymore.

        changed = False
        keys = {}
        for key, value, refs in records:
            if not self._parents:
                if refs:
                    for ref in refs:
                        if ref:
                            raise knit.KnitCorrupt(
                                self,
                                "attempt to add node with parents in parentless index.",
                            )
                    refs = ()
                    changed = True
            keys[key] = (value, refs)
        # check for dups
        if not random_id:
            present_nodes = self._get_entries(keys)
            for _index, key, value, node_refs in present_nodes:
                # Sometimes these are passed as a list rather than a tuple
                node_refs = static_tuple.as_tuples(node_refs)
                passed = static_tuple.as_tuples(keys[key])
                if node_refs != passed[1]:
                    details = "{} {} {}".format(key, (value, node_refs), passed)
                    if self._inconsistency_fatal:
                        raise knit.KnitCorrupt(
                            self,
                            "inconsistent details in add_records: {}".format(details),
                        )
                    else:
                        trace.warning(
                            "inconsistent details in skipped record: %s", details
                        )
                del keys[key]
                changed = True
        if changed:
            result = []
            if self._parents:
                for key, (value, node_refs) in keys.items():
                    result.append((key, value, node_refs))
            else:
                for key, (value, node_refs) in keys.items():  # noqa: B007
                    result.append((key, value))
            records = result
        key_dependencies = self._key_dependencies
        if key_dependencies is not None:
            if self._parents:
                for key, value, refs in records:  # noqa: B007
                    parents = refs[0]
                    key_dependencies.add_references(key, parents)
            else:
                for key, value, refs in records:  # noqa: B007
                    new_keys.add_key(key)
        self._add_callback(records)

    def _check_read(self):
        """Raise an exception if reads are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

    def _check_write_ok(self):
        """Raise an exception if writes are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

    def _get_entries(self, keys, check_present=False):
        """Get the entries for keys.

        Note: Callers are responsible for checking that the index is locked
        before calling this method.

        :param keys: An iterable of index key tuples.
        """
        keys = set(keys)
        found_keys = set()
        if self._parents:
            for node in self._graph_index.iter_entries(keys):
                yield node
                found_keys.add(node[1])
        else:
            # adapt parentless index to the rest of the code.
            for node in self._graph_index.iter_entries(keys):
                yield node[0], node[1], node[2], ()
                found_keys.add(node[1])
        if check_present:
            missing_keys = keys.difference(found_keys)
            if missing_keys:
                raise errors.RevisionNotPresent(missing_keys.pop(), self)

    def find_ancestry(self, keys):
        """See CombinedGraphIndex.find_ancestry."""
        return self._graph_index.find_ancestry(keys, 0)

    def get_parent_map(self, keys):
        """Get a map of the parents of keys.

        :param keys: The keys to look up parents for.
        :return: A mapping from keys to parents. Absent keys are absent from
            the mapping.
        """
        self._check_read()
        nodes = self._get_entries(keys)
        result = {}
        if self._parents:
            for node in nodes:
                result[node[1]] = node[3][0]
        else:
            for node in nodes:
                result[node[1]] = None
        return result

    def get_missing_parents(self):
        """Return the keys of missing parents."""
        # Copied from _KnitGraphIndex.get_missing_parents
        # We may have false positives, so filter those out.
        self._key_dependencies.satisfy_refs_for_keys(
            self.get_parent_map(self._key_dependencies.get_unsatisfied_refs())
        )
        return frozenset(self._key_dependencies.get_unsatisfied_refs())

    def get_build_details(self, keys):
        """Get the various build details for keys.

        Ghosts are omitted from the result.

        :param keys: An iterable of keys.
        :return: A dict of key:
            (index_memo, compression_parent, parents, record_details).

            * index_memo: opaque structure to pass to read_records to extract
              the raw data
            * compression_parent: Content that this record is built upon, may
              be None
            * parents: Logical parents of this node
            * record_details: extra information about the content which needs
              to be passed to Factory.parse_record
        """
        self._check_read()
        result = {}
        entries = self._get_entries(keys)
        for entry in entries:
            key = entry[1]
            if not self._parents:
                parents = None
            else:
                parents = entry[3][0]
            details = _GCBuildDetails(parents, self._node_to_position(entry))
            result[key] = details
        return result

    def keys(self):
        """Get all the keys in the collection.

        The keys are not ordered.
        """
        self._check_read()
        return [node[1] for node in self._graph_index.iter_all_entries()]

    def _node_to_position(self, node):
        """Convert an index value to position details."""
        bits = node[2].split(b" ")
        # It would be nice not to read the entire gzip.
        # start and stop are put into _int_cache because they are very common.
        # They define the 'group' that an entry is in, and many groups can have
        # thousands of objects.
        # Branching Launchpad, for example, saves ~600k integers, at 12 bytes
        # each, or about 7MB. Note that it might be even more when you consider
        # how PyInt is allocated in separate slabs. And you can't return a slab
        # to the OS if even 1 int on it is in use. Note though that Python uses
        # a LIFO when re-using PyInt slots, which might cause more
        # fragmentation.
        start = int(bits[0])
        start = self._int_cache.setdefault(start, start)
        stop = int(bits[1])
        stop = self._int_cache.setdefault(stop, stop)
        basis_end = int(bits[2])
        delta_end = int(bits[3])
        # We can't use StaticTuple here, because node[0] is a BTreeGraphIndex
        # instance...
        return (node[0], start, stop, basis_end, delta_end)

    def scan_unvalidated_index(self, graph_index):
        """Inform this _GCGraphIndex that there is an unvalidated index.

        This allows this _GCGraphIndex to keep track of any missing
        compression parents we may want to have filled in to make those
        indices valid.  It also allows _GCGraphIndex to track any new keys.

        :param graph_index: A GraphIndex
        """
        key_dependencies = self._key_dependencies
        if key_dependencies is None:
            return
        for node in graph_index.iter_all_entries():
            # Add parent refs from graph_index (and discard parent refs
            # that the graph_index has).
            key_dependencies.add_references(node[1], node[3][0])


GroupCompressor: type[_CommonGroupCompressor]


from ._groupcompress_py import (
    LinesDeltaIndex,
    apply_delta,
    apply_delta_to_source,
    decode_base128_int,
    decode_copy_instruction,
    encode_base128_int,
)

try:
    from ._groupcompress_pyx import (  # type: ignore
        DeltaIndex,
        apply_delta,
        apply_delta_to_source,
        decode_base128_int,
        encode_base128_int,
    )

    GroupCompressor = PyrexGroupCompressor
except ImportError as e:
    osutils.failed_to_load_extension(e)
    GroupCompressor = PythonGroupCompressor
