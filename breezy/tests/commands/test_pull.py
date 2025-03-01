# Copyright (C) 2007, 2009, 2010, 2011, 2016 Canonical Ltd
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

from ... import branch, builtins
from .. import transport_util, ui_testing


class TestPull(transport_util.TestCaseWithConnectionHookedTransport):
    def test_pull(self):
        wt1 = self.make_branch_and_tree("branch1")
        wt1.commit("empty commit")
        self.make_branch_and_tree("branch2")

        self.start_logging_connections()

        cmd = builtins.cmd_pull()
        # We don't care about the ouput but 'outf' should be defined
        cmd.outf = ui_testing.StringIOWithEncoding()
        cmd.run(self.get_url("branch1"), directory="branch2")
        self.assertEqual(1, len(self.connections))

    def test_pull_with_bound_branch(self):
        self.make_branch_and_tree("master")
        local_wt = self.make_branch_and_tree("local")
        master_branch = branch.Branch.open(self.get_url("master"))
        local_wt.branch.bind(master_branch)

        remote_wt = self.make_branch_and_tree("remote")
        remote_wt.commit("empty commit")

        self.start_logging_connections()

        pull = builtins.cmd_pull()
        # We don't care about the ouput but 'outf' should be defined
        pull.outf = ui_testing.StringIOWithEncoding()
        pull.run(self.get_url("remote"), directory="local")
        self.assertEqual(2, len(self.connections))
