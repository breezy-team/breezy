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

from bzrlib import (
    tests,
    timestamp,
    )

class TestPatchHeader(tests.TestCase):

    def test_encode_patch_date(self):
        self.assertEqual('1970-01-01 00:00:00 +0000',
            timestamp.patch_header_date(0))
        self.assertEqual('1970-01-01 05:00:00 +0500',
            timestamp.patch_header_date(0, 5 * 3600))
        self.assertEqual('1969-12-31 19:00:00 -0500',
            timestamp.patch_header_date(0, -5 * 3600))
        self.assertEqual('1969-12-31 19:00:00 -0500',
            timestamp.patch_header_date(0, -5 * 3600))
        self.assertEqual('2007-03-06 10:04:19 -0500',
            timestamp.patch_header_date(1173193459, -5 * 3600))

    def test_parse_patch_date(self):
        self.assertEqual((0, 0),
            timestamp.parse_patch_date('1970-01-01 00:00:00 +0000'))
        self.assertEqual((0, -5 * 3600),
            timestamp.parse_patch_date('1969-12-31 19:00:00 -0500'))
        self.assertEqual((0, +5 * 3600),
            timestamp.parse_patch_date('1970-01-01 05:00:00 +0500'))
        self.assertEqual((1173193459, -5 * 3600),
            timestamp.parse_patch_date('2007-03-06 10:04:19 -0500'))
