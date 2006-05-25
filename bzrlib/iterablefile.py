# Copyright (C) 2005 Aaron Bentley
# <aaron.bentley@utoronto.ca>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import doctest

class IterableFileBase(object):
    """Create a file-like object from any iterable"""

    def __init__(self, iterable):
        object.__init__(self)
        self._iter = iterable.__iter__()
        self._buffer = ""
        self.done = False

    def read_n(self, length):
        """
        >>> IterableFileBase(['This ', 'is ', 'a ', 'test.']).read_n(8)
        'This is '
        """
        def test_length(result):
            if len(result) >= length:
                return length
            else:
                return None
        return self._read(test_length)

    def read_to(self, sequence, length=None):
        """
        >>> f = IterableFileBase(['Th\\nis ', 'is \\n', 'a ', 'te\\nst.'])
        >>> f.read_to('\\n')
        'Th\\n'
        >>> f.read_to('\\n')
        'is is \\n'
        """
        def test_contents(result):
            if length is not None:
                if len(result) >= length:
                    return length
            try:
                return result.index(sequence)+len(sequence)
            except ValueError:
                return None
        return self._read(test_contents)

    def _read(self, result_length):
        """
        Read data until result satisfies the condition result_length.
        result_length is a callable that returns None until the condition
        is satisfied, and returns the length of the result to use when
        the condition is satisfied.  (i.e. it returns the length of the
        subset of the first condition match.)
        """
        result = self._buffer
        while result_length(result) is None:
            try:
                result += self._iter.next()
            except StopIteration:
                self.done = True
                self._buffer = ""
                return result
        output_length = result_length(result)
        self._buffer = result[output_length:]
        return result[:output_length]

    def read_all(self):
        """
        >>> IterableFileBase(['This ', 'is ', 'a ', 'test.']).read_all()
        'This is a test.'
        """
        def no_stop(result):
            return None
        return self._read(no_stop)


    def push_back(self, contents):
        """
        >>> f = IterableFileBase(['Th\\nis ', 'is \\n', 'a ', 'te\\nst.'])
        >>> f.read_to('\\n')
        'Th\\n'
        >>> f.push_back("Sh")
        >>> f.read_all()
        'Shis is \\na te\\nst.'
        """
        self._buffer = contents + self._buffer


class IterableFile(object):
    """This class supplies all File methods that can be implemented cheaply."""
    def __init__(self, iterable):
        object.__init__(self)
        self._file_base = IterableFileBase(iterable)
        self._iter = self._make_iterator()
        self._closed = False
        self.softspace = 0

    def _make_iterator(self):
        while not self._file_base.done:
            self._check_closed()
            result = self._file_base.read_to('\n')
            if result != '':
                yield result

    def _check_closed(self):
        if self.closed:
            raise ValueError("File is closed.")

    def close(self):
        """
        >>> f = IterableFile(['This ', 'is ', 'a ', 'test.'])
        >>> f.closed
        False
        >>> f.close()
        >>> f.closed
        True
        """
        self._file_base.done = True
        self._closed = True

    closed = property(lambda x: x._closed)

    def flush(self):
        """No-op for standard compliance.
        >>> f = IterableFile([])
        >>> f.close()
        >>> f.flush()
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        self._check_closed()

    def next(self):
        """Implementation of the iterator protocol's next()

        >>> f = IterableFile(['This \\n', 'is ', 'a ', 'test.'])
        >>> f.next()
        'This \\n'
        >>> f.close()
        >>> f.next()
        Traceback (most recent call last):
        ValueError: File is closed.
        >>> f = IterableFile(['This \\n', 'is ', 'a ', 'test.\\n'])
        >>> f.next()
        'This \\n'
        >>> f.next()
        'is a test.\\n'
        >>> f.next()
        Traceback (most recent call last):
        StopIteration
        """
        self._check_closed()
        return self._iter.next()

    def __iter__(self):
        """
        >>> list(IterableFile(['Th\\nis ', 'is \\n', 'a ', 'te\\nst.']))
        ['Th\\n', 'is is \\n', 'a te\\n', 'st.']
        >>> f = IterableFile(['Th\\nis ', 'is \\n', 'a ', 'te\\nst.'])
        >>> f.close()
        >>> list(f)
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        return self

    def read(self, length=None):
        """
        >>> IterableFile(['This ', 'is ', 'a ', 'test.']).read()
        'This is a test.'
        >>> f = IterableFile(['This ', 'is ', 'a ', 'test.'])
        >>> f.read(10)
        'This is a '
        >>> f = IterableFile(['This ', 'is ', 'a ', 'test.'])
        >>> f.close()
        >>> f.read(10)
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        self._check_closed()
        if length is None:
            return self._file_base.read_all()
        else:
            return self._file_base.read_n(length)

    def read_to(self, sequence, size=None):
        """
        Read characters until a sequence is found, with optional max size.
        The specified sequence, if found, will be included in the result

        >>> f = IterableFile(['Th\\nis ', 'is \\n', 'a ', 'te\\nst.'])
        >>> f.read_to('i')
        'Th\\ni'
        >>> f.read_to('i')
        's i'
        >>> f.close()
        >>> f.read_to('i')
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        self._check_closed()
        return self._file_base.read_to(sequence, size)

    def readline(self, size=None):
        """
        >>> f = IterableFile(['Th\\nis ', 'is \\n', 'a ', 'te\\nst.'])
        >>> f.readline()
        'Th\\n'
        >>> f.readline(4)
        'is i'
        >>> f.close()
        >>> f.readline()
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        return self.read_to('\n', size)

    def readlines(self, sizehint=None):
        """
        >>> f = IterableFile(['Th\\nis ', 'is \\n', 'a ', 'te\\nst.'])
        >>> f.readlines()
        ['Th\\n', 'is is \\n', 'a te\\n', 'st.']
        >>> f = IterableFile(['Th\\nis ', 'is \\n', 'a ', 'te\\nst.'])
        >>> f.close()
        >>> f.readlines()
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        lines = []
        while True:
            line = self.readline()
            if line == "":
                return lines
            if sizehint is None:
                lines.append(line)
            elif len(line) < sizehint:
                lines.append(line)
                sizehint -= len(line)
            else:
                self._file_base.push_back(line)
                return lines

        
if __name__ == "__main__":
    doctest.testmod()
