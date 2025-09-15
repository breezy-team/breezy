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

"""Tests for Knit data structure."""

import gzip
import sys
from io import BytesIO

from patiencediff import PatienceSequenceMatcher

from ... import errors, osutils
from ... import transport as _mod_transport
from ...bzr import multiparent
from ...tests import (
    TestCase,
    TestCaseWithMemoryTransport,
    TestCaseWithTransport,
    TestNotApplicable,
    features,
)
from .. import knit, knitpack_repo, pack, pack_repo
from ..index import *  # noqa: F403
from ..knit import (
    AnnotatedKnitContent,
    KnitContent,
    KnitCorrupt,
    KnitDataStreamIncompatible,
    KnitDataStreamUnknown,
    KnitHeaderError,
    KnitIndexUnknownMethod,
    KnitVersionedFiles,
    PlainKnitContent,
    _KndxIndex,
    _KnitGraphIndex,
    _KnitKeyAccess,
    _VFContentMapGenerator,
    make_file_factory,
)
from ..versionedfile import (
    AbsentContentFactory,
    ConstantMapper,
    RecordingVersionedFilesDecorator,
    network_bytes_to_kind_and_offset,
)

compiled_knit_feature = features.ModuleAvailableFeature(
    "breezy.bzr._knit_load_data_pyx"
)


class ErrorTests(TestCase):
    def test_knit_data_stream_incompatible(self):
        error = KnitDataStreamIncompatible("stream format", "target format")
        self.assertEqual(
            "Cannot insert knit data stream of format "
            '"stream format" into knit of format '
            '"target format".',
            str(error),
        )

    def test_knit_data_stream_unknown(self):
        error = KnitDataStreamUnknown("stream format")
        self.assertEqual(
            'Cannot parse knit data stream of format "stream format".', str(error)
        )

    def test_knit_header_error(self):
        error = KnitHeaderError("line foo\n", "path/to/file")
        self.assertEqual(
            "Knit header error: 'line foo\\n' unexpected for file \"path/to/file\".",
            str(error),
        )

    def test_knit_index_unknown_method(self):
        error = KnitIndexUnknownMethod("http://host/foo.kndx", ["bad", "no-eol"])
        self.assertEqual(
            "Knit index http://host/foo.kndx does not have a"
            " known method in options: ['bad', 'no-eol']",
            str(error),
        )


class KnitContentTestsMixin:
    def test_constructor(self):
        self._make_content([])

    def test_text(self):
        content = self._make_content([])
        self.assertEqual(content.text(), [])

        content = self._make_content([(b"origin1", b"text1"), (b"origin2", b"text2")])
        self.assertEqual(content.text(), [b"text1", b"text2"])

    def test_copy(self):
        content = self._make_content([(b"origin1", b"text1"), (b"origin2", b"text2")])
        copy = content.copy()
        self.assertIsInstance(copy, content.__class__)
        self.assertEqual(copy.annotate(), content.annotate())

    def assertDerivedBlocksEqual(self, source, target, noeol=False):
        """Assert that the derived matching blocks match real output."""
        source_lines = source.splitlines(True)
        target_lines = target.splitlines(True)

        def nl(line):
            if noeol and not line.endswith("\n"):
                return line + "\n"
            else:
                return line

        source_content = self._make_content([(None, nl(l)) for l in source_lines])
        target_content = self._make_content([(None, nl(l)) for l in target_lines])
        line_delta = source_content.line_delta(target_content)
        delta_blocks = list(
            KnitContent.get_line_delta_blocks(line_delta, source_lines, target_lines)
        )
        matcher = PatienceSequenceMatcher(None, source_lines, target_lines)
        matcher_blocks = list(matcher.get_matching_blocks())
        self.assertEqual(matcher_blocks, delta_blocks)

    def test_get_line_delta_blocks(self):
        self.assertDerivedBlocksEqual("a\nb\nc\n", "q\nc\n")
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1)
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1A)
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1B)
        self.assertDerivedBlocksEqual(TEXT_1B, TEXT_1A)
        self.assertDerivedBlocksEqual(TEXT_1A, TEXT_1B)
        self.assertDerivedBlocksEqual(TEXT_1A, "")
        self.assertDerivedBlocksEqual("", TEXT_1A)
        self.assertDerivedBlocksEqual("", "")
        self.assertDerivedBlocksEqual("a\nb\nc", "a\nb\nc\nd")

    def test_get_line_delta_blocks_noeol(self):
        """Handle historical knit deltas safely.

        Some existing knit deltas don't consider the last line to differ
        when the only difference whether it has a final newline.

        New knit deltas appear to always consider the last line to differ
        in this case.
        """
        self.assertDerivedBlocksEqual("a\nb\nc", "a\nb\nc\nd\n", noeol=True)
        self.assertDerivedBlocksEqual("a\nb\nc\nd\n", "a\nb\nc", noeol=True)
        self.assertDerivedBlocksEqual("a\nb\nc\n", "a\nb\nc", noeol=True)
        self.assertDerivedBlocksEqual("a\nb\nc", "a\nb\nc\n", noeol=True)


TEXT_1 = """\
Banana cup cakes:

- bananas
- eggs
- broken tea cups
"""

TEXT_1A = """\
Banana cup cake recipe
(serves 6)

- bananas
- eggs
- broken tea cups
- self-raising flour
"""

TEXT_1B = """\
Banana cup cake recipe

- bananas (do not use plantains!!!)
- broken tea cups
- flour
"""

delta_1_1a = """\
0,1,2
Banana cup cake recipe
(serves 6)
5,5,1
- self-raising flour
"""

TEXT_2 = """\
Boeuf bourguignon

- beef
- red wine
- small onions
- carrot
- mushrooms
"""


