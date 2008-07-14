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

"""Tests for Knit data structure"""

from cStringIO import StringIO
import difflib
import gzip
import sha
import sys

from bzrlib import (
    errors,
    generate_ids,
    knit,
    multiparent,
    pack,
    )
from bzrlib.errors import (
    RevisionAlreadyPresent,
    KnitHeaderError,
    RevisionNotPresent,
    NoSuchFile,
    )
from bzrlib.index import *
from bzrlib.knit import (
    AnnotatedKnitContent,
    KnitContent,
    KnitSequenceMatcher,
    KnitVersionedFiles,
    PlainKnitContent,
    _DirectPackAccess,
    _KndxIndex,
    _KnitGraphIndex,
    _KnitKeyAccess,
    make_file_factory,
    )
from bzrlib.osutils import split_lines
from bzrlib.symbol_versioning import one_four
from bzrlib.tests import (
    Feature,
    KnownFailure,
    TestCase,
    TestCaseWithMemoryTransport,
    TestCaseWithTransport,
    )
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryTransport
from bzrlib.tuned_gzip import GzipFile
from bzrlib.versionedfile import (
    AbsentContentFactory,
    ConstantMapper,
    RecordingVersionedFilesDecorator,
    )


class _CompiledKnitFeature(Feature):

    def _probe(self):
        try:
            import bzrlib._knit_load_data_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._knit_load_data_c'

CompiledKnitFeature = _CompiledKnitFeature()


