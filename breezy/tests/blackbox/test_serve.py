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


"""Tests of the brz serve command."""

import signal
import sys
import threading
from _thread import interrupt_main  # type: ignore

from ... import builtins, config, errors, osutils, trace, transport, urlutils
from ... import revision as _mod_revision
from ...branch import Branch
from ...bzr.smart import client, medium
from ...bzr.smart.server import BzrServerFactory, SmartTCPServer
from ...controldir import ControlDir
from ...transport import remote
from .. import TestCaseWithMemoryTransport, TestCaseWithTransport


class TestBzrServeBase(TestCaseWithTransport):
    def run_bzr_serve_then_func(
        self, serve_args, retcode=0, func=None, *func_args, **func_kwargs
    ):
        """Run 'brz serve', and run the given func in a thread once the server
        has started.

        When 'func' terminates, the server will be terminated too.

        Returns stdout and stderr.
        """

        def on_server_start_thread(tcp_server):
            """This runs concurrently with the server thread.

            The server is interrupted as soon as ``func`` finishes, even if an
            exception is encountered.
            """
            try:
                # Run func if set
                self.tcp_server = tcp_server
                if func is not None:
                    try:
                        func(*func_args, **func_kwargs)
                    except Exception as e:
                        # Log errors to make some test failures a little less
                        # mysterious.
                        trace.mutter("func broke: %r", e)
            finally:
                # Then stop the server
                trace.mutter("interrupting...")
                interrupt_main()

        # When the hook is fired, it just starts ``on_server_start_thread`` and
        # return

        def on_server_start(backing_urls, tcp_server):
            t = threading.Thread(target=on_server_start_thread, args=(tcp_server,))
            t.start()

        # install hook
        SmartTCPServer.hooks.install_named_hook(
            "server_started_ex", on_server_start, "run_bzr_serve_then_func hook"
        )
        # It seems interrupt_main() will not raise KeyboardInterrupt
        # until after socket.accept returns. So we set the timeout low to make
        # the test faster.
        self.overrideAttr(SmartTCPServer, "_ACCEPT_TIMEOUT", 0.1)
        # start a TCP server
        try:
            out, err = self.run_bzr(["serve"] + list(serve_args), retcode=retcode)
        except KeyboardInterrupt:
            return (self._last_cmd_stdout.getvalue(), self._last_cmd_stderr.getvalue())
        return out, err