class TestPlainKnitContent(TestCase, KnitContentTestsMixin):
    def _make_content(self, lines):
        annotated_content = AnnotatedKnitContent(lines)
        return PlainKnitContent(annotated_content.text(), "bogus")

    def test_annotate(self):
        content = self._make_content([])
        self.assertEqual(content.annotate(), [])

        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.annotate(), [("bogus", "text1"), ("bogus", "text2")])

    def test_line_delta(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        self.assertEqual(content1.line_delta(content2), [(1, 2, 2, ["a", "c"])])

    def test_line_delta_iter(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        it = content1.line_delta_iter(content2)
        self.assertEqual(next(it), (1, 2, 2, ["a", "c"]))
        self.assertRaises(StopIteration, next, it)


class TestAnnotatedKnitContent(TestCase, KnitContentTestsMixin):
    def _make_content(self, lines):
        return AnnotatedKnitContent(lines)

    def test_annotate(self):
        content = self._make_content([])
        self.assertEqual(content.annotate(), [])

        content = self._make_content([(b"origin1", b"text1"), (b"origin2", b"text2")])
        self.assertEqual(
            content.annotate(), [(b"origin1", b"text1"), (b"origin2", b"text2")]
        )

    def test_line_delta(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        self.assertEqual(
            content1.line_delta(content2), [(1, 2, 2, [("", "a"), ("", "c")])]
        )

    def test_line_delta_iter(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        it = content1.line_delta_iter(content2)
        self.assertEqual(next(it), (1, 2, 2, [("", "a"), ("", "c")]))
        self.assertRaises(StopIteration, next, it)


class MockTransport:
    def __init__(self, file_lines=None):
        self.file_lines = file_lines
        self.calls = []
        # We have no base directory for the MockTransport
        self.base = ""

    def get(self, filename):
        if self.file_lines is None:
            raise _mod_transport.NoSuchFile(filename)
        else:
            return BytesIO(b"\n".join(self.file_lines))

    def readv(self, relpath, offsets):
        fp = self.get(relpath)
        for offset, size in offsets:
            fp.seek(offset)
            yield offset, fp.read(size)

    def __getattr__(self, name):
        def queue_call(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return queue_call


class MockReadvFailingTransport(MockTransport):
    """Fail in the middle of a readv() result.

    This Transport will successfully yield the first two requested hunks, but
    raise NoSuchFile for the rest.
    """

    def readv(self, relpath, offsets):
        for count, result in enumerate(MockTransport.readv(self, relpath, offsets), 1):
            # we use 2 because the first offset is the pack header, the second
            # is the first actual content requset
            if count > 2:
                raise _mod_transport.NoSuchFile(relpath)
            yield result


class KnitRecordAccessTestsMixin:
    """Tests for getting and putting knit records."""

    def test_add_raw_records(self):
        """add_raw_records adds records retrievable later."""
        access = self.get_access()
        memos = access.add_raw_records([(b"key", 10)], [b"1234567890"])
        self.assertEqual([b"1234567890"], list(access.get_raw_records(memos)))

    def test_add_raw_record(self):
        """add_raw_record adds records retrievable later."""
        access = self.get_access()
        memos = access.add_raw_record(b"key", 10, [b"1234567890"])
        self.assertEqual([b"1234567890"], list(access.get_raw_records([memos])))

    def test_add_several_raw_records(self):
        """add_raw_records with many records and read some back."""
        access = self.get_access()
        memos = access.add_raw_records(
            [(b"key", 10), (b"key2", 2), (b"key3", 5)], [b"12345678901234567"]
        )
        self.assertEqual(
            [b"1234567890", b"12", b"34567"], list(access.get_raw_records(memos))
        )
        self.assertEqual([b"1234567890"], list(access.get_raw_records(memos[0:1])))
        self.assertEqual([b"12"], list(access.get_raw_records(memos[1:2])))
        self.assertEqual([b"34567"], list(access.get_raw_records(memos[2:3])))
        self.assertEqual(
            [b"1234567890", b"34567"],
            list(access.get_raw_records(memos[0:1] + memos[2:3])),
        )


class TestKnitKnitAccess(TestCaseWithMemoryTransport, KnitRecordAccessTestsMixin):
    """Tests for the .kndx implementation."""

    def get_access(self):
        """Get a .knit style access instance."""
        mapper = ConstantMapper("foo")
        access = _KnitKeyAccess(self.get_transport(), mapper)
        return access


class _TestException(Exception):
    """Just an exception for local tests to use."""


class TestPackKnitAccess(TestCaseWithMemoryTransport, KnitRecordAccessTestsMixin):
    """Tests for the pack based access."""

    def get_access(self):
        return self._get_access()[0]

    def _get_access(self, packname="packfile", index="FOO"):
        transport = self.get_transport()

        def write_data(bytes):
            transport.append_bytes(packname, bytes)

        writer = pack.ContainerWriter(write_data)
        writer.begin()
        access = pack_repo._DirectPackAccess({})
        access.set_writer(writer, index, (transport, packname))
        return access, writer

    def make_pack_file(self):
        """Create a pack file with 2 records."""
        access, writer = self._get_access(packname="packname", index="foo")
        memos = []
        memos.extend(access.add_raw_records([(b"key1", 10)], [b"1234567890"]))
        memos.extend(access.add_raw_records([(b"key2", 5)], [b"12345"]))
        writer.end()
        return memos

    def test_pack_collection_pack_retries(self):
        """An explicit pack of a pack collection succeeds even when a
        concurrent pack happens.
        """
        builder = self.make_branch_builder(".")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", b"content\nrev 1\n")),
            ],
            revision_id=b"rev-1",
        )
        builder.build_snapshot(
            [b"rev-1"],
            [
                ("modify", ("file", b"content\nrev 2\n")),
            ],
            revision_id=b"rev-2",
        )
        builder.build_snapshot(
            [b"rev-2"],
            [
                ("modify", ("file", b"content\nrev 3\n")),
            ],
            revision_id=b"rev-3",
        )
        self.addCleanup(builder.finish_series)
        b = builder.get_branch()
        self.addCleanup(b.lock_write().unlock)
        repo = b.repository
        collection = repo._pack_collection
        # Concurrently repack the repo.
        reopened_repo = repo.controldir.open_repository()
        reopened_repo.pack()
        # Pack the new pack.
        collection.pack()

    def make_vf_for_retrying(self):
        """Create 3 packs and a reload function.

        Originally, 2 pack files will have the data, but one will be missing.
        And then the third will be used in place of the first two if reload()
        is called.

        :return: (versioned_file, reload_counter)
            versioned_file  a KnitVersionedFiles using the packs for access
        """
        builder = self.make_branch_builder(".", format="1.9")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", b"content\nrev 1\n")),
            ],
            revision_id=b"rev-1",
        )
        builder.build_snapshot(
            [b"rev-1"],
            [
                ("modify", ("file", b"content\nrev 2\n")),
            ],
            revision_id=b"rev-2",
        )
        builder.build_snapshot(
            [b"rev-2"],
            [
                ("modify", ("file", b"content\nrev 3\n")),
            ],
            revision_id=b"rev-3",
        )
        builder.finish_series()
        b = builder.get_branch()
        b.lock_write()
        self.addCleanup(b.unlock)
        # Pack these three revisions into another pack file, but don't remove
        # the originals
        repo = b.repository
        collection = repo._pack_collection
        collection.ensure_loaded()
        orig_packs = collection.packs
        packer = knitpack_repo.KnitPacker(collection, orig_packs, ".testpack")
        new_pack = packer.pack()
        # forget about the new pack
        collection.reset()
        repo.refresh_data()
        vf = repo.revisions
        # Set up a reload() function that switches to using the new pack file
        new_index = new_pack.revision_index
        access_tuple = new_pack.access_tuple()
        reload_counter = [0, 0, 0]

        def reload():
            reload_counter[0] += 1
            if reload_counter[1] > 0:
                # We already reloaded, nothing more to do
                reload_counter[2] += 1
                return False
            reload_counter[1] += 1
            vf._index._graph_index._indices[:] = [new_index]
            vf._access._indices.clear()
            vf._access._indices[new_index] = access_tuple
            return True

        # Delete one of the pack files so the data will need to be reloaded. We
        # will delete the file with 'rev-2' in it
        trans, name = orig_packs[1].access_tuple()
        trans.delete(name)
        # We don't have the index trigger reloading because we want to test
        # that we reload when the .pack disappears
        vf._access._reload_func = reload
        return vf, reload_counter

    def make_reload_func(self, return_val=True):
        reload_called = [0]

        def reload():
            reload_called[0] += 1
            return return_val

        return reload_called, reload

    def make_retry_exception(self):
        # We raise a real exception so that sys.exc_info() is properly
        # populated
        try:
            raise _TestException("foobar")
        except _TestException:
            retry_exc = pack_repo.RetryWithNewPacks(
                None, reload_occurred=False, exc_info=sys.exc_info()
            )
        # GZ 2010-08-10: Cycle with exc_info affects 3 tests
        return retry_exc

    def test_read_from_several_packs(self):
        access, writer = self._get_access()
        memos = []
        memos.extend(access.add_raw_records([(b"key", 10)], [b"1234567890"]))
        writer.end()
        access, writer = self._get_access("pack2", "FOOBAR")
        memos.extend(access.add_raw_records([(b"key", 5)], [b"12345"]))
        writer.end()
        access, writer = self._get_access("pack3", "BAZ")
        memos.extend(access.add_raw_records([(b"key", 5)], [b"alpha"]))
        writer.end()
        transport = self.get_transport()
        access = pack_repo._DirectPackAccess(
            {
                "FOO": (transport, "packfile"),
                "FOOBAR": (transport, "pack2"),
                "BAZ": (transport, "pack3"),
            }
        )
        self.assertEqual(
            [b"1234567890", b"12345", b"alpha"], list(access.get_raw_records(memos))
        )
        self.assertEqual([b"1234567890"], list(access.get_raw_records(memos[0:1])))
        self.assertEqual([b"12345"], list(access.get_raw_records(memos[1:2])))
        self.assertEqual([b"alpha"], list(access.get_raw_records(memos[2:3])))
        self.assertEqual(
            [b"1234567890", b"alpha"],
            list(access.get_raw_records(memos[0:1] + memos[2:3])),
        )

    def test_set_writer(self):
        """The writer should be settable post construction."""
        access = pack_repo._DirectPackAccess({})
        transport = self.get_transport()
        packname = "packfile"
        index = "foo"

        def write_data(bytes):
            transport.append_bytes(packname, bytes)

        writer = pack.ContainerWriter(write_data)
        writer.begin()
        access.set_writer(writer, index, (transport, packname))
        memos = access.add_raw_records([(b"key", 10)], [b"1234567890"])
        writer.end()
        self.assertEqual([b"1234567890"], list(access.get_raw_records(memos)))

    def test_missing_index_raises_retry(self):
        memos = self.make_pack_file()
        transport = self.get_transport()
        _reload_called, reload_func = self.make_reload_func()
        # Note that the index key has changed from 'foo' to 'bar'
        access = pack_repo._DirectPackAccess(
            {"bar": (transport, "packname")}, reload_func=reload_func
        )
        e = self.assertListRaises(
            pack_repo.RetryWithNewPacks, access.get_raw_records, memos
        )
        # Because a key was passed in which does not match our index list, we
        # assume that the listing was already reloaded
        self.assertTrue(e.reload_occurred)
        self.assertIsInstance(e.exc_info, tuple)
        self.assertIs(e.exc_info[0], KeyError)
        self.assertIsInstance(e.exc_info[1], KeyError)

    def test_missing_index_raises_key_error_with_no_reload(self):
        memos = self.make_pack_file()
        transport = self.get_transport()
        # Note that the index key has changed from 'foo' to 'bar'
        access = pack_repo._DirectPackAccess({"bar": (transport, "packname")})
        self.assertListRaises(KeyError, access.get_raw_records, memos)

    def test_missing_file_raises_retry(self):
        memos = self.make_pack_file()
        transport = self.get_transport()
        _reload_called, reload_func = self.make_reload_func()
        # Note that the 'filename' has been changed to 'different-packname'
        access = pack_repo._DirectPackAccess(
            {"foo": (transport, "different-packname")}, reload_func=reload_func
        )
        e = self.assertListRaises(
            pack_repo.RetryWithNewPacks, access.get_raw_records, memos
        )
        # The file has gone missing, so we assume we need to reload
        self.assertFalse(e.reload_occurred)
        self.assertIsInstance(e.exc_info, tuple)
        self.assertIs(e.exc_info[0], _mod_transport.NoSuchFile)
        self.assertIsInstance(e.exc_info[1], _mod_transport.NoSuchFile)
        self.assertEqual("different-packname", e.exc_info[1].path)

    def test_missing_file_raises_no_such_file_with_no_reload(self):
        memos = self.make_pack_file()
        transport = self.get_transport()
        # Note that the 'filename' has been changed to 'different-packname'
        access = pack_repo._DirectPackAccess({"foo": (transport, "different-packname")})
        self.assertListRaises(_mod_transport.NoSuchFile, access.get_raw_records, memos)

    def test_failing_readv_raises_retry(self):
        memos = self.make_pack_file()
        transport = self.get_transport()
        failing_transport = MockReadvFailingTransport([transport.get_bytes("packname")])
        _reload_called, reload_func = self.make_reload_func()
        access = pack_repo._DirectPackAccess(
            {"foo": (failing_transport, "packname")}, reload_func=reload_func
        )
        # Asking for a single record will not trigger the Mock failure
        self.assertEqual([b"1234567890"], list(access.get_raw_records(memos[:1])))
        self.assertEqual([b"12345"], list(access.get_raw_records(memos[1:2])))
        # A multiple offset readv() will fail mid-way through
        e = self.assertListRaises(
            pack_repo.RetryWithNewPacks, access.get_raw_records, memos
        )
        # The file has gone missing, so we assume we need to reload
        self.assertFalse(e.reload_occurred)
        self.assertIsInstance(e.exc_info, tuple)
        self.assertIs(e.exc_info[0], _mod_transport.NoSuchFile)
        self.assertIsInstance(e.exc_info[1], _mod_transport.NoSuchFile)
        self.assertEqual("packname", e.exc_info[1].path)

    def test_failing_readv_raises_no_such_file_with_no_reload(self):
        memos = self.make_pack_file()
        transport = self.get_transport()
        failing_transport = MockReadvFailingTransport([transport.get_bytes("packname")])
        _reload_called, _reload_func = self.make_reload_func()
        access = pack_repo._DirectPackAccess({"foo": (failing_transport, "packname")})
        # Asking for a single record will not trigger the Mock failure
        self.assertEqual([b"1234567890"], list(access.get_raw_records(memos[:1])))
        self.assertEqual([b"12345"], list(access.get_raw_records(memos[1:2])))
        # A multiple offset readv() will fail mid-way through
        self.assertListRaises(_mod_transport.NoSuchFile, access.get_raw_records, memos)

    def test_reload_or_raise_no_reload(self):
        access = pack_repo._DirectPackAccess({}, reload_func=None)
        retry_exc = self.make_retry_exception()
        # Without a reload_func, we will just re-raise the original exception
        self.assertRaises(_TestException, access.reload_or_raise, retry_exc)

    def test_reload_or_raise_reload_changed(self):
        reload_called, reload_func = self.make_reload_func(return_val=True)
        access = pack_repo._DirectPackAccess({}, reload_func=reload_func)
        retry_exc = self.make_retry_exception()
        access.reload_or_raise(retry_exc)
        self.assertEqual([1], reload_called)
        retry_exc.reload_occurred = True
        access.reload_or_raise(retry_exc)
        self.assertEqual([2], reload_called)

    def test_reload_or_raise_reload_no_change(self):
        reload_called, reload_func = self.make_reload_func(return_val=False)
        access = pack_repo._DirectPackAccess({}, reload_func=reload_func)
        retry_exc = self.make_retry_exception()
        # If reload_occurred is False, then we consider it an error to have
        # reload_func() return False (no changes).
        self.assertRaises(_TestException, access.reload_or_raise, retry_exc)
        self.assertEqual([1], reload_called)
        retry_exc.reload_occurred = True
        # If reload_occurred is True, then we assume nothing changed because
        # it had changed earlier, but didn't change again
        access.reload_or_raise(retry_exc)
        self.assertEqual([2], reload_called)

    def test_annotate_retries(self):
        vf, reload_counter = self.make_vf_for_retrying()
        # It is a little bit bogus to annotate the Revision VF, but it works,
        # as we have ancestry stored there
        key = (b"rev-3",)
        reload_lines = vf.annotate(key)
        self.assertEqual([1, 1, 0], reload_counter)
        plain_lines = vf.annotate(key)
        self.assertEqual([1, 1, 0], reload_counter)  # No extra reloading
        if reload_lines != plain_lines:
            self.fail("Annotation was not identical with reloading.")
        # Now delete the packs-in-use, which should trigger another reload, but
        # this time we just raise an exception because we can't recover
        for trans, name in vf._access._indices.values():
            trans.delete(name)
        self.assertRaises(_mod_transport.NoSuchFile, vf.annotate, key)
        self.assertEqual([2, 1, 1], reload_counter)

    def test__get_record_map_retries(self):
        vf, reload_counter = self.make_vf_for_retrying()
        keys = [(b"rev-1",), (b"rev-2",), (b"rev-3",)]
        records = vf._get_record_map(keys)
        self.assertEqual(keys, sorted(records.keys()))
        self.assertEqual([1, 1, 0], reload_counter)
        # Now delete the packs-in-use, which should trigger another reload, but
        # this time we just raise an exception because we can't recover
        for trans, name in vf._access._indices.values():
            trans.delete(name)
        self.assertRaises(_mod_transport.NoSuchFile, vf._get_record_map, keys)
        self.assertEqual([2, 1, 1], reload_counter)

    def test_get_record_stream_retries(self):
        vf, reload_counter = self.make_vf_for_retrying()
        keys = [(b"rev-1",), (b"rev-2",), (b"rev-3",)]
        record_stream = vf.get_record_stream(keys, "topological", False)
        record = next(record_stream)
        self.assertEqual((b"rev-1",), record.key)
        self.assertEqual([0, 0, 0], reload_counter)
        record = next(record_stream)
        self.assertEqual((b"rev-2",), record.key)
        self.assertEqual([1, 1, 0], reload_counter)
        record = next(record_stream)
        self.assertEqual((b"rev-3",), record.key)
        self.assertEqual([1, 1, 0], reload_counter)
        # Now delete all pack files, and see that we raise the right error
        for trans, name in vf._access._indices.values():
            trans.delete(name)
        self.assertListRaises(
            _mod_transport.NoSuchFile, vf.get_record_stream, keys, "topological", False
        )

    def test_iter_lines_added_or_present_in_keys_retries(self):
        vf, reload_counter = self.make_vf_for_retrying()
        keys = [(b"rev-1",), (b"rev-2",), (b"rev-3",)]
        # Unfortunately, iter_lines_added_or_present_in_keys iterates the
        # result in random order (determined by the iteration order from a
        # set()), so we don't have any solid way to trigger whether data is
        # read before or after. However we tried to delete the middle node to
        # exercise the code well.
        # What we care about is that all lines are always yielded, but not
        # duplicated
        reload_lines = sorted(vf.iter_lines_added_or_present_in_keys(keys))
        self.assertEqual([1, 1, 0], reload_counter)
        # Now do it again, to make sure the result is equivalent
        plain_lines = sorted(vf.iter_lines_added_or_present_in_keys(keys))
        self.assertEqual([1, 1, 0], reload_counter)  # No extra reloading
        self.assertEqual(plain_lines, reload_lines)
        self.assertEqual(21, len(plain_lines))
        # Now delete all pack files, and see that we raise the right error
        for trans, name in vf._access._indices.values():
            trans.delete(name)
        self.assertListRaises(
            _mod_transport.NoSuchFile, vf.iter_lines_added_or_present_in_keys, keys
        )
        self.assertEqual([2, 1, 1], reload_counter)

    def test_get_record_stream_yields_disk_sorted_order(self):
        # if we get 'unordered' pick a semi-optimal order for reading. The
        # order should be grouped by pack file, and then by position in file
        repo = self.make_repository("test", format="pack-0.92")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        vf = repo.texts
        vf.add_lines((b"f-id", b"rev-5"), [(b"f-id", b"rev-4")], [b"lines\n"])
        vf.add_lines((b"f-id", b"rev-1"), [], [b"lines\n"])
        vf.add_lines((b"f-id", b"rev-2"), [(b"f-id", b"rev-1")], [b"lines\n"])
        repo.commit_write_group()
        # We inserted them as rev-5, rev-1, rev-2, we should get them back in
        # the same order
        stream = vf.get_record_stream(
            [(b"f-id", b"rev-1"), (b"f-id", b"rev-5"), (b"f-id", b"rev-2")],
            "unordered",
            False,
        )
        keys = [r.key for r in stream]
        self.assertEqual(
            [(b"f-id", b"rev-5"), (b"f-id", b"rev-1"), (b"f-id", b"rev-2")], keys
        )
        repo.start_write_group()
        vf.add_lines((b"f-id", b"rev-4"), [(b"f-id", b"rev-3")], [b"lines\n"])
        vf.add_lines((b"f-id", b"rev-3"), [(b"f-id", b"rev-2")], [b"lines\n"])
        vf.add_lines((b"f-id", b"rev-6"), [(b"f-id", b"rev-5")], [b"lines\n"])
        repo.commit_write_group()
        # Request in random order, to make sure the output order isn't based on
        # the request
        request_keys = {(b"f-id", b"rev-%d" % i) for i in range(1, 7)}
        stream = vf.get_record_stream(request_keys, "unordered", False)
        keys = [r.key for r in stream]
        # We want to get the keys back in disk order, but it doesn't matter
        # which pack we read from first. So this can come back in 2 orders
        alt1 = [(b"f-id", b"rev-%d" % i) for i in [4, 3, 6, 5, 1, 2]]
        alt2 = [(b"f-id", b"rev-%d" % i) for i in [5, 1, 2, 4, 3, 6]]
        if keys != alt1 and keys != alt2:
            self.fail(
                "Returned key order did not match either expected order."
                f" expected {alt1} or {alt2}, not {keys}"
            )


class LowLevelKnitDataTests(TestCase):
    def create_gz_content(self, text):
        sio = BytesIO()
        with gzip.GzipFile(mode="wb", fileobj=sio) as gz_file:
            gz_file.write(text)
        return sio.getvalue()

    def make_multiple_records(self):
        """Create the content for multiple records."""
        sha1sum = osutils.sha_string(b"foo\nbar\n")
        total_txt = []
        gz_txt = self.create_gz_content(
            b"version rev-id-1 2 %s\nfoo\nbar\nend rev-id-1\n" % (sha1sum,)
        )
        record_1 = (0, len(gz_txt), sha1sum)
        total_txt.append(gz_txt)
        sha1sum = osutils.sha_string(b"baz\n")
        gz_txt = self.create_gz_content(
            b"version rev-id-2 1 %s\nbaz\nend rev-id-2\n" % (sha1sum,)
        )
        record_2 = (record_1[1], len(gz_txt), sha1sum)
        total_txt.append(gz_txt)
        return total_txt, record_1, record_2

    def test_valid_knit_data(self):
        sha1sum = osutils.sha_string(b"foo\nbar\n")
        gz_txt = self.create_gz_content(
            b"version rev-id-1 2 %s\nfoo\nbar\nend rev-id-1\n" % (sha1sum,)
        )
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper("filename"))
        knit = KnitVersionedFiles(None, access)
        records = [((b"rev-id-1",), ((b"rev-id-1",), 0, len(gz_txt)))]

        contents = list(knit._read_records_iter(records))
        self.assertEqual(
            [
                (
                    (b"rev-id-1",),
                    [b"foo\n", b"bar\n"],
                    b"4e48e2c9a3d2ca8a708cb0cc545700544efb5021",
                )
            ],
            contents,
        )

        raw_contents = list(knit._read_records_iter_raw(records))
        self.assertEqual([((b"rev-id-1",), gz_txt, sha1sum)], raw_contents)

    def test_multiple_records_valid(self):
        total_txt, record_1, record_2 = self.make_multiple_records()
        transport = MockTransport([b"".join(total_txt)])
        access = _KnitKeyAccess(transport, ConstantMapper("filename"))
        knit = KnitVersionedFiles(None, access)
        records = [
            ((b"rev-id-1",), ((b"rev-id-1",), record_1[0], record_1[1])),
            ((b"rev-id-2",), ((b"rev-id-2",), record_2[0], record_2[1])),
        ]

        contents = list(knit._read_records_iter(records))
        self.assertEqual(
            [
                ((b"rev-id-1",), [b"foo\n", b"bar\n"], record_1[2]),
                ((b"rev-id-2",), [b"baz\n"], record_2[2]),
            ],
            contents,
        )

        raw_contents = list(knit._read_records_iter_raw(records))
        self.assertEqual(
            [
                ((b"rev-id-1",), total_txt[0], record_1[2]),
                ((b"rev-id-2",), total_txt[1], record_2[2]),
            ],
            raw_contents,
        )

    def test_not_enough_lines(self):
        sha1sum = osutils.sha_string(b"foo\n")
        # record says 2 lines data says 1
        gz_txt = self.create_gz_content(
            b"version rev-id-1 2 %s\nfoo\nend rev-id-1\n" % (sha1sum,)
        )
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper("filename"))
        knit = KnitVersionedFiles(None, access)
        records = [((b"rev-id-1",), ((b"rev-id-1",), 0, len(gz_txt)))]
        self.assertRaises(KnitCorrupt, list, knit._read_records_iter(records))

        # read_records_iter_raw won't detect that sort of mismatch/corruption
        raw_contents = list(knit._read_records_iter_raw(records))
        self.assertEqual([((b"rev-id-1",), gz_txt, sha1sum)], raw_contents)

    def test_too_many_lines(self):
        sha1sum = osutils.sha_string(b"foo\nbar\n")
        # record says 1 lines data says 2
        gz_txt = self.create_gz_content(
            b"version rev-id-1 1 %s\nfoo\nbar\nend rev-id-1\n" % (sha1sum,)
        )
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper("filename"))
        knit = KnitVersionedFiles(None, access)
        records = [((b"rev-id-1",), ((b"rev-id-1",), 0, len(gz_txt)))]
        self.assertRaises(KnitCorrupt, list, knit._read_records_iter(records))

        # read_records_iter_raw won't detect that sort of mismatch/corruption
        raw_contents = list(knit._read_records_iter_raw(records))
        self.assertEqual([((b"rev-id-1",), gz_txt, sha1sum)], raw_contents)

    def test_mismatched_version_id(self):
        sha1sum = osutils.sha_string(b"foo\nbar\n")
        gz_txt = self.create_gz_content(
            b"version rev-id-1 2 %s\nfoo\nbar\nend rev-id-1\n" % (sha1sum,)
        )
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper("filename"))
        knit = KnitVersionedFiles(None, access)
        # We are asking for rev-id-2, but the data is rev-id-1
        records = [((b"rev-id-2",), ((b"rev-id-2",), 0, len(gz_txt)))]
        self.assertRaises(KnitCorrupt, list, knit._read_records_iter(records))

        # read_records_iter_raw detects mismatches in the header
        self.assertRaises(KnitCorrupt, list, knit._read_records_iter_raw(records))

    def test_uncompressed_data(self):
        sha1sum = osutils.sha_string(b"foo\nbar\n")
        txt = b"version rev-id-1 2 %s\nfoo\nbar\nend rev-id-1\n" % (sha1sum,)
        transport = MockTransport([txt])
        access = _KnitKeyAccess(transport, ConstantMapper("filename"))
        knit = KnitVersionedFiles(None, access)
        records = [((b"rev-id-1",), ((b"rev-id-1",), 0, len(txt)))]

        # We don't have valid gzip data ==> corrupt
        self.assertRaises(KnitCorrupt, list, knit._read_records_iter(records))

        # read_records_iter_raw will notice the bad data
        self.assertRaises(KnitCorrupt, list, knit._read_records_iter_raw(records))

    def test_corrupted_data(self):
        sha1sum = osutils.sha_string(b"foo\nbar\n")
        gz_txt = self.create_gz_content(
            b"version rev-id-1 2 %s\nfoo\nbar\nend rev-id-1\n" % (sha1sum,)
        )
        # Change 2 bytes in the middle to \xff
        gz_txt = gz_txt[:10] + b"\xff\xff" + gz_txt[12:]
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper("filename"))
        knit = KnitVersionedFiles(None, access)
        records = [((b"rev-id-1",), ((b"rev-id-1",), 0, len(gz_txt)))]
        self.assertRaises(KnitCorrupt, list, knit._read_records_iter(records))
        # read_records_iter_raw will barf on bad gz data
        self.assertRaises(KnitCorrupt, list, knit._read_records_iter_raw(records))


