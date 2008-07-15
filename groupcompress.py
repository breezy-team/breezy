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

from itertools import izip
from cStringIO import StringIO
import zlib

from bzrlib import (
    annotate,
    debug,
    diff,
    errors,
    graph as _mod_graph,
    pack,
    patiencediff,
    )
from bzrlib.graph import Graph
from bzrlib.knit import _DirectPackAccess
from bzrlib.osutils import (
    contains_whitespace,
    contains_linebreaks,
    sha_string,
    sha_strings,
    split_lines,
    )
from bzrlib.plugins.index2.btree_index import BTreeBuilder
from bzrlib.tsort import topo_sort
from bzrlib.versionedfile import (
    adapter_registry,
    AbsentContentFactory,
    FulltextContentFactory,
    VersionedFiles,
    )


def parse(line_list):
    result = []
    lines = iter(line_list)
    next = lines.next
    label_line = lines.next()
    sha1_line = lines.next()
    if (not label_line.startswith('label: ') or
        not sha1_line.startswith('sha1: ')):
        raise AssertionError("bad text record %r" % lines)
    label = tuple(label_line[7:-1].split('\x00'))
    sha1 = sha1_line[6:-1]
    for header in lines:
        op = header[0]
        numbers = header[2:]
        numbers = [int(n) for n in header[2:].split(',')]
        if op == 'c':
            result.append((op, numbers[0], numbers[1], None))
        else:
            contents = [next() for i in xrange(numbers[0])]
            result.append((op, None, numbers[0], contents))
    return label, sha1, result

def apply_delta(basis, delta):
    """Apply delta to this object to become new_version_id."""
    lines = []
    last_offset = 0
    # eq ranges occur where gaps occur
    # start, end refer to offsets in basis
    for op, start, count, delta_lines in delta:
        if op == 'c':
            lines.append(basis[start:start+count])
        else:
            lines.extend(delta_lines)
    trim_encoding_newline(lines)
    return lines


def trim_encoding_newline(lines):
    if lines[-1] == '\n':
        del lines[-1]
    else:
        lines[-1] = lines[-1][:-1]


