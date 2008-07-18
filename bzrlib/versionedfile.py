# Copyright (C) 2005, 2006 Canonical Ltd
#
# Authors:
#   Johan Rydberg <jrydberg@gnu.org>
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

"""Versioned text file storage api."""

from copy import copy
from cStringIO import StringIO
import os
import urllib
from zlib import adler32

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """

from bzrlib import (
    errors,
    osutils,
    multiparent,
    tsort,
    revision,
    ui,
    )
from bzrlib.graph import DictParentsProvider, Graph, _StackedParentsProvider
from bzrlib.transport.memory import MemoryTransport
""")
from bzrlib.inter import InterObject
from bzrlib.registry import Registry
from bzrlib.symbol_versioning import *
from bzrlib.textmerge import TextMerge


adapter_registry = Registry()
adapter_registry.register_lazy(('knit-delta-gz', 'fulltext'), 'bzrlib.knit',
    'DeltaPlainToFullText')
adapter_registry.register_lazy(('knit-ft-gz', 'fulltext'), 'bzrlib.knit',
    'FTPlainToFullText')
adapter_registry.register_lazy(('knit-annotated-delta-gz', 'knit-delta-gz'),
    'bzrlib.knit', 'DeltaAnnotatedToUnannotated')
adapter_registry.register_lazy(('knit-annotated-delta-gz', 'fulltext'),
    'bzrlib.knit', 'DeltaAnnotatedToFullText')
adapter_registry.register_lazy(('knit-annotated-ft-gz', 'knit-ft-gz'),
    'bzrlib.knit', 'FTAnnotatedToUnannotated')
adapter_registry.register_lazy(('knit-annotated-ft-gz', 'fulltext'),
    'bzrlib.knit', 'FTAnnotatedToFullText')


class ContentFactory(object):
    """Abstract interface for insertion and retrieval from a VersionedFile.
    
    :ivar sha1: None, or the sha1 of the content fulltext.
    :ivar storage_kind: The native storage kind of this factory. One of
        'mpdiff', 'knit-annotated-ft', 'knit-annotated-delta', 'knit-ft',
        'knit-delta', 'fulltext', 'knit-annotated-ft-gz',
        'knit-annotated-delta-gz', 'knit-ft-gz', 'knit-delta-gz'.
    :ivar key: The key of this content. Each key is a tuple with a single
        string in it.
    :ivar parents: A tuple of parent keys for self.key. If the object has
        no parent information, None (as opposed to () for an empty list of
        parents).
    """

    def __init__(self):
        """Create a ContentFactory."""
        self.sha1 = None
        self.storage_kind = None
        self.key = None
        self.parents = None


class FulltextContentFactory(ContentFactory):
    """Static data content factory.

    This takes a fulltext when created and just returns that during
    get_bytes_as('fulltext').
    
    :ivar sha1: None, or the sha1 of the content fulltext.
    :ivar storage_kind: The native storage kind of this factory. Always
        'fulltext'.
    :ivar key: The key of this content. Each key is a tuple with a single
        string in it.
    :ivar parents: A tuple of parent keys for self.key. If the object has
        no parent information, None (as opposed to () for an empty list of
        parents).
     """

    def __init__(self, key, parents, sha1, text):
        """Create a ContentFactory."""
        self.sha1 = sha1
        self.storage_kind = 'fulltext'
        self.key = key
        self.parents = parents
        self._text = text

    def get_bytes_as(self, storage_kind):
        if storage_kind == self.storage_kind:
            return self._text
        raise errors.UnavailableRepresentation(self.key, storage_kind,
            self.storage_kind)


class AbsentContentFactory(ContentFactory):
    """A placeholder content factory for unavailable texts.
    
    :ivar sha1: None.
    :ivar storage_kind: 'absent'.
    :ivar key: The key of this content. Each key is a tuple with a single
        string in it.
    :ivar parents: None.
    """

    def __init__(self, key):
        """Create a ContentFactory."""
        self.sha1 = None
        self.storage_kind = 'absent'
        self.key = key
        self.parents = None


class AdapterFactory(ContentFactory):
    """A content factory to adapt between key prefix's."""

    def __init__(self, key, parents, adapted):
        """Create an adapter factory instance."""
        self.key = key
        self.parents = parents
        self._adapted = adapted

    def __getattr__(self, attr):
        """Return a member from the adapted object."""
        if attr in ('key', 'parents'):
            return self.__dict__[attr]
        else:
            return getattr(self._adapted, attr)


def filter_absent(record_stream):
    """Adapt a record stream to remove absent records."""
    for record in record_stream:
        if record.storage_kind != 'absent':
            yield record


