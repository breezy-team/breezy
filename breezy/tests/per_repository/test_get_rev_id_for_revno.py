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

"""Tests for get_rev_id_for_revno."""

from breezy import errors
from breezy.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestGetRevIdForRevno(TestCaseWithExternalReferenceRepository):

    def setUp(self):
        super(TestGetRevIdForRevno, self).setUp()
        self.tree = self.make_branch_and_tree('base')
        self.revid1 = self.tree.commit('one')
        self.revid2 = self.tree.commit('two')
        self.revid3 = self.tree.commit('three')

    def test_success(self):
        repo = self.tree.branch.repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(
            (True, self.revid1),
            repo.get_rev_id_for_revno(1, (3, self.revid3)))
        self.assertEqual(
            (True, self.revid2),
            repo.get_rev_id_for_revno(2, (3, self.revid3)))

    def test_unknown_revision(self):
        tree2 = self.make_branch_and_tree('other')
        unknown_revid = tree2.commit('other')
        repo = self.tree.branch.repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertRaises(
            errors.NoSuchRevision,
            repo.get_rev_id_for_revno, 1, (3, unknown_revid))

    def test_known_pair_is_after(self):
        repo = self.tree.branch.repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertRaises(
            errors.RevnoOutOfBounds,
            repo.get_rev_id_for_revno, 3, (2, self.revid2))
