# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
from itertools import izip, chain
import operator
import os
import sys
import warnings
from zlib import Z_DEFAULT_COMPRESSION

import bzrlib
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    annotate,
    graph as _mod_graph,
    lru_cache,
    pack,
    trace,
    )
""")
from bzrlib import (
    cache_utf8,
    debug,
    diff,
    errors,
    osutils,
    patiencediff,
    progress,
    merge,
    ui,
    )
from bzrlib.errors import (
    FileExists,
    NoSuchFile,
    KnitError,
    InvalidRevisionId,
    KnitCorrupt,
    KnitHeaderError,
    RevisionNotPresent,
    RevisionAlreadyPresent,
    )
from bzrlib.tuned_gzip import GzipFile, bytes_to_gzip
from bzrlib.osutils import (
    contains_whitespace,
    contains_linebreaks,
    sha_string,
    sha_strings,
    )
from bzrlib.symbol_versioning import DEPRECATED_PARAMETER, deprecated_passed
from bzrlib.tsort import topo_sort
import bzrlib.ui
import bzrlib.weave
from bzrlib.versionedfile import VersionedFile, InterVersionedFile


# TODO: Split out code specific to this format into an associated object.

# TODO: Can we put in some kind of value to check that the index and data
# files belong together?

# TODO: accommodate binaries, perhaps by storing a byte count

# TODO: function to check whole file

# TODO: atomically append data, then measure backwards from the cursor
# position after writing to work out where it was located.  we may need to
# bypass python file buffering.

DATA_SUFFIX = '.knit'
INDEX_SUFFIX = '.kndx'


class KnitContent(object):
    """Content of a knit version to which deltas can be applied."""

    def __init__(self):
        self._should_strip_eol = False

    def annotate(self):
        """Return a list of (origin, text) tuples."""
        return list(self.annotate_iter())

    def apply_delta(self, delta, new_version_id):
        """Apply delta to this object to become new_version_id."""
        raise NotImplementedError(self.apply_delta)

    def cleanup_eol(self, copy_on_mutate=True):
        if self._should_strip_eol:
            if copy_on_mutate:
                self._lines = self._lines[:]
            self.strip_last_line_newline()

    def line_delta_iter(self, new_lines):
        """Generate line-based delta from this content to new_lines."""
        new_texts = new_lines.text()
        old_texts = self.text()
        s = patiencediff.PatienceSequenceMatcher(None, old_texts, new_texts)
        for tag, i1, i2, j1, j2 in s.get_opcodes():
            if tag == 'equal':
                continue
            # ofrom, oto, length, data
            yield i1, i2, j2 - j1, new_lines._lines[j1:j2]

    def line_delta(self, new_lines):
        return list(self.line_delta_iter(new_lines))

    @staticmethod
    def get_line_delta_blocks(knit_delta, source, target):
        """Extract SequenceMatcher.get_matching_blocks() from a knit delta"""
        target_len = len(target)
        s_pos = 0
        t_pos = 0
        for s_begin, s_end, t_len, new_text in knit_delta:
            true_n = s_begin - s_pos
            n = true_n
            if n > 0:
                # knit deltas do not provide reliable info about whether the
                # last line of a file matches, due to eol handling.
                if source[s_pos + n -1] != target[t_pos + n -1]:
                    n-=1
                if n > 0:
                    yield s_pos, t_pos, n
            t_pos += t_len + true_n
            s_pos = s_end
        n = target_len - t_pos
        if n > 0:
            if source[s_pos + n -1] != target[t_pos + n -1]:
                n-=1
            if n > 0:
                yield s_pos, t_pos, n
        yield s_pos + (target_len - t_pos), target_len, 0


class AnnotatedKnitContent(KnitContent):
    """Annotated content."""

    def __init__(self, lines):
        KnitContent.__init__(self)
        self._lines = lines

    def annotate_iter(self):
        """Yield tuples of (origin, text) for each content line."""
        return iter(self._lines)

    def apply_delta(self, delta, new_version_id):
        """Apply delta to this object to become new_version_id."""
        offset = 0
        lines = self._lines
        for start, end, count, delta_lines in delta:
            lines[offset+start:offset+end] = delta_lines
            offset = offset + (start - end) + count

    def strip_last_line_newline(self):
        line = self._lines[-1][1].rstrip('\n')
        self._lines[-1] = (self._lines[-1][0], line)
        self._should_strip_eol = False

    def text(self):
        try:
            lines = [text for origin, text in self._lines]
        except ValueError, e:
            # most commonly (only?) caused by the internal form of the knit
            # missing annotation information because of a bug - see thread
            # around 20071015
            raise KnitCorrupt(self,
                "line in annotated knit missing annotation information: %s"
                % (e,))

        if self._should_strip_eol:
            anno, line = lines[-1]
            lines[-1] = (anno, line.rstrip('\n'))
        return lines

    def copy(self):
        return AnnotatedKnitContent(self._lines[:])


class PlainKnitContent(KnitContent):
    """Unannotated content.
    
    When annotate[_iter] is called on this content, the same version is reported
    for all lines. Generally, annotate[_iter] is not useful on PlainKnitContent
    objects.
    """

    def __init__(self, lines, version_id):
        KnitContent.__init__(self)
        self._lines = lines
        self._version_id = version_id

    def annotate_iter(self):
        """Yield tuples of (origin, text) for each content line."""
        for line in self._lines:
            yield self._version_id, line

    def apply_delta(self, delta, new_version_id):
        """Apply delta to this object to become new_version_id."""
        offset = 0
        lines = self._lines
        for start, end, count, delta_lines in delta:
            lines[offset+start:offset+end] = delta_lines
            offset = offset + (start - end) + count
        self._version_id = new_version_id

    def copy(self):
        return PlainKnitContent(self._lines[:], self._version_id)

    def strip_last_line_newline(self):
        self._lines[-1] = self._lines[-1].rstrip('\n')
        self._should_strip_eol = False

    def text(self):
        lines = self._lines
        if self._should_strip_eol:
            lines = lines[:]
            lines[-1] = lines[-1].rstrip('\n')
        return lines


class _KnitFactory(object):
    """Base class for common Factory functions."""

    def parse_record(self, version_id, record, record_details,
                     base_content, copy_base_content=True):
        """Parse a record into a full content object.

        :param version_id: The official version id for this content
        :param record: The data returned by read_records_iter()
        :param record_details: Details about the record returned by
            get_build_details
        :param base_content: If get_build_details returns a compression_parent,
            you must return a base_content here, else use None
        :param copy_base_content: When building from the base_content, decide
            you can either copy it and return a new object, or modify it in
            place.
        :return: (content, delta) A Content object and possibly a line-delta,
            delta may be None
        """
        method, noeol = record_details
        if method == 'line-delta':
            assert base_content is not None
            if copy_base_content:
                content = base_content.copy()
            else:
                content = base_content
            delta = self.parse_line_delta(record, version_id)
            content.apply_delta(delta, version_id)
        else:
            content = self.parse_fulltext(record, version_id)
            delta = None
        content._should_strip_eol = noeol
        return (content, delta)


class KnitAnnotateFactory(_KnitFactory):
    """Factory for creating annotated Content objects."""

    annotated = True

    def make(self, lines, version_id):
        num_lines = len(lines)
        return AnnotatedKnitContent(zip([version_id] * num_lines, lines))

    def parse_fulltext(self, content, version_id):
        """Convert fulltext to internal representation

        fulltext content is of the format
        revid(utf8) plaintext\n
        internal representation is of the format:
        (revid, plaintext)
        """
        # TODO: jam 20070209 The tests expect this to be returned as tuples,
        #       but the code itself doesn't really depend on that.
        #       Figure out a way to not require the overhead of turning the
        #       list back into tuples.
        lines = [tuple(line.split(' ', 1)) for line in content]
        return AnnotatedKnitContent(lines)

    def parse_line_delta_iter(self, lines):
        return iter(self.parse_line_delta(lines))

    def parse_line_delta(self, lines, version_id, plain=False):
        """Convert a line based delta into internal representation.

        line delta is in the form of:
        intstart intend intcount
        1..count lines:
        revid(utf8) newline\n
        internal representation is
        (start, end, count, [1..count tuples (revid, newline)])

        :param plain: If True, the lines are returned as a plain
            list without annotations, not as a list of (origin, content) tuples, i.e.
            (start, end, count, [1..count newline])
        """
        result = []
        lines = iter(lines)
        next = lines.next

        cache = {}
        def cache_and_return(line):
            origin, text = line.split(' ', 1)
            return cache.setdefault(origin, origin), text

        # walk through the lines parsing.
        # Note that the plain test is explicitly pulled out of the
        # loop to minimise any performance impact
        if plain:
            for header in lines:
                start, end, count = [int(n) for n in header.split(',')]
                contents = [next().split(' ', 1)[1] for i in xrange(count)]
                result.append((start, end, count, contents))
        else:
            for header in lines:
                start, end, count = [int(n) for n in header.split(',')]
                contents = [tuple(next().split(' ', 1)) for i in xrange(count)]
                result.append((start, end, count, contents))
        return result

    def get_fulltext_content(self, lines):
        """Extract just the content lines from a fulltext."""
        return (line.split(' ', 1)[1] for line in lines)

    def get_linedelta_content(self, lines):
        """Extract just the content from a line delta.

        This doesn't return all of the extra information stored in a delta.
        Only the actual content lines.
        """
        lines = iter(lines)
        next = lines.next
        for header in lines:
            header = header.split(',')
            count = int(header[2])
            for i in xrange(count):
                origin, text = next().split(' ', 1)
                yield text

    def lower_fulltext(self, content):
        """convert a fulltext content record into a serializable form.

        see parse_fulltext which this inverts.
        """
        # TODO: jam 20070209 We only do the caching thing to make sure that
        #       the origin is a valid utf-8 line, eventually we could remove it
        return ['%s %s' % (o, t) for o, t in content._lines]

    def lower_line_delta(self, delta):
        """convert a delta into a serializable form.

        See parse_line_delta which this inverts.
        """
        # TODO: jam 20070209 We only do the caching thing to make sure that
        #       the origin is a valid utf-8 line, eventually we could remove it
        out = []
        for start, end, c, lines in delta:
            out.append('%d,%d,%d\n' % (start, end, c))
            out.extend(origin + ' ' + text
                       for origin, text in lines)
        return out

    def annotate_iter(self, knit, version_id):
        content = knit._get_content(version_id)
        return content.annotate_iter()


class KnitPlainFactory(_KnitFactory):
    """Factory for creating plain Content objects."""

    annotated = False

    def make(self, lines, version_id):
        return PlainKnitContent(lines, version_id)

    def parse_fulltext(self, content, version_id):
        """This parses an unannotated fulltext.

        Note that this is not a noop - the internal representation
        has (versionid, line) - its just a constant versionid.
        """
        return self.make(content, version_id)

    def parse_line_delta_iter(self, lines, version_id):
        cur = 0
        num_lines = len(lines)
        while cur < num_lines:
            header = lines[cur]
            cur += 1
            start, end, c = [int(n) for n in header.split(',')]
            yield start, end, c, lines[cur:cur+c]
            cur += c

    def parse_line_delta(self, lines, version_id):
        return list(self.parse_line_delta_iter(lines, version_id))

    def get_fulltext_content(self, lines):
        """Extract just the content lines from a fulltext."""
        return iter(lines)

    def get_linedelta_content(self, lines):
        """Extract just the content from a line delta.

        This doesn't return all of the extra information stored in a delta.
        Only the actual content lines.
        """
        lines = iter(lines)
        next = lines.next
        for header in lines:
            header = header.split(',')
            count = int(header[2])
            for i in xrange(count):
                yield next()

    def lower_fulltext(self, content):
        return content.text()

    def lower_line_delta(self, delta):
        out = []
        for start, end, c, lines in delta:
            out.append('%d,%d,%d\n' % (start, end, c))
            out.extend(lines)
        return out

    def annotate_iter(self, knit, version_id):
        annotator = _KnitAnnotator(knit)
        return iter(annotator.annotate(version_id))


def make_empty_knit(transport, relpath):
    """Construct a empty knit at the specified location."""
    k = KnitVersionedFile(transport, relpath, 'w', KnitPlainFactory)


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

    def __init__(self, relpath, transport, file_mode=None, access_mode=None,
        factory=None, delta=True, create=False, create_parent_dir=False,
        delay_create=False, dir_mode=None, index=None, access_method=None):
        """Construct a knit at location specified by relpath.
        
        :param create: If not True, only open an existing knit.
        :param create_parent_dir: If True, create the parent directory if 
            creating the file fails. (This is used for stores with 
            hash-prefixes that may not exist yet)
        :param delay_create: The calling code is aware that the knit won't 
            actually be created until the first data is stored.
        :param index: An index to use for the knit.
        """
        if access_mode is None:
            access_mode = 'w'
        super(KnitVersionedFile, self).__init__(access_mode)
        assert access_mode in ('r', 'w'), "invalid mode specified %r" % access_mode
        self.transport = transport
        self.filename = relpath
        self.factory = factory or KnitAnnotateFactory()
        self.writable = (access_mode == 'w')
        self.delta = delta

        self._max_delta_chain = 200

        if index is None:
            self._index = _KnitIndex(transport, relpath + INDEX_SUFFIX,
                access_mode, create=create, file_mode=file_mode,
                create_parent_dir=create_parent_dir, delay_create=delay_create,
                dir_mode=dir_mode)
        else:
            self._index = index
        if access_method is None:
            _access = _KnitAccess(transport, relpath + DATA_SUFFIX, file_mode, dir_mode,
                ((create and not len(self)) and delay_create), create_parent_dir)
        else:
            _access = access_method
        if create and not len(self) and not delay_create:
            _access.create()
        self._data = _KnitData(_access)

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__,
                           self.transport.abspath(self.filename))
    
    def _check_should_delta(self, first_parents):
        """Iterate back through the parent listing, looking for a fulltext.

        This is used when we want to decide whether to add a delta or a new
        fulltext. It searches for _max_delta_chain parents. When it finds a
        fulltext parent, it sees if the total size of the deltas leading up to
        it is large enough to indicate that we want a new full text anyway.

        Return True if we should create a new delta, False if we should use a
        full text.
        """
        delta_size = 0
        fulltext_size = None
        delta_parents = first_parents
        for count in xrange(self._max_delta_chain):
            parent = delta_parents[0]
            method = self._index.get_method(parent)
            index, pos, size = self._index.get_position(parent)
            if method == 'fulltext':
                fulltext_size = size
                break
            delta_size += size
            delta_parents = self._index.get_parents(parent)
        else:
            # We couldn't find a fulltext, so we must create a new one
            return False

        return fulltext_size > delta_size

    def _add_raw_records(self, records, data):
        """Add all the records 'records' with data pre-joined in 'data'.

        :param records: A list of tuples(version_id, options, parents, size).
        :param data: The data for the records. When it is written, the records
                     are adjusted to have pos pointing into data by the sum of
                     the preceding records sizes.
        """
        # write all the data
        raw_record_sizes = [record[3] for record in records]
        positions = self._data.add_raw_records(raw_record_sizes, data)
        offset = 0
        index_entries = []
        for (version_id, options, parents, size), access_memo in zip(
            records, positions):
            index_entries.append((version_id, options, access_memo, parents))
            if self._data._do_cache:
                self._data._cache[version_id] = data[offset:offset+size]
            offset += size
        self._index.add_versions(index_entries)

    def enable_cache(self):
        """Start caching data for this knit"""
        self._data.enable_cache()

    def clear_cache(self):
        """Clear the data cache only."""
        self._data.clear_cache()

    def copy_to(self, name, transport):
        """See VersionedFile.copy_to()."""
        # copy the current index to a temp index to avoid racing with local
        # writes
        transport.put_file_non_atomic(name + INDEX_SUFFIX + '.tmp',
                self.transport.get(self._index._filename))
        # copy the data file
        f = self._data._open_file()
        try:
            transport.put_file(name + DATA_SUFFIX, f)
        finally:
            f.close()
        # move the copied index into place
        transport.move(name + INDEX_SUFFIX + '.tmp', name + INDEX_SUFFIX)

    def create_empty(self, name, transport, mode=None):
        return KnitVersionedFile(name, transport, factory=self.factory,
                                 delta=self.delta, create=True)
    
    def get_data_stream(self, required_versions):
        """Get a data stream for the specified versions.

        Versions may be returned in any order, not necessarily the order
        specified.  They are returned in a partial order by compression
        parent, so that the deltas can be applied as the data stream is
        inserted; however note that compression parents will not be sent
        unless they were specifically requested, as the client may already
        have them.

        :param required_versions: The exact set of versions to be extracted.
            Unlike some other knit methods, this is not used to generate a
            transitive closure, rather it is used precisely as given.
        
        :returns: format_signature, list of (version, options, length, parents),
            reader_callable.
        """
        required_version_set = frozenset(required_versions)
        version_index = {}
        # list of revisions that can just be sent without waiting for their
        # compression parent
        ready_to_send = []
        # map from revision to the children based on it
        deferred = {}
        # first, read all relevant index data, enough to sort into the right
        # order to return
        for version_id in required_versions:
            options = self._index.get_options(version_id)
            parents = self._index.get_parents_with_ghosts(version_id)
            index_memo = self._index.get_position(version_id)
            version_index[version_id] = (index_memo, options, parents)
            if ('line-delta' in options
                and parents[0] in required_version_set):
                # must wait until the parent has been sent
                deferred.setdefault(parents[0], []). \
                    append(version_id)
            else:
                # either a fulltext, or a delta whose parent the client did
                # not ask for and presumably already has
                ready_to_send.append(version_id)
        # build a list of results to return, plus instructions for data to
        # read from the file
        copy_queue_records = []
        temp_version_list = []
        while ready_to_send:
            # XXX: pushing and popping lists may be a bit inefficient
            version_id = ready_to_send.pop(0)
            (index_memo, options, parents) = version_index[version_id]
            copy_queue_records.append((version_id, index_memo))
            none, data_pos, data_size = index_memo
            temp_version_list.append((version_id, options, data_size,
                parents))
            if version_id in deferred:
                # now we can send all the children of this revision - we could
                # put them in anywhere, but we hope that sending them soon
                # after the fulltext will give good locality in the receiver
                ready_to_send[:0] = deferred.pop(version_id)
        assert len(deferred) == 0, \
            "Still have compressed child versions waiting to be sent"
        # XXX: The stream format is such that we cannot stream it - we have to
        # know the length of all the data a-priori.
        raw_datum = []
        result_version_list = []
        for (version_id, raw_data), \
            (version_id2, options, _, parents) in \
            izip(self._data.read_records_iter_raw(copy_queue_records),
                 temp_version_list):
            assert version_id == version_id2, \
                'logic error, inconsistent results'
            raw_datum.append(raw_data)
            result_version_list.append(
                (version_id, options, len(raw_data), parents))
        # provide a callback to get data incrementally.
        pseudo_file = StringIO(''.join(raw_datum))
        def read(length):
            if length is None:
                return pseudo_file.read()
            else:
                return pseudo_file.read(length)
        return (self.get_format_signature(), result_version_list, read)

    def _extract_blocks(self, version_id, source, target):
        if self._index.get_method(version_id) != 'line-delta':
            return None
        parent, sha1, noeol, delta = self.get_delta(version_id)
        return KnitContent.get_line_delta_blocks(delta, source, target)

    def get_delta(self, version_id):
        """Get a delta for constructing version from some other version."""
        self.check_not_reserved_id(version_id)
        parents = self.get_parents(version_id)
        if len(parents):
            parent = parents[0]
        else:
            parent = None
        index_memo = self._index.get_position(version_id)
        data, sha1 = self._data.read_records(((version_id, index_memo),))[version_id]
        noeol = 'no-eol' in self._index.get_options(version_id)
        if 'fulltext' == self._index.get_method(version_id):
            new_content = self.factory.parse_fulltext(data, version_id)
            if parent is not None:
                reference_content = self._get_content(parent)
                old_texts = reference_content.text()
            else:
                old_texts = []
            new_texts = new_content.text()
            delta_seq = patiencediff.PatienceSequenceMatcher(None, old_texts,
                                                             new_texts)
            return parent, sha1, noeol, self._make_line_delta(delta_seq, new_content)
        else:
            delta = self.factory.parse_line_delta(data, version_id)
            return parent, sha1, noeol, delta

    def get_format_signature(self):
        """See VersionedFile.get_format_signature()."""
        if self.factory.annotated:
            annotated_part = "annotated"
        else:
            annotated_part = "plain"
        return "knit-%s" % (annotated_part,)
        
    def get_graph_with_ghosts(self):
        """See VersionedFile.get_graph_with_ghosts()."""
        graph_items = self._index.get_graph()
        return dict(graph_items)

    def get_sha1(self, version_id):
        return self.get_sha1s([version_id])[0]

    def get_sha1s(self, version_ids):
        """See VersionedFile.get_sha1()."""
        record_map = self._get_record_map(version_ids)
        # record entry 2 is the 'digest'.
        return [record_map[v][2] for v in version_ids]

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

    def insert_data_stream(self, (format, data_list, reader_callable)):
        """Insert knit records from a data stream into this knit.

        If a version in the stream is already present in this knit, it will not
        be inserted a second time.  It will be checked for consistency with the
        stored version however, and may cause a KnitCorrupt error to be raised
        if the data in the stream disagrees with the already stored data.
        
        :seealso: get_data_stream
        """
        if format != self.get_format_signature():
            if 'knit' in debug.debug_flags:
                trace.mutter(
                    'incompatible format signature inserting to %r', self)
            source = self._knit_from_datastream(
                (format, data_list, reader_callable))
            self.join(source)
            return

        for version_id, options, length, parents in data_list:
            if self.has_version(version_id):
                # First check: the list of parents.
                my_parents = self.get_parents_with_ghosts(version_id)
                if tuple(my_parents) != tuple(parents):
                    # XXX: KnitCorrupt is not quite the right exception here.
                    raise KnitCorrupt(
                        self.filename,
                        'parents list %r from data stream does not match '
                        'already recorded parents %r for %s'
                        % (parents, my_parents, version_id))

                # Also check the SHA-1 of the fulltext this content will
                # produce.
                raw_data = reader_callable(length)
                my_fulltext_sha1 = self.get_sha1(version_id)
                df, rec = self._data._parse_record_header(version_id, raw_data)
                stream_fulltext_sha1 = rec[3]
                if my_fulltext_sha1 != stream_fulltext_sha1:
                    # Actually, we don't know if it's this knit that's corrupt,
                    # or the data stream we're trying to insert.
                    raise KnitCorrupt(
                        self.filename, 'sha-1 does not match %s' % version_id)
            else:
                if 'line-delta' in options:
                    # Make sure that this knit record is actually useful: a
                    # line-delta is no use unless we have its parent.
                    # Fetching from a broken repository with this problem
                    # shouldn't break the target repository.
                    #
                    # See https://bugs.launchpad.net/bzr/+bug/164443
                    if not self._index.has_version(parents[0]):
                        raise KnitCorrupt(
                            self.filename,
                            'line-delta from stream '
                            'for version %s '
                            'references '
                            'missing parent %s\n'
                            'Try running "bzr check" '
                            'on the source repository, and "bzr reconcile" '
                            'if necessary.' %
                            (version_id, parents[0]))
                self._add_raw_records(
                    [(version_id, options, parents, length)],
                    reader_callable(length))

    def _knit_from_datastream(self, (format, data_list, reader_callable)):
        """Create a knit object from a data stream.

        This method exists to allow conversion of data streams that do not
        match the signature of this knit. Generally it will be slower and use
        more memory to use this method to insert data, but it will work.

        :seealso: get_data_stream for details on datastreams.
        :return: A knit versioned file which can be used to join the datastream
            into self.
        """
        if format == "knit-plain":
            factory = KnitPlainFactory()
        elif format == "knit-annotated":
            factory = KnitAnnotateFactory()
        else:
            raise errors.KnitDataStreamUnknown(format)
        index = _StreamIndex(data_list, self._index)
        access = _StreamAccess(reader_callable, index, self, factory)
        return KnitVersionedFile(self.filename, self.transport,
            factory=factory, index=index, access_method=access)

    def versions(self):
        """See VersionedFile.versions."""
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(2, "versions scales with size of history")
        return self._index.get_versions()

    def has_version(self, version_id):
        """See VersionedFile.has_version."""
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(2, "has_version is a LBYL scenario")
        return self._index.has_version(version_id)

    __contains__ = has_version

    def _merge_annotations(self, content, parents, parent_texts={},
                           delta=None, annotated=None,
                           left_matching_blocks=None):
        """Merge annotations for content.  This is done by comparing
        the annotations based on changed to the text.
        """
        if left_matching_blocks is not None:
            delta_seq = diff._PrematchedMatcher(left_matching_blocks)
        else:
            delta_seq = None
        if annotated:
            for parent_id in parents:
                merge_content = self._get_content(parent_id, parent_texts)
                if (parent_id == parents[0] and delta_seq is not None):
                    seq = delta_seq
                else:
                    seq = patiencediff.PatienceSequenceMatcher(
                        None, merge_content.text(), content.text())
                for i, j, n in seq.get_matching_blocks():
                    if n == 0:
                        continue
                    # this appears to copy (origin, text) pairs across to the
                    # new content for any line that matches the last-checked
                    # parent.
                    content._lines[j:j+n] = merge_content._lines[i:i+n]
        if delta:
            if delta_seq is None:
                reference_content = self._get_content(parents[0], parent_texts)
                new_texts = content.text()
                old_texts = reference_content.text()
                delta_seq = patiencediff.PatienceSequenceMatcher(
                                                 None, old_texts, new_texts)
            return self._make_line_delta(delta_seq, content)

    def _make_line_delta(self, delta_seq, new_content):
        """Generate a line delta from delta_seq and new_content."""
        diff_hunks = []
        for op in delta_seq.get_opcodes():
            if op[0] == 'equal':
                continue
            diff_hunks.append((op[1], op[2], op[4]-op[3], new_content._lines[op[3]:op[4]]))
        return diff_hunks

    def _get_components_positions(self, version_ids):
        """Produce a map of position data for the components of versions.

        This data is intended to be used for retrieving the knit records.

        A dict of version_id to (record_details, index_memo, next, parents) is
        returned.
        method is the way referenced data should be applied.
        index_memo is the handle to pass to the data access to actually get the
            data
        next is the build-parent of the version, or None for fulltexts.
        parents is the version_ids of the parents of this version
        """
        component_data = {}
        pending_components = version_ids
        while pending_components:
            build_details = self._index.get_build_details(pending_components)
            current_components = set(pending_components)
            pending_components = set()
            for version_id, details in build_details.iteritems():
                (index_memo, compression_parent, parents,
                 record_details) = details
                method = record_details[0]
                if compression_parent is not None:
                    pending_components.add(compression_parent)
                component_data[version_id] = (record_details, index_memo,
                                              compression_parent)
            missing = current_components.difference(build_details)
            if missing:
                raise errors.RevisionNotPresent(missing.pop(), self.filename)
        return component_data
       
    def _get_content(self, version_id, parent_texts={}):
        """Returns a content object that makes up the specified
        version."""
        cached_version = parent_texts.get(version_id, None)
        if cached_version is not None:
            if not self.has_version(version_id):
                raise RevisionNotPresent(version_id, self.filename)
            return cached_version

        text_map, contents_map = self._get_content_maps([version_id])
        return contents_map[version_id]

    def _check_versions_present(self, version_ids):
        """Check that all specified versions are present."""
        self._index.check_versions_present(version_ids)

    def _add_lines_with_ghosts(self, version_id, parents, lines, parent_texts,
        nostore_sha, random_id, check_content):
        """See VersionedFile.add_lines_with_ghosts()."""
        self._check_add(version_id, lines, random_id, check_content)
        return self._add(version_id, lines, parents, self.delta,
            parent_texts, None, nostore_sha, random_id)

    def _add_lines(self, version_id, parents, lines, parent_texts,
        left_matching_blocks, nostore_sha, random_id, check_content):
        """See VersionedFile.add_lines."""
        self._check_add(version_id, lines, random_id, check_content)
        self._check_versions_present(parents)
        return self._add(version_id, lines[:], parents, self.delta,
            parent_texts, left_matching_blocks, nostore_sha, random_id)

    def _check_add(self, version_id, lines, random_id, check_content):
        """check that version_id and lines are safe to add."""
        if contains_whitespace(version_id):
            raise InvalidRevisionId(version_id, self.filename)
        self.check_not_reserved_id(version_id)
        # Technically this could be avoided if we are happy to allow duplicate
        # id insertion when other things than bzr core insert texts, but it
        # seems useful for folk using the knit api directly to have some safety
        # blanket that we can disable.
        if not random_id and self.has_version(version_id):
            raise RevisionAlreadyPresent(version_id, self.filename)
        if check_content:
            self._check_lines_not_unicode(lines)
            self._check_lines_are_lines(lines)

    def _add(self, version_id, lines, parents, delta, parent_texts,
        left_matching_blocks, nostore_sha, random_id):
        """Add a set of lines on top of version specified by parents.

        If delta is true, compress the text as a line-delta against
        the first parent.

        Any versions not present will be converted into ghosts.
        """
        # first thing, if the content is something we don't need to store, find
        # that out.
        line_bytes = ''.join(lines)
        digest = sha_string(line_bytes)
        if nostore_sha == digest:
            raise errors.ExistingContent

        present_parents = []
        if parent_texts is None:
            parent_texts = {}
        for parent in parents:
            if self.has_version(parent):
                present_parents.append(parent)

        # can only compress against the left most present parent.
        if (delta and
            (len(present_parents) == 0 or
             present_parents[0] != parents[0])):
            delta = False

        text_length = len(line_bytes)
        options = []
        if lines:
            if lines[-1][-1] != '\n':
                # copy the contents of lines.
                lines = lines[:]
                options.append('no-eol')
                lines[-1] = lines[-1] + '\n'
                line_bytes += '\n'

        if delta:
            # To speed the extract of texts the delta chain is limited
            # to a fixed number of deltas.  This should minimize both
            # I/O and the time spend applying deltas.
            delta = self._check_should_delta(present_parents)

        assert isinstance(version_id, str)
        content = self.factory.make(lines, version_id)
        if delta or (self.factory.annotated and len(present_parents) > 0):
            # Merge annotations from parent texts if needed.
            delta_hunks = self._merge_annotations(content, present_parents,
                parent_texts, delta, self.factory.annotated,
                left_matching_blocks)

        if delta:
            options.append('line-delta')
            store_lines = self.factory.lower_line_delta(delta_hunks)
            size, bytes = self._data._record_to_data(version_id, digest,
                store_lines)
        else:
            options.append('fulltext')
            # isinstance is slower and we have no hierarchy.
            if self.factory.__class__ == KnitPlainFactory:
                # Use the already joined bytes saving iteration time in
                # _record_to_data.
                size, bytes = self._data._record_to_data(version_id, digest,
                    lines, [line_bytes])
            else:
                # get mixed annotation + content and feed it into the
                # serialiser.
                store_lines = self.factory.lower_fulltext(content)
                size, bytes = self._data._record_to_data(version_id, digest,
                    store_lines)

        access_memo = self._data.add_raw_records([size], bytes)[0]
        self._index.add_versions(
            ((version_id, options, access_memo, parents),),
            random_id=random_id)
        return digest, text_length, content

    def check(self, progress_bar=None):
        """See VersionedFile.check()."""

    def _clone_text(self, new_version_id, old_version_id, parents):
        """See VersionedFile.clone_text()."""
        # FIXME RBC 20060228 make fast by only inserting an index with null 
        # delta.
        self.add_lines(new_version_id, parents, self.get_lines(old_version_id))

    def get_lines(self, version_id):
        """See VersionedFile.get_lines()."""
        return self.get_line_list([version_id])[0]

    def _get_record_map(self, version_ids):
        """Produce a dictionary of knit records.
        
        :return: {version_id:(record, record_details, digest, next)}
            record
                data returned from read_records
            record_details
                opaque information to pass to parse_record
            digest
                SHA1 digest of the full text after all steps are done
            next
                build-parent of the version, i.e. the leftmost ancestor.
                Will be None if the record is not a delta.
        """
        position_map = self._get_components_positions(version_ids)
        # c = component_id, r = record_details, i_m = index_memo, n = next
        records = [(c, i_m) for c, (r, i_m, n)
                             in position_map.iteritems()]
        record_map = {}
        for component_id, record, digest in \
                self._data.read_records_iter(records):
            (record_details, index_memo, next) = position_map[component_id]
            record_map[component_id] = record, record_details, digest, next

        return record_map

    def get_text(self, version_id):
        """See VersionedFile.get_text"""
        return self.get_texts([version_id])[0]

    def get_texts(self, version_ids):
        return [''.join(l) for l in self.get_line_list(version_ids)]

    def get_line_list(self, version_ids):
        """Return the texts of listed versions as a list of strings."""
        for version_id in version_ids:
            self.check_not_reserved_id(version_id)
        text_map, content_map = self._get_content_maps(version_ids)
        return [text_map[v] for v in version_ids]

    _get_lf_split_line_list = get_line_list

    def _get_content_maps(self, version_ids):
        """Produce maps of text and KnitContents
        
        :return: (text_map, content_map) where text_map contains the texts for
        the requested versions and content_map contains the KnitContents.
        Both dicts take version_ids as their keys.
        """
        # FUTURE: This function could be improved for the 'extract many' case
        # by tracking each component and only doing the copy when the number of
        # children than need to apply delta's to it is > 1 or it is part of the
        # final output.
        version_ids = list(version_ids)
        multiple_versions = len(version_ids) != 1
        record_map = self._get_record_map(version_ids)

        text_map = {}
        content_map = {}
        final_content = {}
        for version_id in version_ids:
            components = []
            cursor = version_id
            while cursor is not None:
                record, record_details, digest, next = record_map[cursor]
                components.append((cursor, record, record_details, digest))
                if cursor in content_map:
                    break
                cursor = next

            content = None
            for (component_id, record, record_details,
                 digest) in reversed(components):
                if component_id in content_map:
                    content = content_map[component_id]
                else:
                    content, delta = self.factory.parse_record(version_id,
                        record, record_details, content,
                        copy_base_content=multiple_versions)
                    if multiple_versions:
                        content_map[component_id] = content

            content.cleanup_eol(copy_on_mutate=multiple_versions)
            final_content[version_id] = content

            # digest here is the digest from the last applied component.
            text = content.text()
            actual_sha = sha_strings(text)
            if actual_sha != digest:
                raise KnitCorrupt(self.filename,
                    '\n  sha-1 %s'
                    '\n  of reconstructed text does not match'
                    '\n  expected %s'
                    '\n  for version %s' %
                    (actual_sha, digest, version_id))
            text_map[version_id] = text
        return text_map, final_content

    def iter_lines_added_or_present_in_versions(self, version_ids=None, 
                                                pb=None):
        """See VersionedFile.iter_lines_added_or_present_in_versions()."""
        if version_ids is None:
            version_ids = self.versions()
        if pb is None:
            pb = progress.DummyProgress()
        # we don't care about inclusions, the caller cares.
        # but we need to setup a list of records to visit.
        # we need version_id, position, length
        version_id_records = []
        requested_versions = set(version_ids)
        # filter for available versions
        for version_id in requested_versions:
            if not self.has_version(version_id):
                raise RevisionNotPresent(version_id, self.filename)
        # get a in-component-order queue:
        for version_id in self.versions():
            if version_id in requested_versions:
                index_memo = self._index.get_position(version_id)
                version_id_records.append((version_id, index_memo))

        total = len(version_id_records)
        for version_idx, (version_id, data, sha_value) in \
            enumerate(self._data.read_records_iter(version_id_records)):
            pb.update('Walking content.', version_idx, total)
            method = self._index.get_method(version_id)

            assert method in ('fulltext', 'line-delta')
            if method == 'fulltext':
                line_iterator = self.factory.get_fulltext_content(data)
            else:
                line_iterator = self.factory.get_linedelta_content(data)
            # XXX: It might be more efficient to yield (version_id,
            # line_iterator) in the future. However for now, this is a simpler
            # change to integrate into the rest of the codebase. RBC 20071110
            for line in line_iterator:
                yield line, version_id

        pb.update('Walking content.', total, total)
        
    def iter_parents(self, version_ids):
        """Iterate through the parents for many version ids.

        :param version_ids: An iterable yielding version_ids.
        :return: An iterator that yields (version_id, parents). Requested 
            version_ids not present in the versioned file are simply skipped.
            The order is undefined, allowing for different optimisations in
            the underlying implementation.
        """
        return self._index.iter_parents(version_ids)

    def num_versions(self):
        """See VersionedFile.num_versions()."""
        return self._index.num_versions()

    __len__ = num_versions

    def annotate_iter(self, version_id):
        """See VersionedFile.annotate_iter."""
        return self.factory.annotate_iter(self, version_id)

    def get_parent_map(self, version_ids):
        """See VersionedFile.get_parent_map."""
        result = {}
        lookup = self._index.get_parents_with_ghosts
        for version_id in version_ids:
            try:
                result[version_id] = tuple(lookup(version_id))
            except KeyError:
                pass
        return result

    def get_ancestry(self, versions, topo_sorted=True):
        """See VersionedFile.get_ancestry."""
        if isinstance(versions, basestring):
            versions = [versions]
        if not versions:
            return []
        return self._index.get_ancestry(versions, topo_sorted)

    def get_ancestry_with_ghosts(self, versions):
        """See VersionedFile.get_ancestry_with_ghosts."""
        if isinstance(versions, basestring):
            versions = [versions]
        if not versions:
            return []
        return self._index.get_ancestry_with_ghosts(versions)

    def plan_merge(self, ver_a, ver_b):
        """See VersionedFile.plan_merge."""
        ancestors_b = set(self.get_ancestry(ver_b, topo_sorted=False))
        ancestors_a = set(self.get_ancestry(ver_a, topo_sorted=False))
        annotated_a = self.annotate(ver_a)
        annotated_b = self.annotate(ver_b)
        return merge._plan_annotate_merge(annotated_a, annotated_b,
                                          ancestors_a, ancestors_b)


class _KnitComponentFile(object):
    """One of the files used to implement a knit database"""

    def __init__(self, transport, filename, mode, file_mode=None,
                 create_parent_dir=False, dir_mode=None):
        self._transport = transport
        self._filename = filename
        self._mode = mode
        self._file_mode = file_mode
        self._dir_mode = dir_mode
        self._create_parent_dir = create_parent_dir
        self._need_to_create = False

    def _full_path(self):
        """Return the full path to this file."""
        return self._transport.base + self._filename

    def check_header(self, fp):
        line = fp.readline()
        if line == '':
            # An empty file can actually be treated as though the file doesn't
            # exist yet.
            raise errors.NoSuchFile(self._full_path())
        if line != self.HEADER:
            raise KnitHeaderError(badline=line,
                              filename=self._transport.abspath(self._filename))

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

    The index file on disc contains a header, followed by one line per knit
    record. The same revision can be present in an index file more than once.
    The first occurrence gets assigned a sequence number starting from 0. 
    
    The format of a single line is
    REVISION_ID FLAGS BYTE_OFFSET LENGTH( PARENT_ID|PARENT_SEQUENCE_ID)* :\n
    REVISION_ID is a utf8-encoded revision id
    FLAGS is a comma separated list of flags about the record. Values include 
        no-eol, line-delta, fulltext.
    BYTE_OFFSET is the ascii representation of the byte offset in the data file
        that the the compressed data starts at.
    LENGTH is the ascii representation of the length of the data file.
    PARENT_ID a utf-8 revision id prefixed by a '.' that is a parent of
        REVISION_ID.
    PARENT_SEQUENCE_ID the ascii representation of the sequence number of a
        revision id already in the knit that is a parent of REVISION_ID.
    The ' :' marker is the end of record marker.
    
    partial writes:
    when a write is interrupted to the index file, it will result in a line
    that does not end in ' :'. If the ' :' is not present at the end of a line,
    or at the end of the file, then the record that is missing it will be
    ignored by the parser.

    When writing new records to the index file, the data is preceded by '\n'
    to ensure that records always start on new lines even if the last write was
    interrupted. As a result its normal for the last line in the index to be
    missing a trailing newline. One can be added with no harmful effects.
    """

    HEADER = "# bzr knit index 8\n"

    # speed of knit parsing went from 280 ms to 280 ms with slots addition.
    # __slots__ = ['_cache', '_history', '_transport', '_filename']

    def _cache_version(self, version_id, options, pos, size, parents):
        """Cache a version record in the history array and index cache.

        This is inlined into _load_data for performance. KEEP IN SYNC.
        (It saves 60ms, 25% of the __init__ overhead on local 4000 record
         indexes).
        """
        # only want the _history index to reference the 1st index entry
        # for version_id
        if version_id not in self._cache:
            index = len(self._history)
            self._history.append(version_id)
        else:
            index = self._cache[version_id][5]
        self._cache[version_id] = (version_id,
                                   options,
                                   pos,
                                   size,
                                   parents,
                                   index)

    def __init__(self, transport, filename, mode, create=False, file_mode=None,
                 create_parent_dir=False, delay_create=False, dir_mode=None):
        _KnitComponentFile.__init__(self, transport, filename, mode,
                                    file_mode=file_mode,
                                    create_parent_dir=create_parent_dir,
                                    dir_mode=dir_mode)
        self._cache = {}
        # position in _history is the 'official' index for a revision
        # but the values may have come from a newer entry.
        # so - wc -l of a knit index is != the number of unique names
        # in the knit.
        self._history = []
        try:
            fp = self._transport.get(self._filename)
            try:
                # _load_data may raise NoSuchFile if the target knit is
                # completely empty.
                _load_data(self, fp)
            finally:
                fp.close()
        except NoSuchFile:
            if mode != 'w' or not create:
                raise
            elif delay_create:
                self._need_to_create = True
            else:
                self._transport.put_bytes_non_atomic(
                    self._filename, self.HEADER, mode=self._file_mode)

    def get_graph(self):
        """Return a list of the node:parents lists from this knit index."""
        return [(vid, idx[4]) for vid, idx in self._cache.iteritems()]

    def get_ancestry(self, versions, topo_sorted=True):
        """See VersionedFile.get_ancestry."""
        # get a graph of all the mentioned versions:
        graph = {}
        pending = set(versions)
        cache = self._cache
        while pending:
            version = pending.pop()
            # trim ghosts
            try:
                parents = [p for p in cache[version][4] if p in cache]
            except KeyError:
                raise RevisionNotPresent(version, self._filename)
            # if not completed and not a ghost
            pending.update([p for p in parents if p not in graph])
            graph[version] = parents
        if not topo_sorted:
            return graph.keys()
        return topo_sort(graph.items())

    def get_ancestry_with_ghosts(self, versions):
        """See VersionedFile.get_ancestry_with_ghosts."""
        # get a graph of all the mentioned versions:
        self.check_versions_present(versions)
        cache = self._cache
        graph = {}
        pending = set(versions)
        while pending:
            version = pending.pop()
            try:
                parents = cache[version][4]
            except KeyError:
                # ghost, fake it
                graph[version] = []
            else:
                # if not completed
                pending.update([p for p in parents if p not in graph])
                graph[version] = parents
        return topo_sort(graph.items())

    def get_build_details(self, version_ids):
        """Get the method, index_memo and compression parent for version_ids.

        Ghosts are omitted from the result.

        :param version_ids: An iterable of version_ids.
        :return: A dict of version_id:(index_memo, compression_parent,
                                       parents, record_details).
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
        result = {}
        for version_id in version_ids:
            if version_id not in self._cache:
                # ghosts are omitted
                continue
            method = self.get_method(version_id)
            parents = self.get_parents_with_ghosts(version_id)
            if method == 'fulltext':
                compression_parent = None
            else:
                compression_parent = parents[0]
            noeol = 'no-eol' in self.get_options(version_id)
            index_memo = self.get_position(version_id)
            result[version_id] = (index_memo, compression_parent,
                                  parents, (method, noeol))
        return result

    def iter_parents(self, version_ids):
        """Iterate through the parents for many version ids.

        :param version_ids: An iterable yielding version_ids.
        :return: An iterator that yields (version_id, parents). Requested 
            version_ids not present in the versioned file are simply skipped.
            The order is undefined, allowing for different optimisations in
            the underlying implementation.
        """
        for version_id in version_ids:
            try:
                yield version_id, tuple(self.get_parents(version_id))
            except KeyError:
                pass

    def num_versions(self):
        return len(self._history)

    __len__ = num_versions

    def get_versions(self):
        """Get all the versions in the file. not topologically sorted."""
        return self._history

    def _version_list_to_index(self, versions):
        result_list = []
        cache = self._cache
        for version in versions:
            if version in cache:
                # -- inlined lookup() --
                result_list.append(str(cache[version][5]))
                # -- end lookup () --
            else:
                result_list.append('.' + version)
        return ' '.join(result_list)

    def add_version(self, version_id, options, index_memo, parents):
        """Add a version record to the index."""
        self.add_versions(((version_id, options, index_memo, parents),))

    def add_versions(self, versions, random_id=False):
        """Add multiple versions to the index.
        
        :param versions: a list of tuples:
                         (version_id, options, pos, size, parents).
        :param random_id: If True the ids being added were randomly generated
            and no check for existence will be performed.
        """
        lines = []
        orig_history = self._history[:]
        orig_cache = self._cache.copy()

        try:
            for version_id, options, (index, pos, size), parents in versions:
                line = "\n%s %s %s %s %s :" % (version_id,
                                               ','.join(options),
                                               pos,
                                               size,
                                               self._version_list_to_index(parents))
                assert isinstance(line, str), \
                    'content must be utf-8 encoded: %r' % (line,)
                lines.append(line)
                self._cache_version(version_id, options, pos, size, parents)
            if not self._need_to_create:
                self._transport.append_bytes(self._filename, ''.join(lines))
            else:
                sio = StringIO()
                sio.write(self.HEADER)
                sio.writelines(lines)
                sio.seek(0)
                self._transport.put_file_non_atomic(self._filename, sio,
                                    create_parent_dir=self._create_parent_dir,
                                    mode=self._file_mode,
                                    dir_mode=self._dir_mode)
                self._need_to_create = False
        except:
            # If any problems happen, restore the original values and re-raise
            self._history = orig_history
            self._cache = orig_cache
            raise

    def has_version(self, version_id):
        """True if the version is in the index."""
        return version_id in self._cache

    def get_position(self, version_id):
        """Return details needed to access the version.
        
        .kndx indices do not support split-out data, so return None for the 
        index field.

        :return: a tuple (None, data position, size) to hand to the access
            logic to get the record.
        """
        entry = self._cache[version_id]
        return None, entry[2], entry[3]

    def get_method(self, version_id):
        """Return compression method of specified version."""
        try:
            options = self._cache[version_id][1]
        except KeyError:
            raise RevisionNotPresent(version_id, self._filename)
        if 'fulltext' in options:
            return 'fulltext'
        else:
            if 'line-delta' not in options:
                raise errors.KnitIndexUnknownMethod(self._full_path(), options)
            return 'line-delta'

    def get_options(self, version_id):
        """Return a list representing options.

        e.g. ['foo', 'bar']
        """
        return self._cache[version_id][1]

    def get_parents(self, version_id):
        """Return parents of specified version ignoring ghosts."""
        return [parent for parent in self._cache[version_id][4] 
                if parent in self._cache]

    def get_parents_with_ghosts(self, version_id):
        """Return parents of specified version with ghosts."""
        return self._cache[version_id][4] 

    def check_versions_present(self, version_ids):
        """Check that all specified versions are present."""
        cache = self._cache
        for version_id in version_ids:
            if version_id not in cache:
                raise RevisionNotPresent(version_id, self._filename)


class KnitGraphIndex(object):
    """A knit index that builds on GraphIndex."""

    def __init__(self, graph_index, deltas=False, parents=True, add_callback=None):
        """Construct a KnitGraphIndex on a graph_index.

        :param graph_index: An implementation of bzrlib.index.GraphIndex.
        :param deltas: Allow delta-compressed records.
        :param add_callback: If not None, allow additions to the index and call
            this callback with a list of added GraphIndex nodes:
            [(node, value, node_refs), ...]
        :param parents: If True, record knits parents, if not do not record 
            parents.
        """
        self._graph_index = graph_index
        self._deltas = deltas
        self._add_callback = add_callback
        self._parents = parents
        if deltas and not parents:
            raise KnitCorrupt(self, "Cannot do delta compression without "
                "parent tracking.")

    def _get_entries(self, keys, check_present=False):
        """Get the entries for keys.
        
        :param keys: An iterable of index keys, - 1-tuples.
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

    def _present_keys(self, version_ids):
        return set([
            node[1] for node in self._get_entries(version_ids)])

    def _parentless_ancestry(self, versions):
        """Honour the get_ancestry API for parentless knit indices."""
        wanted_keys = self._version_ids_to_keys(versions)
        present_keys = self._present_keys(wanted_keys)
        missing = set(wanted_keys).difference(present_keys)
        if missing:
            raise RevisionNotPresent(missing.pop(), self)
        return list(self._keys_to_version_ids(present_keys))

    def get_ancestry(self, versions, topo_sorted=True):
        """See VersionedFile.get_ancestry."""
        if not self._parents:
            return self._parentless_ancestry(versions)
        # XXX: This will do len(history) index calls - perhaps
        # it should be altered to be a index core feature?
        # get a graph of all the mentioned versions:
        graph = {}
        ghosts = set()
        versions = self._version_ids_to_keys(versions)
        pending = set(versions)
        while pending:
            # get all pending nodes
            this_iteration = pending
            new_nodes = self._get_entries(this_iteration)
            found = set()
            pending = set()
            for (index, key, value, node_refs) in new_nodes:
                # dont ask for ghosties - otherwise
                # we we can end up looping with pending
                # being entirely ghosted.
                graph[key] = [parent for parent in node_refs[0]
                    if parent not in ghosts]
                # queue parents
                for parent in graph[key]:
                    # dont examine known nodes again
                    if parent in graph:
                        continue
                    pending.add(parent)
                found.add(key)
            ghosts.update(this_iteration.difference(found))
        if versions.difference(graph):
            raise RevisionNotPresent(versions.difference(graph).pop(), self)
        if topo_sorted:
            result_keys = topo_sort(graph.items())
        else:
            result_keys = graph.iterkeys()
        return [key[0] for key in result_keys]

    def get_ancestry_with_ghosts(self, versions):
        """See VersionedFile.get_ancestry."""
        if not self._parents:
            return self._parentless_ancestry(versions)
        # XXX: This will do len(history) index calls - perhaps
        # it should be altered to be a index core feature?
        # get a graph of all the mentioned versions:
        graph = {}
        versions = self._version_ids_to_keys(versions)
        pending = set(versions)
        while pending:
            # get all pending nodes
            this_iteration = pending
            new_nodes = self._get_entries(this_iteration)
            pending = set()
            for (index, key, value, node_refs) in new_nodes:
                graph[key] = node_refs[0]
                # queue parents 
                for parent in graph[key]:
                    # dont examine known nodes again
                    if parent in graph:
                        continue
                    pending.add(parent)
            missing_versions = this_iteration.difference(graph)
            missing_needed = versions.intersection(missing_versions)
            if missing_needed:
                raise RevisionNotPresent(missing_needed.pop(), self)
            for missing_version in missing_versions:
                # add a key, no parents
                graph[missing_version] = []
                pending.discard(missing_version) # don't look for it
        result_keys = topo_sort(graph.items())
        return [key[0] for key in result_keys]

    def get_build_details(self, version_ids):
        """Get the method, index_memo and compression parent for version_ids.

        Ghosts are omitted from the result.

        :param version_ids: An iterable of version_ids.
        :return: A dict of version_id:(index_memo, compression_parent,
                                       parents, record_details).
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
        result = {}
        entries = self._get_entries(self._version_ids_to_keys(version_ids), True)
        for entry in entries:
            version_id = self._keys_to_version_ids((entry[1],))[0]
            if not self._parents:
                parents = ()
            else:
                parents = self._keys_to_version_ids(entry[3][0])
            if not self._deltas:
                compression_parent = None
            else:
                compression_parent_key = self._compression_parent(entry)
                if compression_parent_key:
                    compression_parent = self._keys_to_version_ids(
                    (compression_parent_key,))[0]
                else:
                    compression_parent = None
            noeol = (entry[2][0] == 'N')
            if compression_parent:
                method = 'line-delta'
            else:
                method = 'fulltext'
            result[version_id] = (self._node_to_position(entry),
                                  compression_parent, parents,
                                  (method, noeol))
        return result

    def _compression_parent(self, an_entry):
        # return the key that an_entry is compressed against, or None
        # Grab the second parent list (as deltas implies parents currently)
        compression_parents = an_entry[3][1]
        if not compression_parents:
            return None
        assert len(compression_parents) == 1
        return compression_parents[0]

    def _get_method(self, node):
        if not self._deltas:
            return 'fulltext'
        if self._compression_parent(node):
            return 'line-delta'
        else:
            return 'fulltext'

    def get_graph(self):
        """Return a list of the node:parents lists from this knit index."""
        if not self._parents:
            return [(key, ()) for key in self.get_versions()]
        result = []
        for index, key, value, refs in self._graph_index.iter_all_entries():
            result.append((key[0], tuple([ref[0] for ref in refs[0]])))
        return result

    def iter_parents(self, version_ids):
        """Iterate through the parents for many version ids.

        :param version_ids: An iterable yielding version_ids.
        :return: An iterator that yields (version_id, parents). Requested 
            version_ids not present in the versioned file are simply skipped.
            The order is undefined, allowing for different optimisations in
            the underlying implementation.
        """
        if self._parents:
            all_nodes = set(self._get_entries(self._version_ids_to_keys(version_ids)))
            all_parents = set()
            present_parents = set()
            for node in all_nodes:
                all_parents.update(node[3][0])
                # any node we are querying must be present
                present_parents.add(node[1])
            unknown_parents = all_parents.difference(present_parents)
            present_parents.update(self._present_keys(unknown_parents))
            for node in all_nodes:
                parents = []
                for parent in node[3][0]:
                    if parent in present_parents:
                        parents.append(parent[0])
                yield node[1][0], tuple(parents)
        else:
            for node in self._get_entries(self._version_ids_to_keys(version_ids)):
                yield node[1][0], ()

    def num_versions(self):
        return len(list(self._graph_index.iter_all_entries()))

    __len__ = num_versions

    def get_versions(self):
        """Get all the versions in the file. not topologically sorted."""
        return [node[1][0] for node in self._graph_index.iter_all_entries()]
    
    def has_version(self, version_id):
        """True if the version is in the index."""
        return len(self._present_keys(self._version_ids_to_keys([version_id]))) == 1

    def _keys_to_version_ids(self, keys):
        return tuple(key[0] for key in keys)

    def get_position(self, version_id):
        """Return details needed to access the version.
        
        :return: a tuple (index, data position, size) to hand to the access
            logic to get the record.
        """
        node = self._get_node(version_id)
        return self._node_to_position(node)

    def _node_to_position(self, node):
        """Convert an index value to position details."""
        bits = node[2][1:].split(' ')
        return node[0], int(bits[0]), int(bits[1])

    def get_method(self, version_id):
        """Return compression method of specified version."""
        return self._get_method(self._get_node(version_id))

    def _get_node(self, version_id):
        try:
            return list(self._get_entries(self._version_ids_to_keys([version_id])))[0]
        except IndexError:
            raise RevisionNotPresent(version_id, self)

    def get_options(self, version_id):
        """Return a list representing options.

        e.g. ['foo', 'bar']
        """
        node = self._get_node(version_id)
        options = [self._get_method(node)]
        if node[2][0] == 'N':
            options.append('no-eol')
        return options

    def get_parents(self, version_id):
        """Return parents of specified version ignoring ghosts."""
        parents = list(self.iter_parents([version_id]))
        if not parents:
            # missing key
            raise errors.RevisionNotPresent(version_id, self)
        return parents[0][1]

    def get_parents_with_ghosts(self, version_id):
        """Return parents of specified version with ghosts."""
        nodes = list(self._get_entries(self._version_ids_to_keys([version_id]),
            check_present=True))
        if not self._parents:
            return ()
        return self._keys_to_version_ids(nodes[0][3][0])

    def check_versions_present(self, version_ids):
        """Check that all specified versions are present."""
        keys = self._version_ids_to_keys(version_ids)
        present = self._present_keys(keys)
        missing = keys.difference(present)
        if missing:
            raise RevisionNotPresent(missing.pop(), self)

    def add_version(self, version_id, options, access_memo, parents):
        """Add a version record to the index."""
        return self.add_versions(((version_id, options, access_memo, parents),))

    def add_versions(self, versions, random_id=False):
        """Add multiple versions to the index.
        
        This function does not insert data into the Immutable GraphIndex
        backing the KnitGraphIndex, instead it prepares data for insertion by
        the caller and checks that it is safe to insert then calls
        self._add_callback with the prepared GraphIndex nodes.

        :param versions: a list of tuples:
                         (version_id, options, pos, size, parents).
        :param random_id: If True the ids being added were randomly generated
            and no check for existence will be performed.
        """
        if not self._add_callback:
            raise errors.ReadOnlyError(self)
        # we hope there are no repositories with inconsistent parentage
        # anymore.
        # check for dups

        keys = {}
        for (version_id, options, access_memo, parents) in versions:
            index, pos, size = access_memo
            key = (version_id, )
            parents = tuple((parent, ) for parent in parents)
            if 'no-eol' in options:
                value = 'N'
            else:
                value = ' '
            value += "%d %d" % (pos, size)
            if not self._deltas:
                if 'line-delta' in options:
                    raise KnitCorrupt(self, "attempt to add line-delta in non-delta knit")
            if self._parents:
                if self._deltas:
                    if 'line-delta' in options:
                        node_refs = (parents, (parents[0],))
                    else:
                        node_refs = (parents, ())
                else:
                    node_refs = (parents, )
            else:
                if parents:
                    raise KnitCorrupt(self, "attempt to add node with parents "
                        "in parentless index.")
                node_refs = ()
            keys[key] = (value, node_refs)
        if not random_id:
            present_nodes = self._get_entries(keys)
            for (index, key, value, node_refs) in present_nodes:
                if (value, node_refs) != keys[key]:
                    raise KnitCorrupt(self, "inconsistent details in add_versions"
                        ": %s %s" % ((value, node_refs), keys[key]))
                del keys[key]
        result = []
        if self._parents:
            for key, (value, node_refs) in keys.iteritems():
                result.append((key, value, node_refs))
        else:
            for key, (value, node_refs) in keys.iteritems():
                result.append((key, value))
        self._add_callback(result)
        
    def _version_ids_to_keys(self, version_ids):
        return set((version_id, ) for version_id in version_ids)


class _KnitAccess(object):
    """Access to knit records in a .knit file."""

    def __init__(self, transport, filename, _file_mode, _dir_mode,
        _need_to_create, _create_parent_dir):
        """Create a _KnitAccess for accessing and inserting data.

        :param transport: The transport the .knit is located on.
        :param filename: The filename of the .knit.
        """
        self._transport = transport
        self._filename = filename
        self._file_mode = _file_mode
        self._dir_mode = _dir_mode
        self._need_to_create = _need_to_create
        self._create_parent_dir = _create_parent_dir

    def add_raw_records(self, sizes, raw_data):
        """Add raw knit bytes to a storage area.

        The data is spooled to whereever the access method is storing data.

        :param sizes: An iterable containing the size of each raw data segment.
        :param raw_data: A bytestring containing the data.
        :return: A list of memos to retrieve the record later. Each memo is a
            tuple - (index, pos, length), where the index field is always None
            for the .knit access method.
        """
        assert type(raw_data) == str, \
            'data must be plain bytes was %s' % type(raw_data)
        if not self._need_to_create:
            base = self._transport.append_bytes(self._filename, raw_data)
        else:
            self._transport.put_bytes_non_atomic(self._filename, raw_data,
                                   create_parent_dir=self._create_parent_dir,
                                   mode=self._file_mode,
                                   dir_mode=self._dir_mode)
            self._need_to_create = False
            base = 0
        result = []
        for size in sizes:
            result.append((None, base, size))
            base += size
        return result

    def create(self):
        """IFF this data access has its own storage area, initialise it.

        :return: None.
        """
        self._transport.put_bytes_non_atomic(self._filename, '',
                                             mode=self._file_mode)

    def open_file(self):
        """IFF this data access can be represented as a single file, open it.

        For knits that are not mapped to a single file on disk this will
        always return None.

        :return: None or a file handle.
        """
        try:
            return self._transport.get(self._filename)
        except NoSuchFile:
            pass
        return None

    def get_raw_records(self, memos_for_retrieval):
        """Get the raw bytes for a records.

        :param memos_for_retrieval: An iterable containing the (index, pos, 
            length) memo for retrieving the bytes. The .knit method ignores
            the index as there is always only a single file.
        :return: An iterator over the bytes of the records.
        """
        read_vector = [(pos, size) for (index, pos, size) in memos_for_retrieval]
        for pos, data in self._transport.readv(self._filename, read_vector):
            yield data


class _PackAccess(object):
    """Access to knit records via a collection of packs."""

    def __init__(self, index_to_packs, writer=None):
        """Create a _PackAccess object.

        :param index_to_packs: A dict mapping index objects to the transport
            and file names for obtaining data.
        :param writer: A tuple (pack.ContainerWriter, write_index) which
            contains the pack to write, and the index that reads from it will
            be associated with.
        """
        if writer:
            self.container_writer = writer[0]
            self.write_index = writer[1]
        else:
            self.container_writer = None
            self.write_index = None
        self.indices = index_to_packs

    def add_raw_records(self, sizes, raw_data):
        """Add raw knit bytes to a storage area.

        The data is spooled to the container writer in one bytes-record per
        raw data item.

        :param sizes: An iterable containing the size of each raw data segment.
        :param raw_data: A bytestring containing the data.
        :return: A list of memos to retrieve the record later. Each memo is a
            tuple - (index, pos, length), where the index field is the 
            write_index object supplied to the PackAccess object.
        """
        assert type(raw_data) == str, \
            'data must be plain bytes was %s' % type(raw_data)
        result = []
        offset = 0
        for size in sizes:
            p_offset, p_length = self.container_writer.add_bytes_record(
                raw_data[offset:offset+size], [])
            offset += size
            result.append((self.write_index, p_offset, p_length))
        return result

    def create(self):
        """Pack based knits do not get individually created."""

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
        for (index, offset, length) in memos_for_retrieval:
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
            transport, path = self.indices[index]
            reader = pack.make_readv_reader(transport, path, offsets)
            for names, read_func in reader.iter_records():
                yield read_func(None)

    def open_file(self):
        """Pack based knits have no single file."""
        return None

    def set_writer(self, writer, index, (transport, packname)):
        """Set a writer to use for adding data."""
        if index is not None:
            self.indices[index] = (transport, packname)
        self.container_writer = writer
        self.write_index = index


class _StreamAccess(object):
    """A Knit Access object that provides data from a datastream.
    
    It also provides a fallback to present as unannotated data, annotated data
    from a *backing* access object.

    This is triggered by a index_memo which is pointing to a different index
    than this was constructed with, and is used to allow extracting full
    unannotated texts for insertion into annotated knits.
    """

    def __init__(self, reader_callable, stream_index, backing_knit,
        orig_factory):
        """Create a _StreamAccess object.

        :param reader_callable: The reader_callable from the datastream.
            This is called to buffer all the data immediately, for 
            random access.
        :param stream_index: The index the data stream this provides access to
            which will be present in native index_memo's.
        :param backing_knit: The knit object that will provide access to 
            annotated texts which are not available in the stream, so as to
            create unannotated texts.
        :param orig_factory: The original content factory used to generate the
            stream. This is used for checking whether the thunk code for
            supporting _copy_texts will generate the correct form of data.
        """
        self.data = reader_callable(None)
        self.stream_index = stream_index
        self.backing_knit = backing_knit
        self.orig_factory = orig_factory

    def get_raw_records(self, memos_for_retrieval):
        """Get the raw bytes for a records.

        :param memos_for_retrieval: An iterable containing the (thunk_flag,
            index, start, end) memo for retrieving the bytes.
        :return: An iterator over the bytes of the records.
        """
        # use a generator for memory friendliness
        for thunk_flag, version_id, start, end in memos_for_retrieval:
            if version_id is self.stream_index:
                yield self.data[start:end]
                continue
            # we have been asked to thunk. This thunking only occurs when
            # we are obtaining plain texts from an annotated backing knit
            # so that _copy_texts will work.
            # We could improve performance here by scanning for where we need
            # to do this and using get_line_list, then interleaving the output
            # as desired. However, for now, this is sufficient.
            if self.orig_factory.__class__ != KnitPlainFactory:
                raise errors.KnitCorrupt(
                    self, 'Bad thunk request %r' % version_id)
            lines = self.backing_knit.get_lines(version_id)
            line_bytes = ''.join(lines)
            digest = sha_string(line_bytes)
            if lines:
                if lines[-1][-1] != '\n':
                    lines[-1] = lines[-1] + '\n'
                    line_bytes += '\n'
            orig_options = list(self.backing_knit._index.get_options(version_id))
            if 'fulltext' not in orig_options:
                if 'line-delta' not in orig_options:
                    raise errors.KnitCorrupt(self,
                        'Unknown compression method %r' % orig_options)
                orig_options.remove('line-delta')
                orig_options.append('fulltext')
            # We want plain data, because we expect to thunk only to allow text
            # extraction.
            size, bytes = self.backing_knit._data._record_to_data(version_id,
                digest, lines, line_bytes)
            yield bytes


class _StreamIndex(object):
    """A Knit Index object that uses the data map from a datastream."""

    def __init__(self, data_list, backing_index):
        """Create a _StreamIndex object.

        :param data_list: The data_list from the datastream.
        :param backing_index: The index which will supply values for nodes
            referenced outside of this stream.
        """
        self.data_list = data_list
        self.backing_index = backing_index
        self._by_version = {}
        pos = 0
        for key, options, length, parents in data_list:
            self._by_version[key] = options, (pos, pos + length), parents
            pos += length

    def get_ancestry(self, versions, topo_sorted):
        """Get an ancestry list for versions."""
        if topo_sorted:
            # Not needed for basic joins
            raise NotImplementedError(self.get_ancestry)
        # get a graph of all the mentioned versions:
        # Little ugly - basically copied from KnitIndex, but don't want to
        # accidentally incorporate too much of that index's code.
        ancestry = set()
        pending = set(versions)
        cache = self._by_version
        while pending:
            version = pending.pop()
            # trim ghosts
            try:
                parents = [p for p in cache[version][2] if p in cache]
            except KeyError:
                raise RevisionNotPresent(version, self)
            # if not completed and not a ghost
            pending.update([p for p in parents if p not in ancestry])
            ancestry.add(version)
        return list(ancestry)

    def get_build_details(self, version_ids):
        """Get the method, index_memo and compression parent for version_ids.

        Ghosts are omitted from the result.

        :param version_ids: An iterable of version_ids.
        :return: A dict of version_id:(index_memo, compression_parent,
                                       parents, record_details).
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
        result = {}
        for version_id in version_ids:
            try:
                method = self.get_method(version_id)
            except errors.RevisionNotPresent:
                # ghosts are omitted
                continue
            parent_ids = self.get_parents_with_ghosts(version_id)
            noeol = ('no-eol' in self.get_options(version_id))
            if method == 'fulltext':
                compression_parent = None
            else:
                compression_parent = parent_ids[0]
            index_memo = self.get_position(version_id)
            result[version_id] = (index_memo, compression_parent,
                                  parent_ids, (method, noeol))
        return result

    def get_method(self, version_id):
        """Return compression method of specified version."""
        try:
            options = self._by_version[version_id][0]
        except KeyError:
            # Strictly speaking this should check in the backing knit, but
            # until we have a test to discriminate, this will do.
            return self.backing_index.get_method(version_id)
        if 'fulltext' in options:
            return 'fulltext'
        elif 'line-delta' in options:
            return 'line-delta'
        else:
            raise errors.KnitIndexUnknownMethod(self, options)

    def get_options(self, version_id):
        """Return a list representing options.

        e.g. ['foo', 'bar']
        """
        try:
            return self._by_version[version_id][0]
        except KeyError:
            return self.backing_index.get_options(version_id)

    def get_parents_with_ghosts(self, version_id):
        """Return parents of specified version with ghosts."""
        try:
            return self._by_version[version_id][2]
        except KeyError:
            return self.backing_index.get_parents_with_ghosts(version_id)

    def get_position(self, version_id):
        """Return details needed to access the version.
        
        _StreamAccess has the data as a big array, so we return slice
        coordinates into that (as index_memo's are opaque outside the
        index and matching access class).

        :return: a tuple (thunk_flag, index, start, end).  If thunk_flag is
            False, index will be self, otherwise it will be a version id.
        """
        try:
            start, end = self._by_version[version_id][1]
            return False, self, start, end
        except KeyError:
            # Signal to the access object to handle this from the backing knit.
            return (True, version_id, None, None)

    def get_versions(self):
        """Get all the versions in the stream."""
        return self._by_version.keys()

    def iter_parents(self, version_ids):
        """Iterate through the parents for many version ids.

        :param version_ids: An iterable yielding version_ids.
        :return: An iterator that yields (version_id, parents). Requested 
            version_ids not present in the versioned file are simply skipped.
            The order is undefined, allowing for different optimisations in
            the underlying implementation.
        """
        result = []
        for version in version_ids:
            try:
                result.append((version, self._by_version[version][2]))
            except KeyError:
                pass
        return result