class TestBzrServe(TestBzrServeBase):
    def setUp(self):
        super().setUp()
        self.disable_missing_extensions_warning()

    def test_server_exception_with_hook(self):
        """Catch exception from the server in the server_exception hook.

        We use ``run_bzr_serve_then_func`` without a ``func`` so the server
        will receive a KeyboardInterrupt exception we want to catch.
        """

        def hook(exception):
            if exception[0] is KeyboardInterrupt:
                sys.stderr.write(b"catching KeyboardInterrupt\n")
                return True
            else:
                return False

        SmartTCPServer.hooks.install_named_hook(
            "server_exception", hook, "test_server_except_hook hook"
        )
        args = ["--listen", "localhost", "--port", "0", "--quiet"]
        out, err = self.run_bzr_serve_then_func(args, retcode=0)
        self.assertEqual("catching KeyboardInterrupt\n", err)

    def test_server_exception_no_hook(self):
        """Test exception without hook returns error"""
        args = []
        out, err = self.run_bzr_serve_then_func(args, retcode=3)

    def assertInetServerShutsdownCleanly(self, process):
        """Shutdown the server process looking for errors."""
        # Shutdown the server: the server should shut down when it cannot read
        # from stdin anymore.
        process.stdin.close()
        # Hide stdin from the subprocess module, so it won't fail to close it.
        process.stdin = None
        result = self.finish_brz_subprocess(process)
        self.assertEqual(b"", result[0])
        self.assertEqual(b"", result[1])

    def assertServerFinishesCleanly(self, process):
        """Shutdown the brz serve instance process looking for errors."""
        # Shutdown the server
        result = self.finish_brz_subprocess(
            process, retcode=3, send_signal=signal.SIGINT
        )
        self.assertEqual(b"", result[0])
        self.assertEqual(b"brz: interrupted\n", result[1])

    def make_read_requests(self, branch):
        """Do some read only requests."""
        with branch.lock_read():
            branch.repository.all_revision_ids()
            self.assertEqual(_mod_revision.NULL_REVISION, branch.last_revision())

    def start_server_inet(self, extra_options=()):
        """Start a brz server subprocess using the --inet option.

        :param extra_options: extra options to give the server.
        :return: a tuple with the brz process handle for passing to
            finish_brz_subprocess, a client for the server, and a transport.
        """
        # Serve from the current directory
        args = ["serve", "--inet"]
        args.extend(extra_options)
        process = self.start_brz_subprocess(args)

        # Connect to the server
        # We use this url because while this is no valid URL to connect to this
        # server instance, the transport needs a URL.
        url = "bzr://localhost/"
        self.permit_url(url)
        client_medium = medium.SmartSimplePipesClientMedium(
            process.stdout, process.stdin, url
        )
        transport = remote.RemoteTransport(url, medium=client_medium)
        return process, transport

    def start_server_port(self, extra_options=()):
        """Start a brz server subprocess.

        :param extra_options: extra options to give the server.
        :return: a tuple with the brz process handle for passing to
            finish_brz_subprocess, and the base url for the server.
        """
        # Serve from the current directory
        args = ["serve", "--listen", "localhost", "--port", "0"]
        args.extend(extra_options)
        process = self.start_brz_subprocess(args, skip_if_plan_to_signal=True)
        port_line = process.stderr.readline()
        prefix = b"listening on port: "
        self.assertStartsWith(port_line, prefix)
        port = int(port_line[len(prefix) :])
        url = "bzr://localhost:%d/" % port
        self.permit_url(url)
        return process, url

    def test_bzr_serve_quiet(self):
        self.make_branch(".")
        args = ["--listen", "localhost", "--port", "0", "--quiet"]
        out, err = self.run_bzr_serve_then_func(args, retcode=3)
        self.assertEqual("", out)
        self.assertEqual("", err)

    def test_bzr_serve_inet_readonly(self):
        """Brz server should provide a read only filesystem by default."""
        process, transport = self.start_server_inet()
        self.assertRaises(errors.TransportNotPossible, transport.mkdir, "adir")
        self.assertInetServerShutsdownCleanly(process)

    def test_bzr_serve_inet_readwrite(self):
        # Make a branch
        self.make_branch(".")

        process, transport = self.start_server_inet(["--allow-writes"])

        # We get a working branch, and can create a directory
        branch = ControlDir.open_from_transport(transport).open_branch()
        self.make_read_requests(branch)
        transport.mkdir("adir")
        self.assertInetServerShutsdownCleanly(process)

    def test_bzr_serve_port_readonly(self):
        """Brz server should provide a read only filesystem by default."""
        process, url = self.start_server_port()
        t = transport.get_transport_from_url(url)
        self.assertRaises(errors.TransportNotPossible, t.mkdir, "adir")
        self.assertServerFinishesCleanly(process)

    def test_bzr_serve_port_readwrite(self):
        # Make a branch
        self.make_branch(".")

        process, url = self.start_server_port(["--allow-writes"])

        # Connect to the server
        branch = Branch.open(url)
        self.make_read_requests(branch)
        self.assertServerFinishesCleanly(process)

    def test_bzr_serve_supports_protocol(self):
        # Make a branch
        self.make_branch(".")

        process, url = self.start_server_port(["--allow-writes", "--protocol=bzr"])

        # Connect to the server
        branch = Branch.open(url)
        self.make_read_requests(branch)
        self.assertServerFinishesCleanly(process)

    def test_bzr_serve_dhpss(self):
        # This is a smoke test that the server doesn't crash when run with
        # -Dhpss, and does drop some hpss logging to the file.
        self.make_branch(".")
        log_fname = self.test_dir + "/server.log"
        self.overrideEnv("BRZ_LOG", log_fname)
        process, transport = self.start_server_inet(["-Dhpss"])
        branch = ControlDir.open_from_transport(transport).open_branch()
        self.make_read_requests(branch)
        self.assertInetServerShutsdownCleanly(process)
        f = open(log_fname, "rb")
        content = f.read()
        f.close()
        self.assertContainsRe(content, rb"hpss request: \[[0-9-]+\]")

    def test_bzr_serve_supports_configurable_timeout(self):
        gs = config.GlobalStack()
        gs.set("serve.client_timeout", 0.2)
        # Save the config as the subprocess will use it
        gs.store.save()
        process, url = self.start_server_port()
        self.build_tree_contents([("a_file", b"contents\n")])
        # We can connect and issue a request
        t = transport.get_transport_from_url(url)
        self.assertEqual(b"contents\n", t.get_bytes("a_file"))
        # However, if we just wait for more content from the server, it will
        # eventually disconnect us.
        m = t.get_smart_medium()
        m.read_bytes(1)
        # Now, we wait for timeout to trigger
        err = process.stderr.readline()
        self.assertEqual(
            b"Connection Timeout: disconnecting client after 0.2 seconds\n", err
        )
        self.assertServerFinishesCleanly(process)

    def test_bzr_serve_supports_client_timeout(self):
        process, url = self.start_server_port(["--client-timeout=0.1"])
        self.build_tree_contents([("a_file", b"contents\n")])
        # We can connect and issue a request
        t = transport.get_transport_from_url(url)
        self.assertEqual(b"contents\n", t.get_bytes("a_file"))
        # However, if we just wait for more content from the server, it will
        # eventually disconnect us.
        # TODO: Use something like signal.alarm() so that if the server doesn't
        #       properly handle the timeout, we end up failing the test instead
        #       of hanging forever.
        m = t.get_smart_medium()
        m.read_bytes(1)
        # Now, we wait for timeout to trigger
        err = process.stderr.readline()
        self.assertEqual(
            b"Connection Timeout: disconnecting client after 0.1 seconds\n", err
        )
        self.assertServerFinishesCleanly(process)

    def test_bzr_serve_graceful_shutdown(self):
        big_contents = b"a" * 64 * 1024
        self.build_tree_contents([("bigfile", big_contents)])
        process, url = self.start_server_port(["--client-timeout=1.0"])
        t = transport.get_transport_from_url(url)
        m = t.get_smart_medium()
        c = client._SmartClient(m)
        # Start, but don't finish a response
        resp, response_handler = c.call_expecting_body(b"get", b"bigfile")
        self.assertEqual((b"ok",), resp)
        # Note: process.send_signal is a Python 2.6ism
        process.send_signal(signal.SIGHUP)
        # Wait for the server to notice the signal, and then read the actual
        # body of the response. That way we know that it is waiting for the
        # request to finish
        self.assertEqual(b"Requested to stop gracefully\n", process.stderr.readline())
        self.assertIn(
            process.stderr.readline(), (b"", b"Waiting for 1 client(s) to finish\n")
        )
        body = response_handler.read_body_bytes()
        if body != big_contents:
            self.fail('Failed to properly read the contents of "bigfile"')
        # Now that our request is finished, the medium should notice it has
        # been disconnected.
        self.assertEqual(b"", m.read_bytes(1))
        # And the server should be stopping
        self.assertEqual(0, process.wait())


