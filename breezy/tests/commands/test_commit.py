# Copyright (C) 2007-2010, 2016 Canonical Ltd
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

import os
from breezy import (
    branch,
    builtins,
    errors,
    )
from breezy.tests import transport_util


class TestCommitWithBoundBranch(
        transport_util.TestCaseWithConnectionHookedTransport):

    def setUp(self):
        super(TestCommitWithBoundBranch, self).setUp()
        self.master_wt = self.make_branch_and_tree('master')
        self.local_wt = self.make_branch_and_tree('local')

        master_branch = branch.Branch.open(self.get_url('master'))
        self.local_wt.branch.bind(master_branch)

    def test_commit_mine_modified(self):

        self.start_logging_connections()

        commit = builtins.cmd_commit()
        # commit do not provide a directory parameter, we have to change dir
        # manually
        os.chdir('local')
        commit.run(message=u'empty commit', unchanged=True)
        self.assertEqual(1, len(self.connections))

    def test_commit_both_modified(self):
        self.master_wt.commit('empty commit on master')
        self.start_logging_connections()

        commit = builtins.cmd_commit()
        # commit do not provide a directory parameter, we have to change dir
        # manually
        os.chdir('local')
        self.assertRaises(errors.BoundBranchOutOfDate, commit.run,
                          message=u'empty commit', unchanged=True)
        self.assertEqual(1, len(self.connections))

    def test_commit_local(self):
        """Commits with --local should not connect to the master!"""
        self.start_logging_connections()

        commit = builtins.cmd_commit()
        # commit do not provide a directory parameter, we have to change dir
        # manually
        os.chdir('local')
        commit.run(message=u'empty commit', unchanged=True, local=True)

        # it shouldn't open any connections
        self.assertEqual(0, len(self.connections))
