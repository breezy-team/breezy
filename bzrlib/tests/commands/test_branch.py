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


from bzrlib.builtins import cmd_branch
from bzrlib.tests.TransportUtil import TestCaseWithConnectionHookedTransport


class TestBranch(TestCaseWithConnectionHookedTransport):

    def test_branch_locally(self):
        self.make_branch_and_tree('branch')
        cmd = cmd_branch()
        cmd.run(self.get_url() + '/branch', 'local')
        self.assertEquals(1, len(self.connections))

# FIXME: Bug in ftp transport suspected, neither of the two
# cmd.run() variants can finish, we get stucked somewhere in a
# rename.... Have a look at changes introduced in revno 2423 ?
# Done, reverting the -r 2422.2423 patch makes things better but
# BzrDir.sprout still try to create a working tree without
# checking that the path is local and the test still hangs
# (server shutdown missing ?). Needs more investigation.

#    def test_branch_remotely(self):
#        self.make_branch_and_tree('branch')
#        cmd = cmd_branch()
#        cmd.run(self.get_url() + '/branch', self.get_url() + '/remote')
#        cmd.run('branch', self.get_url() + '/remote')
#        self.assertEquals(2, len(self.connections))

