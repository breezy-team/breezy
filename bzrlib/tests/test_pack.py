# Copyright (C) 2007 Canonical Ltd
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

"""Tests for bzrlib.pack."""


from cStringIO import StringIO

from bzrlib import pack, errors, tests


class TestContainerWriter(tests.TestCase):

    def test_construct(self):
        """Test constructing a ContainerWriter.
        
        This uses None as the output stream to show that the constructor doesn't
        try to use the output stream.
        """
        writer = pack.ContainerWriter(None)

    def test_begin(self):
        """The begin() method writes the container format marker line."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        self.assertEqual('Bazaar pack format 1 (introduced in 0.18)\n',
                         output.getvalue())

    def test_end(self):
        """The end() method writes an End Marker record."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        writer.end()
        self.assertEqual('Bazaar pack format 1 (introduced in 0.18)\nE',
                         output.getvalue())

    def test_add_bytes_record_no_name(self):
        """Add a bytes record with no name."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        offset, length = writer.add_bytes_record('abc', names=[])
        self.assertEqual((42, 7), (offset, length))
        self.assertEqual('Bazaar pack format 1 (introduced in 0.18)\nB3\n\nabc',
                         output.getvalue())

    def test_add_bytes_record_one_name(self):
        """Add a bytes record with one name."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        offset, length = writer.add_bytes_record('abc', names=['name1'])
        self.assertEqual((42, 13), (offset, length))
        self.assertEqual(
            'Bazaar pack format 1 (introduced in 0.18)\n'
            'B3\nname1\n\nabc',
            output.getvalue())

    def test_add_bytes_record_two_names(self):
        """Add a bytes record with two names."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        offset, length = writer.add_bytes_record('abc', names=['name1', 'name2'])
        self.assertEqual((42, 19), (offset, length))
        self.assertEqual(
            'Bazaar pack format 1 (introduced in 0.18)\n'
            'B3\nname1\nname2\n\nabc',
            output.getvalue())

    def test_add_second_bytes_record_gets_higher_offset(self):
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        writer.add_bytes_record('abc', names=[])
        offset, length = writer.add_bytes_record('abc', names=[])
        self.assertEqual((49, 7), (offset, length))
        self.assertEqual(
            'Bazaar pack format 1 (introduced in 0.18)\n'
            'B3\n\nabc'
            'B3\n\nabc',
            output.getvalue())

    def test_add_bytes_record_invalid_name(self):
        """Adding a Bytes record with a name with whitespace in it raises
        InvalidRecordError.
        """
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        self.assertRaises(
            errors.InvalidRecordError,
            writer.add_bytes_record, 'abc', names=['bad name'])


class TestContainerReader(tests.TestCase):

    def get_reader_for(self, bytes):
        stream = StringIO(bytes)
        reader = pack.ContainerReader(stream)
        return reader

    def test_construct(self):
        """Test constructing a ContainerReader.
        
        This uses None as the output stream to show that the constructor doesn't
        try to use the input stream.
        """
        reader = pack.ContainerReader(None)

    def test_empty_container(self):
        """Read an empty container."""
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\nE")
        self.assertEqual([], list(reader.iter_records()))

    def test_unknown_format(self):
        """Unrecognised container formats raise UnknownContainerFormatError."""
        reader = self.get_reader_for("unknown format\n")
        self.assertRaises(
            errors.UnknownContainerFormatError, reader.iter_records)

    def test_unexpected_end_of_container(self):
        """Containers that don't end with an End Marker record should cause
        UnexpectedEndOfContainerError to be raised.
        """
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\n")
        iterator = reader.iter_records()
        self.assertRaises(
            errors.UnexpectedEndOfContainerError, iterator.next)

    def test_unknown_record_type(self):
        """Unknown record types cause UnknownRecordTypeError to be raised."""
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\nX")
        iterator = reader.iter_records()
        self.assertRaises(
            errors.UnknownRecordTypeError, iterator.next)

    def test_container_with_one_unnamed_record(self):
        """Read a container with one Bytes record.
        
        Parsing Bytes records is more thoroughly exercised by
        TestBytesRecordReader.  This test is here to ensure that
        ContainerReader's integration with BytesRecordReader is working.
        """
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\nB5\n\naaaaaE")
        expected_records = [([], 'aaaaa')]
        self.assertEqual(
            expected_records,
            [(names, read_bytes(None))
             for (names, read_bytes) in reader.iter_records()])

    def test_validate_empty_container(self):
        """validate does not raise an error for a container with no records."""
        reader = self.get_reader_for("Bazaar pack format 1 (introduced in 0.18)\nE")
        # No exception raised
        reader.validate()

    def test_validate_non_empty_valid_container(self):
        """validate does not raise an error for a container with a valid record.
        """
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\nB3\nname\n\nabcE")
        # No exception raised
        reader.validate()

    def test_validate_bad_format(self):
        """validate raises an error for unrecognised format strings.

        It may raise either UnexpectedEndOfContainerError or
        UnknownContainerFormatError, depending on exactly what the string is.
        """
        inputs = ["", "x", "Bazaar pack format 1 (introduced in 0.18)", "bad\n"]
        for input in inputs:
            reader = self.get_reader_for(input)
            self.assertRaises(
                (errors.UnexpectedEndOfContainerError,
                 errors.UnknownContainerFormatError),
                reader.validate)

    def test_validate_bad_record_marker(self):
        """validate raises UnknownRecordTypeError for unrecognised record
        types.
        """
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\nX")
        self.assertRaises(errors.UnknownRecordTypeError, reader.validate)

    def test_validate_data_after_end_marker(self):
        """validate raises ContainerHasExcessDataError if there are any bytes
        after the end of the container.
        """
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\nEcrud")
        self.assertRaises(
            errors.ContainerHasExcessDataError, reader.validate)

    def test_validate_no_end_marker(self):
        """validate raises UnexpectedEndOfContainerError if there's no end of
        container marker, even if the container up to this point has been valid.
        """
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\n")
        self.assertRaises(
            errors.UnexpectedEndOfContainerError, reader.validate)

    def test_validate_duplicate_name(self):
        """validate raises DuplicateRecordNameError if the same name occurs
        multiple times in the container.
        """
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\n"
            "B0\nname\n\n"
            "B0\nname\n\n"
            "E")
        self.assertRaises(errors.DuplicateRecordNameError, reader.validate)

    def test_validate_undecodeable_name(self):
        """Names that aren't valid UTF-8 cause validate to fail."""
        reader = self.get_reader_for(
            "Bazaar pack format 1 (introduced in 0.18)\nB0\n\xcc\n\nE")
        self.assertRaises(errors.InvalidRecordError, reader.validate)
        

