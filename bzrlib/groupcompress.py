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

# osutils.sha_string('')
_null_sha1 = 'da39a3ee5e6b4b0d3255bfef95601890afd80709'


def sort_gc_optimal(parent_map):
    """Sort and group the keys in parent_map into groupcompress order.

    groupcompress is defined (currently) as reverse-topological order, grouped
    by the key prefix.

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
    # Group Compress Block v1 Lzma
    GCB_LZ_HEADER = 'gcb1l\n'
    GCB_KNOWN_HEADERS = (GCB_HEADER, GCB_LZ_HEADER)

    def __init__(self):
        # map by key? or just order in file?
        self._compressor_name = None
        self._z_content = None
        self._z_content_decompressor = None
        self._z_content_length = None
        self._content_length = None
        self._content = None

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
        # TODO: If we re-use the same content block at different times during
        #       get_record_stream(), it is possible that the first pass will
        #       get inserted, triggering an extract/_ensure_content() which
        #       will get rid of _z_content. And then the next use of the block
        #       will try to access _z_content (to send it over the wire), and
        #       fail because it is already extracted. Consider never releasing
        #       _z_content because of this.
        if num_bytes is None:
            num_bytes = self._content_length
        elif (self._content_length is not None
              and num_bytes > self._content_length):
            raise AssertionError(
                'requested num_bytes (%d) > content length (%d)'
                % (num_bytes, self._content_length))
        # Expand the content if required
        if self._content is None:
            if self._z_content is None:
                raise AssertionError('No content to decompress')
            if self._z_content == '':
                self._content = ''
            elif self._compressor_name == 'lzma':
                # We don't do partial lzma decomp yet
                self._content = pylzma.decompress(self._z_content)
            elif self._compressor_name == 'zlib':
                # Start a zlib decompressor
                if num_bytes is None:
                    self._content = zlib.decompress(self._z_content)
                else:
                    self._z_content_decompressor = zlib.decompressobj()
                    # Seed the decompressor with the uncompressed bytes, so
                    # that the rest of the code is simplified
                    self._content = self._z_content_decompressor.decompress(
                        self._z_content, num_bytes + _ZLIB_DECOMP_WINDOW)
            else:
                raise AssertionError('Unknown compressor: %r'
                                     % self._compressor_name)
        # Any bytes remaining to be decompressed will be in the decompressors
        # 'unconsumed_tail'

        # Do we have enough bytes already?
        if num_bytes is not None and len(self._content) >= num_bytes:
            return
        if num_bytes is None and self._z_content_decompressor is None:
            # We must have already decompressed everything
            return
        # If we got this far, and don't have a decompressor, something is wrong
        if self._z_content_decompressor is None:
            raise AssertionError(
                'No decompressor to decompress %d bytes' % num_bytes)
        remaining_decomp = self._z_content_decompressor.unconsumed_tail
        if num_bytes is None:
            if remaining_decomp:
                # We don't know how much is left, but we'll decompress it all
                self._content += self._z_content_decompressor.decompress(
                    remaining_decomp)
                # Note: There's what I consider a bug in zlib.decompressobj
                #       If you pass back in the entire unconsumed_tail, only
                #       this time you don't pass a max-size, it doesn't
                #       change the unconsumed_tail back to None/''.
                #       However, we know we are done with the whole stream
                self._z_content_decompressor = None
            # XXX: Why is this the only place in this routine we set this?
            self._content_length = len(self._content)
        else:
            if not remaining_decomp:
                raise AssertionError('Nothing left to decompress')
            needed_bytes = num_bytes - len(self._content)
            # We always set max_size to 32kB over the minimum needed, so that
            # zlib will give us as much as we really want.
            # TODO: If this isn't good enough, we could make a loop here,
            #       that keeps expanding the request until we get enough
            self._content += self._z_content_decompressor.decompress(
                remaining_decomp, needed_bytes + _ZLIB_DECOMP_WINDOW)
            if len(self._content) < num_bytes:
                raise AssertionError('%d bytes wanted, only %d available'
                                     % (num_bytes, len(self._content)))
            if not self._z_content_decompressor.unconsumed_tail:
                # The stream is finished
                self._z_content_decompressor = None

    def _parse_bytes(self, bytes, pos):
        """Read the various lengths from the header.

        This also populates the various 'compressed' buffers.

        :return: The position in bytes just after the last newline
        """
        # At present, we have 2 integers for the compressed and uncompressed
        # content. In base10 (ascii) 14 bytes can represent > 1TB, so to avoid
        # checking too far, cap the search to 14 bytes.
        pos2 = bytes.index('\n', pos, pos + 14)
        self._z_content_length = int(bytes[pos:pos2])
        pos = pos2 + 1
        pos2 = bytes.index('\n', pos, pos + 14)
        self._content_length = int(bytes[pos:pos2])
        pos = pos2 + 1
        if len(bytes) != (pos + self._z_content_length):
            # XXX: Define some GCCorrupt error ?
            raise AssertionError('Invalid bytes: (%d) != %d + %d' %
                                 (len(bytes), pos, self._z_content_length))
        self._z_content = bytes[pos:]

    @classmethod
    def from_bytes(cls, bytes):
        out = cls()
        if bytes[:6] not in cls.GCB_KNOWN_HEADERS:
            raise ValueError('bytes did not start with any of %r'
                             % (cls.GCB_KNOWN_HEADERS,))
        # XXX: why not testing the whole header ?
        if bytes[4] == 'z':
            out._compressor_name = 'zlib'
        elif bytes[4] == 'l':
            out._compressor_name = 'lzma'
        else:
            raise ValueError('unknown compressor: %r' % (bytes,))
        out._parse_bytes(bytes, 6)
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
        if c == 'f':
            bytes = self._content[content_start:end]
        elif c == 'd':
            bytes = apply_delta_to_source(self._content, content_start, end)
        return bytes

    def set_content(self, content):
        """Set the content of this block."""
        self._content_length = len(content)
        self._content = content
        self._z_content = None

    def to_bytes(self):
        """Encode the information into a byte stream."""
        compress = zlib.compress
        if _USE_LZMA:
            compress = pylzma.compress
        if self._z_content is None:
            if self._content is None:
                raise AssertionError('Nothing to compress')
            self._z_content = compress(self._content)
            self._z_content_length = len(self._z_content)
        if _USE_LZMA:
            header = self.GCB_LZ_HEADER
        else:
            header = self.GCB_HEADER
        chunks = [header,
                  '%d\n%d\n' % (self._z_content_length, self._content_length),
                  self._z_content,
                 ]
        return ''.join(chunks)

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
            kind = self._content[pos]
            pos += 1
            if kind not in ('f', 'd'):
                raise ValueError('invalid kind character: %r' % (kind,))
            content_len, len_len = decode_base128_int(
                                self._content[pos:pos + 5])
            pos += len_len
            if content_len + pos > self._content_length:
                raise ValueError('invalid content_len %d for record @ pos %d'
                                 % (content_len, pos - len_len - 1))
            if kind == 'f': # Fulltext
                result.append(('f', content_len))
            elif kind == 'd': # Delta
                delta_content = self._content[pos:pos+content_len]
                delta_info = []
                # The first entry in a delta is the decompressed length
                decomp_len, delta_pos = decode_base128_int(delta_content)
                result.append(('d', content_len, decomp_len, delta_info))
                measured_len = 0
                while delta_pos < content_len:
                    c = ord(delta_content[delta_pos])
                    delta_pos += 1
                    if c & 0x80: # Copy
                        (offset, length,
                         delta_pos) = decode_copy_instruction(delta_content, c,
                                                              delta_pos)
                        delta_info.append(('c', offset, length))
                        measured_len += length
                    else: # Insert
                        if include_text:
                            txt = delta_content[delta_pos:delta_pos+c]
                        else:
                            txt = ''
                        delta_info.append(('i', c, txt))
                        measured_len += c
                        delta_pos += c
                if delta_pos != content_len:
                    raise ValueError('Delta consumed a bad number of bytes:'
                                     ' %d != %d' % (delta_pos, content_len))
                if measured_len != decomp_len:
                    raise ValueError('Delta claimed fulltext was %d bytes, but'
                                     ' extraction resulted in %d bytes'
                                     % (decomp_len, measured_len))
            pos += content_len
        return result


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
                # There are code paths that first extract as fulltext, and then
                # extract as storage_kind (smart fetch). So we don't break the
                # refcycle here, but instead in manager.get_record_stream()
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
            (found_sha1, start_point, end_point,
             type) = compressor.compress(factory.key, bytes, factory.sha1)
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
            # TODO: Can we break the refcycle at this point and set
            #       factory._manager = None?
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
        self.chunks = []
        self._last = None
        self.endpoint = 0
        self.input_bytes = 0
        self.labels_deltas = {}
        self._delta_index = None # Set by the children
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

        :return: The sha1 of lines, the start and end offsets in the delta, and
            the type ('fulltext' or 'delta').

        :seealso VersionedFiles.add_lines:
        """
        if not bytes: # empty, like a dir entry, etc
            if nostore_sha == _null_sha1:
                raise errors.ExistingContent()
            return _null_sha1, 0, 0, 'fulltext'
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

        start, end, type = self._compress(key, bytes, len(bytes) / 2, soft)
        return sha1, start, end, type

    def _compress(self, key, bytes, max_delta_size, soft=False):
        """Compress lines with label key.

        :param key: A key tuple. It is stored in the output for identification
            of the text during decompression.

        :param bytes: The bytes to be compressed

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
        :return: An iterable over bytes and the sha1.
        """
        (start_byte, start_chunk, end_byte, end_chunk) = self.labels_deltas[key]
        delta_chunks = self.chunks[start_chunk:end_chunk]
        stored_bytes = ''.join(delta_chunks)
        if stored_bytes[0] == 'f':
            fulltext_len, offset = decode_base128_int(stored_bytes[1:10])
            data_len = fulltext_len + 1 + offset
            if  data_len != len(stored_bytes):
                raise ValueError('Index claimed fulltext len, but stored bytes'
                                 ' claim %s != %s'
                                 % (len(stored_bytes), data_len))
            bytes = stored_bytes[offset + 1:]
        else:
            # XXX: This is inefficient at best
            source = ''.join(self.chunks[:start_chunk])
            if stored_bytes[0] != 'd':
                raise ValueError('Unknown content kind, bytes claim %s'
                                 % (stored_bytes[0],))
            delta_len, offset = decode_base128_int(stored_bytes[1:10])
            data_len = delta_len + 1 + offset
            if data_len != len(stored_bytes):
                raise ValueError('Index claimed delta len, but stored bytes'
                                 ' claim %s != %s'
                                 % (len(stored_bytes), data_len))
            bytes = apply_delta(source, stored_bytes[offset + 1:])
        bytes_sha1 = osutils.sha_string(bytes)
        return bytes, bytes_sha1

    def flush(self):
        """Finish this group, creating a formatted stream.

        After calling this, the compressor should no longer be used
        """
        content = ''.join(self.chunks)
        self.chunks = None
        self._delta_index = None
        self._block.set_content(content)
        return self._block

    def pop_last(self):
        """Call this if you want to 'revoke' the last compression.

        After this, the data structures will be rolled back, but you cannot do
        more compression.
        """
        self._delta_index = None
        del self.chunks[self._last[0]:]
        self.endpoint = self._last[1]
        self._last = None

    def ratio(self):
        """Return the overall compression ratio."""
        return float(self.input_bytes) / float(self.endpoint)