class VersionedFile(object):
    """Versioned text file storage.
    
    A versioned file manages versions of line-based text files,
    keeping track of the originating version for each line.

    To clients the "lines" of the file are represented as a list of
    strings. These strings will typically have terminal newline
    characters, but this is not required.  In particular files commonly
    do not have a newline at the end of the file.

    Texts are identified by a version-id string.
    """

    @staticmethod
    def check_not_reserved_id(version_id):
        revision.check_not_reserved_id(version_id)

    def copy_to(self, name, transport):
        """Copy this versioned file to name on transport."""
        raise NotImplementedError(self.copy_to)

    def get_record_stream(self, versions, ordering, include_delta_closure):
        """Get a stream of records for versions.

        :param versions: The versions to include. Each version is a tuple
            (version,).
        :param ordering: Either 'unordered' or 'topological'. A topologically
            sorted stream has compression parents strictly before their
            children.
        :param include_delta_closure: If True then the closure across any
            compression parents will be included (in the data content of the
            stream, not in the emitted records). This guarantees that
            'fulltext' can be used successfully on every record.
        :return: An iterator of ContentFactory objects, each of which is only
            valid until the iterator is advanced.
        """
        raise NotImplementedError(self.get_record_stream)

    def has_version(self, version_id):
        """Returns whether version is present."""
        raise NotImplementedError(self.has_version)

    def insert_record_stream(self, stream):
        """Insert a record stream into this versioned file.

        :param stream: A stream of records to insert. 
        :return: None
        :seealso VersionedFile.get_record_stream:
        """
        raise NotImplementedError

    def add_lines(self, version_id, parents, lines, parent_texts=None,
        left_matching_blocks=None, nostore_sha=None, random_id=False,
        check_content=True):
        """Add a single text on top of the versioned file.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history.

        Must raise RevisionNotPresent if any of the given parents are
        not present in file history.

        :param lines: A list of lines. Each line must be a bytestring. And all
            of them except the last must be terminated with \n and contain no
            other \n's. The last line may either contain no \n's or a single
            terminated \n. If the lines list does meet this constraint the add
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
        self._check_write_ok()
        return self._add_lines(version_id, parents, lines, parent_texts,
            left_matching_blocks, nostore_sha, random_id, check_content)

    def _add_lines(self, version_id, parents, lines, parent_texts,
        left_matching_blocks, nostore_sha, random_id, check_content):
        """Helper to do the class specific add_lines."""
        raise NotImplementedError(self.add_lines)

    def add_lines_with_ghosts(self, version_id, parents, lines,
        parent_texts=None, nostore_sha=None, random_id=False,
        check_content=True, left_matching_blocks=None):
        """Add lines to the versioned file, allowing ghosts to be present.
        
        This takes the same parameters as add_lines and returns the same.
        """
        self._check_write_ok()
        return self._add_lines_with_ghosts(version_id, parents, lines,
            parent_texts, nostore_sha, random_id, check_content, left_matching_blocks)

    def _add_lines_with_ghosts(self, version_id, parents, lines, parent_texts,
        nostore_sha, random_id, check_content, left_matching_blocks):
        """Helper to do class specific add_lines_with_ghosts."""
        raise NotImplementedError(self.add_lines_with_ghosts)

    def check(self, progress_bar=None):
        """Check the versioned file for integrity."""
        raise NotImplementedError(self.check)

    def _check_lines_not_unicode(self, lines):
        """Check that lines being added to a versioned file are not unicode."""
        for line in lines:
            if line.__class__ is not str:
                raise errors.BzrBadParameterUnicode("lines")

    def _check_lines_are_lines(self, lines):
        """Check that the lines really are full lines without inline EOL."""
        for line in lines:
            if '\n' in line[:-1]:
                raise errors.BzrBadParameterContainsNewline("lines")

    def get_format_signature(self):
        """Get a text description of the data encoding in this file.
        
        :since: 0.90
        """
        raise NotImplementedError(self.get_format_signature)

    def make_mpdiffs(self, version_ids):
        """Create multiparent diffs for specified versions."""
        knit_versions = set()
        knit_versions.update(version_ids)
        parent_map = self.get_parent_map(version_ids)
        for version_id in version_ids:
            try:
                knit_versions.update(parent_map[version_id])
            except KeyError:
                raise errors.RevisionNotPresent(version_id, self)
        # We need to filter out ghosts, because we can't diff against them.
        knit_versions = set(self.get_parent_map(knit_versions).keys())
        lines = dict(zip(knit_versions,
            self._get_lf_split_line_list(knit_versions)))
        diffs = []
        for version_id in version_ids:
            target = lines[version_id]
            try:
                parents = [lines[p] for p in parent_map[version_id] if p in
                    knit_versions]
            except KeyError:
                # I don't know how this could ever trigger.
                # parent_map[version_id] was already triggered in the previous
                # for loop, and lines[p] has the 'if p in knit_versions' check,
                # so we again won't have a KeyError.
                raise errors.RevisionNotPresent(version_id, self)
            if len(parents) > 0:
                left_parent_blocks = self._extract_blocks(version_id,
                                                          parents[0], target)
            else:
                left_parent_blocks = None
            diffs.append(multiparent.MultiParent.from_lines(target, parents,
                         left_parent_blocks))
        return diffs

    def _extract_blocks(self, version_id, source, target):
        return None

    def add_mpdiffs(self, records):
        """Add mpdiffs to this VersionedFile.

        Records should be iterables of version, parents, expected_sha1,
        mpdiff. mpdiff should be a MultiParent instance.
        """
        # Does this need to call self._check_write_ok()? (IanC 20070919)
        vf_parents = {}
        mpvf = multiparent.MultiMemoryVersionedFile()
        versions = []
        for version, parent_ids, expected_sha1, mpdiff in records:
            versions.append(version)
            mpvf.add_diff(mpdiff, version, parent_ids)
        needed_parents = set()
        for version, parent_ids, expected_sha1, mpdiff in records:
            needed_parents.update(p for p in parent_ids
                                  if not mpvf.has_version(p))
        present_parents = set(self.get_parent_map(needed_parents).keys())
        for parent_id, lines in zip(present_parents,
                                 self._get_lf_split_line_list(present_parents)):
            mpvf.add_version(lines, parent_id, [])
        for (version, parent_ids, expected_sha1, mpdiff), lines in\
            zip(records, mpvf.get_line_list(versions)):
            if len(parent_ids) == 1:
                left_matching_blocks = list(mpdiff.get_matching_blocks(0,
                    mpvf.get_diff(parent_ids[0]).num_lines()))
            else:
                left_matching_blocks = None
            try:
                _, _, version_text = self.add_lines_with_ghosts(version,
                    parent_ids, lines, vf_parents,
                    left_matching_blocks=left_matching_blocks)
            except NotImplementedError:
                # The vf can't handle ghosts, so add lines normally, which will
                # (reasonably) fail if there are ghosts in the data.
                _, _, version_text = self.add_lines(version,
                    parent_ids, lines, vf_parents,
                    left_matching_blocks=left_matching_blocks)
            vf_parents[version] = version_text
        sha1s = self.get_sha1s(versions)
        for version, parent_ids, expected_sha1, mpdiff in records:
            if expected_sha1 != sha1s[version]:
                raise errors.VersionedFileInvalidChecksum(version)

    def get_text(self, version_id):
        """Return version contents as a text string.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return ''.join(self.get_lines(version_id))
    get_string = get_text

    def get_texts(self, version_ids):
        """Return the texts of listed versions as a list of strings.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return [''.join(self.get_lines(v)) for v in version_ids]

    def get_lines(self, version_id):
        """Return version contents as a sequence of lines.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_lines)

    def _get_lf_split_line_list(self, version_ids):
        return [StringIO(t).readlines() for t in self.get_texts(version_ids)]

    def get_ancestry(self, version_ids, topo_sorted=True):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        This list will not be topologically sorted if topo_sorted=False is
        passed.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history."""
        if isinstance(version_ids, basestring):
            version_ids = [version_ids]
        raise NotImplementedError(self.get_ancestry)
        
    def get_ancestry_with_ghosts(self, version_ids):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history.
        
        Ghosts that are known about will be included in ancestry list,
        but are not explicitly marked.
        """
        raise NotImplementedError(self.get_ancestry_with_ghosts)
    
    def get_parent_map(self, version_ids):
        """Get a map of the parents of version_ids.

        :param version_ids: The version ids to look up parents for.
        :return: A mapping from version id to parents.
        """
        raise NotImplementedError(self.get_parent_map)

    def get_parents_with_ghosts(self, version_id):
        """Return version names for parents of version_id.

        Will raise RevisionNotPresent if version_id is not present
        in the history.

        Ghosts that are known about will be included in the parent list,
        but are not explicitly marked.
        """
        try:
            return list(self.get_parent_map([version_id])[version_id])
        except KeyError:
            raise errors.RevisionNotPresent(version_id, self)

    def annotate(self, version_id):
        """Return a list of (version-id, line) tuples for version_id.

        :raise RevisionNotPresent: If the given version is
        not present in file history.
        """
        raise NotImplementedError(self.annotate)

    def iter_lines_added_or_present_in_versions(self, version_ids=None,
                                                pb=None):
        """Iterate over the lines in the versioned file from version_ids.

        This may return lines from other versions. Each item the returned
        iterator yields is a tuple of a line and a text version that that line
        is present in (not introduced in).

        Ordering of results is in whatever order is most suitable for the
        underlying storage format.

        If a progress bar is supplied, it may be used to indicate progress.
        The caller is responsible for cleaning up progress bars (because this
        is an iterator).

        NOTES: Lines are normalised: they will all have \n terminators.
               Lines are returned in arbitrary order.

        :return: An iterator over (line, version_id).
        """
        raise NotImplementedError(self.iter_lines_added_or_present_in_versions)

    def plan_merge(self, ver_a, ver_b):
        """Return pseudo-annotation indicating how the two versions merge.

        This is computed between versions a and b and their common
        base.

        Weave lines present in none of them are skipped entirely.

        Legend:
        killed-base Dead in base revision
        killed-both Killed in each revision
        killed-a    Killed in a
        killed-b    Killed in b
        unchanged   Alive in both a and b (possibly created in both)
        new-a       Created in a
        new-b       Created in b
        ghost-a     Killed in a, unborn in b    
        ghost-b     Killed in b, unborn in a
        irrelevant  Not in either revision
        """
        raise NotImplementedError(VersionedFile.plan_merge)
        
    def weave_merge(self, plan, a_marker=TextMerge.A_MARKER,
                    b_marker=TextMerge.B_MARKER):
        return PlanWeaveMerge(plan, a_marker, b_marker).merge_lines()[0]


