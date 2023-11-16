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

"""Tests for Branch.iter_merge_sorted_revisions()."""

from breezy import errors, tests
from breezy.tests import per_branch


class TestIterMergeSortedRevisionsSimpleGraph(per_branch.TestCaseWithBranch):
    def setUp(self):
        super().setUp()
        self.revids = {}
        builder = self.make_builder_with_merges(".")
        self.branch = builder.get_branch()
        self.branch.lock_read()
        self.addCleanup(self.branch.unlock)

    def make_snapshot(self, builder, parents, revid_name):
        self.assertNotIn(revid_name, self.revids)
        if parents is None:
            files = [
                ("add", ("", None, "directory", "")),
            ]
        else:
            parents = [self.revids[name] for name in parents]
            files = []
        self.revids[revid_name] = builder.build_snapshot(
            parents, files, message=f"Revision {revid_name}"
        )

    def make_builder_with_merges(self, relpath):
        try:
            builder = self.make_branch_builder(relpath)
        except (errors.TransportNotPossible, errors.UninitializableFormat) as e:
            raise tests.TestNotApplicable("format not directly constructable") from e
        builder.start_series()
        # 1
        # |\
        # 2 |
        # | |
        # | 1.1.1
        # |/
        # 3
        self.make_snapshot(builder, None, "1")
        self.make_snapshot(builder, ["1"], "1.1.1")
        self.make_snapshot(builder, ["1"], "2")
        self.make_snapshot(builder, ["2", "1.1.1"], "3")
        builder.finish_series()
        return builder

    def assertIterRevids(self, expected, *args, **kwargs):
        if kwargs.get("stop_revision_id") is not None:
            kwargs["stop_revision_id"] = self.revids[kwargs["stop_revision_id"]]
        if kwargs.get("start_revision_id") is not None:
            kwargs["start_revision_id"] = self.revids[kwargs["start_revision_id"]]
        # We don't care about depths and revnos here, only about returning the
        # right revids.
        revids = [
            revid
            for (revid, depth, revno, eom) in self.branch.iter_merge_sorted_revisions(
                *args, **kwargs
            )
        ]
        self.assertEqual([self.revids[short] for short in expected], revids)

    def test_merge_sorted(self):
        self.assertIterRevids(["3", "1.1.1", "2", "1"])

    def test_merge_sorted_range(self):
        self.assertIterRevids(
            ["1.1.1"], start_revision_id="1.1.1", stop_revision_id="1"
        )

    def test_merge_sorted_range_start_only(self):
        self.assertIterRevids(["1.1.1", "1"], start_revision_id="1.1.1")

    def test_merge_sorted_range_stop_exclude(self):
        self.assertIterRevids(["3", "1.1.1", "2"], stop_revision_id="1")

    def test_merge_sorted_range_stop_include(self):
        self.assertIterRevids(
            ["3", "1.1.1", "2"], stop_revision_id="2", stop_rule="include"
        )

    def test_merge_sorted_range_stop_with_merges(self):
        self.assertIterRevids(
            ["3", "1.1.1"], stop_revision_id="3", stop_rule="with-merges"
        )

    def test_merge_sorted_range_stop_with_merges_can_show_non_parents(self):
        # 1.1.1 gets logged before the end revision is reached.
        # so it is returned even though 1.1.1 is not a parent of 2.
        self.assertIterRevids(
            ["3", "1.1.1", "2"], stop_revision_id="2", stop_rule="with-merges"
        )

    def test_merge_sorted_range_stop_with_merges_ignore_non_parents(self):
        # 2 is not a parent of 1.1.1 so it must not be returned
        self.assertIterRevids(
            ["3", "1.1.1"], stop_revision_id="1.1.1", stop_rule="with-merges"
        )

    def test_merge_sorted_single_stop_exclude(self):
        # from X..X exclusive is an empty result
        self.assertIterRevids([], start_revision_id="3", stop_revision_id="3")

    def test_merge_sorted_single_stop_include(self):
        # from X..X inclusive is [X]
        self.assertIterRevids(
            ["3"], start_revision_id="3", stop_revision_id="3", stop_rule="include"
        )

    def test_merge_sorted_single_stop_with_merges(self):
        self.assertIterRevids(
            ["3", "1.1.1"],
            start_revision_id="3",
            stop_revision_id="3",
            stop_rule="with-merges",
        )

    def test_merge_sorted_forward(self):
        self.assertIterRevids(["1", "2", "1.1.1", "3"], direction="forward")

    def test_merge_sorted_range_forward(self):
        self.assertIterRevids(
            ["1.1.1"],
            start_revision_id="1.1.1",
            stop_revision_id="1",
            direction="forward",
        )

    def test_merge_sorted_range_start_only_forward(self):
        self.assertIterRevids(
            ["1", "1.1.1"], start_revision_id="1.1.1", direction="forward"
        )

    def test_merge_sorted_range_stop_exclude_forward(self):
        self.assertIterRevids(
            ["2", "1.1.1", "3"], stop_revision_id="1", direction="forward"
        )

    def test_merge_sorted_range_stop_include_forward(self):
        self.assertIterRevids(
            ["2", "1.1.1", "3"],
            stop_revision_id="2",
            stop_rule="include",
            direction="forward",
        )

    def test_merge_sorted_range_stop_with_merges_forward(self):
        self.assertIterRevids(
            ["1.1.1", "3"],
            stop_revision_id="3",
            stop_rule="with-merges",
            direction="forward",
        )


