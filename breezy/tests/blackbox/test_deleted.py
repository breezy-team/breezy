# Copyright (C) 2010, 2016 Canonical Ltd
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


"""Black-box tests for 'brz deleted', which shows newly deleted files."""

from breezy.tests import TestCaseWithTransport


class TestDeleted(TestCaseWithTransport):
    def test_deleted_directory(self):
        """Test --directory option."""
        tree = self.make_branch_and_tree("a")
        self.build_tree(["a/README"])
        tree.add("README")
        tree.commit("r1")
        tree.remove("README")
        out, _err = self.run_bzr(["deleted", "--directory=a"])
        self.assertEqual("README\n", out)