class _KnitData(object):
    """Manage extraction of data from a KnitAccess, caching and decompressing.
    
    The KnitData class provides the logic for parsing and using knit records,
    making use of an access method for the low level read and write operations.
    """

    def __init__(self, access):
        """Create a KnitData object.

        :param access: The access method to use. Access methods such as
            _KnitAccess manage the insertion of raw records and the subsequent
            retrieval of the same.
        """
        self._access = access
        self._checked = False
        # TODO: jam 20060713 conceptually, this could spill to disk
        #       if the cached size gets larger than a certain amount
        #       but it complicates the model a bit, so for now just use
        #       a simple dictionary
        self._cache = {}
        self._do_cache = False

    def enable_cache(self):
        """Enable caching of reads."""
        self._do_cache = True

    def clear_cache(self):
        """Clear the record cache."""
        self._do_cache = False
        self._cache = {}

    def _open_file(self):
        return self._access.open_file()

    def _record_to_data(self, version_id, digest, lines, dense_lines=None):
        """Convert version_id, digest, lines into a raw data block.
        
        :param dense_lines: The bytes of lines but in a denser form. For
            instance, if lines is a list of 1000 bytestrings each ending in \n,
            dense_lines may be a list with one line in it, containing all the
            1000's lines and their \n's. Using dense_lines if it is already
            known is a win because the string join to create bytes in this
            function spends less time resizing the final string.
        :return: (len, a StringIO instance with the raw data ready to read.)
        """
        # Note: using a string copy here increases memory pressure with e.g.
        # ISO's, but it is about 3 seconds faster on a 1.2Ghz intel machine
        # when doing the initial commit of a mozilla tree. RBC 20070921
        bytes = ''.join(chain(
            ["version %s %d %s\n" % (version_id,
                                     len(lines),
                                     digest)],
            dense_lines or lines,
            ["end %s\n" % version_id]))
        assert bytes.__class__ == str
        compressed_bytes = bytes_to_gzip(bytes)
        return len(compressed_bytes), compressed_bytes

    def add_raw_records(self, sizes, raw_data):
        """Append a prepared record to the data file.
        
        :param sizes: An iterable containing the size of each raw data segment.
        :param raw_data: A bytestring containing the data.
        :return: a list of index data for the way the data was stored.
            See the access method add_raw_records documentation for more
            details.
        """
        return self._access.add_raw_records(sizes, raw_data)
        
    def _parse_record_header(self, version_id, raw_data):
        """Parse a record header for consistency.

        :return: the header and the decompressor stream.
                 as (stream, header_record)
        """
        df = GzipFile(mode='rb', fileobj=StringIO(raw_data))
        try:
            rec = self._check_header(version_id, df.readline())
        except Exception, e:
            raise KnitCorrupt(self._access,
                              "While reading {%s} got %s(%s)"
                              % (version_id, e.__class__.__name__, str(e)))
        return df, rec

    def _check_header(self, version_id, line):
        rec = line.split()
        if len(rec) != 4:
            raise KnitCorrupt(self._access,
                              'unexpected number of elements in record header')
        if rec[1] != version_id:
            raise KnitCorrupt(self._access,
                              'unexpected version, wanted %r, got %r'
                              % (version_id, rec[1]))
        return rec

    def _parse_record(self, version_id, data):
        # profiling notes:
        # 4168 calls in 2880 217 internal
        # 4168 calls to _parse_record_header in 2121
        # 4168 calls to readlines in 330
        df = GzipFile(mode='rb', fileobj=StringIO(data))

        try:
            record_contents = df.readlines()
        except Exception, e:
            raise KnitCorrupt(self._access,
                              "While reading {%s} got %s(%s)"
                              % (version_id, e.__class__.__name__, str(e)))
        header = record_contents.pop(0)
        rec = self._check_header(version_id, header)

        last_line = record_contents.pop()
        if len(record_contents) != int(rec[2]):
            raise KnitCorrupt(self._access,
                              'incorrect number of lines %s != %s'
                              ' for version {%s}'
                              % (len(record_contents), int(rec[2]),
                                 version_id))
        if last_line != 'end %s\n' % rec[1]:
            raise KnitCorrupt(self._access,
                              'unexpected version end line %r, wanted %r' 
                              % (last_line, version_id))
        df.close()
        return record_contents, rec[3]

    def read_records_iter_raw(self, records):
        """Read text records from data file and yield raw data.

        This unpacks enough of the text record to validate the id is
        as expected but thats all.
        """
        # setup an iterator of the external records:
        # uses readv so nice and fast we hope.
        if len(records):
            # grab the disk data needed.
            if self._cache:
                # Don't check _cache if it is empty
                needed_offsets = [index_memo for version_id, index_memo
                                              in records
                                              if version_id not in self._cache]
            else:
                needed_offsets = [index_memo for version_id, index_memo
                                               in records]

            raw_records = self._access.get_raw_records(needed_offsets)

        for version_id, index_memo in records:
            if version_id in self._cache:
                # This data has already been validated
                data = self._cache[version_id]
            else:
                data = raw_records.next()
                if self._do_cache:
                    self._cache[version_id] = data

                # validate the header
                df, rec = self._parse_record_header(version_id, data)
                df.close()
            yield version_id, data

    def read_records_iter(self, records):
        """Read text records from data file and yield result.

        The result will be returned in whatever is the fastest to read.
        Not by the order requested. Also, multiple requests for the same
        record will only yield 1 response.
        :param records: A list of (version_id, pos, len) entries
        :return: Yields (version_id, contents, digest) in the order
                 read, not the order requested
        """
        if not records:
            return

        if self._cache:
            # Skip records we have alread seen
            yielded_records = set()
            needed_records = set()
            for record in records:
                if record[0] in self._cache:
                    if record[0] in yielded_records:
                        continue
                    yielded_records.add(record[0])
                    data = self._cache[record[0]]
                    content, digest = self._parse_record(record[0], data)
                    yield (record[0], content, digest)
                else:
                    needed_records.add(record)
            needed_records = sorted(needed_records, key=operator.itemgetter(1))
        else:
            needed_records = sorted(set(records), key=operator.itemgetter(1))

        if not needed_records:
            return

        # The transport optimizes the fetching as well 
        # (ie, reads continuous ranges.)
        raw_data = self._access.get_raw_records(
            [index_memo for version_id, index_memo in needed_records])

        for (version_id, index_memo), data in \
                izip(iter(needed_records), raw_data):
            content, digest = self._parse_record(version_id, data)
            if self._do_cache:
                self._cache[version_id] = data
            yield version_id, content, digest

    def read_records(self, records):
        """Read records into a dictionary."""
        components = {}
        for record_id, content, digest in \
                self.read_records_iter(records):
            components[record_id] = (content, digest)
        return components


