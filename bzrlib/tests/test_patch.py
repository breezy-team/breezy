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

from bzrlib.errors import BinaryFile
from bzrlib.patch import diff3
from bzrlib.tests import TestCaseInTempDir


class TestPatch(TestCaseInTempDir):

    def test_diff3_binaries(self):
        with file('this', 'wb') as f: f.write('a')
        with file('other', 'wb') as f: f.write('a')
        with file('base', 'wb') as f: f.write('\x00')
        self.assertRaises(BinaryFile, diff3, 'unused', 'this', 'other', 'base')