class GroupCompressor(object):
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

    def __init__(self, delta=True):
        """Create a GroupCompressor.

        :paeam delta: If False, do not compress records.
        """
        self._delta = delta
        self.lines = []
        self.line_offsets = []
        self.endpoint = 0
        self.input_bytes = 0
        # line: set(locations it appears at), set(N+1 for N in locations)
        self.line_locations = {}
        self.labels_deltas = {}

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
        index_lines = [False, False]
        pos = 0
        line_locations = self.line_locations
        accumulator = []
        copying = False
        new_len = 0
        new_start = 0
        # We either copy a range (while there are reusable lines) or we 
        # insert new lines. To find reusable lines we traverse 
        while pos < len(lines):
            line = lines[pos]
            if line not in line_locations:
                if copying:
                    # flush the copy
                    copy_start = min(copy_ends) - copy_len
                    stop_byte = self.line_offsets[copy_start + copy_len - 1]
                    if copy_start == 0:
                        start_byte = 0
                    else:
                        start_byte = self.line_offsets[copy_start - 1]
                    bytes = stop_byte - start_byte
                    copy_control_instruction = "c,%d,%d\n" % (start_byte, bytes)
                    insert_instruction = "i,%d\n" % copy_len
                    if (bytes + len(insert_instruction) >
                        len(copy_control_instruction)):
                        new_lines.append(copy_control_instruction)
                        index_lines.append(False)
                    else:
                        # inserting is shorter than copying, so insert.
                        new_lines.append(insert_instruction)
                        new_lines.extend(lines[new_start:new_start+copy_len])
                        index_lines.extend([False]*(copy_len + 1))
                    copying = False
                    new_start = pos
                    new_len = 1
                else:
                    new_len += 1
            else:
                if copying:
                    locations, next = line_locations[line]
                    next_locations = locations.intersection(copy_ends)
                    if len(next_locations):
                        # range continues
                        copy_len += 1
                        copy_ends = set(loc + 1 for loc in next_locations)
                    else:
                        # range stops, flush and start a new copy range
                        copy_start = min(copy_ends) - copy_len
                        stop_byte = self.line_offsets[copy_start + copy_len - 1]
                        if copy_start == 0:
                            start_byte = 0
                        else:
                            start_byte = self.line_offsets[copy_start - 1]
                        bytes = stop_byte - start_byte
                        copy_control_instruction = "c,%d,%d\n" % (start_byte, bytes)
                        insert_instruction = "i,%d\n" % copy_len
                        if (bytes + len(insert_instruction) >
                            len(copy_control_instruction)):
                            new_lines.append(copy_control_instruction)
                            index_lines.append(False)
                        else:
                            # inserting is shorter than copying, so insert.
                            new_lines.append(insert_instruction)
                            new_lines.extend(lines[new_start:new_start+copy_len])
                            index_lines.extend([False]*(copy_len + 1))
                        copy_len = 1
                        copy_ends = next
                        new_start = pos
                else:
                    # Flush
                    if new_len:
                        new_lines.append("i,%d\n" % new_len)
                        new_lines.extend(lines[new_start:new_start+new_len])
                        index_lines.append(False)
                        index_lines.extend([True]*new_len)
                    # setup a copy
                    copy_len = 1
                    copy_ends = line_locations[line][1]
                    copying = True
                    new_start = pos
            pos += 1
        if copying:
            copy_start = min(copy_ends) - copy_len
            stop_byte = self.line_offsets[copy_start + copy_len - 1]
            if copy_start == 0:
                start_byte = 0
            else:
                start_byte = self.line_offsets[copy_start - 1]
            bytes = stop_byte - start_byte
            copy_control_instruction = "c,%d,%d\n" % (start_byte, bytes)
            insert_instruction = "i,%d\n" % copy_len
            if (bytes + len(insert_instruction) >
                len(copy_control_instruction)):
                new_lines.append(copy_control_instruction)
                index_lines.append(False)
            else:
                # inserting is shorter than copying, so insert.
                new_lines.append(insert_instruction)
                new_lines.extend(lines[new_start:new_start+copy_len])
                index_lines.extend([False]*(copy_len + 1))
        elif new_len:
            new_lines.append("i,%d\n" % new_len)
            new_lines.extend(lines[new_start:new_start+new_len])
            index_lines.append(False)
            index_lines.extend([True]*new_len)
        delta_start = (self.endpoint, len(self.lines))
        self.output_lines(new_lines, index_lines)
        trim_encoding_newline(lines)
        self.input_bytes += sum(map(len, lines))
        delta_end = (self.endpoint, len(self.lines))
        self.labels_deltas[key] = (delta_start, delta_end)
        return sha1, self.endpoint

    def extract(self, key):
        """Extract a key previously added to the compressor.
        
        :param key: The key to extract.
        :return: An iterable over bytes and the sha1.
        """
        delta_details = self.labels_deltas[key]
        delta_lines = self.lines[delta_details[0][1]:delta_details[1][1]]
        label, sha1, delta = parse(delta_lines)
        if label != key:
            raise AssertionError("wrong key: %r, wanted %r" % (label, key))
        # Perhaps we want to keep the line offsets too in memory at least?
        lines = apply_delta(''.join(self.lines), delta)
        sha1 = sha_strings(lines)
        return lines, sha1

    def output_lines(self, new_lines, index_lines):
        """Output some lines.

        :param new_lines: The lines to output.
        :param index_lines: A boolean flag for each line - when True, index
            that line.
        """
        endpoint = self.endpoint
        offset = len(self.lines)
        for (pos, line), index in izip(enumerate(new_lines), index_lines):
            self.lines.append(line)
            endpoint += len(line)
            self.line_offsets.append(endpoint)
            if index:
                indices, next_lines = self.line_locations.setdefault(line,
                    (set(), set()))
                indices.add(pos + offset)
                next_lines.add(pos + offset + 1)
        self.endpoint = endpoint

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
        self._unadded_refs = {}

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
        sha1 = list(self._insert_record_stream([record], random_id=random_id))[0]
        return sha1, len(bytes), None

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
            fulltext = split_lines(record.get_bytes_as('fulltext'))
            parent_lines = [parent_cache[parent] for parent in parent_map[key]]
            parent_cache[key] = list(
                reannotate(parent_lines, fulltext, key, None, head_cache))
        return parent_cache[key]

    def check(self, progress_bar=None):
        """See VersionedFiles.check()."""
        keys = self.keys()
        for record in self.get_record_stream(keys, 'unordered', True):
            record.get_bytes_as('fulltext')

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

    def get_parent_map(self, keys):
        """Get a map of the parents of keys.

        :param keys: The keys to look up parents for.
        :return: A mapping from keys to parents. Absent keys are absent from
            the mapping.
        """
        result = {}
        sources = [self._index]
        source_results = []
        missing = set(keys)
        for source in sources:
            if not missing:
                break
            new_result = source.get_parent_map(missing)
            source_results.append(new_result)
            result.update(new_result)
            missing.difference_update(set(new_result))
        if self._unadded_refs:
            for key in missing:
                if key in self._unadded_refs:
                    result[key] = self._unadded_refs[key]
        return result

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
        keys = set(keys)
        if not keys:
            return
        if not self._index.has_graph:
            # Cannot topological order when no graph has been stored.
            ordering = 'unordered'
        # Cheap: iterate
        locations = self._index.get_build_details(keys)
        if ordering == 'topological':
            # would be better to not globally sort initially but instead
            # start with one key, recurse to its oldest parent, then grab
            # everything in the same group, etc.
            parent_map = dict((key, details[2]) for key, details in
                locations.iteritems())
            local = frozenset(keys).intersection(set(self._unadded_refs))
            for key in local:
                parent_map[key] = self._unadded_refs[key]
                locations[key] = None
            present_keys = topo_sort(parent_map)
            # Now group by source:
        else:
            present_keys = locations.keys()
            local = frozenset(keys).intersection(set(self._unadded_refs))
            for key in local:
                present_keys.append(key)
                locations[key] = None
        absent_keys = keys.difference(set(locations))
        for key in absent_keys:
            yield AbsentContentFactory(key)
        for key in present_keys:
            if key in self._unadded_refs:
                lines, sha1 = self._compressor.extract(key)
                parents = self._unadded_refs[key]
            else:
                index_memo, _, parents, (method, _) = locations[key]
                # read
                read_memo = index_memo[0:3]
                zdata = self._access.get_raw_records([read_memo]).next()
                # decompress
                plain = zlib.decompress(zdata)
                # parse
                delta_lines = split_lines(plain[index_memo[3]:index_memo[4]])
                label, sha1, delta = parse(delta_lines)
                if label != key:
                    raise AssertionError("wrong key: %r, wanted %r" % (label, key))
                basis = plain[:index_memo[3]]
                # basis = StringIO(basis).readlines()
                #basis = split_lines(plain[:last_end])
                lines = apply_delta(basis, delta)
            bytes = ''.join(lines)
            yield FulltextContentFactory(key, parents, sha1, bytes)
            
    def get_sha1s(self, keys):
        """See VersionedFiles.get_sha1s()."""
        result = {}
        for record in self.get_record_stream(keys, 'unordered', True):
            if record.sha1 != None:
                result[record.key] = record.sha1
            else:
                if record.storage_kind != 'absent':
                    result[record.key] == sha_string(record.get_bytes_as(
                        'fulltext'))
        return result

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert. 
        :return: None
        :seealso VersionedFiles.get_record_stream:
        """
        for _ in self._insert_record_stream(stream):
            pass

    def _insert_record_stream(self, stream, random_id=False):
        """Internal core to insert a record stream into this container.

        This helper function has a different interface than insert_record_stream
        to allow add_lines to be minimal, but still return the needed data.

        :param stream: A stream of records to insert. 
        :return: An iterator over the sha1 of the inserted records.
        :seealso insert_record_stream:
        :seealso add_lines:
        """
        def get_adapter(adapter_key):
            try:
                return adapters[adapter_key]
            except KeyError:
                adapter_factory = adapter_registry.get(adapter_key)
                adapter = adapter_factory(self)
                adapters[adapter_key] = adapter
                return adapter
        adapters = {}
        # This will go up to fulltexts for gc to gc fetching, which isn't
        # ideal.
        self._compressor = GroupCompressor(self._delta)
        self._unadded_refs = {}
        keys_to_add = []
        basis_end = 0
        groups = 1
        def flush():
            compressed = zlib.compress(''.join(self._compressor.lines))
            index, start, length = self._access.add_raw_records(
                [(None, len(compressed))], compressed)[0]
            nodes = []
            for key, reads, refs in keys_to_add:
                nodes.append((key, "%d %d %s" % (start, length, reads), refs))
            self._index.add_records(nodes, random_id=random_id)
        for record in stream:
            # Raise an error when a record is missing.
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent([record.key], self)
            elif record.storage_kind == 'fulltext':
                bytes = record.get_bytes_as('fulltext')
            else:
                adapter_key = record.storage_kind, 'fulltext'
                adapter = get_adapter(adapter_key)
                bytes = adapter.get_bytes(record,
                    record.get_bytes_as(record.storage_kind))
            found_sha1, end_point = self._compressor.compress(record.key,
                split_lines(bytes), record.sha1)
            self._unadded_refs[record.key] = record.parents
            yield found_sha1
            keys_to_add.append((record.key, '%d %d' % (basis_end, end_point),
                (record.parents,)))
            basis_end = end_point
            if basis_end > 1024 * 1024 * 20:
                flush()
                self._compressor = GroupCompressor(self._delta)
                self._unadded_refs = {}
                keys_to_add = []
                basis_end = 0
                groups += 1
        if len(keys_to_add):
            flush()
        self._compressor = None
        self._unadded_refs = {}

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
            pb.update('Walking content.', key_idx, total)
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(record.key, self)
            lines = split_lines(record.get_bytes_as('fulltext'))
            for line in lines:
                yield line, key
        pb.update('Walking content.', total, total)

    def keys(self):
        """See VersionedFiles.keys."""
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(2, "keys scales with size of history")
        sources = [self._index]
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
        :param is_locked: A callback to check whether the object should answer
            queries.
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
        """raise if reads are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

    def _check_write_ok(self):
        """Assert if writes are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

    def _get_entries(self, keys, check_present=False):
        """Get the entries for keys.
        
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
        entries = self._get_entries(keys, False)
        for entry in entries:
            key = entry[1]
            if not self._parents:
                parents = None
            else:
                parents = entry[3][0]
            value = entry[2]
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
