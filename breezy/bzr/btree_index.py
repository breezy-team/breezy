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
#

"""B+Tree indices."""

from io import BytesIO

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import bisect
import math
import tempfile
import zlib
""",
)

from .. import chunk_writer, debug, fifo_cache, lru_cache, osutils, trace, transport
from . import index as _mod_index
from .index import _OPTION_KEY_ELEMENTS, _OPTION_LEN, _OPTION_NODE_REFS

_BTSIGNATURE = b"B+Tree Graph Index 2\n"
_OPTION_ROW_LENGTHS = b"row_lengths="
_LEAF_FLAG = b"type=leaf\n"
_INTERNAL_FLAG = b"type=internal\n"
_INTERNAL_OFFSET = b"offset="

_RESERVED_HEADER_BYTES = 120
_PAGE_SIZE = 4096

# 4K per page: 4MB - 1000 entries
_NODE_CACHE_SIZE = 1000


class _BuilderRow:
    """The stored state accumulated while writing out a row in the index.

    :ivar spool: A temporary file used to accumulate nodes for this row
        in the tree.
    :ivar nodes: The count of nodes emitted so far.
    """

    def __init__(self):
        """Create a _BuilderRow."""
        self.nodes = 0
        self.spool = None  # tempfile.TemporaryFile(prefix='bzr-index-row-')
        self.writer = None

    def finish_node(self, pad=True):
        byte_lines, _, padding = self.writer.finish()
        if self.nodes == 0:
            self.spool = BytesIO()
            # padded note:
            self.spool.write(b"\x00" * _RESERVED_HEADER_BYTES)
        elif self.nodes == 1:
            # We got bigger than 1 node, switch to a temp file
            spool = tempfile.TemporaryFile(prefix="bzr-index-row-")
            spool.write(self.spool.getvalue())
            self.spool = spool
        skipped_bytes = 0
        if not pad and padding:
            del byte_lines[-1]
            skipped_bytes = padding
        self.spool.writelines(byte_lines)
        remainder = (self.spool.tell() + skipped_bytes) % _PAGE_SIZE
        if remainder != 0:
            raise AssertionError(
                f"incorrect node length: {self.spool.tell()}, {remainder}"
            )
        self.nodes += 1
        self.writer = None


class _InternalBuilderRow(_BuilderRow):
    """The stored state accumulated while writing out internal rows."""

    def finish_node(self, pad=True):
        if not pad:
            raise AssertionError("Must pad internal nodes only.")
        _BuilderRow.finish_node(self)


class _LeafBuilderRow(_BuilderRow):
    """The stored state accumulated while writing out a leaf rows."""


class BTreeBuilder(_mod_index.GraphIndexBuilder):
    """A Builder for B+Tree based Graph indices.

    The resulting graph has the structure:

    _SIGNATURE OPTIONS NODES
    _SIGNATURE     := 'B+Tree Graph Index 1' NEWLINE
    OPTIONS        := REF_LISTS KEY_ELEMENTS LENGTH
    REF_LISTS      := 'node_ref_lists=' DIGITS NEWLINE
    KEY_ELEMENTS   := 'key_elements=' DIGITS NEWLINE
    LENGTH         := 'len=' DIGITS NEWLINE
    ROW_LENGTHS    := 'row_lengths' DIGITS (COMMA DIGITS)*
    NODES          := NODE_COMPRESSED*
    NODE_COMPRESSED:= COMPRESSED_BYTES{4096}
    NODE_RAW       := INTERNAL | LEAF
    INTERNAL       := INTERNAL_FLAG POINTERS
    LEAF           := LEAF_FLAG ROWS
    KEY_ELEMENT    := Not-whitespace-utf8
    KEY            := KEY_ELEMENT (NULL KEY_ELEMENT)*
    ROWS           := ROW*
    ROW            := KEY NULL ABSENT? NULL REFERENCES NULL VALUE NEWLINE
    ABSENT         := 'a'
    REFERENCES     := REFERENCE_LIST (TAB REFERENCE_LIST){node_ref_lists - 1}
    REFERENCE_LIST := (REFERENCE (CR REFERENCE)*)?
    REFERENCE      := KEY
    VALUE          := no-newline-no-null-bytes
    """

    def __init__(self, reference_lists=0, key_elements=1, spill_at=100000):
        """See GraphIndexBuilder.__init__.

        :param spill_at: Optional parameter controlling the maximum number
            of nodes that BTreeBuilder will hold in memory.
        """
        _mod_index.GraphIndexBuilder.__init__(
            self, reference_lists=reference_lists, key_elements=key_elements
        )
        self._spill_at = spill_at
        self._backing_indices = []
        # A map of {key: (node_refs, value)}
        self._nodes = {}
        # Indicate it hasn't been built yet
        self._nodes_by_key = None
        self._optimize_for_size = False

    def add_node(self, key, value, references=()):
        r"""Add a node to the index.

        If adding the node causes the builder to reach its spill_at threshold,
        disk spilling will be triggered.

        :param key: The key. keys are non-empty tuples containing
            as many whitespace-free utf8 bytestrings as the key length
            defined for this index.
        :param references: An iterable of iterables of keys. Each is a
            reference to another key.
        :param value: The value to associate with the key. It may be any
            bytes as long as it does not contain \\0 or \\n.
        """
        # Ensure that 'key' is a tuple.
        key = tuple(key)
        # we don't care about absent_references
        node_refs, _ = self._check_key_ref_value(key, references, value)
        if key in self._nodes:
            raise _mod_index.BadIndexDuplicateKey(key, self)
        self._nodes[key] = (node_refs, value)
        if self._nodes_by_key is not None and self._key_length > 1:
            self._update_nodes_by_key(key, value, node_refs)
        if len(self._nodes) < self._spill_at:
            return
        self._spill_mem_keys_to_disk()

    def _spill_mem_keys_to_disk(self):
        """Write the in memory keys down to disk to cap memory consumption.

        If we already have some keys written to disk, we will combine them so
        as to preserve the sorted order.  The algorithm for combining uses
        powers of two.  So on the first spill, write all mem nodes into a
        single index. On the second spill, combine the mem nodes with the nodes
        on disk to create a 2x sized disk index and get rid of the first index.
        On the third spill, create a single new disk index, which will contain
        the mem nodes, and preserve the existing 2x sized index.  On the fourth,
        combine mem with the first and second indexes, creating a new one of
        size 4x. On the fifth create a single new one, etc.
        """
        if self._combine_backing_indices:
            (new_backing_file, size, backing_pos) = self._spill_mem_keys_and_combine()
        else:
            new_backing_file, size = self._spill_mem_keys_without_combining()
        # Note: The transport here isn't strictly needed, because we will use
        #       direct access to the new_backing._file object
        new_backing = BTreeGraphIndex(
            transport.get_transport_from_path("."), "<temp>", size
        )
        # GC will clean up the file
        new_backing._file = new_backing_file
        if self._combine_backing_indices:
            if len(self._backing_indices) == backing_pos:
                self._backing_indices.append(None)
            self._backing_indices[backing_pos] = new_backing
            for bp in range(backing_pos):
                self._backing_indices[bp] = None
        else:
            self._backing_indices.append(new_backing)
        self._nodes = {}
        self._nodes_by_key = None

    def _spill_mem_keys_without_combining(self):
        return self._write_nodes(self._iter_mem_nodes(), allow_optimize=False)

    def _spill_mem_keys_and_combine(self):
        iterators_to_combine = [self._iter_mem_nodes()]
        pos = -1
        for pos, backing in enumerate(self._backing_indices):
            if backing is None:
                pos -= 1
                break
            iterators_to_combine.append(backing.iter_all_entries())
        backing_pos = pos + 1
        new_backing_file, size = self._write_nodes(
            self._iter_smallest(iterators_to_combine), allow_optimize=False
        )
        return new_backing_file, size, backing_pos

    def add_nodes(self, nodes):
        """Add nodes to the index.

        :param nodes: An iterable of (key, node_refs, value) entries to add.
        """
        if self.reference_lists:
            for key, value, node_refs in nodes:
                self.add_node(key, value, node_refs)
        else:
            for key, value in nodes:
                self.add_node(key, value)

    def _iter_mem_nodes(self):
        """Iterate over the nodes held in memory."""
        nodes = self._nodes
        if self.reference_lists:
            for key in sorted(nodes):
                references, value = nodes[key]
                yield self, key, value, references
        else:
            for key in sorted(nodes):
                references, value = nodes[key]
                yield self, key, value

    def _iter_smallest(self, iterators_to_combine):
        if len(iterators_to_combine) == 1:
            yield from iterators_to_combine[0]
            return
        current_values = []
        for iterator in iterators_to_combine:
            try:
                current_values.append(next(iterator))
            except StopIteration:
                current_values.append(None)
        last = None
        while True:
            # Decorate candidates with the value to allow 2.4's min to be used.
            candidates = [
                (item[1][1], item)
                for item in enumerate(current_values)
                if item[1] is not None
            ]
            if not len(candidates):
                return
            selected = min(candidates)
            # undecorate back to (pos, node)
            selected = selected[1]
            if last == selected[1][1]:
                raise _mod_index.BadIndexDuplicateKey(last, self)
            last = selected[1][1]
            # Yield, with self as the index
            yield (self,) + selected[1][1:]
            pos = selected[0]
            try:
                current_values[pos] = next(iterators_to_combine[pos])
            except StopIteration:
                current_values[pos] = None

    def _add_key(self, string_key, line, rows, allow_optimize=True):
        """Add a key to the current chunk.

        :param string_key: The key to add.
        :param line: The fully serialised key and value.
        :param allow_optimize: If set to False, prevent setting the optimize
            flag when writing out. This is used by the _spill_mem_keys_to_disk
            functionality.
        """
        new_leaf = False
        if rows[-1].writer is None:
            # opening a new leaf chunk;
            new_leaf = True
            for pos, internal_row in enumerate(rows[:-1]):
                # flesh out any internal nodes that are needed to
                # preserve the height of the tree
                if internal_row.writer is None:
                    length = _PAGE_SIZE
                    if internal_row.nodes == 0:
                        length -= _RESERVED_HEADER_BYTES  # padded
                    if allow_optimize:
                        optimize_for_size = self._optimize_for_size
                    else:
                        optimize_for_size = False
                    internal_row.writer = chunk_writer.ChunkWriter(
                        length, 0, optimize_for_size=optimize_for_size
                    )
                    internal_row.writer.write(_INTERNAL_FLAG)
                    internal_row.writer.write(
                        _INTERNAL_OFFSET + b"%d\n" % rows[pos + 1].nodes
                    )
            # add a new leaf
            length = _PAGE_SIZE
            if rows[-1].nodes == 0:
                length -= _RESERVED_HEADER_BYTES  # padded
            rows[-1].writer = chunk_writer.ChunkWriter(
                length, optimize_for_size=self._optimize_for_size
            )
            rows[-1].writer.write(_LEAF_FLAG)
        if rows[-1].writer.write(line):
            # if we failed to write, despite having an empty page to write to,
            # then line is too big. raising the error avoids infinite recursion
            # searching for a suitably large page that will not be found.
            if new_leaf:
                raise _mod_index.BadIndexKey(string_key)
            # this key did not fit in the node:
            rows[-1].finish_node()
            key_line = string_key + b"\n"
            new_row = True
            for row in reversed(rows[:-1]):
                # Mark the start of the next node in the node above. If it
                # doesn't fit then propagate upwards until we find one that
                # it does fit into.
                if row.writer.write(key_line):
                    row.finish_node()
                else:
                    # We've found a node that can handle the pointer.
                    new_row = False
                    break
            # If we reached the current root without being able to mark the
            # division point, then we need a new root:
            if new_row:
                # We need a new row
                if "index" in debug.debug_flags:
                    trace.mutter("Inserting new global row.")
                new_row = _InternalBuilderRow()
                reserved_bytes = 0
                rows.insert(0, new_row)
                # This will be padded, hence the -100
                new_row.writer = chunk_writer.ChunkWriter(
                    _PAGE_SIZE - _RESERVED_HEADER_BYTES,
                    reserved_bytes,
                    optimize_for_size=self._optimize_for_size,
                )
                new_row.writer.write(_INTERNAL_FLAG)
                new_row.writer.write(_INTERNAL_OFFSET + b"%d\n" % (rows[1].nodes - 1))
                new_row.writer.write(key_line)
            self._add_key(string_key, line, rows, allow_optimize=allow_optimize)

    def _write_nodes(self, node_iterator, allow_optimize=True):
        """Write node_iterator out as a B+Tree.

        :param node_iterator: An iterator of sorted nodes. Each node should
            match the output given by iter_all_entries.
        :param allow_optimize: If set to False, prevent setting the optimize
            flag when writing out. This is used by the _spill_mem_keys_to_disk
            functionality.
        :return: A file handle for a temporary file containing a B+Tree for
            the nodes.
        """
        # The index rows - rows[0] is the root, rows[1] is the layer under it
        # etc.
        rows = []
        # forward sorted by key. In future we may consider topological sorting,
        # at the cost of table scans for direct lookup, or a second index for
        # direct lookup
        key_count = 0
        # A stack with the number of nodes of each size. 0 is the root node
        # and must always be 1 (if there are any nodes in the tree).
        self.row_lengths = []
        # Loop over all nodes adding them to the bottom row
        # (rows[-1]). When we finish a chunk in a row,
        # propagate the key that didn't fit (comes after the chunk) to the
        # row above, transitively.
        for node in node_iterator:
            if key_count == 0:
                # First key triggers the first row
                rows.append(_LeafBuilderRow())
            key_count += 1
            string_key, line = _btree_serializer._flatten_node(
                node, self.reference_lists
            )
            self._add_key(string_key, line, rows, allow_optimize=allow_optimize)
        for row in reversed(rows):
            pad = not isinstance(row, _LeafBuilderRow)
            row.finish_node(pad=pad)
        lines = [_BTSIGNATURE]
        lines.append(b"%s%d\n" % (_OPTION_NODE_REFS, self.reference_lists))
        lines.append(b"%s%d\n" % (_OPTION_KEY_ELEMENTS, self._key_length))
        lines.append(b"%s%d\n" % (_OPTION_LEN, key_count))
        row_lengths = [row.nodes for row in rows]
        lines.append(
            _OPTION_ROW_LENGTHS
            + ",".join(map(str, row_lengths)).encode("ascii")
            + b"\n"
        )
        if row_lengths and row_lengths[-1] > 1:
            result = tempfile.NamedTemporaryFile(prefix="bzr-index-")
        else:
            result = BytesIO()
        result.writelines(lines)
        position = sum(map(len, lines))
        if position > _RESERVED_HEADER_BYTES:
            raise AssertionError(
                "Could not fit the header in the"
                f" reserved space: {position} > {_RESERVED_HEADER_BYTES}"
            )
        # write the rows out:
        for row in rows:
            reserved = _RESERVED_HEADER_BYTES  # reserved space for first node
            row.spool.flush()
            row.spool.seek(0)
            # copy nodes to the finalised file.
            # Special case the first node as it may be prefixed
            node = row.spool.read(_PAGE_SIZE)
            result.write(node[reserved:])
            if len(node) == _PAGE_SIZE:
                result.write(b"\x00" * (reserved - position))
            position = 0  # Only the root row actually has an offset
            copied_len = osutils.pumpfile(row.spool, result)
            if copied_len != (row.nodes - 1) * _PAGE_SIZE:
                if not isinstance(row, _LeafBuilderRow):
                    raise AssertionError(
                        "Incorrect amount of data copied"
                        f" expected: {(row.nodes - 1) * _PAGE_SIZE}, got: {copied_len}"
                    )
        result.flush()
        size = result.tell()
        result.seek(0)
        return result, size

    def finish(self):
        """Finalise the index.

        :return: A file handle for a temporary file containing the nodes added
            to the index.
        """
        return self._write_nodes(self.iter_all_entries())[0]

    def iter_all_entries(self):
        """Iterate over all keys within the index.

        :return: An iterable of (index, key, value, reference_lists). There is
            no defined order for the result iteration - it will be in the most
            efficient order for the index (in this case dictionary hash order).
        """
        if "evil" in debug.debug_flags:
            trace.mutter_callsite(3, "iter_all_entries scales with size of history.")
        # Doing serial rather than ordered would be faster; but this shouldn't
        # be getting called routinely anyway.
        iterators = [self._iter_mem_nodes()]
        for backing in self._backing_indices:
            if backing is not None:
                iterators.append(backing.iter_all_entries())
        if len(iterators) == 1:
            return iterators[0]
        return self._iter_smallest(iterators)

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable of (index, key, value, reference_lists). There is
            no defined order for the result iteration - it will be in the most
            efficient order for the index (keys iteration order in this case).
        """
        keys = set(keys)
        # Note: We don't use keys.intersection() here. If you read the C api,
        #       set.intersection(other) special cases when other is a set and
        #       will iterate the smaller of the two and lookup in the other.
        #       It does *not* do this for any other type (even dict, unlike
        #       some other set functions.) Since we expect keys is generally <<
        #       self._nodes, it is faster to iterate over it in a list
        #       comprehension
        nodes = self._nodes
        local_keys = [key for key in keys if key in nodes]
        if self.reference_lists:
            for key in local_keys:
                node = nodes[key]
                yield self, key, node[1], node[0]
        else:
            for key in local_keys:
                node = nodes[key]
                yield self, key, node[1]
        # Find things that are in backing indices that have not been handled
        # yet.
        if not self._backing_indices:
            return  # We won't find anything there either
        # Remove all of the keys that we found locally
        keys.difference_update(local_keys)
        for backing in self._backing_indices:
            if backing is None:
                continue
            if not keys:
                return
            for node in backing.iter_entries(keys):
                keys.remove(node[1])
                yield (self,) + node[1:]

    def iter_entries_prefix(self, keys):
        """Iterate over keys within the index using prefix matching.

        Prefix matching is applied within the tuple of a key, not to within
        the bytestring of each key element. e.g. if you have the keys ('foo',
        'bar'), ('foobar', 'gam') and do a prefix search for ('foo', None) then
        only the former key is returned.

        :param keys: An iterable providing the key prefixes to be retrieved.
            Each key prefix takes the form of a tuple the length of a key, but
            with the last N elements 'None' rather than a regular bytestring.
            The first element cannot be 'None'.
        :return: An iterable as per iter_all_entries, but restricted to the
            keys with a matching prefix to those supplied. No additional keys
            will be returned, and every match that is in the index will be
            returned.
        """
        keys = set(keys)
        if not keys:
            return
        for backing in self._backing_indices:
            if backing is None:
                continue
            for node in backing.iter_entries_prefix(keys):
                yield (self,) + node[1:]
        if self._key_length == 1:
            for key in keys:
                _mod_index._sanity_check_key(self, key)
                try:
                    node = self._nodes[key]
                except KeyError:
                    continue
                if self.reference_lists:
                    yield self, key, node[1], node[0]
                else:
                    yield self, key, node[1]
            return
        nodes_by_key = self._get_nodes_by_key()
        yield from _mod_index._iter_entries_prefix(self, nodes_by_key, keys)

    def _get_nodes_by_key(self):
        if self._nodes_by_key is None:
            nodes_by_key = {}
            if self.reference_lists:
                for key, (references, value) in self._nodes.items():
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key, value, references
            else:
                for key, (_references, value) in self._nodes.items():
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key, value
            self._nodes_by_key = nodes_by_key
        return self._nodes_by_key

    def key_count(self):
        """Return an estimate of the number of keys in this index.

        For InMemoryGraphIndex the estimate is exact.
        """
        return len(self._nodes) + sum(
            backing.key_count()
            for backing in self._backing_indices
            if backing is not None
        )

    def validate(self):
        """In memory index's have no known corruption at the moment."""

    def __lt__(self, other):
        if isinstance(other, type(self)):
            return self._nodes < other._nodes
        # Always sort existing indexes before ones that are still being built.
        if isinstance(other, BTreeGraphIndex):
            return False
        raise TypeError