class RecordingVersionedFilesDecorator(object):
    """A minimal versioned files that records calls made on it.
    
    Only enough methods have been added to support tests using it to date.

    :ivar calls: A list of the calls made; can be reset at any time by
        assigning [] to it.
    """

    def __init__(self, backing_vf):
        """Create a RecordingVersionedFileDsecorator decorating backing_vf.
        
        :param backing_vf: The versioned file to answer all methods.
        """
        self._backing_vf = backing_vf
        self.calls = []

    def add_lines(self, key, parents, lines, parent_texts=None,
        left_matching_blocks=None, nostore_sha=None, random_id=False,
        check_content=True):
        self.calls.append(("add_lines", key, parents, lines, parent_texts,
            left_matching_blocks, nostore_sha, random_id, check_content))
        return self._backing_vf.add_lines(key, parents, lines, parent_texts,
            left_matching_blocks, nostore_sha, random_id, check_content)

    def check(self):
        self._backing_vf.check()

    def get_parent_map(self, keys):
        self.calls.append(("get_parent_map", copy(keys)))
        return self._backing_vf.get_parent_map(keys)

    def get_record_stream(self, keys, sort_order, include_delta_closure):
        self.calls.append(("get_record_stream", list(keys), sort_order,
            include_delta_closure))
        return self._backing_vf.get_record_stream(keys, sort_order,
            include_delta_closure)

    def get_sha1s(self, keys):
        self.calls.append(("get_sha1s", copy(keys)))
        return self._backing_vf.get_sha1s(keys)

    def iter_lines_added_or_present_in_keys(self, keys, pb=None):
        self.calls.append(("iter_lines_added_or_present_in_keys", copy(keys)))
        return self._backing_vf.iter_lines_added_or_present_in_keys(keys, pb=pb)

    def keys(self):
        self.calls.append(("keys",))
        return self._backing_vf.keys()


