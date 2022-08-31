# Copyright (C) 2020 Jelmer Vernooij
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

from . import TestCaseWithTransport

from ..memorybranch import MemoryBranch


class MemoryBranchTests(TestCaseWithTransport):

    def setUp(self):
        super(MemoryBranchTests, self).setUp()
        self.tree = self.make_branch_and_tree('.')
        self.revid1 = self.tree.commit('rev1')
        self.revid2 = self.tree.commit('rev2')
        self.branch = MemoryBranch(
            self.tree.branch.repository, (2, self.revid2))

    def test_last_revision_info(self):
        self.assertEqual((2, self.revid2), self.branch.last_revision_info())

    def test_last_revision(self):
        self.assertEqual(self.revid2, self.branch.last_revision())

    def test_revno(self):
        self.assertEqual(2, self.branch.revno())

    def test_get_rev_id(self):
        self.assertEqual(self.revid1, self.branch.get_rev_id(1))

    def test_revision_id_to_revno(self):
        self.assertEqual(2, self.branch.revision_id_to_revno(self.revid2))
        self.assertEqual(1, self.branch.revision_id_to_revno(self.revid1))
