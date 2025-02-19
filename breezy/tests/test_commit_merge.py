# Copyright (C) 2005, 2006, 2007, 2009, 2010, 2011, 2016 Canonical Ltd
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

from .. import check, osutils
from ..commit import PointlessCommit
from . import TestCaseWithTransport
from .features import SymlinkFeature
from .matchers import RevisionHistoryMatches


class TestCommitMerge(TestCaseWithTransport):
    """Tests for committing the results of a merge.

    These don't currently test the merge code, which is intentional to
    reduce the scope of testing.  We just mark the revision as merged
    without bothering about the contents much.
    """

    def test_merge_commit_empty(self):
        """Simple commit of two-way merge of empty trees."""
        wtx = self.make_branch_and_tree("x")
        base_rev = wtx.commit("common parent")
        bx = wtx.branch
        wty = wtx.controldir.sprout("y").open_workingtree()
        by = wty.branch

        wtx.commit("commit one", rev_id=b"x@u-0-1", allow_pointless=True)
        wty.commit("commit two", rev_id=b"y@u-0-1", allow_pointless=True)

        by.fetch(bx)
        # just having the history there does nothing
        self.assertRaises(
            PointlessCommit,
            wty.commit,
            "no changes yet",
            rev_id=b"y@u-0-2",
            allow_pointless=False,
        )
        wty.merge_from_branch(bx)
        wty.commit("merge from x", rev_id=b"y@u-0-2", allow_pointless=False)

        self.assertEqual(by.revno(), 3)
        graph = wty.branch.repository.get_graph()
        self.addCleanup(wty.lock_read().unlock)
        self.assertThat(by, RevisionHistoryMatches([base_rev, b"y@u-0-1", b"y@u-0-2"]))
        rev = by.repository.get_revision(b"y@u-0-2")
        self.assertEqual(rev.parent_ids, [b"y@u-0-1", b"x@u-0-1"])

    def test_merge_new_file(self):
        """Commit merge of two trees with no overlapping files."""
        wtx = self.make_branch_and_tree("x")
        base_rev = wtx.commit("common parent")
        bx = wtx.branch
        wtx.commit("establish root id")
        wty = wtx.controldir.sprout("y").open_workingtree()
        self.assertEqual(wtx.path2id(""), wty.path2id(""))
        by = wty.branch

        self.build_tree(["x/ecks", "y/why"])

        wtx.add(["ecks"], ids=[b"ecks-id"])
        wty.add(["why"], ids=[b"why-id"])

        wtx.commit("commit one", rev_id=b"x@u-0-1", allow_pointless=True)
        wty.commit("commit two", rev_id=b"y@u-0-1", allow_pointless=True)

        wty.merge_from_branch(bx)

        # partial commit of merges is currently not allowed, because
        # it would give different merge graphs for each file which
        # might be complex.  it can be allowed in the future.
        self.assertRaises(
            Exception,
            wty.commit,
            "partial commit",
            allow_pointless=False,
            specific_files=["ecks"],
        )

        wty.commit("merge from x", rev_id=b"y@u-0-2", allow_pointless=False)
        tree = by.repository.revision_tree(b"y@u-0-2")
        self.assertEqual(tree.get_file_revision("ecks"), b"x@u-0-1")
        self.assertEqual(tree.get_file_revision("why"), b"y@u-0-1")

        check.check_dwim(bx.base, False, True, True)
        check.check_dwim(by.base, False, True, True)

    def test_merge_with_symlink(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        tree_a = self.make_branch_and_tree("tree_a")
        os.symlink("target", osutils.pathjoin("tree_a", "link"))
        tree_a.add("link")
        tree_a.commit("added link")
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        self.build_tree(["tree_a/file"])
        tree_a.add("file")
        tree_a.commit("added file")
        self.build_tree(["tree_b/another_file"])
        tree_b.add("another_file")
        tree_b.commit("add another file")
        tree_b.merge_from_branch(tree_a.branch)
        tree_b.commit("merge")
