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

"""Tests for get_rev_id_for_revno on a repository with external references."""

from breezy import errors
from breezy.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestGetRevIdForRevno(TestCaseWithExternalReferenceRepository):

    def test_uses_fallback(self):
        tree = self.make_branch_and_tree('base')
        base = tree.branch.repository
        revid = tree.commit('one')
        revid2 = tree.commit('two')
        spare_tree = tree.controldir.sprout('spare').open_workingtree()
        revid3 = spare_tree.commit('three')
        branch = spare_tree.branch.create_clone_on_transport(
            self.get_transport('referring'),
            stacked_on=tree.branch.base)
        repo = branch.repository
        # Sanity check: now repo has 'revid3', and base has 'revid' + 'revid2'
        self.assertEqual({revid3},
                         set(repo.controldir.open_repository().all_revision_ids()))
        self.assertEqual({revid2, revid},
                         set(base.controldir.open_repository().all_revision_ids()))
        # get_rev_id_for_revno will find revno 1 == 'revid', even though
        # that revision can only be found in the fallback.
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(
            (True, revid), repo.get_rev_id_for_revno(1, (3, revid3)))
