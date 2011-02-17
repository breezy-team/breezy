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
