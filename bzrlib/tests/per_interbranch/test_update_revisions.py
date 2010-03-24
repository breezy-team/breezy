# Copyright (C) 2009 Canonical Ltd
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

from bzrlib import (
    errors,
    )
from bzrlib.tests.per_interbranch import (
    TestCaseWithInterBranch,
    )


class TestUpdateRevisions(TestCaseWithInterBranch):

    def setUp(self):
        super(TestUpdateRevisions, self).setUp()
        self.tree1 = self.make_branch_and_tree('tree1')
        rev1 = self.tree1.commit('one')
        branch2 = self.make_to_branch('tree2')
        branch2.repository.fetch(self.tree1.branch.repository)
        self.tree1.branch.copy_content_into(branch2)
        self.tree2 = branch2.bzrdir.create_workingtree()

    def test_accepts_graph(self):
        # An implementation may not use it, but it should allow a 'graph' to be
        # supplied
        rev2 = self.tree2.commit('two')

        self.tree1.lock_write()
        self.addCleanup(self.tree1.unlock)
        self.tree2.lock_read()
        self.addCleanup(self.tree2.unlock)
        graph = self.tree2.branch.repository.get_graph(
            self.tree1.branch.repository)

        self.tree1.branch.update_revisions(self.tree2.branch, graph=graph)
        self.assertEqual((2, rev2), self.tree1.branch.last_revision_info())

    def test_overwrite_ignores_diverged(self):
        rev2 = self.tree1.commit('two')
        rev2b = self.tree2.commit('alt two')

        self.assertRaises(errors.DivergedBranches,
                          self.tree1.branch.update_revisions,
                          self.tree2.branch, overwrite=False)
        # However, the revision should be copied into the repository
        self.assertTrue(self.tree1.branch.repository.has_revision(rev2b))

        self.tree1.branch.update_revisions(self.tree2.branch, overwrite=True)
        self.assertEqual((2, rev2b), self.tree1.branch.last_revision_info())

    def test_ignores_older_unless_overwrite(self):
        rev2 = self.tree1.commit('two')

        self.tree1.branch.update_revisions(self.tree2.branch)
        self.assertEqual((2, rev2), self.tree1.branch.last_revision_info())

        self.tree1.branch.update_revisions(self.tree2.branch, overwrite=True)
