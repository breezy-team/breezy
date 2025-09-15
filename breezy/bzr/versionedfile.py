# Copyright (C) 2006-2011 Canonical Ltd
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

"""Versioned text file storage api."""

import functools
import itertools
import os
from copy import copy
from io import BytesIO
from typing import Any, Optional
from zlib import adler32

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import fastbencode as bencode

from breezy.bzr import (
    multiparent,
    )
""",
)
from vcsgraph import (
    graph as _mod_graph,
)
from vcsgraph import (
    known_graph as _mod_known_graph,
)

from .. import errors, osutils, revision, urlutils
from .. import transport as _mod_transport
from .._bzr_rs import versionedfile as _versionedfile_rs
from ..registry import Registry
from ..textmerge import TextMerge
from . import index

FulltextContentFactory = _versionedfile_rs.FulltextContentFactory
ChunkedContentFactory = _versionedfile_rs.ChunkedContentFactory
AbsentContentFactory = _versionedfile_rs.AbsentContentFactory
record_to_fulltext_bytes = _versionedfile_rs.record_to_fulltext_bytes
fulltext_network_to_record = _versionedfile_rs.fulltext_network_to_record


adapter_registry = Registry[tuple[str, str], Any, None]()
adapter_registry.register_lazy(
    ("knit-annotated-delta-gz", "knit-delta-gz"),
    "breezy.bzr.knit",
    "DeltaAnnotatedToUnannotated",
)
adapter_registry.register_lazy(
    ("knit-annotated-ft-gz", "knit-ft-gz"),
    "breezy.bzr.knit",
    "FTAnnotatedToUnannotated",
)
for target_storage_kind in ("fulltext", "chunked", "lines"):
    adapter_registry.register_lazy(
        ("knit-delta-gz", target_storage_kind),
        "breezy.bzr.knit",
        "DeltaPlainToFullText",
    )
    adapter_registry.register_lazy(
        ("knit-ft-gz", target_storage_kind), "breezy.bzr.knit", "FTPlainToFullText"
    )
    adapter_registry.register_lazy(
        ("knit-annotated-ft-gz", target_storage_kind),
        "breezy.bzr.knit",
        "FTAnnotatedToFullText",
    )
    adapter_registry.register_lazy(
        ("knit-annotated-delta-gz", target_storage_kind),
        "breezy.bzr.knit",
        "DeltaAnnotatedToFullText",
    )


class UnavailableRepresentation(errors.InternalBzrError):
    """Raised when a requested content encoding is not available.

    This error occurs when trying to access content in a specific encoding
    that is not supported or available for the given key.
    """

    _fmt = (
        "The encoding '%(wanted)s' is not available for key %(key)s which "
        "is encoded as '%(native)s'."
    )

    def __init__(self, key, wanted, native):
        """Initialize an UnavailableRepresentation error.

        Args:
            key: The content key that was requested.
            wanted: The encoding that was requested.
            native: The encoding that is actually available.
        """
        errors.InternalBzrError.__init__(self)
        self.wanted = wanted
        self.native = native
        self.key = key


class ExistingContent(errors.BzrError):
    """Raised when attempting to insert content that already exists.

    This error occurs when trying to add content to a versioned file
    that has already been stored.
    """

    _fmt = "The content being inserted is already present."


class ContentFactory:
    """Abstract interface for insertion and retrieval from a VersionedFile.

    :ivar sha1: None, or the sha1 of the content fulltext.
    :ivar size: None, or the size of the content fulltext.
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

    def __init__(self) -> None:
        """Create a ContentFactory."""
        self.sha1: Optional[bytes] = None
        self.size: Optional[int] = None
        self.storage_kind: Optional[str] = None
        self.key: Optional[tuple[bytes, ...]] = None
        self.parents = None

    def map_key(self, cb):
        """Add prefix to all keys."""
        if self.key is not None:
            self.key = cb(self.key)
        if self.parents is not None:
            self.parents = tuple([cb(parent) for parent in self.parents])
        return self


class FileContentFactory(ContentFactory):
    """File-based content factory."""

    def __init__(self, key, parents, fileobj, sha1=None, size=None):
        """Initialize a FileContentFactory.

        Args:
            key: Unique identifier for this content.
            parents: Parent keys for this content.
            fileobj: File-like object containing the content data.
            sha1: SHA1 hash of the content (optional).
            size: Size of the content in bytes (optional).
        """
        self.key = key
        self.parents = parents
        self.file = fileobj
        self.storage_kind = "file"
        self.sha1 = sha1
        self.size = size
        self._needs_reset = False

    def get_bytes_as(self, storage_kind):
        """Get the content bytes in the specified storage format.

        Args:
            storage_kind: The desired storage format ('fulltext', 'chunked', 'lines').

        Returns:
            bytes or list: The content data in the requested format.

        Raises:
            UnavailableRepresentation: If the requested storage kind is not supported.
        """
        if self._needs_reset:
            self.file.seek(0)
        self._needs_reset = True
        if storage_kind == "fulltext":
            return self.file.read()
        elif storage_kind == "chunked":
            return list(osutils.file_iterator(self.file))
        elif storage_kind == "lines":
            return list(self.file.readlines())
        raise UnavailableRepresentation(self.key, storage_kind, self.storage_kind)

    def iter_bytes_as(self, storage_kind):
        """Iterate over content bytes in the specified storage format.

        Args:
            storage_kind: The desired storage format ('chunked', 'lines').

        Returns:
            iterator: Iterator over the content data in the requested format.

        Raises:
            UnavailableRepresentation: If the requested storage kind is not supported.
        """
        if self._needs_reset:
            self.file.seek(0)
        self._needs_reset = True
        if storage_kind == "chunked":
            return osutils.file_iterator(self.file)
        elif storage_kind == "lines":
            return self.file
        raise UnavailableRepresentation(self.key, storage_kind, self.storage_kind)


class AdapterFactory(ContentFactory):
    """A content factory to adapt between key prefix's."""

    def __init__(self, key, parents, adapted):
        """Create an adapter factory instance."""
        self.key = key
        self.parents = parents
        self._adapted = adapted

    def __getattr__(self, attr):
        """Return a member from the adapted object."""
        if attr in ("key", "parents"):
            return self.__dict__[attr]
        else:
            return getattr(self._adapted, attr)


def filter_absent(record_stream):
    """Adapt a record stream to remove absent records."""
    for record in record_stream:
        if record.storage_kind != "absent":
            yield record


