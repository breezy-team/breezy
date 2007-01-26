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

"""Tests for indirect branch urls through Launchpad.net"""

from bzrlib import (
    transport,
    )
from bzrlib.transport import get_transport
from bzrlib.tests import TestCase, TestSkipped

class IndirectUrlTests(TestCase):

    def test_indirect_through_url(self):
        """A launchpad url should map to a http url"""
        # These can change to use the smartserver protocol or something 
        # else in the future.
        url = 'lp:///plone'
        t = get_transport(url)
        real_url = t.base
        self.assertStartsWith(real_url, 'http')

