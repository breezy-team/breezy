# Copyright (C) 2006-2010, 2016 Canonical Ltd
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


"""Black-box tests for 'brz added', which shows newly-added files."""

from breezy.tests import TestCaseWithTransport


class TestAdded(TestCaseWithTransport):
    def test_added(self):
        """Test that 'added' command reports added files."""
        self._test_added("a", "a\n")

    def test_added_with_spaces(self):
        """Test that 'added' command reports added files with spaces in their names quoted."""
        self._test_added("a filename with spaces", '"a filename with spaces"\n')

    def test_added_null_separator(self):
        """Test that added uses its null operator properly."""
        self._test_added("a", "a\0", null=True)

    def _test_added(self, name, output, null=False):
        def check_added(expected, null=False):
            command = "added"

            if null:
                command += " --null"

            out, err = self.run_bzr(command)
            self.assertEqual(out, expected)
            self.assertEqual(err, "")

        # in empty directory, nothing added
        tree = self.make_branch_and_tree(".")
        check_added("")

        # with unknown file, still nothing added
        self.build_tree_contents(
            [(name, b"contents of %s\n" % (name.encode("utf-8"),))]
        )
        check_added("")

        # after add, shows up in list
        # bug report 20060119 by Nathan McCallum -- 'brz added' causes
        # NameError
        tree.add(name)
        check_added(output, null)

        # after commit, now no longer listed
        tree.commit(message='add "{}"'.format(name))
        check_added("")

    def test_added_directory(self):
        """Test --directory option."""
        tree = self.make_branch_and_tree("a")
        self.build_tree(["a/README"])
        tree.add("README")
        out, err = self.run_bzr(["added", "--directory=a"])
        self.assertEqual("README\n", out)
