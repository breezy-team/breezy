# Copyright (C) 2006 by Canonical Ltd
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


"""Tests of the bzr serve command."""

import signal

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithTransport


class TestBzrServe(TestCaseWithTransport):
    
    def test_bzr_serve_port(self):
        # Make a branch
        self.make_branch('.')

        # Serve that branch from the current directory
        process = self.start_bzr_subprocess('serve', '--port', 'localhost:0')
        port_line = process.stdout.readline()
        prefix = 'listening on port: '
        self.assertStartsWith(port_line, prefix)
        port = int(port_line[len(prefix):])

        # Connect to the server
        branch = Branch.open('bzr://localhost:%d/' % port)

        # We get a working branch
        branch.repository.get_revision_graph()
        self.assertEqual(None, branch.last_revision())

        # Shutdown the server
        result = self.finish_bzr_subprocess(process, retcode=3,
                                            send_signal=signal.SIGINT)
        self.assertEqual('', result[0])
        self.assertEqual('bzr: interrupted\n', result[1])

    def test_bzr_serve_no_args(self):
        """'bzr serve' with no arguments or options should not traceback."""
        out, err = self.run_bzr_error(
            ['bzr serve requires one of --inet or --port'], 'serve')

