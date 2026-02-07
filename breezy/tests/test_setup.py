# Copyright (C) 2005, 2006, 2008-2011 Canonical Ltd
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

"""Test for setup.py build process."""

from packaging import version

from .. import tests


class TestDistutilsVersion(tests.TestCase):
    """Tests for version comparison utilities used in setup.py."""

    def test_version_with_string(self):
        """Test version comparison for pyrex-specific version strings."""
        # We really care about two pyrex specific versions and our ability to
        # detect them
        self.assertLess(version.Version("0.9.4.1"), version.Version("0.17.beta1"))
        self.assertLess(version.Version("0.9.6.3"), version.Version("0.10"))
