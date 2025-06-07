# Copyright (C) 2007, 2009, 2011, 2012, 2016 Canonical Ltd
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

"""Tests for breezy.pack."""

from io import BytesIO

from breezy import tests

from .. import pack


class TestContainerSerialiser(tests.TestCase):
    """Tests for the ContainerSerialiser class."""

    def test_construct(self):
        """Test constructing a ContainerSerialiser."""
        pack.ContainerSerialiser()

    def test_begin(self):
        serialiser = pack.ContainerSerialiser()
        self.assertEqual(
            b"Bazaar pack format 1 (introduced in 0.18)\n", serialiser.begin()
        )

    def test_end(self):
        serialiser = pack.ContainerSerialiser()
        self.assertEqual(b"E", serialiser.end())

    def test_bytes_record_no_name(self):
        serialiser = pack.ContainerSerialiser()
        record = serialiser.bytes_record(b"bytes", [])
        self.assertEqual(b"B5\n\nbytes", record)

    def test_bytes_record_one_name_with_one_part(self):
        serialiser = pack.ContainerSerialiser()
        record = serialiser.bytes_record(b"bytes", [(b"name",)])
        self.assertEqual(b"B5\nname\n\nbytes", record)

    def test_bytes_record_one_name_with_two_parts(self):
        serialiser = pack.ContainerSerialiser()
        record = serialiser.bytes_record(b"bytes", [(b"part1", b"part2")])
        self.assertEqual(b"B5\npart1\x00part2\n\nbytes", record)

    def test_bytes_record_two_names(self):
        serialiser = pack.ContainerSerialiser()
        record = serialiser.bytes_record(b"bytes", [(b"name1",), (b"name2",)])
        self.assertEqual(b"B5\nname1\nname2\n\nbytes", record)

    def test_bytes_record_whitespace_in_name_part(self):
        serialiser = pack.ContainerSerialiser()
        self.assertRaises(
            pack.InvalidRecordError, serialiser.bytes_record, b"bytes", [(b"bad name",)]
        )

    def test_bytes_record_header(self):
        serialiser = pack.ContainerSerialiser()
        record = serialiser.bytes_header(32, [(b"name1",), (b"name2",)])
        self.assertEqual(b"B32\nname1\nname2\n\n", record)


