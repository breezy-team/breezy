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

import os
from bzrlib import (
    branch,
    builtins,
    errors,
    )
from bzrlib.tests import transport_util


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
        self.assertEquals(1, len(self.connections))

    def test_commit_both_modified(self):
        self.master_wt.commit('empty commit on master')
        self.start_logging_connections()

        commit = builtins.cmd_commit()
        # commit do not provide a directory parameter, we have to change dir
        # manually
        os.chdir('local')
        # cmd_commit translates BoundBranchOutOfDate into BzrCommandError
        self.assertRaises(errors.BzrCommandError, commit.run,
                          message=u'empty commit', unchanged=True)
        self.assertEquals(1, len(self.connections))

