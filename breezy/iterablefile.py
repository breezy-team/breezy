# Copyright (C) 2005 Aaron Bentley, Canonical Ltd
# <aaron.bentley@utoronto.ca>
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

# ruff: noqa: D301
# ruff: noqa: D212
# ruff: noqa: D415

from collections.abc import Callable, Iterable, Iterator


class IterableFileBase:
    """Create a file-like object from any iterable"""

    def __init__(self, iterable: Iterable[bytes]) -> None:
        object.__init__(self)
        self._iter = iter(iterable)
        self._buffer = b""
        self.done = False

    def read_n(self, length: int) -> bytes:
        """
        >>> IterableFileBase([b'This ', b'is ', b'a ', b'test.']).read_n(8)
        b'This is '
        """

        def test_length(result):
            if len(result) >= length:
                return length
            else:
                return None

        return self._read(test_length)

    def read_to(self, sequence: bytes, length: int | None = None) -> bytes:
        """
        >>> f = IterableFileBase([b'Th\\nis ', b'is \\n', b'a ', b'te\\nst.'])
        >>> f.read_to(b'\\n')
        b'Th\\n'
        >>> f.read_to(b'\\n')
        b'is is \\n'
        """

        def test_contents(result):
            if length is not None:
                if len(result) >= length:
                    return length
            try:
                return result.index(sequence) + len(sequence)
            except ValueError:
                return None

        return self._read(test_contents)

    def _read(self, result_length: Callable[[bytes], int | None]) -> bytes:
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
                result += next(self._iter)
            except StopIteration:
                self.done = True
                self._buffer = b""
                return result
        output_length = result_length(result)
        self._buffer = result[output_length:]
        return result[:output_length]

    def read_all(self) -> bytes:
        """
        >>> IterableFileBase([b'This ', b'is ', b'a ', b'test.']).read_all()
        b'This is a test.'
        """

        def no_stop(result):
            return None

        return self._read(no_stop)

    def push_back(self, contents: bytes) -> None:
        """
        >>> f = IterableFileBase([b'Th\\nis ', b'is \\n', b'a ', b'te\\nst.'])
        >>> f.read_to(b'\\n')
        b'Th\\n'
        >>> f.push_back(b"Sh")
        >>> f.read_all()
        b'Shis is \\na te\\nst.'
        """
        self._buffer = contents + self._buffer


class IterableFile:
    """This class supplies all File methods that can be implemented cheaply."""

    def __init__(self, iterable: Iterable[bytes]) -> None:
        object.__init__(self)
        self._file_base = IterableFileBase(iterable)
        self._iter = self._make_iterator()
        self._closed = False
        self.softspace = 0

    def _make_iterator(self) -> Iterator[bytes]:
        while not self._file_base.done:
            self._check_closed()
            result = self._file_base.read_to(b"\n")
            if result != b"":
                yield result

    def _check_closed(self):
        if self.closed:
            raise ValueError("File is closed.")

    def close(self) -> None:
        """
        >>> f = IterableFile([b'This ', b'is ', b'a ', b'test.'])
        >>> f.closed
        False
        >>> f.close()
        >>> f.closed
        True
        """
        self._file_base.done = True
        self._closed = True

    closed = property(lambda x: x._closed)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # If there was an error raised, prefer the original one
        try:
            self.close()
        except BaseException:
            if exc_type is None:
                raise
        return False

    def flush(self) -> None:
        """No-op for standard compliance.
        >>> f = IterableFile([])
        >>> f.close()
        >>> f.flush()
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        self._check_closed()

    def __next__(self) -> bytes:
        """Implementation of the iterator protocol's next()

        >>> f = IterableFile([b'This \\n', b'is ', b'a ', b'test.'])
        >>> next(f)
        b'This \\n'
        >>> f.close()
        >>> next(f)
        Traceback (most recent call last):
        ValueError: File is closed.
        >>> f = IterableFile([b'This \\n', b'is ', b'a ', b'test.\\n'])
        >>> next(f)
        b'This \\n'
        >>> next(f)
        b'is a test.\\n'
        >>> next(f)
        Traceback (most recent call last):
        StopIteration
        """
        self._check_closed()
        return next(self._iter)

    def __iter__(self) -> Iterator[bytes]:
        """
        >>> list(IterableFile([b'Th\\nis ', b'is \\n', b'a ', b'te\\nst.']))
        [b'Th\\n', b'is is \\n', b'a te\\n', b'st.']
        >>> f = IterableFile([b'Th\\nis ', b'is \\n', b'a ', b'te\\nst.'])
        >>> f.close()
        >>> list(f)
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        return self

    def read(self, length: int | None = None) -> bytes:
        """
        >>> IterableFile([b'This ', b'is ', b'a ', b'test.']).read()
        b'This is a test.'
        >>> f = IterableFile([b'This ', b'is ', b'a ', b'test.'])
        >>> f.read(10)
        b'This is a '
        >>> f = IterableFile([b'This ', b'is ', b'a ', b'test.'])
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

    def read_to(self, sequence: bytes, size: int | None = None) -> bytes:
        """
        Read characters until a sequence is found, with optional max size.
        The specified sequence, if found, will be included in the result

        >>> f = IterableFile([b'Th\\nis ', b'is \\n', b'a ', b'te\\nst.'])
        >>> f.read_to(b'i')
        b'Th\\ni'
        >>> f.read_to(b'i')
        b's i'
        >>> f.close()
        >>> f.read_to(b'i')
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        self._check_closed()
        return self._file_base.read_to(sequence, size)

    def readline(self, size: int | None = None) -> bytes:
        """
        >>> f = IterableFile([b'Th\\nis ', b'is \\n', b'a ', b'te\\nst.'])
        >>> f.readline()
        b'Th\\n'
        >>> f.readline(4)
        b'is i'
        >>> f.close()
        >>> f.readline()
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        return self.read_to(b"\n", size)

    def readlines(self, sizehint=None) -> list[bytes]:
        """
        >>> f = IterableFile([b'Th\\nis ', b'is \\n', b'a ', b'te\\nst.'])
        >>> f.readlines()
        [b'Th\\n', b'is is \\n', b'a te\\n', b'st.']
        >>> f = IterableFile([b'Th\\nis ', b'is \\n', b'a ', b'te\\nst.'])
        >>> f.close()
        >>> f.readlines()
        Traceback (most recent call last):
        ValueError: File is closed.
        """
        lines: list[bytes] = []
        while True:
            line = self.readline()
            if line == b"":
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
    import doctest

    doctest.testmod()