class LowLevelKnitIndexTests(TestCase):
    @property
    def _load_data(self):
        from .._knit_load_data_py import _load_data_py

        return _load_data_py

    def get_knit_index(self, transport, name, mode):
        mapper = ConstantMapper(name)
        self.overrideAttr(knit, "_load_data", self._load_data)

        def allow_writes():
            return "w" in mode

        return _KndxIndex(transport, mapper, lambda: None, allow_writes, lambda: True)

    def test_create_file(self):
        transport = MockTransport()
        index = self.get_knit_index(transport, "filename", "w")
        index.keys()
        call = transport.calls.pop(0)
        # call[1][1] is a BytesIO - we can't test it by simple equality.
        self.assertEqual("put_file_non_atomic", call[0])
        self.assertEqual("filename.kndx", call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(_KndxIndex.HEADER, call[1][1].getvalue())
        self.assertEqual({"create_parent_dir": True}, call[2])

    def test_read_utf8_version_id(self):
        unicode_revision_id = "version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode("utf-8")
        transport = MockTransport(
            [_KndxIndex.HEADER, b"%s option 0 1 :" % (utf8_revision_id,)]
        )
        index = self.get_knit_index(transport, "filename", "r")
        # _KndxIndex is a private class, and deals in utf8 revision_ids, not
        # Unicode revision_ids.
        self.assertEqual({(utf8_revision_id,): ()}, index.get_parent_map(index.keys()))
        self.assertNotIn((unicode_revision_id,), index.keys())

    def test_read_utf8_parents(self):
        unicode_revision_id = "version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode("utf-8")
        transport = MockTransport(
            [_KndxIndex.HEADER, b"version option 0 1 .%s :" % (utf8_revision_id,)]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(
            {(b"version",): ((utf8_revision_id,),)}, index.get_parent_map(index.keys())
        )

    def test_read_ignore_corrupted_lines(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"corrupted",
                b"corrupted options 0 1 .b .c ",
                b"version options 0 1 :",
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(1, len(index.keys()))
        self.assertEqual({(b"version",)}, index.keys())

    def test_read_corrupted_header(self):
        transport = MockTransport([b"not a bzr knit index header\n"])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertRaises(KnitHeaderError, index.keys)

    def test_read_duplicate_entries(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"parent options 0 1 :",
                b"version options1 0 1 0 :",
                b"version options2 1 2 .other :",
                b"version options3 3 4 0 .other :",
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(2, len(index.keys()))
        # check that the index used is the first one written. (Specific
        # to KnitIndex style indices.
        self.assertEqual(b"1", index._dictionary_compress([(b"version",)]))
        self.assertEqual(((b"version",), 3, 4), index.get_position((b"version",)))
        self.assertEqual([b"options3"], index.get_options((b"version",)))
        self.assertEqual(
            {(b"version",): ((b"parent",), (b"other",))},
            index.get_parent_map([(b"version",)]),
        )

    def test_read_compressed_parents(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 0 1 :",
                b"b option 0 1 0 :",
                b"c option 0 1 1 0 :",
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(
            {(b"b",): ((b"a",),), (b"c",): ((b"b",), (b"a",))},
            index.get_parent_map([(b"b",), (b"c",)]),
        )

    def test_write_utf8_version_id(self):
        unicode_revision_id = "version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode("utf-8")
        transport = MockTransport([_KndxIndex.HEADER])
        index = self.get_knit_index(transport, "filename", "r")
        index.add_records(
            [((utf8_revision_id,), [b"option"], ((utf8_revision_id,), 0, 1), [])]
        )
        call = transport.calls.pop(0)
        # call[1][1] is a BytesIO - we can't test it by simple equality.
        self.assertEqual("put_file_non_atomic", call[0])
        self.assertEqual("filename.kndx", call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(
            _KndxIndex.HEADER + b"\n%s option 0 1  :" % (utf8_revision_id,),
            call[1][1].getvalue(),
        )
        self.assertEqual({"create_parent_dir": True}, call[2])

    def test_write_utf8_parents(self):
        unicode_revision_id = "version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode("utf-8")
        transport = MockTransport([_KndxIndex.HEADER])
        index = self.get_knit_index(transport, "filename", "r")
        index.add_records(
            [((b"version",), [b"option"], ((b"version",), 0, 1), [(utf8_revision_id,)])]
        )
        call = transport.calls.pop(0)
        # call[1][1] is a BytesIO - we can't test it by simple equality.
        self.assertEqual("put_file_non_atomic", call[0])
        self.assertEqual("filename.kndx", call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(
            _KndxIndex.HEADER + b"\nversion option 0 1 .%s :" % (utf8_revision_id,),
            call[1][1].getvalue(),
        )
        self.assertEqual({"create_parent_dir": True}, call[2])

    def test_keys(self):
        transport = MockTransport([_KndxIndex.HEADER])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual(set(), index.keys())

        index.add_records([((b"a",), [b"option"], ((b"a",), 0, 1), [])])
        self.assertEqual({(b"a",)}, index.keys())

        index.add_records([((b"a",), [b"option"], ((b"a",), 0, 1), [])])
        self.assertEqual({(b"a",)}, index.keys())

        index.add_records([((b"b",), [b"option"], ((b"b",), 0, 1), [])])
        self.assertEqual({(b"a",), (b"b",)}, index.keys())

    def add_a_b(self, index, random_id=None):
        kwargs = {}
        if random_id is not None:
            kwargs["random_id"] = random_id
        index.add_records(
            [
                ((b"a",), [b"option"], ((b"a",), 0, 1), [(b"b",)]),
                ((b"a",), [b"opt"], ((b"a",), 1, 2), [(b"c",)]),
                ((b"b",), [b"option"], ((b"b",), 2, 3), [(b"a",)]),
            ],
            **kwargs,
        )

    def assertIndexIsAB(self, index):
        self.assertEqual(
            {
                (b"a",): ((b"c",),),
                (b"b",): ((b"a",),),
            },
            index.get_parent_map(index.keys()),
        )
        self.assertEqual(((b"a",), 1, 2), index.get_position((b"a",)))
        self.assertEqual(((b"b",), 2, 3), index.get_position((b"b",)))
        self.assertEqual([b"opt"], index.get_options((b"a",)))

    def test_add_versions(self):
        transport = MockTransport([_KndxIndex.HEADER])
        index = self.get_knit_index(transport, "filename", "r")

        self.add_a_b(index)
        call = transport.calls.pop(0)
        # call[1][1] is a BytesIO - we can't test it by simple equality.
        self.assertEqual("put_file_non_atomic", call[0])
        self.assertEqual("filename.kndx", call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(
            _KndxIndex.HEADER + b"\na option 0 1 .b :"
            b"\na opt 1 2 .c :"
            b"\nb option 2 3 0 :",
            call[1][1].getvalue(),
        )
        self.assertEqual({"create_parent_dir": True}, call[2])
        self.assertIndexIsAB(index)

    def test_add_versions_random_id_is_accepted(self):
        transport = MockTransport([_KndxIndex.HEADER])
        index = self.get_knit_index(transport, "filename", "r")
        self.add_a_b(index, random_id=True)

    def test_delay_create_and_add_versions(self):
        transport = MockTransport()

        index = self.get_knit_index(transport, "filename", "w")
        # dir_mode=0777)
        self.assertEqual([], transport.calls)
        self.add_a_b(index)
        # self.assertEqual(
        # [    {"dir_mode": 0777, "create_parent_dir": True, "mode": "wb"},
        #    kwargs)
        # Two calls: one during which we load the existing index (and when its
        # missing create it), then a second where we write the contents out.
        self.assertEqual(2, len(transport.calls))
        call = transport.calls.pop(0)
        self.assertEqual("put_file_non_atomic", call[0])
        self.assertEqual("filename.kndx", call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(_KndxIndex.HEADER, call[1][1].getvalue())
        self.assertEqual({"create_parent_dir": True}, call[2])
        call = transport.calls.pop(0)
        # call[1][1] is a BytesIO - we can't test it by simple equality.
        self.assertEqual("put_file_non_atomic", call[0])
        self.assertEqual("filename.kndx", call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(
            _KndxIndex.HEADER + b"\na option 0 1 .b :"
            b"\na opt 1 2 .c :"
            b"\nb option 2 3 0 :",
            call[1][1].getvalue(),
        )
        self.assertEqual({"create_parent_dir": True}, call[2])

    def assertTotalBuildSize(self, size, keys, positions):
        self.assertEqual(size, knit._get_total_build_size(None, keys, positions))

    def test__get_total_build_size(self):
        positions = {
            (b"a",): (("fulltext", False), ((b"a",), 0, 100), None),
            (b"b",): (("line-delta", False), ((b"b",), 100, 21), (b"a",)),
            (b"c",): (("line-delta", False), ((b"c",), 121, 35), (b"b",)),
            (b"d",): (("line-delta", False), ((b"d",), 156, 12), (b"b",)),
        }
        self.assertTotalBuildSize(100, [(b"a",)], positions)
        self.assertTotalBuildSize(121, [(b"b",)], positions)
        # c needs both a & b
        self.assertTotalBuildSize(156, [(b"c",)], positions)
        # we shouldn't count 'b' twice
        self.assertTotalBuildSize(156, [(b"b",), (b"c",)], positions)
        self.assertTotalBuildSize(133, [(b"d",)], positions)
        self.assertTotalBuildSize(168, [(b"c",), (b"d",)], positions)

    def test_get_position(self):
        transport = MockTransport(
            [_KndxIndex.HEADER, b"a option 0 1 :", b"b option 1 2 :"]
        )
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual(((b"a",), 0, 1), index.get_position((b"a",)))
        self.assertEqual(((b"b",), 1, 2), index.get_position((b"b",)))

    def test_get_method(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a fulltext,unknown 0 1 :",
                b"b unknown,line-delta 1 2 :",
                b"c bad 3 4 :",
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual("fulltext", index.get_method(b"a"))
        self.assertEqual("line-delta", index.get_method(b"b"))
        self.assertRaises(knit.KnitIndexUnknownMethod, index.get_method, b"c")

    def test_get_options(self):
        transport = MockTransport(
            [_KndxIndex.HEADER, b"a opt1 0 1 :", b"b opt2,opt3 1 2 :"]
        )
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual([b"opt1"], index.get_options(b"a"))
        self.assertEqual([b"opt2", b"opt3"], index.get_options(b"b"))

    def test_get_parent_map(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 0 1 :",
                b"b option 1 2 0 .c :",
                b"c option 1 2 1 0 .e :",
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual(
            {
                (b"a",): (),
                (b"b",): ((b"a",), (b"c",)),
                (b"c",): ((b"b",), (b"a",), (b"e",)),
            },
            index.get_parent_map(index.keys()),
        )

    def test_impossible_parent(self):
        """Test we get KnitCorrupt if the parent couldn't possibly exist."""
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 0 1 :",
                b"b option 0 1 4 :",  # We don't have a 4th record
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertRaises(KnitCorrupt, index.keys)

    def test_corrupted_parent(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 0 1 :",
                b"b option 0 1 :",
                b"c option 0 1 1v :",  # Can't have a parent of '1v'
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertRaises(KnitCorrupt, index.keys)

    def test_corrupted_parent_in_list(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 0 1 :",
                b"b option 0 1 :",
                b"c option 0 1 1 v :",  # Can't have a parent of 'v'
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertRaises(KnitCorrupt, index.keys)

    def test_invalid_position(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 1v 1 :",
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertRaises(KnitCorrupt, index.keys)

    def test_invalid_size(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 1 1v :",
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertRaises(KnitCorrupt, index.keys)

    def test_scan_unvalidated_index_not_implemented(self):
        transport = MockTransport()
        index = self.get_knit_index(transport, "filename", "r")
        self.assertRaises(
            NotImplementedError, index.scan_unvalidated_index, "dummy graph_index"
        )
        self.assertRaises(NotImplementedError, index.get_missing_compression_parents)

    def test_short_line(self):
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 0 10  :",
                b"b option 10 10 0",  # This line isn't terminated, ignored
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual({(b"a",)}, index.keys())

    def test_skip_incomplete_record(self):
        # A line with bogus data should just be skipped
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 0 10  :",
                b"b option 10 10 0",  # This line isn't terminated, ignored
                b"c option 20 10 0 :",  # Properly terminated, and starts with '\n'
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual({(b"a",), (b"c",)}, index.keys())

    def test_trailing_characters(self):
        # A line with bogus data should just be skipped
        transport = MockTransport(
            [
                _KndxIndex.HEADER,
                b"a option 0 10  :",
                b"b option 10 10 0 :a",  # This line has extra trailing characters
                b"c option 20 10 0 :",  # Properly terminated, and starts with '\n'
            ]
        )
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual({(b"a",), (b"c",)}, index.keys())


class LowLevelKnitIndexTests_c(LowLevelKnitIndexTests):
    _test_needs_features = [compiled_knit_feature]

    @property
    def _load_data(self):
        from .._knit_load_data_pyx import _load_data_c

        return _load_data_c


class Test_KnitAnnotator(TestCaseWithMemoryTransport):
    def make_annotator(self):
        factory = knit.make_pack_factory(True, True, 1)
        vf = factory(self.get_transport())
        return knit._KnitAnnotator(vf)

    def test__expand_fulltext(self):
        ann = self.make_annotator()
        rev_key = (b"rev-id",)
        ann._num_compression_children[rev_key] = 1
        res = ann._expand_record(
            rev_key,
            ((b"parent-id",),),
            None,
            [b"line1\n", b"line2\n"],
            ("fulltext", True),
        )
        # The content object and text lines should be cached appropriately
        self.assertEqual([b"line1\n", b"line2"], res)
        content_obj = ann._content_objects[rev_key]
        self.assertEqual([b"line1\n", b"line2\n"], content_obj._lines)
        self.assertEqual(res, content_obj.text())
        self.assertEqual(res, ann._text_cache[rev_key])

    def test__expand_delta_comp_parent_not_available(self):
        # Parent isn't available yet, so we return nothing, but queue up this
        # node for later processing
        ann = self.make_annotator()
        rev_key = (b"rev-id",)
        parent_key = (b"parent-id",)
        record = [b"0,1,1\n", b"new-line\n"]
        details = ("line-delta", False)
        res = ann._expand_record(rev_key, (parent_key,), parent_key, record, details)
        self.assertEqual(None, res)
        self.assertIn(parent_key, ann._pending_deltas)
        pending = ann._pending_deltas[parent_key]
        self.assertEqual(1, len(pending))
        self.assertEqual((rev_key, (parent_key,), record, details), pending[0])

    def test__expand_record_tracks_num_children(self):
        ann = self.make_annotator()
        rev_key = (b"rev-id",)
        rev2_key = (b"rev2-id",)
        parent_key = (b"parent-id",)
        record = [b"0,1,1\n", b"new-line\n"]
        details = ("line-delta", False)
        ann._num_compression_children[parent_key] = 2
        ann._expand_record(
            parent_key, (), None, [b"line1\n", b"line2\n"], ("fulltext", False)
        )
        ann._expand_record(rev_key, (parent_key,), parent_key, record, details)
        self.assertEqual({parent_key: 1}, ann._num_compression_children)
        # Expanding the second child should remove the content object, and the
        # num_compression_children entry
        ann._expand_record(rev2_key, (parent_key,), parent_key, record, details)
        self.assertNotIn(parent_key, ann._content_objects)
        self.assertEqual({}, ann._num_compression_children)
        # We should not cache the content_objects for rev2 and rev, because
        # they do not have compression children of their own.
        self.assertEqual({}, ann._content_objects)

    def test__expand_delta_records_blocks(self):
        ann = self.make_annotator()
        rev_key = (b"rev-id",)
        parent_key = (b"parent-id",)
        record = [b"0,1,1\n", b"new-line\n"]
        details = ("line-delta", True)
        ann._num_compression_children[parent_key] = 2
        ann._expand_record(
            parent_key,
            (),
            None,
            [b"line1\n", b"line2\n", b"line3\n"],
            ("fulltext", False),
        )
        ann._expand_record(rev_key, (parent_key,), parent_key, record, details)
        self.assertEqual(
            {(rev_key, parent_key): [(1, 1, 1), (3, 3, 0)]}, ann._matching_blocks
        )
        rev2_key = (b"rev2-id",)
        record = [b"0,1,1\n", b"new-line\n"]
        details = ("line-delta", False)
        ann._expand_record(rev2_key, (parent_key,), parent_key, record, details)
        self.assertEqual(
            [(1, 1, 2), (3, 3, 0)], ann._matching_blocks[(rev2_key, parent_key)]
        )

    def test__get_parent_ann_uses_matching_blocks(self):
        ann = self.make_annotator()
        rev_key = (b"rev-id",)
        parent_key = (b"parent-id",)
        parent_ann = [(parent_key,)] * 3
        block_key = (rev_key, parent_key)
        ann._annotations_cache[parent_key] = parent_ann
        ann._matching_blocks[block_key] = [(0, 1, 1), (3, 3, 0)]
        # We should not try to access any parent_lines content, because we know
        # we already have the matching blocks
        par_ann, blocks = ann._get_parent_annotations_and_matches(
            rev_key, [b"1\n", b"2\n", b"3\n"], parent_key
        )
        self.assertEqual(parent_ann, par_ann)
        self.assertEqual([(0, 1, 1), (3, 3, 0)], blocks)
        self.assertEqual({}, ann._matching_blocks)

    def test__process_pending(self):
        ann = self.make_annotator()
        rev_key = (b"rev-id",)
        p1_key = (b"p1-id",)
        p2_key = (b"p2-id",)
        record = [b"0,1,1\n", b"new-line\n"]
        details = ("line-delta", False)
        p1_record = [b"line1\n", b"line2\n"]
        ann._num_compression_children[p1_key] = 1
        res = ann._expand_record(rev_key, (p1_key, p2_key), p1_key, record, details)
        self.assertEqual(None, res)
        # self.assertTrue(p1_key in ann._pending_deltas)
        self.assertEqual({}, ann._pending_annotation)
        # Now insert p1, and we should be able to expand the delta
        res = ann._expand_record(p1_key, (), None, p1_record, ("fulltext", False))
        self.assertEqual(p1_record, res)
        ann._annotations_cache[p1_key] = [(p1_key,)] * 2
        res = ann._process_pending(p1_key)
        self.assertEqual([], res)
        self.assertNotIn(p1_key, ann._pending_deltas)
        self.assertIn(p2_key, ann._pending_annotation)
        self.assertEqual(
            {p2_key: [(rev_key, (p1_key, p2_key))]}, ann._pending_annotation
        )
        # Now fill in parent 2, and pending annotation should be satisfied
        res = ann._expand_record(p2_key, (), None, [], ("fulltext", False))
        ann._annotations_cache[p2_key] = []
        res = ann._process_pending(p2_key)
        self.assertEqual([rev_key], res)
        self.assertEqual({}, ann._pending_annotation)
        self.assertEqual({}, ann._pending_deltas)

    def test_record_delta_removes_basis(self):
        ann = self.make_annotator()
        ann._expand_record(
            (b"parent-id",), (), None, [b"line1\n", b"line2\n"], ("fulltext", False)
        )
        ann._num_compression_children[b"parent-id"] = 2

    def test_annotate_special_text(self):
        ann = self.make_annotator()
        vf = ann._vf
        rev1_key = (b"rev-1",)
        rev2_key = (b"rev-2",)
        rev3_key = (b"rev-3",)
        spec_key = (b"special:",)
        vf.add_lines(rev1_key, [], [b"initial content\n"])
        vf.add_lines(
            rev2_key,
            [rev1_key],
            [b"initial content\n", b"common content\n", b"content in 2\n"],
        )
        vf.add_lines(
            rev3_key,
            [rev1_key],
            [b"initial content\n", b"common content\n", b"content in 3\n"],
        )
        spec_text = b"initial content\ncommon content\ncontent in 2\ncontent in 3\n"
        ann.add_special_text(spec_key, [rev2_key, rev3_key], spec_text)
        anns, lines = ann.annotate(spec_key)
        self.assertEqual(
            [
                (rev1_key,),
                (rev2_key, rev3_key),
                (rev2_key,),
                (rev3_key,),
            ],
            anns,
        )
        self.assertEqualDiff(spec_text, b"".join(lines))


class KnitTests(TestCaseWithTransport):
    """Class containing knit test helper routines."""

    def make_test_knit(self, annotate=False, name="test"):
        mapper = ConstantMapper(name)
        return make_file_factory(annotate, mapper)(self.get_transport())


class TestBadShaError(KnitTests):
    """Tests for handling of sha errors."""

    def test_sha_exception_has_text(self):
        # having the failed text included in the error allows for recovery.
        source = self.make_test_knit()
        target = self.make_test_knit(name="target")
        if not source._max_delta_chain:
            raise TestNotApplicable(
                "cannot get delta-caused sha failures without deltas."
            )
        # create a basis
        basis = (b"basis",)
        broken = (b"broken",)
        source.add_lines(basis, (), [b"foo\n"])
        source.add_lines(broken, (basis,), [b"foo\n", b"bar\n"])
        # Seed target with a bad basis text
        target.add_lines(basis, (), [b"gam\n"])
        target.insert_record_stream(
            source.get_record_stream([broken], "unordered", False)
        )
        err = self.assertRaises(
            KnitCorrupt,
            next(target.get_record_stream([broken], "unordered", True)).get_bytes_as,
            "chunked",
        )
        self.assertEqual([b"gam\n", b"bar\n"], err.content)
        # Test for formatting with live data
        self.assertStartsWith(str(err), "Knit ")


class TestKnitIndex(KnitTests):
    def test_add_versions_dictionary_compresses(self):
        """Adding versions to the index should update the lookup dict."""
        knit = self.make_test_knit()
        idx = knit._index
        idx.add_records([((b"a-1",), [b"fulltext"], ((b"a-1",), 0, 0), [])])
        self.check_file_contents(
            "test.kndx", b"# bzr knit index 8\n\na-1 fulltext 0 0  :"
        )
        idx.add_records(
            [
                ((b"a-2",), [b"fulltext"], ((b"a-2",), 0, 0), [(b"a-1",)]),
                ((b"a-3",), [b"fulltext"], ((b"a-3",), 0, 0), [(b"a-2",)]),
            ]
        )
        self.check_file_contents(
            "test.kndx",
            b"# bzr knit index 8\n"
            b"\n"
            b"a-1 fulltext 0 0  :\n"
            b"a-2 fulltext 0 0 0 :\n"
            b"a-3 fulltext 0 0 1 :",
        )
        self.assertEqual({(b"a-3",), (b"a-1",), (b"a-2",)}, idx.keys())
        self.assertEqual(
            {
                (b"a-1",): (((b"a-1",), 0, 0), None, (), ("fulltext", False)),
                (b"a-2",): (((b"a-2",), 0, 0), None, ((b"a-1",),), ("fulltext", False)),
                (b"a-3",): (((b"a-3",), 0, 0), None, ((b"a-2",),), ("fulltext", False)),
            },
            idx.get_build_details(idx.keys()),
        )
        self.assertEqual(
            {
                (b"a-1",): (),
                (b"a-2",): ((b"a-1",),),
                (b"a-3",): ((b"a-2",),),
            },
            idx.get_parent_map(idx.keys()),
        )

    def test_add_versions_fails_clean(self):
        """If add_versions fails in the middle, it restores a pristine state.

        Any modifications that are made to the index are reset if all versions
        cannot be added.
        """
        # This cheats a little bit by passing in a generator which will
        # raise an exception before the processing finishes
        # Other possibilities would be to have an version with the wrong number
        # of entries, or to make the backing transport unable to write any
        # files.

        knit = self.make_test_knit()
        idx = knit._index
        idx.add_records([((b"a-1",), [b"fulltext"], ((b"a-1",), 0, 0), [])])

        class StopEarly(Exception):
            pass

        def generate_failure():
            """Add some entries and then raise an exception."""
            yield ((b"a-2",), [b"fulltext"], (None, 0, 0), (b"a-1",))
            yield ((b"a-3",), [b"fulltext"], (None, 0, 0), (b"a-2",))
            raise StopEarly()

        # Assert the pre-condition
        def assertA1Only():
            self.assertEqual({(b"a-1",)}, set(idx.keys()))
            self.assertEqual(
                {(b"a-1",): (((b"a-1",), 0, 0), None, (), ("fulltext", False))},
                idx.get_build_details([(b"a-1",)]),
            )
            self.assertEqual({(b"a-1",): ()}, idx.get_parent_map(idx.keys()))

        assertA1Only()
        self.assertRaises(StopEarly, idx.add_records, generate_failure())
        # And it shouldn't be modified
        assertA1Only()

    def test_knit_index_ignores_empty_files(self):
        # There was a race condition in older bzr, where a ^C at the right time
        # could leave an empty .kndx file, which bzr would later claim was a
        # corrupted file since the header was not present. In reality, the file
        # just wasn't created, so it should be ignored.
        t = _mod_transport.get_transport_from_path(".")
        t.put_bytes("test.kndx", b"")

        self.make_test_knit()

    def test_knit_index_checks_header(self):
        t = _mod_transport.get_transport_from_path(".")
        t.put_bytes("test.kndx", b"# not really a knit header\n\n")
        k = self.make_test_knit()
        self.assertRaises(KnitHeaderError, k.keys)


class TestGraphIndexKnit(KnitTests):
    """Tests for knits using a GraphIndex rather than a KnitIndex."""

    def make_g_index(self, name, ref_lists=0, nodes=None):
        if nodes is None:
            nodes = []
        builder = GraphIndexBuilder(ref_lists)
        for node, references, value in nodes:
            builder.add_node(node, references, value)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return GraphIndex(trans, name, size)

    def two_graph_index(self, deltas=False, catch_adds=False):
        """Build a two-graph index.

        :param deltas: If true, use underlying indices with two node-ref
            lists and 'parent' set to a delta-compressed against tail.
        """
        # build a complex graph across several indices.
        if deltas:
            # delta compression inn the index
            index1 = self.make_g_index(
                "1",
                2,
                [
                    (
                        (b"tip",),
                        b"N0 100",
                        (
                            [(b"parent",)],
                            [],
                        ),
                    ),
                    ((b"tail",), b"", ([], [])),
                ],
            )
            index2 = self.make_g_index(
                "2",
                2,
                [
                    (
                        (b"parent",),
                        b" 100 78",
                        ([(b"tail",), (b"ghost",)], [(b"tail",)]),
                    ),
                    ((b"separate",), b"", ([], [])),
                ],
            )
        else:
            # just blob location and graph in the index.
            index1 = self.make_g_index(
                "1",
                1,
                [((b"tip",), b"N0 100", ([(b"parent",)],)), ((b"tail",), b"", ([],))],
            )
            index2 = self.make_g_index(
                "2",
                1,
                [
                    ((b"parent",), b" 100 78", ([(b"tail",), (b"ghost",)],)),
                    ((b"separate",), b"", ([],)),
                ],
            )
        combined_index = CombinedGraphIndex([index1, index2])
        if catch_adds:
            self.combined_index = combined_index
            self.caught_entries = []
            add_callback = self.catch_add
        else:
            add_callback = None
        return _KnitGraphIndex(
            combined_index, lambda: True, deltas=deltas, add_callback=add_callback
        )

    def test_keys(self):
        index = self.two_graph_index()
        self.assertEqual(
            {(b"tail",), (b"tip",), (b"parent",), (b"separate",)}, set(index.keys())
        )

    def test_get_position(self):
        index = self.two_graph_index()
        self.assertEqual(
            (index._graph_index._indices[0], 0, 100), index.get_position((b"tip",))
        )
        self.assertEqual(
            (index._graph_index._indices[1], 100, 78), index.get_position((b"parent",))
        )

    def test_get_method_deltas(self):
        index = self.two_graph_index(deltas=True)
        self.assertEqual("fulltext", index.get_method((b"tip",)))
        self.assertEqual("line-delta", index.get_method((b"parent",)))

    def test_get_method_no_deltas(self):
        # check that the parent-history lookup is ignored with deltas=False.
        index = self.two_graph_index(deltas=False)
        self.assertEqual("fulltext", index.get_method((b"tip",)))
        self.assertEqual("fulltext", index.get_method((b"parent",)))

    def test_get_options_deltas(self):
        index = self.two_graph_index(deltas=True)
        self.assertEqual([b"fulltext", b"no-eol"], index.get_options((b"tip",)))
        self.assertEqual([b"line-delta"], index.get_options((b"parent",)))

    def test_get_options_no_deltas(self):
        # check that the parent-history lookup is ignored with deltas=False.
        index = self.two_graph_index(deltas=False)
        self.assertEqual([b"fulltext", b"no-eol"], index.get_options((b"tip",)))
        self.assertEqual([b"fulltext"], index.get_options((b"parent",)))

    def test_get_parent_map(self):
        index = self.two_graph_index()
        self.assertEqual(
            {(b"parent",): ((b"tail",), (b"ghost",))},
            index.get_parent_map([(b"parent",), (b"ghost",)]),
        )

    def catch_add(self, entries):
        self.caught_entries.append(entries)

    def test_add_no_callback_errors(self):
        index = self.two_graph_index()
        self.assertRaises(
            errors.ReadOnlyError,
            index.add_records,
            [((b"new",), b"fulltext,no-eol", (None, 50, 60), [b"separate"])],
        )

    def test_add_version_smoke(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records(
            [((b"new",), b"fulltext,no-eol", (None, 50, 60), [(b"separate",)])]
        )
        self.assertEqual(
            [[((b"new",), b"N50 60", (((b"separate",),),))]], self.caught_entries
        )

    def test_add_version_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"new",), b"no-eol,line-delta", (None, 0, 100), [(b"parent",)])],
        )
        self.assertEqual([], self.caught_entries)

    def test_add_version_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_records(
            [((b"tip",), b"fulltext,no-eol", (None, 0, 100), [(b"parent",)])]
        )
        index.add_records(
            [((b"tip",), b"no-eol,fulltext", (None, 0, 100), [(b"parent",)])]
        )
        # position/length are ignored (because each pack could have fulltext or
        # delta, and be at a different position.
        index.add_records(
            [((b"tip",), b"fulltext,no-eol", (None, 50, 100), [(b"parent",)])]
        )
        index.add_records(
            [((b"tip",), b"fulltext,no-eol", (None, 0, 1000), [(b"parent",)])]
        )
        # but neither should have added data:
        self.assertEqual([[], [], [], []], self.caught_entries)

    def test_add_version_different_dup(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        # change options
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"line-delta", (None, 0, 100), [(b"parent",)])],
        )
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"fulltext", (None, 0, 100), [(b"parent",)])],
        )
        # parents
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"fulltext,no-eol", (None, 0, 100), [])],
        )
        self.assertEqual([], self.caught_entries)

    def test_add_versions_nodeltas(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records(
            [
                ((b"new",), b"fulltext,no-eol", (None, 50, 60), [(b"separate",)]),
                ((b"new2",), b"fulltext", (None, 0, 6), [(b"new",)]),
            ]
        )
        self.assertEqual(
            [
                ((b"new",), b"N50 60", (((b"separate",),),)),
                ((b"new2",), b" 0 6", (((b"new",),),)),
            ],
            sorted(self.caught_entries[0]),
        )
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_deltas(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        index.add_records(
            [
                ((b"new",), b"fulltext,no-eol", (None, 50, 60), [(b"separate",)]),
                ((b"new2",), b"line-delta", (None, 0, 6), [(b"new",)]),
            ]
        )
        self.assertEqual(
            [
                ((b"new",), b"N50 60", (((b"separate",),), ())),
                (
                    (b"new2",),
                    b" 0 6",
                    (
                        ((b"new",),),
                        ((b"new",),),
                    ),
                ),
            ],
            sorted(self.caught_entries[0]),
        )
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"new",), b"no-eol,line-delta", (None, 0, 100), [(b"parent",)])],
        )
        self.assertEqual([], self.caught_entries)

    def test_add_versions_random_id_accepted(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([], random_id=True)

    def test_add_versions_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_records(
            [((b"tip",), b"fulltext,no-eol", (None, 0, 100), [(b"parent",)])]
        )
        index.add_records(
            [((b"tip",), b"no-eol,fulltext", (None, 0, 100), [(b"parent",)])]
        )
        # position/length are ignored (because each pack could have fulltext or
        # delta, and be at a different position.
        index.add_records(
            [((b"tip",), b"fulltext,no-eol", (None, 50, 100), [(b"parent",)])]
        )
        index.add_records(
            [((b"tip",), b"fulltext,no-eol", (None, 0, 1000), [(b"parent",)])]
        )
        # but neither should have added data.
        self.assertEqual([[], [], [], []], self.caught_entries)

    def test_add_versions_different_dup(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        # change options
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"line-delta", (None, 0, 100), [(b"parent",)])],
        )
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"fulltext", (None, 0, 100), [(b"parent",)])],
        )
        # parents
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"fulltext,no-eol", (None, 0, 100), [])],
        )
        # change options in the second record
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [
                ((b"tip",), b"fulltext,no-eol", (None, 0, 100), [(b"parent",)]),
                ((b"tip",), b"line-delta", (None, 0, 100), [(b"parent",)]),
            ],
        )
        self.assertEqual([], self.caught_entries)

    def make_g_index_missing_compression_parent(self):
        graph_index = self.make_g_index(
            "missing_comp",
            2,
            [
                (
                    (b"tip",),
                    b" 100 78",
                    ([(b"missing-parent",), (b"ghost",)], [(b"missing-parent",)]),
                )
            ],
        )
        return graph_index

    def make_g_index_missing_parent(self):
        graph_index = self.make_g_index(
            "missing_parent",
            2,
            [
                ((b"parent",), b" 100 78", ([], [])),
                (
                    (b"tip",),
                    b" 100 78",
                    ([(b"parent",), (b"missing-parent",)], [(b"parent",)]),
                ),
            ],
        )
        return graph_index

    def make_g_index_no_external_refs(self):
        graph_index = self.make_g_index(
            "no_external_refs",
            2,
            [((b"rev",), b" 100 78", ([(b"parent",), (b"ghost",)], []))],
        )
        return graph_index

    def test_add_good_unvalidated_index(self):
        unvalidated = self.make_g_index_no_external_refs()
        combined = CombinedGraphIndex([unvalidated])
        index = _KnitGraphIndex(combined, lambda: True, deltas=True)
        index.scan_unvalidated_index(unvalidated)
        self.assertEqual(frozenset(), index.get_missing_compression_parents())

    def test_add_missing_compression_parent_unvalidated_index(self):
        unvalidated = self.make_g_index_missing_compression_parent()
        combined = CombinedGraphIndex([unvalidated])
        index = _KnitGraphIndex(combined, lambda: True, deltas=True)
        index.scan_unvalidated_index(unvalidated)
        # This also checks that its only the compression parent that is
        # examined, otherwise 'ghost' would also be reported as a missing
        # parent.
        self.assertEqual(
            frozenset([(b"missing-parent",)]), index.get_missing_compression_parents()
        )

    def test_add_missing_noncompression_parent_unvalidated_index(self):
        unvalidated = self.make_g_index_missing_parent()
        combined = CombinedGraphIndex([unvalidated])
        index = _KnitGraphIndex(
            combined, lambda: True, deltas=True, track_external_parent_refs=True
        )
        index.scan_unvalidated_index(unvalidated)
        self.assertEqual(frozenset([(b"missing-parent",)]), index.get_missing_parents())

    def test_track_external_parent_refs(self):
        g_index = self.make_g_index("empty", 2, [])
        combined = CombinedGraphIndex([g_index])
        index = _KnitGraphIndex(
            combined,
            lambda: True,
            deltas=True,
            add_callback=self.catch_add,
            track_external_parent_refs=True,
        )
        self.caught_entries = []
        index.add_records(
            [
                (
                    (b"new-key",),
                    b"fulltext,no-eol",
                    (None, 50, 60),
                    [(b"parent-1",), (b"parent-2",)],
                )
            ]
        )
        self.assertEqual(
            frozenset([(b"parent-1",), (b"parent-2",)]), index.get_missing_parents()
        )

    def test_add_unvalidated_index_with_present_external_references(self):
        index = self.two_graph_index(deltas=True)
        # Ugly hack to get at one of the underlying GraphIndex objects that
        # two_graph_index built.
        unvalidated = index._graph_index._indices[1]
        # 'parent' is an external ref of _indices[1] (unvalidated), but is
        # present in _indices[0].
        index.scan_unvalidated_index(unvalidated)
        self.assertEqual(frozenset(), index.get_missing_compression_parents())

    def make_new_missing_parent_g_index(self, name):
        missing_parent = name.encode("ascii") + b"-missing-parent"
        graph_index = self.make_g_index(
            name,
            2,
            [
                (
                    (name.encode("ascii") + b"tip",),
                    b" 100 78",
                    ([(missing_parent,), (b"ghost",)], [(missing_parent,)]),
                )
            ],
        )
        return graph_index

    def test_add_mulitiple_unvalidated_indices_with_missing_parents(self):
        g_index_1 = self.make_new_missing_parent_g_index("one")
        g_index_2 = self.make_new_missing_parent_g_index("two")
        combined = CombinedGraphIndex([g_index_1, g_index_2])
        index = _KnitGraphIndex(combined, lambda: True, deltas=True)
        index.scan_unvalidated_index(g_index_1)
        index.scan_unvalidated_index(g_index_2)
        self.assertEqual(
            frozenset([(b"one-missing-parent",), (b"two-missing-parent",)]),
            index.get_missing_compression_parents(),
        )

    def test_add_mulitiple_unvalidated_indices_with_mutual_dependencies(self):
        graph_index_a = self.make_g_index(
            "one",
            2,
            [
                ((b"parent-one",), b" 100 78", ([(b"non-compression-parent",)], [])),
                (
                    (b"child-of-two",),
                    b" 100 78",
                    ([(b"parent-two",)], [(b"parent-two",)]),
                ),
            ],
        )
        graph_index_b = self.make_g_index(
            "two",
            2,
            [
                ((b"parent-two",), b" 100 78", ([(b"non-compression-parent",)], [])),
                (
                    (b"child-of-one",),
                    b" 100 78",
                    ([(b"parent-one",)], [(b"parent-one",)]),
                ),
            ],
        )
        combined = CombinedGraphIndex([graph_index_a, graph_index_b])
        index = _KnitGraphIndex(combined, lambda: True, deltas=True)
        index.scan_unvalidated_index(graph_index_a)
        index.scan_unvalidated_index(graph_index_b)
        self.assertEqual(frozenset([]), index.get_missing_compression_parents())


