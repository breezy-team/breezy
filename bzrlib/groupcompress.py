# Copyright (C) 2008, 2009 Canonical Ltd
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

from itertools import izip
from cStringIO import StringIO
import time
import zlib
try:
    import pylzma
except ImportError:
    pylzma = None

from bzrlib import (
    annotate,
    debug,
    diff,
    errors,
    graph as _mod_graph,
    osutils,
    pack,
    patiencediff,
    trace,
    )
from bzrlib.graph import Graph
from bzrlib.knit import _DirectPackAccess
from bzrlib.btree_index import BTreeBuilder
from bzrlib.lru_cache import LRUSizeCache
from bzrlib.tsort import topo_sort
from bzrlib.versionedfile import (
    adapter_registry,
    AbsentContentFactory,
    ChunkedContentFactory,
    FulltextContentFactory,
    VersionedFiles,
    )

_USE_LZMA = False and (pylzma is not None)
_NO_LABELS = True
_FAST = False

# osutils.sha_string('')
_null_sha1 = 'da39a3ee5e6b4b0d3255bfef95601890afd80709'


def encode_base128_int(val):
    """Convert an integer into a 7-bit lsb encoding."""
    bytes = []
    count = 0
    while val >= 0x80:
        bytes.append(chr((val | 0x80) & 0xFF))
        val >>= 7
    bytes.append(chr(val))
    return ''.join(bytes)


def decode_base128_int(bytes):
    """Decode an integer from a 7-bit lsb encoding."""
    offset = 0
    val = 0
    shift = 0
    bval = ord(bytes[offset])
    while bval >= 0x80:
        val |= (bval & 0x7F) << shift
        shift += 7
        offset += 1
        bval = ord(bytes[offset])
    val |= bval << shift
    offset += 1
    return val, offset


def encode_copy_instruction(offset, length):
    """Convert this offset into a control code and bytes."""
    copy_command = 0x80
    copy_bytes = [None]

    for copy_bit in (0x01, 0x02, 0x04, 0x08):
        base_byte = offset & 0xff
        if base_byte:
            copy_command |= copy_bit
            copy_bytes.append(chr(base_byte))
        offset >>= 8
    if length is None:
        # None is used by the test suite
        copy_bytes[0] = chr(copy_command)
        return ''.join(copy_bytes)
    if length > 0x10000:
        raise ValueError("we don't emit copy records for lengths > 64KiB")
    if length == 0:
        raise ValueError("We cannot emit a copy of length 0")
    if length != 0x10000:
        # A copy of length exactly 64*1024 == 0x10000 is sent as a length of 0,
        # since that saves bytes for large chained copies
        for copy_bit in (0x10, 0x20):
            base_byte = length & 0xff
            if base_byte:
                copy_command |= copy_bit
                copy_bytes.append(chr(base_byte))
            length >>= 8
    copy_bytes[0] = chr(copy_command)
    return ''.join(copy_bytes)


def sort_gc_optimal(parent_map):
    """Sort and group the keys in parent_map into groupcompress order.

    groupcompress is defined (currently) as reverse-topological order, grouped by
    the key prefix.

    :return: A sorted-list of keys
    """
    # groupcompress ordering is approximately reverse topological,
    # properly grouped by file-id.
    per_prefix_map = {}
    for item in parent_map.iteritems():
        key = item[0]
        if isinstance(key, str) or len(key) == 1:
            prefix = ''
        else:
            prefix = key[0]
        try:
            per_prefix_map[prefix].append(item)
        except KeyError:
            per_prefix_map[prefix] = [item]

    present_keys = []
    for prefix in sorted(per_prefix_map):
        present_keys.extend(reversed(topo_sort(per_prefix_map[prefix])))
    return present_keys


class GroupCompressBlockEntry(object):
    """Track the information about a single object inside a GC group.

    This is generally just the dumb data structure.
    """

    def __init__(self, key, type, sha1, start, length):
        self.key = key
        self.type = type # delta, fulltext, external?
        self.sha1 = sha1 # Sha1 of content
        self.start = start # Byte offset to start of data
        self.length = length # Length of content

    def __repr__(self):
        return '%s(%s, %s, %s, %s, %s)' % (
            self.__class__.__name__,
            self.key, self.type, self.sha1, self.start, self.length
            )

    @property
    def end(self):
        return self.start + self.length

# The max zlib window size is 32kB, so if we set 'max_size' output of the
# decompressor to the requested bytes + 32kB, then we should guarantee
# num_bytes coming out.
_ZLIB_DECOMP_WINDOW = 32*1024