class KeyMapper(object):
    """KeyMappers map between keys and underlying partitioned storage."""

    def map(self, key):
        """Map key to an underlying storage identifier.

        :param key: A key tuple e.g. ('file-id', 'revision-id').
        :return: An underlying storage identifier, specific to the partitioning
            mechanism.
        """
        raise NotImplementedError(self.map)

    def unmap(self, partition_id):
        """Map a partitioned storage id back to a key prefix.
        
        :param partition_id: The underlying partition id.
        :return: As much of a key (or prefix) as is derivable from the partition
            id.
        """
        raise NotImplementedError(self.unmap)


class ConstantMapper(KeyMapper):
    """A key mapper that maps to a constant result."""

    def __init__(self, result):
        """Create a ConstantMapper which will return result for all maps."""
        self._result = result

    def map(self, key):
        """See KeyMapper.map()."""
        return self._result


class URLEscapeMapper(KeyMapper):
    """Base class for use with transport backed storage.

    This provides a map and unmap wrapper that respectively url escape and
    unescape their outputs and inputs.
    """

    def map(self, key):
        """See KeyMapper.map()."""
        return urllib.quote(self._map(key))

    def unmap(self, partition_id):
        """See KeyMapper.unmap()."""
        return self._unmap(urllib.unquote(partition_id))


class PrefixMapper(URLEscapeMapper):
    """A key mapper that extracts the first component of a key.
    
    This mapper is for use with a transport based backend.
    """

    def _map(self, key):
        """See KeyMapper.map()."""
        return key[0]

    def _unmap(self, partition_id):
        """See KeyMapper.unmap()."""
        return (partition_id,)


class HashPrefixMapper(URLEscapeMapper):
    """A key mapper that combines the first component of a key with a hash.

    This mapper is for use with a transport based backend.
    """

    def _map(self, key):
        """See KeyMapper.map()."""
        prefix = self._escape(key[0])
        return "%02x/%s" % (adler32(prefix) & 0xff, prefix)

    def _escape(self, prefix):
        """No escaping needed here."""
        return prefix

    def _unmap(self, partition_id):
        """See KeyMapper.unmap()."""
        return (self._unescape(osutils.basename(partition_id)),)

    def _unescape(self, basename):
        """No unescaping needed for HashPrefixMapper."""
        return basename


class HashEscapedPrefixMapper(HashPrefixMapper):
    """Combines the escaped first component of a key with a hash.
    
    This mapper is for use with a transport based backend.
    """

    _safe = "abcdefghijklmnopqrstuvwxyz0123456789-_@,."

    def _escape(self, prefix):
        """Turn a key element into a filesystem safe string.

        This is similar to a plain urllib.quote, except
        it uses specific safe characters, so that it doesn't
        have to translate a lot of valid file ids.
        """
        # @ does not get escaped. This is because it is a valid
        # filesystem character we use all the time, and it looks
        # a lot better than seeing %40 all the time.
        r = [((c in self._safe) and c or ('%%%02x' % ord(c)))
             for c in prefix]
        return ''.join(r)

    def _unescape(self, basename):
        """Escaped names are easily unescaped by urlutils."""
        return urllib.unquote(basename)


def make_versioned_files_factory(versioned_file_factory, mapper):
    """Create a ThunkedVersionedFiles factory.

    This will create a callable which when called creates a
    ThunkedVersionedFiles on a transport, using mapper to access individual
    versioned files, and versioned_file_factory to create each individual file.
    """
    def factory(transport):
        return ThunkedVersionedFiles(transport, versioned_file_factory, mapper,
            lambda:True)
    return factory


