# Copyright (C) 2011-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for the unpeel map."""

from io import BytesIO

from ...tests import (
    TestCaseWithTransport,
    )

from ..unpeel_map import (
    UnpeelMap,
    )


class TestUnpeelMap(TestCaseWithTransport):

    def test_new(self):
        m = UnpeelMap()
        self.assertIs(None, m.peel_tag("ab" * 20))

    def test_load(self):
        f = BytesIO(
            b"unpeel map version 1\n"
            b"0123456789012345678901234567890123456789: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n")
        m = UnpeelMap()
        m.load(f)
        self.assertEqual(b"0123456789012345678901234567890123456789",
                         m.peel_tag(b"aa" * 20))

    def test_update(self):
        m = UnpeelMap()
        m.update({
            b"0123456789012345678901234567890123456789": set([b"aa" * 20]),
            })
        self.assertEqual(b"0123456789012345678901234567890123456789",
                         m.peel_tag(b"aa" * 20))
