# Copyright (C) 2011 Canonical Ltd
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


from bzrlib import (
    remote,
    tests,
    )
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestGraph(TestCaseWithRepository):

    def test_get_known_graph_ancestry_stacked(self):
        """get_known_graph_ancestry works correctly on stacking.

        See <https://bugs.launchpad.net/bugs/715000>.
        """
        branch_a, branch_b, branch_c, revid_1 = self.make_double_stacked_branches()
        for br in [branch_a, branch_b, branch_c]:
            self.assertEquals(
                [revid_1],
                br.repository.get_known_graph_ancestry([revid_1]).topo_sort())

    def make_double_stacked_branches(self):
        wt_a = self.make_branch_and_tree('a')
        branch_a = wt_a.branch
        branch_b = self.make_branch('b')
        branch_b.set_stacked_on_url('../a')
        branch_c = self.make_branch('c')
        branch_c.set_stacked_on_url('../b')
        revid_1 = wt_a.commit('first commit')
        return branch_a, branch_b, branch_c, revid_1

    def make_stacked_branch_with_long_history(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        builder.build_snapshot('A', None, [
            ('add', ('', 'directory', 'root-id', None))])
        builder.build_snapshot('B', ['A'], [])
        builder.build_snapshot('C', ['B'], [])
        builder.build_snapshot('D', ['C'], [])
        builder.build_snapshot('E', ['D'], [])
        builder.build_snapshot('F', ['E'], [])
        source_b = builder.get_branch()
        master_b = self.make_branch('master')
        master_b.pull(source_b, stop_revision='E')
        stacked_b = self.make_branch('stacked')
        stacked_b.set_stacked_on_url('../master')
        stacked_b.pull(source_b, stop_revision='F')
        builder.finish_series()
        return master_b, stacked_b

    def test_doesnt_call_get_parent_map_on_all_fallback_revs(self):
        if not isinstance(self.repository_format,
                          remote.RemoteRepositoryFormat):
            raise tests.TestNotApplicable('only for RemoteRepository')
        # bug #388269
        master_b, stacked_b = self.make_stacked_branch_with_long_history()
        self.addCleanup(stacked_b.lock_read().unlock)
        rpc = stacked_b.repository._get_parent_map_rpc
        calls = []
        def logging_rpc(keys):
            import pdb; pdb.set_trace()
            calls.append(keys)
            return rpc(keys)
        stacked_b.repository._get_parent_map_rpc = logging_rpc
        self.make_repository('target_repo', shared=True)
        target_b = self.make_branch('target_repo/branch')
        target_b.pull(stacked_b)
        self.assertEqual([], calls)
        self.fail("test isn't working yet.")