class PythonGroupCompressor(_CommonGroupCompressor):

    def __init__(self):
        """Create a GroupCompressor.

        Used only if the pyrex version is not available.
        """
        super(PythonGroupCompressor, self).__init__()
        self._delta_index = LinesDeltaIndex([])
        # The actual content is managed by LinesDeltaIndex
        self.chunks = self._delta_index.lines

    def _compress(self, key, bytes, max_delta_size, soft=False):
        """see _CommonGroupCompressor._compress"""
        input_len = len(bytes)
        new_lines = osutils.split_lines(bytes)
        out_lines, index_lines = self._delta_index.make_delta(
            new_lines, bytes_length=input_len, soft=soft)
        delta_length = sum(map(len, out_lines))
        if delta_length > max_delta_size:
            # The delta is longer than the fulltext, insert a fulltext
            type = 'fulltext'
            out_lines = ['f', encode_base128_int(input_len)]
            out_lines.extend(new_lines)
            index_lines = [False, False]
            index_lines.extend([True] * len(new_lines))
        else:
            # this is a worthy delta, output it
            type = 'delta'
            out_lines[0] = 'd'
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
        self.labels_deltas[key] = (start, chunk_start,
                                   self.endpoint, chunk_end)
        return start, self.endpoint, type


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
        super(PyrexGroupCompressor, self).__init__()
        self._delta_index = DeltaIndex()

    def _compress(self, key, bytes, max_delta_size, soft=False):
        """see _CommonGroupCompressor._compress"""
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
        delta = self._delta_index.make_delta(bytes, max_delta_size)
        if (delta is None):
            type = 'fulltext'
            enc_length = encode_base128_int(len(bytes))
            len_mini_header = 1 + len(enc_length)
            self._delta_index.add_source(bytes, len_mini_header)
            new_chunks = ['f', enc_length, bytes]
        else:
            type = 'delta'
            enc_length = encode_base128_int(len(delta))
            len_mini_header = 1 + len(enc_length)
            new_chunks = ['d', enc_length, delta]
            self._delta_index.add_delta_source(delta, len_mini_header)
        # Before insertion
        start = self.endpoint
        chunk_start = len(self.chunks)
        # Now output these bytes
        self._output_chunks(new_chunks)
        self.input_bytes += input_len
        chunk_end = len(self.chunks)
        self.labels_deltas[key] = (start, chunk_start,
                                   self.endpoint, chunk_end)
        if not self._delta_index._source_offset == self.endpoint:
            raise AssertionError('the delta index is out of sync'
                'with the output lines %s != %s'
                % (self._delta_index._source_offset, self.endpoint))
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
        # XXX: Setting random_id=True makes
        # test_insert_record_stream_existing_keys fail for groupcompress and
        # groupcompress-nograph, this needs to be revisited while addressing
        # 'bzr branch' performance issues.
        for _ in self._insert_record_stream(stream, random_id=False):
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
        max_fulltext_len = 0
        max_fulltext_prefix = None
        insert_manager = None
        block_start = None
        block_length = None
        # XXX: TODO: remove this, it is just for safety checking for now
        inserted_keys = set()
        for record in stream:
            # Raise an error when a record is missing.
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(record.key, self)
            if random_id:
                if record.key in inserted_keys:
                    trace.note('Insert claimed random_id=True,'
                               ' but then inserted %r two times', record.key)
                    continue
                inserted_keys.add(record.key)
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
                    if insert_manager is None:
                        raise AssertionError('No insert_manager set')
                    value = "%d %d %d %d" % (block_start, block_length,
                                             record._start, record._end)
                    nodes = [(record.key, value, (record.parents,))]
                    # TODO: Consider buffering up many nodes to be added, not
                    #       sure how much overhead this has, but we're seeing
                    #       ~23s / 120s in add_records calls
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
            (found_sha1, start_point, end_point,
             type) = self._compressor.compress(record.key,
                                               bytes, record.sha1, soft=soft,
                                               nostore_sha=nostore_sha)
            # delta_ratio = float(len(bytes)) / (end_point - start_point)
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
            last_prefix = prefix
            if start_new_block:
                self._compressor.pop_last()
                flush()
                max_fulltext_len = len(bytes)
                (found_sha1, start_point, end_point,
                 type) = self._compressor.compress(record.key, bytes,
                                                   record.sha1)
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


from bzrlib._groupcompress_py import (
    apply_delta,
    apply_delta_to_source,
    encode_base128_int,
    decode_base128_int,
    decode_copy_instruction,
    LinesDeltaIndex,
    )
try:
    from bzrlib._groupcompress_pyx import (
        apply_delta,
        apply_delta_to_source,
        DeltaIndex,
        encode_base128_int,
        decode_base128_int,
        )
    GroupCompressor = PyrexGroupCompressor
except ImportError:
    GroupCompressor = PythonGroupCompressor