class TestNoParentsGraphIndexKnit(KnitTests):
    """Tests for knits using _KnitGraphIndex with no parents."""

    def make_g_index(self, name, ref_lists=0, nodes=None):
        if nodes is None:
            nodes = []
        builder = GraphIndexBuilder(ref_lists)
        for node, references in nodes:
            builder.add_node(node, references)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return GraphIndex(trans, name, size)

    def test_add_good_unvalidated_index(self):
        unvalidated = self.make_g_index("unvalidated")
        combined = CombinedGraphIndex([unvalidated])
        index = _KnitGraphIndex(combined, lambda: True, parents=False)
        index.scan_unvalidated_index(unvalidated)
        self.assertEqual(frozenset(), index.get_missing_compression_parents())

    def test_parents_deltas_incompatible(self):
        index = CombinedGraphIndex([])
        self.assertRaises(
            knit.KnitError,
            _KnitGraphIndex,
            lambda: True,
            index,
            deltas=True,
            parents=False,
        )

    def two_graph_index(self, catch_adds=False):
        """Build a two-graph index.

        :param deltas: If true, use underlying indices with two node-ref
            lists and 'parent' set to a delta-compressed against tail.
        """
        # put several versions in the index.
        index1 = self.make_g_index("1", 0, [((b"tip",), b"N0 100"), ((b"tail",), b"")])
        index2 = self.make_g_index(
            "2", 0, [((b"parent",), b" 100 78"), ((b"separate",), b"")]
        )
        combined_index = CombinedGraphIndex([index1, index2])
        if catch_adds:
            self.combined_index = combined_index
            self.caught_entries = []
            add_callback = self.catch_add
        else:
            add_callback = None
        return _KnitGraphIndex(
            combined_index, lambda: True, parents=False, add_callback=add_callback
        )

    def test_keys(self):
        index = self.two_graph_index()
        self.assertEqual(
            {(b"tail",), (b"tip",), (b"parent",), (b"separate",)}, set(index.keys())
        )

    def test_get_position(self):
        index = self.two_graph_index()
        self.assertEqual(
            (index._graph_index._indices[0], 0, 100), index.get_position((b"tip",))
        )
        self.assertEqual(
            (index._graph_index._indices[1], 100, 78), index.get_position((b"parent",))
        )

    def test_get_method(self):
        index = self.two_graph_index()
        self.assertEqual("fulltext", index.get_method((b"tip",)))
        self.assertEqual([b"fulltext"], index.get_options((b"parent",)))

    def test_get_options(self):
        index = self.two_graph_index()
        self.assertEqual([b"fulltext", b"no-eol"], index.get_options((b"tip",)))
        self.assertEqual([b"fulltext"], index.get_options((b"parent",)))

    def test_get_parent_map(self):
        index = self.two_graph_index()
        self.assertEqual(
            {(b"parent",): None}, index.get_parent_map([(b"parent",), (b"ghost",)])
        )

    def catch_add(self, entries):
        self.caught_entries.append(entries)

    def test_add_no_callback_errors(self):
        index = self.two_graph_index()
        self.assertRaises(
            errors.ReadOnlyError,
            index.add_records,
            [((b"new",), b"fulltext,no-eol", (None, 50, 60), [(b"separate",)])],
        )

    def test_add_version_smoke(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([((b"new",), b"fulltext,no-eol", (None, 50, 60), [])])
        self.assertEqual([[((b"new",), b"N50 60")]], self.caught_entries)

    def test_add_version_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"new",), b"no-eol,line-delta", (None, 0, 100), [])],
        )
        self.assertEqual([], self.caught_entries)

    def test_add_version_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_records([((b"tip",), b"fulltext,no-eol", (None, 0, 100), [])])
        index.add_records([((b"tip",), b"no-eol,fulltext", (None, 0, 100), [])])
        # position/length are ignored (because each pack could have fulltext or
        # delta, and be at a different position.
        index.add_records([((b"tip",), b"fulltext,no-eol", (None, 50, 100), [])])
        index.add_records([((b"tip",), b"fulltext,no-eol", (None, 0, 1000), [])])
        # but neither should have added data.
        self.assertEqual([[], [], [], []], self.caught_entries)

    def test_add_version_different_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # change options
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"no-eol,line-delta", (None, 0, 100), [])],
        )
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"line-delta,no-eol", (None, 0, 100), [])],
        )
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"fulltext", (None, 0, 100), [])],
        )
        # parents
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"fulltext,no-eol", (None, 0, 100), [(b"parent",)])],
        )
        self.assertEqual([], self.caught_entries)

    def test_add_versions(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records(
            [
                ((b"new",), b"fulltext,no-eol", (None, 50, 60), []),
                ((b"new2",), b"fulltext", (None, 0, 6), []),
            ]
        )
        self.assertEqual(
            [((b"new",), b"N50 60"), ((b"new2",), b" 0 6")],
            sorted(self.caught_entries[0]),
        )
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"new",), b"no-eol,line-delta", (None, 0, 100), [(b"parent",)])],
        )
        self.assertEqual([], self.caught_entries)

    def test_add_versions_parents_not_parents_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"new",), b"no-eol,fulltext", (None, 0, 100), [(b"parent",)])],
        )
        self.assertEqual([], self.caught_entries)

    def test_add_versions_random_id_accepted(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([], random_id=True)

    def test_add_versions_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_records([((b"tip",), b"fulltext,no-eol", (None, 0, 100), [])])
        index.add_records([((b"tip",), b"no-eol,fulltext", (None, 0, 100), [])])
        # position/length are ignored (because each pack could have fulltext or
        # delta, and be at a different position.
        index.add_records([((b"tip",), b"fulltext,no-eol", (None, 50, 100), [])])
        index.add_records([((b"tip",), b"fulltext,no-eol", (None, 0, 1000), [])])
        # but neither should have added data.
        self.assertEqual([[], [], [], []], self.caught_entries)

    def test_add_versions_different_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # change options
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"no-eol,line-delta", (None, 0, 100), [])],
        )
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"line-delta,no-eol", (None, 0, 100), [])],
        )
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"fulltext", (None, 0, 100), [])],
        )
        # parents
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [((b"tip",), b"fulltext,no-eol", (None, 0, 100), [(b"parent",)])],
        )
        # change options in the second record
        self.assertRaises(
            KnitCorrupt,
            index.add_records,
            [
                ((b"tip",), b"fulltext,no-eol", (None, 0, 100), []),
                ((b"tip",), b"no-eol,line-delta", (None, 0, 100), []),
            ],
        )
        self.assertEqual([], self.caught_entries)