class _LeafNode(dict):
    """A leaf node for a serialised B+Tree index."""

    __slots__ = ("_keys", "max_key", "min_key")

    def __init__(self, bytes, key_length, ref_list_length):
        """Parse bytes to create a leaf node object."""
        # splitlines mangles the \r delimiters.. don't use it.
        key_list = _btree_serializer._parse_leaf_lines(
            bytes, key_length, ref_list_length
        )
        if key_list:
            self.min_key = key_list[0][0]
            self.max_key = key_list[-1][0]
        else:
            self.min_key = self.max_key = None
        super().__init__(key_list)
        self._keys = dict(self)

    def all_items(self):
        """Return a sorted list of (key, (value, refs)) items."""
        items = sorted(self.items())
        return items

    def all_keys(self):
        """Return a sorted list of all keys."""
        keys = sorted(self.keys())
        return keys


class _InternalNode:
    """An internal node for a serialised B+Tree index."""

    __slots__ = ("keys", "offset")

    def __init__(self, bytes):
        """Parse bytes to create an internal node object."""
        # splitlines mangles the \r delimiters.. don't use it.
        self.keys = self._parse_lines(bytes.split(b"\n"))

    def _parse_lines(self, lines):
        nodes = []
        self.offset = int(lines[1][7:])
        for line in lines[2:]:
            if line == b"":
                break
            nodes.append(tuple(line.split(b"\0")))
        return nodes


