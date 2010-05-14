# Copyright (C) 2005-2010 Canonical Ltd
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

"""Tests for test fixtures"""

import codecs

from bzrlib import (
    tests,
    )
from bzrlib.tests import (
    fixtures,
    )


class TestTestFixtures(tests.TestCase):

    def test_unicode_factory(self):
        unicode_factory = fixtures.UnicodeFactory()
        ss1 = unicode_factory.choose_short_string()
        self.assertIsInstance(ss1,
            unicode)
        # default version should return something that's not representable in
        # ascii
        self.assertRaises(UnicodeEncodeError,
            ss1.encode, 'ascii')

        # the encoding chosen by the factory is supported by Python
        codecs.lookup(unicode_factory.choose_encoding())