class TestKnitVersionedFiles(KnitTests):
    def assertGroupKeysForIo(
        self, exp_groups, keys, non_local_keys, positions, _min_buffer_size=None
    ):
        kvf = self.make_test_knit()
        if _min_buffer_size is None:
            _min_buffer_size = knit._STREAM_MIN_BUFFER_SIZE
        self.assertEqual(
            exp_groups,
            kvf._group_keys_for_io(
                keys, non_local_keys, positions, _min_buffer_size=_min_buffer_size
            ),
        )

    def assertSplitByPrefix(self, expected_map, expected_prefix_order, keys):
        split, prefix_order = KnitVersionedFiles._split_by_prefix(keys)
        self.assertEqual(expected_map, split)
        self.assertEqual(expected_prefix_order, prefix_order)

    def test__group_keys_for_io(self):
        ft_detail = ("fulltext", False)
        ld_detail = ("line-delta", False)
        f_a = (b"f", b"a")
        f_b = (b"f", b"b")
        f_c = (b"f", b"c")
        g_a = (b"g", b"a")
        g_b = (b"g", b"b")
        g_c = (b"g", b"c")
        positions = {
            f_a: (ft_detail, (f_a, 0, 100), None),
            f_b: (ld_detail, (f_b, 100, 21), f_a),
            f_c: (ld_detail, (f_c, 180, 15), f_b),
            g_a: (ft_detail, (g_a, 121, 35), None),
            g_b: (ld_detail, (g_b, 156, 12), g_a),
            g_c: (ld_detail, (g_c, 195, 13), g_a),
        }
        self.assertGroupKeysForIo([([f_a], set())], [f_a], [], positions)
        self.assertGroupKeysForIo([([f_a], {f_a})], [f_a], [f_a], positions)
        self.assertGroupKeysForIo([([f_a, f_b], set())], [f_a, f_b], [], positions)
        self.assertGroupKeysForIo([([f_a, f_b], {f_b})], [f_a, f_b], [f_b], positions)
        self.assertGroupKeysForIo(
            [([f_a, f_b, g_a, g_b], set())], [f_a, g_a, f_b, g_b], [], positions
        )
        self.assertGroupKeysForIo(
            [([f_a, f_b, g_a, g_b], set())],
            [f_a, g_a, f_b, g_b],
            [],
            positions,
            _min_buffer_size=150,
        )
        self.assertGroupKeysForIo(
            [([f_a, f_b], set()), ([g_a, g_b], set())],
            [f_a, g_a, f_b, g_b],
            [],
            positions,
            _min_buffer_size=100,
        )
        self.assertGroupKeysForIo(
            [([f_c], set()), ([g_b], set())],
            [f_c, g_b],
            [],
            positions,
            _min_buffer_size=125,
        )
        self.assertGroupKeysForIo(
            [([g_b, f_c], set())], [g_b, f_c], [], positions, _min_buffer_size=125
        )

    def test__split_by_prefix(self):
        self.assertSplitByPrefix(
            {
                b"f": [(b"f", b"a"), (b"f", b"b")],
                b"g": [(b"g", b"b"), (b"g", b"a")],
            },
            [b"f", b"g"],
            [(b"f", b"a"), (b"g", b"b"), (b"g", b"a"), (b"f", b"b")],
        )

        self.assertSplitByPrefix(
            {
                b"f": [(b"f", b"a"), (b"f", b"b")],
                b"g": [(b"g", b"b"), (b"g", b"a")],
            },
            [b"f", b"g"],
            [(b"f", b"a"), (b"f", b"b"), (b"g", b"b"), (b"g", b"a")],
        )

        self.assertSplitByPrefix(
            {
                b"f": [(b"f", b"a"), (b"f", b"b")],
                b"g": [(b"g", b"b"), (b"g", b"a")],
            },
            [b"f", b"g"],
            [(b"f", b"a"), (b"f", b"b"), (b"g", b"b"), (b"g", b"a")],
        )

        self.assertSplitByPrefix(
            {
                b"f": [(b"f", b"a"), (b"f", b"b")],
                b"g": [(b"g", b"b"), (b"g", b"a")],
                b"": [(b"a",), (b"b",)],
            },
            [b"f", b"g", b""],
            [(b"f", b"a"), (b"g", b"b"), (b"a",), (b"b",), (b"g", b"a"), (b"f", b"b")],
        )