class InterKnit(InterVersionedFile):
    """Optimised code paths for knit to knit operations."""
    
    _matching_file_from_factory = KnitVersionedFile
    _matching_file_to_factory = KnitVersionedFile
    
    @staticmethod
    def is_compatible(source, target):
        """Be compatible with knits.  """
        try:
            return (isinstance(source, KnitVersionedFile) and
                    isinstance(target, KnitVersionedFile))
        except AttributeError:
            return False

    def _copy_texts(self, pb, msg, version_ids, ignore_missing=False):
        """Copy texts to the target by extracting and adding them one by one.

        see join() for the parameter definitions.
        """
        version_ids = self._get_source_version_ids(version_ids, ignore_missing)
        graph = self.source.get_graph(version_ids)
        order = topo_sort(graph.items())

        def size_of_content(content):
            return sum(len(line) for line in content.text())
        # Cache at most 10MB of parent texts
        parent_cache = lru_cache.LRUSizeCache(max_size=10*1024*1024,
                                              compute_size=size_of_content)
        # TODO: jam 20071116 It would be nice to have a streaming interface to
        #       get multiple texts from a source. The source could be smarter
        #       about how it handled intermediate stages.
        #       get_line_list() or make_mpdiffs() seem like a possibility, but
        #       at the moment they extract all full texts into memory, which
        #       causes us to store more than our 3x fulltext goal.
        #       Repository.iter_files_bytes() may be another possibility
        to_process = [version for version in order
                               if version not in self.target]
        total = len(to_process)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for index, version in enumerate(to_process):
                pb.update('Converting versioned data', index, total)
                sha1, num_bytes, parent_text = self.target.add_lines(version,
                    self.source.get_parents_with_ghosts(version),
                    self.source.get_lines(version),
                    parent_texts=parent_cache)
                parent_cache[version] = parent_text
        finally:
            pb.finished()
        return total

    def join(self, pb=None, msg=None, version_ids=None, ignore_missing=False):
        """See InterVersionedFile.join."""
        assert isinstance(self.source, KnitVersionedFile)
        assert isinstance(self.target, KnitVersionedFile)

        # If the source and target are mismatched w.r.t. annotations vs
        # plain, the data needs to be converted accordingly
        if self.source.factory.annotated == self.target.factory.annotated:
            converter = None
        elif self.source.factory.annotated:
            converter = self._anno_to_plain_converter
        else:
            # We're converting from a plain to an annotated knit. Copy them
            # across by full texts.
            return self._copy_texts(pb, msg, version_ids, ignore_missing)

        version_ids = self._get_source_version_ids(version_ids, ignore_missing)
        if not version_ids:
            return 0

        pb = ui.ui_factory.nested_progress_bar()
        try:
            version_ids = list(version_ids)
            if None in version_ids:
                version_ids.remove(None)
    
            self.source_ancestry = set(self.source.get_ancestry(version_ids,
                topo_sorted=False))
            this_versions = set(self.target._index.get_versions())
            # XXX: For efficiency we should not look at the whole index,
            #      we only need to consider the referenced revisions - they
            #      must all be present, or the method must be full-text.
            #      TODO, RBC 20070919
            needed_versions = self.source_ancestry - this_versions
    
            if not needed_versions:
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
                    # otherwise we don't care
                    assert (self.target.has_version(parent) or
                            parent in copy_set or
                            not self.source.has_version(parent))
                index_memo = self.source._index.get_position(version_id)
                copy_queue_records.append((version_id, index_memo))
                copy_queue.append((version_id, options, parents))
                copy_set.add(version_id)

            # data suck the join:
            count = 0
            total = len(version_list)
            raw_datum = []
            raw_records = []
            for (version_id, raw_data), \
                (version_id2, options, parents) in \
                izip(self.source._data.read_records_iter_raw(copy_queue_records),
                     copy_queue):
                assert version_id == version_id2, 'logic error, inconsistent results'
                count = count + 1
                pb.update("Joining knit", count, total)
                if converter:
                    size, raw_data = converter(raw_data, version_id, options,
                        parents)
                else:
                    size = len(raw_data)
                raw_records.append((version_id, options, parents, size))
                raw_datum.append(raw_data)
            self.target._add_raw_records(raw_records, ''.join(raw_datum))
            return count
        finally:
            pb.finished()

    def _anno_to_plain_converter(self, raw_data, version_id, options,
                                 parents):
        """Convert annotated content to plain content."""
        data, digest = self.source._data._parse_record(version_id, raw_data)
        if 'fulltext' in options:
            content = self.source.factory.parse_fulltext(data, version_id)
            lines = self.target.factory.lower_fulltext(content)
        else:
            delta = self.source.factory.parse_line_delta(data, version_id,
                plain=True)
            lines = self.target.factory.lower_line_delta(delta)
        return self.target._data._record_to_data(version_id, digest, lines)


