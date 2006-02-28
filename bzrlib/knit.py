# Copyright (C) 2005, 2006 by Canonical Ltd
# Written by Martin Pool.
# Modified by Johan Rydberg <jrydberg@gnu.org>
# Modified by Robert Collins <robert.collins@canonical.com>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Knit versionedfile implementation.

A knit is a versioned file implementation that supports efficient append only
updates.
"""

import os
import difflib
from difflib import SequenceMatcher

from bzrlib.errors import FileExists, NoSuchFile, KnitError, \
        InvalidRevisionId, KnitCorrupt, KnitHeaderError, \
        RevisionNotPresent, RevisionAlreadyPresent
from bzrlib.trace import mutter
from bzrlib.osutils import contains_whitespace, contains_linebreaks, \
     sha_strings
from bzrlib.versionedfile import VersionedFile
from bzrlib.tsort import topo_sort

from StringIO import StringIO
from gzip import GzipFile
import sha

# TODO: Split out code specific to this format into an associated object.

# TODO: Can we put in some kind of value to check that the index and data
# files belong together?

# TODO: accomodate binaries, perhaps by storing a byte count

# TODO: function to check whole file

# TODO: atomically append data, then measure backwards from the cursor
# position after writing to work out where it was located.  we may need to
# bypass python file buffering.

DATA_SUFFIX = '.knit'
INDEX_SUFFIX = '.kndx'


class KnitContent(object):
    """Content of a knit version to which deltas can be applied."""

    def __init__(self, lines):
        self._lines = lines

    def annotate_iter(self):
        """Yield tuples of (origin, text) for each content line."""
        for origin, text in self._lines:
            yield origin, text

    def annotate(self):
        """Return a list of (origin, text) tuples."""
        return list(self.annotate_iter())

    def apply_delta(self, delta):
        """Apply delta to this content."""
        offset = 0
        for start, end, count, lines in delta:
            self._lines[offset+start:offset+end] = lines
            offset = offset + (start - end) + count

    def line_delta_iter(self, new_lines):
        """Generate line-based delta from new_lines to this content."""
        new_texts = [text for origin, text in new_lines._lines]
        old_texts = [text for origin, text in self._lines]
        s = difflib.SequenceMatcher(None, old_texts, new_texts)
        for op in s.get_opcodes():
            if op[0] == 'equal':
                continue
            yield (op[1], op[2], op[4]-op[3], new_lines._lines[op[3]:op[4]])

    def line_delta(self, new_lines):
        return list(self.line_delta_iter(new_lines))

    def text(self):
        return [text for origin, text in self._lines]


class _KnitFactory(object):
    """Base factory for creating content objects."""

    def make(self, lines, version):
        num_lines = len(lines)
        return KnitContent(zip([version] * num_lines, lines))


class KnitAnnotateFactory(_KnitFactory):
    """Factory for creating annotated Content objects."""

    annotated = True

    def parse_fulltext(self, content, version):
        lines = []
        for line in content:
            origin, text = line.split(' ', 1)
            lines.append((int(origin), text))
        return KnitContent(lines)

    def parse_line_delta_iter(self, lines):
        while lines:
            header = lines.pop(0)
            start, end, c = [int(n) for n in header.split(',')]
            contents = []
            for i in range(c):
                origin, text = lines.pop(0).split(' ', 1)
                contents.append((int(origin), text))
            yield start, end, c, contents

    def parse_line_delta(self, lines, version):
        return list(self.parse_line_delta_iter(lines))

    def lower_fulltext(self, content):
        return ['%d %s' % (o, t) for o, t in content._lines]

    def lower_line_delta(self, delta):
        out = []
        for start, end, c, lines in delta:
            out.append('%d,%d,%d\n' % (start, end, c))
            for origin, text in lines:
                out.append('%d %s' % (origin, text))
        return out


class KnitPlainFactory(_KnitFactory):
    """Factory for creating plain Content objects."""

    annotated = False

    def parse_fulltext(self, content, version):
        return self.make(content, version)

    def parse_line_delta_iter(self, lines, version):
        while lines:
            header = lines.pop(0)
            start, end, c = [int(n) for n in header.split(',')]
            yield start, end, c, zip([version] * c, lines[:c])
            del lines[:c]

    def parse_line_delta(self, lines, version):
        return list(self.parse_line_delta_iter(lines, version))
    
    def lower_fulltext(self, content):
        return content.text()

    def lower_line_delta(self, delta):
        out = []
        for start, end, c, lines in delta:
            out.append('%d,%d,%d\n' % (start, end, c))
            out.extend([text for origin, text in lines])
        return out


def make_empty_knit(transport, relpath):
    """Construct a empty knit at the specified location."""
    k = KnitVersionedFile(transport, relpath, 'w', KnitPlainFactory)
    k._data._open_file()


class KnitVersionedFile(VersionedFile):
    """Weave-like structure with faster random access.

    A knit stores a number of texts and a summary of the relationships
    between them.  Texts are identified by a string version-id.  Texts
    are normally stored and retrieved as a series of lines, but can
    also be passed as single strings.

    Lines are stored with the trailing newline (if any) included, to
    avoid special cases for files with no final newline.  Lines are
    composed of 8-bit characters, not unicode.  The combination of
    these approaches should mean any 'binary' file can be safely
    stored and retrieved.
    """

    def __init__(self, transport, relpath, mode, factory,
                 basis_knit=None, delta=True):
        """Construct a knit at location specified by relpath."""
        assert mode in ('r', 'w'), "invalid mode specified"
        assert not basis_knit or isinstance(basis_knit, KnitVersionedFile), \
            type(basis_knit)

        self.transport = transport
        self.filename = relpath
        self.basis_knit = basis_knit
        self.factory = factory
        self.writable = (mode == 'w')
        self.delta = delta

        self._index = _KnitIndex(transport, relpath + INDEX_SUFFIX,
            mode)
        self._data = _KnitData(transport, relpath + DATA_SUFFIX,
            mode)

    def versions(self):
        """See VersionedFile.versions."""
        return self._index.get_versions()

    def has_version(self, version_id):
        """See VersionedFile.has_version."""
        return self._index.has_version(version_id)

    __contains__ = has_version

    def _merge_annotations(self, content, parents):
        """Merge annotations for content.  This is done by comparing
        the annotations based on changed to the text."""
        for parent_id in parents:
            merge_content = self._get_content(parent_id)
            seq = SequenceMatcher(None, merge_content.text(), content.text())
            for i, j, n in seq.get_matching_blocks():
                if n == 0:
                    continue
                content._lines[j:j+n] = merge_content._lines[i:i+n]

    def _get_components(self, version_id):
        """Return a list of (version_id, method, data) tuples that
        makes up version specified by version_id of the knit.

        The components should be applied in the order of the returned
        list.

        The basis knit will be used to the largest extent possible
        since it is assumed that accesses to it is faster.
        """
        # needed_revisions holds a list of (method, version_id) of
        # versions that is needed to be fetched to construct the final
        # version of the file.
        #
        # basis_revisions is a list of versions that needs to be
        # fetched but exists in the basis knit.

        basis = self.basis_knit
        needed_versions = []
        basis_versions = []
        cursor = version_id

        while 1:
            picked_knit = self
            if basis and basis._index.has_version(cursor):
                picked_knit = basis
                basis_versions.append(cursor)
            method = picked_knit._index.get_method(cursor)
            needed_versions.append((method, cursor))
            if method == 'fulltext':
                break
            cursor = picked_knit.get_parents(cursor)[0]

        components = {}
        if basis_versions:
            records = []
            for comp_id in basis_versions:
                data_pos, data_size = basis._index.get_data_position(comp_id)
                records.append((piece_id, data_pos, data_size))
            components.update(basis._data.read_records(records))

        records = []
        for comp_id in [vid for method, vid in needed_versions
                        if vid not in basis_versions]:
            data_pos, data_size = self._index.get_position(comp_id)
            records.append((comp_id, data_pos, data_size))
        components.update(self._data.read_records(records))

        # get_data_records returns a mapping with the version id as
        # index and the value as data.  The order the components need
        # to be applied is held by needed_versions (reversed).
        out = []
        for method, comp_id in reversed(needed_versions):
            out.append((comp_id, method, components[comp_id]))

        return out

    def _get_content(self, version_id):
        """Returns a content object that makes up the specified
        version."""
        if not self.has_version(version_id):
            raise RevisionNotPresent(version_id, self.filename)

        if self.basis_knit and version_id in self.basis_knit:
            return self.basis_knit._get_content(version_id)

        content = None
        components = self._get_components(version_id)
        for component_id, method, (data, digest) in components:
            version_idx = self._index.lookup(component_id)
            if method == 'fulltext':
                assert content is None
                content = self.factory.parse_fulltext(data, version_idx)
            elif method == 'line-delta':
                delta = self.factory.parse_line_delta(data, version_idx)
                content.apply_delta(delta)

        if 'no-eol' in self._index.get_options(version_id):
            line = content._lines[-1][1].rstrip('\n')
            content._lines[-1] = (content._lines[-1][0], line)

        if sha_strings(content.text()) != digest:
            raise KnitCorrupt(self.filename, 'sha-1 does not match')

        return content

    def _check_versions_present(self, version_ids):
        """Check that all specified versions are present."""
        version_ids = set(version_ids)
        for r in list(version_ids):
            if self._index.has_version(r):
                version_ids.remove(r)
        if version_ids:
            raise RevisionNotPresent(list(version_ids)[0], self.filename)

    def add_lines(self, version_id, parents, lines):
        """See VersionedFile.add_lines."""
        assert self.writable, "knit is not opened for write"
        ### FIXME escape. RBC 20060228
        if contains_whitespace(version_id):
            raise InvalidRevisionId(version_id)
        if self.has_version(version_id):
            raise RevisionAlreadyPresent(version_id, self.filename)

        if True or __debug__:
            for l in lines:
                assert '\n' not in l[:-1]

        self._check_versions_present(parents)
        return self._add(version_id, lines[:], parents, self.delta)

    def _add(self, version_id, lines, parents, delta):
        """Add a set of lines on top of version specified by parents.

        If delta is true, compress the text as a line-delta against
        the first parent.
        """
        if delta and not parents:
            delta = False

        digest = sha_strings(lines)
        options = []
        if lines:
            if lines[-1][-1] != '\n':
                options.append('no-eol')
                lines[-1] = lines[-1] + '\n'

        lines = self.factory.make(lines, len(self._index))
        if self.factory.annotated and len(parents) > 0:
            # Merge annotations from parent texts if so is needed.
            self._merge_annotations(lines, parents)

        if parents and delta:
            # To speed the extract of texts the delta chain is limited
            # to a fixed number of deltas.  This should minimize both
            # I/O and the time spend applying deltas.
            count = 0
            delta_parents = parents
            while count < 25:
                parent = delta_parents[0]
                method = self._index.get_method(parent)
                if method == 'fulltext':
                    break
                delta_parents = self._index.get_parents(parent)
                count = count + 1
            if method == 'line-delta':
                delta = False

        if delta:
            options.append('line-delta')
            content = self._get_content(parents[0])
            delta_hunks = content.line_delta(lines)
            store_lines = self.factory.lower_line_delta(delta_hunks)
        else:
            options.append('fulltext')
            store_lines = self.factory.lower_fulltext(lines)

        where, size = self._data.add_record(version_id, digest, store_lines)
        self._index.add_version(version_id, options, where, size, parents)

    def clone_text(self, new_version_id, old_version_id, parents):
        """See VersionedFile.clone_text()."""
        # FIXME RBC 20060228 make fast by only inserting an index with null delta.
        self.add_lines(new_version_id, parents, self.get_lines(old_version_id))

    def get_lines(self, version_id):
        """See VersionedFile.get_lines()."""
        return self._get_content(version_id).text()

    def annotate_iter(self, version_id):
        """See VersionedFile.annotate_iter."""
        content = self._get_content(version_id)
        for origin, text in content.annotate_iter():
            yield self._index.idx_to_name(origin), text

    def get_parents(self, version_id):
        """See VersionedFile.get_parents."""
        self._check_versions_present([version_id])
        return list(self._index.get_parents(version_id))

    def get_ancestry(self, versions):
        """See VersionedFile.get_ancestry."""
        if isinstance(versions, basestring):
            versions = [versions]
        if not versions:
            return []
        self._check_versions_present(versions)
        return self._index.get_ancestry(versions)

    def _reannotate_line_delta(self, other, lines, new_version_id,
                               new_version_idx):
        """Re-annotate line-delta and return new delta."""
        new_delta = []
        for start, end, count, contents \
                in self.factory.parse_line_delta_iter(lines):
            new_lines = []
            for origin, line in contents:
                old_version_id = other._index.idx_to_name(origin)
                if old_version_id == new_version_id:
                    idx = new_version_idx
                else:
                    idx = self._index.lookup(old_version_id)
                new_lines.append((idx, line))
            new_delta.append((start, end, count, new_lines))

        return self.factory.lower_line_delta(new_delta)

    def _reannotate_fulltext(self, other, lines, new_version_id,
                             new_version_idx):
        """Re-annotate fulltext and return new version."""
        content = self.factory.parse_fulltext(lines, new_version_idx)
        new_lines = []
        for origin, line in content.annotate_iter():
            old_version_id = other._index.idx_to_name(origin)
            if old_version_id == new_version_id:
                idx = new_version_idx
            else:
                idx = self._index.lookup(old_version_id)
            new_lines.append((idx, line))

        return self.factory.lower_fulltext(KnitContent(new_lines))

    def join(self, other, pb=None, msg=None, version_ids=None):
        """See VersionedFile.join."""
        assert isinstance(other, KnitVersionedFile)

        if version_ids is None:
            version_ids = other.versions()
        if not version_ids:
            return 0

        if pb is None:
            from bzrlib.progress import DummyProgress
            pb = DummyProgress()

        version_ids = list(version_ids)
        if None in version_ids:
            version_ids.remove(None)

        other_ancestry = set(other.get_ancestry(version_ids))
        needed_versions = other_ancestry - set(self._index.get_versions())
        if not needed_versions:
            return 0
        full_list = topo_sort(other._index.get_graph())

        version_list = [i for i in full_list if (not self.has_version(i)
                        and i in needed_versions)]

        records = []
        for version_id in version_list:
            data_pos, data_size = other._index.get_position(version_id)
            records.append((version_id, data_pos, data_size))

        count = 0
        for version_id, lines, digest \
                in other._data.read_records_iter(records):
            options = other._index.get_options(version_id)
            parents = other._index.get_parents(version_id)
            
            for parent in parents:
                assert self.has_version(parent)

            if self.factory.annotated:
                # FIXME jrydberg: it should be possible to skip
                # re-annotating components if we know that we are
                # going to pull all revisions in the same order.
                new_version_id = version_id
                new_version_idx = self._index.num_versions()
                if 'fulltext' in options:
                    lines = self._reannotate_fulltext(other, lines,
                        new_version_id, new_version_idx)
                elif 'line-delta' in options:
                    lines = self._reannotate_line_delta(other, lines,
                        new_version_id, new_version_idx)

            count = count + 1
            pb.update(self.filename, count, len(version_list))

            pos, size = self._data.add_record(version_id, digest, lines)
            self._index.add_version(version_id, options, pos, size, parents)

        pb.clear()
        return count

    def walk(self, version_ids):
        """See VersionedFile.walk."""
        # We take the short path here, and extract all relevant texts
        # and put them in a weave and let that do all the work.  Far
        # from optimal, but is much simpler.
        from bzrlib.weave import Weave

        w = Weave(self.filename)
        ancestry = self.get_ancestry(version_ids)
        sorted_graph = topo_sort(self._index.get_graph())
        version_list = [vid for vid in sorted_graph if vid in ancestry]
        
        for version_id in version_list:
            lines = self.get_lines(version_id)
            w.add_lines(version_id, self.get_parents(version_id), lines)

        for lineno, insert_id, dset, line in w.walk(version_ids):
            yield lineno, insert_id, dset, line


class _KnitComponentFile(object):
    """One of the files used to implement a knit database"""

    def __init__(self, transport, filename, mode):
        self._transport = transport
        self._filename = filename
        self._mode = mode

    def write_header(self):
        old_len = self._transport.append(self._filename, self.HEADER)
        if old_len != 0:
            raise KnitCorrupt(self._filename, 'misaligned after writing header')

    def check_header(self, fp):
        line = fp.read(len(self.HEADER))
        if line != self.HEADER:
            raise KnitHeaderError(badline=line)

    def commit(self):
        """Commit is a nop."""

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self._filename)


class _KnitIndex(_KnitComponentFile):
    """Manages knit index file.

    The index is already kept in memory and read on startup, to enable
    fast lookups of revision information.  The cursor of the index
    file is always pointing to the end, making it easy to append
    entries.

    _cache is a cache for fast mapping from version id to a Index
    object.

    _history is a cache for fast mapping from indexes to version ids.

    The index data format is dictionary compressed when it comes to
    parent references; a index entry may only have parents that with a
    lover index number.  As a result, the index is topological sorted.
    """

    HEADER = "# bzr knit index 7\n"

    def _cache_version(self, version_id, options, pos, size, parents):
        val = (version_id, options, pos, size, parents)
        self._cache[version_id] = val
        self._history.append(version_id)

    def _iter_index(self, fp):
        lines = fp.read()
        for l in lines.splitlines(False):
            yield l.split()

    def __init__(self, transport, filename, mode):
        _KnitComponentFile.__init__(self, transport, filename, mode)
        self._cache = {}
        self._history = []
        try:
            fp = self._transport.get(self._filename)
            self.check_header(fp)
            for rec in self._iter_index(fp):
                self._cache_version(rec[0], rec[1].split(','), int(rec[2]), int(rec[3]),
                    [self._history[int(i)] for i in rec[4:]])
        except NoSuchFile, e:
            if mode != 'w':
                raise e
            self.write_header()

    def get_graph(self):
        graph = []
        for version_id, index in self._cache.iteritems():
            graph.append((version_id, index[4]))
        return graph

    def get_ancestry(self, versions):
        """See VersionedFile.get_ancestry."""
        version_idxs = []
        for version_id in versions:
            version_idxs.append(self._history.index(version_id))
        i = set(versions)
        for v in xrange(max(version_idxs), 0, -1):
            if self._history[v] in i:
                # include all its parents
                i.update(self._cache[self._history[v]][4])
        return list(i)

    def num_versions(self):
        return len(self._history)

    __len__ = num_versions

    def get_versions(self):
        return self._history

    def idx_to_name(self, idx):
        return self._history[idx]

    def lookup(self, version_id):
        assert version_id in self._cache
        return self._history.index(version_id)

    def add_version(self, version_id, options, pos, size, parents):
        """Add a version record to the index."""
        self._cache_version(version_id, options, pos, size, parents)

        content = "%s %s %s %s %s\n" % (version_id,
                                        ','.join(options),
                                        pos,
                                        size,
                                        ' '.join([str(self.lookup(vid)) for 
                                                  vid in parents]))
        self._transport.append(self._filename, content)

    def has_version(self, version_id):
        """True if the version is in the index."""
        return self._cache.has_key(version_id)

    def get_position(self, version_id):
        """Return data position and size of specified version."""
        return (self._cache[version_id][2], \
                self._cache[version_id][3])

    def get_method(self, version_id):
        """Return compression method of specified version."""
        options = self._cache[version_id][1]
        if 'fulltext' in options:
            return 'fulltext'
        else:
            assert 'line-delta' in options
            return 'line-delta'

    def get_options(self, version_id):
        return self._cache[version_id][1]

    def get_parents(self, version_id):
        """Return parents of specified version."""
        return self._cache[version_id][4]

    def check_versions_present(self, version_ids):
        """Check that all specified versions are present."""
        version_ids = set(version_ids)
        for version_id in list(version_ids):
            if version_id in self._cache:
                version_ids.remove(version_id)
        if version_ids:
            raise RevisionNotPresent(list(version_ids)[0], self.filename)


class _KnitData(_KnitComponentFile):
    """Contents of the knit data file"""

    HEADER = "# bzr knit data 7\n"

    def __init__(self, transport, filename, mode):
        _KnitComponentFile.__init__(self, transport, filename, mode)
        self._file = None
        self._checked = False

    def _open_file(self):
        if self._file is None:
            try:
                self._file = self._transport.get(self._filename)
            except NoSuchFile:
                pass
        return self._file

    def add_record(self, version_id, digest, lines):
        """Write new text record to disk.  Returns the position in the
        file where it was written."""
        sio = StringIO()
        data_file = GzipFile(None, mode='wb', fileobj=sio)
        print >>data_file, "version %s %d %s" % (version_id, len(lines), digest)
        data_file.writelines(lines)
        print >>data_file, "end %s\n" % version_id
        data_file.close()

        content = sio.getvalue()
        start_pos = self._transport.append(self._filename, content)
        return start_pos, len(content)

    def _parse_record(self, version_id, data):
        df = GzipFile(mode='rb', fileobj=StringIO(data))
        rec = df.readline().split()
        if len(rec) != 4:
            raise KnitCorrupt(self._filename, 'unexpected number of records')
        if rec[1] != version_id:
            raise KnitCorrupt(self.file.name, 
                              'unexpected version, wanted %r' % version_id)
        lines = int(rec[2])
        record_contents = self._read_record_contents(df, lines)
        l = df.readline()
        if l != 'end %s\n' % version_id:
            raise KnitCorrupt(self._filename, 'unexpected version end line %r, wanted %r' 
                        % (l, version_id))
        return record_contents, rec[3]

    def _read_record_contents(self, df, record_lines):
        """Read and return n lines from datafile."""
        r = []
        for i in range(record_lines):
            r.append(df.readline())
        return r

    def read_records_iter(self, records):
        """Read text records from data file and yield result.

        Each passed record is a tuple of (version_id, pos, len) and
        will be read in the given order.  Yields (version_id,
        contents, digest).
        """

        class ContinuousRange:
            def __init__(self, rec_id, pos, size):
                self.start_pos = pos
                self.end_pos = pos + size
                self.versions = [(rec_id, pos, size)]

            def add(self, rec_id, pos, size):
                if self.end_pos != pos:
                    return False
                self.end_pos = pos + size
                self.versions.append((rec_id, pos, size))
                return True

            def split(self, fp):
                for rec_id, pos, size in self.versions:
                    yield rec_id, fp.read(size)

        fp = self._open_file()

        # Loop through all records and try to collect as large
        # continuous region as possible to read.
        while records:
            record_id, pos, size = records.pop(0)
            continuous_range = ContinuousRange(record_id, pos, size)
            while records:
                record_id, pos, size = records[0]
                if continuous_range.add(record_id, pos, size):
                    del records[0]
                else:
                    break
            fp.seek(continuous_range.start_pos, 0)
            for record_id, data in continuous_range.split(fp):
                content, digest = self._parse_record(record_id, data)
                yield record_id, content, digest

        self._file = None

    def read_records(self, records):
        """Read records into a dictionary."""
        components = {}
        for record_id, content, digest in self.read_records_iter(records):
            components[record_id] = (content, digest)
        return components

