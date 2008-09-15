# Copyright (C) 2008 Canonical Ltd
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

"""Effort tests for the smart protocol."""

from bzrlib import (
    builtins,
    debug,
    tests,
    )
from bzrlib.branch import Branch
from bzrlib.smart import client, server
from bzrlib.transport import get_transport


class EmptyPushEffortTests(tests.TestCaseWithMemoryTransport):
    """Tests that a push of 0 revisions should make a limited number of smart
    protocol RPCs.
    """

    def setUp(self):
        super(EmptyPushEffortTests, self).setUp()
        debug.debug_flags.add('hpss')
        self.smart_server = server.SmartTCPServer_for_testing()
        self.smart_server.setUp(self.get_server())
        self.addCleanup(self.smart_server.tearDown)
        self.empty_branch = self.make_branch('empty')
        self.make_branch('target')
        client._SmartClient.hooks.install_named_hook(
            'call', self.capture_hpss_call, None)
        self.hpss_calls = []

    def capture_hpss_call(self, params):
        self.hpss_calls.append(params.method)

    def test_empty_branch_api(self):
        transport = get_transport(self.smart_server.get_url()).clone('target')
        target = Branch.open_from_transport(transport)
        self.empty_branch.push(target)
        self.assertEqual(
            ['BzrDir.open',
             'BzrDir.open_branch',
             'BzrDir.find_repositoryV2',
             'Branch.lock_write',
             'Branch.last_revision_info',
             'Branch.unlock'],
            self.hpss_calls)

    def test_empty_branch_command(self):
        cmd = builtins.cmd_push()
        cmd.outf = tests.StringIOWrapper()
        cmd.run(
            directory=self.get_url() + 'empty',
            location=self.smart_server.get_url() + 'target')
        self.assertTrue(len(self.hpss_calls) <= 8)