class TestStacking(KnitTests):
    def get_basis_and_test_knit(self):
        basis = self.make_test_knit(name="basis")
        basis = RecordingVersionedFilesDecorator(basis)
        test = self.make_test_knit(name="test")
        test.add_fallback_versioned_files(basis)
        return basis, test

    def test_add_fallback_versioned_files(self):
        basis = self.make_test_knit(name="basis")
        test = self.make_test_knit(name="test")
        # It must not error; other tests test that the fallback is referred to
        # when accessing data.
        test.add_fallback_versioned_files(basis)

    def test_add_lines(self):
        # lines added to the test are not added to the basis
        basis, test = self.get_basis_and_test_knit()
        key = (b"foo",)
        key_basis = (b"bar",)
        key_cross_border = (b"quux",)
        key_delta = (b"zaphod",)
        test.add_lines(key, (), [b"foo\n"])
        self.assertEqual({}, basis.get_parent_map([key]))
        # lines added to the test that reference across the stack do a
        # fulltext.
        basis.add_lines(key_basis, (), [b"foo\n"])
        basis.calls = []
        test.add_lines(key_cross_border, (key_basis,), [b"foo\n"])
        self.assertEqual("fulltext", test._index.get_method(key_cross_border))
        # we don't even need to look at the basis to see that this should be
        # stored as a fulltext
        self.assertEqual([], basis.calls)
        # Subsequent adds do delta.
        basis.calls = []
        test.add_lines(key_delta, (key_cross_border,), [b"foo\n"])
        self.assertEqual("line-delta", test._index.get_method(key_delta))
        self.assertEqual([], basis.calls)

    def test_annotate(self):
        # annotations from the test knit are answered without asking the basis
        basis, test = self.get_basis_and_test_knit()
        key = (b"foo",)
        key_basis = (b"bar",)
        test.add_lines(key, (), [b"foo\n"])
        details = test.annotate(key)
        self.assertEqual([(key, b"foo\n")], details)
        self.assertEqual([], basis.calls)
        # But texts that are not in the test knit are looked for in the basis
        # directly.
        basis.add_lines(key_basis, (), [b"foo\n", b"bar\n"])
        basis.calls = []
        details = test.annotate(key_basis)
        self.assertEqual([(key_basis, b"foo\n"), (key_basis, b"bar\n")], details)
        # Not optimised to date:
        # self.assertEqual([("annotate", key_basis)], basis.calls)
        self.assertEqual(
            [
                ("get_parent_map", {key_basis}),
                ("get_parent_map", {key_basis}),
                ("get_record_stream", [key_basis], "topological", True),
            ],
            basis.calls,
        )

    def test_check(self):
        # At the moment checking a stacked knit does implicitly check the
        # fallback files.
        _basis, test = self.get_basis_and_test_knit()
        test.check()

    def test_get_parent_map(self):
        # parents in the test knit are answered without asking the basis
        basis, test = self.get_basis_and_test_knit()
        key = (b"foo",)
        key_basis = (b"bar",)
        key_missing = (b"missing",)
        test.add_lines(key, (), [])
        parent_map = test.get_parent_map([key])
        self.assertEqual({key: ()}, parent_map)
        self.assertEqual([], basis.calls)
        # But parents that are not in the test knit are looked for in the basis
        basis.add_lines(key_basis, (), [])
        basis.calls = []
        parent_map = test.get_parent_map([key, key_basis, key_missing])
        self.assertEqual({key: (), key_basis: ()}, parent_map)
        self.assertEqual([("get_parent_map", {key_basis, key_missing})], basis.calls)

    def test_get_record_stream_unordered_fulltexts(self):
        # records from the test knit are answered without asking the basis:
        basis, test = self.get_basis_and_test_knit()
        key = (b"foo",)
        key_basis = (b"bar",)
        key_missing = (b"missing",)
        test.add_lines(key, (), [b"foo\n"])
        records = list(test.get_record_stream([key], "unordered", True))
        self.assertEqual(1, len(records))
        self.assertEqual([], basis.calls)
        # Missing (from test knit) objects are retrieved from the basis:
        basis.add_lines(key_basis, (), [b"foo\n", b"bar\n"])
        basis.calls = []
        records = list(
            test.get_record_stream([key_basis, key_missing], "unordered", True)
        )
        self.assertEqual(2, len(records))
        calls = list(basis.calls)
        for record in records:
            self.assertSubset([record.key], (key_basis, key_missing))
            if record.key == key_missing:
                self.assertIsInstance(record, AbsentContentFactory)
            else:
                reference = list(
                    basis.get_record_stream([key_basis], "unordered", True)
                )[0]
                self.assertEqual(reference.key, record.key)
                self.assertEqual(reference.sha1, record.sha1)
                self.assertEqual(reference.storage_kind, record.storage_kind)
                self.assertEqual(
                    reference.get_bytes_as(reference.storage_kind),
                    record.get_bytes_as(record.storage_kind),
                )
                self.assertEqual(
                    reference.get_bytes_as("fulltext"), record.get_bytes_as("fulltext")
                )
        # It's not strictly minimal, but it seems reasonable for now for it to
        # ask which fallbacks have which parents.
        self.assertEqual(
            [
                ("get_parent_map", {key_basis, key_missing}),
                ("get_record_stream", [key_basis], "unordered", True),
            ],
            calls,
        )

    def test_get_record_stream_ordered_fulltexts(self):
        # ordering is preserved down into the fallback store.
        basis, test = self.get_basis_and_test_knit()
        key = (b"foo",)
        key_basis = (b"bar",)
        key_basis_2 = (b"quux",)
        key_missing = (b"missing",)
        test.add_lines(key, (key_basis,), [b"foo\n"])
        # Missing (from test knit) objects are retrieved from the basis:
        basis.add_lines(key_basis, (key_basis_2,), [b"foo\n", b"bar\n"])
        basis.add_lines(key_basis_2, (), [b"quux\n"])
        basis.calls = []
        # ask for in non-topological order
        records = list(
            test.get_record_stream(
                [key, key_basis, key_missing, key_basis_2], "topological", True
            )
        )
        self.assertEqual(4, len(records))
        results = []
        for record in records:
            self.assertSubset([record.key], (key_basis, key_missing, key_basis_2, key))
            if record.key == key_missing:
                self.assertIsInstance(record, AbsentContentFactory)
            else:
                results.append(
                    (
                        record.key,
                        record.sha1,
                        record.storage_kind,
                        record.get_bytes_as("fulltext"),
                    )
                )
        calls = list(basis.calls)
        order = [record[0] for record in results]
        self.assertEqual([key_basis_2, key_basis, key], order)
        for result in results:
            source = test if result[0] == key else basis
            record = next(source.get_record_stream([result[0]], "unordered", True))
            self.assertEqual(record.key, result[0])
            self.assertEqual(record.sha1, result[1])
            # We used to check that the storage kind matched, but actually it
            # depends on whether it was sourced from the basis, or in a single
            # group, because asking for full texts returns proxy objects to a
            # _ContentMapGenerator object; so checking the kind is unneeded.
            self.assertEqual(record.get_bytes_as("fulltext"), result[3])
        # It's not strictly minimal, but it seems reasonable for now for it to
        # ask which fallbacks have which parents.
        self.assertEqual(2, len(calls))
        self.assertEqual(
            ("get_parent_map", {key_basis, key_basis_2, key_missing}), calls[0]
        )
        # topological is requested from the fallback, because that is what
        # was requested at the top level.
        self.assertIn(
            calls[1],
            [
                ("get_record_stream", [key_basis_2, key_basis], "topological", True),
                ("get_record_stream", [key_basis, key_basis_2], "topological", True),
            ],
        )

    def test_get_record_stream_unordered_deltas(self):
        # records from the test knit are answered without asking the basis:
        basis, test = self.get_basis_and_test_knit()
        key = (b"foo",)
        key_basis = (b"bar",)
        key_missing = (b"missing",)
        test.add_lines(key, (), [b"foo\n"])
        records = list(test.get_record_stream([key], "unordered", False))
        self.assertEqual(1, len(records))
        self.assertEqual([], basis.calls)
        # Missing (from test knit) objects are retrieved from the basis:
        basis.add_lines(key_basis, (), [b"foo\n", b"bar\n"])
        basis.calls = []
        records = list(
            test.get_record_stream([key_basis, key_missing], "unordered", False)
        )
        self.assertEqual(2, len(records))
        calls = list(basis.calls)
        for record in records:
            self.assertSubset([record.key], (key_basis, key_missing))
            if record.key == key_missing:
                self.assertIsInstance(record, AbsentContentFactory)
            else:
                reference = list(
                    basis.get_record_stream([key_basis], "unordered", False)
                )[0]
                self.assertEqual(reference.key, record.key)
                self.assertEqual(reference.sha1, record.sha1)
                self.assertEqual(reference.storage_kind, record.storage_kind)
                self.assertEqual(
                    reference.get_bytes_as(reference.storage_kind),
                    record.get_bytes_as(record.storage_kind),
                )
        # It's not strictly minimal, but it seems reasonable for now for it to
        # ask which fallbacks have which parents.
        self.assertEqual(
            [
                ("get_parent_map", {key_basis, key_missing}),
                ("get_record_stream", [key_basis], "unordered", False),
            ],
            calls,
        )

    def test_get_record_stream_ordered_deltas(self):
        # ordering is preserved down into the fallback store.
        basis, test = self.get_basis_and_test_knit()
        key = (b"foo",)
        key_basis = (b"bar",)
        key_basis_2 = (b"quux",)
        key_missing = (b"missing",)
        test.add_lines(key, (key_basis,), [b"foo\n"])
        # Missing (from test knit) objects are retrieved from the basis:
        basis.add_lines(key_basis, (key_basis_2,), [b"foo\n", b"bar\n"])
        basis.add_lines(key_basis_2, (), [b"quux\n"])
        basis.calls = []
        # ask for in non-topological order
        records = list(
            test.get_record_stream(
                [key, key_basis, key_missing, key_basis_2], "topological", False
            )
        )
        self.assertEqual(4, len(records))
        results = []
        for record in records:
            self.assertSubset([record.key], (key_basis, key_missing, key_basis_2, key))
            if record.key == key_missing:
                self.assertIsInstance(record, AbsentContentFactory)
            else:
                results.append(
                    (
                        record.key,
                        record.sha1,
                        record.storage_kind,
                        record.get_bytes_as(record.storage_kind),
                    )
                )
        calls = list(basis.calls)
        order = [record[0] for record in results]
        self.assertEqual([key_basis_2, key_basis, key], order)
        for result in results:
            source = test if result[0] == key else basis
            record = next(source.get_record_stream([result[0]], "unordered", False))
            self.assertEqual(record.key, result[0])
            self.assertEqual(record.sha1, result[1])
            self.assertEqual(record.storage_kind, result[2])
            self.assertEqual(record.get_bytes_as(record.storage_kind), result[3])
        # It's not strictly minimal, but it seems reasonable for now for it to
        # ask which fallbacks have which parents.
        self.assertEqual(
            [
                ("get_parent_map", {key_basis, key_basis_2, key_missing}),
                ("get_record_stream", [key_basis_2, key_basis], "topological", False),
            ],
            calls,
        )

    def test_get_sha1s(self):
        # sha1's in the test knit are answered without asking the basis
        basis, test = self.get_basis_and_test_knit()
        key = (b"foo",)
        key_basis = (b"bar",)
        key_missing = (b"missing",)
        test.add_lines(key, (), [b"foo\n"])
        key_sha1sum = osutils.sha_string(b"foo\n")
        sha1s = test.get_sha1s([key])
        self.assertEqual({key: key_sha1sum}, sha1s)
        self.assertEqual([], basis.calls)
        # But texts that are not in the test knit are looked for in the basis
        # directly (rather than via text reconstruction) so that remote servers
        # etc don't have to answer with full content.
        basis.add_lines(key_basis, (), [b"foo\n", b"bar\n"])
        basis_sha1sum = osutils.sha_string(b"foo\nbar\n")
        basis.calls = []
        sha1s = test.get_sha1s([key, key_missing, key_basis])
        self.assertEqual({key: key_sha1sum, key_basis: basis_sha1sum}, sha1s)
        self.assertEqual([("get_sha1s", {key_basis, key_missing})], basis.calls)

    def test_insert_record_stream(self):
        # records are inserted as normal; insert_record_stream builds on
        # add_lines, so a smoke test should be all that's needed:
        key_basis = (b"bar",)
        key_delta = (b"zaphod",)
        basis, test = self.get_basis_and_test_knit()
        source = self.make_test_knit(name="source")
        basis.add_lines(key_basis, (), [b"foo\n"])
        basis.calls = []
        source.add_lines(key_basis, (), [b"foo\n"])
        source.add_lines(key_delta, (key_basis,), [b"bar\n"])
        stream = source.get_record_stream([key_delta], "unordered", False)
        test.insert_record_stream(stream)
        # XXX: this does somewhat too many calls in making sure of whether it
        # has to recreate the full text.
        self.assertEqual(
            [
                ("get_parent_map", {key_basis}),
                ("get_parent_map", {key_basis}),
                ("get_record_stream", [key_basis], "unordered", True),
            ],
            basis.calls,
        )
        self.assertEqual({key_delta: (key_basis,)}, test.get_parent_map([key_delta]))
        self.assertEqual(
            b"bar\n",
            next(test.get_record_stream([key_delta], "unordered", True)).get_bytes_as(
                "fulltext"
            ),
        )

    def test_iter_lines_added_or_present_in_keys(self):
        # Lines from the basis are returned, and lines for a given key are only
        # returned once.
        key1 = (b"foo1",)
        key2 = (b"foo2",)
        # all sources are asked for keys:
        basis, test = self.get_basis_and_test_knit()
        basis.add_lines(key1, (), [b"foo"])
        basis.calls = []
        lines = list(test.iter_lines_added_or_present_in_keys([key1]))
        self.assertEqual([(b"foo\n", key1)], lines)
        self.assertEqual([("iter_lines_added_or_present_in_keys", {key1})], basis.calls)
        # keys in both are not duplicated:
        test.add_lines(key2, (), [b"bar\n"])
        basis.add_lines(key2, (), [b"bar\n"])
        basis.calls = []
        lines = list(test.iter_lines_added_or_present_in_keys([key2]))
        self.assertEqual([(b"bar\n", key2)], lines)
        self.assertEqual([], basis.calls)

    def test_keys(self):
        key1 = (b"foo1",)
        key2 = (b"foo2",)
        # all sources are asked for keys:
        basis, test = self.get_basis_and_test_knit()
        keys = test.keys()
        self.assertEqual(set(), set(keys))
        self.assertEqual([("keys",)], basis.calls)
        # keys from a basis are returned:
        basis.add_lines(key1, (), [])
        basis.calls = []
        keys = test.keys()
        self.assertEqual({key1}, set(keys))
        self.assertEqual([("keys",)], basis.calls)
        # keys in both are not duplicated:
        test.add_lines(key2, (), [])
        basis.add_lines(key2, (), [])
        basis.calls = []
        keys = test.keys()
        self.assertEqual(2, len(keys))
        self.assertEqual({key1, key2}, set(keys))
        self.assertEqual([("keys",)], basis.calls)

    def test_add_mpdiffs(self):
        # records are inserted as normal; add_mpdiff builds on
        # add_lines, so a smoke test should be all that's needed:
        key_basis = (b"bar",)
        key_delta = (b"zaphod",)
        basis, test = self.get_basis_and_test_knit()
        source = self.make_test_knit(name="source")
        basis.add_lines(key_basis, (), [b"foo\n"])
        basis.calls = []
        source.add_lines(key_basis, (), [b"foo\n"])
        source.add_lines(key_delta, (key_basis,), [b"bar\n"])
        diffs = source.make_mpdiffs([key_delta])
        test.add_mpdiffs(
            [
                (
                    key_delta,
                    (key_basis,),
                    source.get_sha1s([key_delta])[key_delta],
                    diffs[0],
                )
            ]
        )
        self.assertEqual(
            [
                ("get_parent_map", {key_basis}),
                ("get_record_stream", [key_basis], "unordered", True),
            ],
            basis.calls,
        )
        self.assertEqual({key_delta: (key_basis,)}, test.get_parent_map([key_delta]))
        self.assertEqual(
            b"bar\n",
            next(test.get_record_stream([key_delta], "unordered", True)).get_bytes_as(
                "fulltext"
            ),
        )

    def test_make_mpdiffs(self):
        # Generating an mpdiff across a stacking boundary should detect parent
        # texts regions.
        key = (b"foo",)
        key_left = (b"bar",)
        key_right = (b"zaphod",)
        basis, test = self.get_basis_and_test_knit()
        basis.add_lines(key_left, (), [b"bar\n"])
        basis.add_lines(key_right, (), [b"zaphod\n"])
        basis.calls = []
        test.add_lines(key, (key_left, key_right), [b"bar\n", b"foo\n", b"zaphod\n"])
        diffs = test.make_mpdiffs([key])
        self.assertEqual(
            [
                multiparent.MultiParent(
                    [
                        multiparent.ParentText(0, 0, 0, 1),
                        multiparent.NewText([b"foo\n"]),
                        multiparent.ParentText(1, 0, 2, 1),
                    ]
                )
            ],
            diffs,
        )
        self.assertEqual(3, len(basis.calls))
        self.assertEqual(
            [
                ("get_parent_map", {key_left, key_right}),
                ("get_parent_map", {key_left, key_right}),
            ],
            basis.calls[:-1],
        )
        last_call = basis.calls[-1]
        self.assertEqual("get_record_stream", last_call[0])
        self.assertEqual({key_left, key_right}, set(last_call[1]))
        self.assertEqual("topological", last_call[2])
        self.assertEqual(True, last_call[3])


