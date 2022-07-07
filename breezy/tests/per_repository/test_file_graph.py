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


"""Tests for the per file graph API."""


from breezy.tests.per_repository import TestCaseWithRepository
from breezy.tests import TestNotApplicable


class TestPerFileGraph(TestCaseWithRepository):

    def test_file_graph(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([("a", b"contents")])
        tree.add(["a"])
        if not tree.supports_file_ids:
            raise TestNotApplicable('file ids not supported')
        fileid = tree.path2id("a")
        revid1 = tree.commit("msg")
        self.build_tree_contents([("a", b"new contents")])
        revid2 = tree.commit("msg")
        self.addCleanup(tree.lock_read().unlock)
        graph = tree.branch.repository.get_file_graph()
        self.assertEqual({
            (fileid, revid2): ((fileid, revid1),), (fileid, revid1): ()},
            graph.get_parent_map([(fileid, revid2), (fileid, revid1)]))