class TestCmdServeChrooting(TestBzrServeBase):
    def test_serve_tcp(self):
        """'brz serve' wraps the given --directory in a ChrootServer.

        So requests that search up through the parent directories (like
        find_repositoryV3) will give "not found" responses, rather than
        InvalidURLJoin or jail break errors.
        """
        t = self.get_transport()
        t.mkdir("server-root")
        self.run_bzr_serve_then_func(
            [
                "--listen",
                "127.0.0.1",
                "--port",
                "0",
                "--directory",
                t.local_abspath("server-root"),
                "--allow-writes",
            ],
            func=self.when_server_started,
        )
        # The when_server_started method issued a find_repositoryV3 that should
        # fail with 'norepository' because there are no repositories inside the
        # --directory.
        self.assertEqual((b"norepository",), self.client_resp)

    def when_server_started(self):
        # Connect to the TCP server and issue some requests and see what comes
        # back.
        client_medium = medium.SmartTCPClientMedium(
            "127.0.0.1",
            self.tcp_server.port,
            "bzr://localhost:%d/" % (self.tcp_server.port,),
        )
        smart_client = client._SmartClient(client_medium)
        resp = smart_client.call("mkdir", "foo", "")
        resp = smart_client.call("BzrDirFormat.initialize", "foo/")
        try:
            resp = smart_client.call("BzrDir.find_repositoryV3", "foo/")
        except errors.ErrorFromSmartServer as e:
            resp = e.error_tuple
        self.client_resp = resp
        client_medium.disconnect()


