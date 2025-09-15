# Copyright (C) 2007-2010, 2016 Canonical Ltd
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


"""Black-box tests for 'brz unknowns', which shows unknown files."""

from breezy.tests import TestCaseWithTransport


class TestUnknowns(TestCaseWithTransport):
    def test_unknowns(self):
        """Test that 'unknown' command reports unknown files."""
        # in empty directory, no unknowns
        tree = self.make_branch_and_tree(".")
        self.assertEqual(self.run_bzr("unknowns")[0], "")

        # single unknown file
        self.build_tree_contents([("a", b"contents of a\n")])
        self.assertEqual(self.run_bzr("unknowns")[0], "a\n")

        # multiple unknown files, including one with a space in its name
        self.build_tree(["b", "c", "d e"])
        self.assertEqual(self.run_bzr("unknowns")[0], 'a\nb\nc\n"d e"\n')

        # after add, file no longer shown
        tree.add(["a", "d e"])
        self.assertEqual(self.run_bzr("unknowns")[0], "b\nc\n")

        # after all added, none shown
        tree.add(["b", "c"])
        self.assertEqual(self.run_bzr("unknowns")[0], "")

    def test_unknowns_directory(self):
        """Test --directory option."""
        self.make_branch_and_tree("a")
        self.build_tree(["a/README"])
        out, _err = self.run_bzr(["unknowns", "--directory=a"])
        self.assertEqual("README\n", out)
