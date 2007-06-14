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

"""Container format for Bazaar data.

"Containers" and "records" are described in doc/developers/container-format.txt.
"""

import re

from bzrlib import errors


FORMAT_ONE = "Bazaar pack format 1"


_whitespace_re = re.compile('[\t\n\x0b\x0c\r ]')


def _check_name(name):
    """Do some basic checking of 'name'.
    
    At the moment, this just checks that there are no whitespace characters in a
    name.

    :raises InvalidRecordError: if name is not valid.
    :seealso: _check_name_encoding
    """
    if _whitespace_re.search(name) is not None:
        raise errors.InvalidRecordError("%r is not a valid name." % (name,))


def _check_name_encoding(name):
    """Check that 'name' is valid UTF-8.
    
    This is separate from _check_name because UTF-8 decoding is relatively
    expensive, and we usually want to avoid it.

    :raises InvalidRecordError: if name is not valid UTF-8.
    """
    try:
        name.decode('utf-8')
    except UnicodeDecodeError, e:
        raise errors.InvalidRecordError(str(e))


class ContainerWriter(object):
    """A class for writing containers."""

    def __init__(self, write_func):
        """Constructor.

        :param write_func: a callable that will be called when this
            ContainerWriter needs to write some bytes.
        """
        self.write_func = write_func

    def begin(self):
        """Begin writing a container."""
        self.write_func(FORMAT_ONE + "\n")

    def end(self):
        """Finish writing a container."""
        self.write_func("E")

    def add_bytes_record(self, bytes, names):
        """Add a Bytes record with the given names."""
        # Kind marker
        self.write_func("B")
        # Length
        self.write_func(str(len(bytes)) + "\n")
        # Names
        for name in names:
            # Make sure we're writing valid names.  Note that we will leave a
            # half-written record if a name is bad!
            _check_name(name)
            self.write_func(name + "\n")
        # End of headers
        self.write_func("\n")
        # Finally, the contents.
        self.write_func(bytes)


class BaseReader(object):

    def __init__(self, reader_func):
        """Constructor.

        :param reader_func: a callable that takes one optional argument,
            ``size``, and returns at most that many bytes.  When the callable
            returns less than the requested number of bytes, then the end of the
            file/stream has been reached.
        """
        self.reader_func = reader_func

    def _read_line(self):
        """Read a line from the input stream.

        This is a simple but inefficient implementation that just reads one byte
        at a time.  Lines should not be very long, so this is probably
        tolerable.

        :returns: a line, without the trailing newline
        """
        # XXX: Have a maximum line length, to prevent malicious input from
        # consuming an unreasonable amount of resources?
        #   -- Andrew Bennetts, 2007-05-07.
        line = ''
        while not line.endswith('\n'):
            byte = self.reader_func(1)
            if byte == '':
                raise errors.UnexpectedEndOfContainerError()
            line += byte
        return line[:-1]


class ContainerReader(BaseReader):
    """A class for reading Bazaar's container format."""

    def iter_records(self):
        """Iterate over the container, yielding each record as it is read.

        Each yielded record will be a 2-tuple of (names, callable), where names
        is a ``list`` and bytes is a function that takes one argument,
        ``max_length``.

        You **must not** call the callable after advancing the interator to the
        next record.  That is, this code is invalid::

            record_iter = container.iter_records()
            names1, callable1 = record_iter.next()
            names2, callable2 = record_iter.next()
            bytes1 = callable1(None)
        
        As it will give incorrect results and invalidate the state of the
        ContainerReader.

        :raises ContainerError: if any sort of containter corruption is
            detected, e.g. UnknownContainerFormatError is the format of the
            container is unrecognised.
        :seealso: ContainerReader.read
        """
        self._read_format()
        return self._iter_records()
    
    def iter_record_objects(self):
        """Iterate over the container, yielding each record as it is read.

        Each yielded record will be an object with ``read`` and ``validate``
        methods.  Like with iter_records, it is not safe to use a record object
        after advancing the iterator to yield next record.

        :raises ContainerError: if any sort of containter corruption is
            detected, e.g. UnknownContainerFormatError is the format of the
            container is unrecognised.
        :seealso: iter_records
        """
        self._read_format()
        return self._iter_record_objects()
    
    def _iter_records(self):
        for record in self._iter_record_objects():
            yield record.read()

    def _iter_record_objects(self):
        while True:
            record_kind = self.reader_func(1)
            if record_kind == 'B':
                # Bytes record.
                reader = BytesRecordReader(self.reader_func)
                yield reader
            elif record_kind == 'E':
                # End marker.  There are no more records.
                return
            elif record_kind == '':
                # End of stream encountered, but no End Marker record seen, so
                # this container is incomplete.
                raise errors.UnexpectedEndOfContainerError()
            else:
                # Unknown record type.
                raise errors.UnknownRecordTypeError(record_kind)

    def _read_format(self):
        format = self._read_line()
        if format != FORMAT_ONE:
            raise errors.UnknownContainerFormatError(format)

    def validate(self):
        """Validate this container and its records.

        You can either validate or iter_records, you can't do both.

        :raises ContainerError: if something is invalid.
        """
        all_names = set()
        for record_names, read_bytes in self.iter_records():
            read_bytes(None)
            for name in record_names:
                _check_name_encoding(name)
                # Check that the name is unique.  Note that Python will refuse
                # to decode non-shortest forms of UTF-8 encoding, so there is no
                # risk that the same unicode string has been encoded two
                # different ways.
                if name in all_names:
                    raise errors.DuplicateRecordNameError(name)
                all_names.add(name)
        excess_bytes = self.reader_func(1)
        if excess_bytes != '':
            raise errors.ContainerHasExcessDataError(excess_bytes)


class BytesRecordReader(BaseReader):

    def read(self):
        """Read this record.

        You can either validate or read a record, you can't do both.

        :returns: A tuple of (names, callable).  The callable can be called
            repeatedly to obtain the bytes for the record, with a max_length
            argument.  If max_length is None, returns all the bytes.  Because
            records can be arbitrarily large, using None is not recommended
            unless you have reason to believe the content will fit in memory.
        """
        # Read the content length.
        length_line = self._read_line()
        try:
            length = int(length_line)
        except ValueError:
            raise errors.InvalidRecordError(
                "%r is not a valid length." % (length_line,))
        
        # Read the list of names.
        names = []
        while True:
            name = self._read_line()
            if name == '':
                break
            _check_name(name)
            names.append(name)

        self._remaining_length = length
        return names, self._content_reader

    def _content_reader(self, max_length):
        if max_length is None:
            length_to_read = self._remaining_length
        else:
            length_to_read = min(max_length, self._remaining_length)
        self._remaining_length -= length_to_read
        bytes = self.reader_func(length_to_read)
        if len(bytes) != length_to_read:
            raise errors.UnexpectedEndOfContainerError()
        return bytes

    def validate(self):
        """Validate this record.

        You can either validate or read, you can't do both.

        :raises ContainerError: if this record is invalid.
        """
        names, read_bytes = self.read()
        for name in names:
            _check_name_encoding(name)
        read_bytes(None)