class TestUserdirExpansion(TestCaseWithMemoryTransport):
    @staticmethod
    def fake_expanduser(path):
        """A simple, environment-independent, function for the duration of this
        test.

        Paths starting with a path segment of '~user' will expand to start with
        '/home/user/'.  Every other path will be unchanged.
        """
        if path.split("/", 1)[0] == "~user":
            return "/home/user" + path[len("~user") :]
        return path

    def make_test_server(self, base_path="/"):
        """Make and start a BzrServerFactory, backed by a memory transport, and
        creat '/home/user' in that transport.
        """
        bzr_server = BzrServerFactory(self.fake_expanduser, lambda t: base_path)
        mem_transport = self.get_transport()
        mem_transport.mkdir("home")
        mem_transport.mkdir("home/user")
        bzr_server.set_up(mem_transport, None, None, inet=True, timeout=4.0)
        self.addCleanup(bzr_server.tear_down)
        return bzr_server

    def test_bzr_serve_expands_userdir(self):
        bzr_server = self.make_test_server()
        self.assertTrue(bzr_server.smart_server.backing_transport.has("~user"))

    def test_bzr_serve_does_not_expand_userdir_outside_base(self):
        bzr_server = self.make_test_server("/foo")
        self.assertFalse(bzr_server.smart_server.backing_transport.has("~user"))

    def test_get_base_path(self):
        """cmd_serve will turn the --directory option into a LocalTransport
        (optionally decorated with 'readonly+').  BzrServerFactory can
        determine the original --directory from that transport.
        """
        # URLs always include the trailing slash, and get_base_path returns it
        base_dir = osutils.abspath("/a/b/c") + "/"
        base_url = urlutils.local_path_to_url(base_dir) + "/"
        # Define a fake 'protocol' to capture the transport that cmd_serve
        # passes to serve_bzr.

        def capture_transport(transport, host, port, inet, timeout):
            self.bzr_serve_transport = transport

        cmd = builtins.cmd_serve()
        # Read-only
        cmd.run(directory=base_dir, protocol=capture_transport)
        server_maker = BzrServerFactory()
        self.assertEqual("readonly+%s" % base_url, self.bzr_serve_transport.base)
        self.assertEqual(base_dir, server_maker.get_base_path(self.bzr_serve_transport))
        # Read-write
        cmd.run(directory=base_dir, protocol=capture_transport, allow_writes=True)
        server_maker = BzrServerFactory()
        self.assertEqual(base_url, self.bzr_serve_transport.base)
        self.assertEqual(base_dir, server_maker.get_base_path(self.bzr_serve_transport))
        # Read-only, from a URL
        cmd.run(directory=base_url, protocol=capture_transport)
        server_maker = BzrServerFactory()
        self.assertEqual("readonly+%s" % base_url, self.bzr_serve_transport.base)
        self.assertEqual(base_dir, server_maker.get_base_path(self.bzr_serve_transport))