class KnitContentTestsMixin(object):

    def test_constructor(self):
        content = self._make_content([])

    def test_text(self):
        content = self._make_content([])
        self.assertEqual(content.text(), [])

        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.text(), ["text1", "text2"])

    def test_copy(self):
        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        copy = content.copy()
        self.assertIsInstance(copy, content.__class__)
        self.assertEqual(copy.annotate(), content.annotate())

    def assertDerivedBlocksEqual(self, source, target, noeol=False):
        """Assert that the derived matching blocks match real output"""
        source_lines = source.splitlines(True)
        target_lines = target.splitlines(True)
        def nl(line):
            if noeol and not line.endswith('\n'):
                return line + '\n'
            else:
                return line
        source_content = self._make_content([(None, nl(l)) for l in source_lines])
        target_content = self._make_content([(None, nl(l)) for l in target_lines])
        line_delta = source_content.line_delta(target_content)
        delta_blocks = list(KnitContent.get_line_delta_blocks(line_delta,
            source_lines, target_lines))
        matcher = KnitSequenceMatcher(None, source_lines, target_lines)
        matcher_blocks = list(list(matcher.get_matching_blocks()))
        self.assertEqual(matcher_blocks, delta_blocks)

    def test_get_line_delta_blocks(self):
        self.assertDerivedBlocksEqual('a\nb\nc\n', 'q\nc\n')
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1)
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1A)
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1B)
        self.assertDerivedBlocksEqual(TEXT_1B, TEXT_1A)
        self.assertDerivedBlocksEqual(TEXT_1A, TEXT_1B)
        self.assertDerivedBlocksEqual(TEXT_1A, '')
        self.assertDerivedBlocksEqual('', TEXT_1A)
        self.assertDerivedBlocksEqual('', '')
        self.assertDerivedBlocksEqual('a\nb\nc', 'a\nb\nc\nd')

    def test_get_line_delta_blocks_noeol(self):
        """Handle historical knit deltas safely

        Some existing knit deltas don't consider the last line to differ
        when the only difference whether it has a final newline.

        New knit deltas appear to always consider the last line to differ
        in this case.
        """
        self.assertDerivedBlocksEqual('a\nb\nc', 'a\nb\nc\nd\n', noeol=True)
        self.assertDerivedBlocksEqual('a\nb\nc\nd\n', 'a\nb\nc', noeol=True)
        self.assertDerivedBlocksEqual('a\nb\nc\n', 'a\nb\nc', noeol=True)
        self.assertDerivedBlocksEqual('a\nb\nc', 'a\nb\nc\n', noeol=True)


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
        return PlainKnitContent(annotated_content.text(), 'bogus')

    def test_annotate(self):
        content = self._make_content([])
        self.assertEqual(content.annotate(), [])

        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.annotate(),
            [("bogus", "text1"), ("bogus", "text2")])

    def test_line_delta(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        self.assertEqual(content1.line_delta(content2),
            [(1, 2, 2, ["a", "c"])])

    def test_line_delta_iter(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        it = content1.line_delta_iter(content2)
        self.assertEqual(it.next(), (1, 2, 2, ["a", "c"]))
        self.assertRaises(StopIteration, it.next)


class TestAnnotatedKnitContent(TestCase, KnitContentTestsMixin):

    def _make_content(self, lines):
        return AnnotatedKnitContent(lines)

    def test_annotate(self):
        content = self._make_content([])
        self.assertEqual(content.annotate(), [])

        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.annotate(),
            [("origin1", "text1"), ("origin2", "text2")])

    def test_line_delta(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        self.assertEqual(content1.line_delta(content2),
            [(1, 2, 2, [("", "a"), ("", "c")])])

    def test_line_delta_iter(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        it = content1.line_delta_iter(content2)
        self.assertEqual(it.next(), (1, 2, 2, [("", "a"), ("", "c")]))
        self.assertRaises(StopIteration, it.next)


class MockTransport(object):

    def __init__(self, file_lines=None):
        self.file_lines = file_lines
        self.calls = []
        # We have no base directory for the MockTransport
        self.base = ''

    def get(self, filename):
        if self.file_lines is None:
            raise NoSuchFile(filename)
        else:
            return StringIO("\n".join(self.file_lines))

    def readv(self, relpath, offsets):
        fp = self.get(relpath)
        for offset, size in offsets:
            fp.seek(offset)
            yield offset, fp.read(size)

    def __getattr__(self, name):
        def queue_call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return queue_call


class KnitRecordAccessTestsMixin(object):
    """Tests for getting and putting knit records."""

    def test_add_raw_records(self):
        """Add_raw_records adds records retrievable later."""
        access = self.get_access()
        memos = access.add_raw_records([('key', 10)], '1234567890')
        self.assertEqual(['1234567890'], list(access.get_raw_records(memos)))
 
    def test_add_several_raw_records(self):
        """add_raw_records with many records and read some back."""
        access = self.get_access()
        memos = access.add_raw_records([('key', 10), ('key2', 2), ('key3', 5)],
            '12345678901234567')
        self.assertEqual(['1234567890', '12', '34567'],
            list(access.get_raw_records(memos)))
        self.assertEqual(['1234567890'],
            list(access.get_raw_records(memos[0:1])))
        self.assertEqual(['12'],
            list(access.get_raw_records(memos[1:2])))
        self.assertEqual(['34567'],
            list(access.get_raw_records(memos[2:3])))
        self.assertEqual(['1234567890', '34567'],
            list(access.get_raw_records(memos[0:1] + memos[2:3])))


class TestKnitKnitAccess(TestCaseWithMemoryTransport, KnitRecordAccessTestsMixin):
    """Tests for the .kndx implementation."""

    def get_access(self):
        """Get a .knit style access instance."""
        mapper = ConstantMapper("foo")
        access = _KnitKeyAccess(self.get_transport(), mapper)
        return access
    

class TestPackKnitAccess(TestCaseWithMemoryTransport, KnitRecordAccessTestsMixin):
    """Tests for the pack based access."""

    def get_access(self):
        return self._get_access()[0]

    def _get_access(self, packname='packfile', index='FOO'):
        transport = self.get_transport()
        def write_data(bytes):
            transport.append_bytes(packname, bytes)
        writer = pack.ContainerWriter(write_data)
        writer.begin()
        access = _DirectPackAccess({})
        access.set_writer(writer, index, (transport, packname))
        return access, writer

    def test_read_from_several_packs(self):
        access, writer = self._get_access()
        memos = []
        memos.extend(access.add_raw_records([('key', 10)], '1234567890'))
        writer.end()
        access, writer = self._get_access('pack2', 'FOOBAR')
        memos.extend(access.add_raw_records([('key', 5)], '12345'))
        writer.end()
        access, writer = self._get_access('pack3', 'BAZ')
        memos.extend(access.add_raw_records([('key', 5)], 'alpha'))
        writer.end()
        transport = self.get_transport()
        access = _DirectPackAccess({"FOO":(transport, 'packfile'),
            "FOOBAR":(transport, 'pack2'),
            "BAZ":(transport, 'pack3')})
        self.assertEqual(['1234567890', '12345', 'alpha'],
            list(access.get_raw_records(memos)))
        self.assertEqual(['1234567890'],
            list(access.get_raw_records(memos[0:1])))
        self.assertEqual(['12345'],
            list(access.get_raw_records(memos[1:2])))
        self.assertEqual(['alpha'],
            list(access.get_raw_records(memos[2:3])))
        self.assertEqual(['1234567890', 'alpha'],
            list(access.get_raw_records(memos[0:1] + memos[2:3])))

    def test_set_writer(self):
        """The writer should be settable post construction."""
        access = _DirectPackAccess({})
        transport = self.get_transport()
        packname = 'packfile'
        index = 'foo'
        def write_data(bytes):
            transport.append_bytes(packname, bytes)
        writer = pack.ContainerWriter(write_data)
        writer.begin()
        access.set_writer(writer, index, (transport, packname))
        memos = access.add_raw_records([('key', 10)], '1234567890')
        writer.end()
        self.assertEqual(['1234567890'], list(access.get_raw_records(memos)))


class LowLevelKnitDataTests(TestCase):

    def create_gz_content(self, text):
        sio = StringIO()
        gz_file = gzip.GzipFile(mode='wb', fileobj=sio)
        gz_file.write(text)
        gz_file.close()
        return sio.getvalue()

    def test_valid_knit_data(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        gz_txt = self.create_gz_content('version rev-id-1 2 %s\n'
                                        'foo\n'
                                        'bar\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper('filename'))
        knit = KnitVersionedFiles(None, access)
        records = [(('rev-id-1',), (('rev-id-1',), 0, len(gz_txt)))]

        contents = list(knit._read_records_iter(records))
        self.assertEqual([(('rev-id-1',), ['foo\n', 'bar\n'],
            '4e48e2c9a3d2ca8a708cb0cc545700544efb5021')], contents)

        raw_contents = list(knit._read_records_iter_raw(records))
        self.assertEqual([(('rev-id-1',), gz_txt, sha1sum)], raw_contents)

    def test_not_enough_lines(self):
        sha1sum = sha.new('foo\n').hexdigest()
        # record says 2 lines data says 1
        gz_txt = self.create_gz_content('version rev-id-1 2 %s\n'
                                        'foo\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper('filename'))
        knit = KnitVersionedFiles(None, access)
        records = [(('rev-id-1',), (('rev-id-1',), 0, len(gz_txt)))]
        self.assertRaises(errors.KnitCorrupt, list,
            knit._read_records_iter(records))

        # read_records_iter_raw won't detect that sort of mismatch/corruption
        raw_contents = list(knit._read_records_iter_raw(records))
        self.assertEqual([(('rev-id-1',),  gz_txt, sha1sum)], raw_contents)

    def test_too_many_lines(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        # record says 1 lines data says 2
        gz_txt = self.create_gz_content('version rev-id-1 1 %s\n'
                                        'foo\n'
                                        'bar\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper('filename'))
        knit = KnitVersionedFiles(None, access)
        records = [(('rev-id-1',), (('rev-id-1',), 0, len(gz_txt)))]
        self.assertRaises(errors.KnitCorrupt, list,
            knit._read_records_iter(records))

        # read_records_iter_raw won't detect that sort of mismatch/corruption
        raw_contents = list(knit._read_records_iter_raw(records))
        self.assertEqual([(('rev-id-1',), gz_txt, sha1sum)], raw_contents)

    def test_mismatched_version_id(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        gz_txt = self.create_gz_content('version rev-id-1 2 %s\n'
                                        'foo\n'
                                        'bar\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper('filename'))
        knit = KnitVersionedFiles(None, access)
        # We are asking for rev-id-2, but the data is rev-id-1
        records = [(('rev-id-2',), (('rev-id-2',), 0, len(gz_txt)))]
        self.assertRaises(errors.KnitCorrupt, list,
            knit._read_records_iter(records))

        # read_records_iter_raw detects mismatches in the header
        self.assertRaises(errors.KnitCorrupt, list,
            knit._read_records_iter_raw(records))

    def test_uncompressed_data(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        txt = ('version rev-id-1 2 %s\n'
               'foo\n'
               'bar\n'
               'end rev-id-1\n'
               % (sha1sum,))
        transport = MockTransport([txt])
        access = _KnitKeyAccess(transport, ConstantMapper('filename'))
        knit = KnitVersionedFiles(None, access)
        records = [(('rev-id-1',), (('rev-id-1',), 0, len(txt)))]

        # We don't have valid gzip data ==> corrupt
        self.assertRaises(errors.KnitCorrupt, list,
            knit._read_records_iter(records))

        # read_records_iter_raw will notice the bad data
        self.assertRaises(errors.KnitCorrupt, list,
            knit._read_records_iter_raw(records))

    def test_corrupted_data(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        gz_txt = self.create_gz_content('version rev-id-1 2 %s\n'
                                        'foo\n'
                                        'bar\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        # Change 2 bytes in the middle to \xff
        gz_txt = gz_txt[:10] + '\xff\xff' + gz_txt[12:]
        transport = MockTransport([gz_txt])
        access = _KnitKeyAccess(transport, ConstantMapper('filename'))
        knit = KnitVersionedFiles(None, access)
        records = [(('rev-id-1',), (('rev-id-1',), 0, len(gz_txt)))]
        self.assertRaises(errors.KnitCorrupt, list,
            knit._read_records_iter(records))
        # read_records_iter_raw will barf on bad gz data
        self.assertRaises(errors.KnitCorrupt, list,
            knit._read_records_iter_raw(records))


class LowLevelKnitIndexTests(TestCase):

    def get_knit_index(self, transport, name, mode):
        mapper = ConstantMapper(name)
        orig = knit._load_data
        def reset():
            knit._load_data = orig
        self.addCleanup(reset)
        from bzrlib._knit_load_data_py import _load_data_py
        knit._load_data = _load_data_py
        allow_writes = lambda: 'w' in mode
        return _KndxIndex(transport, mapper, lambda:None, allow_writes, lambda:True)

    def test_create_file(self):
        transport = MockTransport()
        index = self.get_knit_index(transport, "filename", "w")
        index.keys()
        call = transport.calls.pop(0)
        # call[1][1] is a StringIO - we can't test it by simple equality.
        self.assertEqual('put_file_non_atomic', call[0])
        self.assertEqual('filename.kndx', call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(_KndxIndex.HEADER,
            call[1][1].getvalue())
        self.assertEqual({'create_parent_dir': True}, call[2])

    def test_read_utf8_version_id(self):
        unicode_revision_id = u"version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode('utf-8')
        transport = MockTransport([
            _KndxIndex.HEADER,
            '%s option 0 1 :' % (utf8_revision_id,)
            ])
        index = self.get_knit_index(transport, "filename", "r")
        # _KndxIndex is a private class, and deals in utf8 revision_ids, not
        # Unicode revision_ids.
        self.assertEqual({(utf8_revision_id,):()},
            index.get_parent_map(index.keys()))
        self.assertFalse((unicode_revision_id,) in index.keys())

    def test_read_utf8_parents(self):
        unicode_revision_id = u"version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode('utf-8')
        transport = MockTransport([
            _KndxIndex.HEADER,
            "version option 0 1 .%s :" % (utf8_revision_id,)
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual({("version",):((utf8_revision_id,),)},
            index.get_parent_map(index.keys()))

    def test_read_ignore_corrupted_lines(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "corrupted",
            "corrupted options 0 1 .b .c ",
            "version options 0 1 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(1, len(index.keys()))
        self.assertEqual(set([("version",)]), index.keys())

    def test_read_corrupted_header(self):
        transport = MockTransport(['not a bzr knit index header\n'])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertRaises(KnitHeaderError, index.keys)

    def test_read_duplicate_entries(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "parent options 0 1 :",
            "version options1 0 1 0 :",
            "version options2 1 2 .other :",
            "version options3 3 4 0 .other :"
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(2, len(index.keys()))
        # check that the index used is the first one written. (Specific
        # to KnitIndex style indices.
        self.assertEqual("1", index._dictionary_compress([("version",)]))
        self.assertEqual((("version",), 3, 4), index.get_position(("version",)))
        self.assertEqual(["options3"], index.get_options(("version",)))
        self.assertEqual({("version",):(("parent",), ("other",))},
            index.get_parent_map([("version",)]))

    def test_read_compressed_parents(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 0 :",
            "c option 0 1 1 0 :",
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual({("b",):(("a",),), ("c",):(("b",), ("a",))},
            index.get_parent_map([("b",), ("c",)]))

    def test_write_utf8_version_id(self):
        unicode_revision_id = u"version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode('utf-8')
        transport = MockTransport([
            _KndxIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")
        index.add_records([
            ((utf8_revision_id,), ["option"], ((utf8_revision_id,), 0, 1), [])])
        call = transport.calls.pop(0)
        # call[1][1] is a StringIO - we can't test it by simple equality.
        self.assertEqual('put_file_non_atomic', call[0])
        self.assertEqual('filename.kndx', call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(_KndxIndex.HEADER +
            "\n%s option 0 1  :" % (utf8_revision_id,),
            call[1][1].getvalue())
        self.assertEqual({'create_parent_dir': True}, call[2])

    def test_write_utf8_parents(self):
        unicode_revision_id = u"version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode('utf-8')
        transport = MockTransport([
            _KndxIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")
        index.add_records([
            (("version",), ["option"], (("version",), 0, 1), [(utf8_revision_id,)])])
        call = transport.calls.pop(0)
        # call[1][1] is a StringIO - we can't test it by simple equality.
        self.assertEqual('put_file_non_atomic', call[0])
        self.assertEqual('filename.kndx', call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(_KndxIndex.HEADER +
            "\nversion option 0 1 .%s :" % (utf8_revision_id,),
            call[1][1].getvalue())
        self.assertEqual({'create_parent_dir': True}, call[2])

    def test_keys(self):
        transport = MockTransport([
            _KndxIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual(set(), index.keys())

        index.add_records([(("a",), ["option"], (("a",), 0, 1), [])])
        self.assertEqual(set([("a",)]), index.keys())

        index.add_records([(("a",), ["option"], (("a",), 0, 1), [])])
        self.assertEqual(set([("a",)]), index.keys())

        index.add_records([(("b",), ["option"], (("b",), 0, 1), [])])
        self.assertEqual(set([("a",), ("b",)]), index.keys())

    def add_a_b(self, index, random_id=None):
        kwargs = {}
        if random_id is not None:
            kwargs["random_id"] = random_id
        index.add_records([
            (("a",), ["option"], (("a",), 0, 1), [("b",)]),
            (("a",), ["opt"], (("a",), 1, 2), [("c",)]),
            (("b",), ["option"], (("b",), 2, 3), [("a",)])
            ], **kwargs)

    def assertIndexIsAB(self, index):
        self.assertEqual({
            ('a',): (('c',),),
            ('b',): (('a',),),
            },
            index.get_parent_map(index.keys()))
        self.assertEqual((("a",), 1, 2), index.get_position(("a",)))
        self.assertEqual((("b",), 2, 3), index.get_position(("b",)))
        self.assertEqual(["opt"], index.get_options(("a",)))

    def test_add_versions(self):
        transport = MockTransport([
            _KndxIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.add_a_b(index)
        call = transport.calls.pop(0)
        # call[1][1] is a StringIO - we can't test it by simple equality.
        self.assertEqual('put_file_non_atomic', call[0])
        self.assertEqual('filename.kndx', call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(
            _KndxIndex.HEADER +
            "\na option 0 1 .b :"
            "\na opt 1 2 .c :"
            "\nb option 2 3 0 :",
            call[1][1].getvalue())
        self.assertEqual({'create_parent_dir': True}, call[2])
        self.assertIndexIsAB(index)

    def test_add_versions_random_id_is_accepted(self):
        transport = MockTransport([
            _KndxIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.add_a_b(index, random_id=True)

    def test_delay_create_and_add_versions(self):
        transport = MockTransport()

        index = self.get_knit_index(transport, "filename", "w")
        # dir_mode=0777)
        self.assertEqual([], transport.calls)
        self.add_a_b(index)
        #self.assertEqual(
        #[    {"dir_mode": 0777, "create_parent_dir": True, "mode": "wb"},
        #    kwargs)
        # Two calls: one during which we load the existing index (and when its
        # missing create it), then a second where we write the contents out.
        self.assertEqual(2, len(transport.calls))
        call = transport.calls.pop(0)
        self.assertEqual('put_file_non_atomic', call[0])
        self.assertEqual('filename.kndx', call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(_KndxIndex.HEADER, call[1][1].getvalue())
        self.assertEqual({'create_parent_dir': True}, call[2])
        call = transport.calls.pop(0)
        # call[1][1] is a StringIO - we can't test it by simple equality.
        self.assertEqual('put_file_non_atomic', call[0])
        self.assertEqual('filename.kndx', call[1][0])
        # With no history, _KndxIndex writes a new index:
        self.assertEqual(
            _KndxIndex.HEADER +
            "\na option 0 1 .b :"
            "\na opt 1 2 .c :"
            "\nb option 2 3 0 :",
            call[1][1].getvalue())
        self.assertEqual({'create_parent_dir': True}, call[2])

    def test_get_position(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 1 :",
            "b option 1 2 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual((("a",), 0, 1), index.get_position(("a",)))
        self.assertEqual((("b",), 1, 2), index.get_position(("b",)))

    def test_get_method(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a fulltext,unknown 0 1 :",
            "b unknown,line-delta 1 2 :",
            "c bad 3 4 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual("fulltext", index.get_method("a"))
        self.assertEqual("line-delta", index.get_method("b"))
        self.assertRaises(errors.KnitIndexUnknownMethod, index.get_method, "c")

    def test_get_options(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a opt1 0 1 :",
            "b opt2,opt3 1 2 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual(["opt1"], index.get_options("a"))
        self.assertEqual(["opt2", "opt3"], index.get_options("b"))

    def test_get_parent_map(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 1 :",
            "b option 1 2 0 .c :",
            "c option 1 2 1 0 .e :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual({
            ("a",):(),
            ("b",):(("a",), ("c",)),
            ("c",):(("b",), ("a",), ("e",)),
            }, index.get_parent_map(index.keys()))

    def test_impossible_parent(self):
        """Test we get KnitCorrupt if the parent couldn't possibly exist."""
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 4 :"  # We don't have a 4th record
            ])
        index = self.get_knit_index(transport, 'filename', 'r')
        try:
            self.assertRaises(errors.KnitCorrupt, index.keys)
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.IndexError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_corrupted_parent(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 :",
            "c option 0 1 1v :", # Can't have a parent of '1v'
            ])
        index = self.get_knit_index(transport, 'filename', 'r')
        try:
            self.assertRaises(errors.KnitCorrupt, index.keys)
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.ValueError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_corrupted_parent_in_list(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 :",
            "c option 0 1 1 v :", # Can't have a parent of 'v'
            ])
        index = self.get_knit_index(transport, 'filename', 'r')
        try:
            self.assertRaises(errors.KnitCorrupt, index.keys)
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.ValueError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_invalid_position(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 1v 1 :",
            ])
        index = self.get_knit_index(transport, 'filename', 'r')
        try:
            self.assertRaises(errors.KnitCorrupt, index.keys)
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.ValueError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_invalid_size(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 1 1v :",
            ])
        index = self.get_knit_index(transport, 'filename', 'r')
        try:
            self.assertRaises(errors.KnitCorrupt, index.keys)
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.ValueError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_short_line(self):
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 10  :",
            "b option 10 10 0", # This line isn't terminated, ignored
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(set([('a',)]), index.keys())

    def test_skip_incomplete_record(self):
        # A line with bogus data should just be skipped
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 10  :",
            "b option 10 10 0", # This line isn't terminated, ignored
            "c option 20 10 0 :", # Properly terminated, and starts with '\n'
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(set([('a',), ('c',)]), index.keys())

    def test_trailing_characters(self):
        # A line with bogus data should just be skipped
        transport = MockTransport([
            _KndxIndex.HEADER,
            "a option 0 10  :",
            "b option 10 10 0 :a", # This line has extra trailing characters
            "c option 20 10 0 :", # Properly terminated, and starts with '\n'
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(set([('a',), ('c',)]), index.keys())


class LowLevelKnitIndexTests_c(LowLevelKnitIndexTests):

    _test_needs_features = [CompiledKnitFeature]

    def get_knit_index(self, transport, name, mode):
        mapper = ConstantMapper(name)
        orig = knit._load_data
        def reset():
            knit._load_data = orig
        self.addCleanup(reset)
        from bzrlib._knit_load_data_c import _load_data_c
        knit._load_data = _load_data_c
        allow_writes = lambda: mode == 'w'
        return _KndxIndex(transport, mapper, lambda:None, allow_writes, lambda:True)


class KnitTests(TestCaseWithTransport):
    """Class containing knit test helper routines."""

    def make_test_knit(self, annotate=False, name='test'):
        mapper = ConstantMapper(name)
        return make_file_factory(annotate, mapper)(self.get_transport())


class TestKnitIndex(KnitTests):

    def test_add_versions_dictionary_compresses(self):
        """Adding versions to the index should update the lookup dict"""
        knit = self.make_test_knit()
        idx = knit._index
        idx.add_records([(('a-1',), ['fulltext'], (('a-1',), 0, 0), [])])
        self.check_file_contents('test.kndx',
            '# bzr knit index 8\n'
            '\n'
            'a-1 fulltext 0 0  :'
            )
        idx.add_records([
            (('a-2',), ['fulltext'], (('a-2',), 0, 0), [('a-1',)]),
            (('a-3',), ['fulltext'], (('a-3',), 0, 0), [('a-2',)]),
            ])
        self.check_file_contents('test.kndx',
            '# bzr knit index 8\n'
            '\n'
            'a-1 fulltext 0 0  :\n'
            'a-2 fulltext 0 0 0 :\n'
            'a-3 fulltext 0 0 1 :'
            )
        self.assertEqual(set([('a-3',), ('a-1',), ('a-2',)]), idx.keys())
        self.assertEqual({
            ('a-1',): ((('a-1',), 0, 0), None, (), ('fulltext', False)),
            ('a-2',): ((('a-2',), 0, 0), None, (('a-1',),), ('fulltext', False)),
            ('a-3',): ((('a-3',), 0, 0), None, (('a-2',),), ('fulltext', False)),
            }, idx.get_build_details(idx.keys()))
        self.assertEqual({('a-1',):(),
            ('a-2',):(('a-1',),),
            ('a-3',):(('a-2',),),},
            idx.get_parent_map(idx.keys()))

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
        idx.add_records([(('a-1',), ['fulltext'], (('a-1',), 0, 0), [])])

        class StopEarly(Exception):
            pass

        def generate_failure():
            """Add some entries and then raise an exception"""
            yield (('a-2',), ['fulltext'], (None, 0, 0), ('a-1',))
            yield (('a-3',), ['fulltext'], (None, 0, 0), ('a-2',))
            raise StopEarly()

        # Assert the pre-condition
        def assertA1Only():
            self.assertEqual(set([('a-1',)]), set(idx.keys()))
            self.assertEqual(
                {('a-1',): ((('a-1',), 0, 0), None, (), ('fulltext', False))},
                idx.get_build_details([('a-1',)]))
            self.assertEqual({('a-1',):()}, idx.get_parent_map(idx.keys()))

        assertA1Only()
        self.assertRaises(StopEarly, idx.add_records, generate_failure())
        # And it shouldn't be modified
        assertA1Only()

    def test_knit_index_ignores_empty_files(self):
        # There was a race condition in older bzr, where a ^C at the right time
        # could leave an empty .kndx file, which bzr would later claim was a
        # corrupted file since the header was not present. In reality, the file
        # just wasn't created, so it should be ignored.
        t = get_transport('.')
        t.put_bytes('test.kndx', '')

        knit = self.make_test_knit()

    def test_knit_index_checks_header(self):
        t = get_transport('.')
        t.put_bytes('test.kndx', '# not really a knit header\n\n')
        k = self.make_test_knit()
        self.assertRaises(KnitHeaderError, k.keys)


class TestGraphIndexKnit(KnitTests):
    """Tests for knits using a GraphIndex rather than a KnitIndex."""

    def make_g_index(self, name, ref_lists=0, nodes=[]):
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
            index1 = self.make_g_index('1', 2, [
                (('tip', ), 'N0 100', ([('parent', )], [], )),
                (('tail', ), '', ([], []))])
            index2 = self.make_g_index('2', 2, [
                (('parent', ), ' 100 78', ([('tail', ), ('ghost', )], [('tail', )])),
                (('separate', ), '', ([], []))])
        else:
            # just blob location and graph in the index.
            index1 = self.make_g_index('1', 1, [
                (('tip', ), 'N0 100', ([('parent', )], )),
                (('tail', ), '', ([], ))])
            index2 = self.make_g_index('2', 1, [
                (('parent', ), ' 100 78', ([('tail', ), ('ghost', )], )),
                (('separate', ), '', ([], ))])
        combined_index = CombinedGraphIndex([index1, index2])
        if catch_adds:
            self.combined_index = combined_index
            self.caught_entries = []
            add_callback = self.catch_add
        else:
            add_callback = None
        return _KnitGraphIndex(combined_index, lambda:True, deltas=deltas,
            add_callback=add_callback)

    def test_keys(self):
        index = self.two_graph_index()
        self.assertEqual(set([('tail',), ('tip',), ('parent',), ('separate',)]),
            set(index.keys()))

    def test_get_position(self):
        index = self.two_graph_index()
        self.assertEqual((index._graph_index._indices[0], 0, 100), index.get_position(('tip',)))
        self.assertEqual((index._graph_index._indices[1], 100, 78), index.get_position(('parent',)))

    def test_get_method_deltas(self):
        index = self.two_graph_index(deltas=True)
        self.assertEqual('fulltext', index.get_method(('tip',)))
        self.assertEqual('line-delta', index.get_method(('parent',)))

    def test_get_method_no_deltas(self):
        # check that the parent-history lookup is ignored with deltas=False.
        index = self.two_graph_index(deltas=False)
        self.assertEqual('fulltext', index.get_method(('tip',)))
        self.assertEqual('fulltext', index.get_method(('parent',)))

    def test_get_options_deltas(self):
        index = self.two_graph_index(deltas=True)
        self.assertEqual(['fulltext', 'no-eol'], index.get_options(('tip',)))
        self.assertEqual(['line-delta'], index.get_options(('parent',)))

    def test_get_options_no_deltas(self):
        # check that the parent-history lookup is ignored with deltas=False.
        index = self.two_graph_index(deltas=False)
        self.assertEqual(['fulltext', 'no-eol'], index.get_options(('tip',)))
        self.assertEqual(['fulltext'], index.get_options(('parent',)))

    def test_get_parent_map(self):
        index = self.two_graph_index()
        self.assertEqual({('parent',):(('tail',), ('ghost',))},
            index.get_parent_map([('parent',), ('ghost',)]))

    def catch_add(self, entries):
        self.caught_entries.append(entries)

    def test_add_no_callback_errors(self):
        index = self.two_graph_index()
        self.assertRaises(errors.ReadOnlyError, index.add_records,
            [(('new',), 'fulltext,no-eol', (None, 50, 60), ['separate'])])

    def test_add_version_smoke(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([(('new',), 'fulltext,no-eol', (None, 50, 60),
            [('separate',)])])
        self.assertEqual([[(('new', ), 'N50 60', ((('separate',),),))]],
            self.caught_entries)

    def test_add_version_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('new',), 'no-eol,line-delta', (None, 0, 100), [('parent',)])])
        self.assertEqual([], self.caught_entries)

    def test_add_version_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 0, 100), [('parent',)])])
        index.add_records([(('tip',), 'no-eol,fulltext', (None, 0, 100), [('parent',)])])
        # position/length are ignored (because each pack could have fulltext or
        # delta, and be at a different position.
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 50, 100),
            [('parent',)])])
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 0, 1000),
            [('parent',)])])
        # but neither should have added data:
        self.assertEqual([[], [], [], []], self.caught_entries)
        
    def test_add_version_different_dup(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        # change options
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'no-eol,line-delta', (None, 0, 100), [('parent',)])])
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'line-delta,no-eol', (None, 0, 100), [('parent',)])])
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext', (None, 0, 100), [('parent',)])])
        # parents
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext,no-eol', (None, 0, 100), [])])
        self.assertEqual([], self.caught_entries)
        
    def test_add_versions_nodeltas(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([
                (('new',), 'fulltext,no-eol', (None, 50, 60), [('separate',)]),
                (('new2',), 'fulltext', (None, 0, 6), [('new',)]),
                ])
        self.assertEqual([(('new', ), 'N50 60', ((('separate',),),)),
            (('new2', ), ' 0 6', ((('new',),),))],
            sorted(self.caught_entries[0]))
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_deltas(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        index.add_records([
                (('new',), 'fulltext,no-eol', (None, 50, 60), [('separate',)]),
                (('new2',), 'line-delta', (None, 0, 6), [('new',)]),
                ])
        self.assertEqual([(('new', ), 'N50 60', ((('separate',),), ())),
            (('new2', ), ' 0 6', ((('new',),), (('new',),), ))],
            sorted(self.caught_entries[0]))
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('new',), 'no-eol,line-delta', (None, 0, 100), [('parent',)])])
        self.assertEqual([], self.caught_entries)

    def test_add_versions_random_id_accepted(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([], random_id=True)

    def test_add_versions_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 0, 100),
            [('parent',)])])
        index.add_records([(('tip',), 'no-eol,fulltext', (None, 0, 100),
            [('parent',)])])
        # position/length are ignored (because each pack could have fulltext or
        # delta, and be at a different position.
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 50, 100),
            [('parent',)])])
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 0, 1000),
            [('parent',)])])
        # but neither should have added data.
        self.assertEqual([[], [], [], []], self.caught_entries)
        
    def test_add_versions_different_dup(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        # change options
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'no-eol,line-delta', (None, 0, 100), [('parent',)])])
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'line-delta,no-eol', (None, 0, 100), [('parent',)])])
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext', (None, 0, 100), [('parent',)])])
        # parents
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext,no-eol', (None, 0, 100), [])])
        # change options in the second record
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext,no-eol', (None, 0, 100), [('parent',)]),
             (('tip',), 'no-eol,line-delta', (None, 0, 100), [('parent',)])])
        self.assertEqual([], self.caught_entries)