class TestBytesRecordReader(tests.TestCase):
    """Tests for reading and validating Bytes records with BytesRecordReader."""

    def get_reader_for(self, bytes):
        stream = StringIO(bytes)
        reader = pack.BytesRecordReader(stream)
        return reader

    def test_record_with_no_name(self):
        """Reading a Bytes record with no name returns an empty list of
        names.
        """
        reader = self.get_reader_for("5\n\naaaaa")
        names, get_bytes = reader.read()
        self.assertEqual([], names)
        self.assertEqual('aaaaa', get_bytes(None))

    def test_record_with_one_name(self):
        """Reading a Bytes record with one name returns a list of just that
        name.
        """
        reader = self.get_reader_for("5\nname1\n\naaaaa")
        names, get_bytes = reader.read()
        self.assertEqual(['name1'], names)
        self.assertEqual('aaaaa', get_bytes(None))

    def test_record_with_two_names(self):
        """Reading a Bytes record with two names returns a list of both names.
        """
        reader = self.get_reader_for("5\nname1\nname2\n\naaaaa")
        names, get_bytes = reader.read()
        self.assertEqual(['name1', 'name2'], names)
        self.assertEqual('aaaaa', get_bytes(None))

    def test_invalid_length(self):
        """If the length-prefix is not a number, parsing raises
        InvalidRecordError.
        """
        reader = self.get_reader_for("not a number\n")
        self.assertRaises(errors.InvalidRecordError, reader.read)

    def test_early_eof(self):
        """Tests for premature EOF occuring during parsing Bytes records with
        BytesRecordReader.
        
        A incomplete container might be interrupted at any point.  The
        BytesRecordReader needs to cope with the input stream running out no
        matter where it is in the parsing process.

        In all cases, UnexpectedEndOfContainerError should be raised.
        """
        complete_record = "6\nname\n\nabcdef"
        for count in range(0, len(complete_record)):
            incomplete_record = complete_record[:count]
            reader = self.get_reader_for(incomplete_record)
            # We don't use assertRaises to make diagnosing failures easier
            # (assertRaises doesn't allow a custom failure message).
            try:
                names, read_bytes = reader.read()
                read_bytes(None)
            except errors.UnexpectedEndOfContainerError:
                pass
            else:
                self.fail(
                    "UnexpectedEndOfContainerError not raised when parsing %r"
                    % (incomplete_record,))

    def test_initial_eof(self):
        """EOF before any bytes read at all."""
        reader = self.get_reader_for("")
        self.assertRaises(errors.UnexpectedEndOfContainerError, reader.read)

    def test_eof_after_length(self):
        """EOF after reading the length and before reading name(s)."""
        reader = self.get_reader_for("123\n")
        self.assertRaises(errors.UnexpectedEndOfContainerError, reader.read)

    def test_eof_during_name(self):
        """EOF during reading a name."""
        reader = self.get_reader_for("123\nname")
        self.assertRaises(errors.UnexpectedEndOfContainerError, reader.read)

    def test_read_invalid_name_whitespace(self):
        """Names must have no whitespace."""
        # A name with a space.
        reader = self.get_reader_for("0\nbad name\n\n")
        self.assertRaises(errors.InvalidRecordError, reader.read)

        # A name with a tab.
        reader = self.get_reader_for("0\nbad\tname\n\n")
        self.assertRaises(errors.InvalidRecordError, reader.read)

        # A name with a vertical tab.
        reader = self.get_reader_for("0\nbad\vname\n\n")
        self.assertRaises(errors.InvalidRecordError, reader.read)

    def test_validate_whitespace_in_name(self):
        """Names must have no whitespace."""
        reader = self.get_reader_for("0\nbad name\n\n")
        self.assertRaises(errors.InvalidRecordError, reader.validate)

    def test_validate_interrupted_prelude(self):
        """EOF during reading a record's prelude causes validate to fail."""
        reader = self.get_reader_for("")
        self.assertRaises(
            errors.UnexpectedEndOfContainerError, reader.validate)

    def test_validate_interrupted_body(self):
        """EOF during reading a record's body causes validate to fail."""
        reader = self.get_reader_for("1\n\n")
        self.assertRaises(
            errors.UnexpectedEndOfContainerError, reader.validate)

    def test_validate_unparseable_length(self):
        """An unparseable record length causes validate to fail."""
        reader = self.get_reader_for("\n\n")
        self.assertRaises(
            errors.InvalidRecordError, reader.validate)

    def test_validate_undecodeable_name(self):
        """Names that aren't valid UTF-8 cause validate to fail."""
        reader = self.get_reader_for("0\n\xcc\n\n")
        self.assertRaises(errors.InvalidRecordError, reader.validate)

    def test_read_max_length(self):
        """If the max_length passed to the callable returned by read is not
        None, then no more than that many bytes will be read.
        """
        reader = self.get_reader_for("6\n\nabcdef")
        names, get_bytes = reader.read()
        self.assertEqual('abc', get_bytes(3))

    def test_read_no_max_length(self):
        """If the max_length passed to the callable returned by read is None,
        then all the bytes in the record will be read.
        """
        reader = self.get_reader_for("6\n\nabcdef")
        names, get_bytes = reader.read()
        self.assertEqual('abcdef', get_bytes(None))

    def test_repeated_read_calls(self):
        """Repeated calls to the callable returned from BytesRecordReader.read
        will not read beyond the end of the record.
        """
        reader = self.get_reader_for("6\n\nabcdefB3\nnext-record\nXXX")
        names, get_bytes = reader.read()
        self.assertEqual('abcdef', get_bytes(None))
        self.assertEqual('', get_bytes(None))
        self.assertEqual('', get_bytes(99))


