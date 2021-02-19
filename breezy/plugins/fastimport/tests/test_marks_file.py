# Copyright (C) 2020 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Test the marks file methods."""

from __future__ import absolute_import

from .... import tests

from .. import marks_file


class TestMarksFile(tests.TestCaseWithTransport):

    def test_read(self):
        self.build_tree_contents([('marks', """\
:1 jelmer@jelmer-rev1
:2 joe@example.com-rev2
""")])
        self.assertEqual({
            b'1': b'jelmer@jelmer-rev1',
            b'2': b'joe@example.com-rev2',
            }, marks_file.import_marks('marks'))

    def test_write(self):
        marks_file.export_marks('marks', {
            b'1': b'jelmer@jelmer-rev1',
            b'2': b'joe@example.com-rev2',
            })
        self.assertFileEqual("""\
:1 jelmer@jelmer-rev1
:2 joe@example.com-rev2
""", 'marks')