class TestNoParentsGraphIndexKnit(KnitTests):
    """Tests for knits using _KnitGraphIndex with no parents."""

    def make_g_index(self, name, ref_lists=0, nodes=[]):
        builder = GraphIndexBuilder(ref_lists)
        for node, references in nodes:
            builder.add_node(node, references)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return GraphIndex(trans, name, size)

    def test_parents_deltas_incompatible(self):
        index = CombinedGraphIndex([])
        self.assertRaises(errors.KnitError, _KnitGraphIndex, lambda:True,
            index, deltas=True, parents=False)

    def two_graph_index(self, catch_adds=False):
        """Build a two-graph index.

        :param deltas: If true, use underlying indices with two node-ref
            lists and 'parent' set to a delta-compressed against tail.
        """
        # put several versions in the index.
        index1 = self.make_g_index('1', 0, [
            (('tip', ), 'N0 100'),
            (('tail', ), '')])
        index2 = self.make_g_index('2', 0, [
            (('parent', ), ' 100 78'),
            (('separate', ), '')])
        combined_index = CombinedGraphIndex([index1, index2])
        if catch_adds:
            self.combined_index = combined_index
            self.caught_entries = []
            add_callback = self.catch_add
        else:
            add_callback = None
        return _KnitGraphIndex(combined_index, lambda:True, parents=False,
            add_callback=add_callback)

    def test_keys(self):
        index = self.two_graph_index()
        self.assertEqual(set([('tail',), ('tip',), ('parent',), ('separate',)]),
            set(index.keys()))

    def test_get_position(self):
        index = self.two_graph_index()
        self.assertEqual((index._graph_index._indices[0], 0, 100),
            index.get_position(('tip',)))
        self.assertEqual((index._graph_index._indices[1], 100, 78),
            index.get_position(('parent',)))

    def test_get_method(self):
        index = self.two_graph_index()
        self.assertEqual('fulltext', index.get_method(('tip',)))
        self.assertEqual(['fulltext'], index.get_options(('parent',)))

    def test_get_options(self):
        index = self.two_graph_index()
        self.assertEqual(['fulltext', 'no-eol'], index.get_options(('tip',)))
        self.assertEqual(['fulltext'], index.get_options(('parent',)))

    def test_get_parent_map(self):
        index = self.two_graph_index()
        self.assertEqual({('parent',):None},
            index.get_parent_map([('parent',), ('ghost',)]))

    def catch_add(self, entries):
        self.caught_entries.append(entries)

    def test_add_no_callback_errors(self):
        index = self.two_graph_index()
        self.assertRaises(errors.ReadOnlyError, index.add_records,
            [(('new',), 'fulltext,no-eol', (None, 50, 60), [('separate',)])])

    def test_add_version_smoke(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([(('new',), 'fulltext,no-eol', (None, 50, 60), [])])
        self.assertEqual([[(('new', ), 'N50 60')]],
            self.caught_entries)

    def test_add_version_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('new',), 'no-eol,line-delta', (None, 0, 100), [])])
        self.assertEqual([], self.caught_entries)

    def test_add_version_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 0, 100), [])])
        index.add_records([(('tip',), 'no-eol,fulltext', (None, 0, 100), [])])
        # position/length are ignored (because each pack could have fulltext or
        # delta, and be at a different position.
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 50, 100), [])])
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 0, 1000), [])])
        # but neither should have added data.
        self.assertEqual([[], [], [], []], self.caught_entries)
        
    def test_add_version_different_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # change options
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'no-eol,line-delta', (None, 0, 100), [])])
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'line-delta,no-eol', (None, 0, 100), [])])
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext', (None, 0, 100), [])])
        # parents
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext,no-eol', (None, 0, 100), [('parent',)])])
        self.assertEqual([], self.caught_entries)
        
    def test_add_versions(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([
                (('new',), 'fulltext,no-eol', (None, 50, 60), []),
                (('new2',), 'fulltext', (None, 0, 6), []),
                ])
        self.assertEqual([(('new', ), 'N50 60'), (('new2', ), ' 0 6')],
            sorted(self.caught_entries[0]))
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('new',), 'no-eol,line-delta', (None, 0, 100), [('parent',)])])
        self.assertEqual([], self.caught_entries)

    def test_add_versions_parents_not_parents_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('new',), 'no-eol,fulltext', (None, 0, 100), [('parent',)])])
        self.assertEqual([], self.caught_entries)

    def test_add_versions_random_id_accepted(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_records([], random_id=True)

    def test_add_versions_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 0, 100), [])])
        index.add_records([(('tip',), 'no-eol,fulltext', (None, 0, 100), [])])
        # position/length are ignored (because each pack could have fulltext or
        # delta, and be at a different position.
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 50, 100), [])])
        index.add_records([(('tip',), 'fulltext,no-eol', (None, 0, 1000), [])])
        # but neither should have added data.
        self.assertEqual([[], [], [], []], self.caught_entries)
        
    def test_add_versions_different_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # change options
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'no-eol,line-delta', (None, 0, 100), [])])
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'line-delta,no-eol', (None, 0, 100), [])])
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext', (None, 0, 100), [])])
        # parents
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext,no-eol', (None, 0, 100), [('parent',)])])
        # change options in the second record
        self.assertRaises(errors.KnitCorrupt, index.add_records,
            [(('tip',), 'fulltext,no-eol', (None, 0, 100), []),
             (('tip',), 'no-eol,line-delta', (None, 0, 100), [])])
        self.assertEqual([], self.caught_entries)