class _MPDiffGenerator:
    """Pull out the functionality for generating mp_diffs."""

    def __init__(self, vf, keys):
        self.vf = vf
        # This is the order the keys were requested in
        self.ordered_keys = tuple(keys)
        # keys + their parents, what we need to compute the diffs
        self.needed_keys = ()
        # Map from key: mp_diff
        self.diffs = {}
        # Map from key: parents_needed (may have ghosts)
        self.parent_map = {}
        # Parents that aren't present
        self.ghost_parents = ()
        # Map from parent_key => number of children for this text
        self.refcounts = {}
        # Content chunks that are cached while we still need them
        self.chunks = {}

    def _find_needed_keys(self):
        """Find the set of keys we need to request.

        This includes all the original keys passed in, and the non-ghost
        parents of those keys.

        :return: (needed_keys, refcounts)
            needed_keys is the set of all texts we need to extract
            refcounts is a dict of {key: num_children} letting us know when we
                no longer need to cache a given parent text
        """
        # All the keys and their parents
        needed_keys = set(self.ordered_keys)
        parent_map = self.vf.get_parent_map(needed_keys)
        self.parent_map = parent_map
        # TODO: Should we be using a different construct here? I think this
        #       uses difference_update internally, and we expect the result to
        #       be tiny
        missing_keys = needed_keys.difference(parent_map)
        if missing_keys:
            raise errors.RevisionNotPresent(list(missing_keys)[0], self.vf)
        # Parents that might be missing. They are allowed to be ghosts, but we
        # should check for them
        refcounts = {}
        setdefault = refcounts.setdefault
        just_parents = set()
        for _child_key, parent_keys in parent_map.items():
            if not parent_keys:
                # parent_keys may be None if a given VersionedFile claims to
                # not support graph operations.
                continue
            just_parents.update(parent_keys)
            needed_keys.update(parent_keys)
            for p in parent_keys:
                refcounts[p] = setdefault(p, 0) + 1
        just_parents.difference_update(parent_map)
        # Remove any parents that are actually ghosts from the needed set
        self.present_parents = set(self.vf.get_parent_map(just_parents))
        self.ghost_parents = just_parents.difference(self.present_parents)
        needed_keys.difference_update(self.ghost_parents)
        self.needed_keys = needed_keys
        self.refcounts = refcounts
        return needed_keys, refcounts

    def _compute_diff(self, key, parent_lines, lines):
        """Compute a single mp_diff, and store it in self._diffs."""
        if len(parent_lines) > 0:
            # XXX: _extract_blocks is not usefully defined anywhere...
            #      It was meant to extract the left-parent diff without
            #      having to recompute it for Knit content (pack-0.92,
            #      etc). That seems to have regressed somewhere
            left_parent_blocks = self.vf._extract_blocks(key, parent_lines[0], lines)
        else:
            left_parent_blocks = None
        diff = multiparent.MultiParent.from_lines(
            lines, parent_lines, left_parent_blocks
        )
        self.diffs[key] = diff

    def _process_one_record(self, key, this_chunks):
        parent_keys = None
        if key in self.parent_map:
            # This record should be ready to diff, since we requested
            # content in 'topological' order
            parent_keys = self.parent_map.pop(key)
            # If a VersionedFile claims 'no-graph' support, then it may return
            # None for any parent request, so we replace it with an empty tuple
            if parent_keys is None:
                parent_keys = ()
            parent_lines = []
            for p in parent_keys:
                # Alternatively we could check p not in self.needed_keys, but
                # ghost_parents should be tiny versus huge
                if p in self.ghost_parents:
                    continue
                refcount = self.refcounts[p]
                if refcount == 1:  # Last child reference
                    self.refcounts.pop(p)
                    parent_chunks = self.chunks.pop(p)
                else:
                    self.refcounts[p] = refcount - 1
                    parent_chunks = self.chunks[p]
                p_lines = osutils.chunks_to_lines(parent_chunks)
                # TODO: Should we cache the line form? We did the
                #       computation to get it, but storing it this way will
                #       be less memory efficient...
                parent_lines.append(p_lines)
                del p_lines
            lines = osutils.chunks_to_lines(this_chunks)
            # Since we needed the lines, we'll go ahead and cache them this way
            this_chunks = lines
            self._compute_diff(key, parent_lines, lines)
            del lines
        # Is this content required for any more children?
        if key in self.refcounts:
            self.chunks[key] = this_chunks

    def _extract_diffs(self):
        needed_keys, _refcounts = self._find_needed_keys()
        for record in self.vf.get_record_stream(needed_keys, "topological", True):
            if record.storage_kind == "absent":
                raise errors.RevisionNotPresent(record.key, self.vf)
            self._process_one_record(record.key, record.get_bytes_as("chunked"))

    def compute_diffs(self):
        self._extract_diffs()
        dpop = self.diffs.pop
        return [dpop(k) for k in self.ordered_keys]