class GroupCompressBlock(object):
    """An object which maintains the internal structure of the compressed data.

    This tracks the meta info (start of text, length, type, etc.)
    """

    # Group Compress Block v1 Zlib
    GCB_HEADER = 'gcb1z\n'
    GCB_LZ_HEADER = 'gcb1l\n'

    def __init__(self):
        # map by key? or just order in file?
        self._entries = {}
        self._compressor_name = None
        self._z_header_length = None
        self._header_length = None
        self._z_header = None
        self._z_content = None
        self._z_content_decompressor = None
        self._z_content_length = None
        self._content_length = None
        self._content = None

    def __len__(self):
        return self._content_length + self._header_length

    def _parse_header(self):
        """Parse the header part of the block."""
        assert self._z_header is not None
        if self._z_header == '':
            # Nothing to process
            self._z_header = None
            return
        if self._compressor_name == 'lzma':
            header = pylzma.decompress(self._z_header)
        else:
            assert self._compressor_name == 'zlib'
            header = zlib.decompress(self._z_header)
        self._z_header = None # We have consumed the header
        lines = header.split('\n')
        del header
        info_dict = {}
        for line in lines:
            if not line: #End of record
                if not info_dict:
                    break
                self.add_entry(**info_dict)
                info_dict = {}
                continue
            key, value = line.split(':', 1)
            if key == 'key':
                value = tuple(map(intern, value.split('\x00')))
            elif key in ('start', 'length'):
                value = int(value)
            elif key == 'type':
                value = intern(value)
            info_dict[key] = value

    def _ensure_content(self, num_bytes=None):
        """Make sure that content has been expanded enough.

        :param num_bytes: Ensure that we have extracted at least num_bytes of
            content. If None, consume everything
        """
        # TODO: If we re-use the same content block at different times during
        #       get_record_stream(), it is possible that the first pass will
        #       get inserted, triggering an extract/_ensure_content() which
        #       will get rid of _z_content. And then the next use of the block
        #       will try to access _z_content (to send it over the wire), and
        #       fail because it is already extracted. Consider never releasing
        #       _z_content because of this.
        if num_bytes is None:
            num_bytes = self._content_length
        if self._content_length is not None:
            assert num_bytes <= self._content_length
        if self._content is None:
            assert self._z_content is not None
            if self._z_content == '':
                self._content = ''
            elif self._compressor_name == 'lzma':
                # We don't do partial lzma decomp yet
                self._content = pylzma.decompress(self._z_content)
            else:
                # Start a zlib decompressor
                assert self._compressor_name == 'zlib'
                if num_bytes is None:
                    self._content = zlib.decompress(self._z_content)
                else:
                    self._z_content_decompressor = zlib.decompressobj()
                    # Seed the decompressor with the uncompressed bytes, so
                    # that the rest of the code is simplified
                    self._content = self._z_content_decompressor.decompress(
                        self._z_content, num_bytes + _ZLIB_DECOMP_WINDOW)
                # Any bytes remaining to be decompressed will be in the
                # decompressors 'unconsumed_tail'
        # Do we have enough bytes already?
        if num_bytes is not None and len(self._content) >= num_bytes:
            return
        if num_bytes is None and self._z_content_decompressor is None:
            # We must have already decompressed everything
            return
        # If we got this far, and don't have a decompressor, something is wrong
        assert self._z_content_decompressor is not None
        remaining_decomp = self._z_content_decompressor.unconsumed_tail
        if num_bytes is None:
            if remaining_decomp:
                # We don't know how much is left, but we'll decompress it all
                self._content += self._z_content_decompressor.decompress(
                    remaining_decomp)
                # Note: There what I consider a bug in zlib.decompressobj
                #       If you pass back in the entire unconsumed_tail, only
                #       this time you don't pass a max-size, it doesn't
                #       change the unconsumed_tail back to None/''.
                #       However, we know we are done with the whole stream
                self._z_content_decompressor = None
            self._content_length = len(self._content)
        else:
            # If we have nothing left to decomp, we ran out of decomp bytes
            assert remaining_decomp
            needed_bytes = num_bytes - len(self._content)
            # We always set max_size to 32kB over the minimum needed, so that
            # zlib will give us as much as we really want.
            # TODO: If this isn't good enough, we could make a loop here,
            #       that keeps expanding the request until we get enough
            self._content += self._z_content_decompressor.decompress(
                remaining_decomp, needed_bytes + _ZLIB_DECOMP_WINDOW)
            assert len(self._content) >= num_bytes
            if not self._z_content_decompressor.unconsumed_tail:
                # The stream is finished
                self._z_content_decompressor = None

    def _parse_bytes(self, bytes):
        """Read the various lengths from the header.

        This also populates the various 'compressed' buffers.

        :return: The position in bytes just after the last newline
        """
        # At present, there are 4 lengths to be read, we have 2 integers for
        # the length of the compressed and uncompressed header, and 2 integers
        # for the compressed and uncompressed content
        # 14 bytes can represent > 1TB, so to avoid checking too far, cap the
        # search to 14 bytes.
        pos = bytes.index('\n', 6, 20)
        self._z_header_length = int(bytes[6:pos])
        pos += 1
        pos2 = bytes.index('\n', pos, pos + 14)
        self._header_length = int(bytes[pos:pos2])
        end_of_z_lengths = pos2
        pos2 += 1
        # Older versions don't have the content lengths, if we want to preserve
        # backwards compatibility, we could try/except over these, and allow
        # them to be skipped
        try:
            pos = bytes.index('\n', pos2, pos2 + 14)
            self._z_content_length = int(bytes[pos2:pos])
            pos += 1
            pos2 = bytes.index('\n', pos, pos + 14)
            self._content_length = int(bytes[pos:pos2])
            pos = pos2 + 1
            assert len(bytes) == (pos + self._z_header_length +
                                  self._z_content_length)
            pos2 = pos + self._z_header_length
            self._z_header = bytes[pos:pos2]
            self._z_content = bytes[pos2:]
            assert len(self._z_content) == self._z_content_length
        except ValueError:
            # This is the older form, which did not encode its content length
            pos = end_of_z_lengths + 1
            pos2 = pos + self._z_header_length
            self._z_header = bytes[pos:pos2]
            self._z_content = bytes[pos2:]
            self._z_content_length = len(self._z_content)

    @classmethod
    def from_bytes(cls, bytes):
        out = cls()
        if bytes[:6] not in (cls.GCB_HEADER, cls.GCB_LZ_HEADER):
            raise ValueError('bytes did not start with %r' % (cls.GCB_HEADER,))
        if bytes[4] == 'z':
            out._compressor_name = 'zlib'
        elif bytes[4] == 'l':
            out._compressor_name = 'lzma'
        else:
            raise ValueError('unknown compressor: %r' % (bytes,))
        out._parse_bytes(bytes)
        if not _NO_LABELS:
            out._parse_header()
        return out

    def extract(self, key, start, end, sha1=None):
        """Extract the text for a specific key.

        :param key: The label used for this content
        :param sha1: TODO (should we validate only when sha1 is supplied?)
        :return: The bytes for the content
        """
        if start == end == 0:
            return ''
        self._ensure_content(end)
        # The bytes are 'f' or 'd' for the type, then a variable-length
        # base128 integer for the content size, then the actual content
        # We know that the variable-length integer won't be longer than 5
        # bytes (it takes 5 bytes to encode 2^32)
        c = self._content[start]
        if c == 'f':
            type = 'fulltext'
        else:
            if c != 'd':
                raise ValueError('Unknown content control code: %s'
                                 % (c,))
            type = 'delta'
        content_len, len_len = decode_base128_int(
                            self._content[start + 1:start + 6])
        content_start = start + 1 + len_len
        if end != content_start + content_len:
            raise ValueError('end != len according to field header'
                ' %s != %s' % (end, content_start + content_len))
        content = self._content[content_start:end]
        if c == 'f':
            bytes = content
        elif c == 'd':
            bytes = apply_delta(self._content, content)
        return bytes

    def add_entry(self, key, type, sha1, start, length):
        """Add new meta info about an entry.

        :param key: The key for the new content
        :param type: Whether this is a delta or fulltext entry (external?)
        :param sha1: sha1sum of the fulltext of this entry
        :param start: where the encoded bytes start
        :param length: total number of bytes in the encoded form
        :return: The entry?
        """
        entry = GroupCompressBlockEntry(key, type, sha1, start, length)
        if key in self._entries:
            raise ValueError('Duplicate key found: %s' % (key,))
        self._entries[key] = entry
        return entry

    def set_content(self, content):
        """Set the content of this block."""
        self._content_length = len(content)
        self._content = content
        self._z_content = None
        self._z_header_length = None

    def to_bytes(self):
        """Encode the information into a byte stream."""
        compress = zlib.compress
        if _USE_LZMA:
            compress = pylzma.compress
        chunks = []
        for key in sorted(self._entries):
            entry = self._entries[key]
            chunk = ('key:%s\n'
                     'sha1:%s\n'
                     'type:%s\n'
                     'start:%s\n'
                     'length:%s\n'
                     '\n'
                     ) % ('\x00'.join(entry.key),
                          entry.sha1,
                          entry.type,
                          entry.start,
                          entry.length,
                          )
            chunks.append(chunk)
        bytes = ''.join(chunks)
        info_len = len(bytes)
        z_header_bytes = compress(bytes)
        del bytes, chunks
        z_header_len = len(z_header_bytes)
        # TODO: we may want to have the header compressed in the same chain
        #       as the data, or we may not, evaulate it
        #       having them compressed together is probably a win for
        #       revisions and the 'inv' portion of chk inventories. As the
        #       label in the header is duplicated in the text.
        #       For chk pages and real bytes, I would guess this is not
        #       true.
        if _NO_LABELS:
            z_header_bytes = ''
            z_header_len = 0
            info_len = 0
        if self._z_content is not None:
            content_len = self._content_length
            z_content_len = self._z_content_length
            z_content_bytes = self._z_content
        else:
            assert self._content is not None
            content_len = self._content_length
            z_content_bytes = compress(self._content)
            self._z_content = z_content_bytes
            z_content_len = len(z_content_bytes)
            self._z_content_length = z_content_len
        if _USE_LZMA:
            header = self.GCB_LZ_HEADER
        else:
            header = self.GCB_HEADER
        chunks = [header,
                  '%d\n%d\n%d\n%d\n' % (z_header_len, info_len,
                                        z_content_len, content_len)
                 ]
        chunks.append(z_header_bytes)
        chunks.append(z_content_bytes)
        return ''.join(chunks)


