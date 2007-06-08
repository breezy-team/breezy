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

from bzrlib import pack, errors
from bzrlib.tests import TestCase


class TestContainerWriter(TestCase):

    def test_construct(self):
        """Test constructing a ContainerWriter.
        
        This uses None as the output stream to show that the constructor doesn't
        try to use the output stream.
        """
        writer = pack.ContainerWriter(None)

    def test_begin(self):
        """Test the begin() method."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        self.assertEqual('bzr pack format 1\n', output.getvalue())

    def test_end(self):
        """Test the end() method."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        writer.end()
        self.assertEqual('bzr pack format 1\nE', output.getvalue())

    def test_add_bytes_record_no_name(self):
        """Add a bytes record with no name."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        writer.add_bytes_record('abc', names=[])
        self.assertEqual('bzr pack format 1\nB3\n\nabc', output.getvalue())

    def test_add_bytes_record_one_name(self):
        """Add a bytes record with one name."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        writer.add_bytes_record('abc', names=['name1'])
        self.assertEqual('bzr pack format 1\nB3\nname1\n\nabc',
                         output.getvalue())

    def test_add_bytes_record_two_names(self):
        """Add a bytes record with two names."""
        output = StringIO()
        writer = pack.ContainerWriter(output.write)
        writer.begin()
        writer.add_bytes_record('abc', names=['name1', 'name2'])
        self.assertEqual('bzr pack format 1\nB3\nname1\nname2\n\nabc',
                         output.getvalue())


class TestContainerReader(TestCase):

    def test_construct(self):
        """Test constructing a ContainerReader.
        
        This uses None as the output stream to show that the constructor doesn't
        try to use the input stream.
        """
        reader = pack.ContainerReader(None)

    def test_empty_container(self):
        """Read an empty container."""
        input = StringIO("bzr pack format 1\nE")
        reader = pack.ContainerReader(input.read)
        self.assertEqual([], list(reader.iter_records()))

    def test_unknown_format(self):
        """Unrecognised container formats raise UnknownContainerFormatError."""
        input = StringIO("unknown format\n")
        reader = pack.ContainerReader(input.read)
        self.assertRaises(
            errors.UnknownContainerFormatError, reader.iter_records)

    def test_unexpected_end_of_container(self):
        """Containers that don't end with an End Marker record should cause
        UnexpectedEndOfContainerError to be raised.
        """
        input = StringIO("bzr pack format 1\n")
        reader = pack.ContainerReader(input.read)
        iterator = reader.iter_records()
        self.assertRaises(
            errors.UnexpectedEndOfContainerError, iterator.next)

    def test_unknown_record_type(self):
        """Unknown record types cause UnknownRecordTypeError to be raised."""
        input = StringIO("bzr pack format 1\nX")
        reader = pack.ContainerReader(input.read)
        iterator = reader.iter_records()
        self.assertRaises(
            errors.UnknownRecordTypeError, iterator.next)

    def test_container_with_one_unnamed_record(self):
        """Read a container with one Bytes record.
        
        Parsing Bytes records is more thoroughly exercised by XXX.  This test is
        here to ensure that ContainerReader's integration with BytesRecordReader
        is working.
        """
        input = StringIO("bzr pack format 1\nB5\n\naaaaaE")
        reader = pack.ContainerReader(input.read)
        expected_records = [([], 'aaaaa')]
        self.assertEqual(expected_records, list(reader.iter_records()))


class TestBytesRecordReader(TestCase):
    """Tests for parsing Bytes records with BytesRecordReader."""

    def test_record_with_no_name(self):
        """Reading a Bytes record with no name returns an empty list of
        names.
        """
        input = StringIO("5\n\naaaaa")
        reader = pack.BytesRecordReader(input.read)
        names, bytes = reader.read()
        self.assertEqual([], names)
        self.assertEqual('aaaaa', bytes)

    def test_record_with_one_name(self):
        """Reading a Bytes record with one name returns a list of just that
        name.
        """
        input = StringIO("5\nname1\n\naaaaa")
        reader = pack.BytesRecordReader(input.read)
        names, bytes = reader.read()
        self.assertEqual(['name1'], names)
        self.assertEqual('aaaaa', bytes)

    def test_record_with_two_names(self):
        """Reading a Bytes record with two names returns a list of both names.
        """
        input = StringIO("5\nname1\nname2\n\naaaaa")
        reader = pack.BytesRecordReader(input.read)
        names, bytes = reader.read()
        self.assertEqual(['name1', 'name2'], names)
        self.assertEqual('aaaaa', bytes)

    def test_invalid_length(self):
        """If the length-prefix is not a number, parsing raises
        InvalidRecordError.
        """
        input = StringIO("not a number\n")
        reader = pack.BytesRecordReader(input.read)
        self.assertRaises(errors.InvalidRecordError, reader.read)

    # Other Bytes record parsing cases to test:
    #  - incomplete bytes (i.e. stream ends before $length bytes read)
    #  - _read_line encountering end of stream (at any time; during length,
    #    names, end of headers...)



