# Copyright (C) 2011 Jelmer Vernooij <jelmer@samba.org>
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

"""Tests for the unpeel map."""

from cStringIO import StringIO

from ....tests import (
    TestCaseWithTransport,
    )

from ..unpeel_map import (
    UnpeelMap,
    )


class TestUnpeelMap(TestCaseWithTransport):

    def test_new(self):
        m = UnpeelMap()
        self.assertIs(None, m.peel_tag("ab"* 20))

    def test_load(self):
        f = StringIO(
            "unpeel map version 1\n"
            "0123456789012345678901234567890123456789: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n")
        m = UnpeelMap()
        m.load(f)
        self.assertEquals("0123456789012345678901234567890123456789",
            m.peel_tag("aa"*20))

    def test_update(self):
        m = UnpeelMap()
        m.update({
           "0123456789012345678901234567890123456789": set(["aa" * 20]),
           })
        self.assertEquals("0123456789012345678901234567890123456789",
            m.peel_tag("aa"*20))
