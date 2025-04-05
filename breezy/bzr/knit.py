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

import operator
import os
from io import BytesIO

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import patiencediff
import gzip

from breezy import (
    debug,
    diff,
    trace,
    tsort,
    ui,
    )
from breezy.bzr import (
    pack,
    tuned_gzip,
    )

from breezy.bzr import pack_repo
from breezy.i18n import gettext
""",
)
from .. import annotate, errors, osutils
from .. import transport as _mod_transport
from ..bzr.versionedfile import (
    AbsentContentFactory,
    ConstantMapper,
    ContentFactory,
    ExistingContent,
    UnavailableRepresentation,
    VersionedFilesWithFallbacks,
    _KeyRefs,
    adapter_registry,
    sort_groupcompress,
)
from ..errors import InternalBzrError, InvalidRevisionId, RevisionNotPresent
from ..osutils import contains_whitespace, sha_string, sha_strings
from ..transport import NoSuchFile
from . import index as _mod_index

# TODO: Split out code specific to this format into an associated object.

# TODO: Can we put in some kind of value to check that the index and data
# files belong together?

# TODO: accommodate binaries, perhaps by storing a byte count

# TODO: function to check whole file

# TODO: atomically append data, then measure backwards from the cursor
# position after writing to work out where it was located.  we may need to
# bypass python file buffering.

DATA_SUFFIX = ".knit"
INDEX_SUFFIX = ".kndx"
_STREAM_MIN_BUFFER_SIZE = 5 * 1024 * 1024


class KnitError(InternalBzrError):
    _fmt = "Knit error"


class KnitCorrupt(KnitError):
    _fmt = "Knit %(filename)s corrupt: %(how)s"

    def __init__(self, filename, how):
        KnitError.__init__(self)
        self.filename = filename
        self.how = how


class SHA1KnitCorrupt(KnitCorrupt):
    _fmt = (
        "Knit %(filename)s corrupt: sha-1 of reconstructed text does not "
        "match expected sha-1. key %(key)s expected sha %(expected)s actual "
        "sha %(actual)s"
    )

    def __init__(self, filename, actual, expected, key, content):
        KnitError.__init__(self)
        self.filename = filename
        self.actual = actual
        self.expected = expected
        self.key = key
        self.content = content


class KnitDataStreamIncompatible(KnitError):
    # Not raised anymore, as we can convert data streams.  In future we may
    # need it again for more exotic cases, so we're keeping it around for now.

    _fmt = 'Cannot insert knit data stream of format "%(stream_format)s" into knit of format "%(target_format)s".'

    def __init__(self, stream_format, target_format):
        self.stream_format = stream_format
        self.target_format = target_format


class KnitDataStreamUnknown(KnitError):
    # Indicates a data stream we don't know how to handle.

    _fmt = 'Cannot parse knit data stream of format "%(stream_format)s".'

    def __init__(self, stream_format):
        self.stream_format = stream_format


class KnitHeaderError(KnitError):
    _fmt = 'Knit header error: %(badline)r unexpected for file "%(filename)s".'

    def __init__(self, badline, filename):
        KnitError.__init__(self)
        self.badline = badline
        self.filename = filename


class KnitIndexUnknownMethod(KnitError):
    """Raised when we don't understand the storage method.

    Currently only 'fulltext' and 'line-delta' are supported.
    """

    _fmt = (
        "Knit index %(filename)s does not have a known method in options: %(options)r"
    )

    def __init__(self, filename, options):
        KnitError.__init__(self)
        self.filename = filename
        self.options = options


class KnitAdapter:
    """Base class for knit record adaption."""

    def __init__(self, basis_vf):
        """Create an adapter which accesses full texts from basis_vf.

        :param basis_vf: A versioned file to access basis texts of deltas from.
            May be None for adapters that do not need to access basis texts.
        """
        self._data = KnitVersionedFiles(None, None)
        self._annotate_factory = KnitAnnotateFactory()
        self._plain_factory = KnitPlainFactory()
        self._basis_vf = basis_vf


class FTAnnotatedToUnannotated(KnitAdapter):
    """An adapter from FT annotated knits to unannotated ones."""

    def get_bytes(self, factory, target_storage_kind):
        if target_storage_kind != "knit-ft-gz":
            raise UnavailableRepresentation(
                factory.key, target_storage_kind, factory.storage_kind
            )
        annotated_compressed_bytes = factory._raw_record
        rec, contents = self._data._parse_record_unchecked(annotated_compressed_bytes)
        content = self._annotate_factory.parse_fulltext(contents, rec[1])
        size, chunks = self._data._record_to_data((rec[1],), rec[3], content.text())
        return b"".join(chunks)


class DeltaAnnotatedToUnannotated(KnitAdapter):
    """An adapter for deltas from annotated to unannotated."""

    def get_bytes(self, factory, target_storage_kind):
        if target_storage_kind != "knit-delta-gz":
            raise UnavailableRepresentation(
                factory.key, target_storage_kind, factory.storage_kind
            )
        annotated_compressed_bytes = factory._raw_record
        rec, contents = self._data._parse_record_unchecked(annotated_compressed_bytes)
        delta = self._annotate_factory.parse_line_delta(contents, rec[1], plain=True)
        contents = self._plain_factory.lower_line_delta(delta)
        size, chunks = self._data._record_to_data((rec[1],), rec[3], contents)
        return b"".join(chunks)


class FTAnnotatedToFullText(KnitAdapter):
    """An adapter from FT annotated knits to unannotated ones."""

    def get_bytes(self, factory, target_storage_kind):
        annotated_compressed_bytes = factory._raw_record
        rec, contents = self._data._parse_record_unchecked(annotated_compressed_bytes)
        content, delta = self._annotate_factory.parse_record(
            factory.key[-1], contents, factory._build_details, None
        )
        if target_storage_kind == "fulltext":
            return b"".join(content.text())
        elif target_storage_kind in ("chunked", "lines"):
            return content.text()
        raise UnavailableRepresentation(
            factory.key, target_storage_kind, factory.storage_kind
        )


class DeltaAnnotatedToFullText(KnitAdapter):
    """An adapter for deltas from annotated to unannotated."""

    def get_bytes(self, factory, target_storage_kind):
        annotated_compressed_bytes = factory._raw_record
        rec, contents = self._data._parse_record_unchecked(annotated_compressed_bytes)
        delta = self._annotate_factory.parse_line_delta(contents, rec[1], plain=True)
        compression_parent = factory.parents[0]
        basis_entry = next(
            self._basis_vf.get_record_stream([compression_parent], "unordered", True)
        )
        if basis_entry.storage_kind == "absent":
            raise errors.RevisionNotPresent(compression_parent, self._basis_vf)
        basis_lines = basis_entry.get_bytes_as("lines")
        # Manually apply the delta because we have one annotated content and
        # one plain.
        basis_content = PlainKnitContent(basis_lines, compression_parent)
        basis_content.apply_delta(delta, rec[1])
        basis_content._should_strip_eol = factory._build_details[1]

        if target_storage_kind == "fulltext":
            return b"".join(basis_content.text())
        elif target_storage_kind in ("chunked", "lines"):
            return basis_content.text()
        raise UnavailableRepresentation(
            factory.key, target_storage_kind, factory.storage_kind
        )


class FTPlainToFullText(KnitAdapter):
    """An adapter from FT plain knits to unannotated ones."""

    def get_bytes(self, factory, target_storage_kind):
        compressed_bytes = factory._raw_record
        rec, contents = self._data._parse_record_unchecked(compressed_bytes)
        content, delta = self._plain_factory.parse_record(
            factory.key[-1], contents, factory._build_details, None
        )
        if target_storage_kind == "fulltext":
            return b"".join(content.text())
        elif target_storage_kind in ("chunked", "lines"):
            return content.text()
        raise UnavailableRepresentation(
            factory.key, target_storage_kind, factory.storage_kind
        )


class DeltaPlainToFullText(KnitAdapter):
    """An adapter for deltas from annotated to unannotated."""

    def get_bytes(self, factory, target_storage_kind):
        compressed_bytes = factory._raw_record
        rec, contents = self._data._parse_record_unchecked(compressed_bytes)
        self._plain_factory.parse_line_delta(contents, rec[1])
        compression_parent = factory.parents[0]
        # XXX: string splitting overhead.
        basis_entry = next(
            self._basis_vf.get_record_stream([compression_parent], "unordered", True)
        )
        if basis_entry.storage_kind == "absent":
            raise errors.RevisionNotPresent(compression_parent, self._basis_vf)
        basis_lines = basis_entry.get_bytes_as("lines")
        basis_content = PlainKnitContent(basis_lines, compression_parent)
        # Manually apply the delta because we have one annotated content and
        # one plain.
        content, _ = self._plain_factory.parse_record(
            rec[1], contents, factory._build_details, basis_content
        )
        if target_storage_kind == "fulltext":
            return b"".join(content.text())
        elif target_storage_kind in ("chunked", "lines"):
            return content.text()
        raise UnavailableRepresentation(
            factory.key, target_storage_kind, factory.storage_kind
        )


class KnitContentFactory(ContentFactory):
    """Content factory for streaming from knits.

    :seealso ContentFactory:
    """

    def __init__(
        self,
        key,
        parents,
        build_details,
        sha1,
        raw_record,
        annotated,
        knit=None,
        network_bytes=None,
    ):
        """Create a KnitContentFactory for key.

        :param key: The key.
        :param parents: The parents.
        :param build_details: The build details as returned from
            get_build_details.
        :param sha1: The sha1 expected from the full text of this object.
        :param raw_record: The bytes of the knit data from disk.
        :param annotated: True if the raw data is annotated.
        :param network_bytes: None to calculate the network bytes on demand,
            not-none if they are already known.
        """
        ContentFactory.__init__(self)
        self.sha1 = sha1
        self.key = key
        self.parents = parents
        if build_details[0] == "line-delta":
            kind = "delta"
        else:
            kind = "ft"
        if annotated:
            annotated_kind = "annotated-"
        else:
            annotated_kind = ""
        self.storage_kind = "knit-{}{}-gz".format(annotated_kind, kind)
        self._raw_record = raw_record
        self._network_bytes = network_bytes
        self._build_details = build_details
        self._knit = knit

    def _create_network_bytes(self):
        """Create a fully serialised network version for transmission."""
        # storage_kind, key, parents, Noeol, raw_record
        key_bytes = b"\x00".join(self.key)
        if self.parents is None:
            parent_bytes = b"None:"
        else:
            parent_bytes = b"\t".join(b"\x00".join(key) for key in self.parents)
        if self._build_details[1]:
            noeol = b"N"
        else:
            noeol = b" "
        network_bytes = b"%s\n%s\n%s\n%s%s" % (
            self.storage_kind.encode("ascii"),
            key_bytes,
            parent_bytes,
            noeol,
            self._raw_record,
        )
        self._network_bytes = network_bytes

    def get_bytes_as(self, storage_kind):
        if storage_kind == self.storage_kind:
            if self._network_bytes is None:
                self._create_network_bytes()
            return self._network_bytes
        if "-ft-" in self.storage_kind and storage_kind in (
            "chunked",
            "fulltext",
            "lines",
        ):
            adapter_key = (self.storage_kind, storage_kind)
            adapter_factory = adapter_registry.get(adapter_key)
            adapter = adapter_factory(None)
            return adapter.get_bytes(self, storage_kind)
        if self._knit is not None:
            # Not redundant with direct conversion above - that only handles
            # fulltext cases.
            if storage_kind in ("chunked", "lines"):
                return self._knit.get_lines(self.key[0])
            elif storage_kind == "fulltext":
                return self._knit.get_text(self.key[0])
        raise UnavailableRepresentation(self.key, storage_kind, self.storage_kind)

    def iter_bytes_as(self, storage_kind):
        return iter(self.get_bytes_as(storage_kind))


class LazyKnitContentFactory(ContentFactory):
    """A ContentFactory which can either generate full text or a wire form.

    :seealso ContentFactory:
    """

    def __init__(self, key, parents, generator, first):
        """Create a LazyKnitContentFactory.

        :param key: The key of the record.
        :param parents: The parents of the record.
        :param generator: A _ContentMapGenerator containing the record for this
            key.
        :param first: Is this the first content object returned from generator?
            if it is, its storage kind is knit-delta-closure, otherwise it is
            knit-delta-closure-ref
        """
        self.key = key
        self.parents = parents
        self.sha1 = None
        self.size = None
        self._generator = generator
        self.storage_kind = "knit-delta-closure"
        if not first:
            self.storage_kind = self.storage_kind + "-ref"
        self._first = first

    def get_bytes_as(self, storage_kind):
        if storage_kind == self.storage_kind:
            if self._first:
                return self._generator._wire_bytes()
            else:
                # all the keys etc are contained in the bytes returned in the
                # first record.
                return b""
        if storage_kind in ("chunked", "fulltext", "lines"):
            chunks = self._generator._get_one_work(self.key).text()
            if storage_kind in ("chunked", "lines"):
                return chunks
            else:
                return b"".join(chunks)
        raise UnavailableRepresentation(self.key, storage_kind, self.storage_kind)

    def iter_bytes_as(self, storage_kind):
        if storage_kind in ("chunked", "lines"):
            chunks = self._generator._get_one_work(self.key).text()
            return iter(chunks)
        raise errors.UnavailableRepresentation(
            self.key, storage_kind, self.storage_kind
        )


def knit_delta_closure_to_records(storage_kind, bytes, line_end):
    """Convert a network record to a iterator over stream records.

    :param storage_kind: The storage kind of the record.
        Must be 'knit-delta-closure'.
    :param bytes: The bytes of the record on the network.
    """
    generator = _NetworkContentMapGenerator(bytes, line_end)
    return generator.get_record_stream()


def knit_network_to_record(storage_kind, bytes, line_end):
    """Convert a network record to a record object.

    :param storage_kind: The storage kind of the record.
    :param bytes: The bytes of the record on the network.
    """
    start = line_end
    line_end = bytes.find(b"\n", start)
    key = tuple(bytes[start:line_end].split(b"\x00"))
    start = line_end + 1
    line_end = bytes.find(b"\n", start)
    parent_line = bytes[start:line_end]
    if parent_line == b"None:":
        parents = None
    else:
        parents = tuple(
            [
                tuple(segment.split(b"\x00"))
                for segment in parent_line.split(b"\t")
                if segment
            ]
        )
    start = line_end + 1
    noeol = bytes[start : start + 1] == b"N"
    if "ft" in storage_kind:
        method = "fulltext"
    else:
        method = "line-delta"
    build_details = (method, noeol)
    start = start + 1
    raw_record = bytes[start:]
    annotated = "annotated" in storage_kind
    return [
        KnitContentFactory(
            key,
            parents,
            build_details,
            None,
            raw_record,
            annotated,
            network_bytes=bytes,
        )
    ]


class KnitContent:
    r"""Content of a knit version to which deltas can be applied.

    This is always stored in memory as a list of lines with \\n at the end,
    plus a flag saying if the final ending is really there or not, because that
    corresponds to the on-disk knit representation.
    """

    def __init__(self):
        self._should_strip_eol = False

    def apply_delta(self, delta, new_version_id):
        """Apply delta to this object to become new_version_id."""
        raise NotImplementedError(self.apply_delta)

    def line_delta_iter(self, new_lines):
        """Generate line-based delta from this content to new_lines."""
        new_texts = new_lines.text()
        old_texts = self.text()
        s = patiencediff.PatienceSequenceMatcher(None, old_texts, new_texts)
        for tag, i1, i2, j1, j2 in s.get_opcodes():
            if tag == "equal":
                continue
            # ofrom, oto, length, data
            yield i1, i2, j2 - j1, new_lines._lines[j1:j2]

    def line_delta(self, new_lines):
        return list(self.line_delta_iter(new_lines))

    @staticmethod
    def get_line_delta_blocks(knit_delta, source, target):
        """Extract SequenceMatcher.get_matching_blocks() from a knit delta."""
        target_len = len(target)
        s_pos = 0
        t_pos = 0
        for s_begin, s_end, t_len, _new_text in knit_delta:
            true_n = s_begin - s_pos
            n = true_n
            if n > 0:
                # knit deltas do not provide reliable info about whether the
                # last line of a file matches, due to eol handling.
                if source[s_pos + n - 1] != target[t_pos + n - 1]:
                    n -= 1
                if n > 0:
                    yield s_pos, t_pos, n
            t_pos += t_len + true_n
            s_pos = s_end
        n = target_len - t_pos
        if n > 0:
            if source[s_pos + n - 1] != target[t_pos + n - 1]:
                n -= 1
            if n > 0:
                yield s_pos, t_pos, n
        yield s_pos + (target_len - t_pos), target_len, 0


class AnnotatedKnitContent(KnitContent):
    """Annotated content."""

    def __init__(self, lines):
        KnitContent.__init__(self)
        self._lines = list(lines)

    def annotate(self):
        """Return a list of (origin, text) for each content line."""
        lines = self._lines[:]
        if self._should_strip_eol:
            origin, last_line = lines[-1]
            lines[-1] = (origin, last_line.rstrip(b"\n"))
        return lines

    def apply_delta(self, delta, new_version_id):
        """Apply delta to this object to become new_version_id."""
        offset = 0
        lines = self._lines
        for start, end, count, delta_lines in delta:
            lines[offset + start : offset + end] = delta_lines
            offset = offset + (start - end) + count

    def text(self):
        try:
            lines = [text for origin, text in self._lines]
        except ValueError as e:
            # most commonly (only?) caused by the internal form of the knit
            # missing annotation information because of a bug - see thread
            # around 20071015
            raise KnitCorrupt(
                self, f"line in annotated knit missing annotation information: {e}"
            ) from e
        if self._should_strip_eol:
            lines[-1] = lines[-1].rstrip(b"\n")
        return lines

    def copy(self):
        return AnnotatedKnitContent(self._lines)


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

    def annotate(self):
        """Return a list of (origin, text) for each content line."""
        return [(self._version_id, line) for line in self._lines]

    def apply_delta(self, delta, new_version_id):
        """Apply delta to this object to become new_version_id."""
        offset = 0
        lines = self._lines
        for start, end, count, delta_lines in delta:
            lines[offset + start : offset + end] = delta_lines
            offset = offset + (start - end) + count
        self._version_id = new_version_id

    def copy(self):
        return PlainKnitContent(self._lines[:], self._version_id)

    def text(self):
        lines = self._lines
        if self._should_strip_eol:
            lines = lines[:]
            lines[-1] = lines[-1].rstrip(b"\n")
        return lines


class _KnitFactory:
    """Base class for common Factory functions."""

    def parse_record(
        self, version_id, record, record_details, base_content, copy_base_content=True
    ):
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
        if method == "line-delta":
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
        r"""Convert fulltext to internal representation.

        fulltext content is of the format
        revid(utf8) plaintext\n
        internal representation is of the format:
        (revid, plaintext)
        """
        # TODO: jam 20070209 The tests expect this to be returned as tuples,
        #       but the code itself doesn't really depend on that.
        #       Figure out a way to not require the overhead of turning the
        #       list back into tuples.
        lines = (tuple(line.split(b" ", 1)) for line in content)
        return AnnotatedKnitContent(lines)

    def parse_line_delta(self, lines, version_id, plain=False):
        r"""Convert a line based delta into internal representation.

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

        cache = {}

        def cache_and_return(line):
            origin, text = line.split(b" ", 1)
            return cache.setdefault(origin, origin), text

        # walk through the lines parsing.
        # Note that the plain test is explicitly pulled out of the
        # loop to minimise any performance impact
        if plain:
            for header in lines:
                start, end, count = (int(n) for n in header.split(b","))
                contents = [next(lines).split(b" ", 1)[1] for _ in range(count)]
                result.append((start, end, count, contents))
        else:
            for header in lines:
                start, end, count = (int(n) for n in header.split(b","))
                contents = [tuple(next(lines).split(b" ", 1)) for _ in range(count)]
                result.append((start, end, count, contents))
        return result

    def get_fulltext_content(self, lines):
        """Extract just the content lines from a fulltext."""
        return (line.split(b" ", 1)[1] for line in lines)

    def get_linedelta_content(self, lines):
        """Extract just the content from a line delta.

        This doesn't return all of the extra information stored in a delta.
        Only the actual content lines.
        """
        lines = iter(lines)
        for header in lines:
            header = header.split(b",")
            count = int(header[2])
            for _ in range(count):
                origin, text = next(lines).split(b" ", 1)
                yield text

    def lower_fulltext(self, content):
        """Convert a fulltext content record into a serializable form.

        see parse_fulltext which this inverts.
        """
        return [b"%s %s" % (o, t) for o, t in content._lines]

    def lower_line_delta(self, delta):
        """Convert a delta into a serializable form.

        See parse_line_delta which this inverts.
        """
        # TODO: jam 20070209 We only do the caching thing to make sure that
        #       the origin is a valid utf-8 line, eventually we could remove it
        out = []
        for start, end, c, lines in delta:
            out.append(b"%d,%d,%d\n" % (start, end, c))
            out.extend(origin + b" " + text for origin, text in lines)
        return out

    def annotate(self, knit, key):
        content = knit._get_content(key)
        # adjust for the fact that serialised annotations are only key suffixes
        # for this factory.
        if isinstance(key, tuple):
            prefix = key[:-1]
            origins = content.annotate()
            result = []
            for origin, line in origins:
                result.append((prefix + (origin,), line))
            return result
        else:
            # XXX: This smells a bit.  Why would key ever be a non-tuple here?
            # Aren't keys defined to be tuples?  -- spiv 20080618
            return content.annotate()


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
            start, end, c = (int(n) for n in header.split(b","))
            yield start, end, c, lines[cur : cur + c]
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
        for header in lines:
            header = header.split(b",")
            count = int(header[2])
            for _ in range(count):
                yield next(lines)

    def lower_fulltext(self, content):
        return content.text()

    def lower_line_delta(self, delta):
        out = []
        for start, end, c, lines in delta:
            out.append(b"%d,%d,%d\n" % (start, end, c))
            out.extend(lines)
        return out

    def annotate(self, knit, key):
        annotator = _KnitAnnotator(knit)
        return annotator.annotate_flat(key)


