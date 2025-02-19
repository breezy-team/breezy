# Copyright (C) 2005, 2006 Canonical Ltd
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

import os

from breezy.tests import TestCaseWithTransport


class TestAncestry(TestCaseWithTransport):
    def _build_branches(self):
        a_wt = self.make_branch_and_tree("A")
        self.build_tree_contents([("A/foo", b"1111\n")])
        a_wt.add("foo")
        a_wt.commit("added foo", rev_id=b"A1")

        b_wt = a_wt.controldir.sprout("B").open_workingtree()
        self.build_tree_contents([("B/foo", b"1111\n22\n")])
        b_wt.commit("modified B/foo", rev_id=b"B1")

        self.build_tree_contents([("A/foo", b"000\n1111\n")])
        a_wt.commit("modified A/foo", rev_id=b"A2")

        a_wt.merge_from_branch(
            b_wt.branch, b_wt.last_revision(), b_wt.branch.get_rev_id(1)
        )
        a_wt.commit("merged B into A", rev_id=b"A3")
        return a_wt, b_wt

    def _check_ancestry(self, location="", result=None):
        out = self.run_bzr(["ancestry", location])[0]
        if result is not None:
            self.assertEqualDiff(result, out)
        else:
            # A2 and B1 can be in either order, because they are parallel, and
            # thus their topological order is not defined
            result = "A1\nB1\nA2\nA3\n"
            if result != out:
                result = "A1\nA2\nB1\nA3\n"
            self.assertEqualDiff(result, out)

    def test_ancestry(self):
        """Tests 'ancestry' command"""
        self._build_branches()
        os.chdir("A")
        self._check_ancestry()

    def test_ancestry_with_location(self):
        """Tests 'ancestry' command with a specified location."""
        self._build_branches()
        self._check_ancestry("A")

    def test_ancestry_with_repo_branch(self):
        """Tests 'ancestry' command with a location that is a
        repository branch.
        """
        a_tree = self._build_branches()[0]

        self.make_repository("repo", shared=True)

        a_tree.controldir.sprout("repo/A")
        self._check_ancestry("repo/A")

    def test_ancestry_with_checkout(self):
        """Tests 'ancestry' command with a location that is a
        checkout of a repository branch.
        """
        a_tree = self._build_branches()[0]
        self.make_repository("repo", shared=True)
        repo_branch = a_tree.controldir.sprout("repo/A").open_branch()
        repo_branch.create_checkout("A-checkout")
        self._check_ancestry("A-checkout")

    def test_ancestry_with_lightweight_checkout(self):
        """Tests 'ancestry' command with a location that is a
        lightweight checkout of a repository branch.
        """
        a_tree = self._build_branches()[0]
        self.make_repository("repo", shared=True)
        repo_branch = a_tree.controldir.sprout("repo/A").open_branch()
        repo_branch.create_checkout("A-checkout", lightweight=True)
        self._check_ancestry("A-checkout")

    def test_ancestry_with_truncated_checkout(self):
        """Tests 'ancestry' command with a location that is a
        checkout of a repository branch with a shortened revision history.
        """
        a_tree = self._build_branches()[0]
        self.make_repository("repo", shared=True)
        repo_branch = a_tree.controldir.sprout("repo/A").open_branch()
        repo_branch.create_checkout("A-checkout", revision_id=repo_branch.get_rev_id(2))
        self._check_ancestry("A-checkout", "A1\nA2\n")

    def test_ancestry_with_truncated_lightweight_checkout(self):
        """Tests 'ancestry' command with a location that is a lightweight
        checkout of a repository branch with a shortened revision history.
        """
        a_tree = self._build_branches()[0]
        self.make_repository("repo", shared=True)
        repo_branch = a_tree.controldir.sprout("repo/A").open_branch()
        repo_branch.create_checkout(
            "A-checkout", revision_id=repo_branch.get_rev_id(2), lightweight=True
        )
        self._check_ancestry("A-checkout", "A1\nA2\n")