InterVersionedFile.register_optimiser(InterKnit)


class WeaveToKnit(InterVersionedFile):
    """Optimised code paths for weave to knit operations."""
    
    _matching_file_from_factory = bzrlib.weave.WeaveFile
    _matching_file_to_factory = KnitVersionedFile
    
    @staticmethod
    def is_compatible(source, target):
        """Be compatible with weaves to knits."""
        try:
            return (isinstance(source, bzrlib.weave.Weave) and
                    isinstance(target, KnitVersionedFile))
        except AttributeError:
            return False

    def join(self, pb=None, msg=None, version_ids=None, ignore_missing=False):
        """See InterVersionedFile.join."""
        assert isinstance(self.source, bzrlib.weave.Weave)
        assert isinstance(self.target, KnitVersionedFile)

        version_ids = self._get_source_version_ids(version_ids, ignore_missing)

        if not version_ids:
            return 0

        pb = ui.ui_factory.nested_progress_bar()
        try:
            version_ids = list(version_ids)
    
            self.source_ancestry = set(self.source.get_ancestry(version_ids))
            this_versions = set(self.target._index.get_versions())
            needed_versions = self.source_ancestry - this_versions
    
            if not needed_versions:
                return 0
            full_list = topo_sort(self.source.get_graph())
    
            version_list = [i for i in full_list if (not self.target.has_version(i)
                            and i in needed_versions)]
    
            # do the join:
            count = 0
            total = len(version_list)
            for version_id in version_list:
                pb.update("Converting to knit", count, total)
                parents = self.source.get_parents(version_id)
                # check that its will be a consistent copy:
                for parent in parents:
                    # if source has the parent, we must already have it
                    assert (self.target.has_version(parent))
                self.target.add_lines(
                    version_id, parents, self.source.get_lines(version_id))
                count = count + 1
            return count
        finally:
            pb.finished()


