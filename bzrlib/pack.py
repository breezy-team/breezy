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
    """
    # XXX: consider checking that name is a str of valid UTF-8 too?
    if _whitespace_re.search(name) is not None:
        raise errors.InvalidRecordError("%r is not a valid name." % (name,))


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

        Each yielded record will be a 2-tuple of (names, bytes), where names is
        a ``list`` and bytes is a ``str``.

        :raises UnknownContainerFormatError: if the format of the container is
            unrecognised.
        """
        format = self._read_line()
        if format != FORMAT_ONE:
            raise errors.UnknownContainerFormatError(format)
        return self._iter_records()
    
    def _iter_records(self):
        while True:
            record_kind = self.reader_func(1)
            if record_kind == 'B':
                # Bytes record.
                reader = BytesRecordReader(self.reader_func)
                yield reader.read()
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


class BytesRecordReader(BaseReader):

    def read(self):
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
        bytes = self.reader_func(length)
        if len(bytes) != length:
            raise errors.UnexpectedEndOfContainerError()
        return names, bytes