class VersionedFiles(object):
    """Storage for many versioned files.

    This object allows a single keyspace for accessing the history graph and
    contents of named bytestrings.

    Currently no implementation allows the graph of different key prefixes to
    intersect, but the API does allow such implementations in the future.

    The keyspace is expressed via simple tuples. Any instance of VersionedFiles
    may have a different length key-size, but that size will be constant for
    all texts added to or retrieved from it. For instance, bzrlib uses
    instances with a key-size of 2 for storing user files in a repository, with
    the first element the fileid, and the second the version of that file.

    The use of tuples allows a single code base to support several different
    uses with only the mapping logic changing from instance to instance.
    """

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
        raise NotImplementedError(self.add_lines)

    def add_mpdiffs(self, records):
        """Add mpdiffs to this VersionedFile.

        Records should be iterables of version, parents, expected_sha1,
        mpdiff. mpdiff should be a MultiParent instance.
        """
        vf_parents = {}
        mpvf = multiparent.MultiMemoryVersionedFile()
        versions = []
        for version, parent_ids, expected_sha1, mpdiff in records:
            versions.append(version)
            mpvf.add_diff(mpdiff, version, parent_ids)
        needed_parents = set()
        for version, parent_ids, expected_sha1, mpdiff in records:
            needed_parents.update(p for p in parent_ids
                                  if not mpvf.has_version(p))
        # It seems likely that adding all the present parents as fulltexts can
        # easily exhaust memory.
        split_lines = osutils.split_lines
        for record in self.get_record_stream(needed_parents, 'unordered',
            True):
            if record.storage_kind == 'absent':
                continue
            mpvf.add_version(split_lines(record.get_bytes_as('fulltext')),
                record.key, [])
        for (key, parent_keys, expected_sha1, mpdiff), lines in\
            zip(records, mpvf.get_line_list(versions)):
            if len(parent_keys) == 1:
                left_matching_blocks = list(mpdiff.get_matching_blocks(0,
                    mpvf.get_diff(parent_keys[0]).num_lines()))
            else:
                left_matching_blocks = None
            version_sha1, _, version_text = self.add_lines(key,
                parent_keys, lines, vf_parents,
                left_matching_blocks=left_matching_blocks)
            if version_sha1 != expected_sha1:
                raise errors.VersionedFileInvalidChecksum(version)
            vf_parents[key] = version_text

    def annotate(self, key):
        """Return a list of (version-key, line) tuples for the text of key.

        :raise RevisionNotPresent: If the key is not present.
        """
        raise NotImplementedError(self.annotate)

    def check(self, progress_bar=None):
        """Check this object for integrity."""
        raise NotImplementedError(self.check)

    @staticmethod
    def check_not_reserved_id(version_id):
        revision.check_not_reserved_id(version_id)

    def _check_lines_not_unicode(self, lines):
        """Check that lines being added to a versioned file are not unicode."""
        for line in lines:
            if line.__class__ is not str:
                raise errors.BzrBadParameterUnicode("lines")

    def _check_lines_are_lines(self, lines):
        """Check that the lines really are full lines without inline EOL."""
        for line in lines:
            if '\n' in line[:-1]:
                raise errors.BzrBadParameterContainsNewline("lines")

    def get_parent_map(self, keys):
        """Get a map of the parents of keys.

        :param keys: The keys to look up parents for.
        :return: A mapping from keys to parents. Absent keys are absent from
            the mapping.
        """
        raise NotImplementedError(self.get_parent_map)

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
        raise NotImplementedError(self.get_record_stream)

    def get_sha1s(self, keys):
        """Get the sha1's of the texts for the given keys.

        :param keys: The names of the keys to lookup
        :return: a dict from key to sha1 digest. Keys of texts which are not
            present in the store are not present in the returned
            dictionary.
        """
        raise NotImplementedError(self.get_sha1s)

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert. 
        :return: None
        :seealso VersionedFile.get_record_stream:
        """
        raise NotImplementedError

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
        raise NotImplementedError(self.iter_lines_added_or_present_in_keys)

    def keys(self):
        """Return a iterable of the keys for all the contained texts."""
        raise NotImplementedError(self.keys)

    def make_mpdiffs(self, keys):
        """Create multiparent diffs for specified keys."""
        keys_order = tuple(keys)
        keys = frozenset(keys)
        knit_keys = set(keys)
        parent_map = self.get_parent_map(keys)
        for parent_keys in parent_map.itervalues():
            if parent_keys:
                knit_keys.update(parent_keys)
        missing_keys = keys - set(parent_map)
        if missing_keys:
            raise errors.RevisionNotPresent(list(missing_keys)[0], self)
        # We need to filter out ghosts, because we can't diff against them.
        maybe_ghosts = knit_keys - keys
        ghosts = maybe_ghosts - set(self.get_parent_map(maybe_ghosts))
        knit_keys.difference_update(ghosts)
        lines = {}
        split_lines = osutils.split_lines
        for record in self.get_record_stream(knit_keys, 'topological', True):
            lines[record.key] = split_lines(record.get_bytes_as('fulltext'))
            # line_block_dict = {}
            # for parent, blocks in record.extract_line_blocks():
            #   line_blocks[parent] = blocks
            # line_blocks[record.key] = line_block_dict
        diffs = []
        for key in keys_order:
            target = lines[key]
            parents = parent_map[key] or []
            # Note that filtering knit_keys can lead to a parent difference
            # between the creation and the application of the mpdiff.
            parent_lines = [lines[p] for p in parents if p in knit_keys]
            if len(parent_lines) > 0:
                left_parent_blocks = self._extract_blocks(key, parent_lines[0],
                    target)
            else:
                left_parent_blocks = None
            diffs.append(multiparent.MultiParent.from_lines(target,
                parent_lines, left_parent_blocks))
        return diffs

    def _extract_blocks(self, version_id, source, target):
        return None


class ThunkedVersionedFiles(VersionedFiles):
    """Storage for many versioned files thunked onto a 'VersionedFile' class.

    This object allows a single keyspace for accessing the history graph and
    contents of named bytestrings.

    Currently no implementation allows the graph of different key prefixes to
    intersect, but the API does allow such implementations in the future.
    """

    def __init__(self, transport, file_factory, mapper, is_locked):
        """Create a ThunkedVersionedFiles."""
        self._transport = transport
        self._file_factory = file_factory
        self._mapper = mapper
        self._is_locked = is_locked

    def add_lines(self, key, parents, lines, parent_texts=None,
        left_matching_blocks=None, nostore_sha=None, random_id=False,
        check_content=True):
        """See VersionedFiles.add_lines()."""
        path = self._mapper.map(key)
        version_id = key[-1]
        parents = [parent[-1] for parent in parents]
        vf = self._get_vf(path)
        try:
            try:
                return vf.add_lines_with_ghosts(version_id, parents, lines,
                    parent_texts=parent_texts,
                    left_matching_blocks=left_matching_blocks,
                    nostore_sha=nostore_sha, random_id=random_id,
                    check_content=check_content)
            except NotImplementedError:
                return vf.add_lines(version_id, parents, lines,
                    parent_texts=parent_texts,
                    left_matching_blocks=left_matching_blocks,
                    nostore_sha=nostore_sha, random_id=random_id,
                    check_content=check_content)
        except errors.NoSuchFile:
            # parent directory may be missing, try again.
            self._transport.mkdir(osutils.dirname(path))
            try:
                return vf.add_lines_with_ghosts(version_id, parents, lines,
                    parent_texts=parent_texts,
                    left_matching_blocks=left_matching_blocks,
                    nostore_sha=nostore_sha, random_id=random_id,
                    check_content=check_content)
            except NotImplementedError:
                return vf.add_lines(version_id, parents, lines,
                    parent_texts=parent_texts,
                    left_matching_blocks=left_matching_blocks,
                    nostore_sha=nostore_sha, random_id=random_id,
                    check_content=check_content)

    def annotate(self, key):
        """Return a list of (version-key, line) tuples for the text of key.

        :raise RevisionNotPresent: If the key is not present.
        """
        prefix = key[:-1]
        path = self._mapper.map(prefix)
        vf = self._get_vf(path)
        origins = vf.annotate(key[-1])
        result = []
        for origin, line in origins:
            result.append((prefix + (origin,), line))
        return result

    def check(self, progress_bar=None):
        """See VersionedFiles.check()."""
        for prefix, vf in self._iter_all_components():
            vf.check()

    def get_parent_map(self, keys):
        """Get a map of the parents of keys.

        :param keys: The keys to look up parents for.
        :return: A mapping from keys to parents. Absent keys are absent from
            the mapping.
        """
        prefixes = self._partition_keys(keys)
        result = {}
        for prefix, suffixes in prefixes.items():
            path = self._mapper.map(prefix)
            vf = self._get_vf(path)
            parent_map = vf.get_parent_map(suffixes)
            for key, parents in parent_map.items():
                result[prefix + (key,)] = tuple(
                    prefix + (parent,) for parent in parents)
        return result

    def _get_vf(self, path):
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        return self._file_factory(path, self._transport, create=True,
            get_scope=lambda:None)

    def _partition_keys(self, keys):
        """Turn keys into a dict of prefix:suffix_list."""
        result = {}
        for key in keys:
            prefix_keys = result.setdefault(key[:-1], [])
            prefix_keys.append(key[-1])
        return result

    def _get_all_prefixes(self):
        # Identify all key prefixes.
        # XXX: A bit hacky, needs polish.
        if type(self._mapper) == ConstantMapper:
            paths = [self._mapper.map(())]
            prefixes = [()]
        else:
            relpaths = set()
            for quoted_relpath in self._transport.iter_files_recursive():
                path, ext = os.path.splitext(quoted_relpath)
                relpaths.add(path)
            paths = list(relpaths)
            prefixes = [self._mapper.unmap(path) for path in paths]
        return zip(paths, prefixes)

    def get_record_stream(self, keys, ordering, include_delta_closure):
        """See VersionedFiles.get_record_stream()."""
        # Ordering will be taken care of by each partitioned store; group keys
        # by partition.
        keys = sorted(keys)
        for prefix, suffixes, vf in self._iter_keys_vf(keys):
            suffixes = [(suffix,) for suffix in suffixes]
            for record in vf.get_record_stream(suffixes, ordering,
                include_delta_closure):
                if record.parents is not None:
                    record.parents = tuple(
                        prefix + parent for parent in record.parents)
                record.key = prefix + record.key
                yield record

    def _iter_keys_vf(self, keys):
        prefixes = self._partition_keys(keys)
        sha1s = {}
        for prefix, suffixes in prefixes.items():
            path = self._mapper.map(prefix)
            vf = self._get_vf(path)
            yield prefix, suffixes, vf

    def get_sha1s(self, keys):
        """See VersionedFiles.get_sha1s()."""
        sha1s = {}
        for prefix,suffixes, vf in self._iter_keys_vf(keys):
            vf_sha1s = vf.get_sha1s(suffixes)
            for suffix, sha1 in vf_sha1s.iteritems():
                sha1s[prefix + (suffix,)] = sha1
        return sha1s

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert. 
        :return: None
        :seealso VersionedFile.get_record_stream:
        """
        for record in stream:
            prefix = record.key[:-1]
            key = record.key[-1:]
            if record.parents is not None:
                parents = [parent[-1:] for parent in record.parents]
            else:
                parents = None
            thunk_record = AdapterFactory(key, parents, record)
            path = self._mapper.map(prefix)
            # Note that this parses the file many times; we can do better but
            # as this only impacts weaves in terms of performance, it is
            # tolerable.
            vf = self._get_vf(path)
            vf.insert_record_stream([thunk_record])

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
        for prefix, suffixes, vf in self._iter_keys_vf(keys):
            for line, version in vf.iter_lines_added_or_present_in_versions(suffixes):
                yield line, prefix + (version,)

    def _iter_all_components(self):
        for path, prefix in self._get_all_prefixes():
            yield prefix, self._get_vf(path)

    def keys(self):
        """See VersionedFiles.keys()."""
        result = set()
        for prefix, vf in self._iter_all_components():
            for suffix in vf.versions():
                result.add(prefix + (suffix,))
        return result