class VersionedFile:
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
        """Check that a version ID is not a reserved identifier.

        Args:
            version_id: The version ID to check, or None.

        Raises:
            ValueError: If version_id is a reserved identifier.
        """
        if version_id is not None:
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

    def add_lines(
        self,
        version_id,
        parents,
        lines,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
    ):
        r"""Add a single text on top of the versioned file.

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
        return self._add_lines(
            version_id,
            parents,
            lines,
            parent_texts,
            left_matching_blocks,
            nostore_sha,
            random_id,
            check_content,
        )

    def _add_lines(
        self,
        version_id,
        parents,
        lines,
        parent_texts,
        left_matching_blocks,
        nostore_sha,
        random_id,
        check_content,
    ):
        """Helper to do the class specific add_lines."""
        raise NotImplementedError(self.add_lines)

    def add_lines_with_ghosts(
        self,
        version_id,
        parents,
        lines,
        parent_texts=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
        left_matching_blocks=None,
    ):
        """Add lines to the versioned file, allowing ghosts to be present.

        This takes the same parameters as add_lines and returns the same.
        """
        self._check_write_ok()
        return self._add_lines_with_ghosts(
            version_id,
            parents,
            lines,
            parent_texts,
            nostore_sha,
            random_id,
            check_content,
            left_matching_blocks,
        )

    def _add_lines_with_ghosts(
        self,
        version_id,
        parents,
        lines,
        parent_texts,
        nostore_sha,
        random_id,
        check_content,
        left_matching_blocks,
    ):
        """Helper to do class specific add_lines_with_ghosts."""
        raise NotImplementedError(self.add_lines_with_ghosts)

    def check(self, progress_bar=None):
        """Check the versioned file for integrity."""
        raise NotImplementedError(self.check)

    def _check_lines_not_unicode(self, lines):
        """Check that lines being added to a versioned file are not unicode."""
        for line in lines:
            if not isinstance(line, bytes):
                raise errors.BzrBadParameterUnicode("lines")

    def _check_lines_are_lines(self, lines):
        """Check that the lines really are full lines without inline EOL."""
        for line in lines:
            if b"\n" in line[:-1]:
                raise errors.BzrBadParameterContainsNewline("lines")

    def get_format_signature(self):
        """Get a text description of the data encoding in this file.

        :since: 0.90
        """
        raise NotImplementedError(self.get_format_signature)

    def make_mpdiffs(self, version_ids):
        """Create multiparent diffs for specified versions."""
        # XXX: Can't use _MPDiffGenerator just yet. This is because version_ids
        #      is a list of strings, not keys. And while self.get_record_stream
        #      is supported, it takes *keys*, while self.get_parent_map() takes
        #      strings... *sigh*
        knit_versions = set()
        knit_versions.update(version_ids)
        parent_map = self.get_parent_map(version_ids)
        for version_id in version_ids:
            try:
                knit_versions.update(parent_map[version_id])
            except KeyError as e:
                raise errors.RevisionNotPresent(version_id, self) from e
        # We need to filter out ghosts, because we can't diff against them.
        knit_versions = set(self.get_parent_map(knit_versions))
        lines = dict(zip(knit_versions, self._get_lf_split_line_list(knit_versions)))
        diffs = []
        for version_id in version_ids:
            target = lines[version_id]
            try:
                parents = [
                    lines[p] for p in parent_map[version_id] if p in knit_versions
                ]
            except KeyError as e:
                # I don't know how this could ever trigger.
                # parent_map[version_id] was already triggered in the previous
                # for loop, and lines[p] has the 'if p in knit_versions' check,
                # so we again won't have a KeyError.
                raise errors.RevisionNotPresent(version_id, self) from e
            if len(parents) > 0:
                left_parent_blocks = self._extract_blocks(
                    version_id, parents[0], target
                )
            else:
                left_parent_blocks = None
            diffs.append(
                multiparent.MultiParent.from_lines(target, parents, left_parent_blocks)
            )
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
        for version, parent_ids, _expected_sha1, mpdiff in records:
            versions.append(version)
            mpvf.add_diff(mpdiff, version, parent_ids)
        needed_parents = set()
        for _version, parent_ids, _expected_sha1, _mpdiff in records:
            needed_parents.update(p for p in parent_ids if not mpvf.has_version(p))
        present_parents = set(self.get_parent_map(needed_parents))
        for parent_id, lines in zip(
            present_parents, self._get_lf_split_line_list(present_parents)
        ):
            mpvf.add_version(lines, parent_id, [])
        for (version, parent_ids, _expected_sha1, mpdiff), lines in zip(
            records, mpvf.get_line_list(versions)
        ):
            if len(parent_ids) == 1:
                left_matching_blocks = list(
                    mpdiff.get_matching_blocks(
                        0, mpvf.get_diff(parent_ids[0]).num_lines()
                    )
                )
            else:
                left_matching_blocks = None
            try:
                _, _, version_text = self.add_lines_with_ghosts(
                    version,
                    parent_ids,
                    lines,
                    vf_parents,
                    left_matching_blocks=left_matching_blocks,
                )
            except NotImplementedError:
                # The vf can't handle ghosts, so add lines normally, which will
                # (reasonably) fail if there are ghosts in the data.
                _, _, version_text = self.add_lines(
                    version,
                    parent_ids,
                    lines,
                    vf_parents,
                    left_matching_blocks=left_matching_blocks,
                )
            vf_parents[version] = version_text
        sha1s = self.get_sha1s(versions)
        for version, _parent_ids, expected_sha1, _mpdiff in records:
            if expected_sha1 != sha1s[version]:
                raise errors.VersionedFileInvalidChecksum(version)

    def get_text(self, version_id):
        """Return version contents as a text string.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return b"".join(self.get_lines(version_id))

    get_string = get_text

    def get_texts(self, version_ids):
        """Return the texts of listed versions as a list of strings.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return [b"".join(self.get_lines(v)) for v in version_ids]

    def get_lines(self, version_id):
        """Return version contents as a sequence of lines.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_lines)

    def _get_lf_split_line_list(self, version_ids):
        return [BytesIO(t).readlines() for t in self.get_texts(version_ids)]

    def get_ancestry(self, version_ids):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history.
        """
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
        except KeyError as e:
            raise errors.RevisionNotPresent(version_id, self) from e

    def annotate(self, version_id):
        """Return a list of (version-id, line) tuples for version_id.

        :raise RevisionNotPresent: If the given version is
        not present in file history.
        """
        raise NotImplementedError(self.annotate)

    def iter_lines_added_or_present_in_versions(self, version_ids=None, pb=None):
        r"""Iterate over the lines in the versioned file from version_ids.

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

    def plan_merge(self, ver_a, ver_b, base=None):
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

    def weave_merge(
        self, plan, a_marker=TextMerge.A_MARKER, b_marker=TextMerge.B_MARKER
    ):
        """Merge text using a weave merge algorithm.

        Args:
            plan: The merge plan to execute.
            a_marker: Marker for 'A' side conflicts (optional).
            b_marker: Marker for 'B' side conflicts (optional).

        Returns:
            list: Merged lines of text.
        """
        return PlanWeaveMerge(plan, a_marker, b_marker).merge_lines()[0]


