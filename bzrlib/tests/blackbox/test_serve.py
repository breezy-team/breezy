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

import os
import signal
import subprocess
import threading

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import ParamikoNotPresent
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.transport import smart


class DoesNotCloseStdOutClient(smart.SmartStreamClient):
    """A client that doesn't close stdout upon disconnect().
    
    We wish to let stdout remain open so that we can see if the server writes
    anything to stdout during its shutdown.
    """

    def disconnect(self):
        if self._connected:
            self._connected = False
            # The client's out is the server's in.
            self._out.close()


class TestBzrServe(TestCaseWithTransport):

    def test_bzr_serve_inet(self):
        # Make a branch
        self.make_branch('.')

        # Serve that branch from the current directory
        process = self.start_bzr_subprocess(['serve', '--inet'])

        # Connect to the server
        # We use this url because while this is no valid URL to connect to this
        # server instance, the transport needs a URL.
        client = DoesNotCloseStdOutClient(
            lambda: (process.stdout, process.stdin))
        transport = smart.SmartTransport('bzr://localhost/', client=client)

        # We get a working branch
        branch = BzrDir.open_from_transport(transport).open_branch()
        branch.repository.get_revision_graph()
        self.assertEqual(None, branch.last_revision())

        # finish with the transport
        del transport
        # Disconnect the client forcefully JUST IN CASE because of __del__'s use
        # in the smart module.
        client.disconnect()

        # Shutdown the server: the client should have disconnected cleanly and
        # closed stdin, so the server process should shut itself down.
        self.assertTrue(process.stdin.closed)
        # Hide stdin from the subprocess module, so it won't fail to close it.
        process.stdin = None
        result = self.finish_bzr_subprocess(process, retcode=0)
        self.assertEqual('', result[0])
        self.assertEqual('', result[1])
    
    def test_bzr_serve_port(self):
        # Make a branch
        self.make_branch('.')

        # Serve that branch from the current directory
        process = self.start_bzr_subprocess(['serve', '--port', 'localhost:0'],
                                            skip_if_plan_to_signal=True)
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

    def test_bzr_connect_to_bzr_ssh(self):
        """bzr+ssh should work in ordinary bzr commands without blowing up."""
        try:
            from bzrlib.transport.sftp import SFTPServer
        except ParamikoNotPresent:
            raise TestSkipped('Paramiko not installed')
        
        from bzrlib.tests.stub_sftp import StubServer
        from paramiko.common import AUTH_SUCCESSFUL

        # XXX: Eventually, all SSH vendor classes should implement this.
        from bzrlib.transport.ssh import _get_ssh_vendor, SSHVendor
        vendor = _get_ssh_vendor()
        if vendor.connect_ssh.im_func == SSHVendor.connect_ssh.im_func:
            raise TestSkipped(
                'connect_ssh is not yet implemented on %r' % vendor)

        # Make a branch
        self.make_branch('a_branch')

        # Start an SSH server
        # XXX: This is horrible -- we define a really dumb SSH server that
        # executes commands, and manage the hooking up of stdin/out/err to the
        # SSH channel ourselves.  Surely this has already been implemented
        # elsewhere?
        class StubSSHServer(StubServer):

            test = self

            def get_allowed_auths(self, username):
                return 'none'

            def check_auth_none(self, username):
                return AUTH_SUCCESSFUL
            
            def check_channel_exec_request(self, channel, command):
                self.test.command_executed = command
                proc = subprocess.Popen(
                    command, shell=True, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                # XXX: horribly inefficient, not to mention ugly.
                def do_stdin():
                    # copy bytes from the channel to the subprocess's stdin
                    while True:
                        bytes = channel.recv(1)
                        if bytes == '':
                            proc.stdin.close()
                            break
                        proc.stdin.write(bytes)
                        proc.stdin.flush()
                threading.Thread(target=do_stdin).start()

                def ferry_bytes(pipe):
                    while True:
                        bytes = pipe.read(1)
                        if bytes == '':
                            channel.close()
                            break
                        channel.sendall(bytes)
                threading.Thread(target=ferry_bytes, args=(proc.stdout,)).start()
                threading.Thread(target=ferry_bytes, args=(proc.stderr,)).start()

                return True

        ssh_server = SFTPServer(StubSSHServer)
        ssh_server.setUp()
        self.addCleanup(ssh_server.tearDown)
        port = ssh_server._listener.port

        # Access the branch via a bzr+ssh URL.  The BZR_REMOTE_PATH environment
        # variable is used to tell bzr what command to run on the remote end.
        path_to_branch = os.path.abspath('.')
        self.run_bzr_subprocess(
            'log', 'bzr+ssh://localhost:%d/%s' % (port, path_to_branch),
            env_changes={'BZR_REMOTE_PATH': self.get_bzr_path()})
        
        self.assertEqual(
            '%s serve --inet --directory=/' % self.get_bzr_path(),
            self.command_executed)
        
        
