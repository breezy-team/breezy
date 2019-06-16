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


"""Tests for _make_parents_provider on stacked repositories."""


from breezy.tests.per_repository import TestCaseWithRepository


class Test_MakeParentsProvider(TestCaseWithRepository):

    def test_add_fallback_after_make_pp(self):
        """Fallbacks added after _make_parents_provider are used by that
        provider.
        """
        referring_repo = self.make_repository('repo')
        pp = referring_repo._make_parents_provider()
        # Initially referring_repo has no revisions and no fallbacks
        self.addCleanup(referring_repo.lock_read().unlock)
        self.assertEqual({}, pp.get_parent_map([b'revid2']))
        # Add a fallback repo with a commit
        wt_a = self.make_branch_and_tree('fallback')
        wt_a.commit('first commit', rev_id=b'revid1')
        wt_a.commit('second commit', rev_id=b'revid2')
        fallback_repo = wt_a.branch.repository
        referring_repo.add_fallback_repository(fallback_repo)
        # Now revid1 appears in pp's results.
        self.assertEqual((b'revid1',), pp.get_parent_map(
            [b'revid2'])[b'revid2'])
