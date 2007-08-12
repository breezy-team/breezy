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

    def test_format_patch_date(self):
        # epoch is always in utc
        self.assertEqual('1970-01-01 00:00:00 +0000',
            timestamp.format_patch_date(0))
        self.assertEqual('1970-01-01 00:00:00 +0000',
            timestamp.format_patch_date(0, 5 * 3600))
        self.assertEqual('1970-01-01 00:00:00 +0000',
            timestamp.format_patch_date(0, -5 * 3600))
        # regular timestamp with typical timezone
        self.assertEqual('2007-03-06 10:04:19 -0500',
            timestamp.format_patch_date(1173193459, -5 * 3600))
        # the timezone part is HHMM
        self.assertEqual('2007-03-06 09:34:19 -0530',
            timestamp.format_patch_date(1173193459, -5.5 * 3600))
        # timezones can be offset by single minutes (but no less)
        self.assertEqual('2007-03-06 15:05:19 +0001',
            timestamp.format_patch_date(1173193459, +1 * 60))

    def test_parse_patch_date(self):
        self.assertEqual((0, 0),
            timestamp.parse_patch_date('1970-01-01 00:00:00 +0000'))
        # even though we don't emit pre-epoch dates, we can parse them
        self.assertEqual((0, -5 * 3600),
            timestamp.parse_patch_date('1969-12-31 19:00:00 -0500'))
        self.assertEqual((0, +5 * 3600),
            timestamp.parse_patch_date('1970-01-01 05:00:00 +0500'))
        self.assertEqual((1173193459, -5 * 3600),
            timestamp.parse_patch_date('2007-03-06 10:04:19 -0500'))
        # offset of three minutes
        self.assertEqual((1173193459, +3 * 60),
            timestamp.parse_patch_date('2007-03-06 15:07:19 +0003'))