class TestNetworkBehaviour(KnitTests):
    """Tests for getting data out of/into knits over the network."""

    def test_include_delta_closure_generates_a_knit_delta_closure(self):
        vf = self.make_test_knit(name="test")
        # put in three texts, giving ft, delta, delta
        vf.add_lines((b"base",), (), [b"base\n", b"content\n"])
        vf.add_lines((b"d1",), ((b"base",),), [b"d1\n"])
        vf.add_lines((b"d2",), ((b"d1",),), [b"d2\n"])
        # But heuristics could interfere, so check what happened:
        self.assertEqual(
            ["knit-ft-gz", "knit-delta-gz", "knit-delta-gz"],
            [
                record.storage_kind
                for record in vf.get_record_stream(
                    [(b"base",), (b"d1",), (b"d2",)], "topological", False
                )
            ],
        )
        # generate a stream of just the deltas include_delta_closure=True,
        # serialise to the network, and check that we get a delta closure on the wire.
        stream = vf.get_record_stream([(b"d1",), (b"d2",)], "topological", True)
        netb = [record.get_bytes_as(record.storage_kind) for record in stream]
        # The first bytes should be a memo from _ContentMapGenerator, and the
        # second bytes should be empty (because its a API proxy not something
        # for wire serialisation.
        self.assertEqual(b"", netb[1])
        bytes = netb[0]
        kind, _line_end = network_bytes_to_kind_and_offset(bytes)
        self.assertEqual("knit-delta-closure", kind)


