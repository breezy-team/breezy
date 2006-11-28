# Copyright (C) 2005, 2006 Canonical Ltd
# Written by Martin Pool.
# Modified by Johan Rydberg <jrydberg@gnu.org>
# Modified by Robert Collins <robert.collins@canonical.com>
# Modified by Aaron Bentley <aaron.bentley@utoronto.ca>
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
from itertools import izip, chain
import operator
import os
import sys
import warnings

import bzrlib
from bzrlib import (
    cache_utf8,
    errors,
    patiencediff,
    progress,
    )
from bzrlib.errors import FileExists, NoSuchFile, KnitError, \
        InvalidRevisionId, KnitCorrupt, KnitHeaderError, \
        RevisionNotPresent, RevisionAlreadyPresent
from bzrlib.tuned_gzip import GzipFile
from bzrlib.trace import mutter
from bzrlib.osutils import contains_whitespace, contains_linebreaks, \
     sha_strings
from bzrlib.symbol_versioning import DEPRECATED_PARAMETER, deprecated_passed
from bzrlib.tsort import topo_sort
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

    def __init__(self, lines):
        self._lines = lines

    def annotate_iter(self):
        """Yield tuples of (origin, text) for each content line."""
        for origin, text in self._lines:
            yield origin, text

    def annotate(self):
        """Return a list of (origin, text) tuples."""
        return list(self.annotate_iter())

    def line_delta_iter(self, new_lines):
        """Generate line-based delta from this content to new_lines."""
        new_texts = [text for origin, text in new_lines._lines]
        old_texts = [text for origin, text in self._lines]
        s = KnitSequenceMatcher(None, old_texts, new_texts)
        for op in s.get_opcodes():
            if op[0] == 'equal':
                continue
            #     ofrom   oto   length        data
            yield (op[1], op[2], op[4]-op[3], new_lines._lines[op[3]:op[4]])

    def line_delta(self, new_lines):
        return list(self.line_delta_iter(new_lines))

    def text(self):
        return [text for origin, text in self._lines]

    def copy(self):
        return KnitContent(self._lines[:])


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
        decode_utf8 = cache_utf8.decode
        lines = []
        for line in content:
            origin, text = line.split(' ', 1)
            lines.append((decode_utf8(origin), text))
        return KnitContent(lines)

    def parse_line_delta_iter(self, lines):
        for result_item in self.parse_line_delta[lines]:
            yield result_item

    def parse_line_delta(self, lines, version):
        """Convert a line based delta into internal representation.

        line delta is in the form of:
        intstart intend intcount
        1..count lines:
        revid(utf8) newline\n
        internal representation is
        (start, end, count, [1..count tuples (revid, newline)])
        """
        decode_utf8 = cache_utf8.decode
        result = []
        lines = iter(lines)
        next = lines.next
        # walk through the lines parsing.
        for header in lines:
            start, end, count = [int(n) for n in header.split(',')]
            contents = []
            remaining = count
            while remaining:
                origin, text = next().split(' ', 1)
                remaining -= 1
                contents.append((decode_utf8(origin), text))
            result.append((start, end, count, contents))
        return result

    def lower_fulltext(self, content):
        """convert a fulltext content record into a serializable form.

        see parse_fulltext which this inverts.
        """
        encode_utf8 = cache_utf8.encode
        return ['%s %s' % (encode_utf8(o), t) for o, t in content._lines]

    def lower_line_delta(self, delta):
        """convert a delta into a serializable form.

        See parse_line_delta which this inverts.
        """
        encode_utf8 = cache_utf8.encode
        out = []
        for start, end, c, lines in delta:
            out.append('%d,%d,%d\n' % (start, end, c))
            out.extend(encode_utf8(origin) + ' ' + text
                       for origin, text in lines)
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

    def __init__(self, relpath, transport, file_mode=None, access_mode=None,
                 factory=None, basis_knit=DEPRECATED_PARAMETER, delta=True,
                 create=False, create_parent_dir=False, delay_create=False,
                 dir_mode=None):
        """Construct a knit at location specified by relpath.
        
        :param create: If not True, only open an existing knit.
        :param create_parent_dir: If True, create the parent directory if 
            creating the file fails. (This is used for stores with 
            hash-prefixes that may not exist yet)
        :param delay_create: The calling code is aware that the knit won't 
            actually be created until the first data is stored.
        """
        if deprecated_passed(basis_knit):
            warnings.warn("KnitVersionedFile.__(): The basis_knit parameter is"
                 " deprecated as of bzr 0.9.",
                 DeprecationWarning, stacklevel=2)
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

        self._index = _KnitIndex(transport, relpath + INDEX_SUFFIX,
            access_mode, create=create, file_mode=file_mode,
            create_parent_dir=create_parent_dir, delay_create=delay_create,
            dir_mode=dir_mode)
        self._data = _KnitData(transport, relpath + DATA_SUFFIX,
            access_mode, create=create and not len(self), file_mode=file_mode,
            create_parent_dir=create_parent_dir, delay_create=delay_create,
            dir_mode=dir_mode)

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
            pos, size = self._index.get_position(parent)
            if method == 'fulltext':
                fulltext_size = size
                break
            delta_size += size
            delta_parents = self._index.get_parents(parent)
        else:
            # We couldn't find a fulltext, so we must create a new one
            return False

        return fulltext_size > delta_size

    def _add_delta(self, version_id, parents, delta_parent, sha1, noeol, delta):
        """See VersionedFile._add_delta()."""
        self._check_add(version_id, []) # should we check the lines ?
        self._check_versions_present(parents)
        present_parents = []
        ghosts = []
        parent_texts = {}
        for parent in parents:
            if not self.has_version(parent):
                ghosts.append(parent)
            else:
                present_parents.append(parent)

        if delta_parent is None:
            # reconstitute as full text.
            assert len(delta) == 1 or len(delta) == 0
            if len(delta):
                assert delta[0][0] == 0
                assert delta[0][1] == 0, delta[0][1]
            return super(KnitVersionedFile, self)._add_delta(version_id,
                                                             parents,
                                                             delta_parent,
                                                             sha1,
                                                             noeol,
                                                             delta)

        digest = sha1

        options = []
        if noeol:
            options.append('no-eol')

        if delta_parent is not None:
            # determine the current delta chain length.
            # To speed the extract of texts the delta chain is limited
            # to a fixed number of deltas.  This should minimize both
            # I/O and the time spend applying deltas.
            # The window was changed to a maximum of 200 deltas, but also added
            # was a check that the total compressed size of the deltas is
            # smaller than the compressed size of the fulltext.
            if not self._check_should_delta([delta_parent]):
                # We don't want a delta here, just do a normal insertion.
                return super(KnitVersionedFile, self)._add_delta(version_id,
                                                                 parents,
                                                                 delta_parent,
                                                                 sha1,
                                                                 noeol,
                                                                 delta)

        options.append('line-delta')
        store_lines = self.factory.lower_line_delta(delta)

        where, size = self._data.add_record(version_id, digest, store_lines)
        self._index.add_version(version_id, options, where, size, parents)

    def _add_raw_records(self, records, data):
        """Add all the records 'records' with data pre-joined in 'data'.

        :param records: A list of tuples(version_id, options, parents, size).
        :param data: The data for the records. When it is written, the records
                     are adjusted to have pos pointing into data by the sum of
                     the preceding records sizes.
        """
        # write all the data
        pos = self._data.add_raw_record(data)
        offset = 0
        index_entries = []
        for (version_id, options, parents, size) in records:
            index_entries.append((version_id, options, pos+offset,
                                  size, parents))
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

    def get_delta(self, version_id):
        """Get a delta for constructing version from some other version."""
        if not self.has_version(version_id):
            raise RevisionNotPresent(version_id, self.filename)
        
        parents = self.get_parents(version_id)
        if len(parents):
            parent = parents[0]
        else:
            parent = None
        data_pos, data_size = self._index.get_position(version_id)
        data, sha1 = self._data.read_records(((version_id, data_pos, data_size),))[version_id]
        version_idx = self._index.lookup(version_id)
        noeol = 'no-eol' in self._index.get_options(version_id)
        if 'fulltext' == self._index.get_method(version_id):
            new_content = self.factory.parse_fulltext(data, version_idx)
            if parent is not None:
                reference_content = self._get_content(parent)
                old_texts = reference_content.text()
            else:
                old_texts = []
            new_texts = new_content.text()
            delta_seq = KnitSequenceMatcher(None, old_texts, new_texts)
            return parent, sha1, noeol, self._make_line_delta(delta_seq, new_content)
        else:
            delta = self.factory.parse_line_delta(data, version_idx)
            return parent, sha1, noeol, delta
        
    def get_graph_with_ghosts(self):
        """See VersionedFile.get_graph_with_ghosts()."""
        graph_items = self._index.get_graph()
        return dict(graph_items)

    def get_sha1(self, version_id):
        """See VersionedFile.get_sha1()."""
        record_map = self._get_record_map([version_id])
        method, content, digest, next = record_map[version_id]
        return digest 

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

    def _merge_annotations(self, content, parents, parent_texts={},
                           delta=None, annotated=None):
        """Merge annotations for content.  This is done by comparing
        the annotations based on changed to the text.
        """
        if annotated:
            delta_seq = None
            for parent_id in parents:
                merge_content = self._get_content(parent_id, parent_texts)
                seq = patiencediff.PatienceSequenceMatcher(
                                   None, merge_content.text(), content.text())
                if delta_seq is None:
                    # setup a delta seq to reuse.
                    delta_seq = seq
                for i, j, n in seq.get_matching_blocks():
                    if n == 0:
                        continue
                    # this appears to copy (origin, text) pairs across to the new
                    # content for any line that matches the last-checked parent.
                    # FIXME: save the sequence control data for delta compression
                    # against the most relevant parent rather than rediffing.
                    content._lines[j:j+n] = merge_content._lines[i:i+n]
        if delta:
            if not annotated:
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

        A dict of version_id to (method, data_pos, data_size, next) is
        returned.
        method is the way referenced data should be applied.
        data_pos is the position of the data in the knit.
        data_size is the size of the data in the knit.
        next is the build-parent of the version, or None for fulltexts.
        """
        component_data = {}
        for version_id in version_ids:
            cursor = version_id

            while cursor is not None and cursor not in component_data:
                method = self._index.get_method(cursor)
                if method == 'fulltext':
                    next = None
                else:
                    next = self.get_parents(cursor)[0]
                data_pos, data_size = self._index.get_position(cursor)
                component_data[cursor] = (method, data_pos, data_size, next)
                cursor = next
        return component_data
       
    def _get_content(self, version_id, parent_texts={}):
        """Returns a content object that makes up the specified
        version."""
        if not self.has_version(version_id):
            raise RevisionNotPresent(version_id, self.filename)

        cached_version = parent_texts.get(version_id, None)
        if cached_version is not None:
            return cached_version

        text_map, contents_map = self._get_content_maps([version_id])
        return contents_map[version_id]

    def _check_versions_present(self, version_ids):
        """Check that all specified versions are present."""
        version_ids = set(version_ids)
        for r in list(version_ids):
            if self._index.has_version(r):
                version_ids.remove(r)
        if version_ids:
            raise RevisionNotPresent(list(version_ids)[0], self.filename)

    def _add_lines_with_ghosts(self, version_id, parents, lines, parent_texts):
        """See VersionedFile.add_lines_with_ghosts()."""
        self._check_add(version_id, lines)
        return self._add(version_id, lines[:], parents, self.delta, parent_texts)

    def _add_lines(self, version_id, parents, lines, parent_texts):
        """See VersionedFile.add_lines."""
        self._check_add(version_id, lines)
        self._check_versions_present(parents)
        return self._add(version_id, lines[:], parents, self.delta, parent_texts)

    def _check_add(self, version_id, lines):
        """check that version_id and lines are safe to add."""
        assert self.writable, "knit is not opened for write"
        ### FIXME escape. RBC 20060228
        if contains_whitespace(version_id):
            raise InvalidRevisionId(version_id, self.filename)
        if self.has_version(version_id):
            raise RevisionAlreadyPresent(version_id, self.filename)
        self._check_lines_not_unicode(lines)
        self._check_lines_are_lines(lines)

    def _add(self, version_id, lines, parents, delta, parent_texts):
        """Add a set of lines on top of version specified by parents.

        If delta is true, compress the text as a line-delta against
        the first parent.

        Any versions not present will be converted into ghosts.
        """
        #  461    0   6546.0390     43.9100   bzrlib.knit:489(_add)
        # +400    0    889.4890    418.9790   +bzrlib.knit:192(lower_fulltext)
        # +461    0   1364.8070    108.8030   +bzrlib.knit:996(add_record)
        # +461    0    193.3940     41.5720   +bzrlib.knit:898(add_version)
        # +461    0    134.0590     18.3810   +bzrlib.osutils:361(sha_strings)
        # +461    0     36.3420     15.4540   +bzrlib.knit:146(make)
        # +1383   0      8.0370      8.0370   +<len>
        # +61     0     13.5770      7.9190   +bzrlib.knit:199(lower_line_delta)
        # +61     0    963.3470      7.8740   +bzrlib.knit:427(_get_content)
        # +61     0    973.9950      5.2950   +bzrlib.knit:136(line_delta)
        # +61     0   1918.1800      5.2640   +bzrlib.knit:359(_merge_annotations)

        present_parents = []
        ghosts = []
        if parent_texts is None:
            parent_texts = {}
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

        if len(present_parents) and delta:
            # To speed the extract of texts the delta chain is limited
            # to a fixed number of deltas.  This should minimize both
            # I/O and the time spend applying deltas.
            delta = self._check_should_delta(present_parents)

        lines = self.factory.make(lines, version_id)
        if delta or (self.factory.annotated and len(present_parents) > 0):
            # Merge annotations from parent texts if so is needed.
            delta_hunks = self._merge_annotations(lines, present_parents, parent_texts,
                                                  delta, self.factory.annotated)

        if delta:
            options.append('line-delta')
            store_lines = self.factory.lower_line_delta(delta_hunks)
        else:
            options.append('fulltext')
            store_lines = self.factory.lower_fulltext(lines)

        where, size = self._data.add_record(version_id, digest, store_lines)
        self._index.add_version(version_id, options, where, size, parents)
        return lines

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
        
        The keys are version_ids, the values are tuples of (method, content,
        digest, next).
        method is the way the content should be applied.  
        content is a KnitContent object.
        digest is the SHA1 digest of this version id after all steps are done
        next is the build-parent of the version, i.e. the leftmost ancestor.
        If the method is fulltext, next will be None.
        """
        position_map = self._get_components_positions(version_ids)
        # c = component_id, m = method, p = position, s = size, n = next
        records = [(c, p, s) for c, (m, p, s, n) in position_map.iteritems()]
        record_map = {}
        for component_id, content, digest in \
                self._data.read_records_iter(records):
            method, position, size, next = position_map[component_id]
            record_map[component_id] = method, content, digest, next
                          
        return record_map

    def get_text(self, version_id):
        """See VersionedFile.get_text"""
        return self.get_texts([version_id])[0]

    def get_texts(self, version_ids):
        return [''.join(l) for l in self.get_line_list(version_ids)]

    def get_line_list(self, version_ids):
        """Return the texts of listed versions as a list of strings."""
        text_map, content_map = self._get_content_maps(version_ids)
        return [text_map[v] for v in version_ids]

    def _get_content_maps(self, version_ids):
        """Produce maps of text and KnitContents
        
        :return: (text_map, content_map) where text_map contains the texts for
        the requested versions and content_map contains the KnitContents.
        Both dicts take version_ids as their keys.
        """
        for version_id in version_ids:
            if not self.has_version(version_id):
                raise RevisionNotPresent(version_id, self.filename)
        record_map = self._get_record_map(version_ids)

        text_map = {}
        content_map = {}
        final_content = {}
        for version_id in version_ids:
            components = []
            cursor = version_id
            while cursor is not None:
                method, data, digest, next = record_map[cursor]
                components.append((cursor, method, data, digest))
                if cursor in content_map:
                    break
                cursor = next

            content = None
            for component_id, method, data, digest in reversed(components):
                if component_id in content_map:
                    content = content_map[component_id]
                else:
                    version_idx = self._index.lookup(component_id)
                    if method == 'fulltext':
                        assert content is None
                        content = self.factory.parse_fulltext(data, version_idx)
                    elif method == 'line-delta':
                        delta = self.factory.parse_line_delta(data[:], 
                                                              version_idx)
                        content = content.copy()
                        content._lines = self._apply_delta(content._lines, 
                                                           delta)
                    content_map[component_id] = content

            if 'no-eol' in self._index.get_options(version_id):
                content = content.copy()
                line = content._lines[-1][1].rstrip('\n')
                content._lines[-1] = (content._lines[-1][0], line)
            final_content[version_id] = content

            # digest here is the digest from the last applied component.
            text = content.text()
            if sha_strings(text) != digest:
                raise KnitCorrupt(self.filename, 
                                  'sha-1 does not match %s' % version_id)

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

        total = len(version_id_records)
        for version_idx, (version_id, data, sha_value) in \
            enumerate(self._data.read_records_iter(version_id_records)):
            pb.update('Walking content.', version_idx, total)
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
        pb.update('Walking content.', total, total)
        
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
        # perf notes:
        # optimism counts!
        # 52554 calls in 1264 872 internal down from 3674
        try:
            return self._index.get_parents(version_id)
        except KeyError:
            raise RevisionNotPresent(version_id, self.filename)

    def get_parents_with_ghosts(self, version_id):
        """See VersionedFile.get_parents."""
        try:
            return self._index.get_parents_with_ghosts(version_id)
        except KeyError:
            raise RevisionNotPresent(version_id, self.filename)

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

    def plan_merge(self, ver_a, ver_b):
        """See VersionedFile.plan_merge."""
        ancestors_b = set(self.get_ancestry(ver_b))
        def status_a(revision, text):
            if revision in ancestors_b:
                return 'killed-b', text
            else:
                return 'new-a', text
        
        ancestors_a = set(self.get_ancestry(ver_a))
        def status_b(revision, text):
            if revision in ancestors_a:
                return 'killed-a', text
            else:
                return 'new-b', text

        annotated_a = self.annotate(ver_a)
        annotated_b = self.annotate(ver_b)
        plain_a = [t for (a, t) in annotated_a]
        plain_b = [t for (a, t) in annotated_b]
        blocks = KnitSequenceMatcher(None, plain_a, plain_b).get_matching_blocks()
        a_cur = 0
        b_cur = 0
        for ai, bi, l in blocks:
            # process all mismatched sections
            # (last mismatched section is handled because blocks always
            # includes a 0-length last block)
            for revision, text in annotated_a[a_cur:ai]:
                yield status_a(revision, text)
            for revision, text in annotated_b[b_cur:bi]:
                yield status_b(revision, text)

            # and now the matched section
            a_cur = ai + l
            b_cur = bi + l
            for text_a, text_b in zip(plain_a[ai:a_cur], plain_b[bi:b_cur]):
                assert text_a == text_b
                yield "unchanged", text_a


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

    def check_header(self, fp):
        line = fp.readline()
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
    when a write is interrupted to the index file, it will result in a line that
    does not end in ' :'. If the ' :' is not present at the end of a line, or at
    the end of the file, then the record that is missing it will be ignored by
    the parser.

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
        
        This is inlined into __init__ for performance. KEEP IN SYNC.
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
        decode_utf8 = cache_utf8.decode
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            count = 0
            total = 1
            try:
                pb.update('read knit index', count, total)
                fp = self._transport.get(self._filename)
                try:
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
                        if len(rec) < 5 or rec[-1] != ':':
                            # corrupt line.
                            # FIXME: in the future we should determine if its a
                            # short write - and ignore it 
                            # or a different failure, and raise. RBC 20060407
                            continue
                        count += 1
                        total += 1
                        #pb.update('read knit index', count, total)
                        # See self._parse_parents
                        parents = []
                        for value in rec[4:-1]:
                            if '.' == value[0]:
                                # uncompressed reference
                                parents.append(decode_utf8(value[1:]))
                            else:
                                # this is 15/4000ms faster than isinstance,
                                # (in lsprof)
                                # this function is called thousands of times a 
                                # second so small variations add up.
                                assert value.__class__ is str
                                parents.append(self._history[int(value)])
                        # end self._parse_parents
                        # self._cache_version(decode_utf8(rec[0]),
                        #                     rec[1].split(','),
                        #                     int(rec[2]),
                        #                     int(rec[3]),
                        #                     parents)
                        # --- self._cache_version
                        # only want the _history index to reference the 1st 
                        # index entry for version_id
                        version_id = decode_utf8(rec[0])
                        if version_id not in self._cache:
                            index = len(self._history)
                            self._history.append(version_id)
                        else:
                            index = self._cache[version_id][5]
                        self._cache[version_id] = (version_id,
                                                   rec[1].split(','),
                                                   int(rec[2]),
                                                   int(rec[3]),
                                                   parents,
                                                   index)
                        # --- self._cache_version 
                finally:
                    fp.close()
            except NoSuchFile, e:
                if mode != 'w' or not create:
                    raise
                if delay_create:
                    self._need_to_create = True
                else:
                    self._transport.put_bytes_non_atomic(self._filename,
                        self.HEADER, mode=self._file_mode)

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
                result.append(cache_utf8.decode_utf8(value[1:]))
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
        return self._cache[version_id][5]

    def _version_list_to_index(self, versions):
        encode_utf8 = cache_utf8.encode
        result_list = []
        for version in versions:
            if version in self._cache:
                # -- inlined lookup() --
                result_list.append(str(self._cache[version][5]))
                # -- end lookup () --
            else:
                result_list.append('.' + encode_utf8(version))
        return ' '.join(result_list)

    def add_version(self, version_id, options, pos, size, parents):
        """Add a version record to the index."""
        self.add_versions(((version_id, options, pos, size, parents),))

    def add_versions(self, versions):
        """Add multiple versions to the index.
        
        :param versions: a list of tuples:
                         (version_id, options, pos, size, parents).
        """
        lines = []
        encode_utf8 = cache_utf8.encode
        orig_history = self._history[:]
        orig_cache = self._cache.copy()

        try:
            for version_id, options, pos, size, parents in versions:
                line = "\n%s %s %s %s %s :" % (encode_utf8(version_id),
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
        return (version_id in self._cache)

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
        """Return parents of specified version with ghosts."""
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

    def __init__(self, transport, filename, mode, create=False, file_mode=None,
                 create_parent_dir=False, delay_create=False,
                 dir_mode=None):
        _KnitComponentFile.__init__(self, transport, filename, mode,
                                    file_mode=file_mode,
                                    create_parent_dir=create_parent_dir,
                                    dir_mode=dir_mode)
        self._checked = False
        # TODO: jam 20060713 conceptually, this could spill to disk
        #       if the cached size gets larger than a certain amount
        #       but it complicates the model a bit, so for now just use
        #       a simple dictionary
        self._cache = {}
        self._do_cache = False
        if create:
            if delay_create:
                self._need_to_create = create
            else:
                self._transport.put_bytes_non_atomic(self._filename, '',
                                                     mode=self._file_mode)

    def enable_cache(self):
        """Enable caching of reads."""
        self._do_cache = True

    def clear_cache(self):
        """Clear the record cache."""
        self._do_cache = False
        self._cache = {}

    def _open_file(self):
        try:
            return self._transport.get(self._filename)
        except NoSuchFile:
            pass
        return None

    def _record_to_data(self, version_id, digest, lines):
        """Convert version_id, digest, lines into a raw data block.
        
        :return: (len, a StringIO instance with the raw data ready to read.)
        """
        sio = StringIO()
        data_file = GzipFile(None, mode='wb', fileobj=sio)

        version_id_utf8 = cache_utf8.encode(version_id)
        data_file.writelines(chain(
            ["version %s %d %s\n" % (version_id_utf8,
                                     len(lines),
                                     digest)],
            lines,
            ["end %s\n" % version_id_utf8]))
        data_file.close()
        length= sio.tell()

        sio.seek(0)
        return length, sio

    def add_raw_record(self, raw_data):
        """Append a prepared record to the data file.
        
        :return: the offset in the data file raw_data was written.
        """
        assert isinstance(raw_data, str), 'data must be plain bytes'
        if not self._need_to_create:
            return self._transport.append_bytes(self._filename, raw_data)
        else:
            self._transport.put_bytes_non_atomic(self._filename, raw_data,
                                   create_parent_dir=self._create_parent_dir,
                                   mode=self._file_mode,
                                   dir_mode=self._dir_mode)
            self._need_to_create = False
            return 0
        
    def add_record(self, version_id, digest, lines):
        """Write new text record to disk.  Returns the position in the
        file where it was written."""
        size, sio = self._record_to_data(version_id, digest, lines)
        # write to disk
        if not self._need_to_create:
            start_pos = self._transport.append_file(self._filename, sio)
        else:
            self._transport.put_file_non_atomic(self._filename, sio,
                               create_parent_dir=self._create_parent_dir,
                               mode=self._file_mode,
                               dir_mode=self._dir_mode)
            self._need_to_create = False
            start_pos = 0
        if self._do_cache:
            self._cache[version_id] = sio.getvalue()
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
        if cache_utf8.decode(rec[1]) != version_id:
            raise KnitCorrupt(self._filename, 
                              'unexpected version, wanted %r, got %r' % (
                                version_id, rec[1]))
        return df, rec

    def _parse_record(self, version_id, data):
        # profiling notes:
        # 4168 calls in 2880 217 internal
        # 4168 calls to _parse_record_header in 2121
        # 4168 calls to readlines in 330
        df, rec = self._parse_record_header(version_id, data)
        record_contents = df.readlines()
        l = record_contents.pop()
        assert len(record_contents) == int(rec[2])
        if l != 'end %s\n' % cache_utf8.encode(version_id):
            raise KnitCorrupt(self._filename, 'unexpected version end line %r, wanted %r' 
                        % (l, version_id))
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
                needed_offsets = [(pos, size) for version_id, pos, size
                                              in records
                                              if version_id not in self._cache]
            else:
                needed_offsets = [(pos, size) for version_id, pos, size
                                               in records]

            raw_records = self._transport.readv(self._filename, needed_offsets)
                

        for version_id, pos, size in records:
            if version_id in self._cache:
                # This data has already been validated
                data = self._cache[version_id]
            else:
                pos, data = raw_records.next()
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
        readv_response = self._transport.readv(self._filename,
            [(pos, size) for version_id, pos, size in needed_records])

        for (version_id, pos, size), (pos, data) in \
                izip(iter(needed_records), readv_response):
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

    def join(self, pb=None, msg=None, version_ids=None, ignore_missing=False):
        """See InterVersionedFile.join."""
        assert isinstance(self.source, KnitVersionedFile)
        assert isinstance(self.target, KnitVersionedFile)

        version_ids = self._get_source_version_ids(version_ids, ignore_missing)

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
    
            if not needed_versions and not mismatched_versions:
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
                data_pos, data_size = self.source._index.get_position(version_id)
                copy_queue_records.append((version_id, data_pos, data_size))
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
                raw_records.append((version_id, options, parents, len(raw_data)))
                raw_datum.append(raw_data)
            self.target._add_raw_records(raw_records, ''.join(raw_datum))

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
            pb.finished()


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

        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            version_ids = list(version_ids)
    
            self.source_ancestry = set(self.source.get_ancestry(version_ids))
            this_versions = set(self.target._index.get_versions())
            needed_versions = self.source_ancestry - this_versions
            cross_check_versions = self.source_ancestry.intersection(this_versions)
            mismatched_versions = set()
            for version in cross_check_versions:
                # scan to include needed parents.
                n1 = set(self.target.get_parents_with_ghosts(version))
                n2 = set(self.source.get_parents(version))
                # if all of n2's parents are in n1, then its fine.
                if n2.difference(n1):
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
    
            if not needed_versions and not mismatched_versions:
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

            for version in mismatched_versions:
                # FIXME RBC 20060309 is this needed?
                n1 = set(self.target.get_parents_with_ghosts(version))
                n2 = set(self.source.get_parents(version))
                # write a combined record to our history preserving the current 
                # parents as first in the list
                new_parents = self.target.get_parents_with_ghosts(version) + list(n2.difference(n1))
                self.target.fix_parents(version, new_parents)
            return count
        finally:
            pb.finished()


InterVersionedFile.register_optimiser(WeaveToKnit)


class KnitSequenceMatcher(difflib.SequenceMatcher):
    """Knit tuned sequence matcher.

    This is based on profiling of difflib which indicated some improvements
    for our usage pattern.
    """

    def find_longest_match(self, alo, ahi, blo, bhi):
        """Find longest matching block in a[alo:ahi] and b[blo:bhi].

        If isjunk is not defined:

        Return (i,j,k) such that a[i:i+k] is equal to b[j:j+k], where
            alo <= i <= i+k <= ahi
            blo <= j <= j+k <= bhi
        and for all (i',j',k') meeting those conditions,
            k >= k'
            i <= i'
            and if i == i', j <= j'

        In other words, of all maximal matching blocks, return one that
        starts earliest in a, and of all those maximal matching blocks that
        start earliest in a, return the one that starts earliest in b.

        >>> s = SequenceMatcher(None, " abcd", "abcd abcd")
        >>> s.find_longest_match(0, 5, 0, 9)
        (0, 4, 5)

        If isjunk is defined, first the longest matching block is
        determined as above, but with the additional restriction that no
        junk element appears in the block.  Then that block is extended as
        far as possible by matching (only) junk elements on both sides.  So
        the resulting block never matches on junk except as identical junk
        happens to be adjacent to an "interesting" match.

        Here's the same example as before, but considering blanks to be
        junk.  That prevents " abcd" from matching the " abcd" at the tail
        end of the second sequence directly.  Instead only the "abcd" can
        match, and matches the leftmost "abcd" in the second sequence:

        >>> s = SequenceMatcher(lambda x: x==" ", " abcd", "abcd abcd")
        >>> s.find_longest_match(0, 5, 0, 9)
        (1, 0, 4)

        If no blocks match, return (alo, blo, 0).

        >>> s = SequenceMatcher(None, "ab", "c")
        >>> s.find_longest_match(0, 2, 0, 1)
        (0, 0, 0)
        """

        # CAUTION:  stripping common prefix or suffix would be incorrect.
        # E.g.,
        #    ab
        #    acab
        # Longest matching block is "ab", but if common prefix is
        # stripped, it's "a" (tied with "b").  UNIX(tm) diff does so
        # strip, so ends up claiming that ab is changed to acab by
        # inserting "ca" in the middle.  That's minimal but unintuitive:
        # "it's obvious" that someone inserted "ac" at the front.
        # Windiff ends up at the same place as diff, but by pairing up
        # the unique 'b's and then matching the first two 'a's.

        a, b, b2j, isbjunk = self.a, self.b, self.b2j, self.isbjunk
        besti, bestj, bestsize = alo, blo, 0
        # find longest junk-free match
        # during an iteration of the loop, j2len[j] = length of longest
        # junk-free match ending with a[i-1] and b[j]
        j2len = {}
        # nothing = []
        b2jget = b2j.get
        for i in xrange(alo, ahi):
            # look at all instances of a[i] in b; note that because
            # b2j has no junk keys, the loop is skipped if a[i] is junk
            j2lenget = j2len.get
            newj2len = {}
            
            # changing b2j.get(a[i], nothing) to a try:KeyError pair produced the
            # following improvement
            #     704  0   4650.5320   2620.7410   bzrlib.knit:1336(find_longest_match)
            # +326674  0   1655.1210   1655.1210   +<method 'get' of 'dict' objects>
            #  +76519  0    374.6700    374.6700   +<method 'has_key' of 'dict' objects>
            # to 
            #     704  0   3733.2820   2209.6520   bzrlib.knit:1336(find_longest_match)
            #  +211400 0   1147.3520   1147.3520   +<method 'get' of 'dict' objects>
            #  +76519  0    376.2780    376.2780   +<method 'has_key' of 'dict' objects>

            try:
                js = b2j[a[i]]
            except KeyError:
                pass
            else:
                for j in js:
                    # a[i] matches b[j]
                    if j >= blo:
                        if j >= bhi:
                            break
                        k = newj2len[j] = 1 + j2lenget(-1 + j, 0)
                        if k > bestsize:
                            besti, bestj, bestsize = 1 + i-k, 1 + j-k, k
            j2len = newj2len

        # Extend the best by non-junk elements on each end.  In particular,
        # "popular" non-junk elements aren't in b2j, which greatly speeds
        # the inner loop above, but also means "the best" match so far
        # doesn't contain any junk *or* popular non-junk elements.
        while besti > alo and bestj > blo and \
              not isbjunk(b[bestj-1]) and \
              a[besti-1] == b[bestj-1]:
            besti, bestj, bestsize = besti-1, bestj-1, bestsize+1
        while besti+bestsize < ahi and bestj+bestsize < bhi and \
              not isbjunk(b[bestj+bestsize]) and \
              a[besti+bestsize] == b[bestj+bestsize]:
            bestsize += 1

        # Now that we have a wholly interesting match (albeit possibly
        # empty!), we may as well suck up the matching junk on each
        # side of it too.  Can't think of a good reason not to, and it
        # saves post-processing the (possibly considerable) expense of
        # figuring out what to do with it.  In the case of an empty
        # interesting match, this is clearly the right thing to do,
        # because no other kind of match is possible in the regions.
        while besti > alo and bestj > blo and \
              isbjunk(b[bestj-1]) and \
              a[besti-1] == b[bestj-1]:
            besti, bestj, bestsize = besti-1, bestj-1, bestsize+1
        while besti+bestsize < ahi and bestj+bestsize < bhi and \
              isbjunk(b[bestj+bestsize]) and \
              a[besti+bestsize] == b[bestj+bestsize]:
            bestsize = bestsize + 1

        return besti, bestj, bestsize