class TestMakeReadvReader(tests.TestCaseWithTransport):

    def test_read_skipping_records(self):
        pack_data = StringIO()
        writer = pack.ContainerWriter(pack_data.write)
        writer.begin()
        memos = []
        memos.append(writer.add_bytes_record('abc', names=[]))
        memos.append(writer.add_bytes_record('def', names=['name1']))
        memos.append(writer.add_bytes_record('ghi', names=['name2']))
        memos.append(writer.add_bytes_record('jkl', names=[]))
        writer.end()
        transport = self.get_transport()
        transport.put_bytes('mypack', pack_data.getvalue())
        requested_records = [memos[0], memos[2]]
        reader = pack.make_readv_reader(transport, 'mypack', requested_records)
        result = []
        for names, reader_func in reader.iter_records():
            result.append((names, reader_func(None)))
        self.assertEqual([([], 'abc'), (['name2'], 'ghi')], result)


class TestReadvFile(tests.TestCaseWithTransport):
    """Tests of the ReadVFile class.

    Error cases are deliberately undefined: this code adapts the underlying
    transport interface to a single 'streaming read' interface as 
    ContainerReader needs.
    """

    def test_read_bytes(self):
        """Test reading of both single bytes and all bytes in a hunk."""
        transport = self.get_transport()
        transport.put_bytes('sample', '0123456789')
        f = pack.ReadVFile(transport.readv('sample', [(0,1), (1,2), (4,1), (6,2)]))
        results = []
        results.append(f.read(1))
        results.append(f.read(2))
        results.append(f.read(1))
        results.append(f.read(1))
        results.append(f.read(1))
        self.assertEqual(['0', '12', '4', '6', '7'], results)

    def test_readline(self):
        """Test using readline() as ContainerReader does.

        This is always within a readv hunk, never across it.
        """
        transport = self.get_transport()
        transport.put_bytes('sample', '0\n2\n4\n')
        f = pack.ReadVFile(transport.readv('sample', [(0,2), (2,4)]))
        results = []
        results.append(f.readline())
        results.append(f.readline())
        results.append(f.readline())
        self.assertEqual(['0\n', '2\n', '4\n'], results)

    def test_readline_and_read(self):
        """Test exercising one byte reads, readline, and then read again."""
        transport = self.get_transport()
        transport.put_bytes('sample', '0\n2\n4\n')
        f = pack.ReadVFile(transport.readv('sample', [(0,6)]))
        results = []
        results.append(f.read(1))
        results.append(f.readline())
        results.append(f.read(4))
        self.assertEqual(['0', '\n', '2\n4\n'], results)