class TestContentMapGenerator(KnitTests):
    """Tests for ContentMapGenerator."""

    def test_get_record_stream_gives_records(self):
        vf = self.make_test_knit(name="test")
        # put in three texts, giving ft, delta, delta
        vf.add_lines((b"base",), (), [b"base\n", b"content\n"])
        vf.add_lines((b"d1",), ((b"base",),), [b"d1\n"])
        vf.add_lines((b"d2",), ((b"d1",),), [b"d2\n"])
        keys = [(b"d1",), (b"d2",)]
        generator = _VFContentMapGenerator(vf, keys, global_map=vf.get_parent_map(keys))
        for record in generator.get_record_stream():
            if record.key == (b"d1",):
                self.assertEqual(b"d1\n", record.get_bytes_as("fulltext"))
            else:
                self.assertEqual(b"d2\n", record.get_bytes_as("fulltext"))

    def test_get_record_stream_kinds_are_raw(self):
        vf = self.make_test_knit(name="test")
        # put in three texts, giving ft, delta, delta
        vf.add_lines((b"base",), (), [b"base\n", b"content\n"])
        vf.add_lines((b"d1",), ((b"base",),), [b"d1\n"])
        vf.add_lines((b"d2",), ((b"d1",),), [b"d2\n"])
        keys = [(b"base",), (b"d1",), (b"d2",)]
        generator = _VFContentMapGenerator(vf, keys, global_map=vf.get_parent_map(keys))
        kinds = {
            (b"base",): "knit-delta-closure",
            (b"d1",): "knit-delta-closure-ref",
            (b"d2",): "knit-delta-closure-ref",
        }
        for record in generator.get_record_stream():
            self.assertEqual(kinds[record.key], record.storage_kind)


class TestErrors(TestCase):
    def test_retry_with_new_packs(self):
        fake_exc_info = ("{exc type}", "{exc value}", "{exc traceback}")
        error = pack_repo.RetryWithNewPacks(
            "{context}", reload_occurred=False, exc_info=fake_exc_info
        )
        self.assertEqual(
            "Pack files have changed, reload and retry. context: {context} {exc value}",
            str(error),
        )
