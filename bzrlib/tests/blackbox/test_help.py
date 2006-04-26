# Copyright (C) 2005, 2006 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr help.
"""


from bzrlib.tests.blackbox import ExternalBase


class TestHelp(ExternalBase):

    def test_help_basic(self):
        for cmd in ['--help', 'help', '-h', '-?']:
            output = self.runbzr(cmd)[0]
            line1 = output.split('\n')[0]
            if not line1.startswith('Bazaar-NG'):
                self.fail("bad output from bzr %s:\n%r" % (cmd, output))
        # see https://launchpad.net/products/bzr/+bug/35940, -h doesn't work

    def test_help_commands(self):
        dash_help  = self.runbzr('--help commands')[0]
        commands   = self.runbzr('help commands')[0]
        long_help  = self.runbzr('help --long')[0]
        qmark_long = self.runbzr('? --long')[0]
        qmark_cmds = self.runbzr('? commands')[0]
        self.assertEquals(dash_help, commands)
        self.assertEquals(dash_help, long_help)
        self.assertEquals(dash_help, qmark_long)
        self.assertEquals(dash_help, qmark_cmds)

    def test_help_detail(self):
        dash_h  = self.runbzr('commit -h')[0]
        help_x  = self.runbzr('help commit')[0]
        qmark_x = self.runbzr('help commit')[0]
        self.assertEquals(dash_h, help_x)
        self.assertEquals(dash_h, qmark_x)

    def test_help_help(self):
        help = self.runbzr('help help')[0]
        qmark = self.runbzr('? ?')[0]
        self.assertEquals(help, qmark)
        for line in help.split('\n'):
            if '--long' in line:
                self.assertTrue('show help on all commands' in line)