class _PlanMergeVersionedFile(VersionedFiles):
    """A VersionedFile for uncommitted and committed texts.

    It is intended to allow merges to be planned with working tree texts.
    It implements only the small part of the VersionedFiles interface used by
    PlanMerge.  It falls back to multiple versionedfiles for data not stored in
    _PlanMergeVersionedFile itself.

    :ivar: fallback_versionedfiles a list of VersionedFiles objects that can be
        queried for missing texts.
    """

    def __init__(self, file_id):
        """Create a _PlanMergeVersionedFile.

        :param file_id: Used with _PlanMerge code which is not yet fully
            tuple-keyspace aware.
        """
        self._file_id = file_id
        # fallback locations
        self.fallback_versionedfiles = []
        # Parents for locally held keys.
        self._parents = {}
        # line data for locally held keys.
        self._lines = {}
        # key lookup providers
        self._providers = [DictParentsProvider(self._parents)]

    def plan_merge(self, ver_a, ver_b, base=None):
        """See VersionedFile.plan_merge"""
        from bzrlib.merge import _PlanMerge
        if base is None:
            return _PlanMerge(ver_a, ver_b, self, (self._file_id,)).plan_merge()
        old_plan = list(_PlanMerge(ver_a, base, self, (self._file_id,)).plan_merge())
        new_plan = list(_PlanMerge(ver_a, ver_b, self, (self._file_id,)).plan_merge())
        return _PlanMerge._subtract_plans(old_plan, new_plan)

    def plan_lca_merge(self, ver_a, ver_b, base=None):
        from bzrlib.merge import _PlanLCAMerge
        graph = Graph(self)
        new_plan = _PlanLCAMerge(ver_a, ver_b, self, (self._file_id,), graph).plan_merge()
        if base is None:
            return new_plan
        old_plan = _PlanLCAMerge(ver_a, base, self, (self._file_id,), graph).plan_merge()
        return _PlanLCAMerge._subtract_plans(list(old_plan), list(new_plan))

    def add_lines(self, key, parents, lines):
        """See VersionedFiles.add_lines

        Lines are added locally, not to fallback versionedfiles.  Also, ghosts
        are permitted.  Only reserved ids are permitted.
        """
        if type(key) is not tuple:
            raise TypeError(key)
        if not revision.is_reserved_id(key[-1]):
            raise ValueError('Only reserved ids may be used')
        if parents is None:
            raise ValueError('Parents may not be None')
        if lines is None:
            raise ValueError('Lines may not be None')
        self._parents[key] = tuple(parents)
        self._lines[key] = lines

    def get_record_stream(self, keys, ordering, include_delta_closure):
        pending = set(keys)
        for key in keys:
            if key in self._lines:
                lines = self._lines[key]
                parents = self._parents[key]
                pending.remove(key)
                yield FulltextContentFactory(key, parents, None,
                    ''.join(lines))
        for versionedfile in self.fallback_versionedfiles:
            for record in versionedfile.get_record_stream(
                pending, 'unordered', True):
                if record.storage_kind == 'absent':
                    continue
                else:
                    pending.remove(record.key)
                    yield record
            if not pending:
                return
        # report absent entries
        for key in pending:
            yield AbsentContentFactory(key)

    def get_parent_map(self, keys):
        """See VersionedFiles.get_parent_map"""
        # We create a new provider because a fallback may have been added.
        # If we make fallbacks private we can update a stack list and avoid
        # object creation thrashing.
        keys = set(keys)
        result = {}
        if revision.NULL_REVISION in keys:
            keys.remove(revision.NULL_REVISION)
            result[revision.NULL_REVISION] = ()
        self._providers = self._providers[:1] + self.fallback_versionedfiles
        result.update(
            _StackedParentsProvider(self._providers).get_parent_map(keys))
        for key, parents in result.iteritems():
            if parents == ():
                result[key] = (revision.NULL_REVISION,)
        return result