class BTreeGraphIndex:
    """Access to nodes via the standard GraphIndex interface for B+Tree's.

    Individual nodes are held in a LRU cache. This holds the root node in
    memory except when very large walks are done.
    """

    def __init__(self, transport, name, size, unlimited_cache=False, offset=0):
        """Create a B+Tree index object on the index name.

        :param transport: The transport to read data for the index from.
        :param name: The file name of the index on transport.
        :param size: Optional size of the index in bytes. This allows
            compatibility with the GraphIndex API, as well as ensuring that
            the initial read (to read the root node header) can be done
            without over-reading even on empty indices, and on small indices
            allows single-IO to read the entire index.
        :param unlimited_cache: If set to True, then instead of using an
            LRUCache with size _NODE_CACHE_SIZE, we will use a dict and always
            cache all leaf nodes.
        :param offset: The start of the btree index data isn't byte 0 of the
            file. Instead it starts at some point later.
        """
        self._transport = transport
        self._name = name
        self._size = size
        self._file = None
        self._recommended_pages = self._compute_recommended_pages()
        self._root_node = None
        self._base_offset = offset
        self._leaf_factory = _LeafNode
        # Default max size is 100,000 leave values
        self._leaf_value_cache = None  # lru_cache.LRUCache(100*1000)
        if unlimited_cache:
            self._leaf_node_cache = {}
            self._internal_node_cache = {}
        else:
            self._leaf_node_cache = lru_cache.LRUCache(_NODE_CACHE_SIZE)
            # We use a FIFO here just to prevent possible blowout. However, a
            # 300k record btree has only 3k leaf nodes, and only 20 internal
            # nodes. A value of 100 scales to ~100*100*100 = 1M records.
            self._internal_node_cache = fifo_cache.FIFOCache(100)
        self._key_count = None
        self._row_lengths = None
        self._row_offsets = None  # Start of each row, [-1] is the end

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        """Equal when self and other were created with the same parameters."""
        return (
            isinstance(self, type(other))
            and self._transport == other._transport
            and self._name == other._name
            and self._size == other._size
        )

    def __lt__(self, other):
        if isinstance(other, type(self)):
            return (self._name, self._size) < (other._name, other._size)
        # Always sort existing indexes before ones that are still being built.
        if isinstance(other, BTreeBuilder):
            return True
        raise TypeError

    def __ne__(self, other):
        return not self.__eq__(other)

    def _get_and_cache_nodes(self, nodes):
        """Read nodes and cache them in the lru.

        The nodes list supplied is sorted and then read from disk, each node
        being inserted it into the _node_cache.

        Note: Asking for more nodes than the _node_cache can contain will
        result in some of the results being immediately discarded, to prevent
        this an assertion is raised if more nodes are asked for than are
        cachable.

        :return: A dict of {node_pos: node}
        """
        found = {}
        start_of_leaves = None
        for node_pos, node in self._read_nodes(sorted(nodes)):
            if node_pos == 0:  # Special case
                self._root_node = node
            else:
                if start_of_leaves is None:
                    start_of_leaves = self._row_offsets[-2]
                if node_pos < start_of_leaves:
                    self._internal_node_cache[node_pos] = node
                else:
                    self._leaf_node_cache[node_pos] = node
            found[node_pos] = node
        return found

    def _compute_recommended_pages(self):
        """Convert transport's recommended_page_size into btree pages.

        recommended_page_size is in bytes, we want to know how many _PAGE_SIZE
        pages fit in that length.
        """
        recommended_read = self._transport.recommended_page_size()
        recommended_pages = int(math.ceil(recommended_read / _PAGE_SIZE))
        return recommended_pages

    def _compute_total_pages_in_index(self):
        """How many pages are in the index.

        If we have read the header we will use the value stored there.
        Otherwise it will be computed based on the length of the index.
        """
        if self._size is None:
            raise AssertionError(
                "_compute_total_pages_in_index should not be"
                " called when self._size is None"
            )
        if self._root_node is not None:
            # This is the number of pages as defined by the header
            return self._row_offsets[-1]
        # This is the number of pages as defined by the size of the index. They
        # should be indentical.
        total_pages = int(math.ceil(self._size / _PAGE_SIZE))
        return total_pages

    def _expand_offsets(self, offsets):
        """Find extra pages to download.

        The idea is that we always want to make big-enough requests (like 64kB
        for http), so that we don't waste round trips. So given the entries
        that we already have cached and the new pages being downloaded figure
        out what other pages we might want to read.

        See also doc/developers/btree_index_prefetch.txt for more details.

        :param offsets: The offsets to be read
        :return: A list of offsets to download
        """
        if "index" in debug.debug_flags:
            trace.mutter("expanding: %s\toffsets: %s", self._name, offsets)

        if len(offsets) >= self._recommended_pages:
            # Don't add more, we are already requesting more than enough
            if "index" in debug.debug_flags:
                trace.mutter(
                    "  not expanding large request (%s >= %s)",
                    len(offsets),
                    self._recommended_pages,
                )
            return offsets
        if self._size is None:
            # Don't try anything, because we don't know where the file ends
            if "index" in debug.debug_flags:
                trace.mutter("  not expanding without knowing index size")
            return offsets
        total_pages = self._compute_total_pages_in_index()
        cached_offsets = self._get_offsets_to_cached_pages()
        # If reading recommended_pages would read the rest of the index, just
        # do so.
        if total_pages - len(cached_offsets) <= self._recommended_pages:
            # Read whatever is left
            if cached_offsets:
                expanded = [x for x in range(total_pages) if x not in cached_offsets]
            else:
                expanded = list(range(total_pages))
            if "index" in debug.debug_flags:
                trace.mutter("  reading all unread pages: %s", expanded)
            return expanded

        if self._root_node is None:
            # ATM on the first read of the root node of a large index, we don't
            # bother pre-reading any other pages. This is because the
            # likelyhood of actually reading interesting pages is very low.
            # See doc/developers/btree_index_prefetch.txt for a discussion, and
            # a possible implementation when we are guessing that the second
            # layer index is small
            final_offsets = offsets
        else:
            tree_depth = len(self._row_lengths)
            if len(cached_offsets) < tree_depth and len(offsets) == 1:
                # We haven't read enough to justify expansion
                # If we are only going to read the root node, and 1 leaf node,
                # then it isn't worth expanding our request. Once we've read at
                # least 2 nodes, then we are probably doing a search, and we
                # start expanding our requests.
                if "index" in debug.debug_flags:
                    trace.mutter("  not expanding on first reads")
                return offsets
            final_offsets = self._expand_to_neighbors(
                offsets, cached_offsets, total_pages
            )

        final_offsets = sorted(final_offsets)
        if "index" in debug.debug_flags:
            trace.mutter("expanded:  %s", final_offsets)
        return final_offsets

    def _expand_to_neighbors(self, offsets, cached_offsets, total_pages):
        """Expand requests to neighbors until we have enough pages.

        This is called from _expand_offsets after policy has determined that we
        want to expand.
        We only want to expand requests within a given layer. We cheat a little
        bit and assume all requests will be in the same layer. This is true
        given the current design, but if it changes this algorithm may perform
        oddly.

        :param offsets: requested offsets
        :param cached_offsets: offsets for pages we currently have cached
        :return: A set() of offsets after expansion
        """
        final_offsets = set(offsets)
        first = end = None
        new_tips = set(final_offsets)
        while len(final_offsets) < self._recommended_pages and new_tips:
            next_tips = set()
            for pos in new_tips:
                if first is None:
                    first, end = self._find_layer_first_and_end(pos)
                previous = pos - 1
                if (
                    previous > 0
                    and previous not in cached_offsets
                    and previous not in final_offsets
                    and previous >= first
                ):
                    next_tips.add(previous)
                after = pos + 1
                if (
                    after < total_pages
                    and after not in cached_offsets
                    and after not in final_offsets
                    and after < end
                ):
                    next_tips.add(after)
                # This would keep us from going bigger than
                # recommended_pages by only expanding the first offsets.
                # However, if we are making a 'wide' request, it is
                # reasonable to expand all points equally.
                # if len(final_offsets) > recommended_pages:
                #     break
            final_offsets.update(next_tips)
            new_tips = next_tips
        return final_offsets

    def clear_cache(self):
        """Clear out any cached/memoized values.

        This can be called at any time, but generally it is used when we have
        extracted some information, but don't expect to be requesting any more
        from this index.
        """
        # Note that we don't touch self._root_node or self._internal_node_cache
        # We don't expect either of those to be big, and it can save
        # round-trips in the future. We may re-evaluate this if InternalNode
        # memory starts to be an issue.
        self._leaf_node_cache.clear()

    def external_references(self, ref_list_num):
        if self._root_node is None:
            self._get_root_node()
        if ref_list_num + 1 > self.node_ref_lists:
            raise ValueError(
                f"No ref list {ref_list_num}, index has {self.node_ref_lists} ref lists"
            )
        keys = set()
        refs = set()
        for node in self.iter_all_entries():
            keys.add(node[1])
            refs.update(node[3][ref_list_num])
        return refs - keys

    def _find_layer_first_and_end(self, offset):
        """Find the start/stop nodes for the layer corresponding to offset.

        :return: (first, end)
            first is the first node in this layer
            end is the first node of the next layer
        """
        first = end = 0
        for roffset in self._row_offsets:
            first = end
            end = roffset
            if offset < roffset:
                break
        return first, end

    def _get_offsets_to_cached_pages(self):
        """Determine what nodes we already have cached."""
        cached_offsets = set(self._internal_node_cache)
        # cache may be dict or LRUCache, keys() is the common method
        cached_offsets.update(self._leaf_node_cache.keys())
        if self._root_node is not None:
            cached_offsets.add(0)
        return cached_offsets

    def _get_root_node(self):
        if self._root_node is None:
            # We may not have a root node yet
            self._get_internal_nodes([0])
        return self._root_node

    def _get_nodes(self, cache, node_indexes):
        found = {}
        needed = []
        for idx in node_indexes:
            if idx == 0 and self._root_node is not None:
                found[0] = self._root_node
                continue
            try:
                found[idx] = cache[idx]
            except KeyError:
                needed.append(idx)
        if not needed:
            return found
        needed = self._expand_offsets(needed)
        found.update(self._get_and_cache_nodes(needed))
        return found

    def _get_internal_nodes(self, node_indexes):
        """Get a node, from cache or disk.

        After getting it, the node will be cached.
        """
        return self._get_nodes(self._internal_node_cache, node_indexes)

    def _cache_leaf_values(self, nodes):
        """Cache directly from key => value, skipping the btree."""
        if self._leaf_value_cache is not None:
            for node in nodes.values():
                for key, value in node.all_items():
                    if key in self._leaf_value_cache:
                        # Don't add the rest of the keys, we've seen this node
                        # before.
                        break
                    self._leaf_value_cache[key] = value

    def _get_leaf_nodes(self, node_indexes):
        """Get a bunch of nodes, from cache or disk."""
        found = self._get_nodes(self._leaf_node_cache, node_indexes)
        self._cache_leaf_values(found)
        return found

    def iter_all_entries(self):
        """Iterate over all keys within the index.

        :return: An iterable of (index, key, value) or
            (index, key, value, reference_lists).
            The former tuple is used when there are no reference lists in the
            index, making the API compatible with simple key:value index types.
            There is no defined order for the result iteration - it will be in
            the most efficient order for the index.
        """
        if "evil" in debug.debug_flags:
            trace.mutter_callsite(3, "iter_all_entries scales with size of history.")
        if not self.key_count():
            return
        if self._row_offsets[-1] == 1:
            # There is only the root node, and we read that via key_count()
            if self.node_ref_lists:
                for key, (value, refs) in self._root_node.all_items():
                    yield (self, key, value, refs)
            else:
                for key, (value, _refs) in self._root_node.all_items():
                    yield (self, key, value)
            return
        start_of_leaves = self._row_offsets[-2]
        end_of_leaves = self._row_offsets[-1]
        needed_offsets = list(range(start_of_leaves, end_of_leaves))
        if needed_offsets == [0]:
            # Special case when we only have a root node, as we have already
            # read everything
            nodes = [(0, self._root_node)]
        else:
            nodes = self._read_nodes(needed_offsets)
        # We iterate strictly in-order so that we can use this function
        # for spilling index builds to disk.
        if self.node_ref_lists:
            for _, node in nodes:
                for key, (value, refs) in node.all_items():
                    yield (self, key, value, refs)
        else:
            for _, node in nodes:
                for key, (value, _refs) in node.all_items():
                    yield (self, key, value)

    @staticmethod
    def _multi_bisect_right(in_keys, fixed_keys):
        """Find the positions where each 'in_key' would fit in fixed_keys.

        This is equivalent to doing "bisect_right" on each in_key into
        fixed_keys

        :param in_keys: A sorted list of keys to match with fixed_keys
        :param fixed_keys: A sorted list of keys to match against
        :return: A list of (integer position, [key list]) tuples.
        """
        if not in_keys:
            return []
        if not fixed_keys:
            # no pointers in the fixed_keys list, which means everything must
            # fall to the left.
            return [(0, in_keys)]

        # TODO: Iterating both lists will generally take M + N steps
        #       Bisecting each key will generally take M * log2 N steps.
        #       If we had an efficient way to compare, we could pick the method
        #       based on which has the fewer number of steps.
        #       There is also the argument that bisect_right is a compiled
        #       function, so there is even more to be gained.
        # iter_steps = len(in_keys) + len(fixed_keys)
        # bisect_steps = len(in_keys) * math.log(len(fixed_keys), 2)
        if len(in_keys) == 1:  # Bisect will always be faster for M = 1
            return [(bisect.bisect_right(fixed_keys, in_keys[0]), in_keys)]
        # elif bisect_steps < iter_steps:
        #     offsets = {}
        #     for key in in_keys:
        #         offsets.setdefault(bisect_right(fixed_keys, key),
        #                            []).append(key)
        #     return [(o, offsets[o]) for o in sorted(offsets)]
        in_keys_iter = iter(in_keys)
        fixed_keys_iter = enumerate(fixed_keys)
        cur_in_key = next(in_keys_iter)
        cur_fixed_offset, cur_fixed_key = next(fixed_keys_iter)

        class InputDone(Exception):
            pass

        class FixedDone(Exception):
            pass

        output = []
        cur_out = []

        # TODO: Another possibility is that rather than iterating on each side,
        #       we could use a combination of bisecting and iterating. For
        #       example, while cur_in_key < fixed_key, bisect to find its
        #       point, then iterate all matching keys, then bisect (restricted
        #       to only the remainder) for the next one, etc.
        try:
            while True:
                if cur_in_key < cur_fixed_key:
                    cur_keys = []
                    cur_out = (cur_fixed_offset, cur_keys)
                    output.append(cur_out)
                    while cur_in_key < cur_fixed_key:
                        cur_keys.append(cur_in_key)
                        try:
                            cur_in_key = next(in_keys_iter)
                        except StopIteration as exc:
                            raise InputDone from exc
                    # At this point cur_in_key must be >= cur_fixed_key
                # step the cur_fixed_key until we pass the cur key, or walk off
                # the end
                while cur_in_key >= cur_fixed_key:
                    try:
                        cur_fixed_offset, cur_fixed_key = next(fixed_keys_iter)
                    except StopIteration as exc:
                        raise FixedDone from exc
        except InputDone:
            # We consumed all of the input, nothing more to do
            pass
        except FixedDone:
            # There was some input left, but we consumed all of fixed, so we
            # have to add one more for the tail
            cur_keys = [cur_in_key]
            cur_keys.extend(in_keys_iter)
            cur_out = (len(fixed_keys), cur_keys)
            output.append(cur_out)
        return output

    def _walk_through_internal_nodes(self, keys):
        """Take the given set of keys, and find the corresponding LeafNodes.

        :param keys: An unsorted iterable of keys to search for
        :return: (nodes, index_and_keys)
            nodes is a dict mapping {index: LeafNode}
            keys_at_index is a list of tuples of [(index, [keys for Leaf])]
        """
        # 6 seconds spent in miss_torture using the sorted() line.
        # Even with out of order disk IO it seems faster not to sort it when
        # large queries are being made.
        keys_at_index = [(0, sorted(keys))]

        for _row_pos, next_row_start in enumerate(self._row_offsets[1:-1]):
            node_indexes = [idx for idx, s_keys in keys_at_index]
            nodes = self._get_internal_nodes(node_indexes)

            next_nodes_and_keys = []
            for node_index, sub_keys in keys_at_index:
                node = nodes[node_index]
                positions = self._multi_bisect_right(sub_keys, node.keys)
                node_offset = next_row_start + node.offset
                next_nodes_and_keys.extend(
                    [(node_offset + pos, s_keys) for pos, s_keys in positions]
                )
            keys_at_index = next_nodes_and_keys
        # We should now be at the _LeafNodes
        node_indexes = [idx for idx, s_keys in keys_at_index]

        # TODO: We may *not* want to always read all the nodes in one
        #       big go. Consider setting a max size on this.
        nodes = self._get_leaf_nodes(node_indexes)
        return nodes, keys_at_index

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable as per iter_all_entries, but restricted to the
            keys supplied. No additional keys will be returned, and every
            key supplied that is in the index will be returned.
        """
        # 6 seconds spent in miss_torture using the sorted() line.
        # Even with out of order disk IO it seems faster not to sort it when
        # large queries are being made.
        # However, now that we are doing multi-way bisecting, we need the keys
        # in sorted order anyway. We could change the multi-way code to not
        # require sorted order. (For example, it bisects for the first node,
        # does an in-order search until a key comes before the current point,
        # which it then bisects for, etc.)
        keys = frozenset(keys)
        if not keys:
            return

        if not self.key_count():
            return

        needed_keys = []
        if self._leaf_value_cache is None:
            needed_keys = keys
        else:
            for key in keys:
                value = self._leaf_value_cache.get(key, None)
                if value is not None:
                    # This key is known not to be here, skip it
                    value, refs = value
                    if self.node_ref_lists:
                        yield (self, key, value, refs)
                    else:
                        yield (self, key, value)
                else:
                    needed_keys.append(key)

        needed_keys = keys
        if not needed_keys:
            return
        nodes, nodes_and_keys = self._walk_through_internal_nodes(needed_keys)
        for node_index, sub_keys in nodes_and_keys:
            if not sub_keys:
                continue
            node = nodes[node_index]
            for next_sub_key in sub_keys:
                if next_sub_key in node:
                    value, refs = node[next_sub_key]
                    if self.node_ref_lists:
                        yield (self, next_sub_key, value, refs)
                    else:
                        yield (self, next_sub_key, value)

    def _find_ancestors(self, keys, ref_list_num, parent_map, missing_keys):
        """Find the parent_map information for the set of keys.

        This populates the parent_map dict and missing_keys set based on the
        queried keys. It also can fill out an arbitrary number of parents that
        it finds while searching for the supplied keys.

        It is unlikely that you want to call this directly. See
        "CombinedGraphIndex.find_ancestry()" for a more appropriate API.

        :param keys: A keys whose ancestry we want to return
            Every key will either end up in 'parent_map' or 'missing_keys'.
        :param ref_list_num: This index in the ref_lists is the parents we
            care about.
        :param parent_map: {key: parent_keys} for keys that are present in this
            index. This may contain more entries than were in 'keys', that are
            reachable ancestors of the keys requested.
        :param missing_keys: keys which are known to be missing in this index.
            This may include parents that were not directly requested, but we
            were able to determine that they are not present in this index.
        :return: search_keys    parents that were found but not queried to know
            if they are missing or present. Callers can re-query this index for
            those keys, and they will be placed into parent_map or missing_keys
        """
        if not self.key_count():
            # We use key_count() to trigger reading the root node and
            # determining info about this BTreeGraphIndex
            # If we don't have any keys, then everything is missing
            missing_keys.update(keys)
            return set()
        if ref_list_num >= self.node_ref_lists:
            raise ValueError(
                f"No ref list {ref_list_num}, index has {self.node_ref_lists} ref lists"
            )

        # The main trick we are trying to accomplish is that when we find a
        # key listing its parents, we expect that the parent key is also likely
        # to sit on the same page. Allowing us to expand parents quickly
        # without suffering the full stack of bisecting, etc.
        nodes, nodes_and_keys = self._walk_through_internal_nodes(keys)

        # These are parent keys which could not be immediately resolved on the
        # page where the child was present. Note that we may already be
        # searching for that key, and it may actually be present [or known
        # missing] on one of the other pages we are reading.
        # TODO:
        #   We could try searching for them in the immediate previous or next
        #   page. If they occur "later" we could put them in a pending lookup
        #   set, and then for each node we read thereafter we could check to
        #   see if they are present.
        #   However, we don't know the impact of keeping this list of things
        #   that I'm going to search for every node I come across from here on
        #   out.
        #   It doesn't handle the case when the parent key is missing on a
        #   page that we *don't* read. So we already have to handle being
        #   re-entrant for that.
        #   Since most keys contain a date string, they are more likely to be
        #   found earlier in the file than later, but we would know that right
        #   away (key < min_key), and wouldn't keep searching it on every other
        #   page that we read.
        #   Mostly, it is an idea, one which should be benchmarked.
        parents_not_on_page = set()

        for node_index, sub_keys in nodes_and_keys:
            if not sub_keys:
                continue
            # sub_keys is all of the keys we are looking for that should exist
            # on this page, if they aren't here, then they won't be found
            node = nodes[node_index]
            parents_to_check = set()
            for next_sub_key in sub_keys:
                if next_sub_key not in node:
                    # This one is just not present in the index at all
                    missing_keys.add(next_sub_key)
                else:
                    value, refs = node[next_sub_key]
                    parent_keys = refs[ref_list_num]
                    parent_map[next_sub_key] = parent_keys
                    parents_to_check.update(parent_keys)
            # Don't look for things we've already found
            parents_to_check = parents_to_check.difference(parent_map)
            # this can be used to test the benefit of having the check loop
            # inlined.
            # parents_not_on_page.update(parents_to_check)
            # continue
            while parents_to_check:
                next_parents_to_check = set()
                for key in parents_to_check:
                    if key in node:
                        value, refs = node[key]
                        parent_keys = refs[ref_list_num]
                        parent_map[key] = parent_keys
                        next_parents_to_check.update(parent_keys)
                    else:
                        # This parent either is genuinely missing, or should be
                        # found on another page. Perf test whether it is better
                        # to check if this node should fit on this page or not.
                        # in the 'everything-in-one-pack' scenario, this *not*
                        # doing the check is 237ms vs 243ms.
                        # So slightly better, but I assume the standard 'lots
                        # of packs' is going to show a reasonable improvement
                        # from the check, because it avoids 'going around
                        # again' for everything that is in another index
                        # parents_not_on_page.add(key)
                        # Missing for some reason
                        if key < node.min_key:
                            # in the case of bzr.dev, 3.4k/5.3k misses are
                            # 'earlier' misses (65%)
                            parents_not_on_page.add(key)
                        elif key > node.max_key:
                            # This parent key would be present on a different
                            # LeafNode
                            parents_not_on_page.add(key)
                        else:
                            # assert (key != node.min_key and
                            #         key != node.max_key)
                            # If it was going to be present, it would be on
                            # *this* page, so mark it missing.
                            missing_keys.add(key)
                parents_to_check = next_parents_to_check.difference(parent_map)
                # Might want to do another .difference() from missing_keys
        # parents_not_on_page could have been found on a different page, or be
        # known to be missing. So cull out everything that has already been
        # found.
        search_keys = parents_not_on_page.difference(parent_map).difference(
            missing_keys
        )
        return search_keys

    def iter_entries_prefix(self, keys):
        """Iterate over keys within the index using prefix matching.

        Prefix matching is applied within the tuple of a key, not to within
        the bytestring of each key element. e.g. if you have the keys ('foo',
        'bar'), ('foobar', 'gam') and do a prefix search for ('foo', None) then
        only the former key is returned.

        WARNING: Note that this method currently causes a full index parse
        unconditionally (which is reasonably appropriate as it is a means for
        thunking many small indices into one larger one and still supplies
        iter_all_entries at the thunk layer).

        :param keys: An iterable providing the key prefixes to be retrieved.
            Each key prefix takes the form of a tuple the length of a key, but
            with the last N elements 'None' rather than a regular bytestring.
            The first element cannot be 'None'.
        :return: An iterable as per iter_all_entries, but restricted to the
            keys with a matching prefix to those supplied. No additional keys
            will be returned, and every match that is in the index will be
            returned.
        """
        keys = sorted(set(keys))
        if not keys:
            return
        # Load if needed to check key lengths
        if self._key_count is None:
            self._get_root_node()
        # TODO: only access nodes that can satisfy the prefixes we are looking
        # for. For now, to meet API usage (as this function is not used by
        # current breezy) just suck the entire index and iterate in memory.
        nodes = {}
        if self.node_ref_lists:
            if self._key_length == 1:
                for _1, key, value, refs in self.iter_all_entries():
                    nodes[key] = value, refs
            else:
                nodes_by_key = {}
                for _1, key, value, refs in self.iter_all_entries():
                    key_value = key, value, refs
                    # For a key of (foo, bar, baz) create
                    # _nodes_by_key[foo][bar][baz] = key_value
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key_value
        else:
            if self._key_length == 1:
                for _1, key, value in self.iter_all_entries():
                    nodes[key] = value
            else:
                nodes_by_key = {}
                for _1, key, value in self.iter_all_entries():
                    key_value = key, value
                    # For a key of (foo, bar, baz) create
                    # _nodes_by_key[foo][bar][baz] = key_value
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key_value
        if self._key_length == 1:
            for key in keys:
                _mod_index._sanity_check_key(self, key)
                try:
                    if self.node_ref_lists:
                        value, node_refs = nodes[key]
                        yield self, key, value, node_refs
                    else:
                        yield self, key, nodes[key]
                except KeyError:
                    pass
            return
        yield from _mod_index._iter_entries_prefix(self, nodes_by_key, keys)

    def key_count(self):
        """Return an estimate of the number of keys in this index.

        For BTreeGraphIndex the estimate is exact as it is contained in the
        header.
        """
        if self._key_count is None:
            self._get_root_node()
        return self._key_count

    def _compute_row_offsets(self):
        """Fill out the _row_offsets attribute based on _row_lengths."""
        offsets = []
        row_offset = 0
        for row in self._row_lengths:
            offsets.append(row_offset)
            row_offset += row
        offsets.append(row_offset)
        self._row_offsets = offsets

    def _parse_header_from_bytes(self, bytes):
        """Parse the header from a region of bytes.

        :param bytes: The data to parse.
        :return: An offset, data tuple such as readv yields, for the unparsed
            data. (which may be of length 0).
        """
        signature = bytes[0 : len(self._signature())]
        if not signature == self._signature():
            raise _mod_index.BadIndexFormatSignature(self._name, BTreeGraphIndex)
        lines = bytes[len(self._signature()) :].splitlines()
        options_line = lines[0]
        if not options_line.startswith(_OPTION_NODE_REFS):
            raise _mod_index.BadIndexOptions(self)
        try:
            self.node_ref_lists = int(options_line[len(_OPTION_NODE_REFS) :])
        except ValueError as e:
            raise _mod_index.BadIndexOptions(self) from e
        options_line = lines[1]
        if not options_line.startswith(_OPTION_KEY_ELEMENTS):
            raise _mod_index.BadIndexOptions(self)
        try:
            self._key_length = int(options_line[len(_OPTION_KEY_ELEMENTS) :])
        except ValueError as e:
            raise _mod_index.BadIndexOptions(self) from e
        options_line = lines[2]
        if not options_line.startswith(_OPTION_LEN):
            raise _mod_index.BadIndexOptions(self)
        try:
            self._key_count = int(options_line[len(_OPTION_LEN) :])
        except ValueError as e:
            raise _mod_index.BadIndexOptions(self) from e
        options_line = lines[3]
        if not options_line.startswith(_OPTION_ROW_LENGTHS):
            raise _mod_index.BadIndexOptions(self)
        try:
            self._row_lengths = [
                int(length)
                for length in options_line[len(_OPTION_ROW_LENGTHS) :].split(b",")
                if length
            ]
        except ValueError as e:
            raise _mod_index.BadIndexOptions(self) from e
        self._compute_row_offsets()

        # calculate the bytes we have processed
        header_end = len(signature) + sum(map(len, lines[0:4])) + 4
        return header_end, bytes[header_end:]

    def _read_nodes(self, nodes):
        """Read some nodes from disk into the LRU cache.

        This performs a readv to get the node data into memory, and parses each
        node, then yields it to the caller. The nodes are requested in the
        supplied order. If possible doing sort() on the list before requesting
        a read may improve performance.

        :param nodes: The nodes to read. 0 - first node, 1 - second node etc.
        :return: None
        """
        # may be the byte string of the whole file
        bytes = None
        # list of (offset, length) regions of the file that should, evenually
        # be read in to data_ranges, either from 'bytes' or from the transport
        ranges = []
        base_offset = self._base_offset
        for index in nodes:
            offset = index * _PAGE_SIZE
            size = _PAGE_SIZE
            if index == 0:
                # Root node - special case
                if self._size:
                    size = min(_PAGE_SIZE, self._size)
                else:
                    # The only case where we don't know the size, is for very
                    # small indexes. So we read the whole thing
                    bytes = self._transport.get_bytes(self._name)
                    num_bytes = len(bytes)
                    self._size = num_bytes - base_offset
                    # the whole thing should be parsed out of 'bytes'
                    ranges = [
                        (start, min(_PAGE_SIZE, num_bytes - start))
                        for start in range(base_offset, num_bytes, _PAGE_SIZE)
                    ]
                    break
            else:
                if offset > self._size:
                    raise AssertionError(
                        "tried to read past the end of the file {} > {}".format(
                            offset, self._size
                        )
                    )
                size = min(size, self._size - offset)
            ranges.append((base_offset + offset, size))
        if not ranges:
            return
        elif bytes is not None:
            # already have the whole file
            data_ranges = [
                (start, bytes[start : start + size]) for start, size in ranges
            ]
        elif self._file is None:
            data_ranges = self._transport.readv(self._name, ranges)
        else:
            data_ranges = []
            for offset, size in ranges:
                self._file.seek(offset)
                data_ranges.append((offset, self._file.read(size)))
        for offset, data in data_ranges:
            offset -= base_offset
            if offset == 0:
                # extract the header
                offset, data = self._parse_header_from_bytes(data)
                if len(data) == 0:
                    continue
            bytes = zlib.decompress(data)
            if bytes.startswith(_LEAF_FLAG):
                node = self._leaf_factory(bytes, self._key_length, self.node_ref_lists)
            elif bytes.startswith(_INTERNAL_FLAG):
                node = _InternalNode(bytes)
            else:
                raise AssertionError("Unknown node type for {!r}".format(bytes))
            yield offset // _PAGE_SIZE, node

    def _signature(self):
        """The file signature for this index type."""
        return _BTSIGNATURE

    def validate(self):
        """Validate that everything in the index can be accessed."""
        # just read and parse every node.
        self._get_root_node()
        if len(self._row_lengths) > 1:
            start_node = self._row_offsets[1]
        else:
            # We shouldn't be reading anything anyway
            start_node = 1
        node_end = self._row_offsets[-1]
        for _node in self._read_nodes(list(range(start_node, node_end))):
            pass


_gcchk_factory = _LeafNode

try:
    from . import _btree_serializer_pyx as _btree_serializer  # type: ignore

    _gcchk_factory = _btree_serializer._parse_into_chk  # type: ignore
except ImportError as e:
    osutils.failed_to_load_extension(e)
    from . import _btree_serializer_py as _btree_serializer
