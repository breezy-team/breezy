# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Tests for Launchpad URI handling."""

from ...tests import TestCase
from . import uris


class TestWebRootForServiceRoot(TestCase):
    """Tests for web root service root conversion."""

    def test_simple(self):
        """Test simple web root for service root conversion."""
        self.assertEqual(
            "https://launchpad.net",
            uris.web_root_for_service_root("https://api.launchpad.net/"),
        )
        self.assertEqual(
            "https://beta.launchpad.net",
            uris.web_root_for_service_root("https://api.beta.launchpad.net/"),
        )