def make_file_factory(annotated, mapper):
    """Create a factory for creating a file based KnitVersionedFiles.

    This is only functional enough to run interface tests, it doesn't try to
    provide a full pack environment.

    :param annotated: knit annotations are wanted.
    :param mapper: The mapper from keys to paths.
    """

    def factory(transport):
        index = _KndxIndex(transport, mapper, lambda: None, lambda: True, lambda: True)
        access = _KnitKeyAccess(transport, mapper)
        return KnitVersionedFiles(index, access, annotated=annotated)

    return factory


def make_pack_factory(graph, delta, keylength):
    """Create a factory for creating a pack based VersionedFiles.

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
        if delta:
            ref_length += 1
            max_delta_chain = 200
        else:
            max_delta_chain = 0
        graph_index = _mod_index.InMemoryGraphIndex(
            reference_lists=ref_length, key_elements=keylength
        )
        stream = transport.open_write_stream("newpack")
        writer = pack.ContainerWriter(stream.write)
        writer.begin()
        index = _KnitGraphIndex(
            graph_index,
            lambda: True,
            parents=parents,
            deltas=delta,
            add_callback=graph_index.add_nodes,
        )
        access = pack_repo._DirectPackAccess({})
        access.set_writer(writer, graph_index, (transport, "newpack"))
        result = KnitVersionedFiles(index, access, max_delta_chain=max_delta_chain)
        result.stream = stream
        result.writer = writer
        return result

    return factory


def cleanup_pack_knit(versioned_files):
    versioned_files.stream.close()
    versioned_files.writer.end()


def _get_total_build_size(self, keys, positions):
    """Determine the total bytes to build these keys.

    (helper function because _KnitGraphIndex and _KndxIndex work the same, but
    don't inherit from a common base.)

    :param keys: Keys that we want to build
    :param positions: dict of {key, (info, index_memo, comp_parent)} (such
        as returned by _get_components_positions)
    :return: Number of bytes to build those keys
    """
    all_build_index_memos = {}
    build_keys = keys
    while build_keys:
        next_keys = set()
        for key in build_keys:
            # This is mostly for the 'stacked' case
            # Where we will be getting the data from a fallback
            if key not in positions:
                continue
            _, index_memo, compression_parent = positions[key]
            all_build_index_memos[key] = index_memo
            if compression_parent not in all_build_index_memos:
                next_keys.add(compression_parent)
        build_keys = next_keys
    return sum(index_memo[2] for index_memo in all_build_index_memos.values())


class KnitVersionedFiles(VersionedFilesWithFallbacks):
    """Storage for many versioned files using knit compression.

    Backend storage is managed by indices and data objects.

    :ivar _index: A _KnitGraphIndex or similar that can describe the
        parents, graph, compression and data location of entries in this
        KnitVersionedFiles.  Note that this is only the index for
        *this* vfs; if there are fallbacks they must be queried separately.
    """

    def __init__(
        self, index, data_access, max_delta_chain=200, annotated=False, reload_func=None
    ):
        """Create a KnitVersionedFiles with index and data_access.

        :param index: The index for the knit data.
        :param data_access: The access object to store and retrieve knit
            records.
        :param max_delta_chain: The maximum number of deltas to permit during
            insertion. Set to 0 to prohibit the use of deltas.
        :param annotated: Set to True to cause annotations to be calculated and
            stored during insertion.
        :param reload_func: An function that can be called if we think we need
            to reload the pack listing and try again. See
            'breezy.bzr.pack_repo.AggregateIndex' for the signature.
        """
        self._index = index
        self._access = data_access
        self._max_delta_chain = max_delta_chain
        if annotated:
            self._factory = KnitAnnotateFactory()
        else:
            self._factory = KnitPlainFactory()
        self._immediate_fallback_vfs = []
        self._reload_func = reload_func

    def __repr__(self):
        return "{}({!r}, {!r})".format(
            self.__class__.__name__, self._index, self._access
        )

    def without_fallbacks(self):
        """Return a clone of this object without any fallbacks configured."""
        return KnitVersionedFiles(
            self._index,
            self._access,
            self._max_delta_chain,
            self._factory.annotated,
            self._reload_func,
        )

    def add_fallback_versioned_files(self, a_versioned_files):
        """Add a source of texts for texts not present in this knit.

        :param a_versioned_files: A VersionedFiles object.
        """
        self._immediate_fallback_vfs.append(a_versioned_files)

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
        self._index._check_write_ok()
        self._check_add(key, lines, random_id, check_content)
        if parents is None:
            # The caller might pass None if there is no graph data, but kndx
            # indexes can't directly store that, so we give them
            # an empty tuple instead.
            parents = ()
        line_bytes = b"".join(lines)
        return self._add(
            key,
            lines,
            parents,
            parent_texts,
            left_matching_blocks,
            nostore_sha,
            random_id,
            line_bytes=line_bytes,
        )

    def add_content(
        self,
        content_factory,
        parent_texts=None,
        left_matching_blocks=None,
        nostore_sha=None,
        random_id=False,
    ):
        """See VersionedFiles.add_content()."""
        self._index._check_write_ok()
        key = content_factory.key
        parents = content_factory.parents
        self._check_add(key, None, random_id, check_content=False)
        if parents is None:
            # The caller might pass None if there is no graph data, but kndx
            # indexes can't directly store that, so we give them
            # an empty tuple instead.
            parents = ()
        lines = content_factory.get_bytes_as("lines")
        line_bytes = content_factory.get_bytes_as("fulltext")
        return self._add(
            key,
            lines,
            parents,
            parent_texts,
            left_matching_blocks,
            nostore_sha,
            random_id,
            line_bytes=line_bytes,
        )

    def _add(
        self,
        key,
        lines,
        parents,
        parent_texts,
        left_matching_blocks,
        nostore_sha,
        random_id,
        line_bytes,
    ):
        """Add a set of lines on top of version specified by parents.

        Any versions not present will be converted into ghosts.

        :param lines: A list of strings where each one is a single line (has a
            single newline at the end of the string) This is now optional
            (callers can pass None). It is left in its location for backwards
            compatibility. It should ''.join(lines) must == line_bytes
        :param line_bytes: A single string containing the content

        We pass both lines and line_bytes because different routes bring the
        values to this function. And for memory efficiency, we don't want to
        have to split/join on-demand.
        """
        # first thing, if the content is something we don't need to store, find
        # that out.
        digest = sha_string(line_bytes)
        if nostore_sha == digest:
            raise ExistingContent

        present_parents = []
        if parent_texts is None:
            parent_texts = {}
        # Do a single query to ascertain parent presence; we only compress
        # against parents in the same kvf.
        present_parent_map = self._index.get_parent_map(parents)
        for parent in parents:
            if parent in present_parent_map:
                present_parents.append(parent)

        # Currently we can only compress against the left most present parent.
        if len(present_parents) == 0 or present_parents[0] != parents[0]:
            delta = False
        else:
            # To speed the extract of texts the delta chain is limited
            # to a fixed number of deltas.  This should minimize both
            # I/O and the time spend applying deltas.
            delta = self._check_should_delta(present_parents[0])

        text_length = len(line_bytes)
        options = []
        no_eol = False
        # Note: line_bytes is not modified to add a newline, that is tracked
        #       via the no_eol flag. 'lines' *is* modified, because that is the
        #       general values needed by the Content code.
        if line_bytes and not line_bytes.endswith(b"\n"):
            options.append(b"no-eol")
            no_eol = True
            # Copy the existing list, or create a new one
            if lines is None:
                lines = osutils.split_lines(line_bytes)
            else:
                lines = lines[:]
            # Replace the last line with one that ends in a final newline
            lines[-1] = lines[-1] + b"\n"
        if lines is None:
            lines = osutils.split_lines(line_bytes)

        for element in key[:-1]:
            if not isinstance(element, bytes):
                raise TypeError("key contains non-bytestrings: {!r}".format(key))
        if key[-1] is None:
            key = key[:-1] + (b"sha1:" + digest,)
        elif not isinstance(key[-1], bytes):
            raise TypeError("key contains non-bytestrings: {!r}".format(key))
        # Knit hunks are still last-element only
        version_id = key[-1]
        content = self._factory.make(lines, version_id)
        if no_eol:
            # Hint to the content object that its text() call should strip the
            # EOL.
            content._should_strip_eol = True
        if delta or (self._factory.annotated and len(present_parents) > 0):
            # Merge annotations from parent texts if needed.
            delta_hunks = self._merge_annotations(
                content,
                present_parents,
                parent_texts,
                delta,
                self._factory.annotated,
                left_matching_blocks,
            )

        if delta:
            options.append(b"line-delta")
            store_lines = self._factory.lower_line_delta(delta_hunks)
            size, data = self._record_to_data(key, digest, store_lines)
        else:
            options.append(b"fulltext")
            # isinstance is slower and we have no hierarchy.
            if self._factory.__class__ is KnitPlainFactory:
                # Use the already joined bytes saving iteration time in
                # _record_to_data.
                dense_lines = [line_bytes]
                if no_eol:
                    dense_lines.append(b"\n")
                size, data = self._record_to_data(key, digest, lines, dense_lines)
            else:
                # get mixed annotation + content and feed it into the
                # serialiser.
                store_lines = self._factory.lower_fulltext(content)
                size, data = self._record_to_data(key, digest, store_lines)

        access_memo = self._access.add_raw_record(key, size, data)
        self._index.add_records(
            ((key, options, access_memo, parents),), random_id=random_id
        )
        return digest, text_length, content

    def annotate(self, key):
        """See VersionedFiles.annotate."""
        return self._factory.annotate(self, key)

    def get_annotator(self):
        return _KnitAnnotator(self)

    def check(self, progress_bar=None, keys=None):
        """See VersionedFiles.check()."""
        if keys is None:
            return self._logical_check()
        else:
            # At the moment, check does not extra work over get_record_stream
            return self.get_record_stream(keys, "unordered", True)

    def _logical_check(self):
        # This doesn't actually test extraction of everything, but that will
        # impact 'bzr check' substantially, and needs to be integrated with
        # care. However, it does check for the obvious problem of a delta with
        # no basis.
        keys = self._index.keys()
        parent_map = self.get_parent_map(keys)
        for key in keys:
            if self._index.get_method(key) != "fulltext":
                compression_parent = parent_map[key][0]
                if compression_parent not in parent_map:
                    raise KnitCorrupt(
                        self,
                        "Missing basis parent {} for {}".format(
                            compression_parent, key
                        ),
                    )
        for fallback_vfs in self._immediate_fallback_vfs:
            fallback_vfs.check()

    def _check_add(self, key, lines, random_id, check_content):
        """Check that version_id and lines are safe to add."""
        if not all(isinstance(x, bytes) or x is None for x in key):
            raise TypeError(key)
        version_id = key[-1]
        if version_id is not None:
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

    def _check_header(self, key, line):
        rec = self._split_header(line)
        self._check_header_version(rec, key[-1])
        return rec

    def _check_header_version(self, rec, version_id):
        """Checks the header version on original format knit records.

        These have the last component of the key embedded in the record.
        """
        if rec[1] != version_id:
            raise KnitCorrupt(
                self,
                "unexpected version, wanted {!r}, got {!r}".format(version_id, rec[1]),
            )

    def _check_should_delta(self, parent):
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
        for _count in range(self._max_delta_chain):
            try:
                # Note that this only looks in the index of this particular
                # KnitVersionedFiles, not in the fallbacks.  This ensures that
                # we won't store a delta spanning physical repository
                # boundaries.
                build_details = self._index.get_build_details([parent])
                parent_details = build_details[parent]
            except (RevisionNotPresent, KeyError):
                # Some basis is not locally present: always fulltext
                return False
            index_memo, compression_parent, _, _ = parent_details
            _, _, size = index_memo
            if compression_parent is None:
                fulltext_size = size
                break
            delta_size += size
            # We don't explicitly check for presence because this is in an
            # inner loop, and if it's missing it'll fail anyhow.
            parent = compression_parent
        else:
            # We couldn't find a fulltext, so we must create a new one
            return False
        # Simple heuristic - if the total I/O wold be greater as a delta than
        # the originally installed fulltext, we create a new fulltext.
        return fulltext_size > delta_size

    def _build_details_to_components(self, build_details):
        """Convert a build_details tuple to a position tuple."""
        # record_details, access_memo, compression_parent
        return build_details[3], build_details[0], build_details[1]

    def _get_components_positions(self, keys, allow_missing=False):
        """Produce a map of position data for the components of keys.

        This data is intended to be used for retrieving the knit records.

        A dict of key to (record_details, index_memo, next, parents) is
        returned.

        * method is the way referenced data should be applied.
        * index_memo is the handle to pass to the data access to actually get
          the data
        * next is the build-parent of the version, or None for fulltexts.
        * parents is the version_ids of the parents of this version

        :param allow_missing: If True do not raise an error on a missing
            component, just ignore it.
        """
        component_data = {}
        pending_components = keys
        while pending_components:
            build_details = self._index.get_build_details(pending_components)
            current_components = set(pending_components)
            pending_components = set()
            for key, details in build_details.items():
                (index_memo, compression_parent, parents, record_details) = details
                if compression_parent is not None:
                    pending_components.add(compression_parent)
                component_data[key] = self._build_details_to_components(details)
            missing = current_components.difference(build_details)
            if missing and not allow_missing:
                raise errors.RevisionNotPresent(missing.pop(), self)
        return component_data

    def _get_content(self, key, parent_texts=None):
        """Returns a content object that makes up the specified
        version.
        """
        if parent_texts is None:
            parent_texts = {}
        cached_version = parent_texts.get(key, None)
        if cached_version is not None:
            # Ensure the cache dict is valid.
            if not self.get_parent_map([key]):
                raise RevisionNotPresent(key, self)
            return cached_version
        generator = _VFContentMapGenerator(self, [key])
        return generator._get_content(key)

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
        sources = [self._index] + self._immediate_fallback_vfs
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

    def _get_record_map(self, keys, allow_missing=False):
        """Produce a dictionary of knit records.

        :return: {key:(record, record_details, digest, next)}

            * record: data returned from read_records (a KnitContentobject)
            * record_details: opaque information to pass to parse_record
            * digest: SHA1 digest of the full text after all steps are done
            * next: build-parent of the version, i.e. the leftmost ancestor.
                Will be None if the record is not a delta.

        :param keys: The keys to build a map for
        :param allow_missing: If some records are missing, rather than
            error, just return the data that could be generated.
        """
        raw_map = self._get_record_map_unparsed(keys, allow_missing=allow_missing)
        return self._raw_map_to_record_map(raw_map)

    def _raw_map_to_record_map(self, raw_map):
        """Parse the contents of _get_record_map_unparsed.

        :return: see _get_record_map.
        """
        result = {}
        for key in raw_map:
            data, record_details, next = raw_map[key]
            content, digest = self._parse_record(key[-1], data)
            result[key] = content, record_details, digest, next
        return result

    def _get_record_map_unparsed(self, keys, allow_missing=False):
        """Get the raw data for reconstructing keys without parsing it.

        :return: A dict suitable for parsing via _raw_map_to_record_map.
            key-> raw_bytes, (method, noeol), compression_parent
        """
        # This retries the whole request if anything fails. Potentially we
        # could be a bit more selective. We could track the keys whose records
        # we have successfully found, and then only request the new records
        # from there. However, _get_components_positions grabs the whole build
        # chain, which means we'll likely try to grab the same records again
        # anyway. Also, can the build chains change as part of a pack
        # operation? We wouldn't want to end up with a broken chain.
        while True:
            try:
                position_map = self._get_components_positions(
                    keys, allow_missing=allow_missing
                )
                # key = component_id, r = record_details, i_m = index_memo,
                # n = next
                records = [(key, i_m) for key, (r, i_m, n) in position_map.items()]
                # Sort by the index memo, so that we request records from the
                # same pack file together, and in forward-sorted order
                records.sort(key=operator.itemgetter(1))
                raw_record_map = {}
                for key, data in self._read_records_iter_unchecked(records):
                    (record_details, index_memo, next) = position_map[key]
                    raw_record_map[key] = data, record_details, next
                return raw_record_map
            except pack_repo.RetryWithNewPacks as e:
                self._access.reload_or_raise(e)

    @classmethod
    def _split_by_prefix(cls, keys):
        """For the given keys, split them up based on their prefix.

        To keep memory pressure somewhat under control, split the
        requests back into per-file-id requests, otherwise "bzr co"
        extracts the full tree into memory before writing it to disk.
        This should be revisited if _get_content_maps() can ever cross
        file-id boundaries.

        The keys for a given file_id are kept in the same relative order.
        Ordering between file_ids is not, though prefix_order will return the
        order that the key was first seen.

        :param keys: An iterable of key tuples
        :return: (split_map, prefix_order)
            split_map       A dictionary mapping prefix => keys
            prefix_order    The order that we saw the various prefixes
        """
        split_by_prefix = {}
        prefix_order = []
        for key in keys:
            if len(key) == 1:
                prefix = b""
            else:
                prefix = key[0]

            if prefix in split_by_prefix:
                split_by_prefix[prefix].append(key)
            else:
                split_by_prefix[prefix] = [key]
                prefix_order.append(prefix)
        return split_by_prefix, prefix_order

    def _group_keys_for_io(
        self, keys, non_local_keys, positions, _min_buffer_size=_STREAM_MIN_BUFFER_SIZE
    ):
        """For the given keys, group them into 'best-sized' requests.

        The idea is to avoid making 1 request per file, but to never try to
        unpack an entire 1.5GB source tree in a single pass. Also when
        possible, we should try to group requests to the same pack file
        together.

        :return: list of (keys, non_local) tuples that indicate what keys
            should be fetched next.
        """
        # TODO: Ideally we would group on 2 factors. We want to extract texts
        #       from the same pack file together, and we want to extract all
        #       the texts for a given build-chain together. Ultimately it
        #       probably needs a better global view.
        len(keys)
        prefix_split_keys, prefix_order = self._split_by_prefix(keys)
        prefix_split_non_local_keys, _ = self._split_by_prefix(non_local_keys)
        cur_keys = []
        cur_non_local = set()
        cur_size = 0
        result = []
        sizes = []
        for prefix in prefix_order:
            keys = prefix_split_keys[prefix]
            non_local = prefix_split_non_local_keys.get(prefix, [])

            this_size = self._index._get_total_build_size(keys, positions)
            cur_size += this_size
            cur_keys.extend(keys)
            cur_non_local.update(non_local)
            if cur_size > _min_buffer_size:
                result.append((cur_keys, cur_non_local))
                sizes.append(cur_size)
                cur_keys = []
                cur_non_local = set()
                cur_size = 0
        if cur_keys:
            result.append((cur_keys, cur_non_local))
            sizes.append(cur_size)
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
            # Cannot sort when no graph has been stored.
            ordering = "unordered"

        remaining_keys = keys
        while True:
            try:
                keys = set(remaining_keys)
                for content_factory in self._get_remaining_record_stream(
                    keys, ordering, include_delta_closure
                ):
                    remaining_keys.discard(content_factory.key)
                    yield content_factory
                return
            except pack_repo.RetryWithNewPacks as e:
                self._access.reload_or_raise(e)

    def _get_remaining_record_stream(self, keys, ordering, include_delta_closure):
        """This function is the 'retry' portion for get_record_stream."""
        if include_delta_closure:
            positions = self._get_components_positions(keys, allow_missing=True)
        else:
            build_details = self._index.get_build_details(keys)
            # map from key to
            # (record_details, access_memo, compression_parent_key)
            positions = {
                key: self._build_details_to_components(details)
                for key, details in build_details.items()
            }
        absent_keys = keys.difference(set(positions))
        # There may be more absent keys : if we're missing the basis component
        # and are trying to include the delta closure.
        # XXX: We should not ever need to examine remote sources because we do
        # not permit deltas across versioned files boundaries.
        if include_delta_closure:
            needed_from_fallback = set()
            # Build up reconstructable_keys dict.  key:True in this dict means
            # the key can be reconstructed.
            reconstructable_keys = {}
            for key in keys:
                # the delta chain
                try:
                    chain = [key, positions[key][2]]
                except KeyError:
                    needed_from_fallback.add(key)
                    continue
                result = True
                while chain[-1] is not None:
                    if chain[-1] in reconstructable_keys:
                        result = reconstructable_keys[chain[-1]]
                        break
                    else:
                        try:
                            chain.append(positions[chain[-1]][2])
                        except KeyError:
                            # missing basis component
                            needed_from_fallback.add(chain[-1])
                            result = True
                            break
                for chain_key in chain[:-1]:
                    reconstructable_keys[chain_key] = result
                if not result:
                    needed_from_fallback.add(key)
        # Double index lookups here : need a unified api ?
        global_map, parent_maps = self._get_parent_map_with_sources(keys)
        if ordering in ("topological", "groupcompress"):
            if ordering == "topological":
                # Global topological sort
                present_keys = tsort.topo_sort(global_map)
            else:
                present_keys = sort_groupcompress(global_map)
            # Now group by source:
            source_keys = []
            current_source = None
            for key in present_keys:
                for parent_map in parent_maps:
                    if key in parent_map:
                        key_source = parent_map
                        break
                if current_source is not key_source:
                    source_keys.append((key_source, []))
                    current_source = key_source
                source_keys[-1][1].append(key)
        else:
            if ordering != "unordered":
                raise AssertionError(
                    "valid values for ordering are:"
                    ' "unordered", "groupcompress" or "topological" not: {!r}'.format(
                        ordering
                    )
                )
            # Just group by source; remote sources first.
            present_keys = []
            source_keys = []
            for parent_map in reversed(parent_maps):
                source_keys.append((parent_map, []))
                for key in parent_map:
                    present_keys.append(key)
                    source_keys[-1][1].append(key)
            # We have been requested to return these records in an order that
            # suits us. So we ask the index to give us an optimally sorted
            # order.
            for source, sub_keys in source_keys:
                if source is parent_maps[0]:
                    # Only sort the keys for this VF
                    self._index._sort_keys_by_io(sub_keys, positions)
        absent_keys = keys - set(global_map)
        for key in absent_keys:
            yield AbsentContentFactory(key)
        # restrict our view to the keys we can answer.
        # XXX: Memory: TODO: batch data here to cap buffered data at (say) 1MB.
        # XXX: At that point we need to consider the impact of double reads by
        # utilising components multiple times.
        if include_delta_closure:
            # XXX: get_content_maps performs its own index queries; allow state
            # to be passed in.
            non_local_keys = needed_from_fallback - absent_keys
            for keys, nlk in self._group_keys_for_io(
                present_keys, non_local_keys, positions
            ):
                generator = _VFContentMapGenerator(
                    self, keys, nlk, global_map, ordering=ordering
                )
                yield from generator.get_record_stream()
        else:
            for source, keys in source_keys:
                if source is parent_maps[0]:
                    # this KnitVersionedFiles
                    records = [(key, positions[key][1]) for key in keys]
                    for key, raw_data in self._read_records_iter_unchecked(records):
                        (record_details, index_memo, _) = positions[key]
                        yield KnitContentFactory(
                            key,
                            global_map[key],
                            record_details,
                            None,
                            raw_data,
                            self._factory.annotated,
                            None,
                        )
                else:
                    vf = self._immediate_fallback_vfs[parent_maps.index(source) - 1]
                    yield from vf.get_record_stream(
                        keys, ordering, include_delta_closure
                    )

    def get_sha1s(self, keys):
        """See VersionedFiles.get_sha1s()."""
        missing = set(keys)
        record_map = self._get_record_map(missing, allow_missing=True)
        result = {}
        for key, details in record_map.items():
            if key not in missing:
                continue
            # record entry 2 is the 'digest'.
            result[key] = details[2]
        missing.difference_update(set(result))
        for source in self._immediate_fallback_vfs:
            if not missing:
                break
            new_result = source.get_sha1s(missing)
            result.update(new_result)
            missing.difference_update(set(new_result))
        return result

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert.
        :return: None
        :seealso VersionedFiles.get_record_stream:
        """

        def get_adapter(adapter_key):
            try:
                return adapters[adapter_key]
            except KeyError:
                adapter_factory = adapter_registry.get(adapter_key)
                adapter = adapter_factory(self)
                adapters[adapter_key] = adapter
                return adapter

        delta_types = set()
        if self._factory.annotated:
            # self is annotated, we need annotated knits to use directly.
            annotated = "annotated-"
            convertibles = []
        else:
            # self is not annotated, but we can strip annotations cheaply.
            annotated = ""
            convertibles = {"knit-annotated-ft-gz"}
            if self._max_delta_chain:
                delta_types.add("knit-annotated-delta-gz")
                convertibles.add("knit-annotated-delta-gz")
        # The set of types we can cheaply adapt without needing basis texts.
        native_types = set()
        if self._max_delta_chain:
            native_types.add("knit-{}delta-gz".format(annotated))
            delta_types.add("knit-{}delta-gz".format(annotated))
        native_types.add("knit-{}ft-gz".format(annotated))
        knit_types = native_types.union(convertibles)
        adapters = {}
        # Buffer all index entries that we can't add immediately because their
        # basis parent is missing. We don't buffer all because generating
        # annotations may require access to some of the new records. However we
        # can't generate annotations from new deltas until their basis parent
        # is present anyway, so we get away with not needing an index that
        # includes the new keys.
        #
        # See <http://launchpad.net/bugs/300177> about ordering of compression
        # parents in the records - to be conservative, we insist that all
        # parents must be present to avoid expanding to a fulltext.
        #
        # key = basis_parent, value = index entry to add
        buffered_index_entries = {}
        for record in stream:
            kind = record.storage_kind
            if kind.startswith("knit-") and kind.endswith("-gz"):
                # Check that the ID in the header of the raw knit bytes matches
                # the record metadata.
                raw_data = record._raw_record
                df, rec = self._parse_record_header(record.key, raw_data)
                df.close()
            buffered = False
            parents = record.parents
            if record.storage_kind in delta_types:
                # TODO: eventually the record itself should track
                #       compression_parent
                compression_parent = parents[0]
            else:
                compression_parent = None
            # Raise an error when a record is missing.
            if record.storage_kind == "absent":
                raise RevisionNotPresent([record.key], self)
            elif (record.storage_kind in knit_types) and (
                compression_parent is None
                or not self._immediate_fallback_vfs
                or compression_parent in self._index
                or compression_parent not in self
            ):
                # we can insert the knit record literally if either it has no
                # compression parent OR we already have its basis in this kvf
                # OR the basis is not present even in the fallbacks.  In the
                # last case it will either turn up later in the stream and all
                # will be well, or it won't turn up at all and we'll raise an
                # error at the end.
                #
                # TODO: self.__contains__ is somewhat redundant with
                # self._index.__contains__; we really want something that directly
                # asks if it's only present in the fallbacks. -- mbp 20081119
                if record.storage_kind not in native_types:
                    try:
                        adapter_key = (record.storage_kind, "knit-delta-gz")
                        adapter = get_adapter(adapter_key)
                    except KeyError:
                        adapter_key = (record.storage_kind, "knit-ft-gz")
                        adapter = get_adapter(adapter_key)
                    bytes = adapter.get_bytes(record, adapter_key[1])
                else:
                    # It's a knit record, it has a _raw_record field (even if
                    # it was reconstituted from a network stream).
                    bytes = record._raw_record
                options = [record._build_details[0].encode("ascii")]
                if record._build_details[1]:
                    options.append(b"no-eol")
                # Just blat it across.
                # Note: This does end up adding data on duplicate keys. As
                # modern repositories use atomic insertions this should not
                # lead to excessive growth in the event of interrupted fetches.
                # 'knit' repositories may suffer excessive growth, but as a
                # deprecated format this is tolerable. It can be fixed if
                # needed by in the kndx index support raising on a duplicate
                # add with identical parents and options.
                access_memo = self._access.add_raw_record(
                    record.key, len(bytes), [bytes]
                )
                index_entry = (record.key, options, access_memo, parents)
                if b"fulltext" not in options:
                    # Not a fulltext, so we need to make sure the compression
                    # parent will also be present.
                    # Note that pack backed knits don't need to buffer here
                    # because they buffer all writes to the transaction level,
                    # but we don't expose that difference at the index level. If
                    # the query here has sufficient cost to show up in
                    # profiling we should do that.
                    #
                    # They're required to be physically in this
                    # KnitVersionedFiles, not in a fallback.
                    if compression_parent not in self._index:
                        pending = buffered_index_entries.setdefault(
                            compression_parent, []
                        )
                        pending.append(index_entry)
                        buffered = True
                if not buffered:
                    self._index.add_records([index_entry])
            elif record.storage_kind in ("chunked", "file"):
                self.add_lines(record.key, parents, record.get_bytes_as("lines"))
            else:
                # Not suitable for direct insertion as a
                # delta, either because it's not the right format, or this
                # KnitVersionedFiles doesn't permit deltas (_max_delta_chain ==
                # 0) or because it depends on a base only present in the
                # fallback kvfs.
                self._access.flush()
                try:
                    # Try getting a fulltext directly from the record.
                    lines = record.get_bytes_as("lines")
                except UnavailableRepresentation:
                    adapter_key = record.storage_kind, "lines"
                    adapter = get_adapter(adapter_key)
                    lines = adapter.get_bytes(record, "lines")
                try:
                    self.add_lines(record.key, parents, lines)
                except errors.RevisionAlreadyPresent:
                    pass
            # Add any records whose basis parent is now available.
            if not buffered:
                added_keys = [record.key]
                while added_keys:
                    key = added_keys.pop(0)
                    if key in buffered_index_entries:
                        index_entries = buffered_index_entries[key]
                        self._index.add_records(index_entries)
                        added_keys.extend(
                            [index_entry[0] for index_entry in index_entries]
                        )
                        del buffered_index_entries[key]
        if buffered_index_entries:
            # There were index entries buffered at the end of the stream,
            # So these need to be added (if the index supports holding such
            # entries for later insertion)
            all_entries = []
            for key in buffered_index_entries:
                index_entries = buffered_index_entries[key]
                all_entries.extend(index_entries)
            self._index.add_records(all_entries, missing_compression_parents=True)

    def get_missing_compression_parent_keys(self):
        """Return an iterable of keys of missing compression parents.

        Check this after calling insert_record_stream to find out if there are
        any missing compression parents.  If there are, the records that
        depend on them are not able to be inserted safely. For atomic
        KnitVersionedFiles built on packs, the transaction should be aborted or
        suspended - commit will fail at this point. Nonatomic knits will error
        earlier because they have no staging area to put pending entries into.
        """
        return self._index.get_missing_compression_parents()

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
         * Lines are normalised by the underlying store: they will all have \\n
           terminators.
         * Lines are returned in arbitrary order.
         * If a requested key did not change any lines (or didn't have any
           lines), it may not be mentioned at all in the result.

        :param pb: Progress bar supplied by caller.
        :return: An iterator over (line, key).
        """
        if pb is None:
            pb = ui.ui_factory.nested_progress_bar()
        keys = set(keys)
        total = len(keys)
        done = False
        while not done:
            try:
                # we don't care about inclusions, the caller cares.
                # but we need to setup a list of records to visit.
                # we need key, position, length
                key_records = []
                build_details = self._index.get_build_details(keys)
                for key, details in build_details.items():
                    if key in keys:
                        key_records.append((key, details[0]))
                records_iter = enumerate(self._read_records_iter(key_records))
                for key_idx, (key, data, _sha_value) in records_iter:
                    pb.update(gettext("Walking content"), key_idx, total)
                    compression_parent = build_details[key][1]
                    if compression_parent is None:
                        # fulltext
                        line_iterator = self._factory.get_fulltext_content(data)
                    else:
                        # Delta
                        line_iterator = self._factory.get_linedelta_content(data)
                    # Now that we are yielding the data for this key, remove it
                    # from the list
                    keys.remove(key)
                    # XXX: It might be more efficient to yield (key,
                    # line_iterator) in the future. However for now, this is a
                    # simpler change to integrate into the rest of the
                    # codebase. RBC 20071110
                    for line in line_iterator:
                        yield line, key
                done = True
            except pack_repo.RetryWithNewPacks as e:
                self._access.reload_or_raise(e)
        # If there are still keys we've not yet found, we look in the fallback
        # vfs, and hope to find them there.  Note that if the keys are found
        # but had no changes or no content, the fallback may not return
        # anything.
        if keys and not self._immediate_fallback_vfs:
            # XXX: strictly the second parameter is meant to be the file id
            # but it's not easily accessible here.
            raise RevisionNotPresent(keys, repr(self))
        for source in self._immediate_fallback_vfs:
            if not keys:
                break
            source_keys = set()
            for line, key in source.iter_lines_added_or_present_in_keys(keys):
                source_keys.add(key)
                yield line, key
            keys.difference_update(source_keys)
        pb.update(gettext("Walking content"), total, total)

    def _make_line_delta(self, delta_seq, new_content):
        """Generate a line delta from delta_seq and new_content."""
        diff_hunks = []
        for op in delta_seq.get_opcodes():
            if op[0] == "equal":
                continue
            diff_hunks.append(
                (op[1], op[2], op[4] - op[3], new_content._lines[op[3] : op[4]])
            )
        return diff_hunks

    def _merge_annotations(
        self,
        content,
        parents,
        parent_texts=None,
        delta=None,
        annotated=None,
        left_matching_blocks=None,
    ):
        """Merge annotations for content and generate deltas.

        This is done by comparing the annotations based on changes to the text
        and generating a delta on the resulting full texts. If annotations are
        not being created then a simple delta is created.
        """
        if parent_texts is None:
            parent_texts = {}
        if left_matching_blocks is not None:
            delta_seq = diff._PrematchedMatcher(left_matching_blocks)
        else:
            delta_seq = None
        if annotated:
            for parent_key in parents:
                merge_content = self._get_content(parent_key, parent_texts)
                if parent_key == parents[0] and delta_seq is not None:
                    seq = delta_seq
                else:
                    seq = patiencediff.PatienceSequenceMatcher(
                        None, merge_content.text(), content.text()
                    )
                for i, j, n in seq.get_matching_blocks():
                    if n == 0:
                        continue
                    # this copies (origin, text) pairs across to the new
                    # content for any line that matches the last-checked
                    # parent.
                    content._lines[j : j + n] = merge_content._lines[i : i + n]
            # XXX: Robert says the following block is a workaround for a
            # now-fixed bug and it can probably be deleted. -- mbp 20080618
            if content._lines and not content._lines[-1][1].endswith(b"\n"):
                # The copied annotation was from a line without a trailing EOL,
                # reinstate one for the content object, to ensure correct
                # serialization.
                line = content._lines[-1][1] + b"\n"
                content._lines[-1] = (content._lines[-1][0], line)
        if delta:
            if delta_seq is None:
                reference_content = self._get_content(parents[0], parent_texts)
                new_texts = content.text()
                old_texts = reference_content.text()
                delta_seq = patiencediff.PatienceSequenceMatcher(
                    None, old_texts, new_texts
                )
            return self._make_line_delta(delta_seq, content)

    def _parse_record(self, version_id, data):
        """Parse an original format knit record.

        These have the last element of the key only present in the stored data.
        """
        rec, record_contents = self._parse_record_unchecked(data)
        self._check_header_version(rec, version_id)
        return record_contents, rec[3]

    def _parse_record_header(self, key, raw_data):
        """Parse a record header for consistency.

        :return: the header and the decompressor stream.
                 as (stream, header_record)
        """
        df = gzip.GzipFile(mode="rb", fileobj=BytesIO(raw_data))
        try:
            # Current serialise
            rec = self._check_header(key, df.readline())
        except Exception as e:
            raise KnitCorrupt(
                self, f"While reading {{{key}}} got {e.__class__.__name__}({e!s})"
            ) from e
        return df, rec

    def _parse_record_unchecked(self, data):
        # profiling notes:
        # 4168 calls in 2880 217 internal
        # 4168 calls to _parse_record_header in 2121
        # 4168 calls to readlines in 330
        with gzip.GzipFile(mode="rb", fileobj=BytesIO(data)) as df:
            try:
                record_contents = df.readlines()
            except Exception as e:
                raise KnitCorrupt(
                    self,
                    f"Corrupt compressed record {data!r}, got {e.__class__.__name__}({e!s})",
                ) from e
            header = record_contents.pop(0)
            rec = self._split_header(header)
            last_line = record_contents.pop()
            if len(record_contents) != int(rec[2]):
                raise KnitCorrupt(
                    self,
                    "incorrect number of lines {} != {} for version {{{}}} {}".format(
                        len(record_contents), int(rec[2]), rec[1], record_contents
                    ),
                )
            if last_line != b"end %s\n" % rec[1]:
                raise KnitCorrupt(
                    self,
                    "unexpected version end line {!r}, wanted {!r}".format(
                        last_line, rec[1]
                    ),
                )
        return rec, record_contents

    def _read_records_iter(self, records):
        """Read text records from data file and yield result.

        The result will be returned in whatever is the fastest to read.
        Not by the order requested. Also, multiple requests for the same
        record will only yield 1 response.

        :param records: A list of (key, access_memo) entries
        :return: Yields (key, contents, digest) in the order
                 read, not the order requested
        """
        if not records:
            return

        # XXX: This smells wrong, IO may not be getting ordered right.
        needed_records = sorted(set(records), key=operator.itemgetter(1))
        if not needed_records:
            return

        # The transport optimizes the fetching as well
        # (ie, reads continuous ranges.)
        raw_data = self._access.get_raw_records(
            [index_memo for key, index_memo in needed_records]
        )

        for (key, _index_memo), data in zip(needed_records, raw_data):
            content, digest = self._parse_record(key[-1], data)
            yield key, content, digest

    def _read_records_iter_raw(self, records):
        """Read text records from data file and yield raw data.

        This unpacks enough of the text record to validate the id is
        as expected but thats all.

        Each item the iterator yields is (key, bytes,
            expected_sha1_of_full_text).
        """
        for key, data in self._read_records_iter_unchecked(records):
            # validate the header (note that we can only use the suffix in
            # current knit records).
            df, rec = self._parse_record_header(key, data)
            df.close()
            yield key, data, rec[3]

    def _read_records_iter_unchecked(self, records):
        """Read text records from data file and yield raw data.

        No validation is done.

        Yields tuples of (key, data).
        """
        # setup an iterator of the external records:
        # uses readv so nice and fast we hope.
        if len(records):
            # grab the disk data needed.
            needed_offsets = [index_memo for key, index_memo in records]
            raw_records = self._access.get_raw_records(needed_offsets)

        for key, _index_memo in records:
            data = next(raw_records)
            yield key, data

    def _record_to_data(self, key, digest, lines, dense_lines=None):
        r"""Convert key, digest, lines into a raw data block.

        :param key: The key of the record. Currently keys are always serialised
            using just the trailing component.
        :param dense_lines: The bytes of lines but in a denser form. For
            instance, if lines is a list of 1000 bytestrings each ending in
            \\n, dense_lines may be a list with one line in it, containing all
            the 1000's lines and their \\n's. Using dense_lines if it is
            already known is a win because the string join to create bytes in
            this function spends less time resizing the final string.
        :return: (len, chunked bytestring with compressed data)
        """
        chunks = [b"version %s %d %s\n" % (key[-1], len(lines), digest)]
        chunks.extend(dense_lines or lines)
        chunks.append(b"end " + key[-1] + b"\n")
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise AssertionError(
                    "data must be plain bytes was {}".format(type(chunk))
                )
        if lines and not lines[-1].endswith(b"\n"):
            raise ValueError("corrupt lines value {!r}".format(lines))
        compressed_chunks = tuned_gzip.chunks_to_gzip(chunks)
        return sum(map(len, compressed_chunks)), compressed_chunks

    def _split_header(self, line):
        rec = line.split()
        if len(rec) != 4:
            raise KnitCorrupt(self, "unexpected number of elements in record header")
        return rec

    def keys(self):
        """See VersionedFiles.keys."""
        if "evil" in debug.debug_flags:
            trace.mutter_callsite(2, "keys scales with size of history")
        sources = [self._index] + self._immediate_fallback_vfs
        result = set()
        for source in sources:
            result.update(source.keys())
        return result


class _ContentMapGenerator:
    """Generate texts or expose raw deltas for a set of texts."""

    def __init__(self, ordering="unordered"):
        self._ordering = ordering

    def _get_content(self, key):
        """Get the content object for key."""
        # Note that _get_content is only called when the _ContentMapGenerator
        # has been constructed with just one key requested for reconstruction.
        if key in self.nonlocal_keys:
            record = next(self.get_record_stream())
            # Create a content object on the fly
            lines = record.get_bytes_as("lines")
            return PlainKnitContent(lines, record.key)
        else:
            # local keys we can ask for directly
            return self._get_one_work(key)

    def get_record_stream(self):
        """Get a record stream for the keys requested during __init__."""
        yield from self._work()

    def _work(self):
        """Produce maps of text and KnitContents as dicts.

        :return: (text_map, content_map) where text_map contains the texts for
            the requested versions and content_map contains the KnitContents.
        """
        # NB: By definition we never need to read remote sources unless texts
        # are requested from them: we don't delta across stores - and we
        # explicitly do not want to to prevent data loss situations.
        if self.global_map is None:
            self.global_map = self.vf.get_parent_map(self.keys)
        nonlocal_keys = self.nonlocal_keys

        missing_keys = set(nonlocal_keys)
        # Read from remote versioned file instances and provide to our caller.
        for source in self.vf._immediate_fallback_vfs:
            if not missing_keys:
                break
            # Loop over fallback repositories asking them for texts - ignore
            # any missing from a particular fallback.
            for record in source.get_record_stream(missing_keys, self._ordering, True):
                if record.storage_kind == "absent":
                    # Not in thie particular stream, may be in one of the
                    # other fallback vfs objects.
                    continue
                missing_keys.remove(record.key)
                yield record

        if self._raw_record_map is None:
            raise AssertionError("_raw_record_map should have been filled")
        first = True
        for key in self.keys:
            if key in self.nonlocal_keys:
                continue
            yield LazyKnitContentFactory(key, self.global_map[key], self, first)
            first = False

    def _get_one_work(self, requested_key):
        # Now, if we have calculated everything already, just return the
        # desired text.
        if requested_key in self._contents_map:
            return self._contents_map[requested_key]
        # To simplify things, parse everything at once - code that wants one text
        # probably wants them all.
        # FUTURE: This function could be improved for the 'extract many' case
        # by tracking each component and only doing the copy when the number of
        # children than need to apply delta's to it is > 1 or it is part of the
        # final output.
        multiple_versions = len(self.keys) != 1
        if self._record_map is None:
            self._record_map = self.vf._raw_map_to_record_map(self._raw_record_map)
        record_map = self._record_map
        # raw_record_map is key:
        # Have read and parsed records at this point.
        for key in self.keys:
            if key in self.nonlocal_keys:
                # already handled
                continue
            components = []
            cursor = key
            while cursor is not None:
                try:
                    record, record_details, digest, next = record_map[cursor]
                except KeyError as e:
                    raise RevisionNotPresent(cursor, self) from e
                components.append((cursor, record, record_details, digest))
                cursor = next
                if cursor in self._contents_map:
                    # no need to plan further back
                    components.append((cursor, None, None, None))
                    break

            content = None
            for component_id, record, record_details, digest in reversed(components):  # noqa: B007
                if component_id in self._contents_map:
                    content = self._contents_map[component_id]
                else:
                    content, delta = self._factory.parse_record(
                        key[-1],
                        record,
                        record_details,
                        content,
                        copy_base_content=multiple_versions,
                    )
                    if multiple_versions:
                        self._contents_map[component_id] = content

            # digest here is the digest from the last applied component.
            text = content.text()
            actual_sha = sha_strings(text)
            if actual_sha != digest:
                raise SHA1KnitCorrupt(self, actual_sha, digest, key, text)
        if multiple_versions:
            return self._contents_map[requested_key]
        else:
            return content

    def _wire_bytes(self):
        """Get the bytes to put on the wire for 'key'.

        The first collection of bytes asked for returns the serialised
        raw_record_map and the additional details (key, parent) for key.
        Subsequent calls return just the additional details (key, parent).
        The wire storage_kind given for the first key is 'knit-delta-closure',
        For subsequent keys it is 'knit-delta-closure-ref'.

        :param key: A key from the content generator.
        :return: Bytes to put on the wire.
        """
        lines = []
        # kind marker for dispatch on the far side,
        lines.append(b"knit-delta-closure")
        # Annotated or not
        if self.vf._factory.annotated:
            lines.append(b"annotated")
        else:
            lines.append(b"")
        # then the list of keys
        lines.append(
            b"\t".join(
                b"\x00".join(key) for key in self.keys if key not in self.nonlocal_keys
            )
        )
        # then the _raw_record_map in serialised form:
        map_byte_list = []
        # for each item in the map:
        # 1 line with key
        # 1 line with parents if the key is to be yielded (None: for None, '' for ())
        # one line with method
        # one line with noeol
        # one line with next ('' for None)
        # one line with byte count of the record bytes
        # the record bytes
        for key, (record_bytes, (method, noeol), next) in self._raw_record_map.items():
            key_bytes = b"\x00".join(key)
            parents = self.global_map.get(key, None)
            if parents is None:
                parent_bytes = b"None:"
            else:
                parent_bytes = b"\t".join(b"\x00".join(key) for key in parents)
            method_bytes = method.encode("ascii")
            if noeol:
                noeol_bytes = b"T"
            else:
                noeol_bytes = b"F"
            if next:
                next_bytes = b"\x00".join(next)
            else:
                next_bytes = b""
            map_byte_list.append(
                b"\n".join(
                    [
                        key_bytes,
                        parent_bytes,
                        method_bytes,
                        noeol_bytes,
                        next_bytes,
                        b"%d" % len(record_bytes),
                        record_bytes,
                    ]
                )
            )
        map_bytes = b"".join(map_byte_list)
        lines.append(map_bytes)
        bytes = b"\n".join(lines)
        return bytes


class _VFContentMapGenerator(_ContentMapGenerator):
    """Content map generator reading from a VersionedFiles object."""

    def __init__(
        self,
        versioned_files,
        keys,
        nonlocal_keys=None,
        global_map=None,
        raw_record_map=None,
        ordering="unordered",
    ):
        """Create a _ContentMapGenerator.

        :param versioned_files: The versioned files that the texts are being
            extracted from.
        :param keys: The keys to produce content maps for.
        :param nonlocal_keys: An iterable of keys(possibly intersecting keys)
            which are known to not be in this knit, but rather in one of the
            fallback knits.
        :param global_map: The result of get_parent_map(keys) (or a supermap).
            This is required if get_record_stream() is to be used.
        :param raw_record_map: A unparsed raw record map to use for answering
            contents.
        """
        _ContentMapGenerator.__init__(self, ordering=ordering)
        # The vf to source data from
        self.vf = versioned_files
        # The keys desired
        self.keys = list(keys)
        # Keys known to be in fallback vfs objects
        if nonlocal_keys is None:
            self.nonlocal_keys = set()
        else:
            self.nonlocal_keys = frozenset(nonlocal_keys)
        # Parents data for keys to be returned in get_record_stream
        self.global_map = global_map
        # The chunked lists for self.keys in text form
        self._text_map = {}
        # A cache of KnitContent objects used in extracting texts.
        self._contents_map = {}
        # All the knit records needed to assemble the requested keys as full
        # texts.
        self._record_map = None
        if raw_record_map is None:
            self._raw_record_map = self.vf._get_record_map_unparsed(
                keys, allow_missing=True
            )
        else:
            self._raw_record_map = raw_record_map
        # the factory for parsing records
        self._factory = self.vf._factory


class _NetworkContentMapGenerator(_ContentMapGenerator):
    """Content map generator sourced from a network stream."""

    def __init__(self, bytes, line_end):
        """Construct a _NetworkContentMapGenerator from a bytes block."""
        self._bytes = bytes
        self.global_map = {}
        self._raw_record_map = {}
        self._contents_map = {}
        self._record_map = None
        self.nonlocal_keys = []
        # Get access to record parsing facilities
        self.vf = KnitVersionedFiles(None, None)
        start = line_end
        # Annotated or not
        line_end = bytes.find(b"\n", start)
        line = bytes[start:line_end]
        start = line_end + 1
        if line == b"annotated":
            self._factory = KnitAnnotateFactory()
        else:
            self._factory = KnitPlainFactory()
        # list of keys to emit in get_record_stream
        line_end = bytes.find(b"\n", start)
        line = bytes[start:line_end]
        start = line_end + 1
        self.keys = [
            tuple(segment.split(b"\x00")) for segment in line.split(b"\t") if segment
        ]
        # now a loop until the end. XXX: It would be nice if this was just a
        # bunch of the same records as get_record_stream(..., False) gives, but
        # there is a decent sized gap stopping that at the moment.
        end = len(bytes)
        while start < end:
            # 1 line with key
            line_end = bytes.find(b"\n", start)
            key = tuple(bytes[start:line_end].split(b"\x00"))
            start = line_end + 1
            # 1 line with parents (None: for None, '' for ())
            line_end = bytes.find(b"\n", start)
            line = bytes[start:line_end]
            if line == b"None:":
                parents = None
            else:
                parents = tuple(
                    tuple(segment.split(b"\x00"))
                    for segment in line.split(b"\t")
                    if segment
                )
            self.global_map[key] = parents
            start = line_end + 1
            # one line with method
            line_end = bytes.find(b"\n", start)
            line = bytes[start:line_end]
            method = line.decode("ascii")
            start = line_end + 1
            # one line with noeol
            line_end = bytes.find(b"\n", start)
            line = bytes[start:line_end]
            noeol = line == b"T"
            start = line_end + 1
            # one line with next (b'' for None)
            line_end = bytes.find(b"\n", start)
            line = bytes[start:line_end]
            if not line:
                next = None
            else:
                next = tuple(bytes[start:line_end].split(b"\x00"))
            start = line_end + 1
            # one line with byte count of the record bytes
            line_end = bytes.find(b"\n", start)
            line = bytes[start:line_end]
            count = int(line)
            start = line_end + 1
            # the record bytes
            record_bytes = bytes[start : start + count]
            start = start + count
            # put it in the map
            self._raw_record_map[key] = (record_bytes, (method, noeol), next)

    def get_record_stream(self):
        """Get a record stream for for keys requested by the bytestream."""
        first = True
        for key in self.keys:
            yield LazyKnitContentFactory(key, self.global_map[key], self, first)
            first = False

    def _wire_bytes(self):
        return self._bytes


class _KndxIndex:
    r"""Manages knit index files.

    The index is kept in memory and read on startup, to enable
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
        that the compressed data starts at.
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

    :ivar _kndx_cache: dict from prefix to the old state of KnitIndex objects,
        where prefix is e.g. the (fileid,) for .texts instances or () for
        constant-mapped things like .revisions, and the old state is
        tuple(history_vector, cache_dict).  This is used to prevent having an
        ABI change with the C extension that reads .kndx files.
    """

    HEADER = b"# bzr knit index 8\n"

    def __init__(self, transport, mapper, get_scope, allow_writes, is_locked):
        """Create a _KndxIndex on transport using mapper."""
        self._transport = transport
        self._mapper = mapper
        self._get_scope = get_scope
        self._allow_writes = allow_writes
        self._is_locked = is_locked
        self._reset_cache()
        self.has_graph = True

    def add_records(self, records, random_id=False, missing_compression_parents=False):
        """Add multiple records to the index.

        :param records: a list of tuples:
                         (key, options, access_memo, parents).
        :param random_id: If True the ids being added were randomly generated
            and no check for existence will be performed.
        :param missing_compression_parents: If True the records being added are
            only compressed against texts already in the index (or inside
            records). If False the records all refer to unavailable texts (or
            texts inside records) as compression parents.
        """
        if missing_compression_parents:
            # It might be nice to get the edge of the records. But keys isn't
            # _wrong_.
            keys = sorted(record[0] for record in records)
            raise errors.RevisionNotPresent(keys, self)
        paths = {}
        for record in records:
            key = record[0]
            prefix = key[:-1]
            path = self._mapper.map(key) + ".kndx"
            path_keys = paths.setdefault(path, (prefix, []))
            path_keys[1].append(record)
        for path in sorted(paths):
            prefix, path_keys = paths[path]
            self._load_prefixes([prefix])
            lines = []
            orig_history = self._kndx_cache[prefix][1][:]
            orig_cache = self._kndx_cache[prefix][0].copy()

            try:
                for key, options, (_, pos, size), parents in path_keys:
                    if not all(isinstance(option, bytes) for option in options):
                        raise TypeError(options)
                    if parents is None:
                        # kndx indices cannot be parentless.
                        parents = ()
                    line = b" ".join(
                        [
                            b"\n" + key[-1],
                            b",".join(options),
                            b"%d" % pos,
                            b"%d" % size,
                            self._dictionary_compress(parents),
                            b":",
                        ]
                    )
                    if not isinstance(line, bytes):
                        raise AssertionError(
                            "data must be utf8 was {}".format(type(line))
                        )
                    lines.append(line)
                    self._cache_key(key, options, pos, size, parents)
                if len(orig_history):
                    self._transport.append_bytes(path, b"".join(lines))
                else:
                    self._init_index(path, lines)
            except:
                # If any problems happen, restore the original values and re-raise
                self._kndx_cache[prefix] = (orig_cache, orig_history)
                raise

    def scan_unvalidated_index(self, graph_index):
        """See _KnitGraphIndex.scan_unvalidated_index."""
        # Because kndx files do not support atomic insertion via separate index
        # files, they do not support this method.
        raise NotImplementedError(self.scan_unvalidated_index)

    def get_missing_compression_parents(self):
        """See _KnitGraphIndex.get_missing_compression_parents."""
        # Because kndx files do not support atomic insertion via separate index
        # files, they do not support this method.
        raise NotImplementedError(self.get_missing_compression_parents)

    def _cache_key(self, key, options, pos, size, parent_keys):
        """Cache a version record in the history array and index cache.

        This is inlined into _load_data for performance. KEEP IN SYNC.
        (It saves 60ms, 25% of the __init__ overhead on local 4000 record
         indexes).
        """
        prefix = key[:-1]
        version_id = key[-1]
        # last-element only for compatibilty with the C load_data.
        parents = tuple(parent[-1] for parent in parent_keys)
        for parent in parent_keys:
            if parent[:-1] != prefix:
                raise ValueError(
                    "mismatched prefixes for {!r}, {!r}".format(key, parent_keys)
                )
        cache, history = self._kndx_cache[prefix]
        # only want the _history index to reference the 1st index entry
        # for version_id
        if version_id not in cache:
            index = len(history)
            history.append(version_id)
        else:
            index = cache[version_id][5]
        cache[version_id] = (version_id, options, pos, size, parents, index)

    def check_header(self, fp):
        line = fp.readline()
        if line == b"":
            # An empty file can actually be treated as though the file doesn't
            # exist yet.
            raise _mod_transport.NoSuchFile(self)
        if line != self.HEADER:
            raise KnitHeaderError(badline=line, filename=self)

    def _check_read(self):
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        if self._get_scope() != self._scope:
            self._reset_cache()

    def _check_write_ok(self):
        """Assert if not writes are permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        if self._get_scope() != self._scope:
            self._reset_cache()
        if self._mode != "w":
            raise errors.ReadOnlyObjectDirtiedError(self)

    def get_build_details(self, keys):
        """Get the method, index_memo and compression parent for keys.

        Ghosts are omitted from the result.

        :param keys: An iterable of keys.
        :return: A dict of key:(index_memo, compression_parent, parents,
            record_details).
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
        parent_map = self.get_parent_map(keys)
        result = {}
        for key in keys:
            if key not in parent_map:
                continue  # Ghost
            method = self.get_method(key)
            if not isinstance(method, str):
                raise TypeError(method)
            parents = parent_map[key]
            if method == "fulltext":
                compression_parent = None
            else:
                compression_parent = parents[0]
            noeol = b"no-eol" in self.get_options(key)
            index_memo = self.get_position(key)
            result[key] = (index_memo, compression_parent, parents, (method, noeol))
        return result

    def get_method(self, key):
        """Return compression method of specified key."""
        options = self.get_options(key)
        if b"fulltext" in options:
            return "fulltext"
        elif b"line-delta" in options:
            return "line-delta"
        else:
            raise KnitIndexUnknownMethod(self, options)

    def get_options(self, key):
        """Return a list representing options.

        e.g. ['foo', 'bar']
        """
        prefix, suffix = self._split_key(key)
        self._load_prefixes([prefix])
        try:
            return self._kndx_cache[prefix][0][suffix][1]
        except KeyError as e:
            raise RevisionNotPresent(key, self) from e

    def find_ancestry(self, keys):
        """See CombinedGraphIndex.find_ancestry()."""
        prefixes = {key[:-1] for key in keys}
        self._load_prefixes(prefixes)
        parent_map = {}
        missing_keys = set()
        pending_keys = list(keys)
        # This assumes that keys will not reference parents in a different
        # prefix, which is accurate so far.
        while pending_keys:
            key = pending_keys.pop()
            if key in parent_map:
                continue
            prefix = key[:-1]
            try:
                suffix_parents = self._kndx_cache[prefix][0][key[-1]][4]
            except KeyError:
                missing_keys.add(key)
            else:
                parent_keys = tuple([prefix + (suffix,) for suffix in suffix_parents])
                parent_map[key] = parent_keys
                pending_keys.extend([p for p in parent_keys if p not in parent_map])
        return parent_map, missing_keys

    def get_parent_map(self, keys):
        """Get a map of the parents of keys.

        :param keys: The keys to look up parents for.
        :return: A mapping from keys to parents. Absent keys are absent from
            the mapping.
        """
        # Parse what we need to up front, this potentially trades off I/O
        # locality (.kndx and .knit in the same block group for the same file
        # id) for less checking in inner loops.
        prefixes = {key[:-1] for key in keys}
        self._load_prefixes(prefixes)
        result = {}
        for key in keys:
            prefix = key[:-1]
            try:
                suffix_parents = self._kndx_cache[prefix][0][key[-1]][4]
            except KeyError:
                pass
            else:
                result[key] = tuple(prefix + (suffix,) for suffix in suffix_parents)
        return result

    def get_position(self, key):
        """Return details needed to access the version.

        :return: a tuple (key, data position, size) to hand to the access
            logic to get the record.
        """
        prefix, suffix = self._split_key(key)
        self._load_prefixes([prefix])
        entry = self._kndx_cache[prefix][0][suffix]
        return key, entry[2], entry[3]

    __contains__ = _mod_index._has_key_from_parent_map

    def _init_index(self, path, extra_lines=None):
        """Initialize an index."""
        if extra_lines is None:
            extra_lines = []
        sio = BytesIO()
        sio.write(self.HEADER)
        sio.writelines(extra_lines)
        sio.seek(0)
        self._transport.put_file_non_atomic(path, sio, create_parent_dir=True)
        # self._create_parent_dir)
        # mode=self._file_mode,
        # dir_mode=self._dir_mode)

    def keys(self):
        """Get all the keys in the collection.

        The keys are not ordered.
        """
        result = set()
        # Identify all key prefixes.
        # XXX: A bit hacky, needs polish.
        if isinstance(self._mapper, ConstantMapper):
            prefixes = [()]
        else:
            relpaths = set()
            for quoted_relpath in self._transport.iter_files_recursive():
                path, ext = os.path.splitext(quoted_relpath)
                relpaths.add(path)
            prefixes = [self._mapper.unmap(path) for path in relpaths]
        self._load_prefixes(prefixes)
        for prefix in prefixes:
            for suffix in self._kndx_cache[prefix][1]:
                result.add(prefix + (suffix,))
        return result

    def _load_prefixes(self, prefixes):
        """Load the indices for prefixes."""
        self._check_read()
        for prefix in prefixes:
            if prefix not in self._kndx_cache:
                # the load_data interface writes to these variables.
                self._cache = {}
                self._history = []
                self._filename = prefix
                try:
                    path = self._mapper.map(prefix) + ".kndx"
                    with self._transport.get(path) as fp:
                        # _load_data may raise NoSuchFile if the target knit is
                        # completely empty.
                        _load_data(self, fp)
                    self._kndx_cache[prefix] = (self._cache, self._history)
                    del self._cache
                    del self._filename
                    del self._history
                except NoSuchFile:
                    self._kndx_cache[prefix] = ({}, [])
                    if isinstance(self._mapper, ConstantMapper):
                        # preserve behaviour for revisions.kndx etc.
                        self._init_index(path)
                    del self._cache
                    del self._filename
                    del self._history

    missing_keys = _mod_index._missing_keys_from_parent_map

    def _partition_keys(self, keys):
        """Turn keys into a dict of prefix:suffix_list."""
        result = {}
        for key in keys:
            prefix_keys = result.setdefault(key[:-1], [])
            prefix_keys.append(key[-1])
        return result

    def _dictionary_compress(self, keys):
        """Dictionary compress keys.

        :param keys: The keys to generate references to.
        :return: A string representation of keys. keys which are present are
            dictionary compressed, and others are emitted as fulltext with a
            '.' prefix.
        """
        if not keys:
            return b""
        result_list = []
        prefix = keys[0][:-1]
        cache = self._kndx_cache[prefix][0]
        for key in keys:
            if key[:-1] != prefix:
                # kndx indices cannot refer across partitioned storage.
                raise ValueError("mismatched prefixes for {!r}".format(keys))
            if key[-1] in cache:
                # -- inlined lookup() --
                result_list.append(b"%d" % cache[key[-1]][5])
                # -- end lookup () --
            else:
                result_list.append(b"." + key[-1])
        return b" ".join(result_list)

    def _reset_cache(self):
        # Possibly this should be a LRU cache. A dictionary from key_prefix to
        # (cache_dict, history_vector) for parsed kndx files.
        self._kndx_cache = {}
        self._scope = self._get_scope()
        allow_writes = self._allow_writes()
        if allow_writes:
            self._mode = "w"
        else:
            self._mode = "r"

    def _sort_keys_by_io(self, keys, positions):
        """Figure out an optimal order to read the records for the given keys.

        Sort keys, grouped by index and sorted by position.

        :param keys: A list of keys whose records we want to read. This will be
            sorted 'in-place'.
        :param positions: A dict, such as the one returned by
            _get_components_positions()
        :return: None
        """

        def get_sort_key(key):
            index_memo = positions[key][1]
            # Group by prefix and position. index_memo[0] is the key, so it is
            # (file_id, revision_id) and we don't want to sort on revision_id,
            # index_memo[1] is the position, and index_memo[2] is the size,
            # which doesn't matter for the sort
            return index_memo[0][:-1], index_memo[1]

        return keys.sort(key=get_sort_key)

    _get_total_build_size = _get_total_build_size

    def _split_key(self, key):
        """Split key into a prefix and suffix."""
        # GZ 2018-07-03: This is intentionally either a sequence or bytes?
        if isinstance(key, bytes):
            return key[:-1], key[-1:]
        return key[:-1], key[-1]


def as_tuples(obj):
    """Ensure that the object and any referenced objects are plain tuples.

    :param obj: a list, tuple or StaticTuple
    :return: a plain tuple instance, with all children also being tuples.
    """
    result = []
    for item in obj:
        if isinstance(item, (tuple, list)):
            item = as_tuples(item)
        result.append(item)
    return tuple(result)


class _KnitGraphIndex:
    """A KnitVersionedFiles index layered on GraphIndex."""

    def __init__(
        self,
        graph_index,
        is_locked,
        deltas=False,
        parents=True,
        add_callback=None,
        track_external_parent_refs=False,
    ):
        """Construct a KnitGraphIndex on a graph_index.

        :param graph_index: An implementation of breezy.index.GraphIndex.
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
        :param track_external_parent_refs: If True, record all external parent
            references parents from added records.  These can be retrieved
            later by calling get_missing_parents().
        """
        self._add_callback = add_callback
        self._graph_index = graph_index
        self._deltas = deltas
        self._parents = parents
        if deltas and not parents:
            # XXX: TODO: Delta tree and parent graph should be conceptually
            # separate.
            raise KnitCorrupt(
                self, "Cannot do delta compression without parent tracking."
            )
        self.has_graph = parents
        self._is_locked = is_locked
        self._missing_compression_parents = set()
        if track_external_parent_refs:
            self._key_dependencies = _KeyRefs()
        else:
            self._key_dependencies = None

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, self._graph_index)

    def add_records(self, records, random_id=False, missing_compression_parents=False):
        """Add multiple records to the index.

        This function does not insert data into the Immutable GraphIndex
        backing the KnitGraphIndex, instead it prepares data for insertion by
        the caller and checks that it is safe to insert then calls
        self._add_callback with the prepared GraphIndex nodes.

        :param records: a list of tuples:
                         (key, options, access_memo, parents).
        :param random_id: If True the ids being added were randomly generated
            and no check for existence will be performed.
        :param missing_compression_parents: If True the records being added are
            only compressed against texts already in the index (or inside
            records). If False the records all refer to unavailable texts (or
            texts inside records) as compression parents.
        """
        if not self._add_callback:
            raise errors.ReadOnlyError(self)
        # we hope there are no repositories with inconsistent parentage
        # anymore.

        keys = {}
        compression_parents = set()
        key_dependencies = self._key_dependencies
        for key, options, access_memo, parents in records:
            if self._parents:
                parents = tuple(parents)
                if key_dependencies is not None:
                    key_dependencies.add_references(key, parents)
            index, pos, size = access_memo
            if b"no-eol" in options:
                value = b"N"
            else:
                value = b" "
            value += b"%d %d" % (pos, size)
            if not self._deltas:
                if b"line-delta" in options:
                    raise KnitCorrupt(
                        self, "attempt to add line-delta in non-delta knit"
                    )
            if self._parents:
                if self._deltas:
                    if b"line-delta" in options:
                        node_refs = (parents, (parents[0],))
                        if missing_compression_parents:
                            compression_parents.add(parents[0])
                    else:
                        node_refs = (parents, ())
                else:
                    node_refs = (parents,)
            else:
                if parents:
                    raise KnitCorrupt(
                        self, "attempt to add node with parents in parentless index."
                    )
                node_refs = ()
            keys[key] = (value, node_refs)
        # check for dups
        if not random_id:
            present_nodes = self._get_entries(keys)
            for _index, key, value, node_refs in present_nodes:
                parents = node_refs[:1]
                # Sometimes these are passed as a list rather than a tuple
                passed = as_tuples(keys[key])
                passed_parents = passed[1][:1]
                if value[0:1] != keys[key][0][0:1] or parents != passed_parents:
                    node_refs = as_tuples(node_refs)
                    raise KnitCorrupt(
                        self,
                        "inconsistent details in add_records: {} {}".format(
                            (value, node_refs), passed
                        ),
                    )
                del keys[key]
        result = []
        if self._parents:
            for key, (value, node_refs) in keys.items():
                result.append((key, value, node_refs))
        else:
            for key, (value, node_refs) in keys.items():  # noqa: B007
                result.append((key, value))
        self._add_callback(result)
        if missing_compression_parents:
            # This may appear to be incorrect (it does not check for
            # compression parents that are in the existing graph index),
            # but such records won't have been buffered, so this is
            # actually correct: every entry when
            # missing_compression_parents==True either has a missing parent, or
            # a parent that is one of the keys in records.
            compression_parents.difference_update(keys)
            self._missing_compression_parents.update(compression_parents)
        # Adding records may have satisfied missing compression parents.
        self._missing_compression_parents.difference_update(keys)

    def scan_unvalidated_index(self, graph_index):
        """Inform this _KnitGraphIndex that there is an unvalidated index.

        This allows this _KnitGraphIndex to keep track of any missing
        compression parents we may want to have filled in to make those
        indices valid.

        :param graph_index: A GraphIndex
        """
        if self._deltas:
            new_missing = graph_index.external_references(ref_list_num=1)
            new_missing.difference_update(self.get_parent_map(new_missing))
            self._missing_compression_parents.update(new_missing)
        if self._key_dependencies is not None:
            # Add parent refs from graph_index (and discard parent refs that
            # the graph_index has).
            for node in graph_index.iter_all_entries():
                self._key_dependencies.add_references(node[1], node[3][0])

    def get_missing_compression_parents(self):
        """Return the keys of missing compression parents.

        Missing compression parents occur when a record stream was missing
        basis texts, or a index was scanned that had missing basis texts.
        """
        return frozenset(self._missing_compression_parents)

    def get_missing_parents(self):
        """Return the keys of missing parents."""
        # If updating this, you should also update
        # groupcompress._GCGraphIndex.get_missing_parents
        # We may have false positives, so filter those out.
        self._key_dependencies.satisfy_refs_for_keys(
            self.get_parent_map(self._key_dependencies.get_unsatisfied_refs())
        )
        return frozenset(self._key_dependencies.get_unsatisfied_refs())

    def _check_read(self):
        """Raise if reads are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

    def _check_write_ok(self):
        """Assert if writes are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

    def _compression_parent(self, an_entry):
        # return the key that an_entry is compressed against, or None
        # Grab the second parent list (as deltas implies parents currently)
        compression_parents = an_entry[3][1]
        if not compression_parents:
            return None
        if len(compression_parents) != 1:
            raise AssertionError(
                "Too many compression parents: {!r}".format(compression_parents)
            )
        return compression_parents[0]

    def get_build_details(self, keys):
        """Get the method, index_memo and compression parent for version_ids.

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
                parents = ()
            else:
                parents = entry[3][0]
            if not self._deltas:
                compression_parent_key = None
            else:
                compression_parent_key = self._compression_parent(entry)
            noeol = entry[2][0:1] == b"N"
            if compression_parent_key:
                method = "line-delta"
            else:
                method = "fulltext"
            result[key] = (
                self._node_to_position(entry),
                compression_parent_key,
                parents,
                (method, noeol),
            )
        return result

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

    def get_method(self, key):
        """Return compression method of specified key."""
        return self._get_method(self._get_node(key))

    def _get_method(self, node):
        if not self._deltas:
            return "fulltext"
        if self._compression_parent(node):
            return "line-delta"
        else:
            return "fulltext"

    def _get_node(self, key):
        try:
            return list(self._get_entries([key]))[0]
        except IndexError as e:
            raise RevisionNotPresent(key, self) from e

    def get_options(self, key):
        """Return a list representing options.

        e.g. ['foo', 'bar']
        """
        node = self._get_node(key)
        options = [self._get_method(node).encode("ascii")]
        if node[2][0:1] == b"N":
            options.append(b"no-eol")
        return options

    def find_ancestry(self, keys):
        """See CombinedGraphIndex.find_ancestry()."""
        return self._graph_index.find_ancestry(keys, 0)

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

    def get_position(self, key):
        """Return details needed to access the version.

        :return: a tuple (index, data position, size) to hand to the access
            logic to get the record.
        """
        node = self._get_node(key)
        return self._node_to_position(node)

    __contains__ = _mod_index._has_key_from_parent_map

    def keys(self):
        """Get all the keys in the collection.

        The keys are not ordered.
        """
        self._check_read()
        return [node[1] for node in self._graph_index.iter_all_entries()]

    missing_keys = _mod_index._missing_keys_from_parent_map

    def _node_to_position(self, node):
        """Convert an index value to position details."""
        bits = node[2][1:].split(b" ")
        return node[0], int(bits[0]), int(bits[1])

    def _sort_keys_by_io(self, keys, positions):
        """Figure out an optimal order to read the records for the given keys.

        Sort keys, grouped by index and sorted by position.

        :param keys: A list of keys whose records we want to read. This will be
            sorted 'in-place'.
        :param positions: A dict, such as the one returned by
            _get_components_positions()
        :return: None
        """

        def get_index_memo(key):
            # index_memo is at offset [1]. It is made up of (GraphIndex,
            # position, size). GI is an object, which will be unique for each
            # pack file. This causes us to group by pack file, then sort by
            # position. Size doesn't matter, but it isn't worth breaking up the
            # tuple.
            return positions[key][1]

        return keys.sort(key=get_index_memo)

    _get_total_build_size = _get_total_build_size


class _KnitKeyAccess:
    """Access to records in .knit files."""

    def __init__(self, transport, mapper):
        """Create a _KnitKeyAccess with transport and mapper.

        :param transport: The transport the access object is rooted at.
        :param mapper: The mapper used to map keys to .knit files.
        """
        self._transport = transport
        self._mapper = mapper

    def add_raw_record(self, key, size, raw_data):
        """Add raw knit bytes to a storage area.

        The data is spooled to the container writer in one bytes-record per
        raw data item.

        :param key: The key of the raw data segment
        :param size: The size of the raw data segment
        :param raw_data: A chunked bytestring containing the data.
        :return: opaque index memo to retrieve the record later.
            For _KnitKeyAccess the memo is (key, pos, length), where the key is
            the record key.
        """
        path = self._mapper.map(key)
        try:
            base = self._transport.append_bytes(path + ".knit", b"".join(raw_data))
        except _mod_transport.NoSuchFile:
            self._transport.mkdir(osutils.dirname(path))
            base = self._transport.append_bytes(path + ".knit", b"".join(raw_data))
        # if base == 0:
        # chmod.
        return (key, base, size)

    def add_raw_records(self, key_sizes, raw_data):
        """Add raw knit bytes to a storage area.

        The data is spooled to the container writer in one bytes-record per
        raw data item.

        :param sizes: An iterable of tuples containing the key and size of each
            raw data segment.
        :param raw_data: A chunked bytestring containing the data.
        :return: A list of memos to retrieve the record later. Each memo is an
            opaque index memo. For _KnitKeyAccess the memo is (key, pos,
            length), where the key is the record key.
        """
        raw_data = b"".join(raw_data)
        if not isinstance(raw_data, bytes):
            raise AssertionError(
                "data must be plain bytes was {}".format(type(raw_data))
            )
        result = []
        offset = 0
        # TODO: This can be tuned for writing to sftp and other servers where
        # append() is relatively expensive by grouping the writes to each key
        # prefix.
        for key, size in key_sizes:
            record_bytes = [raw_data[offset : offset + size]]
            result.append(self.add_raw_record(key, size, record_bytes))
            offset += size
        return result

    def flush(self):
        """Flush pending writes on this access object.

        For .knit files this is a no-op.
        """
        pass

    def get_raw_records(self, memos_for_retrieval):
        """Get the raw bytes for a records.

        :param memos_for_retrieval: An iterable containing the access memo for
            retrieving the bytes.
        :return: An iterator over the bytes of the records.
        """
        # first pass, group into same-index request to minimise readv's issued.
        request_lists = []
        current_prefix = None
        for key, offset, length in memos_for_retrieval:
            if current_prefix == key[:-1]:
                current_list.append((offset, length))
            else:
                if current_prefix is not None:
                    request_lists.append((current_prefix, current_list))
                current_prefix = key[:-1]
                current_list = [(offset, length)]
        # handle the last entry
        if current_prefix is not None:
            request_lists.append((current_prefix, current_list))
        for prefix, read_vector in request_lists:
            path = self._mapper.map(prefix) + ".knit"
            for _pos, data in self._transport.readv(path, read_vector):
                yield data


def annotate_knit(knit, revision_id):
    """Annotate a knit with no cached annotations.

    This implementation is for knits with no cached annotations.
    It will work for knits with cached annotations, but this is not
    recommended.
    """
    annotator = _KnitAnnotator(knit)
    return iter(annotator.annotate_flat(revision_id))


class _KnitAnnotator(annotate.Annotator):
    """Build up the annotations for a text."""

    def __init__(self, vf):
        annotate.Annotator.__init__(self, vf)

        # TODO: handle Nodes which cannot be extracted
        # self._ghosts = set()

        # Map from (key, parent_key) => matching_blocks, should be 'use once'
        self._matching_blocks = {}

        # KnitContent objects
        self._content_objects = {}
        # The number of children that depend on this fulltext content object
        self._num_compression_children = {}
        # Delta records that need their compression parent before they can be
        # expanded
        self._pending_deltas = {}
        # Fulltext records that are waiting for their parents fulltexts before
        # they can be yielded for annotation
        self._pending_annotation = {}

        self._all_build_details = {}

    def _get_build_graph(self, key):
        """Get the graphs for building texts and annotations.

        The data you need for creating a full text may be different than the
        data you need to annotate that text. (At a minimum, you need both
        parents to create an annotation, but only need 1 parent to generate the
        fulltext.)

        :return: A list of (key, index_memo) records, suitable for
            passing to read_records_iter to start reading in the raw data from
            the pack file.
        """
        pending = {key}
        records = []
        ann_keys = set()
        self._num_needed_children[key] = 1
        while pending:
            # get all pending nodes
            this_iteration = pending
            build_details = self._vf._index.get_build_details(this_iteration)
            self._all_build_details.update(build_details)
            # new_nodes = self._vf._index._get_entries(this_iteration)
            pending = set()
            for key, details in build_details.items():
                (index_memo, compression_parent, parent_keys, record_details) = details
                self._parent_map[key] = parent_keys
                self._heads_provider = None
                records.append((key, index_memo))
                # Do we actually need to check _annotated_lines?
                pending.update(
                    [p for p in parent_keys if p not in self._all_build_details]
                )
                if parent_keys:
                    for parent_key in parent_keys:
                        if parent_key in self._num_needed_children:
                            self._num_needed_children[parent_key] += 1
                        else:
                            self._num_needed_children[parent_key] = 1
                if compression_parent:
                    if compression_parent in self._num_compression_children:
                        self._num_compression_children[compression_parent] += 1
                    else:
                        self._num_compression_children[compression_parent] = 1

            missing_versions = this_iteration.difference(build_details)
            if missing_versions:
                for key in missing_versions:
                    if key in self._parent_map and key in self._text_cache:
                        # We already have this text ready, we just need to
                        # yield it later so we get it annotated
                        ann_keys.add(key)
                        parent_keys = self._parent_map[key]
                        for parent_key in parent_keys:
                            if parent_key in self._num_needed_children:
                                self._num_needed_children[parent_key] += 1
                            else:
                                self._num_needed_children[parent_key] = 1
                        pending.update(
                            [p for p in parent_keys if p not in self._all_build_details]
                        )
                    else:
                        raise errors.RevisionNotPresent(key, self._vf)
        # Generally we will want to read the records in reverse order, because
        # we find the parent nodes after the children
        records.reverse()
        return records, ann_keys

    def _get_needed_texts(self, key, pb=None):
        # if True or len(self._vf._immediate_fallback_vfs) > 0:
        if len(self._vf._immediate_fallback_vfs) > 0:
            # If we have fallbacks, go to the generic path
            yield from annotate.Annotator._get_needed_texts(self, key, pb=pb)
            return
        while True:
            try:
                records, ann_keys = self._get_build_graph(key)
                for idx, (sub_key, text, num_lines) in enumerate(
                    self._extract_texts(records)
                ):
                    if pb is not None:
                        pb.update(gettext("annotating"), idx, len(records))
                    yield sub_key, text, num_lines
                for sub_key in ann_keys:
                    text = self._text_cache[sub_key]
                    num_lines = len(text)  # bad assumption
                    yield sub_key, text, num_lines
                return
            except pack_repo.RetryWithNewPacks as e:
                self._vf._access.reload_or_raise(e)
                # The cached build_details are no longer valid
                self._all_build_details.clear()

    def _cache_delta_blocks(self, key, compression_parent, delta, lines):
        parent_lines = self._text_cache[compression_parent]
        blocks = list(KnitContent.get_line_delta_blocks(delta, parent_lines, lines))
        self._matching_blocks[(key, compression_parent)] = blocks

    def _expand_record(
        self, key, parent_keys, compression_parent, record, record_details
    ):
        delta = None
        if compression_parent:
            if compression_parent not in self._content_objects:
                # Waiting for the parent
                self._pending_deltas.setdefault(compression_parent, []).append(
                    (key, parent_keys, record, record_details)
                )
                return None
            # We have the basis parent, so expand the delta
            num = self._num_compression_children[compression_parent]
            num -= 1
            if num == 0:
                base_content = self._content_objects.pop(compression_parent)
                self._num_compression_children.pop(compression_parent)
            else:
                self._num_compression_children[compression_parent] = num
                base_content = self._content_objects[compression_parent]
            # It is tempting to want to copy_base_content=False for the last
            # child object. However, whenever noeol=False,
            # self._text_cache[parent_key] is content._lines. So mutating it
            # gives very bad results.
            # The alternative is to copy the lines into text cache, but then we
            # are copying anyway, so just do it here.
            content, delta = self._vf._factory.parse_record(
                key, record, record_details, base_content, copy_base_content=True
            )
        else:
            # Fulltext record
            content, _ = self._vf._factory.parse_record(
                key, record, record_details, None
            )
        if self._num_compression_children.get(key, 0) > 0:
            self._content_objects[key] = content
        lines = content.text()
        self._text_cache[key] = lines
        if delta is not None:
            self._cache_delta_blocks(key, compression_parent, delta, lines)
        return lines

    def _get_parent_annotations_and_matches(self, key, text, parent_key):
        """Get the list of annotations for the parent, and the matching lines.

        :param text: The opaque value given by _get_needed_texts
        :param parent_key: The key for the parent text
        :return: (parent_annotations, matching_blocks)
            parent_annotations is a list as long as the number of lines in
                parent
            matching_blocks is a list of (parent_idx, text_idx, len) tuples
                indicating which lines match between the two texts
        """
        block_key = (key, parent_key)
        if block_key in self._matching_blocks:
            blocks = self._matching_blocks.pop(block_key)
            parent_annotations = self._annotations_cache[parent_key]
            return parent_annotations, blocks
        return annotate.Annotator._get_parent_annotations_and_matches(
            self, key, text, parent_key
        )

    def _process_pending(self, key):
        """The content for 'key' was just processed.

        Determine if there is any more pending work to be processed.
        """
        to_return = []
        if key in self._pending_deltas:
            compression_parent = key
            children = self._pending_deltas.pop(key)
            for child_key, parent_keys, record, record_details in children:
                self._expand_record(
                    child_key, parent_keys, compression_parent, record, record_details
                )
                if self._check_ready_for_annotations(child_key, parent_keys):
                    to_return.append(child_key)
        # Also check any children that are waiting for this parent to be
        # annotation ready
        if key in self._pending_annotation:
            children = self._pending_annotation.pop(key)
            to_return.extend(
                [
                    c
                    for c, p_keys in children
                    if self._check_ready_for_annotations(c, p_keys)
                ]
            )
        return to_return

    def _check_ready_for_annotations(self, key, parent_keys):
        """Return true if this text is ready to be yielded.

        Otherwise, this will return False, and queue the text into
        self._pending_annotation
        """
        for parent_key in parent_keys:
            if parent_key not in self._annotations_cache:
                # still waiting on at least one parent text, so queue it up
                # Note that if there are multiple parents, we need to wait
                # for all of them.
                self._pending_annotation.setdefault(parent_key, []).append(
                    (key, parent_keys)
                )
                return False
        return True

    def _extract_texts(self, records):
        """Extract the various texts needed based on records."""
        # We iterate in the order read, rather than a strict order requested
        # However, process what we can, and put off to the side things that
        # still need parents, cleaning them up when those parents are
        # processed.
        # Basic data flow:
        #   1) As 'records' are read, see if we can expand these records into
        #      Content objects (and thus lines)
        #   2) If a given line-delta is waiting on its compression parent, it
        #      gets queued up into self._pending_deltas, otherwise we expand
        #      it, and put it into self._text_cache and self._content_objects
        #   3) If we expanded the text, we will then check to see if all
        #      parents have also been processed. If so, this text gets yielded,
        #      else this record gets set aside into pending_annotation
        #   4) Further, if we expanded the text in (2), we will then check to
        #      see if there are any children in self._pending_deltas waiting to
        #      also be processed. If so, we go back to (2) for those
        #   5) Further again, if we yielded the text, we can then check if that
        #      'unlocks' any of the texts in pending_annotations, which should
        #      then get yielded as well
        # Note that both steps 4 and 5 are 'recursive' in that unlocking one
        # compression child could unlock yet another, and yielding a fulltext
        # will also 'unlock' the children that are waiting on that annotation.
        # (Though also, unlocking 1 parent's fulltext, does not unlock a child
        # if other parents are also waiting.)
        # We want to yield content before expanding child content objects, so
        # that we know when we can re-use the content lines, and the annotation
        # code can know when it can stop caching fulltexts, as well.

        # Children that are missing their compression parent
        for key, record, _digest in self._vf._read_records_iter(records):
            # ghosts?
            details = self._all_build_details[key]
            (_, compression_parent, parent_keys, record_details) = details
            lines = self._expand_record(
                key, parent_keys, compression_parent, record, record_details
            )
            if lines is None:
                # Pending delta should be queued up
                continue
            # At this point, we may be able to yield this content, if all
            # parents are also finished
            yield_this_text = self._check_ready_for_annotations(key, parent_keys)
            if yield_this_text:
                # All parents present
                yield key, lines, len(lines)
            to_process = self._process_pending(key)
            while to_process:
                this_process = to_process
                to_process = []
                for key in this_process:
                    lines = self._text_cache[key]
                    yield key, lines, len(lines)
                    to_process.extend(self._process_pending(key))


try:
    from ._knit_load_data_pyx import _load_data_c as _load_data
except ImportError as e:
    osutils.failed_to_load_extension(e)
    from ._knit_load_data_py import _load_data_py as _load_data
