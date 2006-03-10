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

Knit file layout:
lifeless: the data file is made up of "delta records".  each delta record has a delta header 
that contains; (1) a version id, (2) the size of the delta (in lines), and (3)  the digest of 
the -expanded data- (ie, the delta applied to the parent).  the delta also ends with a 
end-marker; simply "end VERSION"

delta can be line or full contents.a
... the 8's there are the index number of the annotation.
version robertc@robertcollins.net-20051003014215-ee2990904cc4c7ad 7 c7d23b2a5bd6ca00e8e266cec0ec228158ee9f9e
59,59,3
8
8         if ie.executable:
8             e.set('executable', 'yes')
130,130,2
8         if elt.get('executable') == 'yes':
8             ie.executable = True
end robertc@robertcollins.net-20051003014215-ee2990904cc4c7ad 


whats in an index:
09:33 < jrydberg> lifeless: each index is made up of a tuple of; version id, options, position, size, parents
09:33 < jrydberg> lifeless: the parents are currently dictionary compressed
09:33 < jrydberg> lifeless: (meaning it currently does not support ghosts)
09:33 < lifeless> right
09:33 < jrydberg> lifeless: the position and size is the range in the data file


so the index sequence is the dictionary compressed sequence number used
in the deltas to provide line annotation

"""

# TODOS:
# 10:16 < lifeless> make partial index writes safe
# 10:16 < lifeless> implement 'knit.check()' like weave.check()
# 10:17 < lifeless> record known ghosts so we can detect when they are filled in rather than the current 'reweave 
#                    always' approach.
# move sha1 out of the content so that join is faster at verifying parents
# record content length ?
                  

from copy import copy
from cStringIO import StringIO
import difflib
from difflib import SequenceMatcher
from gzip import GzipFile
from itertools import izip
import os


import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import FileExists, NoSuchFile, KnitError, \
        InvalidRevisionId, KnitCorrupt, KnitHeaderError, \
        RevisionNotPresent, RevisionAlreadyPresent
from bzrlib.trace import mutter
from bzrlib.osutils import contains_whitespace, contains_linebreaks, \
     sha_strings
from bzrlib.versionedfile import VersionedFile, InterVersionedFile
from bzrlib.tsort import topo_sort


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
        """Convert fulltext to internal representation

        fulltext content is of the format
        revid(utf8) plaintext\n
        internal representation is of the format:
        (revid, plaintext)
        """
        lines = []
        for line in content:
            origin, text = line.split(' ', 1)
            lines.append((origin.decode('utf-8'), text))
        return KnitContent(lines)

    def parse_line_delta_iter(self, lines):
        """Convert a line based delta into internal representation.

        line delta is in the form of:
        intstart intend intcount
        1..count lines:
        revid(utf8) newline\n
        internal represnetation is
        (start, end, count, [1..count tuples (revid, newline)])
        """
        while lines:
            header = lines.pop(0)
            start, end, c = [int(n) for n in header.split(',')]
            contents = []
            for i in range(c):
                origin, text = lines.pop(0).split(' ', 1)
                contents.append((origin.decode('utf-8'), text))
            yield start, end, c, contents

    def parse_line_delta(self, lines, version):
        return list(self.parse_line_delta_iter(lines))

    def lower_fulltext(self, content):
        """convert a fulltext content record into a serializable form.

        see parse_fulltext which this inverts.
        """
        return ['%s %s' % (o.encode('utf-8'), t) for o, t in content._lines]

    def lower_line_delta(self, delta):
        """convert a delta into a serializable form.

        See parse_line_delta_iter which this inverts.
        """
        out = []
        for start, end, c, lines in delta:
            out.append('%d,%d,%d\n' % (start, end, c))
            for origin, text in lines:
                out.append('%s %s' % (origin.encode('utf-8'), text))
        return out


class KnitPlainFactory(_KnitFactory):
    """Factory for creating plain Content objects."""

    annotated = False

    def parse_fulltext(self, content, version):
        """This parses an unannotated fulltext.

        Note that this is not a noop - the internal representation
        has (versionid, line) - its just a constant versionid.
        """
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

    def __init__(self, relpath, transport, file_mode=None, access_mode=None, factory=None,
                 basis_knit=None, delta=True, create=False):
        """Construct a knit at location specified by relpath.
        
        :param create: If not True, only open an existing knit.
        """
        if access_mode is None:
            access_mode = 'w'
        super(KnitVersionedFile, self).__init__(access_mode)
        assert access_mode in ('r', 'w'), "invalid mode specified %r" % access_mode
        assert not basis_knit or isinstance(basis_knit, KnitVersionedFile), \
            type(basis_knit)

        self.transport = transport
        self.filename = relpath
        self.basis_knit = basis_knit
        self.factory = factory or KnitAnnotateFactory()
        self.writable = (access_mode == 'w')
        self.delta = delta

        self._index = _KnitIndex(transport, relpath + INDEX_SUFFIX,
            access_mode, create=create)
        self._data = _KnitData(transport, relpath + DATA_SUFFIX,
            access_mode, create=not len(self.versions()))

    def clear_cache(self):
        """Clear the data cache only."""
        self._data.clear_cache()

    def copy_to(self, name, transport):
        """See VersionedFile.copy_to()."""
        # copy the current index to a temp index to avoid racing with local
        # writes
        transport.put(name + INDEX_SUFFIX + '.tmp', self.transport.get(self._index._filename))
        # copy the data file
        transport.put(name + DATA_SUFFIX, self._data._open_file())
        # rename the copied index into place
        transport.rename(name + INDEX_SUFFIX + '.tmp', name + INDEX_SUFFIX)

    def create_empty(self, name, transport, mode=None):
        return KnitVersionedFile(name, transport, factory=self.factory, delta=self.delta, create=True)
    
    def _fix_parents(self, version, new_parents):
        """Fix the parents list for version.
        
        This is done by appending a new version to the index
        with identical data except for the parents list.
        the parents list must be a superset of the current
        list.
        """
        current_values = self._index._cache[version]
        assert set(current_values[4]).difference(set(new_parents)) == set()
        self._index.add_version(version,
                                current_values[1], 
                                current_values[2],
                                current_values[3],
                                new_parents)

    def get_graph_with_ghosts(self):
        """See VersionedFile.get_graph_with_ghosts()."""
        graph_items = self._index.get_graph()
        return dict(graph_items)

    @staticmethod
    def get_suffixes():
        """See VersionedFile.get_suffixes()."""
        return [DATA_SUFFIX, INDEX_SUFFIX]

    def has_ghost(self, version_id):
        """True if there is a ghost reference in the file to version_id."""
        # maybe we have it
        if self.has_version(version_id):
            return False
        # optimisable if needed by memoising the _ghosts set.
        items = self._index.get_graph()
        for node, parents in items:
            for parent in parents:
                if parent not in self._index._cache:
                    if parent == version_id:
                        return True
        return False

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

    def _add_lines_with_ghosts(self, version_id, parents, lines):
        """See VersionedFile.add_lines_with_ghosts()."""
        self._check_add(version_id, lines)
        return self._add(version_id, lines[:], parents, self.delta)

    def _add_lines(self, version_id, parents, lines):
        """See VersionedFile.add_lines."""
        self._check_add(version_id, lines)
        self._check_versions_present(parents)
        return self._add(version_id, lines[:], parents, self.delta)

    def _check_add(self, version_id, lines):
        """check that version_id and lines are safe to add."""
        assert self.writable, "knit is not opened for write"
        ### FIXME escape. RBC 20060228
        if contains_whitespace(version_id):
            raise InvalidRevisionId(version_id)
        if self.has_version(version_id):
            raise RevisionAlreadyPresent(version_id, self.filename)

        if False or __debug__:
            for l in lines:
                assert '\n' not in l[:-1]

    def _add(self, version_id, lines, parents, delta):
        """Add a set of lines on top of version specified by parents.

        If delta is true, compress the text as a line-delta against
        the first parent.

        Any versions not present will be converted into ghosts.
        """
        present_parents = []
        ghosts = []
        for parent in parents:
            if not self.has_version(parent):
                ghosts.append(parent)
            else:
                present_parents.append(parent)

        if delta and not len(present_parents):
            delta = False

        digest = sha_strings(lines)
        options = []
        if lines:
            if lines[-1][-1] != '\n':
                options.append('no-eol')
                lines[-1] = lines[-1] + '\n'

        lines = self.factory.make(lines, version_id)
        if self.factory.annotated and len(present_parents) > 0:
            # Merge annotations from parent texts if so is needed.
            self._merge_annotations(lines, present_parents)

        if len(present_parents) and delta:
            # To speed the extract of texts the delta chain is limited
            # to a fixed number of deltas.  This should minimize both
            # I/O and the time spend applying deltas.
            count = 0
            delta_parents = present_parents
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
            content = self._get_content(present_parents[0])
            delta_hunks = content.line_delta(lines)
            store_lines = self.factory.lower_line_delta(delta_hunks)
        else:
            options.append('fulltext')
            store_lines = self.factory.lower_fulltext(lines)

        where, size = self._data.add_record(version_id, digest, store_lines)
        self._index.add_version(version_id, options, where, size, parents)

    def check(self, progress_bar=None):
        """See VersionedFile.check()."""

    def _clone_text(self, new_version_id, old_version_id, parents):
        """See VersionedFile.clone_text()."""
        # FIXME RBC 20060228 make fast by only inserting an index with null delta.
        self.add_lines(new_version_id, parents, self.get_lines(old_version_id))

    def get_lines(self, version_id):
        """See VersionedFile.get_lines()."""
        return self._get_content(version_id).text()

    def iter_lines_added_or_present_in_versions(self, version_ids=None):
        """See VersionedFile.iter_lines_added_or_present_in_versions()."""
        if version_ids is None:
            version_ids = self.versions()
        # we dont care about inclusions, the caller cares.
        # but we need to setup a list of records to visit.
        # we need version_id, position, length
        version_id_records = []
        requested_versions = list(version_ids)
        # filter for available versions
        for version_id in requested_versions:
            if not self.has_version(version_id):
                raise RevisionNotPresent(version_id, self.filename)
        # get a in-component-order queue:
        version_ids = []
        for version_id in self.versions():
            if version_id in requested_versions:
                version_ids.append(version_id)
                data_pos, length = self._index.get_position(version_id)
                version_id_records.append((version_id, data_pos, length))

        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        count = 0
        total = len(version_id_records)
        try:
            pb.update('Walking content.', count, total)
            for version_id, data, sha_value in \
                self._data.read_records_iter(version_id_records):
                pb.update('Walking content.', count, total)
                method = self._index.get_method(version_id)
                version_idx = self._index.lookup(version_id)
                assert method in ('fulltext', 'line-delta')
                if method == 'fulltext':
                    content = self.factory.parse_fulltext(data, version_idx)
                    for line in content.text():
                        yield line
                else:
                    delta = self.factory.parse_line_delta(data, version_idx)
                    for start, end, count, lines in delta:
                        for origin, line in lines:
                            yield line
                count +=1
            pb.update('Walking content.', total, total)
            pb.finished()
        except:
            pb.update('Walking content.', total, total)
            pb.finished()
            raise
        
    def num_versions(self):
        """See VersionedFile.num_versions()."""
        return self._index.num_versions()

    __len__ = num_versions

    def annotate_iter(self, version_id):
        """See VersionedFile.annotate_iter."""
        content = self._get_content(version_id)
        for origin, text in content.annotate_iter():
            yield origin, text

    def get_parents(self, version_id):
        """See VersionedFile.get_parents."""
        self._check_versions_present([version_id])
        return list(self._index.get_parents(version_id))

    def get_parents_with_ghosts(self, version_id):
        """See VersionedFile.get_parents."""
        self._check_versions_present([version_id])
        return list(self._index.get_parents_with_ghosts(version_id))

    def get_ancestry(self, versions):
        """See VersionedFile.get_ancestry."""
        if isinstance(versions, basestring):
            versions = [versions]
        if not versions:
            return []
        self._check_versions_present(versions)
        return self._index.get_ancestry(versions)

    def get_ancestry_with_ghosts(self, versions):
        """See VersionedFile.get_ancestry_with_ghosts."""
        if isinstance(versions, basestring):
            versions = [versions]
        if not versions:
            return []
        self._check_versions_present(versions)
        return self._index.get_ancestry_with_ghosts(versions)

    #@deprecated_method(zero_eight)
    def walk(self, version_ids):
        """See VersionedFile.walk."""
        # We take the short path here, and extract all relevant texts
        # and put them in a weave and let that do all the work.  Far
        # from optimal, but is much simpler.
        # FIXME RB 20060228 this really is inefficient!
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
        old_len = self._transport.append(self._filename, StringIO(self.HEADER))
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

    Duplicate entries may be written to the index for a single version id
    if this is done then the latter one completely replaces the former:
    this allows updates to correct version and parent information. 
    Note that the two entries may share the delta, and that successive
    annotations and references MUST point to the first entry.
    """

    HEADER = "# bzr knit index 7\n"

    # speed of knit parsing went from 280 ms to 280 ms with slots addition.
    # __slots__ = ['_cache', '_history', '_transport', '_filename']

    def _cache_version(self, version_id, options, pos, size, parents):
        """Cache a version record in the history array and index cache.
        
        This is inlined into __init__ for performance. KEEP IN SYNC.
        (It saves 60ms, 25% of the __init__ overhead on local 4000 record
         indexes).
        """
        # only want the _history index to reference the 1st index entry
        # for version_id
        if version_id not in self._cache:
            self._history.append(version_id)
        self._cache[version_id] = (version_id, options, pos, size, parents)

    def __init__(self, transport, filename, mode, create=False):
        _KnitComponentFile.__init__(self, transport, filename, mode)
        self._cache = {}
        # position in _history is the 'official' index for a revision
        # but the values may have come from a newer entry.
        # so - wc -l of a knit index is != the number of uniqe names
        # in the weave.
        self._history = []
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            count = 0
            total = 1
            try:
                pb.update('read knit index', count, total)
                fp = self._transport.get(self._filename)
                self.check_header(fp)
                # readlines reads the whole file at once:
                # bad for transports like http, good for local disk
                # we save 60 ms doing this one change (
                # from calling readline each time to calling
                # readlines once.
                # probably what we want for nice behaviour on
                # http is a incremental readlines that yields, or
                # a check for local vs non local indexes,
                for l in fp.readlines():
                    rec = l.split()
                    count += 1
                    total += 1
                    #pb.update('read knit index', count, total)
                    # See self._parse_parents
                    parents = []
                    for value in rec[4:]:
                        if '.' == value[-1]:
                            # uncompressed reference
                            parents.append(value[1:])
                        else:
                            # this is 15/4000ms faster than isinstance,
                            # (in lsprof)
                            # this function is called thousands of times a 
                            # second so small variations add up.
                            assert value.__class__ is str
                            parents.append(self._history[int(value)])
                    # end self._parse_parents
                    # self._cache_version(rec[0], 
                    #                     rec[1].split(','),
                    #                     int(rec[2]),
                    #                     int(rec[3]),
                    #                     parents)
                    # --- self._cache_version
                    # only want the _history index to reference the 1st 
                    # index entry for version_id
                    version_id = rec[0]
                    if version_id not in self._cache:
                        self._history.append(version_id)
                    self._cache[version_id] = (version_id,
                                               rec[1].split(','),
                                               int(rec[2]),
                                               int(rec[3]),
                                               parents)
                    # --- self._cache_version 
            except NoSuchFile, e:
                if mode != 'w' or not create:
                    raise
                self.write_header()
        finally:
            pb.update('read knit index', total, total)
            pb.finished()

    def _parse_parents(self, compressed_parents):
        """convert a list of string parent values into version ids.

        ints are looked up in the index.
        .FOO values are ghosts and converted in to FOO.

        NOTE: the function is retained here for clarity, and for possible
              use in partial index reads. However bulk processing now has
              it inlined in __init__ for inner-loop optimisation.
        """
        result = []
        for value in compressed_parents:
            if value[-1] == '.':
                # uncompressed reference
                result.append(value[1:])
            else:
                # this is 15/4000ms faster than isinstance,
                # this function is called thousands of times a 
                # second so small variations add up.
                assert value.__class__ is str
                result.append(self._history[int(value)])
        return result

    def get_graph(self):
        graph = []
        for version_id, index in self._cache.iteritems():
            graph.append((version_id, index[4]))
        return graph

    def get_ancestry(self, versions):
        """See VersionedFile.get_ancestry."""
        # get a graph of all the mentioned versions:
        graph = {}
        pending = set(versions)
        while len(pending):
            version = pending.pop()
            parents = self._cache[version][4]
            # got the parents ok
            # trim ghosts
            parents = [parent for parent in parents if parent in self._cache]
            for parent in parents:
                # if not completed and not a ghost
                if parent not in graph:
                    pending.add(parent)
            graph[version] = parents
        return topo_sort(graph.items())

    def get_ancestry_with_ghosts(self, versions):
        """See VersionedFile.get_ancestry_with_ghosts."""
        # get a graph of all the mentioned versions:
        graph = {}
        pending = set(versions)
        while len(pending):
            version = pending.pop()
            try:
                parents = self._cache[version][4]
            except KeyError:
                # ghost, fake it
                graph[version] = []
                pass
            else:
                # got the parents ok
                for parent in parents:
                    if parent not in graph:
                        pending.add(parent)
                graph[version] = parents
        return topo_sort(graph.items())

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

    def _version_list_to_index(self, versions):
        result_list = []
        for version in versions:
            if version in self._cache:
                result_list.append(str(self._history.index(version)))
            else:
                result_list.append('.' + version.encode('utf-8'))
        return ' '.join(result_list)

    def add_version(self, version_id, options, pos, size, parents):
        """Add a version record to the index."""
        self._cache_version(version_id, options, pos, size, parents)

        content = "%s %s %s %s %s\n" % (version_id.encode('utf-8'),
                                        ','.join(options),
                                        pos,
                                        size,
                                        self._version_list_to_index(parents))
        assert isinstance(content, str), 'content must be utf-8 encoded'
        self._transport.append(self._filename, StringIO(content))

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
        """Return parents of specified version ignoring ghosts."""
        return [parent for parent in self._cache[version_id][4] 
                if parent in self._cache]

    def get_parents_with_ghosts(self, version_id):
        """Return parents of specified version wth ghosts."""
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

    def __init__(self, transport, filename, mode, create=False):
        _KnitComponentFile.__init__(self, transport, filename, mode)
        self._file = None
        self._checked = False
        if create:
            self._transport.put(self._filename, StringIO(''))
        self._records = {}

    def clear_cache(self):
        """Clear the record cache."""
        self._records = {}

    def _open_file(self):
        if self._file is None:
            try:
                self._file = self._transport.get(self._filename)
            except NoSuchFile:
                pass
        return self._file

    def _record_to_data(self, version_id, digest, lines):
        """Convert version_id, digest, lines into a raw data block.
        
        :return: (len, a StringIO instance with the raw data ready to read.)
        """
        sio = StringIO()
        data_file = GzipFile(None, mode='wb', fileobj=sio)
        print >>data_file, "version %s %d %s" % (version_id.encode('utf-8'), len(lines), digest)
        data_file.writelines(lines)
        print >>data_file, "end %s\n" % version_id.encode('utf-8')
        data_file.close()
        length= sio.tell()
        sio.seek(0)
        return length, sio

    def add_raw_record(self, raw_data):
        """Append a prepared record to the data file."""
        assert isinstance(raw_data, str), 'data must be plain bytes'
        start_pos = self._transport.append(self._filename, StringIO(raw_data))
        return start_pos, len(raw_data)
        
    def add_record(self, version_id, digest, lines):
        """Write new text record to disk.  Returns the position in the
        file where it was written."""
        size, sio = self._record_to_data(version_id, digest, lines)
        # cache
        self._records[version_id] = (digest, lines)
        # write to disk
        start_pos = self._transport.append(self._filename, sio)
        return start_pos, size

    def _parse_record_header(self, version_id, raw_data):
        """Parse a record header for consistency.

        :return: the header and the decompressor stream.
                 as (stream, header_record)
        """
        df = GzipFile(mode='rb', fileobj=StringIO(raw_data))
        rec = df.readline().split()
        if len(rec) != 4:
            raise KnitCorrupt(self._filename, 'unexpected number of elements in record header')
        if rec[1].decode('utf-8')!= version_id:
            raise KnitCorrupt(self._filename, 
                              'unexpected version, wanted %r, got %r' % (
                                version_id, rec[1]))
        return df, rec

    def _parse_record(self, version_id, data):
        df, rec = self._parse_record_header(version_id, data)
        lines = int(rec[2])
        record_contents = self._read_record_contents(df, lines)
        l = df.readline()
        if l.decode('utf-8') != 'end %s\n' % version_id:
            raise KnitCorrupt(self._filename, 'unexpected version end line %r, wanted %r' 
                        % (l, version_id))
        df.close()
        return record_contents, rec[3]

    def _read_record_contents(self, df, record_lines):
        """Read and return n lines from datafile."""
        r = []
        for i in range(record_lines):
            r.append(df.readline())
        return r

    def read_records_iter_raw(self, records):
        """Read text records from data file and yield raw data.

        This unpacks enough of the text record to validate the id is
        as expected but thats all.

        It will actively recompress currently cached records on the
        basis that that is cheaper than I/O activity.
        """
        needed_records = []
        for version_id, pos, size in records:
            if version_id not in self._records:
                needed_records.append((version_id, pos, size))

        # setup an iterator of the external records:
        # uses readv so nice and fast we hope.
        if len(needed_records):
            # grab the disk data needed.
            raw_records = self._transport.readv(self._filename,
                [(pos, size) for version_id, pos, size in needed_records])

        for version_id, pos, size in records:
            if version_id in self._records:
                # compress a new version
                size, sio = self._record_to_data(version_id,
                                                 self._records[version_id][0],
                                                 self._records[version_id][1])
                yield version_id, sio.getvalue()
            else:
                pos, data = raw_records.next()
                # validate the header
                df, rec = self._parse_record_header(version_id, data)
                df.close()
                yield version_id, data


    def read_records_iter(self, records):
        """Read text records from data file and yield result.

        Each passed record is a tuple of (version_id, pos, len) and
        will be read in the given order.  Yields (version_id,
        contents, digest).
        """

        needed_records = []
        for version_id, pos, size in records:
            if version_id not in self._records:
                needed_records.append((version_id, pos, size))

        if len(needed_records):
            # We take it that the transport optimizes the fetching as good
            # as possible (ie, reads continous ranges.)
            response = self._transport.readv(self._filename,
                [(pos, size) for version_id, pos, size in needed_records])

            for (record_id, pos, size), (pos, data) in izip(iter(needed_records), response):
                content, digest = self._parse_record(record_id, data)
                self._records[record_id] = (digest, content)
    
        for version_id, pos, size in records:
            yield version_id, copy(self._records[version_id][1]), copy(self._records[version_id][0])

    def read_records(self, records):
        """Read records into a dictionary."""
        components = {}
        for record_id, content, digest in self.read_records_iter(records):
            components[record_id] = (content, digest)
        return components