class PlanWeaveMerge(TextMerge):
    """Weave merge that takes a plan as its input.
    
    This exists so that VersionedFile.plan_merge is implementable.
    Most callers will want to use WeaveMerge instead.
    """

    def __init__(self, plan, a_marker=TextMerge.A_MARKER,
                 b_marker=TextMerge.B_MARKER):
        TextMerge.__init__(self, a_marker, b_marker)
        self.plan = plan

    def _merge_struct(self):
        lines_a = []
        lines_b = []
        ch_a = ch_b = False

        def outstanding_struct():
            if not lines_a and not lines_b:
                return
            elif ch_a and not ch_b:
                # one-sided change:
                yield(lines_a,)
            elif ch_b and not ch_a:
                yield (lines_b,)
            elif lines_a == lines_b:
                yield(lines_a,)
            else:
                yield (lines_a, lines_b)
       
        # We previously considered either 'unchanged' or 'killed-both' lines
        # to be possible places to resynchronize.  However, assuming agreement
        # on killed-both lines may be too aggressive. -- mbp 20060324
        for state, line in self.plan:
            if state == 'unchanged':
                # resync and flush queued conflicts changes if any
                for struct in outstanding_struct():
                    yield struct
                lines_a = []
                lines_b = []
                ch_a = ch_b = False
                
            if state == 'unchanged':
                if line:
                    yield ([line],)
            elif state == 'killed-a':
                ch_a = True
                lines_b.append(line)
            elif state == 'killed-b':
                ch_b = True
                lines_a.append(line)
            elif state == 'new-a':
                ch_a = True
                lines_a.append(line)
            elif state == 'new-b':
                ch_b = True
                lines_b.append(line)
            elif state == 'conflicted-a':
                ch_b = ch_a = True
                lines_a.append(line)
            elif state == 'conflicted-b':
                ch_b = ch_a = True
                lines_b.append(line)
            else:
                if state not in ('irrelevant', 'ghost-a', 'ghost-b',
                        'killed-base', 'killed-both'):
                    raise AssertionError(state)
        for struct in outstanding_struct():
            yield struct