class RecordingVersionedFilesDecorator:
    """A minimal versioned files that records calls made on it.

    Only enough methods have been added to support tests using it to date.

    :ivar calls: A list of the calls made; can be reset at any time by
        assigning [] to it.
    """

    def __init__(self, backing_vf):
        """Create a RecordingVersionedFilesDecorator decorating backing_vf.

        :param backing_vf: The versioned file to answer all methods.
        """
        self._backing_vf = backing_vf
        self.calls = []

    def add_lines(
        self,
        key,
        parents,
        lines,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
    ):
        """Add lines to the versioned file and record the call.

        Args:
            key: The key for the new version.
            parents: Parent keys for the new version.
            lines: The text lines to add.
            parent_texts: Parent text data (optional).
            left_matching_blocks: Matching blocks for delta compression (optional).
            nostore_sha: SHA to skip storing if duplicate (optional).
            random_id: Whether to use a random ID (optional).
            check_content: Whether to validate content (optional).

        Returns:
            The result from the backing versioned file.
        """
        self.calls.append(
            (
                "add_lines",
                key,
                parents,
                lines,
                parent_texts,
                left_matching_blocks,
                nostore_sha,
                random_id,
                check_content,
            )
        )
        return self._backing_vf.add_lines(
            key,
            parents,
            lines,
            parent_texts,
            left_matching_blocks,
            nostore_sha,
            random_id,
            check_content,
        )

    def add_content(
        self,
        factory,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
    ):
        """Add content from a factory and record the call.

        Args:
            factory: ContentFactory providing the content.
            parent_texts: Parent text data (optional).
            left_matching_blocks: Matching blocks for delta compression (optional).
            nostore_sha: SHA to skip storing if duplicate (optional).
            random_id: Whether to use a random ID (optional).
            check_content: Whether to validate content (optional).

        Returns:
            The result from the backing versioned file.
        """
        self.calls.append(
            (
                "add_content",
                factory,
                parent_texts,
                left_matching_blocks,
                nostore_sha,
                random_id,
                check_content,
            )
        )
        return self._backing_vf.add_content(
            factory,
            parent_texts,
            left_matching_blocks,
            nostore_sha,
            random_id,
            check_content,
        )

    def check(self):
        """Check the backing versioned file for consistency."""
        self._backing_vf.check()

    def get_parent_map(self, keys):
        """Get parent mapping for keys and record the call.

        Args:
            keys: Keys to get parent mapping for.

        Returns:
            dict: Mapping of keys to their parents.
        """
        self.calls.append(("get_parent_map", copy(keys)))
        return self._backing_vf.get_parent_map(keys)

    def get_record_stream(self, keys, sort_order, include_delta_closure):
        """Get a stream of records and record the call.

        Args:
            keys: Keys to get records for.
            sort_order: How to sort the results.
            include_delta_closure: Whether to include delta closure.

        Returns:
            Iterator over record data.
        """
        self.calls.append(
            ("get_record_stream", list(keys), sort_order, include_delta_closure)
        )
        return self._backing_vf.get_record_stream(
            keys, sort_order, include_delta_closure
        )

    def get_sha1s(self, keys):
        """Get SHA1 hashes for keys and record the call.

        Args:
            keys: Keys to get SHA1s for.

        Returns:
            dict: Mapping of keys to their SHA1 hashes.
        """
        self.calls.append(("get_sha1s", copy(keys)))
        return self._backing_vf.get_sha1s(keys)

    def iter_lines_added_or_present_in_keys(self, keys, pb=None):
        """Iterate over lines added or present in keys and record the call.

        Args:
            keys: Keys to iterate over.
            pb: Optional progress bar.

        Returns:
            Iterator over lines.
        """
        self.calls.append(("iter_lines_added_or_present_in_keys", copy(keys)))
        return self._backing_vf.iter_lines_added_or_present_in_keys(keys, pb=pb)

    def keys(self):
        """Get all keys and record the call.

        Returns:
            Iterable of all keys in the versioned file.
        """
        self.calls.append(("keys",))
        return self._backing_vf.keys()


class OrderingVersionedFilesDecorator(RecordingVersionedFilesDecorator):
    """A VF that records calls, and returns keys in specific order.

    :ivar calls: A list of the calls made; can be reset at any time by
        assigning [] to it.
    """

    def __init__(self, backing_vf, key_priority):
        """Create a RecordingVersionedFilesDecorator decorating backing_vf.

        :param backing_vf: The versioned file to answer all methods.
        :param key_priority: A dictionary defining what order keys should be
            returned from an 'unordered' get_record_stream request.
            Keys with lower priority are returned first, keys not present in
            the map get an implicit priority of 0, and are returned in
            lexicographical order.
        """
        RecordingVersionedFilesDecorator.__init__(self, backing_vf)
        self._key_priority = key_priority

    def get_record_stream(self, keys, sort_order, include_delta_closure):
        """Get a stream of records with custom ordering and record the call.

        Args:
            keys: Keys to get records for.
            sort_order: How to sort the results ('unordered' uses key_priority).
            include_delta_closure: Whether to include delta closure.

        Yields:
            Record data in the specified order.
        """
        self.calls.append(
            ("get_record_stream", list(keys), sort_order, include_delta_closure)
        )
        if sort_order == "unordered":

            def sort_key(key):
                return (self._key_priority.get(key, 0), key)

            # Use a defined order by asking for the keys one-by-one from the
            # backing_vf
            for key in sorted(keys, key=sort_key):
                yield from self._backing_vf.get_record_stream(
                    [key], "unordered", include_delta_closure
                )
        else:
            yield from self._backing_vf.get_record_stream(
                keys, sort_order, include_delta_closure
            )