class InterKnit(InterVersionedFile):
    """Optimised code paths for knit to knit operations."""
    
    _matching_file_factory = KnitVersionedFile
    
    @staticmethod
    def is_compatible(source, target):
        """Be compatible with knits.  """
        try:
            return (isinstance(source, KnitVersionedFile) and
                    isinstance(target, KnitVersionedFile))
        except AttributeError:
            return False

    def join(self, pb=None, msg=None, version_ids=None, ignore_missing=False):
        """See InterVersionedFile.join."""
        assert isinstance(self.source, KnitVersionedFile)
        assert isinstance(self.target, KnitVersionedFile)

        if version_ids is None:
            version_ids = self.source.versions()
        else:
            if not ignore_missing:
                self.source._check_versions_present(version_ids)
            else:
                version_ids = set(self.source.versions()).intersection(
                    set(version_ids))

        if not version_ids:
            return 0

        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            version_ids = list(version_ids)
            if None in version_ids:
                version_ids.remove(None)
    
            self.source_ancestry = set(self.source.get_ancestry(version_ids))
            this_versions = set(self.target._index.get_versions())
            needed_versions = self.source_ancestry - this_versions
            cross_check_versions = self.source_ancestry.intersection(this_versions)
            mismatched_versions = set()
            for version in cross_check_versions:
                # scan to include needed parents.
                n1 = set(self.target.get_parents_with_ghosts(version))
                n2 = set(self.source.get_parents_with_ghosts(version))
                if n1 != n2:
                    # FIXME TEST this check for cycles being introduced works
                    # the logic is we have a cycle if in our graph we are an
                    # ancestor of any of the n2 revisions.
                    for parent in n2:
                        if parent in n1:
                            # safe
                            continue
                        else:
                            parent_ancestors = self.source.get_ancestry(parent)
                            if version in parent_ancestors:
                                raise errors.GraphCycleError([parent, version])
                    # ensure this parent will be available later.
                    new_parents = n2.difference(n1)
                    needed_versions.update(new_parents.difference(this_versions))
                    mismatched_versions.add(version)
    
            if not needed_versions and not cross_check_versions:
                return 0
            full_list = topo_sort(self.source.get_graph())
    
            version_list = [i for i in full_list if (not self.target.has_version(i)
                            and i in needed_versions)]
    
            # plan the join:
            copy_queue = []
            copy_queue_records = []
            copy_set = set()
            for version_id in version_list:
                options = self.source._index.get_options(version_id)
                parents = self.source._index.get_parents_with_ghosts(version_id)
                # check that its will be a consistent copy:
                for parent in parents:
                    # if source has the parent, we must :
                    # * already have it or
                    # * have it scheduled already
                    # otherwise we dont care
                    assert (self.target.has_version(parent) or
                            parent in copy_set or
                            not self.source.has_version(parent))
                data_pos, data_size = self.source._index.get_position(version_id)
                copy_queue_records.append((version_id, data_pos, data_size))
                copy_queue.append((version_id, options, parents))
                copy_set.add(version_id)

            # data suck the join:
            count = 0
            total = len(version_list)
            # we want the raw gzip for bulk copying, but the record validated
            # just enough to be sure its the right one.
            # TODO: consider writev or write combining to reduce 
            # death of a thousand cuts feeling.
            for (version_id, raw_data), \
                (version_id2, options, parents) in \
                izip(self.source._data.read_records_iter_raw(copy_queue_records),
                     copy_queue):
                assert version_id == version_id2, 'logic error, inconsistent results'
                count = count + 1
                pb.update("Joining knit", count, total)
                pos, size = self.target._data.add_raw_record(raw_data)
                self.target._index.add_version(version_id, options, pos, size, parents)

            for version in mismatched_versions:
                # FIXME RBC 20060309 is this needed?
                n1 = set(self.target.get_parents_with_ghosts(version))
                n2 = set(self.source.get_parents_with_ghosts(version))
                # write a combined record to our history preserving the current 
                # parents as first in the list
                new_parents = self.target.get_parents_with_ghosts(version) + list(n2.difference(n1))
                self.target.fix_parents(version, new_parents)
            return count
        finally:
            pb.clear()
            pb.finished()


InterVersionedFile.register_optimiser(InterKnit)
