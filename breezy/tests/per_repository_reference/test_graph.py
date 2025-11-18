# Copyright (C) 2011, 2016 Canonical Ltd
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


"""Tests for graph operations on stacked repositories."""

from breezy import tests, urlutils
from breezy.bzr import remote
from breezy.tests.per_repository import TestCaseWithRepository


class TestGraph(TestCaseWithRepository):
    def test_get_known_graph_ancestry_stacked(self):
        """get_known_graph_ancestry works correctly on stacking.

        See <https://bugs.launchpad.net/bugs/715000>.
        """
        branch_a, branch_b, branch_c, revid_1 = self.make_double_stacked_branches()
        for br in [branch_a, branch_b, branch_c]:
            self.assertEqual(
                [revid_1], br.repository.get_known_graph_ancestry([revid_1]).topo_sort()
            )

    def make_double_stacked_branches(self):
        wt_a = self.make_branch_and_tree("a")
        branch_a = wt_a.branch
        branch_b = self.make_branch("b")
        branch_b.set_stacked_on_url(urlutils.relative_url(branch_b.base, branch_a.base))
        branch_c = self.make_branch("c")
        branch_c.set_stacked_on_url(urlutils.relative_url(branch_c.base, branch_b.base))
        revid_1 = wt_a.commit("first commit")
        return branch_a, branch_b, branch_c, revid_1

    def make_stacked_branch_with_long_history(self):
        builder = self.make_branch_builder("source")
        builder.start_series()
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", None))], revision_id=b"A"
        )
        builder.build_snapshot([b"A"], [], revision_id=b"B")
        builder.build_snapshot([b"B"], [], revision_id=b"C")
        builder.build_snapshot([b"C"], [], revision_id=b"D")
        builder.build_snapshot([b"D"], [], revision_id=b"E")
        builder.build_snapshot([b"E"], [], revision_id=b"F")
        source_b = builder.get_branch()
        master_b = self.make_branch("master")
        master_b.pull(source_b, stop_revision=b"E")
        stacked_b = self.make_branch("stacked")
        stacked_b.set_stacked_on_url("../master")
        stacked_b.pull(source_b, stop_revision=b"F")
        builder.finish_series()
        return master_b, stacked_b

    def assertParentMapCalls(self, expected):
        """Check that self.hpss_calls has the expected get_parent_map calls."""
        get_parent_map_calls = []
        for c in self.hpss_calls:
            # Right now, the only RPCs that get called are get_parent_map. If
            # this changes in the future, we can change this to:
            # if c.call.method != 'Repository.get_parent_map':
            #    continue
            self.assertEqual(b"Repository.get_parent_map", c.call.method)
            args = c.call.args
            location = args[0]
            self.assertEqual(b"include-missing:", args[1])
            revisions = sorted(args[2:])
            get_parent_map_calls.append((location, revisions))
        self.assertEqual(expected, get_parent_map_calls)

    def test_doesnt_call_get_parent_map_on_all_fallback_revs(self):
        if not isinstance(self.repository_format, remote.RemoteRepositoryFormat):
            raise tests.TestNotApplicable("only for RemoteRepository")
        # bug #388269
        _master_b, stacked_b = self.make_stacked_branch_with_long_history()
        self.addCleanup(stacked_b.lock_read().unlock)
        self.make_repository("target_repo", shared=True)
        target_b = self.make_branch("target_repo/branch")
        self.addCleanup(target_b.lock_write().unlock)
        self.setup_smart_server_with_call_log()
        target_b.repository.search_missing_revision_ids(
            stacked_b.repository, revision_ids=[b"F"], find_ghosts=False
        )
        self.assertParentMapCalls(
            [
                # One call to stacked to start, which returns F=>E, and that E
                # itself is missing, so when we step, we won't look for it.
                (b"extra/stacked/", [b"F"]),
                # One fallback call to extra/master, which will return the rest of
                # the history.
                (b"extra/master/", [b"E"]),
                # And then one get_parent_map call to the target, to see if it
                # already has any of these revisions.
                (b"extra/target_repo/branch/", [b"A", b"B", b"C", b"D", b"E", b"F"]),
            ]
        )
        # Before bug #388269 was fixed, there would be a bunch of extra calls
        # to 'extra/stacked', ['D'] then ['C'], then ['B'], then ['A'].
        # One-at-a-time for the rest of the ancestry.