InterVersionedFile.register_optimiser(WeaveToKnit)


# Deprecated, use PatienceSequenceMatcher instead
KnitSequenceMatcher = patiencediff.PatienceSequenceMatcher


def annotate_knit(knit, revision_id):
    """Annotate a knit with no cached annotations.

    This implementation is for knits with no cached annotations.
    It will work for knits with cached annotations, but this is not
    recommended.
    """
    annotator = _KnitAnnotator(knit)
    return iter(annotator.annotate(revision_id))


class _KnitAnnotator(object):
    """Build up the annotations for a text."""

    def __init__(self, knit):
        self._knit = knit

        # Content objects, differs from fulltexts because of how final newlines
        # are treated by knits. the content objects here will always have a
        # final newline
        self._fulltext_contents = {}

        # Annotated lines of specific revisions
        self._annotated_lines = {}

        # Track the raw data for nodes that we could not process yet.
        # This maps the revision_id of the base to a list of children that will
        # annotated from it.
        self._pending_children = {}

        # Nodes which cannot be extracted
        self._ghosts = set()

        # Track how many children this node has, so we know if we need to keep
        # it
        self._annotate_children = {}
        self._compression_children = {}

        self._all_build_details = {}
        # The children => parent revision_id graph
        self._revision_id_graph = {}

        self._heads_provider = None

        self._nodes_to_keep_annotations = set()
        self._generations_until_keep = 100

    def set_generations_until_keep(self, value):
        """Set the number of generations before caching a node.

        Setting this to -1 will cache every merge node, setting this higher
        will cache fewer nodes.
        """
        self._generations_until_keep = value

    def _add_fulltext_content(self, revision_id, content_obj):
        self._fulltext_contents[revision_id] = content_obj
        # TODO: jam 20080305 It might be good to check the sha1digest here
        return content_obj.text()

    def _check_parents(self, child, nodes_to_annotate):
        """Check if all parents have been processed.

        :param child: A tuple of (rev_id, parents, raw_content)
        :param nodes_to_annotate: If child is ready, add it to
            nodes_to_annotate, otherwise put it back in self._pending_children
        """
        for parent_id in child[1]:
            if (parent_id not in self._annotated_lines):
                # This parent is present, but another parent is missing
                self._pending_children.setdefault(parent_id,
                                                  []).append(child)
                break
        else:
            # This one is ready to be processed
            nodes_to_annotate.append(child)

    def _add_annotation(self, revision_id, fulltext, parent_ids,
                        left_matching_blocks=None):
        """Add an annotation entry.

        All parents should already have been annotated.
        :return: A list of children that now have their parents satisfied.
        """
        a = self._annotated_lines
        annotated_parent_lines = [a[p] for p in parent_ids]
        annotated_lines = list(annotate.reannotate(annotated_parent_lines,
            fulltext, revision_id, left_matching_blocks,
            heads_provider=self._get_heads_provider()))
        self._annotated_lines[revision_id] = annotated_lines
        for p in parent_ids:
            ann_children = self._annotate_children[p]
            ann_children.remove(revision_id)
            if (not ann_children
                and p not in self._nodes_to_keep_annotations):
                del self._annotated_lines[p]
                del self._all_build_details[p]
                if p in self._fulltext_contents:
                    del self._fulltext_contents[p]
        # Now that we've added this one, see if there are any pending
        # deltas to be done, certainly this parent is finished
        nodes_to_annotate = []
        for child in self._pending_children.pop(revision_id, []):
            self._check_parents(child, nodes_to_annotate)
        return nodes_to_annotate

    def _get_build_graph(self, revision_id):
        """Get the graphs for building texts and annotations.

        The data you need for creating a full text may be different than the
        data you need to annotate that text. (At a minimum, you need both
        parents to create an annotation, but only need 1 parent to generate the
        fulltext.)

        :return: A list of (revision_id, index_memo) records, suitable for
            passing to read_records_iter to start reading in the raw data fro/
            the pack file.
        """
        if revision_id in self._annotated_lines:
            # Nothing to do
            return []
        pending = set([revision_id])
        records = []
        generation = 0
        kept_generation = 0
        while pending:
            # get all pending nodes
            generation += 1
            this_iteration = pending
            build_details = self._knit._index.get_build_details(this_iteration)
            self._all_build_details.update(build_details)
            # new_nodes = self._knit._index._get_entries(this_iteration)
            pending = set()
            for rev_id, details in build_details.iteritems():
                (index_memo, compression_parent, parents,
                 record_details) = details
                self._revision_id_graph[rev_id] = parents
                records.append((rev_id, index_memo))
                # Do we actually need to check _annotated_lines?
                pending.update(p for p in parents
                                 if p not in self._all_build_details)
                if compression_parent:
                    self._compression_children.setdefault(compression_parent,
                        []).append(rev_id)
                if parents:
                    for parent in parents:
                        self._annotate_children.setdefault(parent,
                            []).append(rev_id)
                    num_gens = generation - kept_generation
                    if ((num_gens >= self._generations_until_keep)
                        and len(parents) > 1):
                        kept_generation = generation
                        self._nodes_to_keep_annotations.add(rev_id)

            missing_versions = this_iteration.difference(build_details.keys())
            self._ghosts.update(missing_versions)
            for missing_version in missing_versions:
                # add a key, no parents
                self._revision_id_graph[missing_version] = ()
                pending.discard(missing_version) # don't look for it
        # XXX: This should probably be a real exception, as it is a data
        #      inconsistency
        assert not self._ghosts.intersection(self._compression_children), \
            "We cannot have nodes which have a compression parent of a ghost."
        # Cleanout anything that depends on a ghost so that we don't wait for
        # the ghost to show up
        for node in self._ghosts:
            if node in self._annotate_children:
                # We won't be building this node
                del self._annotate_children[node]
        # Generally we will want to read the records in reverse order, because
        # we find the parent nodes after the children
        records.reverse()
        return records

    def _annotate_records(self, records):
        """Build the annotations for the listed records."""
        # We iterate in the order read, rather than a strict order requested
        # However, process what we can, and put off to the side things that
        # still need parents, cleaning them up when those parents are
        # processed.
        for (rev_id, record,
             digest) in self._knit._data.read_records_iter(records):
            if rev_id in self._annotated_lines:
                continue
            parent_ids = self._revision_id_graph[rev_id]
            parent_ids = [p for p in parent_ids if p not in self._ghosts]
            details = self._all_build_details[rev_id]
            (index_memo, compression_parent, parents,
             record_details) = details
            nodes_to_annotate = []
            # TODO: Remove the punning between compression parents, and
            #       parent_ids, we should be able to do this without assuming
            #       the build order
            if len(parent_ids) == 0:
                # There are no parents for this node, so just add it
                # TODO: This probably needs to be decoupled
                assert compression_parent is None
                fulltext_content, delta = self._knit.factory.parse_record(
                    rev_id, record, record_details, None)
                fulltext = self._add_fulltext_content(rev_id, fulltext_content)
                nodes_to_annotate.extend(self._add_annotation(rev_id, fulltext,
                    parent_ids, left_matching_blocks=None))
            else:
                child = (rev_id, parent_ids, record)
                # Check if all the parents are present
                self._check_parents(child, nodes_to_annotate)
            while nodes_to_annotate:
                # Should we use a queue here instead of a stack?
                (rev_id, parent_ids, record) = nodes_to_annotate.pop()
                (index_memo, compression_parent, parents,
                 record_details) = self._all_build_details[rev_id]
                if compression_parent is not None:
                    comp_children = self._compression_children[compression_parent]
                    assert rev_id in comp_children
                    # If there is only 1 child, it is safe to reuse this
                    # content
                    reuse_content = (len(comp_children) == 1
                        and compression_parent not in
                            self._nodes_to_keep_annotations)
                    if reuse_content:
                        # Remove it from the cache since it will be changing
                        parent_fulltext_content = self._fulltext_contents.pop(compression_parent)
                        # Make sure to copy the fulltext since it might be
                        # modified
                        parent_fulltext = list(parent_fulltext_content.text())
                    else:
                        parent_fulltext_content = self._fulltext_contents[compression_parent]
                        parent_fulltext = parent_fulltext_content.text()
                    comp_children.remove(rev_id)
                    fulltext_content, delta = self._knit.factory.parse_record(
                        rev_id, record, record_details,
                        parent_fulltext_content,
                        copy_base_content=(not reuse_content))
                    fulltext = self._add_fulltext_content(rev_id,
                                                          fulltext_content)
                    blocks = KnitContent.get_line_delta_blocks(delta,
                            parent_fulltext, fulltext)
                else:
                    fulltext_content = self._knit.factory.parse_fulltext(
                        record, rev_id)
                    fulltext = self._add_fulltext_content(rev_id,
                        fulltext_content)
                    blocks = None
                nodes_to_annotate.extend(
                    self._add_annotation(rev_id, fulltext, parent_ids,
                                     left_matching_blocks=blocks))

    def _get_heads_provider(self):
        """Create a heads provider for resolving ancestry issues."""
        if self._heads_provider is not None:
            return self._heads_provider
        parent_provider = _mod_graph.DictParentsProvider(
            self._revision_id_graph)
        graph_obj = _mod_graph.Graph(parent_provider)
        head_cache = _mod_graph.FrozenHeadsCache(graph_obj)
        self._heads_provider = head_cache
        return head_cache

    def annotate(self, revision_id):
        """Return the annotated fulltext at the given revision.

        :param revision_id: The revision id for this file
        """
        records = self._get_build_graph(revision_id)
        if revision_id in self._ghosts:
            raise errors.RevisionNotPresent(revision_id, self._knit)
        self._annotate_records(records)
        return self._annotated_lines[revision_id]


try:
    from bzrlib._knit_load_data_c import _load_data_c as _load_data
except ImportError:
    from bzrlib._knit_load_data_py import _load_data_py as _load_data
