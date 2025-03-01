# Copyright (C) 2006, 2007, 2009, 2012 Canonical Ltd
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

from breezy import tests


class TestRevisionHistory(tests.TestCaseWithTransport):
    def _build_branch(self):
        # setup a standalone branch with three commits
        tree = self.make_branch_and_tree("test")
        with open("test/foo", "wb") as f:
            f.write(b"1111\n")
        tree.add("foo")
        tree.commit("added foo", rev_id=b"revision_1")
        with open("test/foo", "wb") as f:
            f.write(b"2222\n")
        tree.commit("updated foo", rev_id=b"revision_2")
        with open("test/foo", "wb") as f:
            f.write(b"3333\n")
        tree.commit("updated foo again", rev_id=b"revision_3")
        return tree

    def _check_revision_history(self, location="", working_dir=None):
        rh = self.run_bzr(["revision-history", location], working_dir=working_dir)[0]
        self.assertEqual(rh, "revision_1\nrevision_2\nrevision_3\n")

    def test_revision_history(self):
        """No location."""
        self._build_branch()
        self._check_revision_history(working_dir="test")

    def test_revision_history_with_location(self):
        """With a specified location."""
        self._build_branch()
        self._check_revision_history("test")

    def test_revision_history_with_repo_branch(self):
        """With a repository branch location."""
        self._build_branch()
        self.run_bzr("init-shared-repo repo")
        self.run_bzr("branch test repo/test")
        self._check_revision_history("repo/test")

    def test_revision_history_with_checkout(self):
        """With a repository branch checkout location."""
        self._build_branch()
        self.run_bzr("init-shared-repo repo")
        self.run_bzr("branch test repo/test")
        self.run_bzr("checkout repo/test test-checkout")
        self._check_revision_history("test-checkout")

    def test_revision_history_with_lightweight_checkout(self):
        """With a repository branch lightweight checkout location."""
        self._build_branch()
        self.run_bzr("init-shared-repo repo")
        self.run_bzr("branch test repo/test")
        self.run_bzr("checkout --lightweight repo/test test-checkout")
        self._check_revision_history("test-checkout")
