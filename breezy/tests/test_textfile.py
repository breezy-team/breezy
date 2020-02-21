# Copyright (C) 2006 Canonical Ltd
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

from io import BytesIO

from ..errors import BinaryFile
from . import TestCase, TestCaseInTempDir
from ..textfile import text_file, check_text_lines, check_text_path


class TextFile(TestCase):

    def test_text_file(self):
        s = BytesIO(b'ab' * 2048)
        self.assertEqual(text_file(s).read(), s.getvalue())
        s = BytesIO(b'a' * 1023 + b'\x00')
        self.assertRaises(BinaryFile, text_file, s)
        s = BytesIO(b'a' * 1024 + b'\x00')
        self.assertEqual(text_file(s).read(), s.getvalue())

    def test_check_text_lines(self):
        lines = [b'ab' * 2048]
        check_text_lines(lines)
        lines = [b'a' * 1023 + b'\x00']
        self.assertRaises(BinaryFile, check_text_lines, lines)


class TextPath(TestCaseInTempDir):

    def test_text_file(self):
        with open('boo', 'wb') as f:
            f.write(b'ab' * 2048)
        check_text_path('boo')
        with open('boo', 'wb') as f:
            f.write(b'a' * 1023 + b'\x00')
        self.assertRaises(BinaryFile, check_text_path, 'boo')