class TestContainerWriter(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.output = BytesIO()
        self.writer = pack.ContainerWriter(self.output.write)

    def assertOutput(self, expected_output):
        """Assert that the output of self.writer ContainerWriter is equal to
        expected_output.
        """
        self.assertEqual(expected_output, self.output.getvalue())

    def test_construct(self):
        """Test constructing a ContainerWriter.

        This uses None as the output stream to show that the constructor
        doesn't try to use the output stream.
        """
        pack.ContainerWriter(None)

    def test_begin(self):
        """The begin() method writes the container format marker line."""
        self.writer.begin()
        self.assertOutput(b"Bazaar pack format 1 (introduced in 0.18)\n")

    def test_zero_records_written_after_begin(self):
        """After begin is written, 0 records have been written."""
        self.writer.begin()
        self.assertEqual(0, self.writer.records_written)

    def test_end(self):
        """The end() method writes an End Marker record."""
        self.writer.begin()
        self.writer.end()
        self.assertOutput(b"Bazaar pack format 1 (introduced in 0.18)\nE")

    def test_empty_end_does_not_add_a_record_to_records_written(self):
        """The end() method does not count towards the records written."""
        self.writer.begin()
        self.writer.end()
        self.assertEqual(0, self.writer.records_written)

    def test_non_empty_end_does_not_add_a_record_to_records_written(self):
        """The end() method does not count towards the records written."""
        self.writer.begin()
        self.writer.add_bytes_record([b"foo"], len(b"foo"), names=[])
        self.writer.end()
        self.assertEqual(1, self.writer.records_written)

    def test_add_bytes_record_no_name(self):
        """Add a bytes record with no name."""
        self.writer.begin()
        offset, length = self.writer.add_bytes_record([b"abc"], len(b"abc"), names=[])
        self.assertEqual((42, 7), (offset, length))
        self.assertOutput(b"Bazaar pack format 1 (introduced in 0.18)\nB3\n\nabc")

    def test_add_bytes_record_one_name(self):
        """Add a bytes record with one name."""
        self.writer.begin()

        offset, length = self.writer.add_bytes_record(
            [b"abc"], len(b"abc"), names=[(b"name1",)]
        )
        self.assertEqual((42, 13), (offset, length))
        self.assertOutput(
            b"Bazaar pack format 1 (introduced in 0.18)\nB3\nname1\n\nabc"
        )

    def test_add_bytes_record_split_writes(self):
        """Write a large record which does multiple IOs."""
        writes = []
        real_write = self.writer.write_func

        def record_writes(data):
            writes.append(data)
            return real_write(data)

        self.writer.write_func = record_writes
        self.writer._JOIN_WRITES_THRESHOLD = 2

        self.writer.begin()
        offset, length = self.writer.add_bytes_record(
            [b"abcabc"], len(b"abcabc"), names=[(b"name1",)]
        )
        self.assertEqual((42, 16), (offset, length))
        self.assertOutput(
            b"Bazaar pack format 1 (introduced in 0.18)\nB6\nname1\n\nabcabc"
        )

        self.assertEqual(
            [
                b"Bazaar pack format 1 (introduced in 0.18)\n",
                b"B6\nname1\n\n",
                b"abcabc",
            ],
            writes,
        )

    def test_add_bytes_record_two_names(self):
        """Add a bytes record with two names."""
        self.writer.begin()
        offset, length = self.writer.add_bytes_record(
            [b"abc"], len(b"abc"), names=[(b"name1",), (b"name2",)]
        )
        self.assertEqual((42, 19), (offset, length))
        self.assertOutput(
            b"Bazaar pack format 1 (introduced in 0.18)\nB3\nname1\nname2\n\nabc"
        )

    def test_add_bytes_record_two_element_name(self):
        """Add a bytes record with a two-element name."""
        self.writer.begin()
        offset, length = self.writer.add_bytes_record(
            [b"abc"], len(b"abc"), names=[(b"name1", b"name2")]
        )
        self.assertEqual((42, 19), (offset, length))
        self.assertOutput(
            b"Bazaar pack format 1 (introduced in 0.18)\nB3\nname1\x00name2\n\nabc"
        )

    def test_add_second_bytes_record_gets_higher_offset(self):
        self.writer.begin()
        self.writer.add_bytes_record([b"a", b"bc"], len(b"abc"), names=[])
        offset, length = self.writer.add_bytes_record([b"abc"], len(b"abc"), names=[])
        self.assertEqual((49, 7), (offset, length))
        self.assertOutput(
            b"Bazaar pack format 1 (introduced in 0.18)\nB3\n\nabcB3\n\nabc"
        )

    def test_add_bytes_record_invalid_name(self):
        """Adding a Bytes record with a name with whitespace in it raises
        InvalidRecordError.
        """
        self.writer.begin()
        self.assertRaises(
            pack.InvalidRecordError,
            self.writer.add_bytes_record,
            [b"abc"],
            len(b"abc"),
            names=[(b"bad name",)],
        )

    def test_add_bytes_records_add_to_records_written(self):
        """Adding a Bytes record increments the records_written counter."""
        self.writer.begin()
        self.writer.add_bytes_record([b"foo"], len(b"foo"), names=[])
        self.assertEqual(1, self.writer.records_written)
        self.writer.add_bytes_record([b"foo"], len(b"foo"), names=[])
        self.assertEqual(2, self.writer.records_written)


class TestContainerReader(tests.TestCase):
    """Tests for the ContainerReader.

    The ContainerReader reads format 1 containers, so these tests explicitly
    test how it reacts to format 1 data.  If a new version of the format is
    added, then separate tests for that format should be added.
    """

    def get_reader_for(self, data):
        stream = BytesIO(data)
        reader = pack.ContainerReader(stream)
        return reader

    def test_construct(self):
        """Test constructing a ContainerReader.

        This uses None as the output stream to show that the constructor
        doesn't try to use the input stream.
        """
        pack.ContainerReader(None)

    def test_empty_container(self):
        """Read an empty container."""
        reader = self.get_reader_for(b"Bazaar pack format 1 (introduced in 0.18)\nE")
        self.assertEqual([], list(reader.iter_records()))

    def test_unknown_format(self):
        """Unrecognised container formats raise UnknownContainerFormatError."""
        reader = self.get_reader_for(b"unknown format\n")
        self.assertRaises(pack.UnknownContainerFormatError, reader.iter_records)

    def test_unexpected_end_of_container(self):
        """Containers that don't end with an End Marker record should cause
        UnexpectedEndOfContainerError to be raised.
        """
        reader = self.get_reader_for(b"Bazaar pack format 1 (introduced in 0.18)\n")
        iterator = reader.iter_records()
        self.assertRaises(pack.UnexpectedEndOfContainerError, next, iterator)

    def test_unknown_record_type(self):
        """Unknown record types cause UnknownRecordTypeError to be raised."""
        reader = self.get_reader_for(b"Bazaar pack format 1 (introduced in 0.18)\nX")
        iterator = reader.iter_records()
        self.assertRaises(pack.UnknownRecordTypeError, next, iterator)

    def test_container_with_one_unnamed_record(self):
        """Read a container with one Bytes record.

        Parsing Bytes records is more thoroughly exercised by
        TestBytesRecordReader.  This test is here to ensure that
        ContainerReader's integration with BytesRecordReader is working.
        """
        reader = self.get_reader_for(
            b"Bazaar pack format 1 (introduced in 0.18)\nB5\n\naaaaaE"
        )
        expected_records = [([], b"aaaaa")]
        self.assertEqual(
            expected_records,
            [
                (names, read_bytes(None))
                for (names, read_bytes) in reader.iter_records()
            ],
        )

    def test_validate_empty_container(self):
        """Validate does not raise an error for a container with no records."""
        reader = self.get_reader_for(b"Bazaar pack format 1 (introduced in 0.18)\nE")
        # No exception raised
        reader.validate()

    def test_validate_non_empty_valid_container(self):
        """Validate does not raise an error for a container with a valid record."""
        reader = self.get_reader_for(
            b"Bazaar pack format 1 (introduced in 0.18)\nB3\nname\n\nabcE"
        )
        # No exception raised
        reader.validate()

    def test_validate_bad_format(self):
        """Validate raises an error for unrecognised format strings.

        It may raise either UnexpectedEndOfContainerError or
        UnknownContainerFormatError, depending on exactly what the string is.
        """
        inputs = [b"", b"x", b"Bazaar pack format 1 (introduced in 0.18)", b"bad\n"]
        for input in inputs:
            reader = self.get_reader_for(input)
            self.assertRaises(
                (pack.UnexpectedEndOfContainerError, pack.UnknownContainerFormatError),
                reader.validate,
            )

    def test_validate_bad_record_marker(self):
        """Validate raises UnknownRecordTypeError for unrecognised record
        types.
        """
        reader = self.get_reader_for(b"Bazaar pack format 1 (introduced in 0.18)\nX")
        self.assertRaises(pack.UnknownRecordTypeError, reader.validate)

    def test_validate_data_after_end_marker(self):
        """Validate raises ContainerHasExcessDataError if there are any bytes
        after the end of the container.
        """
        reader = self.get_reader_for(
            b"Bazaar pack format 1 (introduced in 0.18)\nEcrud"
        )
        self.assertRaises(pack.ContainerHasExcessDataError, reader.validate)

    def test_validate_no_end_marker(self):
        """Validate raises UnexpectedEndOfContainerError if there's no end of
        container marker, even if the container up to this point has been
        valid.
        """
        reader = self.get_reader_for(b"Bazaar pack format 1 (introduced in 0.18)\n")
        self.assertRaises(pack.UnexpectedEndOfContainerError, reader.validate)

    def test_validate_duplicate_name(self):
        """Validate raises DuplicateRecordNameError if the same name occurs
        multiple times in the container.
        """
        reader = self.get_reader_for(
            b"Bazaar pack format 1 (introduced in 0.18)\nB0\nname\n\nB0\nname\n\nE"
        )
        self.assertRaises(pack.DuplicateRecordNameError, reader.validate)

    def test_validate_undecodeable_name(self):
        """Names that aren't valid UTF-8 cause validate to fail."""
        reader = self.get_reader_for(
            b"Bazaar pack format 1 (introduced in 0.18)\nB0\n\xcc\n\nE"
        )
        self.assertRaises(pack.InvalidRecordError, reader.validate)


class TestBytesRecordReader(tests.TestCase):
    """Tests for reading and validating Bytes records with
    BytesRecordReader.

    Like TestContainerReader, this explicitly tests the reading of format 1
    data.  If a new version of the format is added, then a separate set of
    tests for reading that format should be added.
    """

    def get_reader_for(self, data):
        stream = BytesIO(data)
        reader = pack.BytesRecordReader(stream)
        return reader

    def test_record_with_no_name(self):
        """Reading a Bytes record with no name returns an empty list of
        names.
        """
        reader = self.get_reader_for(b"5\n\naaaaa")
        names, get_bytes = reader.read()
        self.assertEqual([], names)
        self.assertEqual(b"aaaaa", get_bytes(None))

    def test_record_with_one_name(self):
        """Reading a Bytes record with one name returns a list of just that
        name.
        """
        reader = self.get_reader_for(b"5\nname1\n\naaaaa")
        names, get_bytes = reader.read()
        self.assertEqual([(b"name1",)], names)
        self.assertEqual(b"aaaaa", get_bytes(None))

    def test_record_with_two_names(self):
        """Reading a Bytes record with two names returns a list of both names."""
        reader = self.get_reader_for(b"5\nname1\nname2\n\naaaaa")
        names, get_bytes = reader.read()
        self.assertEqual([(b"name1",), (b"name2",)], names)
        self.assertEqual(b"aaaaa", get_bytes(None))

    def test_record_with_two_part_names(self):
        """Reading a Bytes record with a two_part name reads both."""
        reader = self.get_reader_for(b"5\nname1\x00name2\n\naaaaa")
        names, get_bytes = reader.read()
        self.assertEqual(
            [
                (
                    b"name1",
                    b"name2",
                )
            ],
            names,
        )
        self.assertEqual(b"aaaaa", get_bytes(None))

    def test_invalid_length(self):
        """If the length-prefix is not a number, parsing raises
        InvalidRecordError.
        """
        reader = self.get_reader_for(b"not a number\n")
        self.assertRaises(pack.InvalidRecordError, reader.read)

    def test_early_eof(self):
        """Tests for premature EOF occuring during parsing Bytes records with
        BytesRecordReader.

        A incomplete container might be interrupted at any point.  The
        BytesRecordReader needs to cope with the input stream running out no
        matter where it is in the parsing process.

        In all cases, UnexpectedEndOfContainerError should be raised.
        """
        complete_record = b"6\nname\n\nabcdef"
        for count in range(0, len(complete_record)):
            incomplete_record = complete_record[:count]
            reader = self.get_reader_for(incomplete_record)
            # We don't use assertRaises to make diagnosing failures easier
            # (assertRaises doesn't allow a custom failure message).
            try:
                names, read_bytes = reader.read()
                read_bytes(None)
            except pack.UnexpectedEndOfContainerError:
                pass
            else:
                self.fail(
                    f"UnexpectedEndOfContainerError not raised when parsing {incomplete_record!r}"
                )

    def test_initial_eof(self):
        """EOF before any bytes read at all."""
        reader = self.get_reader_for(b"")
        self.assertRaises(pack.UnexpectedEndOfContainerError, reader.read)

    def test_eof_after_length(self):
        """EOF after reading the length and before reading name(s)."""
        reader = self.get_reader_for(b"123\n")
        self.assertRaises(pack.UnexpectedEndOfContainerError, reader.read)

    def test_eof_during_name(self):
        """EOF during reading a name."""
        reader = self.get_reader_for(b"123\nname")
        self.assertRaises(pack.UnexpectedEndOfContainerError, reader.read)

    def test_read_invalid_name_whitespace(self):
        """Names must have no whitespace."""
        # A name with a space.
        reader = self.get_reader_for(b"0\nbad name\n\n")
        self.assertRaises(pack.InvalidRecordError, reader.read)

        # A name with a tab.
        reader = self.get_reader_for(b"0\nbad\tname\n\n")
        self.assertRaises(pack.InvalidRecordError, reader.read)

        # A name with a vertical tab.
        reader = self.get_reader_for(b"0\nbad\vname\n\n")
        self.assertRaises(pack.InvalidRecordError, reader.read)

    def test_validate_whitespace_in_name(self):
        """Names must have no whitespace."""
        reader = self.get_reader_for(b"0\nbad name\n\n")
        self.assertRaises(pack.InvalidRecordError, reader.validate)

    def test_validate_interrupted_prelude(self):
        """EOF during reading a record's prelude causes validate to fail."""
        reader = self.get_reader_for(b"")
        self.assertRaises(pack.UnexpectedEndOfContainerError, reader.validate)

    def test_validate_interrupted_body(self):
        """EOF during reading a record's body causes validate to fail."""
        reader = self.get_reader_for(b"1\n\n")
        self.assertRaises(pack.UnexpectedEndOfContainerError, reader.validate)

    def test_validate_unparseable_length(self):
        """An unparseable record length causes validate to fail."""
        reader = self.get_reader_for(b"\n\n")
        self.assertRaises(pack.InvalidRecordError, reader.validate)

    def test_validate_undecodeable_name(self):
        """Names that aren't valid UTF-8 cause validate to fail."""
        reader = self.get_reader_for(b"0\n\xcc\n\n")
        self.assertRaises(pack.InvalidRecordError, reader.validate)

    def test_read_max_length(self):
        """If the max_length passed to the callable returned by read is not
        None, then no more than that many bytes will be read.
        """
        reader = self.get_reader_for(b"6\n\nabcdef")
        names, get_bytes = reader.read()
        self.assertEqual(b"abc", get_bytes(3))

    def test_read_no_max_length(self):
        """If the max_length passed to the callable returned by read is None,
        then all the bytes in the record will be read.
        """
        reader = self.get_reader_for(b"6\n\nabcdef")
        names, get_bytes = reader.read()
        self.assertEqual(b"abcdef", get_bytes(None))

    def test_repeated_read_calls(self):
        """Repeated calls to the callable returned from BytesRecordReader.read
        will not read beyond the end of the record.
        """
        reader = self.get_reader_for(b"6\n\nabcdefB3\nnext-record\nXXX")
        names, get_bytes = reader.read()
        self.assertEqual(b"abcdef", get_bytes(None))
        self.assertEqual(b"", get_bytes(None))
        self.assertEqual(b"", get_bytes(99))


class TestMakeReadvReader(tests.TestCaseWithTransport):
    def test_read_skipping_records(self):
        pack_data = BytesIO()
        writer = pack.ContainerWriter(pack_data.write)
        writer.begin()
        memos = []
        memos.append(writer.add_bytes_record([b"abc"], 3, names=[]))
        memos.append(writer.add_bytes_record([b"def"], 3, names=[(b"name1",)]))
        memos.append(writer.add_bytes_record([b"ghi"], 3, names=[(b"name2",)]))
        memos.append(writer.add_bytes_record([b"jkl"], 3, names=[]))
        writer.end()
        transport = self.get_transport()
        transport.put_bytes("mypack", pack_data.getvalue())
        requested_records = [memos[0], memos[2]]
        reader = pack.make_readv_reader(transport, "mypack", requested_records)
        result = []
        for names, reader_func in reader.iter_records():
            result.append((names, reader_func(None)))
        self.assertEqual([([], b"abc"), ([(b"name2",)], b"ghi")], result)


class TestReadvFile(tests.TestCaseWithTransport):
    """Tests of the ReadVFile class.

    Error cases are deliberately undefined: this code adapts the underlying
    transport interface to a single 'streaming read' interface as
    ContainerReader needs.
    """

    def test_read_bytes(self):
        """Test reading of both single bytes and all bytes in a hunk."""
        transport = self.get_transport()
        transport.put_bytes("sample", b"0123456789")
        f = pack.ReadVFile(transport.readv("sample", [(0, 1), (1, 2), (4, 1), (6, 2)]))
        results = []
        results.append(f.read(1))
        results.append(f.read(2))
        results.append(f.read(1))
        results.append(f.read(1))
        results.append(f.read(1))
        self.assertEqual([b"0", b"12", b"4", b"6", b"7"], results)

    def test_readline(self):
        """Test using readline() as ContainerReader does.

        This is always within a readv hunk, never across it.
        """
        transport = self.get_transport()
        transport.put_bytes("sample", b"0\n2\n4\n")
        f = pack.ReadVFile(transport.readv("sample", [(0, 2), (2, 4)]))
        results = []
        results.append(f.readline())
        results.append(f.readline())
        results.append(f.readline())
        self.assertEqual([b"0\n", b"2\n", b"4\n"], results)

    def test_readline_and_read(self):
        """Test exercising one byte reads, readline, and then read again."""
        transport = self.get_transport()
        transport.put_bytes("sample", b"0\n2\n4\n")
        f = pack.ReadVFile(transport.readv("sample", [(0, 6)]))
        results = []
        results.append(f.read(1))
        results.append(f.readline())
        results.append(f.read(4))
        self.assertEqual([b"0", b"\n", b"2\n4\n"], results)


class PushParserTestCase(tests.TestCase):
    """Base class for TestCases involving ContainerPushParser."""

    def make_parser_expecting_record_type(self):
        parser = pack.ContainerPushParser()
        parser.accept_bytes(b"Bazaar pack format 1 (introduced in 0.18)\n")
        return parser

    def make_parser_expecting_bytes_record(self):
        parser = pack.ContainerPushParser()
        parser.accept_bytes(b"Bazaar pack format 1 (introduced in 0.18)\nB")
        return parser

    def assertRecordParsing(self, expected_record, data):
        """Assert that 'bytes' is parsed as a given bytes record.

        :param expected_record: A tuple of (names, bytes).
        """
        parser = self.make_parser_expecting_bytes_record()
        parser.accept_bytes(data)
        parsed_records = parser.read_pending_records()
        self.assertEqual([expected_record], parsed_records)


class TestContainerPushParser(PushParserTestCase):
    """Tests for ContainerPushParser.

    The ContainerPushParser reads format 1 containers, so these tests
    explicitly test how it reacts to format 1 data.  If a new version of the
    format is added, then separate tests for that format should be added.
    """

    def test_construct(self):
        """ContainerPushParser can be constructed."""
        pack.ContainerPushParser()

    def test_multiple_records_at_once(self):
        """If multiple records worth of data are fed to the parser in one
        string, the parser will correctly parse all the records.

        (A naive implementation might stop after parsing the first record.)
        """
        parser = self.make_parser_expecting_record_type()
        parser.accept_bytes(b"B5\nname1\n\nbody1B5\nname2\n\nbody2")
        self.assertEqual(
            [([(b"name1",)], b"body1"), ([(b"name2",)], b"body2")],
            parser.read_pending_records(),
        )

    def test_multiple_empty_records_at_once(self):
        """If multiple empty records worth of data are fed to the parser in one
        string, the parser will correctly parse all the records.

        (A naive implementation might stop after parsing the first empty
        record, because the buffer size had not changed.)
        """
        parser = self.make_parser_expecting_record_type()
        parser.accept_bytes(b"B0\nname1\n\nB0\nname2\n\n")
        self.assertEqual(
            [([(b"name1",)], b""), ([(b"name2",)], b"")], parser.read_pending_records()
        )


class TestContainerPushParserBytesParsing(PushParserTestCase):
    """Tests for reading Bytes records with ContainerPushParser.

    The ContainerPushParser reads format 1 containers, so these tests
    explicitly test how it reacts to format 1 data.  If a new version of the
    format is added, then separate tests for that format should be added.
    """

    def test_record_with_no_name(self):
        """Reading a Bytes record with no name returns an empty list of
        names.
        """
        self.assertRecordParsing(([], b"aaaaa"), b"5\n\naaaaa")

    def test_record_with_one_name(self):
        """Reading a Bytes record with one name returns a list of just that
        name.
        """
        self.assertRecordParsing(([(b"name1",)], b"aaaaa"), b"5\nname1\n\naaaaa")

    def test_record_with_two_names(self):
        """Reading a Bytes record with two names returns a list of both names."""
        self.assertRecordParsing(
            ([(b"name1",), (b"name2",)], b"aaaaa"), b"5\nname1\nname2\n\naaaaa"
        )

    def test_record_with_two_part_names(self):
        """Reading a Bytes record with a two_part name reads both."""
        self.assertRecordParsing(
            ([(b"name1", b"name2")], b"aaaaa"), b"5\nname1\x00name2\n\naaaaa"
        )

    def test_invalid_length(self):
        """If the length-prefix is not a number, parsing raises
        InvalidRecordError.
        """
        parser = self.make_parser_expecting_bytes_record()
        self.assertRaises(
            pack.InvalidRecordError, parser.accept_bytes, b"not a number\n"
        )

    def test_incomplete_record(self):
        """If the bytes seen so far don't form a complete record, then there
        will be nothing returned by read_pending_records.
        """
        parser = self.make_parser_expecting_bytes_record()
        parser.accept_bytes(b"5\n\nabcd")
        self.assertEqual([], parser.read_pending_records())

    def test_accept_nothing(self):
        """The edge case of parsing an empty string causes no error."""
        parser = self.make_parser_expecting_bytes_record()
        parser.accept_bytes(b"")

    def assertInvalidRecord(self, data):
        """Assert that parsing the given bytes raises InvalidRecordError."""
        parser = self.make_parser_expecting_bytes_record()
        self.assertRaises(pack.InvalidRecordError, parser.accept_bytes, data)

    def test_read_invalid_name_whitespace(self):
        """Names must have no whitespace."""
        # A name with a space.
        self.assertInvalidRecord(b"0\nbad name\n\n")

        # A name with a tab.
        self.assertInvalidRecord(b"0\nbad\tname\n\n")

        # A name with a vertical tab.
        self.assertInvalidRecord(b"0\nbad\vname\n\n")

    def test_repeated_read_pending_records(self):
        """read_pending_records will not return the same record twice."""
        parser = self.make_parser_expecting_bytes_record()
        parser.accept_bytes(b"6\n\nabcdef")
        self.assertEqual([([], b"abcdef")], parser.read_pending_records())
        self.assertEqual([], parser.read_pending_records())


class TestErrors(tests.TestCase):
    def test_unknown_container_format(self):
        """Test the formatting of UnknownContainerFormatError."""
        e = pack.UnknownContainerFormatError("bad format string")
        self.assertEqual("Unrecognised container format: 'bad format string'", str(e))

    def test_unexpected_end_of_container(self):
        """Test the formatting of UnexpectedEndOfContainerError."""
        e = pack.UnexpectedEndOfContainerError()
        self.assertEqual("Unexpected end of container stream", str(e))

    def test_unknown_record_type(self):
        """Test the formatting of UnknownRecordTypeError."""
        e = pack.UnknownRecordTypeError("X")
        self.assertEqual("Unknown record type: 'X'", str(e))

    def test_invalid_record(self):
        """Test the formatting of InvalidRecordError."""
        e = pack.InvalidRecordError("xxx")
        self.assertEqual("Invalid record: xxx", str(e))

    def test_container_has_excess_data(self):
        """Test the formatting of ContainerHasExcessDataError."""
        e = pack.ContainerHasExcessDataError("excess bytes")
        self.assertEqual("Container has data after end marker: 'excess bytes'", str(e))

    def test_duplicate_record_name_error(self):
        """Test the formatting of DuplicateRecordNameError."""
        e = pack.DuplicateRecordNameError(b"n\xc3\xa5me")
        self.assertEqual(
            "Container has multiple records with the same name: n\xe5me", str(e)
        )
