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


from bzrlib import (
    branch,
    builtins,
    )
from bzrlib.tests import transport_util


class TestUpdate(transport_util.TestCaseWithConnectionHookedTransport):

    def test_update(self):
        remote_wt = self.make_branch_and_tree('remote')
        local_wt = self.make_branch_and_tree('local')

        remote_branch = branch.Branch.open(self.get_url('remote'))
        local_wt.branch.bind(remote_branch)

        remote_wt.commit('empty commit')

        self.start_logging_connections()

        update = builtins.cmd_update()
        # update calls it 'dir' where other commands calls it 'directory'
        update.run(dir='local')
        self.assertEquals(1, len(self.connections))

