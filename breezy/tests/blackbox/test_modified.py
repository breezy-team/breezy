# Copyright (C) 2008, 2009, 2010, 2016 Canonical Ltd
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


"""Black-box tests for 'brz modified', which shows modified files."""

from breezy.tests import TestCaseWithTransport


class TestModified(TestCaseWithTransport):
    def test_modified(self):
        """Test that 'modified' command reports modified files."""
        self._test_modified("a", "a")

    def test_modified_with_spaces(self):
        """Test that 'modified' command reports modified files with spaces in their names quoted."""
        self._test_modified("a filename with spaces", '"a filename with spaces"')

    def _test_modified(self, name, output):
        def check_modified(expected, null=False):
            command = "modified"
            if null:
                command += " --null"
            out, err = self.run_bzr(command)
            self.assertEqual(out, expected)
            self.assertEqual(err, "")

        # in empty directory, nothing modified
        tree = self.make_branch_and_tree(".")
        check_modified("")

        # with unknown file, still nothing modified
        self.build_tree_contents([(name, b"contents of %s\n" % (name.encode("utf-8")))])
        check_modified("")

        # after add, not modified
        tree.add(name)
        check_modified("")

        # after commit, not modified
        tree.commit(message=f"add {output}")
        check_modified("")

        # modify the file
        self.build_tree_contents([(name, b"changed\n")])
        check_modified(output + "\n")

        # check null seps - use the unquoted raw name here
        check_modified(name + "\0", null=True)

        # now commit the file and it's no longer modified
        tree.commit(message=f"modified {name}")
        check_modified("")

    def test_modified_directory(self):
        """Test --directory option."""
        tree = self.make_branch_and_tree("a")
        self.build_tree(["a/README"])
        tree.add("README")
        tree.commit("r1")
        self.build_tree_contents([("a/README", b"changed\n")])
        out, err = self.run_bzr(["modified", "--directory=a"])
        self.assertEqual("README\n", out)
