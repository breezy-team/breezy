# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for repository statistic-gathering apis."""

from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository


class TestGatherStats(TestCaseWithRepository):

    def check_stats_has_size(self, stats):
        """Check that stats has a reasonable size entry."""
        # actual disk size varies from implementation to implementation,
        # but they should all provide it on their native transport.
        self.assertTrue('size' in stats)
        # and it should be a number
        self.assertIsInstance(stats['size'], (int, long))
        # and now remove it to make other assertions work without variation.
        del stats['size']

    def test_gather_stats(self):
        """First smoke test covering the refactoring into the Repository api."""
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # three commits: one to be included by reference, one to be 
        # requested, and one to be in the repository but [mostly] ignored.
        rev1 = tree.commit('first post', committer='person 1',
            timestamp=1170491381, timezone=0)
        rev2 = tree.commit('second post', committer='person 2',
            timestamp=1171491381, timezone=0)
        rev3 = tree.commit('third post', committer='person 3',
            timestamp=1172491381, timezone=0)
        tree.unlock()
        # now, in the same repository, asking for stats with/without the 
        # committers flag generates the same date information.
        stats = tree.branch.repository.gather_stats(rev2, committers=False)
        self.check_stats_has_size(stats)
        self.assertEqual({
            'firstrev': (1170491381.0, 0),
            'latestrev': (1171491381.0, 0),
            'revisions': 3,
            },
            stats)
        stats = tree.branch.repository.gather_stats(rev2, committers=True)
        self.check_stats_has_size(stats)
        self.assertEqual({
            'committers': 2,
            'firstrev': (1170491381.0, 0),
            'latestrev': (1171491381.0, 0),
            'revisions': 3,
            },
            stats)

    def test_gather_stats_norevid_gets_size(self):
        """Without a revid, repository size is still gathered."""
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # put something in the repository, because zero-size is borink.
        rev1 = tree.commit('first post')
        tree.unlock()
        # now ask for global repository stats.
        stats = tree.branch.repository.gather_stats()
        self.check_stats_has_size(stats)
        self.assertEqual({
            'revisions': 1
            },
            stats)

    def test_gather_stats_empty_repo(self):
        """An empty repository still has size and revisions."""
        tree = self.make_branch_and_memory_tree('.')
        # now ask for global repository stats.
        stats = tree.branch.repository.gather_stats()
        self.check_stats_has_size(stats)
        self.assertEqual({
            'revisions': 0
            },
            stats)
