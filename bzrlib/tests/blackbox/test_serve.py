# Copyright (C) 2006 Canonical Ltd
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


"""Tests of the bzr serve command."""

import os
import signal
import subprocess
import sys
import thread
import threading

from bzrlib import (
    errors,
    osutils,
    revision as _mod_revision,
    transport,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import ParamikoNotPresent
from bzrlib.smart import client, medium
from bzrlib.smart.server import SmartTCPServer
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
from bzrlib.transport import get_transport, remote


class TestBzrServe(TestCaseWithTransport):

    def assertInetServerShutsdownCleanly(self, process):
        """Shutdown the server process looking for errors."""
        # Shutdown the server: the server should shut down when it cannot read
        # from stdin anymore.
        process.stdin.close()
        # Hide stdin from the subprocess module, so it won't fail to close it.
        process.stdin = None
        result = self.finish_bzr_subprocess(process)
        self.assertEqual('', result[0])
        self.assertEqual('', result[1])

    def assertServerFinishesCleanly(self, process):
        """Shutdown the bzr serve instance process looking for errors."""
        # Shutdown the server
        result = self.finish_bzr_subprocess(process, retcode=3,
                                            send_signal=signal.SIGINT)
        self.assertEqual('', result[0])
        self.assertEqual('bzr: interrupted\n', result[1])

    def make_read_requests(self, branch):
        """Do some read only requests."""
        branch.lock_read()
        try:
            branch.repository.all_revision_ids()
            self.assertEqual(_mod_revision.NULL_REVISION,
                             _mod_revision.ensure_null(branch.last_revision()))
        finally:
            branch.unlock()

    def start_server_inet(self, extra_options=()):
        """Start a bzr server subprocess using the --inet option.

        :param extra_options: extra options to give the server.
        :return: a tuple with the bzr process handle for passing to
            finish_bzr_subprocess, a client for the server, and a transport.
        """
        # Serve from the current directory
        process = self.start_bzr_subprocess(['serve', '--inet'])

        # Connect to the server
        # We use this url because while this is no valid URL to connect to this
        # server instance, the transport needs a URL.
        url = 'bzr://localhost/'
        client_medium = medium.SmartSimplePipesClientMedium(
            process.stdout, process.stdin, url)
        transport = remote.RemoteTransport(url, medium=client_medium)
        return process, transport

    def start_server_port(self, extra_options=()):
        """Start a bzr server subprocess.

        :param extra_options: extra options to give the server.
        :return: a tuple with the bzr process handle for passing to
            finish_bzr_subprocess, and the base url for the server.
        """
        # Serve from the current directory
        args = ['serve', '--port', 'localhost:0']
        args.extend(extra_options)
        process = self.start_bzr_subprocess(args, skip_if_plan_to_signal=True)
        port_line = process.stderr.readline()
        prefix = 'listening on port: '
        self.assertStartsWith(port_line, prefix)
        port = int(port_line[len(prefix):])
        return process,'bzr://localhost:%d/' % port

    def test_bzr_serve_inet_readonly(self):
        """bzr server should provide a read only filesystem by default."""
        process, transport = self.start_server_inet()
        self.assertRaises(errors.TransportNotPossible, transport.mkdir, 'adir')
        self.assertInetServerShutsdownCleanly(process)

    def test_bzr_serve_inet_readwrite(self):
        # Make a branch
        self.make_branch('.')

        process, transport = self.start_server_inet(['--allow-writes'])

        # We get a working branch
        branch = BzrDir.open_from_transport(transport).open_branch()
        self.make_read_requests(branch)
        self.assertInetServerShutsdownCleanly(process)

    def test_bzr_serve_port_readonly(self):
        """bzr server should provide a read only filesystem by default."""
        process, url = self.start_server_port()
        transport = get_transport(url)
        self.assertRaises(errors.TransportNotPossible, transport.mkdir, 'adir')
        self.assertServerFinishesCleanly(process)

    def test_bzr_serve_port_readwrite(self):
        # Make a branch
        self.make_branch('.')

        process, url = self.start_server_port(['--allow-writes'])

        # Connect to the server
        branch = Branch.open(url)
        self.make_read_requests(branch)
        self.assertServerFinishesCleanly(process)

    def test_bzr_serve_supports_protocol(self):
        # Make a branch
        self.make_branch('.')

        process, url = self.start_server_port(['--allow-writes',
                                               '--protocol=bzr'])

        # Connect to the server
        branch = Branch.open(url)
        self.make_read_requests(branch)
        self.assertServerFinishesCleanly(process)

    def test_bzr_connect_to_bzr_ssh(self):
        """User acceptance that get_transport of a bzr+ssh:// behaves correctly.

        bzr+ssh:// should cause bzr to run a remote bzr smart server over SSH.
        """
        try:
            from bzrlib.transport.sftp import SFTPServer
        except ParamikoNotPresent:
            raise TestSkipped('Paramiko not installed')
        from bzrlib.tests.stub_sftp import StubServer

        # Make a branch
        self.make_branch('a_branch')

        # Start an SSH server
        self.command_executed = []
        # XXX: This is horrible -- we define a really dumb SSH server that
        # executes commands, and manage the hooking up of stdin/out/err to the
        # SSH channel ourselves.  Surely this has already been implemented
        # elsewhere?
        class StubSSHServer(StubServer):

            test = self

            def check_channel_exec_request(self, channel, command):
                self.test.command_executed.append(command)
                proc = subprocess.Popen(
                    command, shell=True, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                # XXX: horribly inefficient, not to mention ugly.
                # Start a thread for each of stdin/out/err, and relay bytes from
                # the subprocess to channel and vice versa.
                def ferry_bytes(read, write, close):
                    while True:
                        bytes = read(1)
                        if bytes == '':
                            close()
                            break
                        write(bytes)

                file_functions = [
                    (channel.recv, proc.stdin.write, proc.stdin.close),
                    (proc.stdout.read, channel.sendall, channel.close),
                    (proc.stderr.read, channel.sendall_stderr, channel.close)]
                for read, write, close in file_functions:
                    t = threading.Thread(
                        target=ferry_bytes, args=(read, write, close))
                    t.start()

                return True

        ssh_server = SFTPServer(StubSSHServer)
        # XXX: We *don't* want to override the default SSH vendor, so we set
        # _vendor to what _get_ssh_vendor returns.
        ssh_server.setUp()
        self.addCleanup(ssh_server.tearDown)
        port = ssh_server._listener.port

        # Access the branch via a bzr+ssh URL.  The BZR_REMOTE_PATH environment
        # variable is used to tell bzr what command to run on the remote end.
        path_to_branch = osutils.abspath('a_branch')

        orig_bzr_remote_path = os.environ.get('BZR_REMOTE_PATH')
        bzr_remote_path = self.get_bzr_path()
        if sys.platform == 'win32':
            bzr_remote_path = sys.executable + ' ' + self.get_bzr_path()
        os.environ['BZR_REMOTE_PATH'] = bzr_remote_path
        try:
            if sys.platform == 'win32':
                path_to_branch = os.path.splitdrive(path_to_branch)[1]
            branch = Branch.open(
                'bzr+ssh://fred:secret@localhost:%d%s' % (port, path_to_branch))
            self.make_read_requests(branch)
            # Check we can perform write operations
            branch.bzrdir.root_transport.mkdir('foo')
        finally:
            # Restore the BZR_REMOTE_PATH environment variable back to its
            # original state.
            if orig_bzr_remote_path is None:
                del os.environ['BZR_REMOTE_PATH']
            else:
                os.environ['BZR_REMOTE_PATH'] = orig_bzr_remote_path

        self.assertEqual(
            ['%s serve --inet --directory=/ --allow-writes'
             % bzr_remote_path],
            self.command_executed)


class TestCmdServeChrooting(TestCaseWithTransport):

    def test_serve_tcp(self):
        """'bzr serve' wraps the given --directory in a ChrootServer.

        So requests that search up through the parent directories (like
        find_repositoryV3) will give "not found" responses, rather than
        InvalidURLJoin or jail break errors.
        """
        t = self.get_transport()
        t.mkdir('server-root')
        self.run_bzr_serve_then_func(
            ['--port', '0', '--directory', t.local_abspath('server-root'),
             '--allow-writes'],
            self.when_server_started)
        # The when_server_started method issued a find_repositoryV3 that should
        # fail with 'norepository' because there are no repositories inside the
        # --directory.
        self.assertEqual(('norepository',), self.client_resp)
        
    def run_bzr_serve_then_func(self, serve_args, func, *func_args,
            **func_kwargs):
        """Run 'bzr serve', and run the given func in a thread once the server
        has started.
        
        When 'func' terminates, the server will be terminated too.
        """
        # install hook
        def on_server_start(backing_urls, tcp_server):
            t = threading.Thread(
                target=on_server_start_thread, args=(tcp_server,))
            t.start()
        def on_server_start_thread(tcp_server):
            try:
                # Run func
                self.tcp_server = tcp_server
                try:
                    func(*func_args, **func_kwargs)
                except Exception, e:
                    # Log errors to make some test failures a little less
                    # mysterious.
                    mutter('func broke: %r', e)
            finally:
                # Then stop the server
                mutter('interrupting...')
                thread.interrupt_main()
        SmartTCPServer.hooks.install_named_hook(
            'server_started_ex', on_server_start,
            'run_bzr_serve_then_func hook')
        # start a TCP server
        try:
            self.run_bzr(['serve'] + list(serve_args))
        except KeyboardInterrupt:
            pass

    def when_server_started(self):
        # Connect to the TCP server and issue some requests and see what comes
        # back.
        client_medium = medium.SmartTCPClientMedium(
            '127.0.0.1', self.tcp_server.port,
            'bzr://localhost:%d/' % (self.tcp_server.port,))
        smart_client = client._SmartClient(client_medium)
        resp = smart_client.call('mkdir', 'foo', '')
        resp = smart_client.call('BzrDirFormat.initialize', 'foo/')
        try:
            resp = smart_client.call('BzrDir.find_repositoryV3', 'foo/')
        except errors.ErrorFromSmartServer, e:
            resp = e.error_tuple
        self.client_resp = resp
        client_medium.disconnect()