class _LazyGroupCompressFactory(object):
    """Yield content from a GroupCompressBlock on demand."""

    def __init__(self, key, parents, manager, start, end, first):
        """Create a _LazyGroupCompressFactory

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
        # Note: This attribute coupled with Manager._factories creates a
        #       reference cycle. Perhaps we would rather use a weakref(), or
        #       find an appropriate time to release the ref. After the first
        #       get_bytes_as call? After Manager.get_record_stream() returns
        #       the object?
        self._manager = manager
        self._bytes = None
        self.storage_kind = 'groupcompress-block'
        if not first:
            self.storage_kind = 'groupcompress-block-ref'
        self._first = first
        self._start = start
        self._end = end

    def __repr__(self):
        return '%s(%s, first=%s)' % (self.__class__.__name__,
            self.key, self._first)

    def get_bytes_as(self, storage_kind):
        if storage_kind == self.storage_kind:
            if self._first:
                # wire bytes, something...
                return self._manager._wire_bytes()
            else:
                return ''
        if storage_kind in ('fulltext', 'chunked'):
            if self._bytes is None:
                # Grab and cache the raw bytes for this entry
                # and break the ref-cycle with _manager since we don't need it
                # anymore
                self._manager._prepare_for_extract()
                block = self._manager._block
                self._bytes = block.extract(self.key, self._start, self._end)
                # XXX: It seems the smart fetch extracts inventories and chk
                #      pages as fulltexts to find the next chk pages, but then
                #      passes them down to be inserted as a
                #      groupcompress-block, so this is not safe to do. Perhaps
                #      we could just change the storage kind to "fulltext" at
                #      that point?
                # self._manager = None
            if storage_kind == 'fulltext':
                return self._bytes
            else:
                return [self._bytes]
        raise errors.UnavailableRepresentation(self.key, storage_kind,
                                               self.storage_kind)


class _LazyGroupContentManager(object):
    """This manages a group of _LazyGroupCompressFactory objects."""

    def __init__(self, block):
        self._block = block
        # We need to preserve the ordering
        self._factories = []
        self._last_byte = 0

    def add_factory(self, key, parents, start, end):
        if not self._factories:
            first = True
        else:
            first = False
        # Note that this creates a reference cycle....
        factory = _LazyGroupCompressFactory(key, parents, self,
            start, end, first=first)
        self._last_byte = max(end, self._last_byte)
        self._factories.append(factory)

    def get_record_stream(self):
        """Get a record for all keys added so far."""
        for factory in self._factories:
            yield factory
            # Break the ref-cycle
            factory._bytes = None
            # XXX: this is not safe, the smart fetch code requests the content
            #      as both a 'fulltext', and then later on as a
            #      groupcompress-block. The iter_interesting_nodes code also is
            #      still buffering multiple records and returning them later.
            #      So that code would need to be updated to either re-fetch the
            #      original object, or buffer it somehow.
            # factory._manager = None
        # TODO: Consider setting self._factories = None after the above loop,
        #       as it will break the reference cycle

    def _trim_block(self, last_byte):
        """Create a new GroupCompressBlock, with just some of the content."""
        # None of the factories need to be adjusted, because the content is
        # located in an identical place. Just that some of the unreferenced
        # trailing bytes are stripped
        trace.mutter('stripping trailing bytes from groupcompress block'
                     ' %d => %d', self._block._content_length, last_byte)
        new_block = GroupCompressBlock()
        self._block._ensure_content(last_byte)
        new_block.set_content(self._block._content[:last_byte])
        self._block = new_block

    def _rebuild_block(self):
        """Create a new GroupCompressBlock with only the referenced texts."""
        compressor = GroupCompressor()
        tstart = time.time()
        old_length = self._block._content_length
        end_point = 0
        for factory in self._factories:
            bytes = factory.get_bytes_as('fulltext')
            (found_sha1, start_point, end_point, type,
             length) = compressor.compress(factory.key, bytes, factory.sha1)
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
        delta = time.time() - tstart
        self._block = new_block
        trace.mutter('creating new compressed block on-the-fly in %.3fs'
                     ' %d bytes => %d bytes', delta, old_length,
                     self._block._content_length)

    def _prepare_for_extract(self):
        """A _LazyGroupCompressFactory is about to extract to fulltext."""
        # We expect that if one child is going to fulltext, all will be. This
        # helps prevent all of them from extracting a small amount at a time.
        # Which in itself isn't terribly expensive, but resizing 2MB 32kB at a
        # time (self._block._content) is a little expensive.
        self._block._ensure_content(self._last_byte)

    def _check_rebuild_block(self):
        """Check to see if our block should be repacked."""
        total_bytes_used = 0
        last_byte_used = 0
        for factory in self._factories:
            total_bytes_used += factory._end - factory._start
            last_byte_used = max(last_byte_used, factory._end)
        # If we are using most of the bytes from the block, we have nothing
        # else to check (currently more that 1/2)
        if total_bytes_used * 2 >= self._block._content_length:
            return
        # Can we just strip off the trailing bytes? If we are going to be
        # transmitting more than 50% of the front of the content, go ahead
        if total_bytes_used * 2 > last_byte_used:
            self._trim_block(last_byte_used)
            return

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
        self._rebuild_block()

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
        lines = ['groupcompress-block\n']
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
            key_bytes = '\x00'.join(factory.key)
            parents = factory.parents
            if parents is None:
                parent_bytes = 'None:'
            else:
                parent_bytes = '\t'.join('\x00'.join(key) for key in parents)
            record_header = '%s\n%s\n%d\n%d\n' % (
                key_bytes, parent_bytes, factory._start, factory._end)
            header_lines.append(record_header)
        header_bytes = ''.join(header_lines)
        del header_lines
        header_bytes_len = len(header_bytes)
        z_header_bytes = zlib.compress(header_bytes)
        del header_bytes
        z_header_bytes_len = len(z_header_bytes)
        block_bytes = self._block.to_bytes()
        lines.append('%d\n%d\n%d\n' % (z_header_bytes_len, header_bytes_len,
                                       len(block_bytes)))
        lines.append(z_header_bytes)
        lines.append(block_bytes)
        del z_header_bytes, block_bytes
        return ''.join(lines)

    @classmethod
    def from_bytes(cls, bytes):
        # TODO: This does extra string copying, probably better to do it a
        #       different way
        (storage_kind, z_header_len, header_len,
         block_len, rest) = bytes.split('\n', 4)
        del bytes
        if storage_kind != 'groupcompress-block':
            raise ValueError('Unknown storage kind: %s' % (storage_kind,))
        z_header_len = int(z_header_len)
        if len(rest) < z_header_len:
            raise ValueError('Compressed header len shorter than all bytes')
        z_header = rest[:z_header_len]
        header_len = int(header_len)
        header = zlib.decompress(z_header)
        if len(header) != header_len:
            raise ValueError('invalid length for decompressed bytes')
        del z_header
        block_len = int(block_len)
        if len(rest) != z_header_len + block_len:
            raise ValueError('Invalid length for block')
        block_bytes = rest[z_header_len:]
        del rest
        # So now we have a valid GCB, we just need to parse the factories that
        # were sent to us
        header_lines = header.split('\n')
        del header
        last = header_lines.pop()
        if last != '':
            raise ValueError('header lines did not end with a trailing'
                             ' newline')
        if len(header_lines) % 4 != 0:
            raise ValueError('The header was not an even multiple of 4 lines')
        block = GroupCompressBlock.from_bytes(block_bytes)
        del block_bytes
        result = cls(block)
        for start in xrange(0, len(header_lines), 4):
            # intern()?
            key = tuple(header_lines[start].split('\x00'))
            parents_line = header_lines[start+1]
            if parents_line == 'None:':
                parents = None
            else:
                parents = tuple([tuple(segment.split('\x00'))
                                 for segment in parents_line.split('\t')
                                  if segment])
            start_offset = int(header_lines[start+2])
            end_offset = int(header_lines[start+3])
            result.add_factory(key, parents, start_offset, end_offset)
        return result


def network_block_to_records(storage_kind, bytes, line_end):
    if storage_kind != 'groupcompress-block':
        raise ValueError('Unknown storage kind: %s' % (storage_kind,))
    manager = _LazyGroupContentManager.from_bytes(bytes)
    return manager.get_record_stream()


class _CommonGroupCompressor(object):

    def __init__(self):
        """Create a GroupCompressor."""
        self.lines = []
        self.endpoint = 0
        self.input_bytes = 0
        self.labels_deltas = {}

    def ratio(self):
        """Return the overall compression ratio."""
        return float(self.input_bytes) / float(self.endpoint)


class PythonGroupCompressor(_CommonGroupCompressor):

    def __init__(self):
        """Create a GroupCompressor.

        :param delta: If False, do not compress records.
        """
        super(PythonGroupCompressor, self).__init__()
        self.line_offsets = []
        self.line_locations = EquivalenceTable([])
        self.lines = self.line_locations.lines
        self._present_prefixes = set()

    def get_matching_blocks(self, lines, soft=False):
        """Return the ranges in lines which match self.lines.

        :param lines: lines to compress
        :return: A list of (old_start, new_start, length) tuples which reflect
            a region in self.lines that is present in lines.  The last element
            of the list is always (old_len, new_len, 0) to provide a end point
            for generating instructions from the matching blocks list.
        """
        result = []
        pos = 0
        line_locations = self.line_locations
        line_locations.set_right_lines(lines)
        locations = None
        max_pos = len(lines)
        result_append = result.append
        min_match_bytes = 10
        if soft:
            min_match_bytes = 200
        while pos < max_pos:
            block, pos, locations = _get_longest_match(line_locations, pos,
                                                       max_pos, locations)
            if block is not None:
                # Check to see if we are matching fewer than 5 characters,
                # which is turned into a simple 'insert', rather than a copy
                # If we have more than 5 lines, we definitely have more than 5
                # chars
                if block[-1] < min_match_bytes:
                    # This block may be a 'short' block, check
                    old_start, new_start, range_len = block
                    matched_bytes = sum(map(len,
                        lines[new_start:new_start + range_len]))
                    if matched_bytes < min_match_bytes:
                        block = None
            if block is not None:
                result_append(block)
        result_append((len(self.lines), len(lines), 0))
        return result

    # FIXME: implement nostore_sha
    def compress(self, key, bytes, expected_sha, nostore_sha=None, soft=False):
        """Compress lines with label key.

        :param key: A key tuple. It is stored in the output
            for identification of the text during decompression. If the last
            element is 'None' it is replaced with the sha1 of the text -
            e.g. sha1:xxxxxxx.
        :param bytes: The bytes to be compressed
        :param expected_sha: If non-None, the sha the lines are believed to
            have. During compression the sha is calculated; a mismatch will
            cause an error.
        :param nostore_sha: If the computed sha1 sum matches, we will raise
            ExistingContent rather than adding the text.
        :param soft: Do a 'soft' compression. This means that we require larger
            ranges to match to be considered for a copy command.
        :return: The sha1 of lines, and the number of bytes accumulated in
            the group output so far.
        :seealso VersionedFiles.add_lines:
        """
        new_lines = osutils.split_lines(bytes)
        sha1 = osutils.sha_string(bytes)
        if key[-1] is None:
            key = key[:-1] + ('sha1:' + sha1,)
        out_lines = []
        index_lines = []
        blocks = self.get_matching_blocks(new_lines, soft=soft)
        current_line_num = 0
        # We either copy a range (while there are reusable lines) or we
        # insert new lines. To find reusable lines we traverse
        for old_start, new_start, range_len in blocks:
            if new_start != current_line_num:
                # non-matching region
                self.flush_insert(current_line_num, new_start,
                                  new_lines, out_lines, index_lines)
            current_line_num = new_start + range_len
            if not range_len:
                continue
            self._flush_copy(old_start, range_len,
                             new_lines, out_lines, index_lines)
        start = self.endpoint # Keep it
        delta_start = (self.endpoint, len(self.lines))
        self.output_lines(out_lines, index_lines)
        length = len(bytes)
        self.input_bytes += length
        delta_end = (self.endpoint, len(self.lines))
        self.labels_deltas[key] = (delta_start, delta_end)
        # FIXME: lot of guessing below
        return sha1, start, self.endpoint, 'delta', length

    def extract(self, key):
        """Extract a key previously added to the compressor.

        :param key: The key to extract.
        :return: An iterable over bytes and the sha1.
        """
        delta_details = self.labels_deltas[key]
        delta_lines = self.lines[delta_details[0][1]:delta_details[1][1]]
        label, sha1, delta = parse(delta_lines)
        ## delta = parse(delta_lines)
        if label != key:
            raise AssertionError("wrong key: %r, wanted %r" % (label, key))
        # Perhaps we want to keep the line offsets too in memory at least?
        chunks = apply_delta(''.join(self.lines), delta)
        sha1 = osutils.sha_strings(chunks)
        return chunks, sha1

    def _flush_insert(self, start_linenum, end_linenum,
                      new_lines, out_lines, index_lines):
        """Add an 'insert' request to the data stream."""
        bytes_to_insert = ''.join(new_lines[start_linenum:end_linenum])
        insert_length = len(bytes_to_insert)
        # Each insert instruction is at most 127 bytes long
        for start_byte in xrange(0, insert_length, 127):
            insert_count = min(insert_length - start_byte, 127)
            assert insert_count <= 127
            out_lines.append(chr(insert_count))
            # Don't index the 'insert' instruction
            index_lines.append(False)
            insert = bytes_to_insert[start_byte:start_byte+insert_count]
            out_lines.append(insert)
            index_lines.append(True)

    def _flush_copy(self, old_start_linenum, num_lines,
                    out_lines, index_lines):
        if old_start_linenum == 0:
            first_byte = 0
        else:
            first_byte = self.line_offsets[old_start_linenum - 1]
        stop_byte = self.line_offsets[old_start_linenum + num_lines - 1]
        num_bytes = stop_byte - first_byte
        # The data stream allows >64kB in a copy, but to match the compiled
        # code, we will also limit it to a 64kB copy
        for start_byte in xrange(first_byte, stop_byte, 64*1024):
            num_bytes = min(64*1024, stop_byte - first_byte)
            copy_command, copy_bytes = encode_copy_instruction(start_byte,
                                                               num_bytes)

    def flush_range(self, new_line_start, source_line_start, match_num_lines,
                    new_lines, out_lines, index_lines):
        """Insert the control codes for this copy & insert instruction.

        :param range_start: 
        """
        if copy_start is not None:
            # range stops, flush and start a new copy range
            stop_byte = self.line_offsets[copy_start + range_len - 1]
            if copy_start == 0:
                start_byte = 0
            else:
                start_byte = self.line_offsets[copy_start - 1]
            bytes = stop_byte - start_byte
            copy_byte = 0
            copy_control_instruction =0
            new_lines.append(copy_control_instruction)
            index_lines.append(False)
            return
        # not copying, or inserting is shorter than copying, so insert.
        new_lines.append(insert_instruction)
        new_lines.extend(lines[range_start:range_start+range_len])
        index_lines.append(False)
        index_lines.extend([copy_start is None]*range_len)

    def flush(self):
        # FIXME: ugly hack to masquerade ourself as the pyrex version
        class content(object):

            def __init__(self, s):
                self.s = s

            def to_bytes(self):
                return self.s

        return content(zlib.compress(''.join(self.lines)))

    def output_lines(self, new_lines, index_lines):
        """Output some lines.

        :param new_lines: The lines to output.
        :param index_lines: A boolean flag for each line - when True, index
            that line.
        """
        # indexed_newlines = [idx for idx, val in enumerate(index_lines)
        #                          if val and new_lines[idx] == '\n']
        # if indexed_newlines:
        #     import pdb; pdb.set_trace()
        endpoint = self.endpoint
        self.line_locations.extend_lines(new_lines, index_lines)
        for line in new_lines:
            endpoint += len(line)
            self.line_offsets.append(endpoint)
        self.endpoint = endpoint


class PyrexGroupCompressor(_CommonGroupCompressor):
    """Produce a serialised group of compressed texts.

    It contains code very similar to SequenceMatcher because of having a similar
    task. However some key differences apply:
     - there is no junk, we want a minimal edit not a human readable diff.
     - we don't filter very common lines (because we don't know where a good
       range will start, and after the first text we want to be emitting minmal
       edits only.
     - we chain the left side, not the right side
     - we incrementally update the adjacency matrix as new lines are provided.
     - we look for matches in all of the left side, so the routine which does
       the analagous task of find_longest_match does not need to filter on the
       left side.
    """

    def __init__(self):
        super(PythonGroupCompressor, self).__init__()
        self.num_keys = 0
        self._last = None
        self._delta_index = DeltaIndex()
        self._block = GroupCompressBlock()

    def compress(self, key, bytes, expected_sha, nostore_sha=None, soft=False):
        """Compress lines with label key.

        :param key: A key tuple. It is stored in the output
            for identification of the text during decompression. If the last
            element is 'None' it is replaced with the sha1 of the text -
            e.g. sha1:xxxxxxx.
        :param bytes: The bytes to be compressed
        :param expected_sha: If non-None, the sha the lines are believed to
            have. During compression the sha is calculated; a mismatch will
            cause an error.
        :param nostore_sha: If the computed sha1 sum matches, we will raise
            ExistingContent rather than adding the text.
        :param soft: Do a 'soft' compression. This means that we require larger
            ranges to match to be considered for a copy command.
        :return: The sha1 of lines, and the number of bytes accumulated in
            the group output so far.
        :seealso VersionedFiles.add_lines:
        """
        if not bytes: # empty, like a dir entry, etc
            if nostore_sha == _null_sha1:
                raise errors.ExistingContent()
            self._block.add_entry(key, type='empty',
                                  sha1=None, start=0,
                                  length=0)
            return _null_sha1, 0, 0, 'fulltext', 0
        # we assume someone knew what they were doing when they passed it in
        if expected_sha is not None:
            sha1 = expected_sha
        else:
            sha1 = osutils.sha_string(bytes)
        if nostore_sha is not None:
            if sha1 == nostore_sha:
                raise errors.ExistingContent()
        if key[-1] is None:
            key = key[:-1] + ('sha1:' + sha1,)
        input_len = len(bytes)
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
            raise AssertionError('_source_offset != endpoint'
                ' somehow the DeltaIndex got out of sync with'
                ' the output lines')
        max_delta_size = len(bytes) / 2
        delta = self._delta_index.make_delta(bytes, max_delta_size)
        if (delta is None):
            type = 'fulltext'
            enc_length = encode_base128_int(len(bytes))
            len_mini_header = 1 + len(enc_length)
            length = len(bytes) + len_mini_header
            self._delta_index.add_source(bytes, len_mini_header)
            new_chunks = ['f', enc_length, bytes]
        else:
            type = 'delta'
            enc_length = encode_base128_int(len(delta))
            len_mini_header = 1 + len(enc_length)
            length = len(delta) + len_mini_header
            new_chunks = ['d', enc_length, delta]
            if _FAST:
                self._delta_index._source_offset += length
            else:
                self._delta_index.add_delta_source(delta, len_mini_header)
        self._block.add_entry(key, type=type, sha1=sha1,
                              start=self.endpoint, length=length)
        start = self.endpoint
        delta_start = (self.endpoint, len(self.lines))
        self.num_keys += 1
        self.output_chunks(new_chunks)
        self.input_bytes += input_len
        delta_end = (self.endpoint, len(self.lines))
        self.labels_deltas[key] = (delta_start, delta_end)
        if not self._delta_index._source_offset == self.endpoint:
            raise AssertionError('the delta index is out of sync'
                'with the output lines %s != %s'
                % (self._delta_index._source_offset, self.endpoint))
        return sha1, start, self.endpoint, type, length

    def extract(self, key):
        """Extract a key previously added to the compressor.

        :param key: The key to extract.
        :return: An iterable over bytes and the sha1.
        """
        delta_details = self.labels_deltas[key]
        delta_chunks = self.lines[delta_details[0][1]:delta_details[1][1]]
        stored_bytes = ''.join(delta_chunks)
        # TODO: Fix this, we shouldn't really be peeking here
        entry = self._block._entries[key]
        if entry.type == 'fulltext':
            if stored_bytes[0] != 'f':
                raise ValueError('Index claimed fulltext, but stored bytes'
                                 ' indicate %s' % (stored_bytes[0],))
            fulltext_len, offset = decode_base128_int(stored_bytes[1:10])
            if fulltext_len + 1 + offset != len(stored_bytes):
                raise ValueError('Index claimed fulltext len, but stored bytes'
                                 ' claim %s != %s'
                                 % (len(stored_bytes),
                                    fulltext_len + 1 + offset))
            bytes = stored_bytes[offset + 1:]
        else:
            if entry.type != 'delta':
                raise ValueError('Unknown entry type: %s' % (entry.type,))
            # XXX: This is inefficient at best
            source = ''.join(self.lines)
            if stored_bytes[0] != 'd':
                raise ValueError('Entry type claims delta, bytes claim %s'
                                 % (stored_bytes[0],))
            delta_len, offset = decode_base128_int(stored_bytes[1:10])
            if delta_len + 1 + offset != len(stored_bytes):
                raise ValueError('Index claimed delta len, but stored bytes'
                                 ' claim %s != %s'
                                 % (len(stored_bytes),
                                    delta_len + 1 + offset))
            bytes = apply_delta(source, stored_bytes[offset + 1:])
        bytes_sha1 = osutils.sha_string(bytes)
        if entry.sha1 != bytes_sha1:
            raise ValueError('Recorded sha1 != measured %s != %s'
                             % (entry.sha1, bytes_sha1))
        return bytes, entry.sha1

    def flush(self):
        """Finish this group, creating a formatted stream."""
        content = ''.join(self.lines)
        self.lines = None
        self._block.set_content(content)
        return self._block

    def output_chunks(self, new_chunks):
        """Output some chunks.

        :param new_chunks: The chunks to output.
        """
        self._last = (len(self.lines), self.endpoint)
        endpoint = self.endpoint
        self.lines.extend(new_chunks)
        endpoint += sum(map(len, new_chunks))
        self.endpoint = endpoint

    def pop_last(self):
        """Call this if you want to 'revoke' the last compression.

        After this, the data structures will be rolled back, but you cannot do
        more compression.
        """
        self._delta_index = None
        del self.lines[self._last[0]:]
        self.endpoint = self._last[1]
        self._last = None


def make_pack_factory(graph, delta, keylength):
    """Create a factory for creating a pack based groupcompress.

    This is only functional enough to run interface tests, it doesn't try to
    provide a full pack environment.

    :param graph: Store a graph.
    :param delta: Delta compress contents.
    :param keylength: How long should keys be.
    """
    def factory(transport):
        parents = graph
        ref_length = 0
        if graph:
            ref_length = 1
        graph_index = BTreeBuilder(reference_lists=ref_length,
            key_elements=keylength)
        stream = transport.open_write_stream('newpack')
        writer = pack.ContainerWriter(stream.write)
        writer.begin()
        index = _GCGraphIndex(graph_index, lambda:True, parents=parents,
            add_callback=graph_index.add_nodes)
        access = _DirectPackAccess({})
        access.set_writer(writer, graph_index, (transport, 'newpack'))
        result = GroupCompressVersionedFiles(index, access, delta)
        result.stream = stream
        result.writer = writer
        return result
    return factory


def cleanup_pack_group(versioned_files):
    versioned_files.writer.end()
    versioned_files.stream.close()


class GroupCompressVersionedFiles(VersionedFiles):
    """A group-compress based VersionedFiles implementation."""

    def __init__(self, index, access, delta=True):
        """Create a GroupCompressVersionedFiles object.

        :param index: The index object storing access and graph data.
        :param access: The access object storing raw data.
        :param delta: Whether to delta compress or just entropy compress.
        """
        self._index = index
        self._access = access
        self._delta = delta
        self._unadded_refs = {}
        self._group_cache = LRUSizeCache(max_size=50*1024*1024)
        self._fallback_vfs = []

    def add_lines(self, key, parents, lines, parent_texts=None,
        left_matching_blocks=None, nostore_sha=None, random_id=False,
        check_content=True):
        """Add a text to the store.

        :param key: The key tuple of the text to add.
        :param parents: The parents key tuples of the text to add.
        :param lines: A list of lines. Each line must be a bytestring. And all
            of them except the last must be terminated with \n and contain no
            other \n's. The last line may either contain no \n's or a single
            terminating \n. If the lines list does meet this constraint the add
            routine may error or may succeed - but you will be unable to read
            the data back accurately. (Checking the lines have been split
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
        self._check_add(key, lines, random_id, check_content)
        if parents is None:
            # The caller might pass None if there is no graph data, but kndx
            # indexes can't directly store that, so we give them
            # an empty tuple instead.
            parents = ()
        # double handling for now. Make it work until then.
        length = sum(map(len, lines))
        record = ChunkedContentFactory(key, parents, None, lines)
        sha1 = list(self._insert_record_stream([record], random_id=random_id,
                                               nostore_sha=nostore_sha))[0]
        return sha1, length, None

    def add_fallback_versioned_files(self, a_versioned_files):
        """Add a source of texts for texts not present in this knit.

        :param a_versioned_files: A VersionedFiles object.
        """
        self._fallback_vfs.append(a_versioned_files)

    def annotate(self, key):
        """See VersionedFiles.annotate."""
        graph = Graph(self)
        parent_map = self.get_parent_map([key])
        if not parent_map:
            raise errors.RevisionNotPresent(key, self)
        if parent_map[key] is not None:
            search = graph._make_breadth_first_searcher([key])
            keys = set()
            while True:
                try:
                    present, ghosts = search.next_with_ghosts()
                except StopIteration:
                    break
                keys.update(present)
            parent_map = self.get_parent_map(keys)
        else:
            keys = [key]
            parent_map = {key:()}
        head_cache = _mod_graph.FrozenHeadsCache(graph)
        parent_cache = {}
        reannotate = annotate.reannotate
        for record in self.get_record_stream(keys, 'topological', True):
            key = record.key
            chunks = osutils.chunks_to_lines(record.get_bytes_as('chunked'))
            parent_lines = [parent_cache[parent] for parent in parent_map[key]]
            parent_cache[key] = list(
                reannotate(parent_lines, chunks, key, None, head_cache))
        return parent_cache[key]

    def check(self, progress_bar=None):
        """See VersionedFiles.check()."""
        keys = self.keys()
        for record in self.get_record_stream(keys, 'unordered', True):
            record.get_bytes_as('fulltext')

    def _check_add(self, key, lines, random_id, check_content):
        """check that version_id and lines are safe to add."""
        version_id = key[-1]
        if version_id is not None:
            if osutils.contains_whitespace(version_id):
                raise errors.InvalidRevisionId(version_id, self)
        self.check_not_reserved_id(version_id)
        # TODO: If random_id==False and the key is already present, we should
        # probably check that the existing content is identical to what is
        # being inserted, and otherwise raise an exception.  This would make
        # the bundle code simpler.
        if check_content:
            self._check_lines_not_unicode(lines)
            self._check_lines_are_lines(lines)

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
        sources = [self._index] + self._fallback_vfs
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

    def _get_block(self, index_memo):
        read_memo = index_memo[0:3]
        # get the group:
        try:
            block = self._group_cache[read_memo]
        except KeyError:
            # read the group
            zdata = self._access.get_raw_records([read_memo]).next()
            # decompress - whole thing - this is not a bug, as it
            # permits caching. We might want to store the partially
            # decompresed group and decompress object, so that recent
            # texts are not penalised by big groups.
            block = GroupCompressBlock.from_bytes(zdata)
            self._group_cache[read_memo] = block
        # cheapo debugging:
        # print len(zdata), len(plain)
        # parse - requires split_lines, better to have byte offsets
        # here (but not by much - we only split the region for the
        # recipe, and we often want to end up with lines anyway.
        return block

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
        if (not self._index.has_graph
            and ordering in ('topological', 'groupcompress')):
            # Cannot topological order when no graph has been stored.
            # but we allow 'as-requested' or 'unordered'
            ordering = 'unordered'

        remaining_keys = keys
        while True:
            try:
                keys = set(remaining_keys)
                for content_factory in self._get_remaining_record_stream(keys,
                        orig_keys, ordering, include_delta_closure):
                    remaining_keys.discard(content_factory.key)
                    yield content_factory
                return
            except errors.RetryWithNewPacks, e:
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
        for source in self._fallback_vfs:
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
        if ordering == 'topological':
            present_keys = topo_sort(parent_map)
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

    def _get_as_requested_source_keys(self, orig_keys, locations, unadded_keys,
                                      key_to_source_map):
        source_keys = []
        current_source = None
        for key in orig_keys:
            if key in locations or key in unadded_keys:
                source = self
            elif key in key_to_source_map:
                source = key_to_source_map[key]
            else: # absent
                continue
            if source is not current_source:
                source_keys.append((source, []))
                current_source = source
            source_keys[-1][1].append(key)
        return source_keys

    def _get_io_ordered_source_keys(self, locations, unadded_keys,
                                    source_result):
        def get_group(key):
            # This is the group the bytes are stored in, followed by the
            # location in the group
            return locations[key][0]
        present_keys = sorted(locations.iterkeys(), key=get_group)
        # We don't have an ordering for keys in the in-memory object, but
        # lets process the in-memory ones first.
        present_keys = list(unadded_keys) + present_keys
        # Now grab all of the ones from other sources
        source_keys = [(self, present_keys)]
        source_keys.extend(source_result)
        return source_keys

    def _get_remaining_record_stream(self, keys, orig_keys, ordering,
                                     include_delta_closure):
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
        (fallback_parent_map, key_to_source_map,
         source_result) = self._find_from_fallback(missing)
        if ordering in ('topological', 'groupcompress'):
            # would be better to not globally sort initially but instead
            # start with one key, recurse to its oldest parent, then grab
            # everything in the same group, etc.
            parent_map = dict((key, details[2]) for key, details in
                locations.iteritems())
            for key in unadded_keys:
                parent_map[key] = self._unadded_refs[key]
            parent_map.update(fallback_parent_map)
            source_keys = self._get_ordered_source_keys(ordering, parent_map,
                                                        key_to_source_map)
        elif ordering == 'as-requested':
            source_keys = self._get_as_requested_source_keys(orig_keys,
                locations, unadded_keys, key_to_source_map)
        else:
            # We want to yield the keys in a semi-optimal (read-wise) ordering.
            # Otherwise we thrash the _group_cache and destroy performance
            source_keys = self._get_io_ordered_source_keys(locations,
                unadded_keys, source_result)
        for key in missing:
            yield AbsentContentFactory(key)
        manager = None
        last_read_memo = None
        # TODO: This works fairly well at batching up existing groups into a
        #       streamable format, and possibly allowing for taking one big
        #       group and splitting it when it isn't fully utilized.
        #       However, it doesn't allow us to find under-utilized groups and
        #       combine them into a bigger group on the fly.
        #       (Consider the issue with how chk_map inserts texts
        #       one-at-a-time.) This could be done at insert_record_stream()
        #       time, but it probably would decrease the number of
        #       bytes-on-the-wire for fetch.
        for source, keys in source_keys:
            if source is self:
                for key in keys:
                    if key in self._unadded_refs:
                        if manager is not None:
                            for factory in manager.get_record_stream():
                                yield factory
                            last_read_memo = manager = None
                        bytes, sha1 = self._compressor.extract(key)
                        parents = self._unadded_refs[key]
                        yield FulltextContentFactory(key, parents, sha1, bytes)
                    else:
                        index_memo, _, parents, (method, _) = locations[key]
                        read_memo = index_memo[0:3]
                        if last_read_memo != read_memo:
                            # We are starting a new block. If we have a
                            # manager, we have found everything that fits for
                            # now, so yield records
                            if manager is not None:
                                for factory in manager.get_record_stream():
                                    yield factory
                            # Now start a new manager
                            block = self._get_block(index_memo)
                            manager = _LazyGroupContentManager(block)
                            last_read_memo = read_memo
                        start, end = index_memo[3:5]
                        manager.add_factory(key, parents, start, end)
            else:
                if manager is not None:
                    for factory in manager.get_record_stream():
                        yield factory
                    last_read_memo = manager = None
                for record in source.get_record_stream(keys, ordering,
                                                       include_delta_closure):
                    yield record
        if manager is not None:
            for factory in manager.get_record_stream():
                yield factory

    def get_sha1s(self, keys):
        """See VersionedFiles.get_sha1s()."""
        result = {}
        for record in self.get_record_stream(keys, 'unordered', True):
            if record.sha1 != None:
                result[record.key] = record.sha1
            else:
                if record.storage_kind != 'absent':
                    result[record.key] = osutils.sha_string(
                        record.get_bytes_as('fulltext'))
        return result

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert.
        :return: None
        :seealso VersionedFiles.get_record_stream:
        """
        for _ in self._insert_record_stream(stream):
            pass

    def _insert_record_stream(self, stream, random_id=False, nostore_sha=None,
                              reuse_blocks=True):
        """Internal core to insert a record stream into this container.

        This helper function has a different interface than insert_record_stream
        to allow add_lines to be minimal, but still return the needed data.

        :param stream: A stream of records to insert.
        :param nostore_sha: If the sha1 of a given text matches nostore_sha,
            raise ExistingContent, rather than committing the new text.
        :param reuse_blocks: If the source is streaming from
            groupcompress-blocks, just insert the blocks as-is, rather than
            expanding the texts and inserting again.
        :return: An iterator over the sha1 of the inserted records.
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
        self._compressor = GroupCompressor()
        self._unadded_refs = {}
        keys_to_add = []
        def flush():
            bytes = self._compressor.flush().to_bytes()
            index, start, length = self._access.add_raw_records(
                [(None, len(bytes))], bytes)[0]
            nodes = []
            for key, reads, refs in keys_to_add:
                nodes.append((key, "%d %d %s" % (start, length, reads), refs))
            self._index.add_records(nodes, random_id=random_id)
            self._unadded_refs = {}
            del keys_to_add[:]
            self._compressor = GroupCompressor()

        last_prefix = None
        last_fulltext_len = None
        max_fulltext_len = 0
        max_fulltext_prefix = None
        insert_manager = None
        block_start = None
        block_length = None
        for record in stream:
            # Raise an error when a record is missing.
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(record.key, self)
            if reuse_blocks:
                # If the reuse_blocks flag is set, check to see if we can just
                # copy a groupcompress block as-is.
                if record.storage_kind == 'groupcompress-block':
                    # Insert the raw block into the target repo
                    insert_manager = record._manager
                    insert_manager._check_rebuild_block()
                    bytes = record._manager._block.to_bytes()
                    _, start, length = self._access.add_raw_records(
                        [(None, len(bytes))], bytes)[0]
                    del bytes
                    block_start = start
                    block_length = length
                if record.storage_kind in ('groupcompress-block',
                                           'groupcompress-block-ref'):
                    assert insert_manager is not None
                    assert record._manager is insert_manager
                    value = "%d %d %d %d" % (block_start, block_length,
                                             record._start, record._end)
                    nodes = [(record.key, value, (record.parents,))]
                    self._index.add_records(nodes, random_id=random_id)
                    continue
            try:
                bytes = record.get_bytes_as('fulltext')
            except errors.UnavailableRepresentation:
                adapter_key = record.storage_kind, 'fulltext'
                adapter = get_adapter(adapter_key)
                bytes = adapter.get_bytes(record)
            if len(record.key) > 1:
                prefix = record.key[0]
                soft = (prefix == last_prefix)
            else:
                prefix = None
                soft = False
            if max_fulltext_len < len(bytes):
                max_fulltext_len = len(bytes)
                max_fulltext_prefix = prefix
            (found_sha1, start_point, end_point, type,
             length) = self._compressor.compress(record.key,
                bytes, record.sha1, soft=soft,
                nostore_sha=nostore_sha)
            # delta_ratio = float(len(bytes)) / length
            # Check if we want to continue to include that text
            if (prefix == max_fulltext_prefix
                and end_point < 2 * max_fulltext_len):
                # As long as we are on the same file_id, we will fill at least
                # 2 * max_fulltext_len
                start_new_block = False
            elif end_point > 4*1024*1024:
                start_new_block = True
            elif (prefix is not None and prefix != last_prefix
                  and end_point > 2*1024*1024):
                start_new_block = True
            else:
                start_new_block = False
            # if type == 'fulltext':
            #     # If this is the first text, we don't do anything
            #     if self._compressor.num_keys > 1:
            #         if prefix is not None and prefix != last_prefix:
            #             # We just inserted a fulltext for a different prefix
            #             # (aka file-id).
            #             if end_point > 512 * 1024:
            #                 start_new_block = True
            #             # TODO: Consider packing several small texts together
            #             #       maybe only flush if end_point > some threshold
            #             # if end_point > 512 * 1024 or len(bytes) <
            #             #     start_new_block = true
            #         else:
            #             # We just added a fulltext, part of the same file-id
            #             if (end_point > 2*1024*1024
            #                 and end_point > 5*max_fulltext_len):
            #                 start_new_block = True
            #     last_fulltext_len = len(bytes)
            # else:
            #     delta_ratio = float(len(bytes)) / length
            #     if delta_ratio < 3: # Not much compression
            #         if end_point > 1*1024*1024:
            #             start_new_block = True
            #     elif delta_ratio < 10: # 10:1 compression
            #         if end_point > 4*1024*1024:
            #             start_new_block = True
            last_prefix = prefix
            if start_new_block:
                self._compressor.pop_last()
                flush()
                max_fulltext_len = len(bytes)
                (found_sha1, start_point, end_point, type,
                 length) = self._compressor.compress(record.key,
                    bytes, record.sha1)
                last_fulltext_len = length
            if record.key[-1] is None:
                key = record.key[:-1] + ('sha1:' + found_sha1,)
            else:
                key = record.key
            self._unadded_refs[key] = record.parents
            yield found_sha1
            keys_to_add.append((key, '%d %d' % (start_point, end_point),
                (record.parents,)))
        if len(keys_to_add):
            flush()
        self._compressor = None

    def iter_lines_added_or_present_in_keys(self, keys, pb=None):
        """Iterate over the lines in the versioned files from keys.

        This may return lines from other keys. Each item the returned
        iterator yields is a tuple of a line and a text version that that line
        is present in (not introduced in).

        Ordering of results is in whatever order is most suitable for the
        underlying storage format.

        If a progress bar is supplied, it may be used to indicate progress.
        The caller is responsible for cleaning up progress bars (because this
        is an iterator).

        NOTES:
         * Lines are normalised by the underlying store: they will all have \n
           terminators.
         * Lines are returned in arbitrary order.

        :return: An iterator over (line, key).
        """
        if pb is None:
            pb = progress.DummyProgress()
        keys = set(keys)
        total = len(keys)
        # we don't care about inclusions, the caller cares.
        # but we need to setup a list of records to visit.
        # we need key, position, length
        for key_idx, record in enumerate(self.get_record_stream(keys,
            'unordered', True)):
            # XXX: todo - optimise to use less than full texts.
            key = record.key
            pb.update('Walking content', key_idx, total)
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(key, self)
            lines = osutils.split_lines(record.get_bytes_as('fulltext'))
            for line in lines:
                yield line, key
        pb.update('Walking content', total, total)

    def keys(self):
        """See VersionedFiles.keys."""
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(2, "keys scales with size of history")
        sources = [self._index] + self._fallback_vfs
        result = set()
        for source in sources:
            result.update(source.keys())
        return result


class _GCGraphIndex(object):
    """Mapper from GroupCompressVersionedFiles needs into GraphIndex storage."""

    def __init__(self, graph_index, is_locked, parents=True,
        add_callback=None):
        """Construct a _GCGraphIndex on a graph_index.

        :param graph_index: An implementation of bzrlib.index.GraphIndex.
        :param is_locked: A callback, returns True if the index is locked and
            thus usable.
        :param parents: If True, record knits parents, if not do not record
            parents.
        :param add_callback: If not None, allow additions to the index and call
            this callback with a list of added GraphIndex nodes:
            [(node, value, node_refs), ...]
        """
        self._add_callback = add_callback
        self._graph_index = graph_index
        self._parents = parents
        self.has_graph = parents
        self._is_locked = is_locked

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
        for (key, value, refs) in records:
            if not self._parents:
                if refs:
                    for ref in refs:
                        if ref:
                            raise KnitCorrupt(self,
                                "attempt to add node with parents "
                                "in parentless index.")
                    refs = ()
                    changed = True
            keys[key] = (value, refs)
        # check for dups
        if not random_id:
            present_nodes = self._get_entries(keys)
            for (index, key, value, node_refs) in present_nodes:
                if node_refs != keys[key][1]:
                    raise errors.KnitCorrupt(self, "inconsistent details in add_records"
                        ": %s %s" % ((value, node_refs), keys[key]))
                del keys[key]
                changed = True
        if changed:
            result = []
            if self._parents:
                for key, (value, node_refs) in keys.iteritems():
                    result.append((key, value, node_refs))
            else:
                for key, (value, node_refs) in keys.iteritems():
                    result.append((key, value))
            records = result
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
                raise RevisionNotPresent(missing_keys.pop(), self)

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

    def get_build_details(self, keys):
        """Get the various build details for keys.

        Ghosts are omitted from the result.

        :param keys: An iterable of keys.
        :return: A dict of key:
            (index_memo, compression_parent, parents, record_details).
            index_memo
                opaque structure to pass to read_records to extract the raw
                data
            compression_parent
                Content that this record is built upon, may be None
            parents
                Logical parents of this node
            record_details
                extra information about the content which needs to be passed to
                Factory.parse_record
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
            method = 'group'
            result[key] = (self._node_to_position(entry),
                                  None, parents, (method, None))
        return result

    def keys(self):
        """Get all the keys in the collection.

        The keys are not ordered.
        """
        self._check_read()
        return [node[1] for node in self._graph_index.iter_all_entries()]

    def _node_to_position(self, node):
        """Convert an index value to position details."""
        bits = node[2].split(' ')
        # It would be nice not to read the entire gzip.
        start = int(bits[0])
        stop = int(bits[1])
        basis_end = int(bits[2])
        delta_end = int(bits[3])
        return node[0], start, stop, basis_end, delta_end


try:
    from bzrlib._groupcompress_pyx import (
        apply_delta,
        DeltaIndex,
        )
    GroupCompressor = PyrexGroupCompressor
except ImportError:
    from bzrlib._groupcompress_py import (
        apply_delta,
        EquivalenceTable,
        _get_longest_match,
        trim_encoding_newline,
        )
    GroupCompressor = PythonGroupCompressor

