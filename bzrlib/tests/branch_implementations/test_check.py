# Copyright (C) 2008 Canonical Ltd
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

"""Tests for branch implementations - test check() functionality"""

from bzrlib import errors
from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestBranchCheck(TestCaseWithBranch):

    def test_check_detects_invalid_revhistory(self):
        # Different formats have different ways of handling invalid revision
        # histories, so the setup portion is customized
        tree = self.make_branch_and_tree('test')
        r1 = tree.commit('one')
        r2 = tree.commit('two')
        r3 = tree.commit('three')
        r4 = tree.commit('four')
        # create an alternate branch
        tree.set_parent_ids([r1])
        tree.branch.set_last_revision_info(1, r1)
        r2b = tree.commit('two-b')

        # now go back and merge the commit
        tree.set_parent_ids([r4, r2b])
        tree.branch.set_last_revision_info(4, r4)

        r5 = tree.commit('five')
        # Now, try to set an invalid history
        try:
            tree.branch.set_revision_history([r1, r2b, r5])
            if tree.branch.last_revision_info() != (3, r5):
                # RemoteBranch silently corrects an impossible revision
                # history given to set_revision_history.  It can be tricked
                # with set_last_revision_info though.
                tree.branch.set_last_revision_info(3, r5)
        except errors.NotLefthandHistory:
            # Branch5 allows set_revision_history to be wrong
            # Branch6 raises NotLefthandHistory, but we can force bogus stuff
            # with set_last_revision_info
            tree.branch.set_last_revision_info(3, r5)

        e = self.assertRaises(errors.BzrCheckError,
                              tree.branch.check)
        self.assertEqual('Internal check failed:'
                         ' revno does not match len(mainline) 3 != 5', str(e))

    def test_check_branch_report_results(self):
        """Checking a branch produces results which can be printed"""
        branch = self.make_branch('.')
        result = branch.check()
        # reports results through logging
        result.report_results(verbose=True)
        result.report_results(verbose=False)


