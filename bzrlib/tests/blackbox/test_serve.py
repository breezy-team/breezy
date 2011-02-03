# Copyright (C) 2006-2011 Canonical Ltd
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
import thread
import threading

from bzrlib import (
    builtins,
    errors,
    osutils,
    revision as _mod_revision,
    transport,
    urlutils,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.smart import client, medium
from bzrlib.smart.server import (
    BzrServerFactory,
    SmartTCPServer,
    )
from bzrlib.tests import (
    TestCaseWithMemoryTransport,
    TestCaseWithTransport,
    )
from bzrlib.trace import mutter
from bzrlib.transport import remote


class TestBzrServeBase(TestCaseWithTransport):

    def run_bzr_serve_then_func(self, serve_args, retcode=0, func=None,
                                *func_args, **func_kwargs):
        """Run 'bzr serve', and run the given func in a thread once the server
        has started.

        When 'func' terminates, the server will be terminated too.

        Returns stdout and stderr.
        """
        # install hook
        def on_server_start(backing_urls, tcp_server):
            t = threading.Thread(
                target=on_server_start_thread, args=(tcp_server,))
            t.start()
        def on_server_start_thread(tcp_server):
            try:
                # Run func if set
                self.tcp_server = tcp_server
                if not func is None:
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
            out, err = self.run_bzr(['serve'] + list(serve_args))
        except KeyboardInterrupt, e:
            out, err = e.args
        return out, err


class TestBzrServe(TestBzrServeBase):

    def setUp(self):
        super(TestBzrServe, self).setUp()
        self.disable_missing_extensions_warning()

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
        args = ['serve', '--inet']
        args.extend(extra_options)
        process = self.start_bzr_subprocess(args)

        # Connect to the server
        # We use this url because while this is no valid URL to connect to this
        # server instance, the transport needs a URL.
        url = 'bzr://localhost/'
        self.permit_url(url)
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
        url = 'bzr://localhost:%d/' % port
        self.permit_url(url)
        return process, url

    def test_bzr_serve_quiet(self):
        self.make_branch('.')
        args = ['--port', 'localhost:0', '--quiet']
        out, err = self.run_bzr_serve_then_func(args, retcode=3)
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_bzr_serve_inet_readonly(self):
        """bzr server should provide a read only filesystem by default."""
        process, transport = self.start_server_inet()
        self.assertRaises(errors.TransportNotPossible, transport.mkdir, 'adir')
        self.assertInetServerShutsdownCleanly(process)

    def test_bzr_serve_inet_readwrite(self):
        # Make a branch
        self.make_branch('.')

        process, transport = self.start_server_inet(['--allow-writes'])

        # We get a working branch, and can create a directory
        branch = BzrDir.open_from_transport(transport).open_branch()
        self.make_read_requests(branch)
        transport.mkdir('adir')
        self.assertInetServerShutsdownCleanly(process)

    def test_bzr_serve_port_readonly(self):
        """bzr server should provide a read only filesystem by default."""
        process, url = self.start_server_port()
        t = transport.get_transport(url)
        self.assertRaises(errors.TransportNotPossible, t.mkdir, 'adir')
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

    def test_bzr_serve_dhpss(self):
        # This is a smoke test that the server doesn't crash when run with
        # -Dhpss, and does drop some hpss logging to the file.
        self.make_branch('.')
        log_fname = os.getcwd() + '/server.log'
        self.overrideEnv('BZR_LOG', log_fname)
        process, transport = self.start_server_inet(['-Dhpss'])
        branch = BzrDir.open_from_transport(transport).open_branch()
        self.make_read_requests(branch)
        self.assertInetServerShutsdownCleanly(process)
        f = open(log_fname, 'rb')
        content = f.read()
        f.close()
        self.assertContainsRe(content, r'hpss request: \[[0-9-]+\]')


class TestCmdServeChrooting(TestBzrServeBase):

    def test_serve_tcp(self):
        """'bzr serve' wraps the given --directory in a ChrootServer.

        So requests that search up through the parent directories (like
        find_repositoryV3) will give "not found" responses, rather than
        InvalidURLJoin or jail break errors.
        """
        t = self.get_transport()
        t.mkdir('server-root')
        self.run_bzr_serve_then_func(
            ['--port', '127.0.0.1:0',
             '--directory', t.local_abspath('server-root'),
             '--allow-writes'],
            func=self.when_server_started)
        # The when_server_started method issued a find_repositoryV3 that should
        # fail with 'norepository' because there are no repositories inside the
        # --directory.
        self.assertEqual(('norepository',), self.client_resp)

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


class TestUserdirExpansion(TestCaseWithMemoryTransport):

    def fake_expanduser(self, path):
        """A simple, environment-independent, function for the duration of this
        test.

        Paths starting with a path segment of '~user' will expand to start with
        '/home/user/'.  Every other path will be unchanged.
        """
        if path.split('/', 1)[0] == '~user':
            return '/home/user' + path[len('~user'):]
        return path

    def make_test_server(self, base_path='/'):
        """Make and start a BzrServerFactory, backed by a memory transport, and
        creat '/home/user' in that transport.
        """
        bzr_server = BzrServerFactory(
            self.fake_expanduser, lambda t: base_path)
        mem_transport = self.get_transport()
        mem_transport.mkdir_multi(['home', 'home/user'])
        bzr_server.set_up(mem_transport, None, None, inet=True)
        self.addCleanup(bzr_server.tear_down)
        return bzr_server

    def test_bzr_serve_expands_userdir(self):
        bzr_server = self.make_test_server()
        self.assertTrue(bzr_server.smart_server.backing_transport.has('~user'))

    def test_bzr_serve_does_not_expand_userdir_outside_base(self):
        bzr_server = self.make_test_server('/foo')
        self.assertFalse(bzr_server.smart_server.backing_transport.has('~user'))

    def test_get_base_path(self):
        """cmd_serve will turn the --directory option into a LocalTransport
        (optionally decorated with 'readonly+').  BzrServerFactory can
        determine the original --directory from that transport.
        """
        # URLs always include the trailing slash, and get_base_path returns it
        base_dir = osutils.abspath('/a/b/c') + '/'
        base_url = urlutils.local_path_to_url(base_dir) + '/'
        # Define a fake 'protocol' to capture the transport that cmd_serve
        # passes to serve_bzr.
        def capture_transport(transport, host, port, inet):
            self.bzr_serve_transport = transport
        cmd = builtins.cmd_serve()
        # Read-only
        cmd.run(directory=base_dir, protocol=capture_transport)
        server_maker = BzrServerFactory()
        self.assertEqual(
            'readonly+%s' % base_url, self.bzr_serve_transport.base)
        self.assertEqual(
            base_dir, server_maker.get_base_path(self.bzr_serve_transport))
        # Read-write
        cmd.run(directory=base_dir, protocol=capture_transport,
            allow_writes=True)
        server_maker = BzrServerFactory()
        self.assertEqual(base_url, self.bzr_serve_transport.base)
        self.assertEqual(base_dir,
            server_maker.get_base_path(self.bzr_serve_transport))
