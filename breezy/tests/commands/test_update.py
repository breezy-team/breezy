# Copyright (C) 2007, 2009, 2010, 2016 Canonical Ltd
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

from ... import (
    branch,
    builtins,
    )
from .. import (
    transport_util,
    ui_testing,
    )


class TestUpdate(transport_util.TestCaseWithConnectionHookedTransport):

    def test_update(self):
        remote_wt = self.make_branch_and_tree('remote')
        local_wt = self.make_branch_and_tree('local')

        remote_branch = branch.Branch.open(self.get_url('remote'))
        local_wt.branch.bind(remote_branch)

        remote_wt.commit('empty commit')

        self.start_logging_connections()

        update = builtins.cmd_update()
        # update needs the encoding from outf to print URLs
        update.outf = ui_testing.StringIOWithEncoding()
        # update calls it 'dir' where other commands calls it 'directory'
        update.run(dir='local')
        self.assertEqual(1, len(self.connections))
