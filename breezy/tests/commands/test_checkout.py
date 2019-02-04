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

from breezy.builtins import cmd_checkout
from breezy.tests.transport_util import TestCaseWithConnectionHookedTransport


class TestCheckout(TestCaseWithConnectionHookedTransport):

    def test_checkout(self):
        self.make_branch_and_tree('branch1')

        self.start_logging_connections()

        cmd = cmd_checkout()
        cmd.run(self.get_url('branch1'), 'local')
        self.assertEqual(1, len(self.connections))

    def test_checkout_lightweight(self):
        self.make_branch_and_tree('branch1')

        self.start_logging_connections()

        cmd = cmd_checkout()
        cmd.run(self.get_url('branch1'), 'local', lightweight=True)
        self.assertEqual(1, len(self.connections))