class KeyMapper:
    """KeyMappers map between keys and underlying partitioned storage."""

    def map(self, key):
        """Map key to an underlying storage identifier.

        :param key: A key tuple e.g. (b'file-id', b'revision-id').
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
        return urlutils.quote(self._map(key))

    def unmap(self, partition_id):
        """See KeyMapper.unmap()."""
        return self._unmap(urlutils.unquote(partition_id))


class PrefixMapper(URLEscapeMapper):
    """A key mapper that extracts the first component of a key.

    This mapper is for use with a transport based backend.
    """

    def _map(self, key):
        """See KeyMapper.map()."""
        return key[0].decode("utf-8")

    def _unmap(self, partition_id):
        """See KeyMapper.unmap()."""
        return (partition_id.encode("utf-8"),)


class HashPrefixMapper(URLEscapeMapper):
    """A key mapper that combines the first component of a key with a hash.

    This mapper is for use with a transport based backend.
    """

    def _map(self, key):
        """See KeyMapper.map()."""
        prefix = self._escape(key[0])
        return f"{adler32(prefix) & 255:02x}/{prefix.decode('utf-8')}"

    def _escape(self, prefix):
        """No escaping needed here."""
        return prefix

    def _unmap(self, partition_id):
        """See KeyMapper.unmap()."""
        return (self._unescape(osutils.basename(partition_id)).encode("utf-8"),)

    def _unescape(self, basename):
        """No unescaping needed for HashPrefixMapper."""
        return basename


class HashEscapedPrefixMapper(HashPrefixMapper):
    """Combines the escaped first component of a key with a hash.

    This mapper is for use with a transport based backend.
    """

    _safe = bytearray(b"abcdefghijklmnopqrstuvwxyz0123456789-_@,.")

    def _escape(self, prefix):
        """Turn a key element into a filesystem safe string.

        This is similar to a plain urlutils.quote, except
        it uses specific safe characters, so that it doesn't
        have to translate a lot of valid file ids.
        """
        # @ does not get escaped. This is because it is a valid
        # filesystem character we use all the time, and it looks
        # a lot better than seeing %40 all the time.
        r = [((c in self._safe) and chr(c)) or (f"%{c:02x}") for c in bytearray(prefix)]
        return "".join(r).encode("ascii")

    def _unescape(self, basename):
        """Escaped names are easily unescaped by urlutils."""
        return urlutils.unquote(basename)


def make_versioned_files_factory(versioned_file_factory, mapper):
    """Create a ThunkedVersionedFiles factory.

    This will create a callable which when called creates a
    ThunkedVersionedFiles on a transport, using mapper to access individual
    versioned files, and versioned_file_factory to create each individual file.
    """

    def factory(transport):
        return ThunkedVersionedFiles(
            transport, versioned_file_factory, mapper, lambda: True
        )

    return factory


class VersionedFiles:
    """Storage for many versioned files.

    This object allows a single keyspace for accessing the history graph and
    contents of named bytestrings.

    Currently no implementation allows the graph of different key prefixes to
    intersect, but the API does allow such implementations in the future.

    The keyspace is expressed via simple tuples. Any instance of VersionedFiles
    may have a different length key-size, but that size will be constant for
    all texts added to or retrieved from it. For instance, breezy uses
    instances with a key-size of 2 for storing user files in a repository, with
    the first element the fileid, and the second the version of that file.

    The use of tuples allows a single code base to support several different
    uses with only the mapping logic changing from instance to instance.

    :ivar _immediate_fallback_vfs: For subclasses that support stacking,
        this is a list of other VersionedFiles immediately underneath this
        one.  They may in turn each have further fallbacks.
    """

    def add_lines(
        self,
        key,
        parents,
        lines,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
    ):
        r"""Add a text to the store.

        :param key: The key tuple of the text to add. If the last element is
            None, a CHK string will be generated during the addition.
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

    def add_content(
        self,
        factory,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
    ):
        """Add a text to the store from a chunk iterable.

        :param key: The key tuple of the text to add. If the last element is
            None, a CHK string will be generated during the addition.
        :param parents: The parents key tuples of the text to add.
        :param chunk_iter: An iterable over bytestrings.
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
        raise NotImplementedError(self.add_content)

    def add_mpdiffs(self, records):
        """Add mpdiffs to this VersionedFile.

        Records should be iterables of version, parents, expected_sha1,
        mpdiff. mpdiff should be a MultiParent instance.
        """
        vf_parents = {}
        mpvf = multiparent.MultiMemoryVersionedFile()
        versions = []
        for version, parent_ids, _expected_sha1, mpdiff in records:
            versions.append(version)
            mpvf.add_diff(mpdiff, version, parent_ids)
        needed_parents = set()
        for _version, parent_ids, _expected_sha1, _mpdiff in records:
            needed_parents.update(p for p in parent_ids if not mpvf.has_version(p))
        # It seems likely that adding all the present parents as fulltexts can
        # easily exhaust memory.
        for record in self.get_record_stream(needed_parents, "unordered", True):
            if record.storage_kind == "absent":
                continue
            mpvf.add_version(record.get_bytes_as("lines"), record.key, [])
        for (key, parent_keys, expected_sha1, mpdiff), lines in zip(
            records, mpvf.get_line_list(versions)
        ):
            if len(parent_keys) == 1:
                left_matching_blocks = list(
                    mpdiff.get_matching_blocks(
                        0, mpvf.get_diff(parent_keys[0]).num_lines()
                    )
                )
            else:
                left_matching_blocks = None
            version_sha1, _, version_text = self.add_lines(
                key,
                parent_keys,
                lines,
                vf_parents,
                left_matching_blocks=left_matching_blocks,
            )
            if version_sha1 != expected_sha1:
                raise errors.VersionedFileInvalidChecksum(version)
            vf_parents[key] = version_text

    def annotate(self, key):
        """Return a list of (version-key, line) tuples for the text of key.

        :raise RevisionNotPresent: If the key is not present.
        """
        raise NotImplementedError(self.annotate)

    def check(self, progress_bar=None):
        """Check this object for integrity.

        :param progress_bar: A progress bar to output as the check progresses.
        :param keys: Specific keys within the VersionedFiles to check. When
            this parameter is not None, check() becomes a generator as per
            get_record_stream. The difference to get_record_stream is that
            more or deeper checks will be performed.
        :return: None, or if keys was supplied a generator as per
            get_record_stream.
        """
        raise NotImplementedError(self.check)

    @staticmethod
    def check_not_reserved_id(version_id):
        """Check that a version ID is not a reserved identifier.

        Args:
            version_id: The version ID to check, or None.

        Raises:
            ValueError: If version_id is a reserved identifier.
        """
        if version_id is not None:
            revision.check_not_reserved_id(version_id)

    def clear_cache(self):
        """Clear whatever caches this VersionedFile holds.

        This is generally called after an operation has been performed, when we
        don't expect to be using this versioned file again soon.
        """

    def _check_lines_not_unicode(self, lines):
        """Check that lines being added to a versioned file are not unicode."""
        for line in lines:
            if line.__class__ is not bytes:
                raise errors.BzrBadParameterUnicode("lines")

    def _check_lines_are_lines(self, lines):
        """Check that the lines really are full lines without inline EOL."""
        for line in lines:
            if b"\n" in line[:-1]:
                raise errors.BzrBadParameterContainsNewline("lines")

    def get_known_graph_ancestry(self, keys):
        """Get a KnownGraph instance with the ancestry of keys."""
        # most basic implementation is a loop around get_parent_map
        pending = set(keys)
        parent_map = {}
        while pending:
            this_parent_map = self.get_parent_map(pending)
            parent_map.update(this_parent_map)
            pending = set(itertools.chain.from_iterable(this_parent_map.values()))
            pending.difference_update(parent_map)
        kg = _mod_known_graph.KnownGraph(parent_map)
        return kg

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

    __contains__ = index._has_key_from_parent_map

    def get_missing_compression_parent_keys(self):
        """Return an iterable of keys of missing compression parents.

        Check this after calling insert_record_stream to find out if there are
        any missing compression parents.  If there are, the records that
        depend on them are not able to be inserted safely. The precise
        behaviour depends on the concrete VersionedFiles class in use.

        Classes that do not support this will raise NotImplementedError.
        """
        raise NotImplementedError(self.get_missing_compression_parent_keys)

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert.
        :return: None
        :seealso VersionedFile.get_record_stream:
        """
        raise NotImplementedError

    def iter_lines_added_or_present_in_keys(self, keys, pb=None):
        r"""Iterate over the lines in the versioned files from keys.

        This may return lines from other keys. Each item the returned
        iterator yields is a tuple of a line and a text version that that line
        is present in (not introduced in).

        Ordering of results is in whatever order is most suitable for the
        underlying storage format.

        If a progress bar is supplied, it may be used to indicate progress.
        The caller is responsible for cleaning up progress bars (because this
        is an iterator).

        Notes:
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
        generator = _MPDiffGenerator(self, keys)
        return generator.compute_diffs()

    def get_annotator(self):
        """Get an annotator for this versioned file.

        Returns:
            VersionedFileAnnotator: An annotator instance for this versioned file.
        """
        from .annotate import VersionedFileAnnotator

        return VersionedFileAnnotator(self)

    missing_keys = index._missing_keys_from_parent_map

    def _extract_blocks(self, version_id, source, target):
        return None

    def _transitive_fallbacks(self):
        """Return the whole stack of fallback versionedfiles.

        This VersionedFiles may have a list of fallbacks, but it doesn't
        necessarily know about the whole stack going down, and it can't know
        at open time because they may change after the objects are opened.
        """
        all_fallbacks = []
        for a_vfs in self._immediate_fallback_vfs:
            all_fallbacks.append(a_vfs)
            all_fallbacks.extend(a_vfs._transitive_fallbacks())
        return all_fallbacks


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

    def add_content(
        self,
        factory,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
    ):
        """See VersionedFiles.add_content()."""
        lines = factory.get_bytes_as("lines")
        return self.add_lines(
            factory.key,
            factory.parents,
            lines,
            parent_texts=parent_texts,
            left_matching_blocks=left_matching_blocks,
            nostore_sha=nostore_sha,
            random_id=random_id,
            check_content=True,
        )

    def add_lines(
        self,
        key,
        parents,
        lines,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
    ):
        """See VersionedFiles.add_lines()."""
        path = self._mapper.map(key)
        version_id = key[-1]
        parents = [parent[-1] for parent in parents]
        vf = self._get_vf(path)
        try:
            try:
                return vf.add_lines_with_ghosts(
                    version_id,
                    parents,
                    lines,
                    parent_texts=parent_texts,
                    left_matching_blocks=left_matching_blocks,
                    nostore_sha=nostore_sha,
                    random_id=random_id,
                    check_content=check_content,
                )
            except NotImplementedError:
                return vf.add_lines(
                    version_id,
                    parents,
                    lines,
                    parent_texts=parent_texts,
                    left_matching_blocks=left_matching_blocks,
                    nostore_sha=nostore_sha,
                    random_id=random_id,
                    check_content=check_content,
                )
        except _mod_transport.NoSuchFile:
            # parent directory may be missing, try again.
            self._transport.mkdir(osutils.dirname(path))
            try:
                return vf.add_lines_with_ghosts(
                    version_id,
                    parents,
                    lines,
                    parent_texts=parent_texts,
                    left_matching_blocks=left_matching_blocks,
                    nostore_sha=nostore_sha,
                    random_id=random_id,
                    check_content=check_content,
                )
            except NotImplementedError:
                return vf.add_lines(
                    version_id,
                    parents,
                    lines,
                    parent_texts=parent_texts,
                    left_matching_blocks=left_matching_blocks,
                    nostore_sha=nostore_sha,
                    random_id=random_id,
                    check_content=check_content,
                )

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

    def check(self, progress_bar=None, keys=None):
        """See VersionedFiles.check()."""
        # XXX: This is over-enthusiastic but as we only thunk for Weaves today
        # this is tolerable. Ideally we'd pass keys down to check() and
        # have the older VersiondFile interface updated too.
        for _prefix, vf in self._iter_all_components():
            vf.check()
        if keys is not None:
            return self.get_record_stream(keys, "unordered", True)

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
                    prefix + (parent,) for parent in parents
                )
        return result

    def _get_vf(self, path):
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        return self._file_factory(
            path, self._transport, create=True, get_scope=lambda: None
        )

    def _partition_keys(self, keys):
        """Turn keys into a dict of prefix:suffix_list."""
        result = {}
        for key in keys:
            prefix_keys = result.setdefault(key[:-1], [])
            prefix_keys.append(key[-1])
        return result

    def _iter_all_prefixes(self):
        # Identify all key prefixes.
        # XXX: A bit hacky, needs polish.
        if isinstance(self._mapper, ConstantMapper):
            paths = [self._mapper.map(())]
            prefixes = [()]
        else:
            relpaths = set()
            for quoted_relpath in self._transport.iter_files_recursive():
                path, _ext = os.path.splitext(quoted_relpath)
                relpaths.add(path)
            paths = list(relpaths)
            prefixes = [self._mapper.unmap(path) for path in paths]
        return zip(paths, prefixes)

    def get_record_stream(self, keys, ordering, include_delta_closure):
        """See VersionedFiles.get_record_stream()."""

        # Ordering will be taken care of by each partitioned store; group keys
        # by partition.
        def add_prefix(p, k):
            return p + k

        keys = sorted(keys)
        for prefix, suffixes, vf in self._iter_keys_vf(keys):
            suffixes = [(suffix,) for suffix in suffixes]
            for record in vf.get_record_stream(
                suffixes, ordering, include_delta_closure
            ):
                record.map_key(functools.partial(add_prefix, prefix))
                yield record

    def _iter_keys_vf(self, keys):
        prefixes = self._partition_keys(keys)
        for prefix, suffixes in prefixes.items():
            path = self._mapper.map(prefix)
            vf = self._get_vf(path)
            yield prefix, suffixes, vf

    def get_sha1s(self, keys):
        """See VersionedFiles.get_sha1s()."""
        sha1s = {}
        for prefix, suffixes, vf in self._iter_keys_vf(keys):
            vf_sha1s = vf.get_sha1s(suffixes)
            for suffix, sha1 in vf_sha1s.items():
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
        r"""Iterate over the lines in the versioned files from keys.

        This may return lines from other keys. Each item the returned
        iterator yields is a tuple of a line and a text version that that line
        is present in (not introduced in).

        Ordering of results is in whatever order is most suitable for the
        underlying storage format.

        If a progress bar is supplied, it may be used to indicate progress.
        The caller is responsible for cleaning up progress bars (because this
        is an iterator).

        Notes:
         * Lines are normalised by the underlying store: they will all have \n
           terminators.
         * Lines are returned in arbitrary order.

        :return: An iterator over (line, key).
        """
        for prefix, suffixes, vf in self._iter_keys_vf(keys):
            for line, version in vf.iter_lines_added_or_present_in_versions(suffixes):
                yield line, prefix + (version,)

    def _iter_all_components(self):
        for path, prefix in self._iter_all_prefixes():
            yield prefix, self._get_vf(path)

    def keys(self):
        """See VersionedFiles.keys()."""
        result = set()
        for prefix, vf in self._iter_all_components():
            for suffix in vf.versions():
                result.add(prefix + (suffix,))
        return result


class VersionedFilesWithFallbacks(VersionedFiles):
    """A versioned files implementation that supports fallback sources.

    This class extends VersionedFiles to provide support for fallback
    versioned files that can supply content not present in the primary
    versioned files.
    """

    def without_fallbacks(self):
        """Return a clone of this object without any fallbacks configured."""
        raise NotImplementedError(self.without_fallbacks)

    def add_fallback_versioned_files(self, a_versioned_files):
        """Add a source of texts for texts not present in this knit.

        :param a_versioned_files: A VersionedFiles object.
        """
        raise NotImplementedError(self.add_fallback_versioned_files)

    def get_known_graph_ancestry(self, keys):
        """Get a KnownGraph instance with the ancestry of keys."""
        parent_map, missing_keys = self._index.find_ancestry(keys)
        for fallback in self._transitive_fallbacks():
            if not missing_keys:
                break
            (f_parent_map, f_missing_keys) = fallback._index.find_ancestry(missing_keys)
            parent_map.update(f_parent_map)
            missing_keys = f_missing_keys
        kg = _mod_known_graph.KnownGraph(parent_map)
        return kg


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
        self._providers = [_mod_graph.DictParentsProvider(self._parents)]

    def plan_merge(self, ver_a, ver_b, base=None):
        """See VersionedFile.plan_merge."""
        from ..merge import _PlanMerge

        if base is None:
            return _PlanMerge(ver_a, ver_b, self, (self._file_id,)).plan_merge()
        old_plan = list(_PlanMerge(ver_a, base, self, (self._file_id,)).plan_merge())
        new_plan = list(_PlanMerge(ver_a, ver_b, self, (self._file_id,)).plan_merge())
        return _PlanMerge._subtract_plans(old_plan, new_plan)

    def plan_lca_merge(self, ver_a, ver_b, base=None):
        from ..merge import _PlanLCAMerge

        graph = _mod_graph.Graph(self)
        new_plan = _PlanLCAMerge(
            ver_a, ver_b, self, (self._file_id,), graph
        ).plan_merge()
        if base is None:
            return new_plan
        old_plan = _PlanLCAMerge(
            ver_a, base, self, (self._file_id,), graph
        ).plan_merge()
        return _PlanLCAMerge._subtract_plans(list(old_plan), list(new_plan))

    def add_content(self, factory):
        return self.add_lines(
            factory.key, factory.parents, factory.get_bytes_as("lines")
        )

    def add_lines(self, key, parents, lines):
        """See VersionedFiles.add_lines.

        Lines are added locally, not to fallback versionedfiles.  Also, ghosts
        are permitted.  Only reserved ids are permitted.
        """
        if not isinstance(key, tuple):
            raise TypeError(key)
        if not revision.is_reserved_id(key[-1]):
            raise ValueError("Only reserved ids may be used")
        if parents is None:
            raise ValueError("Parents may not be None")
        if lines is None:
            raise ValueError("Lines may not be None")
        self._parents[key] = tuple(parents)
        self._lines[key] = lines

    def get_record_stream(self, keys, ordering, include_delta_closure):
        pending = set(keys)
        for key in keys:
            if key in self._lines:
                lines = self._lines[key]
                parents = self._parents[key]
                pending.remove(key)
                yield ChunkedContentFactory(key, parents, None, lines)
        for versionedfile in self.fallback_versionedfiles:
            for record in versionedfile.get_record_stream(pending, "unordered", True):
                if record.storage_kind == "absent":
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
        """See VersionedFiles.get_parent_map."""
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
            _mod_graph.StackedParentsProvider(self._providers).get_parent_map(keys)
        )
        for key, parents in result.items():
            if parents == ():
                result[key] = (revision.NULL_REVISION,)
        return result


class PlanWeaveMerge(TextMerge):
    """Weave merge that takes a plan as its input.

    This exists so that VersionedFile.plan_merge is implementable.
    Most callers will want to use WeaveMerge instead.
    """

    def __init__(self, plan, a_marker=TextMerge.A_MARKER, b_marker=TextMerge.B_MARKER):
        """Initialize a PlanWeaveMerge.

        Args:
            plan: The merge plan to execute.
            a_marker: Marker for 'A' side conflicts (optional).
            b_marker: Marker for 'B' side conflicts (optional).
        """
        TextMerge.__init__(self, a_marker, b_marker)
        self.plan = list(plan)

    def _merge_struct(self):
        lines_a = []
        lines_b = []
        ch_a = ch_b = False

        def outstanding_struct():
            if not lines_a and not lines_b:
                return
            elif ch_a and not ch_b:
                # one-sided change:
                yield (lines_a,)
            elif ch_b and not ch_a:
                yield (lines_b,)
            elif lines_a == lines_b:
                yield (lines_a,)
            else:
                yield (lines_a, lines_b)

        # We previously considered either 'unchanged' or 'killed-both' lines
        # to be possible places to resynchronize.  However, assuming agreement
        # on killed-both lines may be too aggressive. -- mbp 20060324
        for state, line in self.plan:
            if state == "unchanged":
                # resync and flush queued conflicts changes if any
                yield from outstanding_struct()
                lines_a = []
                lines_b = []
                ch_a = ch_b = False

            if state == "unchanged":
                if line:
                    yield ([line],)
            elif state == "killed-a":
                ch_a = True
                lines_b.append(line)
            elif state == "killed-b":
                ch_b = True
                lines_a.append(line)
            elif state == "new-a":
                ch_a = True
                lines_a.append(line)
            elif state == "new-b":
                ch_b = True
                lines_b.append(line)
            elif state == "conflicted-a":
                ch_b = ch_a = True
                lines_a.append(line)
            elif state == "conflicted-b":
                ch_b = ch_a = True
                lines_b.append(line)
            elif state == "killed-both":
                # This counts as a change, even though there is no associated
                # line
                ch_b = ch_a = True
            else:
                if state not in ("irrelevant", "ghost-a", "ghost-b", "killed-base"):
                    raise AssertionError(state)
        yield from outstanding_struct()

    def base_from_plan(self):
        """Construct a BASE file from the plan text."""
        base_lines = []
        for state, line in self.plan:
            if state in ("killed-a", "killed-b", "killed-both", "unchanged"):
                # If unchanged, then this line is straight from base. If a or b
                # or both killed the line, then it *used* to be in base.
                base_lines.append(line)
            else:
                if state not in (
                    "killed-base",
                    "irrelevant",
                    "ghost-a",
                    "ghost-b",
                    "new-a",
                    "new-b",
                    "conflicted-a",
                    "conflicted-b",
                ):
                    # killed-base, irrelevant means it doesn't apply
                    # ghost-a/ghost-b are harder to say for sure, but they
                    # aren't in the 'inc_c' which means they aren't in the
                    # shared base of a & b. So we don't include them.  And
                    # obviously if the line is newly inserted, it isn't in base

                    # If 'conflicted-a' or b, then it is new vs one base, but
                    # old versus another base. However, if we make it present
                    # in the base, it will be deleted from the target, and it
                    # seems better to get a line doubled in the merge result,
                    # rather than have it deleted entirely.
                    # Example, each node is the 'text' at that point:
                    #           MN
                    #          /   \
                    #        MaN   MbN
                    #         |  X  |
                    #        MabN MbaN
                    #          \   /
                    #           ???
                    # There was a criss-cross conflict merge. Both sides
                    # include the other, but put themselves first.
                    # Weave marks this as a 'clean' merge, picking OTHER over
                    # THIS. (Though the details depend on order inserted into
                    # weave, etc.)
                    # LCA generates a plan:
                    # [('unchanged', M),
                    #  ('conflicted-b', b),
                    #  ('unchanged', a),
                    #  ('conflicted-a', b),
                    #  ('unchanged', N)]
                    # If you mark 'conflicted-*' as part of BASE, then a 3-way
                    # merge tool will cleanly generate "MaN" (as BASE vs THIS
                    # removes one 'b', and BASE vs OTHER removes the other)
                    # If you include neither, 3-way creates a clean "MbabN" as
                    # THIS adds one 'b', and OTHER does too.
                    # It seems that having the line 2 times is better than
                    # having it omitted. (Easier to manually delete than notice
                    # it needs to be added.)
                    raise AssertionError(f"Unknown state: {state}")
        return base_lines


class WeaveMerge(PlanWeaveMerge):
    """Weave merge that takes a VersionedFile and two versions as its input."""

    def __init__(
        self,
        versionedfile,
        ver_a,
        ver_b,
        a_marker=PlanWeaveMerge.A_MARKER,
        b_marker=PlanWeaveMerge.B_MARKER,
    ):
        """Initialize a WeaveMerge.

        Args:
            versionedfile: The versioned file containing the versions to merge.
            ver_a: First version ID to merge.
            ver_b: Second version ID to merge.
            a_marker: Marker for 'A' side conflicts (optional).
            b_marker: Marker for 'B' side conflicts (optional).
        """
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
        super().__init__()
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
        parent_view = self._get_parent_map(k for (k,) in keys).items()
        return {(k,): tuple((p,) for p in v) for k, v in parent_view}

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
                yield ChunkedContentFactory(
                    (k,),
                    None,
                    sha1=osutils.sha_strings(lines),
                    chunks=lines,
                )
            else:
                yield AbsentContentFactory((k,))

    def iter_lines_added_or_present_in_keys(self, keys, pb=None):
        """See VersionedFile.iter_lines_added_or_present_in_versions()."""
        for i, (key,) in enumerate(keys):
            if pb is not None:
                pb.update("Finding changed lines", i, len(keys))
            for l in self._get_lines(key):
                yield (l, key)


class NoDupeAddLinesDecorator:
    """Decorator for a VersionedFiles that skips doing an add_lines if the key
    is already present.
    """

    def __init__(self, store):
        """Initialize a NoDupeAddLinesDecorator.

        Args:
            store: The underlying versioned files store to decorate.
        """
        self._store = store

    def add_lines(
        self,
        key,
        parents,
        lines,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
        check_content=True,
    ):
        """See VersionedFiles.add_lines.

        This implementation may return None as the third element of the return
        value when the original store wouldn't.
        """
        if nostore_sha:
            raise NotImplementedError(
                "NoDupeAddLinesDecorator.add_lines does not implement the "
                "nostore_sha behaviour."
            )
        if key[-1] is None:
            sha1 = osutils.sha_strings(lines)
            key = (b"sha1:" + sha1,)
        else:
            sha1 = None
        if key in self._store.get_parent_map([key]):
            # This key has already been inserted, so don't do it again.
            if sha1 is None:
                sha1 = osutils.sha_strings(lines)
            return sha1, sum(map(len, lines)), None
        return self._store.add_lines(
            key,
            parents,
            lines,
            parent_texts=parent_texts,
            left_matching_blocks=left_matching_blocks,
            nostore_sha=nostore_sha,
            random_id=random_id,
            check_content=check_content,
        )

    def __getattr__(self, name):
        """Delegate attribute access to the underlying store.

        Args:
            name: Name of the attribute to access.

        Returns:
            The attribute value from the underlying store.
        """
        return getattr(self._store, name)


def network_bytes_to_kind_and_offset(network_bytes):
    """Strip of a record kind from the front of network_bytes.

    :param network_bytes: The bytes of a record.
    :return: A tuple (storage_kind, offset_of_remaining_bytes)
    """
    line_end = network_bytes.find(b"\n")
    storage_kind = network_bytes[:line_end].decode("ascii")
    return storage_kind, line_end + 1


class NetworkRecordStream:
    """A record_stream which reconstitures a serialised stream."""

    def __init__(self, bytes_iterator):
        """Create a NetworkRecordStream.

        :param bytes_iterator: An iterator of bytes. Each item in this
            iterator should have been obtained from a record_streams'
            record.get_bytes_as(record.storage_kind) call.
        """
        from . import groupcompress, knit

        self._bytes_iterator = bytes_iterator
        self._kind_factory = {
            "fulltext": fulltext_network_to_record,
            "groupcompress-block": groupcompress.network_block_to_records,
            "knit-ft-gz": knit.knit_network_to_record,
            "knit-delta-gz": knit.knit_network_to_record,
            "knit-annotated-ft-gz": knit.knit_network_to_record,
            "knit-annotated-delta-gz": knit.knit_network_to_record,
            "knit-delta-closure": knit.knit_delta_closure_to_records,
        }

    def read(self):
        """Read the stream.

        :return: An iterator as per VersionedFiles.get_record_stream().
        """
        for bytes in self._bytes_iterator:
            storage_kind, line_end = network_bytes_to_kind_and_offset(bytes)
            yield from self._kind_factory[storage_kind](storage_kind, bytes, line_end)


def sort_groupcompress(parent_map):
    """Sort and group the keys in parent_map into groupcompress order.

    groupcompress is defined (currently) as reverse-topological order, grouped
    by the key prefix.

    :return: A sorted-list of keys
    """
    from vcsgraph.tsort import topo_sort

    # gc-optimal ordering is approximately reverse topological,
    # properly grouped by file-id.
    per_prefix_map = {}
    for item in parent_map.items():
        key = item[0]
        prefix = b"" if isinstance(key, bytes) or len(key) == 1 else key[0]
        try:
            per_prefix_map[prefix].append(item)
        except KeyError:
            per_prefix_map[prefix] = [item]

    present_keys = []
    for prefix in sorted(per_prefix_map):
        present_keys.extend(reversed(topo_sort(per_prefix_map[prefix])))
    return present_keys


class _KeyRefs:
    def __init__(self, track_new_keys=False):
        # dict mapping 'key' to 'set of keys referring to that key'
        self.refs = {}
        if track_new_keys:
            # set remembering all new keys
            self.new_keys = set()
        else:
            self.new_keys = None

    def clear(self):
        if self.refs:
            self.refs.clear()
        if self.new_keys:
            self.new_keys.clear()

    def add_references(self, key, refs):
        # Record the new references
        for referenced in refs:
            try:
                needed_by = self.refs[referenced]
            except KeyError:
                needed_by = self.refs[referenced] = set()
            needed_by.add(key)
        # Discard references satisfied by the new key
        self.add_key(key)

    def get_new_keys(self):
        return self.new_keys

    def get_unsatisfied_refs(self):
        return self.refs.keys()

    def _satisfy_refs_for_key(self, key):
        try:
            del self.refs[key]
        except KeyError:
            # No keys depended on this key.  That's ok.
            pass

    def add_key(self, key):
        # satisfy refs for key, and remember that we've seen this key.
        self._satisfy_refs_for_key(key)
        if self.new_keys is not None:
            self.new_keys.add(key)

    def satisfy_refs_for_keys(self, keys):
        for key in keys:
            self._satisfy_refs_for_key(key)

    def get_referrers(self):
        return set(itertools.chain.from_iterable(self.refs.values()))
