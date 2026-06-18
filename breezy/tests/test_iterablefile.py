# Copyright (C) 2005 Aaron Bentley, Canonical Ltd
# <aaron.bentley@utoronto.ca>
# Copyright (C) 2023 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for iterablefile."""

from breezy import tests

from ..osutils import IterableFile


class TestIterableFile(tests.TestCase):
    def test_type(self):
        self.assertRaises((TypeError, AttributeError), IterableFile, None)
        self.assertRaises((TypeError, AttributeError), IterableFile, 1)
        f = IterableFile([1])
        self.assertRaises(TypeError, f.read)

    def test_read_all(self):
        f = IterableFile([b"This ", b"is ", b"a ", b"test"])
        self.assertEqual(b"This is a test", f.read())

    def test_readlines(self):
        f = IterableFile([b"Th\nis ", b"is \n", b"a ", b"te\nst."])
        self.assertEqual(f.readlines(), [b"Th\n", b"is is \n", b"a te\n", b"st."])
        f = IterableFile([b"Th\nis ", b"is \n", b"a ", b"te\nst."])
        f.close()
        self.assertRaises(IOError, f.readlines)

    def test_readline(self):
        f = IterableFile([b"Th\nis ", b"is \n", b"a ", b"te\nst."])
        self.assertEqual(f.readline(), b"Th\n")
        self.assertEqual(f.readline(4), b"is is \n")
        f.close()
        self.assertRaises(IOError, f.readline)
        f = IterableFile(iter([b"Th\nis ", b"", b"is \n", b"a ", b"te\nst."]))
        self.assertEqual(f.readline(), b"Th\n")
        self.assertEqual(f.readline(4), b"is is \n")
        f.close()

    def test_read(self):
        f = IterableFile([b"This ", b"is ", b"", b"a ", b"test."])
        self.assertEqual(b"This is a test.", f.read())
        f = IterableFile([b"This ", b"is ", b"a ", b"test."])
        self.assertEqual(f.read(10), b"This is a ")
        self.assertEqual(f.read(10), b"test.")
        f = IterableFile([b"This ", b"is ", b"a ", b"test."])
        f.close()
        self.assertRaises(IOError, f.read, 10)
        f = IterableFile([b"This ", b"is ", b"a ", b"test."])
        self.assertEqual(b"This is a test.", f.read(100))

    def test_iter(self):
        self.assertEqual(
            list(IterableFile([b"Th\nis ", b"is \n", b"a ", b"te\nst."])),
            [b"Th\n", b"is is \n", b"a te\n", b"st."],
        )
        f = IterableFile([b"Th\nis ", b"is \n", b"a ", b"te\nst."])
        f.close()
        self.assertRaises(IOError, list, f)

    def test_next(self):
        f = IterableFile([b"This \n", b"is ", b"a ", b"test."])
        self.assertEqual(next(f), b"This \n")
        f.close()
        self.assertRaises(IOError, next, f)
        f = IterableFile([b"This \n", b"is ", b"a ", b"test.\n"])
        self.assertEqual(next(f), b"This \n")
        self.assertEqual(next(f), b"is a test.\n")
        self.assertRaises(StopIteration, next, f)
