# groupcompress, a bzr plugin providing new compression logic.
# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
# 

"""Core compression logic for compressing streams of related files."""

from bzrlib import diff, pack, patiencediff
from bzrlib.knit import _DirectPackAccess
from bzrlib.osutils import (
    contains_whitespace,
    contains_linebreaks,
    sha_string,
    sha_strings,
    split_lines,
    )
from bzrlib.plugins.index2.repofmt import InMemoryBTree
from bzrlib.versionedfile import (
    FulltextContentFactory,
    VersionedFiles,
    )


def parse(lines):
    result = []
    lines = iter(lines)
    next = lines.next
    print next(), next()
    for header in lines:
        start, end, count = [int(n) for n in header.split(',')]
        contents = [next() for i in xrange(count)]
        result.append((start, end, count, contents))
    return result

def apply_delta(basis, delta):
    """Apply delta to this object to become new_version_id."""
    lines = []
    last_offset = 0
    # eq ranges occur where gaps occur
    # start, end refer to offsets in basis
    for start, end, count, delta_lines in delta:
        if last_offset != start: # copy an eq range
            lines.extend(basis[last_offset:start])
        lines[start:end] = delta_lines
        last_offset = end
    if last_offset != len(basis):
        lines.extend(basis[last_offset:])
    trim_encoding_newline(lines)
    return lines


def trim_encoding_newline(lines):
    if lines[-1] == '\n':
        del lines[-1]
    else:
        lines[-1] = lines[-1][:-1]


class GroupCompressor(object):
    """Produce a serialised group of compressed texts."""

    def __init__(self, delta=True):
        """Create a GroupCompressor.

        :paeam delta: If False, do not compress records.
        """
        self._delta = delta
        self.lines = []
        self.endpoint = 0
        self.input_bytes = 0

    def compress(self, key, lines, expected_sha):
        """Compress lines with label key.

        :param key: A key tuple. It is stored in the output
            for identification of the text during decompression.
        :param lines: The lines to be compressed. Must be split
            on \n, with the \n preserved.'
        :param expected_sha: If non-None, the sha the lines are blieved to
            have. During compression the sha is calculated; a mismatch will
            cause an error.
        :return: The sha1 of lines, and the number of bytes accumulated in
            the group output so far.
        """
        sha1 = sha_strings(lines)
        label = '\x00'.join(key)
        # setup good encoding for trailing \n support.
        if not lines or lines[-1].endswith('\n'):
            lines.append('\n')
        else:
            lines[-1] = lines[-1] + '\n'
        new_lines = []
        new_lines.append('label: %s\n' % label)
        new_lines.append('sha1: %s\n' % sha1)
        if 0:
            delta_seq = diff.difflib.SequenceMatcher(
                None, self.lines, lines)
        else:
            delta_seq = patiencediff.PatienceSequenceMatcher(
                None, self.lines, lines)
        diff_hunks = []
        for op in delta_seq.get_opcodes():
            if op[0] == 'equal':
                continue
            diff_hunks.append((op[1], op[2], op[4]-op[3], lines[op[3]:op[4]]))
        for start, end, count, new in diff_hunks:
            new_lines.append('%d,%d,%d\n' % (start, end, count))
            new_lines.extend(new)
        self.endpoint += sum(map(len, new_lines))
        self.lines.extend(new_lines)
        trim_encoding_newline(lines)
        self.input_bytes += sum(map(len, lines))
        return sha1, self.endpoint

    def ratio(self):
        """Return the overall compression ratio."""
        return float(self.input_bytes) / float(self.endpoint)

def make_pack_factory(graph, delta, keylength):
    """Create a factory for creating a pack based groupcompress.

    This is only functional enough to run interface tests, it doesn't try to
    provide a full pack environment.
    
    :param graph: Store a graph.
    :param delta: Delta compress contents.
    :param keylength: How long should keys be.
    """
    def factory(transport):
        parents = graph or delta
        ref_length = 0
        if graph:
            ref_length += 1
        graph_index = InMemoryBTree(reference_lists=ref_length,
            key_elements=keylength)
        stream = transport.open_write_stream('newpack')
        writer = pack.ContainerWriter(stream.write)
        writer.begin()
        index = _GCGraphIndex(graph_index, lambda:True, parents=parents,
            deltas=delta, add_callback=graph_index.add_nodes)
        access = _DirectPackAccess({})
        access.set_writer(writer, graph_index, (transport, 'newpack'))
        result = GroupCompressVersionedFiles(index, access, delta)
        result.stream = stream
        result.writer = writer
        return result
    return factory


def cleanup_pack_group(versioned_files):
    versioned_files.stream.close()
    versioned_files.writer.end()


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
        bytes = ''.join(lines)
        record = FulltextContentFactory(key, parents, None, bytes)
        sha1 = self._insert_record_stream([record])
        return sha1, len(bytes), None

    def _check_add(self, key, lines, random_id, check_content):
        """check that version_id and lines are safe to add."""
        version_id = key[-1]
        if contains_whitespace(version_id):
            raise InvalidRevisionId(version_id, self)
        self.check_not_reserved_id(version_id)
        # TODO: If random_id==False and the key is already present, we should
        # probably check that the existing content is identical to what is
        # being inserted, and otherwise raise an exception.  This would make
        # the bundle code simpler.
        if check_content:
            self._check_lines_not_unicode(lines)
            self._check_lines_are_lines(lines)

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert. 
        :return: None
        :seealso VersionedFiles.get_record_stream:
        """
        self._insert_record_stream(stream)

    def _insert_record_stream(self, stream):
        """Internal core to insert a record stream into this container.

        This helper function has a different interface than insert_record_stream
        to allow add_lines to be minimal, but still return the needed data.

        :param stream: A stream of records to insert. 
        :return: An iterator over the sha1 of the inserted records.
        :seealso insert_record_stream:
        :seealso add_lines:
        """
        compressor = GroupCompressor(self._delta)
        # This will go up to fulltexts for gc to gc fetching, which isn't
        # ideal.
        for record in stream:
            found_sha1, end_point = compressor.compress(record.key,
                split_lines(record.get_bytes_as('fulltext')), record.sha1)

class _GCGraphIndex(object):
    """Mapper from GroupCompressVersionedFiles needs into GraphIndex storage."""

    def __init__(self, graph_index, is_locked, deltas=False, parents=True,
        add_callback=None):
        """Construct a _GCGraphIndex on a graph_index.

        :param graph_index: An implementation of bzrlib.index.GraphIndex.
        :param is_locked: A callback to check whether the object should answer
            queries.
        :param deltas: Allow delta-compressed records.
        :param parents: If True, record knits parents, if not do not record 
            parents.
        :param add_callback: If not None, allow additions to the index and call
            this callback with a list of added GraphIndex nodes:
            [(node, value, node_refs), ...]
        :param is_locked: A callback, returns True if the index is locked and
            thus usable.
        """
        self._add_callback = add_callback
        self._graph_index = graph_index
        self._deltas = deltas
        self._parents = parents
        if deltas and not parents:
            # XXX: TODO: Delta tree and parent graph should be conceptually
            # separate.
            raise KnitCorrupt(self, "Cannot do delta compression without "
                "parent tracking.")
        self.has_graph = parents
        self._is_locked = is_locked

    def _check_write_ok(self):
        """Assert if writes are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