class WeaveMerge(PlanWeaveMerge):
    """Weave merge that takes a VersionedFile and two versions as its input."""

    def __init__(self, versionedfile, ver_a, ver_b, 
        a_marker=PlanWeaveMerge.A_MARKER, b_marker=PlanWeaveMerge.B_MARKER):
        plan = versionedfile.plan_merge(ver_a, ver_b)
        PlanWeaveMerge.__init__(self, plan, a_marker, b_marker)


class VirtualVersionedFiles(VersionedFiles):
    """Dummy implementation for VersionedFiles that uses other functions for 
    obtaining fulltexts and parent maps.

    This is always on the bottom of the stack and uses string keys 
    (rather than tuples) internally.
    """

    def __init__(self, get_parent_map, get_lines):
        """Create a VirtualVersionedFiles.

        :param get_parent_map: Same signature as Repository.get_parent_map.
        :param get_lines: Should return lines for specified key or None if 
                          not available.
        """
        super(VirtualVersionedFiles, self).__init__()
        self._get_parent_map = get_parent_map
        self._get_lines = get_lines
        
    def check(self, progressbar=None):
        """See VersionedFiles.check.

        :note: Always returns True for VirtualVersionedFiles.
        """
        return True

    def add_mpdiffs(self, records):
        """See VersionedFiles.mpdiffs.

        :note: Not implemented for VirtualVersionedFiles.
        """
        raise NotImplementedError(self.add_mpdiffs)

    def get_parent_map(self, keys):
        """See VersionedFiles.get_parent_map."""
        return dict([((k,), tuple([(p,) for p in v]))
            for k,v in self._get_parent_map([k for (k,) in keys]).iteritems()])

    def get_sha1s(self, keys):
        """See VersionedFiles.get_sha1s."""
        ret = {}
        for (k,) in keys:
            lines = self._get_lines(k)
            if lines is not None:
                if not isinstance(lines, list):
                    raise AssertionError
                ret[(k,)] = osutils.sha_strings(lines)
        return ret

    def get_record_stream(self, keys, ordering, include_delta_closure):
        """See VersionedFiles.get_record_stream."""
        for (k,) in list(keys):
            lines = self._get_lines(k)
            if lines is not None:
                if not isinstance(lines, list):
                    raise AssertionError
                yield FulltextContentFactory((k,), None, 
                        sha1=osutils.sha_strings(lines),
                        text=''.join(lines))
            else:
                yield AbsentContentFactory((k,))