class TestStacking(KnitTests):

    def get_basis_and_test_knit(self):
        basis = self.make_test_knit(name='basis')
        basis = RecordingVersionedFilesDecorator(basis)
        test = self.make_test_knit(name='test')
        test.add_fallback_versioned_files(basis)
        return basis, test

    def test_add_fallback_versioned_files(self):
        basis = self.make_test_knit(name='basis')
        test = self.make_test_knit(name='test')
        # It must not error; other tests test that the fallback is referred to
        # when accessing data.
        test.add_fallback_versioned_files(basis)

    def test_add_lines(self):
        # lines added to the test are not added to the basis
        basis, test = self.get_basis_and_test_knit()
        key = ('foo',)
        key_basis = ('bar',)
        key_cross_border = ('quux',)
        key_delta = ('zaphod',)
        test.add_lines(key, (), ['foo\n'])
        self.assertEqual({}, basis.get_parent_map([key]))
        # lines added to the test that reference across the stack do a
        # fulltext.
        basis.add_lines(key_basis, (), ['foo\n'])
        basis.calls = []
        test.add_lines(key_cross_border, (key_basis,), ['foo\n'])
        self.assertEqual('fulltext', test._index.get_method(key_cross_border))
        self.assertEqual([("get_parent_map", set([key_basis]))], basis.calls)
        # Subsequent adds do delta.
        basis.calls = []
        test.add_lines(key_delta, (key_cross_border,), ['foo\n'])
        self.assertEqual('line-delta', test._index.get_method(key_delta))
        self.assertEqual([], basis.calls)

    def test_annotate(self):
        # annotations from the test knit are answered without asking the basis
        basis, test = self.get_basis_and_test_knit()
        key = ('foo',)
        key_basis = ('bar',)
        key_missing = ('missing',)
        test.add_lines(key, (), ['foo\n'])
        details = test.annotate(key)
        self.assertEqual([(key, 'foo\n')], details)
        self.assertEqual([], basis.calls)
        # But texts that are not in the test knit are looked for in the basis
        # directly.
        basis.add_lines(key_basis, (), ['foo\n', 'bar\n'])
        basis.calls = []
        details = test.annotate(key_basis)
        self.assertEqual([(key_basis, 'foo\n'), (key_basis, 'bar\n')], details)
        # Not optimised to date:
        # self.assertEqual([("annotate", key_basis)], basis.calls)
        self.assertEqual([('get_parent_map', set([key_basis])),
            ('get_parent_map', set([key_basis])),
            ('get_parent_map', set([key_basis])),
            ('get_record_stream', [key_basis], 'unordered', True)],
            basis.calls)

    def test_check(self):
        # At the moment checking a stacked knit does implicitly check the
        # fallback files.  
        basis, test = self.get_basis_and_test_knit()
        test.check()

    def test_get_parent_map(self):
        # parents in the test knit are answered without asking the basis
        basis, test = self.get_basis_and_test_knit()
        key = ('foo',)
        key_basis = ('bar',)
        key_missing = ('missing',)
        test.add_lines(key, (), [])
        parent_map = test.get_parent_map([key])
        self.assertEqual({key: ()}, parent_map)
        self.assertEqual([], basis.calls)
        # But parents that are not in the test knit are looked for in the basis
        basis.add_lines(key_basis, (), [])
        basis.calls = []
        parent_map = test.get_parent_map([key, key_basis, key_missing])
        self.assertEqual({key: (),
            key_basis: ()}, parent_map)
        self.assertEqual([("get_parent_map", set([key_basis, key_missing]))],
            basis.calls)

    def test_get_record_stream_unordered_fulltexts(self):
        # records from the test knit are answered without asking the basis:
        basis, test = self.get_basis_and_test_knit()
        key = ('foo',)
        key_basis = ('bar',)
        key_missing = ('missing',)
        test.add_lines(key, (), ['foo\n'])
        records = list(test.get_record_stream([key], 'unordered', True))
        self.assertEqual(1, len(records))
        self.assertEqual([], basis.calls)
        # Missing (from test knit) objects are retrieved from the basis:
        basis.add_lines(key_basis, (), ['foo\n', 'bar\n'])
        basis.calls = []
        records = list(test.get_record_stream([key_basis, key_missing],
            'unordered', True))
        self.assertEqual(2, len(records))
        calls = list(basis.calls)
        for record in records:
            self.assertSubset([record.key], (key_basis, key_missing))
            if record.key == key_missing:
                self.assertIsInstance(record, AbsentContentFactory)
            else:
                reference = list(basis.get_record_stream([key_basis],
                    'unordered', True))[0]
                self.assertEqual(reference.key, record.key)
                self.assertEqual(reference.sha1, record.sha1)
                self.assertEqual(reference.storage_kind, record.storage_kind)
                self.assertEqual(reference.get_bytes_as(reference.storage_kind),
                    record.get_bytes_as(record.storage_kind))
                self.assertEqual(reference.get_bytes_as('fulltext'),
                    record.get_bytes_as('fulltext'))
        # It's not strictly minimal, but it seems reasonable for now for it to
        # ask which fallbacks have which parents.
        self.assertEqual([
            ("get_parent_map", set([key_basis, key_missing])),
            ("get_record_stream", [key_basis], 'unordered', True)],
            calls)

    def test_get_record_stream_ordered_fulltexts(self):
        # ordering is preserved down into the fallback store.
        basis, test = self.get_basis_and_test_knit()
        key = ('foo',)
        key_basis = ('bar',)
        key_basis_2 = ('quux',)
        key_missing = ('missing',)
        test.add_lines(key, (key_basis,), ['foo\n'])
        # Missing (from test knit) objects are retrieved from the basis:
        basis.add_lines(key_basis, (key_basis_2,), ['foo\n', 'bar\n'])
        basis.add_lines(key_basis_2, (), ['quux\n'])
        basis.calls = []
        # ask for in non-topological order
        records = list(test.get_record_stream(
            [key, key_basis, key_missing, key_basis_2], 'topological', True))
        self.assertEqual(4, len(records))
        results = []
        for record in records:
            self.assertSubset([record.key],
                (key_basis, key_missing, key_basis_2, key))
            if record.key == key_missing:
                self.assertIsInstance(record, AbsentContentFactory)
            else:
                results.append((record.key, record.sha1, record.storage_kind,
                    record.get_bytes_as('fulltext')))
        calls = list(basis.calls)
        order = [record[0] for record in results]
        self.assertEqual([key_basis_2, key_basis, key], order)
        for result in results:
            if result[0] == key:
                source = test
            else:
                source = basis
            record = source.get_record_stream([result[0]], 'unordered',
                True).next()
            self.assertEqual(record.key, result[0])
            self.assertEqual(record.sha1, result[1])
            self.assertEqual(record.storage_kind, result[2])
            self.assertEqual(record.get_bytes_as('fulltext'), result[3])
        # It's not strictly minimal, but it seems reasonable for now for it to
        # ask which fallbacks have which parents.
        self.assertEqual([
            ("get_parent_map", set([key_basis, key_basis_2, key_missing])),
            # unordered is asked for by the underlying worker as it still
            # buffers everything while answering - which is a problem!
            ("get_record_stream", [key_basis_2, key_basis], 'unordered', True)],
            calls)

    def test_get_record_stream_unordered_deltas(self):
        # records from the test knit are answered without asking the basis:
        basis, test = self.get_basis_and_test_knit()
        key = ('foo',)
        key_basis = ('bar',)
        key_missing = ('missing',)
        test.add_lines(key, (), ['foo\n'])
        records = list(test.get_record_stream([key], 'unordered', False))
        self.assertEqual(1, len(records))
        self.assertEqual([], basis.calls)
        # Missing (from test knit) objects are retrieved from the basis:
        basis.add_lines(key_basis, (), ['foo\n', 'bar\n'])
        basis.calls = []
        records = list(test.get_record_stream([key_basis, key_missing],
            'unordered', False))
        self.assertEqual(2, len(records))
        calls = list(basis.calls)
        for record in records:
            self.assertSubset([record.key], (key_basis, key_missing))
            if record.key == key_missing:
                self.assertIsInstance(record, AbsentContentFactory)
            else:
                reference = list(basis.get_record_stream([key_basis],
                    'unordered', False))[0]
                self.assertEqual(reference.key, record.key)
                self.assertEqual(reference.sha1, record.sha1)
                self.assertEqual(reference.storage_kind, record.storage_kind)
                self.assertEqual(reference.get_bytes_as(reference.storage_kind),
                    record.get_bytes_as(record.storage_kind))
        # It's not strictly minimal, but it seems reasonable for now for it to
        # ask which fallbacks have which parents.
        self.assertEqual([
            ("get_parent_map", set([key_basis, key_missing])),
            ("get_record_stream", [key_basis], 'unordered', False)],
            calls)

    def test_get_record_stream_ordered_deltas(self):
        # ordering is preserved down into the fallback store.
        basis, test = self.get_basis_and_test_knit()
        key = ('foo',)
        key_basis = ('bar',)
        key_basis_2 = ('quux',)
        key_missing = ('missing',)
        test.add_lines(key, (key_basis,), ['foo\n'])
        # Missing (from test knit) objects are retrieved from the basis:
        basis.add_lines(key_basis, (key_basis_2,), ['foo\n', 'bar\n'])
        basis.add_lines(key_basis_2, (), ['quux\n'])
        basis.calls = []
        # ask for in non-topological order
        records = list(test.get_record_stream(
            [key, key_basis, key_missing, key_basis_2], 'topological', False))
        self.assertEqual(4, len(records))
        results = []
        for record in records:
            self.assertSubset([record.key],
                (key_basis, key_missing, key_basis_2, key))
            if record.key == key_missing:
                self.assertIsInstance(record, AbsentContentFactory)
            else:
                results.append((record.key, record.sha1, record.storage_kind,
                    record.get_bytes_as(record.storage_kind)))
        calls = list(basis.calls)
        order = [record[0] for record in results]
        self.assertEqual([key_basis_2, key_basis, key], order)
        for result in results:
            if result[0] == key:
                source = test
            else:
                source = basis
            record = source.get_record_stream([result[0]], 'unordered',
                False).next()
            self.assertEqual(record.key, result[0])
            self.assertEqual(record.sha1, result[1])
            self.assertEqual(record.storage_kind, result[2])
            self.assertEqual(record.get_bytes_as(record.storage_kind), result[3])
        # It's not strictly minimal, but it seems reasonable for now for it to
        # ask which fallbacks have which parents.
        self.assertEqual([
            ("get_parent_map", set([key_basis, key_basis_2, key_missing])),
            ("get_record_stream", [key_basis_2, key_basis], 'topological', False)],
            calls)

    def test_get_sha1s(self):
        # sha1's in the test knit are answered without asking the basis
        basis, test = self.get_basis_and_test_knit()
        key = ('foo',)
        key_basis = ('bar',)
        key_missing = ('missing',)
        test.add_lines(key, (), ['foo\n'])
        key_sha1sum = sha.new('foo\n').hexdigest()
        sha1s = test.get_sha1s([key])
        self.assertEqual({key: key_sha1sum}, sha1s)
        self.assertEqual([], basis.calls)
        # But texts that are not in the test knit are looked for in the basis
        # directly (rather than via text reconstruction) so that remote servers
        # etc don't have to answer with full content.
        basis.add_lines(key_basis, (), ['foo\n', 'bar\n'])
        basis_sha1sum = sha.new('foo\nbar\n').hexdigest()
        basis.calls = []
        sha1s = test.get_sha1s([key, key_missing, key_basis])
        self.assertEqual({key: key_sha1sum,
            key_basis: basis_sha1sum}, sha1s)
        self.assertEqual([("get_sha1s", set([key_basis, key_missing]))],
            basis.calls)

    def test_insert_record_stream(self):
        # records are inserted as normal; insert_record_stream builds on
        # add_lines, so a smoke test should be all that's needed:
        key = ('foo',)
        key_basis = ('bar',)
        key_delta = ('zaphod',)
        basis, test = self.get_basis_and_test_knit()
        source = self.make_test_knit(name='source')
        basis.add_lines(key_basis, (), ['foo\n'])
        basis.calls = []
        source.add_lines(key_basis, (), ['foo\n'])
        source.add_lines(key_delta, (key_basis,), ['bar\n'])
        stream = source.get_record_stream([key_delta], 'unordered', False)
        test.insert_record_stream(stream)
        self.assertEqual([("get_parent_map", set([key_basis]))],
            basis.calls)
        self.assertEqual({key_delta:(key_basis,)},
            test.get_parent_map([key_delta]))
        self.assertEqual('bar\n', test.get_record_stream([key_delta],
            'unordered', True).next().get_bytes_as('fulltext'))

    def test_iter_lines_added_or_present_in_keys(self):
        # Lines from the basis are returned, and lines for a given key are only
        # returned once. 
        key1 = ('foo1',)
        key2 = ('foo2',)
        # all sources are asked for keys:
        basis, test = self.get_basis_and_test_knit()
        basis.add_lines(key1, (), ["foo"])
        basis.calls = []
        lines = list(test.iter_lines_added_or_present_in_keys([key1]))
        self.assertEqual([("foo\n", key1)], lines)
        self.assertEqual([("iter_lines_added_or_present_in_keys", set([key1]))],
            basis.calls)
        # keys in both are not duplicated:
        test.add_lines(key2, (), ["bar\n"])
        basis.add_lines(key2, (), ["bar\n"])
        basis.calls = []
        lines = list(test.iter_lines_added_or_present_in_keys([key2]))
        self.assertEqual([("bar\n", key2)], lines)
        self.assertEqual([], basis.calls)

    def test_keys(self):
        key1 = ('foo1',)
        key2 = ('foo2',)
        # all sources are asked for keys:
        basis, test = self.get_basis_and_test_knit()
        keys = test.keys()
        self.assertEqual(set(), set(keys))
        self.assertEqual([("keys",)], basis.calls)
        # keys from a basis are returned:
        basis.add_lines(key1, (), [])
        basis.calls = []
        keys = test.keys()
        self.assertEqual(set([key1]), set(keys))
        self.assertEqual([("keys",)], basis.calls)
        # keys in both are not duplicated:
        test.add_lines(key2, (), [])
        basis.add_lines(key2, (), [])
        basis.calls = []
        keys = test.keys()
        self.assertEqual(2, len(keys))
        self.assertEqual(set([key1, key2]), set(keys))
        self.assertEqual([("keys",)], basis.calls)

    def test_add_mpdiffs(self):
        # records are inserted as normal; add_mpdiff builds on
        # add_lines, so a smoke test should be all that's needed:
        key = ('foo',)
        key_basis = ('bar',)
        key_delta = ('zaphod',)
        basis, test = self.get_basis_and_test_knit()
        source = self.make_test_knit(name='source')
        basis.add_lines(key_basis, (), ['foo\n'])
        basis.calls = []
        source.add_lines(key_basis, (), ['foo\n'])
        source.add_lines(key_delta, (key_basis,), ['bar\n'])
        diffs = source.make_mpdiffs([key_delta])
        test.add_mpdiffs([(key_delta, (key_basis,),
            source.get_sha1s([key_delta])[key_delta], diffs[0])])
        self.assertEqual([("get_parent_map", set([key_basis])),
            ('get_record_stream', [key_basis], 'unordered', True),
            ('get_parent_map', set([key_basis]))],
            basis.calls)
        self.assertEqual({key_delta:(key_basis,)},
            test.get_parent_map([key_delta]))
        self.assertEqual('bar\n', test.get_record_stream([key_delta],
            'unordered', True).next().get_bytes_as('fulltext'))

    def test_make_mpdiffs(self):
        # Generating an mpdiff across a stacking boundary should detect parent
        # texts regions.
        key = ('foo',)
        key_left = ('bar',)
        key_right = ('zaphod',)
        basis, test = self.get_basis_and_test_knit()
        basis.add_lines(key_left, (), ['bar\n'])
        basis.add_lines(key_right, (), ['zaphod\n'])
        basis.calls = []
        test.add_lines(key, (key_left, key_right),
            ['bar\n', 'foo\n', 'zaphod\n'])
        diffs = test.make_mpdiffs([key])
        self.assertEqual([
            multiparent.MultiParent([multiparent.ParentText(0, 0, 0, 1),
                multiparent.NewText(['foo\n']),
                multiparent.ParentText(1, 0, 2, 1)])],
            diffs)
        self.assertEqual(4, len(basis.calls))
        self.assertEqual([
            ("get_parent_map", set([key_left, key_right])),
            ("get_parent_map", set([key_left, key_right])),
            ("get_parent_map", set([key_left, key_right])),
            ],
            basis.calls[:3])
        last_call = basis.calls[3]
        self.assertEqual('get_record_stream', last_call[0])
        self.assertEqual(set([key_left, key_right]), set(last_call[1]))
        self.assertEqual('unordered', last_call[2])
        self.assertEqual(True, last_call[3])
