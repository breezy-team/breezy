# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

"""Tests for directory lookup through Launchpad.net."""

from ... import transport
from ...branch import Branch
from ...directory_service import directories
from ...tests import TestCaseWithMemoryTransport
from . import _register_directory


class DirectoryOpenBranchTests(TestCaseWithMemoryTransport):
    """Test cases for directory service branch opening."""

    def test_directory_open_branch(self):
        """Test that opening an lp: branch redirects to the real location."""
        # Test that opening an lp: branch redirects to the real location.
        target_branch = self.make_branch("target")

        class FooService:
            """A directory service that maps the name to a FILE url."""

            def look_up(self, name, url, purpose=None):
                if url == "lp:///apt":
                    return target_branch.base.rstrip("/")
                return "!unexpected look_up value!"

        directories.remove("lp:")
        directories.register("lp:", FooService, "Map lp URLs to local urls")
        self.addCleanup(_register_directory)
        self.addCleanup(directories.remove, "lp:")
        t = transport.get_transport("lp:///apt")
        branch = Branch.open_from_transport(t)
        self.assertEqual(target_branch.base, branch.base)
