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


from breezy import (
    tests,
    )
from breezy.bzr import timestamp
from breezy.osutils import local_time_offset


class UnpackHighresDateTests(tests.TestCase):

    def test_unpack_highres_date(self):
        self.assertEqual(
            (1120153132.3508501, -18000),
            timestamp.unpack_highres_date(
                'Thu 2005-06-30 12:38:52.350850105 -0500'))
        self.assertEqual(
            (1120153132.3508501, 0),
            timestamp.unpack_highres_date(
                'Thu 2005-06-30 17:38:52.350850105 +0000'))
        self.assertEqual(
            (1120153132.3508501, 7200),
            timestamp.unpack_highres_date(
                'Thu 2005-06-30 19:38:52.350850105 +0200'))
        self.assertEqual(
            (1152428738.867522, 19800),
            timestamp.unpack_highres_date(
                'Sun 2006-07-09 12:35:38.867522001 +0530'))

    def test_random(self):
        t = time.time()
        o = local_time_offset()
        t2, o2 = timestamp.unpack_highres_date(
            timestamp.format_highres_date(t, o))
        self.assertEqual(t, t2)
        self.assertEqual(o, o2)
        t -= 24 * 3600 * 365 * 2  # Start 2 years ago
        o = -12 * 3600
        for count in range(500):
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
                t, t2,
                'Failed on date %r, %s,%s diff:%s' % (date, t, o, t2 - t))
            self.assertEqual(
                o, o2,
                'Failed on date %r, %s,%s diff:%s' % (date, t, o, t2 - t))