class TestIterMergeSortedRevisionsBushyGraph(per_branch.TestCaseWithBranch):
    def setUp(self):
        super().setUp()
        self.revids = {}

    def make_branch_builder(self, relpath):
        try:
            builder = super().make_branch_builder(relpath)
        except (errors.TransportNotPossible, errors.UninitializableFormat) as e:
            raise tests.TestNotApplicable("format not directly constructable") from e
        return builder

    def make_snapshot(self, builder, parents, revid_name):
        self.assertNotIn(revid_name, self.revids)
        if parents is None:
            files = [
                ("add", ("", None, "directory", "")),
            ]
        else:
            parents = [self.revids[name] for name in parents]
            files = []
        self.revids[revid_name] = builder.build_snapshot(
            parents, files, message=f"Revision {revid_name}"
        )

    def make_branch_with_embedded_merges(self, relpath="."):
        builder = self.make_branch_builder(relpath)

        # 1
        # |\
        # | 1.1.1
        # | /
        # 2
        # | \
        # 3 |
        # | |
        # | 2.1.1
        # | |    \
        # | 2.1.2 |
        # | |     |
        # | |   2.2.1
        # | |  /
        # | 2.1.3
        # |/
        # 4
        builder.start_series()
        self.make_snapshot(builder, None, "1")
        self.make_snapshot(builder, ["1"], "1.1.1")
        self.make_snapshot(builder, ["1", "1.1.1"], "2")
        self.make_snapshot(builder, ["2"], "2.1.1")
        self.make_snapshot(builder, ["2.1.1"], "2.1.2")
        self.make_snapshot(builder, ["2.1.1"], "2.2.1")
        self.make_snapshot(builder, ["2.1.2", "2.2.1"], "2.1.3")
        self.make_snapshot(builder, ["2"], "3")
        self.make_snapshot(builder, ["3", "2.1.3"], "4")
        builder.finish_series()
        br = builder.get_branch()
        br.lock_read()
        self.addCleanup(br.unlock)
        return br

    def make_branch_with_different_depths_merges(self, relpath="."):
        builder = self.make_branch_builder(relpath)
        # 1
        # |\
        # | 1.1.1
        # | /
        # 2
        # | \
        # 3 |
        # | |
        # | 2.1.1
        # | |    \
        # | 2.1.2 |
        # | |     |
        # | |     2.2.1
        # | |    /
        # | 2.1.3
        # |/
        # 4
        builder.start_series()
        self.make_snapshot(builder, None, "1")
        self.make_snapshot(builder, ["1"], "2")
        self.make_snapshot(builder, ["1"], "1.1.1")
        self.make_snapshot(builder, ["1.1.1"], "1.1.2")
        self.make_snapshot(builder, ["1.1.1"], "1.2.1")
        self.make_snapshot(builder, ["1.2.1"], "1.2.2")
        self.make_snapshot(builder, ["1.2.1"], "1.3.1")
        self.make_snapshot(builder, ["1.3.1"], "1.3.2")
        self.make_snapshot(builder, ["1.3.1"], "1.4.1")
        self.make_snapshot(builder, ["1.3.2"], "1.3.3")
        self.make_snapshot(builder, ["1.2.2", "1.3.3"], "1.2.3")
        self.make_snapshot(builder, ["2"], "2.1.1")
        self.make_snapshot(builder, ["2.1.1"], "2.1.2")
        self.make_snapshot(builder, ["2.1.1"], "2.2.1")
        self.make_snapshot(builder, ["2.1.2", "2.2.1"], "2.1.3")
        self.make_snapshot(builder, ["2", "1.2.3"], "3")
        # .. to bring them all and ... bind them
        self.make_snapshot(builder, ["3", "2.1.3"], "4")
        builder.finish_series()
        br = builder.get_branch()
        br.lock_read()
        self.addCleanup(br.unlock)
        return br

    def make_branch_with_alternate_ancestries(self, relpath="."):
        # See test_merge_sorted_exclude_ancestry below for the difference with
        # bt.test_log.TestLogExcludeAncestry.
        # make_branch_with_alternate_ancestries and
        # test_merge_sorted_exclude_ancestry
        # See the FIXME in assertLogRevnos there too.
        builder = self.make_branch_builder(relpath)
        # 1
        # |\
        # | 1.1.1
        # | /| \
        # 2  |  |
        # |  |  1.2.1
        # |  | /
        # |  1.1.2
        # | /
        # 3
        builder.start_series()
        self.make_snapshot(builder, None, "1")
        self.make_snapshot(builder, ["1"], "1.1.1")
        self.make_snapshot(builder, ["1", "1.1.1"], "2")
        self.make_snapshot(builder, ["1.1.1"], "1.2.1")
        self.make_snapshot(builder, ["1.1.1", "1.2.1"], "1.1.2")
        self.make_snapshot(builder, ["2", "1.1.2"], "3")
        builder.finish_series()
        br = builder.get_branch()
        br.lock_read()
        self.addCleanup(br.unlock)
        return br

    def assertIterRevids(self, expected, branch, *args, **kwargs):
        if kwargs.get("stop_revision_id") is not None:
            kwargs["stop_revision_id"] = self.revids[kwargs["stop_revision_id"]]
        if kwargs.get("start_revision_id") is not None:
            kwargs["start_revision_id"] = self.revids[kwargs["start_revision_id"]]
        # We don't care about depths and revnos here, only about returning the
        # right revids.
        revids = [
            revid
            for (revid, depth, revno, eom) in branch.iter_merge_sorted_revisions(
                *args, **kwargs
            )
        ]
        self.assertEqual([self.revids[short] for short in expected], revids)

    def test_merge_sorted_starting_at_embedded_merge(self):
        branch = self.make_branch_with_embedded_merges()
        self.assertIterRevids(
            ["4", "2.1.3", "2.2.1", "2.1.2", "2.1.1", "3", "2", "1.1.1", "1"], branch
        )
        # 3 and 2.1.2 are not part of 2.2.1 ancestry and should not appear
        self.assertIterRevids(
            ["2.2.1", "2.1.1", "2", "1.1.1", "1"],
            branch,
            start_revision_id="2.2.1",
            stop_rule="with-merges",
        )

    def test_merge_sorted_with_different_depths_merge(self):
        branch = self.make_branch_with_different_depths_merges()
        self.assertIterRevids(
            [
                "4",
                "2.1.3",
                "2.2.1",
                "2.1.2",
                "2.1.1",
                "3",
                "1.2.3",
                "1.3.3",
                "1.3.2",
                "1.3.1",
                "1.2.2",
                "1.2.1",
                "1.1.1",
                "2",
                "1",
            ],
            branch,
        )
        # 3 (and its descendants) and 2.1.2 are not part of 2.2.1 ancestry and
        # should not appear
        self.assertIterRevids(
            ["2.2.1", "2.1.1", "2", "1"],
            branch,
            start_revision_id="2.2.1",
            stop_rule="with-merges",
        )

    def test_merge_sorted_exclude_ancestry(self):
        branch = self.make_branch_with_alternate_ancestries()
        self.assertIterRevids(["3", "1.1.2", "1.2.1", "2", "1.1.1", "1"], branch)
        # '2' is not part of the ancestry even if merge_sort order will make it
        # appear before 1.1.1
        self.assertIterRevids(
            ["1.1.2", "1.2.1"],
            branch,
            stop_rule="with-merges-without-common-ancestry",
            start_revision_id="1.1.2",
            stop_revision_id="1.1.1",
        )
