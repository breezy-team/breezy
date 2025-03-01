# Copyright (C) 2007, 2009, 2010, 2011, 2016 Canonical Ltd
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

import random
import time

from breezy import tests, timestamp
from breezy.osutils import local_time_offset


class TestPatchHeader(tests.TestCase):
    def test_format_patch_date(self):
        # epoch is always in utc
        self.assertEqual("1970-01-01 00:00:00 +0000", timestamp.format_patch_date(0))
        self.assertEqual(
            "1970-01-01 00:00:00 +0000", timestamp.format_patch_date(0, 5 * 3600)
        )
        self.assertEqual(
            "1970-01-01 00:00:00 +0000", timestamp.format_patch_date(0, -5 * 3600)
        )
        # regular timestamp with typical timezone
        self.assertEqual(
            "2007-03-06 10:04:19 -0500",
            timestamp.format_patch_date(1173193459, -5 * 3600),
        )
        # the timezone part is HHMM
        self.assertEqual(
            "2007-03-06 09:34:19 -0530",
            timestamp.format_patch_date(1173193459, -5.5 * 3600),
        )
        # timezones can be offset by single minutes (but no less)
        self.assertEqual(
            "2007-03-06 15:05:19 +0001",
            timestamp.format_patch_date(1173193459, +1 * 60),
        )

    def test_parse_patch_date(self):
        self.assertEqual(
            (0, 0), timestamp.parse_patch_date("1970-01-01 00:00:00 +0000")
        )
        # even though we don't emit pre-epoch dates, we can parse them
        self.assertEqual(
            (0, -5 * 3600), timestamp.parse_patch_date("1969-12-31 19:00:00 -0500")
        )
        self.assertEqual(
            (0, +5 * 3600), timestamp.parse_patch_date("1970-01-01 05:00:00 +0500")
        )
        self.assertEqual(
            (1173193459, -5 * 3600),
            timestamp.parse_patch_date("2007-03-06 10:04:19 -0500"),
        )
        # offset of three minutes
        self.assertEqual(
            (1173193459, +3 * 60),
            timestamp.parse_patch_date("2007-03-06 15:07:19 +0003"),
        )
        # No space between time and offset
        self.assertEqual(
            (1173193459, -5 * 3600),
            timestamp.parse_patch_date("2007-03-06 10:04:19-0500"),
        )
        # Extra spacing
        self.assertEqual(
            (1173193459, -5 * 3600),
            timestamp.parse_patch_date("2007-03-06     10:04:19     -0500"),
        )

    def test_parse_patch_date_bad(self):
        self.assertRaises(ValueError, timestamp.parse_patch_date, "NOT A TIME")
        # Extra data at end
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03-06 10:04:19 -0500x"
        )
        # Missing day
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03 10:04:19 -0500"
        )
        # Missing seconds
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03-06 10:04 -0500"
        )
        # Missing offset
        self.assertRaises(ValueError, timestamp.parse_patch_date, "2007-03-06 10:04:19")
        # Missing plus or minus in offset
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03-06 10:04:19 0500"
        )
        # Invalid hour in offset
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03-06 10:04:19 +2400"
        )
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03-06 10:04:19 -2400"
        )
        # Invalid minute in offset
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03-06 10:04:19 -0560"
        )
        # Too many digits in offset
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03-06 10:04:19 79500"
        )
        # Minus sign in middle of offset
        self.assertRaises(
            ValueError, timestamp.parse_patch_date, "2007-03-06 10:04:19 +05-5"
        )


class UnpackHighresDateTests(tests.TestCase):
    def test_unpack_highres_date(self):
        self.assertEqual(
            (1120153132.3508501, -18000),
            timestamp.unpack_highres_date("Thu 2005-06-30 12:38:52.350850105 -0500"),
        )
        self.assertEqual(
            (1120153132.3508501, 0),
            timestamp.unpack_highres_date("Thu 2005-06-30 17:38:52.350850105 +0000"),
        )
        self.assertEqual(
            (1120153132.3508501, 7200),
            timestamp.unpack_highres_date("Thu 2005-06-30 19:38:52.350850105 +0200"),
        )
        self.assertEqual(
            (1152428738.867522, 19800),
            timestamp.unpack_highres_date("Sun 2006-07-09 12:35:38.867522001 +0530"),
        )

    def test_random(self):
        t = time.time()
        o = local_time_offset()
        t2, o2 = timestamp.unpack_highres_date(timestamp.format_highres_date(t, o))
        self.assertEqual(t, t2)
        self.assertEqual(o, o2)
        t -= 24 * 3600 * 365 * 2  # Start 2 years ago
        o = -12 * 3600
        for _count in range(500):
            t += random.random() * 24 * 3600 * 30
            try:
                time.gmtime(t + o)
            except (OverflowError, ValueError):
                # We've reached the maximum for time_t on this platform
                break
            if time.localtime(t).tm_year > 9998:
                # strptime doesn't always understand years with more than 4
                # digits.
                break
            # Add 1 wrap around from [-12, 12]
            o = ((o / 3600 + 13) % 25 - 12) * 3600
            date = timestamp.format_highres_date(t, o)
            t2, o2 = timestamp.unpack_highres_date(date)
            self.assertEqual(
                t, t2, "Failed on date {!r}, {},{} diff:{}".format(date, t, o, t2 - t)
            )
            self.assertEqual(
                o, o2, "Failed on date {!r}, {},{} diff:{}".format(date, t, o, t2 - t)
            )
