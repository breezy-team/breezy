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

from ...builtins import cmd_init
from .. import (
    transport_util,
    ui_testing,
    )


class TestInit(transport_util.TestCaseWithConnectionHookedTransport):

    def setUp(self):
        super(TestInit, self).setUp()
        self.start_logging_connections()

    def test_init(self):
        cmd = cmd_init()
        # We don't care about the ouput but 'outf' should be defined
        cmd.outf = ui_testing.StringIOWithEncoding()
        cmd.run(self.get_url())
        self.assertEqual(1, len(self.connections))
