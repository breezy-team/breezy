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


from bzrlib.builtins import cmd_checkout
from bzrlib.tests.TransportUtil import TestCaseWithConnectionHookedTransport

class TestCheckout(TestCaseWithConnectionHookedTransport):

    def test_checkout(self):
        self.make_branch_and_tree('branch1')
        # make_branch_and_tree create one connection
        self.reset_connections()

        cmd = cmd_checkout()
        cmd.run(self.get_url() + '/branch1', 'local')
        self.assertEquals(1, len(self.connections))

