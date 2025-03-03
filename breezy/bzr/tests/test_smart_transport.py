# Copyright (C) 2006-2016 Canonical Ltd
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

"""Tests for smart transport."""

# all of this deals with byte strings so this is safe
import doctest
import errno
import os
import socket
import subprocess
import sys
import threading
import time
from io import BytesIO
from typing import Optional

from testtools.matchers import DocTestMatches

import breezy

from ... import controldir, debug, errors, osutils, tests, urlutils
from ... import transport as _mod_transport
from ...tests import features, test_server
from ...transport import local, memory, remote, ssh
from ...transport.http import urllib
from .. import bzrdir
from ..remote import UnknownErrorFromSmartServer
from ..smart import client, medium, message, protocol, vfs
from ..smart import request as _mod_request
from ..smart import server as _mod_server
from . import test_smart


def create_file_pipes():
    r, w = os.pipe()
    # These must be opened without buffering, or we get undefined results
    rf = os.fdopen(r, "rb", 0)
    wf = os.fdopen(w, "wb", 0)
    return rf, wf


def portable_socket_pair():
    """Return a pair of TCP sockets connected to each other.

    Unlike socket.socketpair, this should work on Windows.
    """
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_sock.bind(("127.0.0.1", 0))
    listen_sock.listen(1)
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.connect(listen_sock.getsockname())
    server_sock, addr = listen_sock.accept()
    listen_sock.close()
    return server_sock, client_sock


class BytesIOSSHVendor:
    """A SSH vendor that uses BytesIO to buffer writes and answer reads."""

    def __init__(self, read_from, write_to):
        self.read_from = read_from
        self.write_to = write_to
        self.calls = []

    def connect_ssh(self, username, password, host, port, command):
        self.calls.append(("connect_ssh", username, password, host, port, command))
        return BytesIOSSHConnection(self)


class FirstRejectedBytesIOSSHVendor(BytesIOSSHVendor):
    """The first connection will be considered closed.

    The second connection will succeed normally.
    """

    def __init__(self, read_from, write_to, fail_at_write=True):
        super().__init__(read_from, write_to)
        self.fail_at_write = fail_at_write
        self._first = True

    def connect_ssh(self, username, password, host, port, command):
        self.calls.append(("connect_ssh", username, password, host, port, command))
        if self._first:
            self._first = False
            return ClosedSSHConnection(self)
        return BytesIOSSHConnection(self)


class BytesIOSSHConnection(ssh.SSHConnection):
    """A SSH connection that uses BytesIO to buffer writes and answer reads."""

    def __init__(self, vendor):
        self.vendor = vendor

    def close(self):
        self.vendor.calls.append(("close",))
        self.vendor.read_from.close()
        self.vendor.write_to.close()

    def get_sock_or_pipes(self):
        return "pipes", (self.vendor.read_from, self.vendor.write_to)


class ClosedSSHConnection(ssh.SSHConnection):
    """An SSH connection that just has closed channels."""

    def __init__(self, vendor):
        self.vendor = vendor

    def close(self):
        self.vendor.calls.append(("close",))

    def get_sock_or_pipes(self):
        # We create matching pipes, and then close the ssh side
        bzr_read, ssh_write = create_file_pipes()
        # We always fail when bzr goes to read
        ssh_write.close()
        if self.vendor.fail_at_write:
            # If set, we'll also fail when bzr goes to write
            ssh_read, bzr_write = create_file_pipes()
            ssh_read.close()
        else:
            bzr_write = self.vendor.write_to
        return "pipes", (bzr_read, bzr_write)


class _InvalidHostnameFeature(features.Feature):
    """Does 'non_existent.invalid' fail to resolve?

    RFC 2606 states that .invalid is reserved for invalid domain names, and
    also underscores are not a valid character in domain names.  Despite this,
    it's possible a badly misconfigured name server might decide to always
    return an address for any name, so this feature allows us to distinguish a
    broken system from a broken test.
    """

    def _probe(self):
        try:
            socket.gethostbyname("non_existent.invalid")
        except socket.gaierror:
            # The host name failed to resolve.  Good.
            return True
        else:
            return False

    def feature_name(self):
        return "invalid hostname"


InvalidHostnameFeature = _InvalidHostnameFeature()


class SmartClientMediumTests(tests.TestCase):
    """Tests for SmartClientMedium.

    We should create a test scenario for this: we need a server module that
    construct the test-servers (like make_loopsocket_and_medium), and the list
    of SmartClientMedium classes to test.
    """

    def make_loopsocket_and_medium(self):
        """Create a loopback socket for testing, and a medium aimed at it."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        client_medium = medium.SmartTCPClientMedium("127.0.0.1", port, "base")
        return sock, client_medium

    def receive_bytes_on_server(self, sock, bytes):
        """Accept a connection on sock and read 3 bytes.

        The bytes are appended to the list bytes.

        :return: a Thread which is running to do the accept and recv.
        """

        def _receive_bytes_on_server():
            connection, address = sock.accept()
            bytes.append(osutils.recv_all(connection, 3))
            connection.close()

        t = threading.Thread(target=_receive_bytes_on_server)
        t.start()
        return t

    def test_construct_smart_simple_pipes_client_medium(self):
        # the SimplePipes client medium takes two pipes:
        # readable pipe, writeable pipe.
        # Constructing one should just save these and do nothing.
        # We test this by passing in None.
        client_medium = medium.SmartSimplePipesClientMedium(None, None, None)
        del client_medium

    def test_simple_pipes_client_request_type(self):
        # SimplePipesClient should use SmartClientStreamMediumRequest's.
        client_medium = medium.SmartSimplePipesClientMedium(None, None, None)
        request = client_medium.get_request()
        self.assertIsInstance(request, medium.SmartClientStreamMediumRequest)

    def test_simple_pipes_client_get_concurrent_requests(self):
        # the simple_pipes client does not support pipelined requests:
        # but it does support serial requests: we construct one after
        # another is finished. This is a smoke test testing the integration
        # of the SmartClientStreamMediumRequest and the SmartClientStreamMedium
        # classes - as the sibling classes share this logic, they do not have
        # explicit tests for this.
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        request = client_medium.get_request()
        request.finished_writing()
        request.finished_reading()
        request2 = client_medium.get_request()
        request2.finished_writing()
        request2.finished_reading()

    def test_simple_pipes_client__accept_bytes_writes_to_writable(self):
        # accept_bytes writes to the writeable pipe.
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        client_medium._accept_bytes(b"abc")
        self.assertEqual(b"abc", output.getvalue())

    def test_simple_pipes__accept_bytes_subprocess_closed(self):
        # It is unfortunate that we have to use Popen for this. However,
        # os.pipe() does not behave the same as subprocess.Popen().
        # On Windows, if you use os.pipe() and close the write side,
        # read.read() hangs. On Linux, read.read() returns the empty string.
        p = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys\nsys.stdout.write(sys.stdin.read(4))\nsys.stdout.close()\n",
            ],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=0,
        )
        client_medium = medium.SmartSimplePipesClientMedium(p.stdout, p.stdin, "base")
        client_medium._accept_bytes(b"abc\n")
        self.assertEqual(b"abc", client_medium._read_bytes(3))
        p.wait()
        # While writing to the underlying pipe,
        #   Windows py2.6.6 we get IOError(EINVAL)
        #   Lucid py2.6.5, we get IOError(EPIPE)
        # In both cases, it should be wrapped to ConnectionReset
        self.assertRaises(errors.ConnectionReset, client_medium._accept_bytes, b"more")

    def test_simple_pipes__accept_bytes_pipe_closed(self):
        child_read, client_write = create_file_pipes()
        client_medium = medium.SmartSimplePipesClientMedium(None, client_write, "base")
        client_medium._accept_bytes(b"abc\n")
        self.assertEqual(b"abc\n", child_read.read(4))
        # While writing to the underlying pipe,
        #   Windows py2.6.6 we get IOError(EINVAL)
        #   Lucid py2.6.5, we get IOError(EPIPE)
        # In both cases, it should be wrapped to ConnectionReset
        child_read.close()
        self.assertRaises(errors.ConnectionReset, client_medium._accept_bytes, b"more")

    def test_simple_pipes__flush_pipe_closed(self):
        child_read, client_write = create_file_pipes()
        client_medium = medium.SmartSimplePipesClientMedium(None, client_write, "base")
        client_medium._accept_bytes(b"abc\n")
        child_read.close()
        # Even though the pipe is closed, flush on the write side seems to be a
        # no-op, rather than a failure.
        client_medium._flush()

    def test_simple_pipes__flush_subprocess_closed(self):
        p = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys\nsys.stdout.write(sys.stdin.read(4))\nsys.stdout.close()\n",
            ],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=0,
        )
        client_medium = medium.SmartSimplePipesClientMedium(p.stdout, p.stdin, "base")
        client_medium._accept_bytes(b"abc\n")
        p.wait()
        # Even though the child process is dead, flush seems to be a no-op.
        client_medium._flush()

    def test_simple_pipes__read_bytes_pipe_closed(self):
        child_read, client_write = create_file_pipes()
        client_medium = medium.SmartSimplePipesClientMedium(
            child_read, client_write, "base"
        )
        client_medium._accept_bytes(b"abc\n")
        client_write.close()
        self.assertEqual(b"abc\n", client_medium._read_bytes(4))
        self.assertEqual(b"", client_medium._read_bytes(4))

    def test_simple_pipes__read_bytes_subprocess_closed(self):
        p = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys\n"
                'if sys.platform == "win32":\n'
                "    import msvcrt, os\n"
                "    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)\n"
                "    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)\n"
                "sys.stdout.write(sys.stdin.read(4))\n"
                "sys.stdout.close()\n",
            ],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=0,
        )
        client_medium = medium.SmartSimplePipesClientMedium(p.stdout, p.stdin, "base")
        client_medium._accept_bytes(b"abc\n")
        p.wait()
        self.assertEqual(b"abc\n", client_medium._read_bytes(4))
        self.assertEqual(b"", client_medium._read_bytes(4))

    def test_simple_pipes_client_disconnect_does_nothing(self):
        # calling disconnect does nothing.
        input = BytesIO()
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        # send some bytes to ensure disconnecting after activity still does not
        # close.
        client_medium._accept_bytes(b"abc")
        client_medium.disconnect()
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)

    def test_simple_pipes_client_accept_bytes_after_disconnect(self):
        # calling disconnect on the client does not alter the pipe that
        # accept_bytes writes to.
        input = BytesIO()
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        client_medium._accept_bytes(b"abc")
        client_medium.disconnect()
        client_medium._accept_bytes(b"abc")
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)
        self.assertEqual(b"abcabc", output.getvalue())

    def test_simple_pipes_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SimplePipes medium
        # does nothing.
        client_medium = medium.SmartSimplePipesClientMedium(None, None, "base")
        client_medium.disconnect()

    def test_simple_pipes_client_can_always_read(self):
        # SmartSimplePipesClientMedium is never disconnected, so read_bytes
        # always tries to read from the underlying pipe.
        input = BytesIO(b"abcdef")
        client_medium = medium.SmartSimplePipesClientMedium(input, None, "base")
        self.assertEqual(b"abc", client_medium.read_bytes(3))
        client_medium.disconnect()
        self.assertEqual(b"def", client_medium.read_bytes(3))

    def test_simple_pipes_client_supports__flush(self):
        # invoking _flush on a SimplePipesClient should flush the output
        # pipe. We test this by creating an output pipe that records
        # flush calls made to it.
        from io import BytesIO  # get regular BytesIO

        input = BytesIO()
        output = BytesIO()
        flush_calls = []

        def logging_flush():
            flush_calls.append("flush")

        output.flush = logging_flush
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        # this call is here to ensure we only flush once, not on every
        # _accept_bytes call.
        client_medium._accept_bytes(b"abc")
        client_medium._flush()
        client_medium.disconnect()
        self.assertEqual(["flush"], flush_calls)

    def test_construct_smart_ssh_client_medium(self):
        # the SSH client medium takes:
        # host, port, username, password, vendor
        # Constructing one should just save these and do nothing.
        # we test this by creating a empty bound socket and constructing
        # a medium.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        unopened_port = sock.getsockname()[1]
        # having vendor be invalid means that if it tries to connect via the
        # vendor it will blow up.
        ssh_params = medium.SSHParams("127.0.0.1", unopened_port, None, None)
        client_medium = medium.SmartSSHClientMedium("base", ssh_params, "not a vendor")
        sock.close()
        del client_medium

    def test_ssh_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = BytesIO()
        vendor = BytesIOSSHVendor(BytesIO(), output)
        ssh_params = medium.SSHParams(
            "a hostname", "a port", "a username", "a password", "bzr"
        )
        client_medium = medium.SmartSSHClientMedium("base", ssh_params, vendor)
        client_medium._accept_bytes(b"abc")
        self.assertEqual(b"abc", output.getvalue())
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    "a username",
                    "a password",
                    "a hostname",
                    "a port",
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                )
            ],
            vendor.calls,
        )

    def test_ssh_client_changes_command_when_bzr_remote_path_passed(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = BytesIO()
        vendor = BytesIOSSHVendor(BytesIO(), output)
        ssh_params = medium.SSHParams(
            "a hostname", "a port", "a username", "a password", bzr_remote_path="fugly"
        )
        client_medium = medium.SmartSSHClientMedium("base", ssh_params, vendor)
        client_medium._accept_bytes(b"abc")
        self.assertEqual(b"abc", output.getvalue())
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    "a username",
                    "a password",
                    "a hostname",
                    "a port",
                    ["fugly", "serve", "--inet", "--directory=/", "--allow-writes"],
                )
            ],
            vendor.calls,
        )

    def test_ssh_client_disconnect_does_so(self):
        # calling disconnect should disconnect both the read_from and write_to
        # file-like object it from the ssh connection.
        input = BytesIO()
        output = BytesIO()
        vendor = BytesIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium(
            "base", medium.SSHParams("a hostname"), vendor
        )
        client_medium._accept_bytes(b"abc")
        client_medium.disconnect()
        self.assertTrue(input.closed)
        self.assertTrue(output.closed)
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    None,
                    None,
                    "a hostname",
                    None,
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
                ("close",),
            ],
            vendor.calls,
        )

    def test_ssh_client_disconnect_allows_reconnection(self):
        # calling disconnect on the client terminates the connection, but should
        # not prevent additional connections occuring.
        # we test this by initiating a second connection after doing a
        # disconnect.
        input = BytesIO()
        output = BytesIO()
        vendor = BytesIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium(
            "base", medium.SSHParams("a hostname"), vendor
        )
        client_medium._accept_bytes(b"abc")
        client_medium.disconnect()
        # the disconnect has closed output, so we need a new output for the
        # new connection to write to.
        input2 = BytesIO()
        output2 = BytesIO()
        vendor.read_from = input2
        vendor.write_to = output2
        client_medium._accept_bytes(b"abc")
        client_medium.disconnect()
        self.assertTrue(input.closed)
        self.assertTrue(output.closed)
        self.assertTrue(input2.closed)
        self.assertTrue(output2.closed)
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    None,
                    None,
                    "a hostname",
                    None,
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
                ("close",),
                (
                    "connect_ssh",
                    None,
                    None,
                    "a hostname",
                    None,
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
                ("close",),
            ],
            vendor.calls,
        )

    def test_ssh_client_repr(self):
        client_medium = medium.SmartSSHClientMedium(
            "base", medium.SSHParams("example.com", "4242", "username")
        )
        self.assertEqual(
            "SmartSSHClientMedium(bzr+ssh://username@example.com:4242/)",
            repr(client_medium),
        )

    def test_ssh_client_repr_no_port(self):
        client_medium = medium.SmartSSHClientMedium(
            "base", medium.SSHParams("example.com", None, "username")
        )
        self.assertEqual(
            "SmartSSHClientMedium(bzr+ssh://username@example.com/)", repr(client_medium)
        )

    def test_ssh_client_repr_no_username(self):
        client_medium = medium.SmartSSHClientMedium(
            "base", medium.SSHParams("example.com", None, None)
        )
        self.assertEqual(
            "SmartSSHClientMedium(bzr+ssh://example.com/)", repr(client_medium)
        )

    def test_ssh_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SSH medium
        # does not fail.  It's ok to disconnect an unconnected medium.
        client_medium = medium.SmartSSHClientMedium("base", medium.SSHParams(None))
        client_medium.disconnect()

    def test_ssh_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) SSH medium raises
        # MediumNotConnected.
        client_medium = medium.SmartSSHClientMedium("base", medium.SSHParams(None))
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 0)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 1)

    def test_ssh_client_supports__flush(self):
        # invoking _flush on a SSHClientMedium should flush the output
        # pipe. We test this by creating an output pipe that records
        # flush calls made to it.
        from io import BytesIO  # get regular BytesIO

        input = BytesIO()
        output = BytesIO()
        flush_calls = []

        def logging_flush():
            flush_calls.append("flush")

        output.flush = logging_flush
        vendor = BytesIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium(
            "base", medium.SSHParams("a hostname"), vendor=vendor
        )
        # this call is here to ensure we only flush once, not on every
        # _accept_bytes call.
        client_medium._accept_bytes(b"abc")
        client_medium._flush()
        client_medium.disconnect()
        self.assertEqual(["flush"], flush_calls)

    def test_construct_smart_tcp_client_medium(self):
        # the TCP client medium takes a host and a port.  Constructing it won't
        # connect to anything.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        unopened_port = sock.getsockname()[1]
        client_medium = medium.SmartTCPClientMedium("127.0.0.1", unopened_port, "base")
        sock.close()
        del client_medium

    def test_tcp_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        medium.accept_bytes(b"abc")
        t.join()
        sock.close()
        self.assertEqual([b"abc"], bytes)

    def test_tcp_client_disconnect_does_so(self):
        # calling disconnect on the client terminates the connection.
        # we test this by forcing a short read during a socket.MSG_WAITALL
        # call: write 2 bytes, try to read 3, and then the client disconnects.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        medium.accept_bytes(b"ab")
        medium.disconnect()
        t.join()
        sock.close()
        self.assertEqual([b"ab"], bytes)
        # now disconnect again: this should not do anything, if disconnection
        # really did disconnect.
        medium.disconnect()

    def test_tcp_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) TCP medium
        # does not fail.  It's ok to disconnect an unconnected medium.
        client_medium = medium.SmartTCPClientMedium(None, None, None)
        client_medium.disconnect()

    def test_tcp_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) TCP medium raises
        # MediumNotConnected.
        client_medium = medium.SmartTCPClientMedium(None, None, None)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 0)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 1)

    def test_tcp_client_supports__flush(self):
        # invoking _flush on a TCPClientMedium should do something useful.
        # RBC 20060922 not sure how to test/tell in this case.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        # try with nothing buffered
        medium._flush()
        medium._accept_bytes(b"ab")
        # and with something sent.
        medium._flush()
        medium.disconnect()
        t.join()
        sock.close()
        self.assertEqual([b"ab"], bytes)
        # now disconnect again : this should not do anything, if disconnection
        # really did disconnect.
        medium.disconnect()

    def test_tcp_client_host_unknown_connection_error(self):
        self.requireFeature(InvalidHostnameFeature)
        client_medium = medium.SmartTCPClientMedium(
            "non_existent.invalid", 4155, "base"
        )
        self.assertRaises(errors.ConnectionError, client_medium._ensure_connection)


class TestSmartClientStreamMediumRequest(tests.TestCase):
    """Tests the for SmartClientStreamMediumRequest.

    SmartClientStreamMediumRequest is a helper for the three stream based
    mediums: TCP, SSH, SimplePipes, so we only test it once, and then test that
    those three mediums implement the interface it expects.
    """

    def test_accept_bytes_after_finished_writing_errors(self):
        # calling accept_bytes after calling finished_writing raises
        # WritingCompleted to prevent bad assumptions on stream environments
        # breaking the needs of message-based environments.
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        self.assertRaises(errors.WritingCompleted, request.accept_bytes, None)

    def test_accept_bytes(self):
        # accept bytes should invoke _accept_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the pipes get the data.
        input = BytesIO()
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.accept_bytes(b"123")
        request.finished_writing()
        request.finished_reading()
        self.assertEqual(b"", input.getvalue())
        self.assertEqual(b"123", output.getvalue())

    def test_construct_sets_stream_request(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium sets
        # the current request to the new SmartClientStreamMediumRequest
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertIs(client_medium._current_request, request)

    def test_construct_while_another_request_active_throws(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium with
        # a non-None _current_request raises TooManyConcurrentRequests.
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        client_medium._current_request = "a"
        self.assertRaises(
            medium.TooManyConcurrentRequests,
            medium.SmartClientStreamMediumRequest,
            client_medium,
        )

    def test_finished_read_clears_current_request(self):
        # calling finished_reading clears the current request from the requests
        # medium
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        request.finished_reading()
        self.assertEqual(None, client_medium._current_request)

    def test_finished_read_before_finished_write_errors(self):
        # calling finished_reading before calling finished_writing triggers a
        # WritingNotComplete error.
        client_medium = medium.SmartSimplePipesClientMedium(None, None, "base")
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertRaises(errors.WritingNotComplete, request.finished_reading)

    def test_read_bytes(self):
        # read bytes should invoke _read_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the data is supplied. Its possible that a
        # faulty implementation could poke at the pipe variables them selves,
        # but we trust that this will be caught as it will break the integration
        # smoke tests.
        input = BytesIO(b"321")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        self.assertEqual(b"321", request.read_bytes(3))
        request.finished_reading()
        self.assertEqual(b"", input.read())
        self.assertEqual(b"", output.getvalue())

    def test_read_bytes_before_finished_write_errors(self):
        # calling read_bytes before calling finished_writing triggers a
        # WritingNotComplete error because the Smart protocol is designed to be
        # compatible with strict message based protocols like HTTP where the
        # request cannot be submitted until the writing has completed.
        client_medium = medium.SmartSimplePipesClientMedium(None, None, "base")
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertRaises(errors.WritingNotComplete, request.read_bytes, None)

    def test_read_bytes_after_finished_reading_errors(self):
        # calling read_bytes after calling finished_reading raises
        # ReadingCompleted to prevent bad assumptions on stream environments
        # breaking the needs of message-based environments.
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        request.finished_reading()
        self.assertRaises(errors.ReadingCompleted, request.read_bytes, None)

    def test_reset(self):
        server_sock, client_sock = portable_socket_pair()
        # TODO: Use SmartClientAlreadyConnectedSocketMedium for the versions of
        #       bzr where it exists.
        client_medium = medium.SmartTCPClientMedium(None, None, None)
        client_medium._socket = client_sock
        client_medium._connected = True
        req = client_medium.get_request()
        self.assertRaises(medium.TooManyConcurrentRequests, client_medium.get_request)
        client_medium.reset()
        # The stream should be reset, marked as disconnected, though ready for
        # us to make a new request
        self.assertFalse(client_medium._connected)
        self.assertIs(None, client_medium._socket)
        try:
            self.assertEqual("", client_sock.recv(1))
        except OSError as e:
            if e.errno not in (errno.EBADF,):
                raise
        req = client_medium.get_request()
        del req


class RemoteTransportTests(test_smart.TestCaseWithSmartMedium):
    def test_plausible_url(self):
        self.assertTrue(self.get_url().startswith("bzr://"))

    def test_probe_transport(self):
        t = self.get_transport()
        self.assertIsInstance(t, remote.RemoteTransport)

    def test_get_medium_from_transport(self):
        """Remote transport has a medium always, which it can return."""
        t = self.get_transport()
        client_medium = t.get_smart_medium()
        self.assertIsInstance(client_medium, medium.SmartClientMedium)


class ErrorRaisingProtocol:
    def __init__(self, exception):
        self.exception = exception

    def next_read_size(self):
        raise self.exception


class SampleRequest:
    def __init__(self, expected_bytes):
        self.accepted_bytes = b""
        self._finished_reading = False
        self.expected_bytes = expected_bytes
        self.unused_data = b""

    def accept_bytes(self, bytes):
        self.accepted_bytes += bytes
        if self.accepted_bytes.startswith(self.expected_bytes):
            self._finished_reading = True
            self.unused_data = self.accepted_bytes[len(self.expected_bytes) :]

    def next_read_size(self):
        if self._finished_reading:
            return 0
        else:
            return 1


class TestSmartServerStreamMedium(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideEnv("BRZ_NO_SMART_VFS", None)

    def create_pipe_medium(self, to_server, from_server, transport, timeout=4.0):
        """Create a new SmartServerPipeStreamMedium."""
        return medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport, timeout=timeout
        )

    def create_pipe_context(self, to_server_bytes, transport):
        """Create a SmartServerSocketStreamMedium.

        This differes from create_pipe_medium, in that we initialize the
        request that is sent to the server, and return the BytesIO class that
        will hold the response.
        """
        to_server = BytesIO(to_server_bytes)
        from_server = BytesIO()
        m = self.create_pipe_medium(to_server, from_server, transport)
        return m, from_server

    def create_socket_medium(self, server_sock, transport, timeout=4.0):
        """Initialize a new medium.SmartServerSocketStreamMedium."""
        return medium.SmartServerSocketStreamMedium(
            server_sock, transport, timeout=timeout
        )

    def create_socket_context(self, transport, timeout=4.0):
        """Create a new SmartServerSocketStreamMedium with default context.

        This will call portable_socket_pair and pass the server side to
        create_socket_medium along with transport.
        It then returns the client_sock and the server.
        """
        server_sock, client_sock = portable_socket_pair()
        server = self.create_socket_medium(server_sock, transport, timeout=timeout)
        return server, client_sock

    def test_smart_query_version(self):
        """Feed a canned query version to a server."""
        # wire-to-wire, using the whole stack
        transport = local.LocalTransport(urlutils.local_path_to_url("/"))
        server, from_server = self.create_pipe_context(b"hello\n", transport)
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            transport, from_server.write
        )
        server._serve_one_request(smart_protocol)
        self.assertEqual(b"ok\0012\n", from_server.getvalue())

    def test_response_to_canned_get(self):
        transport = memory.MemoryTransport("memory:///")
        transport.put_bytes("testfile", b"contents\nof\nfile\n")
        server, from_server = self.create_pipe_context(
            b"get\001./testfile\n", transport
        )
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            transport, from_server.write
        )
        server._serve_one_request(smart_protocol)
        self.assertEqual(b"ok\n17\ncontents\nof\nfile\ndone\n", from_server.getvalue())

    def test_response_to_canned_get_of_utf8(self):
        # wire-to-wire, using the whole stack, with a UTF-8 filename.
        transport = memory.MemoryTransport("memory:///")
        utf8_filename = "testfile\N{INTERROBANG}".encode()
        # VFS requests use filenames, not raw UTF-8.
        hpss_path = urlutils.quote_from_bytes(utf8_filename)
        transport.put_bytes(hpss_path, b"contents\nof\nfile\n")
        server, from_server = self.create_pipe_context(
            b"get\001" + hpss_path.encode("ascii") + b"\n", transport
        )
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            transport, from_server.write
        )
        server._serve_one_request(smart_protocol)
        self.assertEqual(b"ok\n17\ncontents\nof\nfile\ndone\n", from_server.getvalue())

    def test_pipe_like_stream_with_bulk_data(self):
        sample_request_bytes = b"command\n9\nbulk datadone\n"
        server, from_server = self.create_pipe_context(sample_request_bytes, None)
        sample_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(sample_protocol)
        self.assertEqual(b"", from_server.getvalue())
        self.assertEqual(sample_request_bytes, sample_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_socket_stream_with_bulk_data(self):
        sample_request_bytes = b"command\n9\nbulk datadone\n"
        server, client_sock = self.create_socket_context(None)
        sample_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        client_sock.sendall(sample_request_bytes)
        server._serve_one_request(sample_protocol)
        server._disconnect_client()
        self.assertEqual(b"", client_sock.recv(1))
        self.assertEqual(sample_request_bytes, sample_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_pipe_like_stream_shutdown_detection(self):
        server, _ = self.create_pipe_context(b"", None)
        server._serve_one_request(SampleRequest(b"x"))
        self.assertTrue(server.finished)

    def test_socket_stream_shutdown_detection(self):
        server, client_sock = self.create_socket_context(None)
        client_sock.close()
        server._serve_one_request(SampleRequest(b"x"))
        self.assertTrue(server.finished)

    def test_socket_stream_incomplete_request(self):
        """The medium should still construct the right protocol version even if
        the initial read only reads part of the request.

        Specifically, it should correctly read the protocol version line even
        if the partial read doesn't end in a newline.  An older, naive
        implementation of _get_line in the server used to have a bug in that
        case.
        """
        incomplete_request_bytes = protocol.REQUEST_VERSION_TWO + b"hel"
        rest_of_request_bytes = b"lo\n"
        expected_response = protocol.RESPONSE_VERSION_TWO + b"success\nok\x012\n"
        server, client_sock = self.create_socket_context(None)
        client_sock.sendall(incomplete_request_bytes)
        server_protocol = server._build_protocol()
        client_sock.sendall(rest_of_request_bytes)
        server._serve_one_request(server_protocol)
        server._disconnect_client()
        self.assertEqual(
            expected_response,
            osutils.recv_all(client_sock, 50),
            "Not a version 2 response to 'hello' request.",
        )
        self.assertEqual(b"", client_sock.recv(1))

    def test_pipe_stream_incomplete_request(self):
        """The medium should still construct the right protocol version even if
        the initial read only reads part of the request.

        Specifically, it should correctly read the protocol version line even
        if the partial read doesn't end in a newline.  An older, naive
        implementation of _get_line in the server used to have a bug in that
        case.
        """
        incomplete_request_bytes = protocol.REQUEST_VERSION_TWO + b"hel"
        rest_of_request_bytes = b"lo\n"
        expected_response = protocol.RESPONSE_VERSION_TWO + b"success\nok\x012\n"
        # Make a pair of pipes, to and from the server
        to_server, to_server_w = os.pipe()
        from_server_r, from_server = os.pipe()
        to_server = os.fdopen(to_server, "rb", 0)
        to_server_w = os.fdopen(to_server_w, "wb", 0)
        from_server_r = os.fdopen(from_server_r, "rb", 0)
        from_server = os.fdopen(from_server, "wb", 0)
        server = self.create_pipe_medium(to_server, from_server, None)
        # Like test_socket_stream_incomplete_request, write an incomplete
        # request (that does not end in '\n') and build a protocol from it.
        to_server_w.write(incomplete_request_bytes)
        server_protocol = server._build_protocol()
        # Send the rest of the request, and finish serving it.
        to_server_w.write(rest_of_request_bytes)
        server._serve_one_request(server_protocol)
        to_server_w.close()
        from_server.close()
        self.assertEqual(
            expected_response,
            from_server_r.read(),
            "Not a version 2 response to 'hello' request.",
        )
        self.assertEqual(b"", from_server_r.read(1))
        from_server_r.close()
        to_server.close()

    def test_pipe_like_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received separately.
        sample_request_bytes = b"command\n"
        server, from_server = self.create_pipe_context(sample_request_bytes * 2, None)
        first_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(first_protocol)
        self.assertEqual(0, first_protocol.next_read_size())
        self.assertEqual(b"", from_server.getvalue())
        self.assertFalse(server.finished)
        # Make a new protocol, call _serve_one_request with it to collect the
        # second request.
        second_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(second_protocol)
        self.assertEqual(b"", from_server.getvalue())
        self.assertEqual(sample_request_bytes, second_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_socket_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received separately.
        sample_request_bytes = b"command\n"
        server, client_sock = self.create_socket_context(None)
        first_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        # Put two whole requests on the wire.
        client_sock.sendall(sample_request_bytes * 2)
        server._serve_one_request(first_protocol)
        self.assertEqual(0, first_protocol.next_read_size())
        self.assertFalse(server.finished)
        # Make a new protocol, call _serve_one_request with it to collect the
        # second request.
        second_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        stream_still_open = server._serve_one_request(second_protocol)
        self.assertEqual(sample_request_bytes, second_protocol.accepted_bytes)
        self.assertFalse(server.finished)
        server._disconnect_client()
        self.assertEqual(b"", client_sock.recv(1))
        del stream_still_open

    def test_pipe_like_stream_error_handling(self):
        # Use plain python BytesIO so we can monkey-patch the close method to
        # not discard the contents.
        from io import BytesIO

        to_server = BytesIO(b"")
        from_server = BytesIO()
        self.closed = False

        def close():
            self.closed = True

        from_server.close = close
        server = self.create_pipe_medium(to_server, from_server, None)
        fake_protocol = ErrorRaisingProtocol(Exception("boom"))
        server._serve_one_request(fake_protocol)
        self.assertEqual(b"", from_server.getvalue())
        self.assertTrue(self.closed)
        self.assertTrue(server.finished)

    def test_socket_stream_error_handling(self):
        server, client_sock = self.create_socket_context(None)
        fake_protocol = ErrorRaisingProtocol(Exception("boom"))
        server._serve_one_request(fake_protocol)
        # recv should not block, because the other end of the socket has been
        # closed.
        self.assertEqual(b"", client_sock.recv(1))
        self.assertTrue(server.finished)

    def test_pipe_like_stream_keyboard_interrupt_handling(self):
        server, from_server = self.create_pipe_context(b"", None)
        fake_protocol = ErrorRaisingProtocol(KeyboardInterrupt("boom"))
        self.assertRaises(KeyboardInterrupt, server._serve_one_request, fake_protocol)
        self.assertEqual(b"", from_server.getvalue())

    def test_socket_stream_keyboard_interrupt_handling(self):
        server, client_sock = self.create_socket_context(None)
        fake_protocol = ErrorRaisingProtocol(KeyboardInterrupt("boom"))
        self.assertRaises(KeyboardInterrupt, server._serve_one_request, fake_protocol)
        server._disconnect_client()
        self.assertEqual(b"", client_sock.recv(1))

    def build_protocol_pipe_like(self, bytes):
        server, _ = self.create_pipe_context(bytes, None)
        return server._build_protocol()

    def build_protocol_socket(self, bytes):
        server, client_sock = self.create_socket_context(None)
        client_sock.sendall(bytes)
        client_sock.close()
        return server._build_protocol()

    def assertProtocolOne(self, server_protocol):
        # Use assertIs because assertIsInstance will wrongly pass
        # SmartServerRequestProtocolTwo (because it subclasses
        # SmartServerRequestProtocolOne).
        self.assertIs(type(server_protocol), protocol.SmartServerRequestProtocolOne)

    def assertProtocolTwo(self, server_protocol):
        self.assertIsInstance(server_protocol, protocol.SmartServerRequestProtocolTwo)

    def test_pipe_like_build_protocol_empty_bytes(self):
        # Any empty request (i.e. no bytes) is detected as protocol version one.
        server_protocol = self.build_protocol_pipe_like(b"")
        self.assertProtocolOne(server_protocol)

    def test_socket_like_build_protocol_empty_bytes(self):
        # Any empty request (i.e. no bytes) is detected as protocol version one.
        server_protocol = self.build_protocol_socket(b"")
        self.assertProtocolOne(server_protocol)

    def test_pipe_like_build_protocol_non_two(self):
        # A request that doesn't start with "bzr request 2\n" is version one.
        server_protocol = self.build_protocol_pipe_like(b"abc\n")
        self.assertProtocolOne(server_protocol)

    def test_socket_build_protocol_non_two(self):
        # A request that doesn't start with "bzr request 2\n" is version one.
        server_protocol = self.build_protocol_socket(b"abc\n")
        self.assertProtocolOne(server_protocol)

    def test_pipe_like_build_protocol_two(self):
        # A request that starts with "bzr request 2\n" is version two.
        server_protocol = self.build_protocol_pipe_like(b"bzr request 2\n")
        self.assertProtocolTwo(server_protocol)

    def test_socket_build_protocol_two(self):
        # A request that starts with "bzr request 2\n" is version two.
        server_protocol = self.build_protocol_socket(b"bzr request 2\n")
        self.assertProtocolTwo(server_protocol)

    def test__build_protocol_returns_if_stopping(self):
        # _build_protocol should notice that we are stopping, and return
        # without waiting for bytes from the client.
        server, client_sock = self.create_socket_context(None)
        server._stop_gracefully()
        self.assertIs(None, server._build_protocol())

    def test_socket_set_timeout(self):
        server, _ = self.create_socket_context(None, timeout=1.23)
        self.assertEqual(1.23, server._client_timeout)

    def test_pipe_set_timeout(self):
        server = self.create_pipe_medium(None, None, None, timeout=1.23)
        self.assertEqual(1.23, server._client_timeout)

    def test_socket_wait_for_bytes_with_timeout_with_data(self):
        server, client_sock = self.create_socket_context(None)
        client_sock.sendall(b"data\n")
        # This should not block or consume any actual content
        self.assertFalse(server._wait_for_bytes_with_timeout(0.1))
        data = server.read_bytes(5)
        self.assertEqual(b"data\n", data)

    def test_socket_wait_for_bytes_with_timeout_no_data(self):
        server, client_sock = self.create_socket_context(None)
        # This should timeout quickly, reporting that there wasn't any data
        self.assertRaises(
            errors.ConnectionTimeout, server._wait_for_bytes_with_timeout, 0.01
        )
        client_sock.close()
        data = server.read_bytes(1)
        self.assertEqual(b"", data)

    def test_socket_wait_for_bytes_with_timeout_closed(self):
        server, client_sock = self.create_socket_context(None)
        # With the socket closed, this should return right away.
        # It seems select.select() returns that you *can* read on the socket,
        # even though it closed. Presumably as a way to tell it is closed?
        # Testing shows that without sock.close() this times-out failing the
        # test, but with it, it returns False immediately.
        client_sock.close()
        self.assertFalse(server._wait_for_bytes_with_timeout(10))
        data = server.read_bytes(1)
        self.assertEqual(b"", data)

    def test_socket_wait_for_bytes_with_shutdown(self):
        server, client_sock = self.create_socket_context(None)
        t = time.time()
        # Override the _timer functionality, so that time never increments,
        # this way, we can be sure we stopped because of the flag, and not
        # because of a timeout, etc.
        server._timer = lambda: t
        server._client_poll_timeout = 0.1
        server._stop_gracefully()
        server._wait_for_bytes_with_timeout(1.0)

    def test_socket_serve_timeout_closes_socket(self):
        server, client_sock = self.create_socket_context(None, timeout=0.1)
        # This should timeout quickly, and then close the connection so that
        # client_sock recv doesn't block.
        server.serve()
        self.assertEqual(b"", client_sock.recv(1))

    def test_pipe_wait_for_bytes_with_timeout_with_data(self):
        # We intentionally use a real pipe here, so that we can 'select' on it.
        # You can't select() on a BytesIO
        (r_server, w_client) = os.pipe()
        self.addCleanup(os.close, w_client)
        with os.fdopen(r_server, "rb") as rf_server:
            server = self.create_pipe_medium(rf_server, None, None)
            os.write(w_client, b"data\n")
            # This should not block or consume any actual content
            server._wait_for_bytes_with_timeout(0.1)
            data = server.read_bytes(5)
            self.assertEqual(b"data\n", data)

    def test_pipe_wait_for_bytes_with_timeout_no_data(self):
        # We intentionally use a real pipe here, so that we can 'select' on it.
        # You can't select() on a BytesIO
        (r_server, w_client) = os.pipe()
        # We can't add an os.close cleanup here, because we need to control
        # when the file handle gets closed ourselves.
        with os.fdopen(r_server, "rb") as rf_server:
            server = self.create_pipe_medium(rf_server, None, None)
            if sys.platform == "win32":
                # Windows cannot select() on a pipe, so we just always return
                server._wait_for_bytes_with_timeout(0.01)
            else:
                self.assertRaises(
                    errors.ConnectionTimeout, server._wait_for_bytes_with_timeout, 0.01
                )
            os.close(w_client)
            data = server.read_bytes(5)
            self.assertEqual(b"", data)

    def test_pipe_wait_for_bytes_no_fileno(self):
        server, _ = self.create_pipe_context(b"", None)
        # Our file doesn't support polling, so we should always just return
        # 'you have data to consume.
        server._wait_for_bytes_with_timeout(0.01)


class TestGetProtocolFactoryForBytes(tests.TestCase):
    """_get_protocol_factory_for_bytes identifies the protocol factory a server
    should use to decode a given request.  Any bytes not part of the version
    marker string (and thus part of the actual request) are returned alongside
    the protocol factory.
    """

    def test_version_three(self):
        result = medium._get_protocol_factory_for_bytes(
            b"bzr message 3 (bzr 1.6)\nextra bytes"
        )
        protocol_factory, remainder = result
        self.assertEqual(protocol.build_server_protocol_three, protocol_factory)
        self.assertEqual(b"extra bytes", remainder)

    def test_version_two(self):
        result = medium._get_protocol_factory_for_bytes(b"bzr request 2\nextra bytes")
        protocol_factory, remainder = result
        self.assertEqual(protocol.SmartServerRequestProtocolTwo, protocol_factory)
        self.assertEqual(b"extra bytes", remainder)

    def test_version_one(self):
        """Version one requests have no version markers."""
        result = medium._get_protocol_factory_for_bytes(b"anything\n")
        protocol_factory, remainder = result
        self.assertEqual(protocol.SmartServerRequestProtocolOne, protocol_factory)
        self.assertEqual(b"anything\n", remainder)


class TestSmartTCPServer(tests.TestCase):
    def make_server(self):
        """Create a SmartTCPServer that we can exercise.

        Note: we don't use SmartTCPServer_for_testing because the testing
        version overrides lots of functionality like 'serve', and we want to
        test the raw service.

        This will start the server in another thread, and wait for it to
        indicate it has finished starting up.

        :return: (server, server_thread)
        """
        t = _mod_transport.get_transport_from_url("memory:///")
        server = _mod_server.SmartTCPServer(t, client_timeout=4.0)
        server._ACCEPT_TIMEOUT = 0.1
        # We don't use 'localhost' because that might be an IPv6 address.
        server.start_server("127.0.0.1", 0)
        server_thread = threading.Thread(target=server.serve, args=(self.id(),))
        server_thread.start()
        # Ensure this gets called at some point
        self.addCleanup(server._stop_gracefully)
        server._started.wait()
        return server, server_thread

    def ensure_client_disconnected(self, client_sock):
        """Ensure that a socket is closed, discarding all errors."""
        try:
            client_sock.close()
        except Exception:
            pass

    def connect_to_server(self, server):
        """Create a client socket that can talk to the server."""
        client_sock = socket.socket()
        server_info = server._server_socket.getsockname()
        client_sock.connect(server_info)
        self.addCleanup(self.ensure_client_disconnected, client_sock)
        return client_sock

    def connect_to_server_and_hangup(self, server):
        """Connect to the server, and then hang up.
        That way it doesn't sit waiting for 'accept()' to timeout.
        """
        # If the server has already signaled that the socket is closed, we
        # don't need to try to connect to it. Not being set, though, the server
        # might still close the socket while we try to connect to it. So we
        # still have to catch the exception.
        if server._stopped.is_set():
            return
        try:
            client_sock = self.connect_to_server(server)
            client_sock.close()
        except OSError:
            # If the server has hung up already, that is fine.
            pass

    def say_hello(self, client_sock):
        """Send the 'hello' smart RPC, and expect the response."""
        client_sock.send(b"hello\n")
        self.assertEqual(b"ok\x012\n", client_sock.recv(5))

    def shutdown_server_cleanly(self, server, server_thread):
        server._stop_gracefully()
        self.connect_to_server_and_hangup(server)
        server._stopped.wait()
        server._fully_stopped.wait()
        server_thread.join()

    def test_get_error_unexpected(self):
        """Error reported by server with no specific representation."""
        self.overrideEnv("BRZ_NO_SMART_VFS", None)

        class FlakyTransport:
            base = "a_url"

            def external_url(self):
                return self.base

            def get(self, path):
                raise Exception("some random exception from inside server")

        class FlakyServer(test_server.SmartTCPServer_for_testing):
            def get_backing_transport(self, backing_transport_server):
                return FlakyTransport()

        smart_server = FlakyServer()
        smart_server.start_server()
        self.addCleanup(smart_server.stop_server)
        t = remote.RemoteTCPTransport(smart_server.get_url())
        self.addCleanup(t.disconnect)
        err = self.assertRaises(UnknownErrorFromSmartServer, t.get, "something")
        self.assertContainsRe(str(err), "some random exception")

    def test_propagates_timeout(self):
        server = _mod_server.SmartTCPServer(None, client_timeout=1.23)
        server_sock, client_sock = portable_socket_pair()
        handler = server._make_handler(server_sock)
        self.assertEqual(1.23, handler._client_timeout)

    def test_serve_conn_tracks_connections(self):
        server = _mod_server.SmartTCPServer(None, client_timeout=4.0)
        server_sock, client_sock = portable_socket_pair()
        server.serve_conn(server_sock, "-{}".format(self.id()))
        self.assertEqual(1, len(server._active_connections))
        # We still want to talk on the connection. Polling should indicate it
        # is still active.
        server._poll_active_connections()
        self.assertEqual(1, len(server._active_connections))
        # Closing the socket will end the active thread, and polling will
        # notice and remove it from the active set.
        client_sock.close()
        server._poll_active_connections(0.1)
        self.assertEqual(0, len(server._active_connections))

    def test_serve_closes_out_finished_connections(self):
        server, server_thread = self.make_server()
        # The server is started, connect to it.
        client_sock = self.connect_to_server(server)
        # We send and receive on the connection, so that we know the
        # server-side has seen the connect, and started handling the
        # results.
        self.say_hello(client_sock)
        self.assertEqual(1, len(server._active_connections))
        # Grab a handle to the thread that is processing our request
        _, server_side_thread = server._active_connections[0]
        # Close the connection, ask the server to stop, and wait for the
        # server to stop, as well as the thread that was servicing the
        # client request.
        client_sock.close()
        # Wait for the server-side request thread to notice we are closed.
        server_side_thread.join()
        # Stop the server, it should notice the connection has finished.
        self.shutdown_server_cleanly(server, server_thread)
        # The server should have noticed that all clients are gone before
        # exiting.
        self.assertEqual(0, len(server._active_connections))

    def test_serve_reaps_finished_connections(self):
        server, server_thread = self.make_server()
        client_sock1 = self.connect_to_server(server)
        # We send and receive on the connection, so that we know the
        # server-side has seen the connect, and started handling the
        # results.
        self.say_hello(client_sock1)
        server_handler1, server_side_thread1 = server._active_connections[0]
        client_sock1.close()
        server_side_thread1.join()
        # By waiting until the first connection is fully done, the server
        # should notice after another connection that the first has finished.
        client_sock2 = self.connect_to_server(server)
        self.say_hello(client_sock2)
        server_handler2, server_side_thread2 = server._active_connections[-1]
        # There is a race condition. We know that client_sock2 has been
        # registered, but not that _poll_active_connections has been called. We
        # know that it will be called before the server will accept a new
        # connection, however. So connect one more time, and assert that we
        # either have 1 or 2 active connections (never 3), and that the 'first'
        # connection is not connection 1
        client_sock3 = self.connect_to_server(server)
        self.say_hello(client_sock3)
        # Copy the list, so we don't have it mutating behind our back
        conns = list(server._active_connections)
        self.assertEqual(2, len(conns))
        self.assertNotEqual((server_handler1, server_side_thread1), conns[0])
        self.assertEqual((server_handler2, server_side_thread2), conns[0])
        client_sock2.close()
        client_sock3.close()
        self.shutdown_server_cleanly(server, server_thread)

    def test_graceful_shutdown_waits_for_clients_to_stop(self):
        server, server_thread = self.make_server()
        # We need something big enough that it won't fit in a single recv. So
        # the server thread gets blocked writing content to the client until we
        # finish reading on the client.
        server.backing_transport.put_bytes("bigfile", b"a" * 1024 * 1024)
        client_sock = self.connect_to_server(server)
        self.say_hello(client_sock)
        _, server_side_thread = server._active_connections[0]
        # Start the RPC, but don't finish reading the response
        client_medium = medium.SmartClientAlreadyConnectedSocketMedium(
            "base", client_sock
        )
        client_client = client._SmartClient(client_medium)
        resp, response_handler = client_client.call_expecting_body(b"get", b"bigfile")
        self.assertEqual((b"ok",), resp)
        # Ask the server to stop gracefully, and wait for it.
        server._stop_gracefully()
        self.connect_to_server_and_hangup(server)
        server._stopped.wait()
        # It should not be accepting another connection.
        self.assertRaises(socket.error, self.connect_to_server, server)
        response_handler.read_body_bytes()
        client_sock.close()
        server_side_thread.join()
        server_thread.join()
        self.assertTrue(server._fully_stopped.is_set())
        log = self.get_log()
        self.assertThat(
            log,
            DocTestMatches(
                """\
    INFO  Requested to stop gracefully
... Stopping SmartServerSocketStreamMedium(client=('127.0.0.1', ...
""",
                flags=doctest.ELLIPSIS | doctest.REPORT_UDIFF,
            ),
        )

    def test_stop_gracefully_tells_handlers_to_stop(self):
        server, server_thread = self.make_server()
        client_sock = self.connect_to_server(server)
        self.say_hello(client_sock)
        server_handler, server_side_thread = server._active_connections[0]
        self.assertFalse(server_handler.finished)
        server._stop_gracefully()
        self.assertTrue(server_handler.finished)
        client_sock.close()
        self.connect_to_server_and_hangup(server)
        server_thread.join()


class SmartTCPTests(tests.TestCase):
    """Tests for connection/end to end behaviour using the TCP server.

    All of these tests are run with a server running in another thread serving
    a MemoryTransport, and a connection to it already open.

    the server is obtained by calling self.start_server(readonly=False).
    """

    def start_server(self, readonly=False, backing_transport=None):
        """Setup the server.

        :param readonly: Create a readonly server.
        """
        # NB: Tests using this fall into two categories: tests of the server,
        # tests wanting a server. The latter should be updated to use
        # self.vfs_transport_factory etc.
        if backing_transport is None:
            mem_server = memory.MemoryServer()
            mem_server.start_server()
            self.addCleanup(mem_server.stop_server)
            self.permit_url(mem_server.get_url())
            self.backing_transport = _mod_transport.get_transport_from_url(
                mem_server.get_url()
            )
        else:
            self.backing_transport = backing_transport
        if readonly:
            self.real_backing_transport = self.backing_transport
            self.backing_transport = _mod_transport.get_transport_from_url(
                "readonly+" + self.backing_transport.abspath(".")
            )
        self.server = _mod_server.SmartTCPServer(
            self.backing_transport, client_timeout=4.0
        )
        self.server.start_server("127.0.0.1", 0)
        self.server.start_background_thread("-" + self.id())
        self.transport = remote.RemoteTCPTransport(self.server.get_url())
        self.addCleanup(self.stop_server)
        self.permit_url(self.server.get_url())

    def stop_server(self):
        """Disconnect the client and stop the server.

        This must be re-entrant as some tests will call it explicitly in
        addition to the normal cleanup.
        """
        if getattr(self, "transport", None):
            self.transport.disconnect()
            del self.transport
        if getattr(self, "server", None):
            self.server.stop_background_thread()
            del self.server


class TestServerSocketUsage(SmartTCPTests):
    def test_server_start_stop(self):
        """It should be safe to stop the server with no requests."""
        self.start_server()
        t = remote.RemoteTCPTransport(self.server.get_url())
        self.stop_server()
        self.assertRaises(errors.ConnectionError, t.has, ".")

    def test_server_closes_listening_sock_on_shutdown_after_request(self):
        """The server should close its listening socket when it's stopped."""
        self.start_server()
        server_url = self.server.get_url()
        self.transport.has(".")
        self.stop_server()
        # if the listening socket has closed, we should get a BADFD error
        # when connecting, rather than a hang.
        t = remote.RemoteTCPTransport(server_url)
        self.assertRaises(errors.ConnectionError, t.has, ".")


class WritableEndToEndTests(SmartTCPTests):
    """Client to server tests that require a writable transport."""

    def setUp(self):
        super().setUp()
        self.start_server()

    def test_start_tcp_server(self):
        url = self.server.get_url()
        self.assertContainsRe(url, r"^bzr://127\.0\.0\.1:[0-9]{2,}/")

    def test_smart_transport_has(self):
        """Checking for file existence over smart."""
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        self.backing_transport.put_bytes("foo", b"contents of foo\n")
        self.assertTrue(self.transport.has("foo"))
        self.assertFalse(self.transport.has("non-foo"))

    def test_smart_transport_get(self):
        """Read back a file over smart."""
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        self.backing_transport.put_bytes("foo", b"contents\nof\nfoo\n")
        fp = self.transport.get("foo")
        self.assertEqual(b"contents\nof\nfoo\n", fp.read())

    def test_get_error_enoent(self):
        """Error reported from server getting nonexistent file."""
        # The path in a raised NoSuchFile exception should be the precise path
        # asked for by the client. This gives meaningful and unsurprising errors
        # for users.
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        err = self.assertRaises(
            _mod_transport.NoSuchFile, self.transport.get, "not%20a%20file"
        )
        self.assertSubset([err.path], ["not%20a%20file", "./not%20a%20file"])

    def test_simple_clone_conn(self):
        """Test that cloning reuses the same connection."""
        # we create a real connection not a loopback one, but it will use the
        # same server and pipes
        conn2 = self.transport.clone(".")
        self.assertIs(self.transport.get_smart_medium(), conn2.get_smart_medium())

    def test__remote_path(self):
        self.assertEqual(b"/foo/bar", self.transport._remote_path("foo/bar"))

    def test_clone_changes_base(self):
        """Cloning transport produces one with a new base location."""
        conn2 = self.transport.clone("subdir")
        self.assertEqual(self.transport.base + "subdir/", conn2.base)

    def test_open_dir(self):
        """Test changing directory."""
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        transport = self.transport
        self.backing_transport.mkdir("toffee")
        self.backing_transport.mkdir("toffee/apple")
        self.assertEqual(b"/toffee", transport._remote_path("toffee"))
        toffee_trans = transport.clone("toffee")
        # Check that each transport has only the contents of its directory
        # directly visible. If state was being held in the wrong object, it's
        # conceivable that cloning a transport would alter the state of the
        # cloned-from transport.
        self.assertTrue(transport.has("toffee"))
        self.assertFalse(toffee_trans.has("toffee"))
        self.assertFalse(transport.has("apple"))
        self.assertTrue(toffee_trans.has("apple"))

    def test_open_bzrdir(self):
        """Open an existing bzrdir over smart transport."""
        transport = self.transport
        t = self.backing_transport
        bzrdir.BzrDirFormat.get_default_format().initialize_on_transport(t)
        result_dir = controldir.ControlDir.open_containing_from_transport(transport)
        del result_dir


class ReadOnlyEndToEndTests(SmartTCPTests):
    """Tests from the client to the server using a readonly backing transport."""

    def test_mkdir_error_readonly(self):
        """TransportNotPossible should be preserved from the backing transport."""
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        self.start_server(readonly=True)
        self.assertRaises(errors.TransportNotPossible, self.transport.mkdir, "foo")

    def test_rename_error_readonly(self):
        """TransportNotPossible should be preserved from the backing transport."""
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        self.start_server(readonly=True)
        self.assertRaises(
            errors.TransportNotPossible, self.transport.rename, "foo", "bar"
        )

    def test_open_write_stream_error_readonly(self):
        """TransportNotPossible should be preserved from the backing transport."""
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        self.start_server(readonly=True)
        self.assertRaises(
            errors.TransportNotPossible, self.transport.open_write_stream, "foo"
        )


class TestServerHooks(SmartTCPTests):
    def capture_server_call(self, backing_urls, public_url):
        """Record a server_started|stopped hook firing."""
        self.hook_calls.append((backing_urls, public_url))

    def test_server_started_hook_memory(self):
        """The server_started hook fires when the server is started."""
        self.hook_calls = []
        _mod_server.SmartTCPServer.hooks.install_named_hook(
            "server_started", self.capture_server_call, None
        )
        self.start_server()
        # at this point, the server will be starting a thread up.
        # there is no indicator at the moment, so bodge it by doing a request.
        self.transport.has(".")
        # The default test server uses MemoryTransport and that has no external
        # url:
        self.assertEqual(
            [([self.backing_transport.base], self.transport.base)], self.hook_calls
        )

    def test_server_started_hook_file(self):
        """The server_started hook fires when the server is started."""
        self.hook_calls = []
        _mod_server.SmartTCPServer.hooks.install_named_hook(
            "server_started", self.capture_server_call, None
        )
        self.start_server(backing_transport=_mod_transport.get_transport_from_path("."))
        # at this point, the server will be starting a thread up.
        # there is no indicator at the moment, so bodge it by doing a request.
        self.transport.has(".")
        # The default test server uses MemoryTransport and that has no external
        # url:
        self.assertEqual(
            [
                (
                    [
                        self.backing_transport.base,
                        self.backing_transport.external_url(),
                    ],
                    self.transport.base,
                )
            ],
            self.hook_calls,
        )

    def test_server_stopped_hook_simple_memory(self):
        """The server_stopped hook fires when the server is stopped."""
        self.hook_calls = []
        _mod_server.SmartTCPServer.hooks.install_named_hook(
            "server_stopped", self.capture_server_call, None
        )
        self.start_server()
        result = [([self.backing_transport.base], self.transport.base)]
        # check the stopping message isn't emitted up front.
        self.assertEqual([], self.hook_calls)
        # nor after a single message
        self.transport.has(".")
        self.assertEqual([], self.hook_calls)
        # clean up the server
        self.stop_server()
        # now it should have fired.
        self.assertEqual(result, self.hook_calls)

    def test_server_stopped_hook_simple_file(self):
        """The server_stopped hook fires when the server is stopped."""
        self.hook_calls = []
        _mod_server.SmartTCPServer.hooks.install_named_hook(
            "server_stopped", self.capture_server_call, None
        )
        self.start_server(backing_transport=_mod_transport.get_transport_from_path("."))
        result = [
            (
                [self.backing_transport.base, self.backing_transport.external_url()],
                self.transport.base,
            )
        ]
        # check the stopping message isn't emitted up front.
        self.assertEqual([], self.hook_calls)
        # nor after a single message
        self.transport.has(".")
        self.assertEqual([], self.hook_calls)
        # clean up the server
        self.stop_server()
        # now it should have fired.
        self.assertEqual(result, self.hook_calls)


# TODO: test that when the server suffers an exception that it calls the
# server-stopped hook.


class SmartServerCommandTests(tests.TestCaseWithTransport):
    """Tests that call directly into the command objects, bypassing the network
    and the request dispatching.

    Note: these tests are rudimentary versions of the command object tests in
    test_smart.py.
    """

    def test_hello(self):
        cmd = _mod_request.HelloRequest(None, "/")
        response = cmd.execute()
        self.assertEqual((b"ok", b"2"), response.args)
        self.assertEqual(None, response.body)

    def test_get_bundle(self):
        from breezy.bzr.bundle import serializer

        wt = self.make_branch_and_tree(".")
        self.build_tree_contents([("hello", b"hello world")])
        wt.add("hello")
        rev_id = wt.commit("add hello")

        cmd = _mod_request.GetBundleRequest(self.get_transport(), "/")
        response = cmd.execute(b".", rev_id)
        bundle = serializer.read_bundle(BytesIO(response.body))
        self.assertEqual((), response.args)
        del bundle


class SmartServerRequestHandlerTests(tests.TestCaseWithTransport):
    """Test that call directly into the handler logic, bypassing the network."""

    def setUp(self):
        super().setUp()
        self.overrideEnv("BRZ_NO_SMART_VFS", None)

    def build_handler(self, transport):
        """Returns a handler for the commands in protocol version one."""
        return _mod_request.SmartServerRequestHandler(
            transport, _mod_request.request_handlers, "/"
        )

    def test_construct_request_handler(self):
        """Constructing a request handler should be easy and set defaults."""
        handler = _mod_request.SmartServerRequestHandler(
            None, commands=None, root_client_path="/"
        )
        self.assertFalse(handler.finished_reading)

    def test_hello(self):
        handler = self.build_handler(None)
        handler.args_received((b"hello",))
        self.assertEqual((b"ok", b"2"), handler.response.args)
        self.assertEqual(None, handler.response.body)

    def test_disable_vfs_handler_classes_via_environment(self):
        # VFS handler classes will raise an error from "execute" if
        # BRZ_NO_SMART_VFS is set.
        handler = vfs.HasRequest(None, "/")
        # set environment variable after construction to make sure it's
        # examined.
        self.overrideEnv("BRZ_NO_SMART_VFS", "")
        self.assertRaises(_mod_request.DisabledMethod, handler.execute)

    def test_readonly_exception_becomes_transport_not_possible(self):
        """The response for a read-only error is ('ReadOnlyError')."""
        handler = self.build_handler(self.get_readonly_transport())
        # send a mkdir for foo, with no explicit mode - should fail.
        handler.args_received((b"mkdir", b"foo", b""))
        # and the failure should be an explicit ReadOnlyError
        self.assertEqual((b"ReadOnlyError",), handler.response.args)
        # XXX: TODO: test that other TransportNotPossible errors are
        # presented as TransportNotPossible - not possible to do that
        # until I figure out how to trigger that relatively cleanly via
        # the api. RBC 20060918

    def test_hello_has_finished_body_on_dispatch(self):
        """The 'hello' command should set finished_reading."""
        handler = self.build_handler(None)
        handler.args_received((b"hello",))
        self.assertTrue(handler.finished_reading)
        self.assertNotEqual(None, handler.response)

    def test_put_bytes_non_atomic(self):
        """'put_...' should set finished_reading after reading the bytes."""
        handler = self.build_handler(self.get_transport())
        handler.args_received((b"put_non_atomic", b"a-file", b"", b"F", b""))
        self.assertFalse(handler.finished_reading)
        handler.accept_body(b"1234")
        self.assertFalse(handler.finished_reading)
        handler.accept_body(b"5678")
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual((b"ok",), handler.response.args)
        self.assertEqual(None, handler.response.body)

    def test_readv_accept_body(self):
        """'readv' should set finished_reading after reading offsets."""
        self.build_tree(["a-file"])
        handler = self.build_handler(self.get_readonly_transport())
        handler.args_received((b"readv", b"a-file"))
        self.assertFalse(handler.finished_reading)
        handler.accept_body(b"2,")
        self.assertFalse(handler.finished_reading)
        handler.accept_body(b"3")
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual((b"readv",), handler.response.args)
        # co - nte - nt of a-file is the file contents we are extracting from.
        self.assertEqual(b"nte", handler.response.body)

    def test_readv_short_read_response_contents(self):
        """'readv' when a short read occurs sets the response appropriately."""
        self.build_tree(["a-file"])
        handler = self.build_handler(self.get_readonly_transport())
        handler.args_received((b"readv", b"a-file"))
        # read beyond the end of the file.
        handler.accept_body(b"100,1")
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(
            (b"ShortReadvError", b"./a-file", b"100", b"1", b"0"), handler.response.args
        )
        self.assertEqual(None, handler.response.body)


class RemoteTransportRegistration(tests.TestCase):
    def test_registration(self):
        t = _mod_transport.get_transport_from_url("bzr+ssh://example.com/path")
        self.assertIsInstance(t, remote.RemoteSSHTransport)
        self.assertEqual("example.com", t._parsed_url.host)

    def test_bzr_https(self):
        # https://bugs.launchpad.net/bzr/+bug/128456
        t = _mod_transport.get_transport_from_url("bzr+https://example.com/path")
        self.assertIsInstance(t, remote.RemoteHTTPTransport)
        self.assertStartsWith(t._http_transport.base, "https://")


class TestRemoteTransport(tests.TestCase):
    def test_use_connection_factory(self):
        # We want to be able to pass a client as a parameter to RemoteTransport.
        input = BytesIO(b"ok\n3\nbardone\n")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        transport = remote.RemoteTransport("bzr://localhost/", medium=client_medium)
        # Disable version detection.
        client_medium._protocol_version = 1

        # We want to make sure the client is used when the first remote
        # method is called.  No data should have been sent, or read.
        self.assertEqual(0, input.tell())
        self.assertEqual(b"", output.getvalue())

        # Now call a method that should result in one request: as the
        # transport makes its own protocol instances, we check on the wire.
        # XXX: TODO: give the transport a protocol factory, which can make
        # an instrumented protocol for us.
        self.assertEqual(b"bar", transport.get_bytes("foo"))
        # only the needed data should have been sent/received.
        self.assertEqual(13, input.tell())
        self.assertEqual(b"get\x01/foo\n", output.getvalue())

    def test__translate_error_readonly(self):
        """Sending a ReadOnlyError to _translate_error raises TransportNotPossible."""
        client_medium = medium.SmartSimplePipesClientMedium(None, None, "base")
        transport = remote.RemoteTransport("bzr://localhost/", medium=client_medium)
        err = errors.ErrorFromSmartServer((b"ReadOnlyError",))
        self.assertRaises(errors.TransportNotPossible, transport._translate_error, err)


class TestSmartProtocol(tests.TestCase):
    """Base class for smart protocol tests.

    Each test case gets a smart_server and smart_client created during setUp().

    It is planned that the client can be called with self.call_client() giving
    it an expected server response, which will be fed into it when it tries to
    read. Likewise, self.call_server will call a servers method with a canned
    serialised client request. Output done by the client or server for these
    calls will be captured to self.to_server and self.to_client. Each element
    in the list is a write call from the client or server respectively.

    Subclasses can override client_protocol_class and server_protocol_class.
    """

    request_encoder: object
    response_decoder: type[protocol._StatefulDecoder]
    server_protocol_class: type[protocol.SmartProtocolBase]
    client_protocol_class: Optional[type[protocol.SmartProtocolBase]] = None

    def make_client_protocol_and_output(self, input_bytes=None):
        # This is very similar to
        # breezy.bzr.smart.client._SmartClient._build_client_protocol
        # XXX: make this use _SmartClient!
        if input_bytes is None:
            input = BytesIO()
        else:
            input = BytesIO(input_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        if self.client_protocol_class is not None:
            client_protocol = self.client_protocol_class(request)
            return client_protocol, client_protocol, output
        else:
            self.assertNotEqual(None, self.request_encoder)
            self.assertNotEqual(None, self.response_decoder)
            requester = self.request_encoder(request)
            response_handler = message.ConventionalResponseHandler()
            response_protocol = self.response_decoder(
                response_handler, expect_version_marker=True
            )
            response_handler.setProtoAndMediumRequest(response_protocol, request)
            return requester, response_handler, output

    def make_client_protocol(self, input_bytes=None):
        result = self.make_client_protocol_and_output(input_bytes=input_bytes)
        requester, response_handler, output = result
        return requester, response_handler

    def make_server_protocol(self):
        out_stream = BytesIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        return smart_protocol, out_stream

    def setUp(self):
        super().setUp()
        self.response_marker = getattr(
            self.client_protocol_class, "response_marker", None
        )
        self.request_marker = getattr(
            self.client_protocol_class, "request_marker", None
        )

    def assertOffsetSerialisation(
        self, expected_offsets, expected_serialised, requester
    ):
        """Check that smart (de)serialises offsets as expected.

        We check both serialisation and deserialisation at the same time
        to ensure that the round tripping cannot skew: both directions should
        be as expected.

        :param expected_offsets: a readv offset list.
        :param expected_seralised: an expected serial form of the offsets.
        """
        # XXX: '_deserialise_offsets' should be a method of the
        # SmartServerRequestProtocol in future.
        readv_cmd = vfs.ReadvRequest(None, "/")
        offsets = readv_cmd._deserialise_offsets(expected_serialised)
        self.assertEqual(expected_offsets, offsets)
        serialised = requester._serialise_offsets(offsets)
        self.assertEqual(expected_serialised, serialised)

    def build_protocol_waiting_for_body(self):
        smart_protocol, out_stream = self.make_server_protocol()
        smart_protocol._has_dispatched = True
        smart_protocol.request = _mod_request.SmartServerRequestHandler(
            None, _mod_request.request_handlers, "/"
        )
        # GZ 2010-08-10: Cycle with closure affects 4 tests

        class FakeCommand(_mod_request.SmartServerRequest):
            def do_body(self_cmd, body_bytes):  # noqa: N805
                self.end_received = True
                self.assertEqual(b"abcdefg", body_bytes)
                return _mod_request.SuccessfulSmartServerResponse((b"ok",))

        smart_protocol.request._command = FakeCommand(None)
        # Call accept_bytes to make sure that internal state like _body_decoder
        # is initialised.  This test should probably be given a clearer
        # interface to work with that will not cause this inconsistency.
        #   -- Andrew Bennetts, 2006-09-28
        smart_protocol.accept_bytes(b"")
        return smart_protocol

    def assertServerToClientEncoding(
        self, expected_bytes, expected_tuple, input_tuples
    ):
        """Assert that each input_tuple serialises as expected_bytes, and the
        bytes deserialise as expected_tuple.
        """
        # check the encoding of the server for all input_tuples matches
        # expected bytes
        for input_tuple in input_tuples:
            server_protocol, server_output = self.make_server_protocol()
            server_protocol._send_response(
                _mod_request.SuccessfulSmartServerResponse(input_tuple)
            )
            self.assertEqual(expected_bytes, server_output.getvalue())
        # check the decoding of the client smart_protocol from expected_bytes:
        requester, response_handler = self.make_client_protocol(expected_bytes)
        requester.call(b"foo")
        self.assertEqual(expected_tuple, response_handler.read_response_tuple())


class CommonSmartProtocolTestMixin:
    def test_connection_closed_reporting(self):
        requester, response_handler = self.make_client_protocol()
        requester.call(b"hello")
        ex = self.assertRaises(
            errors.ConnectionReset, response_handler.read_response_tuple
        )
        self.assertEqual(
            "Connection closed: "
            "Unexpected end of message. Please check connectivity "
            "and permissions, and report a bug if problems persist. ",
            str(ex),
        )

    def test_server_offset_serialisation(self):
        r"""The Smart protocol serialises offsets as a comma and \n string.

        We check a number of boundary cases are as expected: empty, one offset,
        one with the order of reads not increasing (an out of order read), and
        one that should coalesce.
        """
        requester, response_handler = self.make_client_protocol()
        self.assertOffsetSerialisation([], b"", requester)
        self.assertOffsetSerialisation([(1, 2)], b"1,2", requester)
        self.assertOffsetSerialisation([(10, 40), (0, 5)], b"10,40\n0,5", requester)
        self.assertOffsetSerialisation(
            [(1, 2), (3, 4), (100, 200)], b"1,2\n3,4\n100,200", requester
        )


class TestVersionOneFeaturesInProtocolOne(
    TestSmartProtocol, CommonSmartProtocolTestMixin
):
    """Tests for version one smart protocol features as implemeted by version
    one.
    """

    client_protocol_class = protocol.SmartClientRequestProtocolOne
    server_protocol_class = protocol.SmartServerRequestProtocolOne

    def test_construct_version_one_server_protocol(self):
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, None)
        self.assertEqual(b"", smart_protocol.unused_data)
        self.assertEqual(b"", smart_protocol.in_buffer)
        self.assertFalse(smart_protocol._has_dispatched)
        self.assertEqual(1, smart_protocol.next_read_size())

    def test_construct_version_one_client_protocol(self):
        # we can construct a client protocol from a client medium request
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        request = client_medium.get_request()
        client_protocol = protocol.SmartClientRequestProtocolOne(request)
        del client_protocol

    def test_accept_bytes_of_bad_request_to_protocol(self):
        out_stream = BytesIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, out_stream.write)
        smart_protocol.accept_bytes(b"abc")
        self.assertEqual(b"abc", smart_protocol.in_buffer)
        smart_protocol.accept_bytes(b"\n")
        self.assertEqual(
            b"error\x01Generic bzr smart protocol error: bad request 'abc'\n",
            out_stream.getvalue(),
        )
        self.assertTrue(smart_protocol._has_dispatched)
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_accept_body_bytes_to_protocol(self):
        protocol = self.build_protocol_waiting_for_body()
        self.assertEqual(6, protocol.next_read_size())
        protocol.accept_bytes(b"7\nabc")
        self.assertEqual(9, protocol.next_read_size())
        protocol.accept_bytes(b"defgd")
        protocol.accept_bytes(b"one\n")
        self.assertEqual(0, protocol.next_read_size())
        self.assertTrue(self.end_received)

    def test_accept_request_and_body_all_at_once(self):
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        mem_transport = memory.MemoryTransport()
        mem_transport.put_bytes("foo", b"abcdefghij")
        out_stream = BytesIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            mem_transport, out_stream.write
        )
        smart_protocol.accept_bytes(b"readv\x01foo\n3\n3,3done\n")
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual(b"readv\n3\ndefdone\n", out_stream.getvalue())
        self.assertEqual(b"", smart_protocol.unused_data)
        self.assertEqual(b"", smart_protocol.in_buffer)

    def test_accept_excess_bytes_are_preserved(self):
        out_stream = BytesIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, out_stream.write)
        smart_protocol.accept_bytes(b"hello\nhello\n")
        self.assertEqual(b"ok\x012\n", out_stream.getvalue())
        self.assertEqual(b"hello\n", smart_protocol.unused_data)
        self.assertEqual(b"", smart_protocol.in_buffer)

    def test_accept_excess_bytes_after_body(self):
        protocol = self.build_protocol_waiting_for_body()
        protocol.accept_bytes(b"7\nabcdefgdone\nX")
        self.assertTrue(self.end_received)
        self.assertEqual(b"X", protocol.unused_data)
        self.assertEqual(b"", protocol.in_buffer)
        protocol.accept_bytes(b"Y")
        self.assertEqual(b"XY", protocol.unused_data)
        self.assertEqual(b"", protocol.in_buffer)

    def test_accept_excess_bytes_after_dispatch(self):
        out_stream = BytesIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, out_stream.write)
        smart_protocol.accept_bytes(b"hello\n")
        self.assertEqual(b"ok\x012\n", out_stream.getvalue())
        smart_protocol.accept_bytes(b"hel")
        self.assertEqual(b"hel", smart_protocol.unused_data)
        smart_protocol.accept_bytes(b"lo\n")
        self.assertEqual(b"hello\n", smart_protocol.unused_data)
        self.assertEqual(b"", smart_protocol.in_buffer)

    def test__send_response_sets_finished_reading(self):
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            _mod_request.SuccessfulSmartServerResponse((b"x",))
        )
        self.assertEqual(0, smart_protocol.next_read_size())

    def test__send_response_errors_with_base_response(self):
        """Ensure that only the Successful/Failed subclasses are used."""
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, lambda x: None)
        self.assertRaises(
            AttributeError,
            smart_protocol._send_response,
            _mod_request.SmartServerResponse((b"x",)),
        )

    def test_query_version(self):
        """query_version on a SmartClientProtocolOne should return a number.

        The protocol provides the query_version because the domain level clients
        may all need to be able to probe for capabilities.
        """
        # What we really want to test here is that SmartClientProtocolOne calls
        # accept_bytes(tuple_based_encoding_of_hello) and reads and parses the
        # response of tuple-encoded (ok, 1).  Also, separately we should test
        # the error if the response is a non-understood version.
        input = BytesIO(b"ok\x012\n")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        self.assertEqual(2, smart_protocol.query_version())

    def test_client_call_empty_response(self):
        # protocol.call() can get back an empty tuple as a response. This occurs
        # when the parsed line is an empty line, and results in a tuple with
        # one element - an empty string.
        self.assertServerToClientEncoding(b"\n", (b"",), [(), (b"",)])

    def test_client_call_three_element_response(self):
        # protocol.call() can get back tuples of other lengths. A three element
        # tuple should be unpacked as three strings.
        self.assertServerToClientEncoding(
            b"a\x01b\x0134\n", (b"a", b"b", b"34"), [(b"a", b"b", b"34")]
        )

    def test_client_call_with_body_bytes_uploads(self):
        # protocol.call_with_body_bytes should length-prefix the bytes onto the
        # wire.
        expected_bytes = b"foo\n7\nabcdefgdone\n"
        input = BytesIO(b"\n")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_bytes((b"foo",), b"abcdefg")
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_call_with_body_readv_array(self):
        # protocol.call_with_upload should encode the readv array and then
        # length-prefix the bytes onto the wire.
        expected_bytes = b"foo\n7\n1,2\n5,6done\n"
        input = BytesIO(b"\n")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_readv_array((b"foo",), [(1, 2), (5, 6)])
        self.assertEqual(expected_bytes, output.getvalue())

    def _test_client_read_response_tuple_raises_UnknownSmartMethod(self, server_bytes):
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call(b"foo")
        self.assertRaises(errors.UnknownSmartMethod, smart_protocol.read_response_tuple)
        # The request has been finished.  There is no body to read, and
        # attempts to read one will fail.
        self.assertRaises(errors.ReadingCompleted, smart_protocol.read_body_bytes)

    def test_client_read_response_tuple_raises_UnknownSmartMethod(self):
        """read_response_tuple raises UnknownSmartMethod if the response says
        the server did not recognise the request.
        """
        server_bytes = b"error\x01Generic bzr smart protocol error: bad request 'foo'\n"
        self._test_client_read_response_tuple_raises_UnknownSmartMethod(server_bytes)

    def test_client_read_response_tuple_raises_UnknownSmartMethod_0_11(self):
        """read_response_tuple also raises UnknownSmartMethod if the response
        from a bzr 0.11 says the server did not recognise the request.

        (bzr 0.11 sends a slightly different error message to later versions.)
        """
        server_bytes = (
            b"error\x01Generic bzr smart protocol error: bad request u'foo'\n"
        )
        self._test_client_read_response_tuple_raises_UnknownSmartMethod(server_bytes)

    def test_client_read_body_bytes_all(self):
        # read_body_bytes should decode the body bytes from the wire into
        # a response.
        expected_bytes = b"1234567"
        server_bytes = b"ok\n7\n1234567done\n"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes, smart_protocol.read_body_bytes())

    def test_client_read_body_bytes_incremental(self):
        # test reading a few bytes at a time from the body
        # XXX: possibly we should test dribbling the bytes into the stringio
        # to make the state machine work harder: however, as we use the
        # LengthPrefixedBodyDecoder that is already well tested - we can skip
        # that.
        expected_bytes = b"1234567"
        server_bytes = b"ok\n7\n1234567done\n"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes[0:2], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[2:4], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[4:6], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[6:7], smart_protocol.read_body_bytes())

    def test_client_cancel_read_body_does_not_eat_body_bytes(self):
        # cancelling the expected body needs to finish the request, but not
        # read any more bytes.
        server_bytes = b"ok\n7\n1234567done\n"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        smart_protocol.cancel_read_body()
        self.assertEqual(3, input.tell())
        self.assertRaises(errors.ReadingCompleted, smart_protocol.read_body_bytes)

    def test_client_read_body_bytes_interrupted_connection(self):
        server_bytes = b"ok\n999\nincomplete body"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        self.assertRaises(errors.ConnectionReset, smart_protocol.read_body_bytes)


class TestVersionOneFeaturesInProtocolTwo(
    TestSmartProtocol, CommonSmartProtocolTestMixin
):
    """Tests for version one smart protocol features as implemeted by version
    two.
    """

    client_protocol_class = protocol.SmartClientRequestProtocolTwo
    server_protocol_class = protocol.SmartServerRequestProtocolTwo

    def test_construct_version_two_server_protocol(self):
        smart_protocol = protocol.SmartServerRequestProtocolTwo(None, None)
        self.assertEqual(b"", smart_protocol.unused_data)
        self.assertEqual(b"", smart_protocol.in_buffer)
        self.assertFalse(smart_protocol._has_dispatched)
        self.assertEqual(1, smart_protocol.next_read_size())

    def test_construct_version_two_client_protocol(self):
        # we can construct a client protocol from a client medium request
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output, "base")
        request = client_medium.get_request()
        client_protocol = protocol.SmartClientRequestProtocolTwo(request)
        del client_protocol

    def test_accept_bytes_of_bad_request_to_protocol(self):
        out_stream = BytesIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes(b"abc")
        self.assertEqual(b"abc", smart_protocol.in_buffer)
        smart_protocol.accept_bytes(b"\n")
        self.assertEqual(
            self.response_marker
            + b"failed\nerror\x01Generic bzr smart protocol error: bad request 'abc'\n",
            out_stream.getvalue(),
        )
        self.assertTrue(smart_protocol._has_dispatched)
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_accept_body_bytes_to_protocol(self):
        protocol = self.build_protocol_waiting_for_body()
        self.assertEqual(6, protocol.next_read_size())
        protocol.accept_bytes(b"7\nabc")
        self.assertEqual(9, protocol.next_read_size())
        protocol.accept_bytes(b"defgd")
        protocol.accept_bytes(b"one\n")
        self.assertEqual(0, protocol.next_read_size())
        self.assertTrue(self.end_received)

    def test_accept_request_and_body_all_at_once(self):
        self.overrideEnv("BRZ_NO_SMART_VFS", None)
        mem_transport = memory.MemoryTransport()
        mem_transport.put_bytes("foo", b"abcdefghij")
        out_stream = BytesIO()
        smart_protocol = self.server_protocol_class(mem_transport, out_stream.write)
        smart_protocol.accept_bytes(b"readv\x01foo\n3\n3,3done\n")
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual(
            self.response_marker + b"success\nreadv\n3\ndefdone\n",
            out_stream.getvalue(),
        )
        self.assertEqual(b"", smart_protocol.unused_data)
        self.assertEqual(b"", smart_protocol.in_buffer)

    def test_accept_excess_bytes_are_preserved(self):
        out_stream = BytesIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes(b"hello\nhello\n")
        self.assertEqual(
            self.response_marker + b"success\nok\x012\n", out_stream.getvalue()
        )
        self.assertEqual(b"hello\n", smart_protocol.unused_data)
        self.assertEqual(b"", smart_protocol.in_buffer)

    def test_accept_excess_bytes_after_body(self):
        # The excess bytes look like the start of another request.
        server_protocol = self.build_protocol_waiting_for_body()
        server_protocol.accept_bytes(b"7\nabcdefgdone\n" + self.response_marker)
        self.assertTrue(self.end_received)
        self.assertEqual(self.response_marker, server_protocol.unused_data)
        self.assertEqual(b"", server_protocol.in_buffer)
        server_protocol.accept_bytes(b"Y")
        self.assertEqual(self.response_marker + b"Y", server_protocol.unused_data)
        self.assertEqual(b"", server_protocol.in_buffer)

    def test_accept_excess_bytes_after_dispatch(self):
        out_stream = BytesIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes(b"hello\n")
        self.assertEqual(
            self.response_marker + b"success\nok\x012\n", out_stream.getvalue()
        )
        smart_protocol.accept_bytes(self.request_marker + b"hel")
        self.assertEqual(self.request_marker + b"hel", smart_protocol.unused_data)
        smart_protocol.accept_bytes(b"lo\n")
        self.assertEqual(self.request_marker + b"hello\n", smart_protocol.unused_data)
        self.assertEqual(b"", smart_protocol.in_buffer)

    def test__send_response_sets_finished_reading(self):
        smart_protocol = self.server_protocol_class(None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            _mod_request.SuccessfulSmartServerResponse((b"x",))
        )
        self.assertEqual(0, smart_protocol.next_read_size())

    def test__send_response_errors_with_base_response(self):
        """Ensure that only the Successful/Failed subclasses are used."""
        smart_protocol = self.server_protocol_class(None, lambda x: None)
        self.assertRaises(
            AttributeError,
            smart_protocol._send_response,
            _mod_request.SmartServerResponse((b"x",)),
        )

    def test_query_version(self):
        """query_version on a SmartClientProtocolTwo should return a number.

        The protocol provides the query_version because the domain level clients
        may all need to be able to probe for capabilities.
        """
        # What we really want to test here is that SmartClientProtocolTwo calls
        # accept_bytes(tuple_based_encoding_of_hello) and reads and parses the
        # response of tuple-encoded (ok, 1).  Also, separately we should test
        # the error if the response is a non-understood version.
        input = BytesIO(self.response_marker + b"success\nok\x012\n")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        self.assertEqual(2, smart_protocol.query_version())

    def test_client_call_empty_response(self):
        # protocol.call() can get back an empty tuple as a response. This occurs
        # when the parsed line is an empty line, and results in a tuple with
        # one element - an empty string.
        self.assertServerToClientEncoding(
            self.response_marker + b"success\n\n", (b"",), [(), (b"",)]
        )

    def test_client_call_three_element_response(self):
        # protocol.call() can get back tuples of other lengths. A three element
        # tuple should be unpacked as three strings.
        self.assertServerToClientEncoding(
            self.response_marker + b"success\na\x01b\x0134\n",
            (b"a", b"b", b"34"),
            [(b"a", b"b", b"34")],
        )

    def test_client_call_with_body_bytes_uploads(self):
        # protocol.call_with_body_bytes should length-prefix the bytes onto the
        # wire.
        expected_bytes = self.request_marker + b"foo\n7\nabcdefgdone\n"
        input = BytesIO(b"\n")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call_with_body_bytes((b"foo",), b"abcdefg")
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_call_with_body_readv_array(self):
        # protocol.call_with_upload should encode the readv array and then
        # length-prefix the bytes onto the wire.
        expected_bytes = self.request_marker + b"foo\n7\n1,2\n5,6done\n"
        input = BytesIO(b"\n")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call_with_body_readv_array((b"foo",), [(1, 2), (5, 6)])
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_read_body_bytes_all(self):
        # read_body_bytes should decode the body bytes from the wire into
        # a response.
        expected_bytes = b"1234567"
        server_bytes = self.response_marker + b"success\nok\n7\n1234567done\n"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes, smart_protocol.read_body_bytes())

    def test_client_read_body_bytes_incremental(self):
        # test reading a few bytes at a time from the body
        # XXX: possibly we should test dribbling the bytes into the stringio
        # to make the state machine work harder: however, as we use the
        # LengthPrefixedBodyDecoder that is already well tested - we can skip
        # that.
        expected_bytes = b"1234567"
        server_bytes = self.response_marker + b"success\nok\n7\n1234567done\n"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes[0:2], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[2:4], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[4:6], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[6:7], smart_protocol.read_body_bytes())

    def test_client_cancel_read_body_does_not_eat_body_bytes(self):
        # cancelling the expected body needs to finish the request, but not
        # read any more bytes.
        server_bytes = self.response_marker + b"success\nok\n7\n1234567done\n"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        smart_protocol.cancel_read_body()
        self.assertEqual(len(self.response_marker + b"success\nok\n"), input.tell())
        self.assertRaises(errors.ReadingCompleted, smart_protocol.read_body_bytes)

    def test_client_read_body_bytes_interrupted_connection(self):
        server_bytes = self.response_marker + b"success\nok\n999\nincomplete body"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        self.assertRaises(errors.ConnectionReset, smart_protocol.read_body_bytes)


class TestSmartProtocolTwoSpecificsMixin:
    def assertBodyStreamSerialisation(self, expected_serialisation, body_stream):
        """Assert that body_stream is serialised as expected_serialisation."""
        out_stream = BytesIO()
        protocol._send_stream(body_stream, out_stream.write)
        self.assertEqual(expected_serialisation, out_stream.getvalue())

    def assertBodyStreamRoundTrips(self, body_stream):
        """Assert that body_stream is the same after being serialised and
        deserialised.
        """
        out_stream = BytesIO()
        protocol._send_stream(body_stream, out_stream.write)
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(out_stream.getvalue())
        decoded_stream = list(iter(decoder.read_next_chunk, None))
        self.assertEqual(body_stream, decoded_stream)

    def test_body_stream_serialisation_empty(self):
        """A body_stream with no bytes can be serialised."""
        self.assertBodyStreamSerialisation(b"chunked\nEND\n", [])
        self.assertBodyStreamRoundTrips([])

    def test_body_stream_serialisation(self):
        stream = [b"chunk one", b"chunk two", b"chunk three"]
        self.assertBodyStreamSerialisation(
            b"chunked\n"
            + b"9\nchunk one"
            + b"9\nchunk two"
            + b"b\nchunk three"
            + b"END\n",
            stream,
        )
        self.assertBodyStreamRoundTrips(stream)

    def test_body_stream_with_empty_element_serialisation(self):
        """A body stream can include ''.

        The empty string can be transmitted like any other string.
        """
        stream = [b"", b"chunk"]
        self.assertBodyStreamSerialisation(
            b"chunked\n" + b"0\n" + b"5\nchunk" + b"END\n", stream
        )
        self.assertBodyStreamRoundTrips(stream)

    def test_body_stream_error_serialistion(self):
        stream = [
            b"first chunk",
            _mod_request.FailedSmartServerResponse((b"FailureName", b"failure arg")),
        ]
        expected_bytes = (
            b"chunked\n"
            + b"b\nfirst chunk"
            + b"ERR\n"
            + b"b\nFailureName"
            + b"b\nfailure arg"
            + b"END\n"
        )
        self.assertBodyStreamSerialisation(expected_bytes, stream)
        self.assertBodyStreamRoundTrips(stream)

    def test__send_response_includes_failure_marker(self):
        r"""FailedSmartServerResponse have 'failed\n' after the version."""
        out_stream = BytesIO()
        smart_protocol = protocol.SmartServerRequestProtocolTwo(None, out_stream.write)
        smart_protocol._send_response(_mod_request.FailedSmartServerResponse((b"x",)))
        self.assertEqual(
            protocol.RESPONSE_VERSION_TWO + b"failed\nx\n", out_stream.getvalue()
        )

    def test__send_response_includes_success_marker(self):
        r"""SuccessfulSmartServerResponse have 'success\n' after the version."""
        out_stream = BytesIO()
        smart_protocol = protocol.SmartServerRequestProtocolTwo(None, out_stream.write)
        smart_protocol._send_response(
            _mod_request.SuccessfulSmartServerResponse((b"x",))
        )
        self.assertEqual(
            protocol.RESPONSE_VERSION_TWO + b"success\nx\n", out_stream.getvalue()
        )

    def test__send_response_with_body_stream_sets_finished_reading(self):
        smart_protocol = protocol.SmartServerRequestProtocolTwo(None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            _mod_request.SuccessfulSmartServerResponse((b"x",), body_stream=[])
        )
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_streamed_body_bytes(self):
        body_header = b"chunked\n"
        two_body_chunks = b"4\n1234" + b"3\n567"
        body_terminator = b"END\n"
        server_bytes = (
            protocol.RESPONSE_VERSION_TWO
            + b"success\nok\n"
            + body_header
            + two_body_chunks
            + body_terminator
        )
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        stream = smart_protocol.read_streamed_body()
        self.assertEqual([b"1234", b"567"], list(stream))

    def test_read_streamed_body_error(self):
        """When a stream is interrupted by an error..."""
        body_header = b"chunked\n"
        a_body_chunk = b"4\naaaa"
        err_signal = b"ERR\n"
        err_chunks = b"a\nerror arg1" + b"4\narg2"
        finish = b"END\n"
        body = body_header + a_body_chunk + err_signal + err_chunks + finish
        server_bytes = protocol.RESPONSE_VERSION_TWO + b"success\nok\n" + body
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        smart_request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(smart_request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        expected_chunks = [
            b"aaaa",
            _mod_request.FailedSmartServerResponse((b"error arg1", b"arg2")),
        ]
        stream = smart_protocol.read_streamed_body()
        self.assertEqual(expected_chunks, list(stream))

    def test_streamed_body_bytes_interrupted_connection(self):
        body_header = b"chunked\n"
        incomplete_body_chunk = b"9999\nincomplete chunk"
        server_bytes = (
            protocol.RESPONSE_VERSION_TWO
            + b"success\nok\n"
            + body_header
            + incomplete_body_chunk
        )
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(True)
        stream = smart_protocol.read_streamed_body()
        self.assertRaises(errors.ConnectionReset, next, stream)

    def test_client_read_response_tuple_sets_response_status(self):
        server_bytes = protocol.RESPONSE_VERSION_TWO + b"success\nok\n"
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call(b"foo")
        smart_protocol.read_response_tuple(False)
        self.assertEqual(True, smart_protocol.response_status)

    def test_client_read_response_tuple_raises_UnknownSmartMethod(self):
        """read_response_tuple raises UnknownSmartMethod if the response says
        the server did not recognise the request.
        """
        server_bytes = (
            protocol.RESPONSE_VERSION_TWO
            + b"failed\n"
            + b"error\x01Generic bzr smart protocol error: bad request 'foo'\n"
        )
        input = BytesIO(server_bytes)
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output, "base")
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call(b"foo")
        self.assertRaises(errors.UnknownSmartMethod, smart_protocol.read_response_tuple)
        # The request has been finished.  There is no body to read, and
        # attempts to read one will fail.
        self.assertRaises(errors.ReadingCompleted, smart_protocol.read_body_bytes)


class TestSmartProtocolTwoSpecifics(
    TestSmartProtocol, TestSmartProtocolTwoSpecificsMixin
):
    """Tests for aspects of smart protocol version two that are unique to
    version two.

    Thus tests involving body streams and success/failure markers belong here.
    """

    client_protocol_class = protocol.SmartClientRequestProtocolTwo
    server_protocol_class = protocol.SmartServerRequestProtocolTwo


class TestVersionOneFeaturesInProtocolThree(
    TestSmartProtocol, CommonSmartProtocolTestMixin
):
    """Tests for version one smart protocol features as implemented by version
    three.
    """

    request_encoder = protocol.ProtocolThreeRequester
    response_decoder = protocol.ProtocolThreeDecoder
    # build_server_protocol_three is a function, so we can't set it as a class
    # attribute directly, because then Python will assume it is actually a
    # method.  So we make server_protocol_class be a static method, rather than
    # simply doing:
    # "server_protocol_class = protocol.build_server_protocol_three".
    server_protocol_class = staticmethod(protocol.build_server_protocol_three)  # type: ignore

    def setUp(self):
        super().setUp()
        self.response_marker = protocol.MESSAGE_VERSION_THREE
        self.request_marker = protocol.MESSAGE_VERSION_THREE

    def test_construct_version_three_server_protocol(self):
        smart_protocol = protocol.ProtocolThreeDecoder(None)
        self.assertEqual(b"", smart_protocol.unused_data)
        self.assertEqual([], smart_protocol._in_buffer_list)
        self.assertEqual(0, smart_protocol._in_buffer_len)
        self.assertFalse(smart_protocol._has_dispatched)
        # The protocol starts by expecting four bytes, a length prefix for the
        # headers.
        self.assertEqual(4, smart_protocol.next_read_size())


class LoggingMessageHandler:
    def __init__(self):
        self.event_log = []

    def _log(self, *args):
        self.event_log.append(args)

    def headers_received(self, headers):
        self._log("headers", headers)

    def protocol_error(self, exception):
        self._log("protocol_error", exception)

    def byte_part_received(self, byte):
        self._log("byte", byte)

    def bytes_part_received(self, bytes):
        self._log("bytes", bytes)

    def structure_part_received(self, structure):
        self._log("structure", structure)

    def end_received(self):
        self._log("end")


class TestProtocolThree(TestSmartProtocol):
    """Tests for v3 of the server-side protocol."""

    request_encoder = protocol.ProtocolThreeRequester
    response_decoder = protocol.ProtocolThreeDecoder
    server_protocol_class = protocol.ProtocolThreeDecoder  # type: ignore

    def test_trivial_request(self):
        """Smoke test for the simplest possible v3 request: empty headers, no
        message parts.
        """
        headers = b"\0\0\0\x02de"  # length-prefixed, bencoded empty dict
        end = b"e"
        request_bytes = headers + end
        smart_protocol = self.server_protocol_class(LoggingMessageHandler())
        smart_protocol.accept_bytes(request_bytes)
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual(b"", smart_protocol.unused_data)

    def test_repeated_excess(self):
        """Repeated calls to accept_bytes after the message end has been parsed
        accumlates the bytes in the unused_data attribute.
        """
        headers = b"\0\0\0\x02de"  # length-prefixed, bencoded empty dict
        end = b"e"
        request_bytes = headers + end
        smart_protocol = self.server_protocol_class(LoggingMessageHandler())
        smart_protocol.accept_bytes(request_bytes)
        self.assertEqual(b"", smart_protocol.unused_data)
        smart_protocol.accept_bytes(b"aaa")
        self.assertEqual(b"aaa", smart_protocol.unused_data)
        smart_protocol.accept_bytes(b"bbb")
        self.assertEqual(b"aaabbb", smart_protocol.unused_data)
        self.assertEqual(0, smart_protocol.next_read_size())

    def make_protocol_expecting_message_part(self):
        headers = b"\0\0\0\x02de"  # length-prefixed, bencoded empty dict
        message_handler = LoggingMessageHandler()
        smart_protocol = self.server_protocol_class(message_handler)
        smart_protocol.accept_bytes(headers)
        # Clear the event log
        del message_handler.event_log[:]
        return smart_protocol, message_handler.event_log

    def test_decode_one_byte(self):
        """The protocol can decode a 'one byte' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(b"ox")
        self.assertEqual([("byte", b"x")], event_log)

    def test_decode_bytes(self):
        """The protocol can decode a 'bytes' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            b"b"  # message part kind
            b"\0\0\0\x07"  # length prefix
            b"payload"  # payload
        )
        self.assertEqual([("bytes", b"payload")], event_log)

    def test_decode_structure(self):
        """The protocol can decode a 'structure' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            b"s"  # message part kind
            b"\0\0\0\x07"  # length prefix
            b"l3:ARGe"  # ['ARG']
        )
        self.assertEqual([("structure", (b"ARG",))], event_log)

    def test_decode_multiple_bytes(self):
        """The protocol can decode a multiple 'bytes' message parts."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            b"b"  # message part kind
            b"\0\0\0\x05"  # length prefix
            b"first"  # payload
            b"b"  # message part kind
            b"\0\0\0\x06"
            b"second"
        )
        self.assertEqual([("bytes", b"first"), ("bytes", b"second")], event_log)


class TestConventionalResponseHandlerBodyStream(tests.TestCase):
    def make_response_handler(self, response_bytes):
        from breezy.bzr.smart.message import ConventionalResponseHandler

        response_handler = ConventionalResponseHandler()
        protocol_decoder = protocol.ProtocolThreeDecoder(response_handler)
        # put decoder in desired state (waiting for message parts)
        protocol_decoder.state_accept = (
            protocol_decoder._state_accept_expecting_message_part
        )
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            BytesIO(response_bytes), output, "base"
        )
        medium_request = client_medium.get_request()
        medium_request.finished_writing()
        response_handler.setProtoAndMediumRequest(protocol_decoder, medium_request)
        return response_handler

    def test_interrupted_by_error(self):
        response_handler = self.make_response_handler(interrupted_body_stream)
        stream = response_handler.read_streamed_body()
        self.assertEqual(b"aaa", next(stream))
        self.assertEqual(b"bbb", next(stream))
        exc = self.assertRaises(errors.ErrorFromSmartServer, next, stream)
        self.assertEqual((b"error", b"Exception", b"Boom!"), exc.error_tuple)

    def test_interrupted_by_connection_lost(self):
        interrupted_body_stream = (
            b"oS"  # successful response
            b"s\0\0\0\x02le"  # empty args
            b"b\0\0\xff\xffincomplete chunk"
        )
        response_handler = self.make_response_handler(interrupted_body_stream)
        stream = response_handler.read_streamed_body()
        self.assertRaises(errors.ConnectionReset, next, stream)

    def test_read_body_bytes_interrupted_by_connection_lost(self):
        interrupted_body_stream = (
            b"oS"  # successful response
            b"s\0\0\0\x02le"  # empty args
            b"b\0\0\xff\xffincomplete chunk"
        )
        response_handler = self.make_response_handler(interrupted_body_stream)
        self.assertRaises(errors.ConnectionReset, response_handler.read_body_bytes)

    def test_multiple_bytes_parts(self):
        multiple_bytes_parts = (
            b"oS"  # successful response
            b"s\0\0\0\x02le"  # empty args
            b"b\0\0\0\x0bSome bytes\n"  # some bytes
            b"b\0\0\0\x0aMore bytes"  # more bytes
            b"e"  # message end
        )
        response_handler = self.make_response_handler(multiple_bytes_parts)
        self.assertEqual(b"Some bytes\nMore bytes", response_handler.read_body_bytes())
        response_handler = self.make_response_handler(multiple_bytes_parts)
        self.assertEqual(
            [b"Some bytes\n", b"More bytes"],
            list(response_handler.read_streamed_body()),
        )


class FakeResponder:
    response_sent = False

    def send_error(self, exc):
        raise exc

    def send_response(self, response):
        pass


class TestConventionalRequestHandlerBodyStream(tests.TestCase):
    """Tests for ConventionalRequestHandler's handling of request bodies."""

    def make_request_handler(self, request_bytes):
        """Make a ConventionalRequestHandler for the given bytes using test
        doubles for the request_handler and the responder.
        """
        from breezy.bzr.smart.message import ConventionalRequestHandler

        request_handler = InstrumentedRequestHandler()
        request_handler.response = _mod_request.SuccessfulSmartServerResponse(
            (b"arg", b"arg")
        )
        responder = FakeResponder()
        message_handler = ConventionalRequestHandler(request_handler, responder)
        protocol_decoder = protocol.ProtocolThreeDecoder(message_handler)
        # put decoder in desired state (waiting for message parts)
        protocol_decoder.state_accept = (
            protocol_decoder._state_accept_expecting_message_part
        )
        protocol_decoder.accept_bytes(request_bytes)
        return request_handler

    def test_multiple_bytes_parts(self):
        """Each bytes part triggers a call to the request_handler's
        accept_body method.
        """
        multiple_bytes_parts = (
            b"s\0\0\0\x07l3:fooe"  # args
            b"b\0\0\0\x0bSome bytes\n"  # some bytes
            b"b\0\0\0\x0aMore bytes"  # more bytes
            b"e"  # message end
        )
        request_handler = self.make_request_handler(multiple_bytes_parts)
        accept_body_calls = [
            call_info[1]
            for call_info in request_handler.calls
            if call_info[0] == "accept_body"
        ]
        self.assertEqual([b"Some bytes\n", b"More bytes"], accept_body_calls)

    def test_error_flag_after_body(self):
        body_then_error = (
            b"s\0\0\0\x07l3:fooe"  # request args
            b"b\0\0\0\x0bSome bytes\n"  # some bytes
            b"b\0\0\0\x0aMore bytes"  # more bytes
            b"oE"  # error flag
            b"s\0\0\0\x07l3:bare"  # error args
            b"e"  # message end
        )
        request_handler = self.make_request_handler(body_then_error)
        self.assertEqual(
            [("post_body_error_received", (b"bar",)), ("end_received",)],
            request_handler.calls[-2:],
        )


class TestMessageHandlerErrors(tests.TestCase):
    """Tests for v3 that unrecognised (but well-formed) requests/responses are
    still fully read off the wire, so that subsequent requests/responses on the
    same medium can be decoded.
    """

    def test_non_conventional_request(self):
        """ConventionalRequestHandler (the default message handler on the
        server side) will reject an unconventional message, but still consume
        all the bytes of that message and signal when it has done so.

        This is what allows a server to continue to accept requests after the
        client sends a completely unrecognised request.
        """
        # Define an invalid request (but one that is a well-formed message).
        # This particular invalid request not only lacks the mandatory
        # verb+args tuple, it has a single-byte part, which is forbidden.  In
        # fact it has that part twice, to trigger multiple errors.
        invalid_request = (
            protocol.MESSAGE_VERSION_THREE  # protocol version marker
            + b"\0\0\0\x02de"  # empty headers
            + b"oX"  # a single byte part: 'X'.  ConventionalRequestHandler will
            +
            # error at this part.
            b"oX"  # and again.
            + b"e"  # end of message
        )

        to_server = BytesIO(invalid_request)
        from_server = BytesIO()
        transport = memory.MemoryTransport("memory:///")
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport, timeout=4.0
        )
        proto = server._build_protocol()
        server._serve_one_request(proto)
        # All the bytes have been read from the medium...
        self.assertEqual(b"", to_server.read())
        # ...and the protocol decoder has consumed all the bytes, and has
        # finished reading.
        self.assertEqual(b"", proto.unused_data)
        self.assertEqual(0, proto.next_read_size())


class InstrumentedRequestHandler:
    """Test Double of SmartServerRequestHandler."""

    def __init__(self):
        self.calls = []
        self.finished_reading = False

    def no_body_received(self):
        self.calls.append(("no_body_received",))

    def end_received(self):
        self.calls.append(("end_received",))
        self.finished_reading = True

    def args_received(self, args):
        self.calls.append(("args_received", args))

    def accept_body(self, bytes):
        self.calls.append(("accept_body", bytes))

    def end_of_body(self):
        self.calls.append(("end_of_body",))
        self.finished_reading = True

    def post_body_error_received(self, error_args):
        self.calls.append(("post_body_error_received", error_args))


class StubRequest:
    def finished_reading(self):
        pass


class TestClientDecodingProtocolThree(TestSmartProtocol):
    """Tests for v3 of the client-side protocol decoding."""

    def make_logging_response_decoder(self):
        """Make v3 response decoder using a test response handler."""
        response_handler = LoggingMessageHandler()
        decoder = protocol.ProtocolThreeDecoder(response_handler)
        return decoder, response_handler

    def make_conventional_response_decoder(self):
        """Make v3 response decoder using a conventional response handler."""
        response_handler = message.ConventionalResponseHandler()
        decoder = protocol.ProtocolThreeDecoder(response_handler)
        response_handler.setProtoAndMediumRequest(decoder, StubRequest())
        return decoder, response_handler

    def test_trivial_response_decoding(self):
        """Smoke test for the simplest possible v3 response: empty headers,
        status byte, empty args, no body.
        """
        headers = b"\0\0\0\x02de"  # length-prefixed, bencoded empty dict
        response_status = b"oS"  # success
        args = b"s\0\0\0\x02le"  # length-prefixed, bencoded empty list
        end = b"e"  # end marker
        message_bytes = headers + response_status + args + end
        decoder, response_handler = self.make_logging_response_decoder()
        decoder.accept_bytes(message_bytes)
        # The protocol decoder has finished, and consumed all bytes
        self.assertEqual(0, decoder.next_read_size())
        self.assertEqual(b"", decoder.unused_data)
        # The message handler has been invoked with all the parts of the
        # trivial response: empty headers, status byte, no args, end.
        self.assertEqual(
            [("headers", {}), ("byte", b"S"), ("structure", ()), ("end",)],
            response_handler.event_log,
        )

    def test_incomplete_message(self):
        """A decoder will keep signalling that it needs more bytes via
        next_read_size() != 0 until it has seen a complete message, regardless
        which state it is in.
        """
        # Define a simple response that uses all possible message parts.
        headers = b"\0\0\0\x02de"  # length-prefixed, bencoded empty dict
        response_status = b"oS"  # success
        args = b"s\0\0\0\x02le"  # length-prefixed, bencoded empty list
        body = b"b\0\0\0\x04BODY"  # a body: 'BODY'
        end = b"e"  # end marker
        simple_response = headers + response_status + args + body + end
        # Feed the request to the decoder one byte at a time.
        decoder, response_handler = self.make_logging_response_decoder()
        for byte in bytearray(simple_response):
            self.assertNotEqual(0, decoder.next_read_size())
            decoder.accept_bytes(bytes([byte]))
        # Now the response is complete
        self.assertEqual(0, decoder.next_read_size())

    def test_read_response_tuple_raises_UnknownSmartMethod(self):
        """read_response_tuple raises UnknownSmartMethod if the server replied
        with 'UnknownMethod'.
        """
        headers = b"\0\0\0\x02de"  # length-prefixed, bencoded empty dict
        response_status = b"oE"  # error flag
        # args: (b'UnknownMethod', 'method-name')
        args = b"s\0\0\0\x20l13:UnknownMethod11:method-namee"
        end = b"e"  # end marker
        message_bytes = headers + response_status + args + end
        decoder, response_handler = self.make_conventional_response_decoder()
        decoder.accept_bytes(message_bytes)
        error = self.assertRaises(
            errors.UnknownSmartMethod, response_handler.read_response_tuple
        )
        self.assertEqual(b"method-name", error.verb)

    def test_read_response_tuple_error(self):
        """If the response has an error, it is raised as an exception."""
        headers = b"\0\0\0\x02de"  # length-prefixed, bencoded empty dict
        response_status = b"oE"  # error
        args = b"s\0\0\0\x1al9:first arg10:second arge"  # two args
        end = b"e"  # end marker
        message_bytes = headers + response_status + args + end
        decoder, response_handler = self.make_conventional_response_decoder()
        decoder.accept_bytes(message_bytes)
        error = self.assertRaises(
            errors.ErrorFromSmartServer, response_handler.read_response_tuple
        )
        self.assertEqual((b"first arg", b"second arg"), error.error_tuple)


class TestClientEncodingProtocolThree(TestSmartProtocol):
    request_encoder = protocol.ProtocolThreeRequester
    response_decoder = protocol.ProtocolThreeDecoder
    server_protocol_class = protocol.ProtocolThreeDecoder  # type: ignore

    def make_client_encoder_and_output(self):
        result = self.make_client_protocol_and_output()
        requester, response_handler, output = result
        return requester, output

    def test_call_smoke_test(self):
        """A smoke test for ProtocolThreeRequester.call.

        This test checks that a particular simple invocation of call emits the
        correct bytes for that invocation.
        """
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({b"header name": b"header value"})
        requester.call(b"one arg")
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol version
            b"\x00\x00\x00\x1fd11:header name12:header valuee"  # headers
            b"s\x00\x00\x00\x0bl7:one arge"  # args
            b"e",  # end
            output.getvalue(),
        )

    def test_call_with_body_bytes_smoke_test(self):
        """A smoke test for ProtocolThreeRequester.call_with_body_bytes.

        This test checks that a particular simple invocation of
        call_with_body_bytes emits the correct bytes for that invocation.
        """
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({b"header name": b"header value"})
        requester.call_with_body_bytes((b"one arg",), b"body bytes")
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol version
            b"\x00\x00\x00\x1fd11:header name12:header valuee"  # headers
            b"s\x00\x00\x00\x0bl7:one arge"  # args
            b"b"  # there is a prefixed body
            b"\x00\x00\x00\nbody bytes"  # the prefixed body
            b"e",  # end
            output.getvalue(),
        )

    def test_call_writes_just_once(self):
        """A bodyless request is written to the medium all at once."""
        medium_request = StubMediumRequest()
        encoder = protocol.ProtocolThreeRequester(medium_request)
        encoder.call(b"arg1", b"arg2", b"arg3")
        self.assertEqual(["accept_bytes", "finished_writing"], medium_request.calls)

    def test_call_with_body_bytes_writes_just_once(self):
        """A request with body bytes is written to the medium all at once."""
        medium_request = StubMediumRequest()
        encoder = protocol.ProtocolThreeRequester(medium_request)
        encoder.call_with_body_bytes((b"arg", b"arg"), b"body bytes")
        self.assertEqual(["accept_bytes", "finished_writing"], medium_request.calls)

    def test_call_with_body_stream_smoke_test(self):
        """A smoke test for ProtocolThreeRequester.call_with_body_stream.

        This test checks that a particular simple invocation of
        call_with_body_stream emits the correct bytes for that invocation.
        """
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({b"header name": b"header value"})
        stream = [b"chunk 1", b"chunk two"]
        requester.call_with_body_stream((b"one arg",), stream)
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol version
            b"\x00\x00\x00\x1fd11:header name12:header valuee"  # headers
            b"s\x00\x00\x00\x0bl7:one arge"  # args
            b"b\x00\x00\x00\x07chunk 1"  # a prefixed body chunk
            b"b\x00\x00\x00\x09chunk two"  # a prefixed body chunk
            b"e",  # end
            output.getvalue(),
        )

    def test_call_with_body_stream_empty_stream(self):
        """call_with_body_stream with an empty stream."""
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({})
        stream = []
        requester.call_with_body_stream((b"one arg",), stream)
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol version
            b"\x00\x00\x00\x02de"  # headers
            b"s\x00\x00\x00\x0bl7:one arge"  # args
            # no body chunks
            b"e",  # end
            output.getvalue(),
        )

    def test_call_with_body_stream_error(self):
        """call_with_body_stream will abort the streamed body with an
        error if the stream raises an error during iteration.

        The resulting request will still be a complete message.
        """
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({})

        def stream_that_fails():
            yield b"aaa"
            yield b"bbb"
            raise Exception("Boom!")

        self.assertRaises(
            Exception,
            requester.call_with_body_stream,
            (b"one arg",),
            stream_that_fails(),
        )
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol version
            b"\x00\x00\x00\x02de"  # headers
            b"s\x00\x00\x00\x0bl7:one arge"  # args
            b"b\x00\x00\x00\x03aaa"  # body
            b"b\x00\x00\x00\x03bbb"  # more body
            b"oE"  # error flag
            b"s\x00\x00\x00\x09l5:errore"  # error args: ('error',)
            b"e",  # end
            output.getvalue(),
        )

    def test_records_start_of_body_stream(self):
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({})
        in_stream = [False]

        def stream_checker():
            self.assertTrue(requester.body_stream_started)
            in_stream[0] = True
            yield b"content"

        flush_called = []
        orig_flush = requester.flush

        def tracked_flush():
            flush_called.append(in_stream[0])
            if in_stream[0]:
                self.assertTrue(requester.body_stream_started)
            else:
                self.assertFalse(requester.body_stream_started)
            return orig_flush()

        requester.flush = tracked_flush
        requester.call_with_body_stream((b"one arg",), stream_checker())
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol version
            b"\x00\x00\x00\x02de"  # headers
            b"s\x00\x00\x00\x0bl7:one arge"  # args
            b"b\x00\x00\x00\x07content"  # body
            b"e",
            output.getvalue(),
        )
        self.assertEqual([False, True, True], flush_called)


class StubMediumRequest:
    """A stub medium request that tracks the number of times accept_bytes is
    called.
    """

    def __init__(self):
        self.calls = []
        self._medium = "dummy medium"

    def accept_bytes(self, bytes):
        self.calls.append("accept_bytes")

    def finished_writing(self):
        self.calls.append("finished_writing")


interrupted_body_stream = (
    b"oS"  # status flag (success)
    b"s\x00\x00\x00\x08l4:argse"  # args struct ('args,')
    b"b\x00\x00\x00\x03aaa"  # body part ('aaa')
    b"b\x00\x00\x00\x03bbb"  # body part ('bbb')
    b"oE"  # status flag (error)
    # err struct ('error', 'Exception', 'Boom!')
    b"s\x00\x00\x00\x1bl5:error9:Exception5:Boom!e"
    b"e"  # EOM
)


class TestResponseEncodingProtocolThree(tests.TestCase):
    def make_response_encoder(self):
        out_stream = BytesIO()
        response_encoder = protocol.ProtocolThreeResponder(out_stream.write)
        return response_encoder, out_stream

    def test_send_error_unknown_method(self):
        encoder, out_stream = self.make_response_encoder()
        encoder.send_error(errors.UnknownSmartMethod("method name"))
        # Use assertEndsWith so that we don't compare the header, which varies
        # by breezy.__version__.
        self.assertEndsWith(
            out_stream.getvalue(),
            # error status
            b"oE" +
            # tuple: 'UnknownMethod', 'method name'
            b"s\x00\x00\x00\x20l13:UnknownMethod11:method namee"
            # end of message
            b"e",
        )

    def test_send_broken_body_stream(self):
        encoder, out_stream = self.make_response_encoder()
        encoder._headers = {}

        def stream_that_fails():
            yield b"aaa"
            yield b"bbb"
            raise Exception("Boom!")

        response = _mod_request.SuccessfulSmartServerResponse(
            (b"args",), body_stream=stream_that_fails()
        )
        encoder.send_response(response)
        expected_response = (
            b"bzr message 3 (bzr 1.6)\n"  # protocol marker
            b"\x00\x00\x00\x02de" + interrupted_body_stream  # headers dict (empty)
        )
        self.assertEqual(expected_response, out_stream.getvalue())


class TestResponseEncoderBufferingProtocolThree(tests.TestCase):
    """Tests for buffering of responses.

    We want to avoid doing many small writes when one would do, to avoid
    unnecessary network overhead.
    """

    def setUp(self):
        super().setUp()
        self.writes = []
        self.responder = protocol.ProtocolThreeResponder(self.writes.append)

    def assertWriteCount(self, expected_count):
        # self.writes can be quite large; don't show the whole thing
        self.assertEqual(
            expected_count,
            len(self.writes),
            f"Too many writes: {len(self.writes)}, expected {expected_count}"
        )

    def test_send_error_writes_just_once(self):
        """An error response is written to the medium all at once."""
        self.responder.send_error(Exception("An exception string."))
        self.assertWriteCount(1)

    def test_send_response_writes_just_once(self):
        """A normal response with no body is written to the medium all at once."""
        response = _mod_request.SuccessfulSmartServerResponse((b"arg", b"arg"))
        self.responder.send_response(response)
        self.assertWriteCount(1)

    def test_send_response_with_body_writes_just_once(self):
        """A normal response with a monolithic body is written to the medium
        all at once.
        """
        response = _mod_request.SuccessfulSmartServerResponse(
            (b"arg", b"arg"), body=b"body bytes"
        )
        self.responder.send_response(response)
        self.assertWriteCount(1)

    def test_send_response_with_body_stream_buffers_writes(self):
        """A normal response with a stream body writes to the medium once."""
        # Construct a response with stream with 2 chunks in it.
        response = _mod_request.SuccessfulSmartServerResponse(
            (b"arg", b"arg"), body_stream=[b"chunk1", b"chunk2"]
        )
        self.responder.send_response(response)
        # Per the discussion in bug 590638 we flush once after the header and
        # then once after each chunk
        self.assertWriteCount(3)


class TestSmartClientUnicode(tests.TestCase):
    """_SmartClient tests for unicode arguments.

    Unicode arguments to call_with_body_bytes are not correct (remote method
    names, arguments, and bodies must all be expressed as byte strings), but
    _SmartClient should gracefully reject them, rather than getting into a
    broken state that prevents future correct calls from working.  That is, it
    should be possible to issue more requests on the medium afterwards, rather
    than allowing one bad call to call_with_body_bytes to cause later calls to
    mysteriously fail with TooManyConcurrentRequests.
    """

    def assertCallDoesNotBreakMedium(self, method, args, body):
        """Call a medium with the given method, args and body, then assert that
        the medium is left in a sane state, i.e. is capable of allowing further
        requests.
        """
        input = BytesIO(b"\n")
        output = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, "ignored base"
        )
        smart_client = client._SmartClient(client_medium)
        self.assertRaises(
            TypeError, smart_client.call_with_body_bytes, method, args, body
        )
        self.assertEqual(b"", output.getvalue())
        self.assertEqual(None, client_medium._current_request)

    def test_call_with_body_bytes_unicode_method(self):
        self.assertCallDoesNotBreakMedium("method", (b"args",), b"body")

    def test_call_with_body_bytes_unicode_args(self):
        self.assertCallDoesNotBreakMedium(b"method", ("args",), b"body")
        self.assertCallDoesNotBreakMedium(b"method", (b"arg1", "arg2"), b"body")

    def test_call_with_body_bytes_unicode_body(self):
        self.assertCallDoesNotBreakMedium(b"method", (b"args",), "body")


class MockMedium(medium.SmartClientMedium):
    """A mock medium that can be used to test _SmartClient.

    It can be given a series of requests to expect (and responses it should
    return for them).  It can also be told when the client is expected to
    disconnect a medium.  Expectations must be satisfied in the order they are
    given, or else an AssertionError will be raised.

    Typical use looks like::

        medium = MockMedium()
        medium.expect_request(...)
        medium.expect_request(...)
        medium.expect_request(...)
    """

    def __init__(self):
        super().__init__("dummy base")
        self._mock_request = _MockMediumRequest(self)
        self._expected_events = []

    def expect_request(self, request_bytes, response_bytes, allow_partial_read=False):
        """Expect 'request_bytes' to be sent, and reply with 'response_bytes'.

        No assumption is made about how many times accept_bytes should be
        called to send the request.  Similarly, no assumption is made about how
        many times read_bytes/read_line are called by protocol code to read a
        response.  e.g.::

            request.accept_bytes(b'ab')
            request.accept_bytes(b'cd')
            request.finished_writing()

        and::

            request.accept_bytes(b'abcd')
            request.finished_writing()

        Will both satisfy ``medium.expect_request('abcd', ...)``.  Thus tests
        using this should not break due to irrelevant changes in protocol
        implementations.

        :param allow_partial_read: if True, no assertion is raised if a
            response is not fully read.  Setting this is useful when the client
            is expected to disconnect without needing to read the complete
            response.  Default is False.
        """
        self._expected_events.append(("send request", request_bytes))
        if allow_partial_read:
            self._expected_events.append(("read response (partial)", response_bytes))
        else:
            self._expected_events.append(("read response", response_bytes))

    def expect_disconnect(self):
        """Expect the client to call ``medium.disconnect()``."""
        self._expected_events.append("disconnect")

    def _assertEvent(self, observed_event):
        """Raise AssertionError unless observed_event matches the next expected
        event.

        :seealso: expect_request
        :seealso: expect_disconnect
        """
        try:
            expected_event = self._expected_events.pop(0)
        except IndexError as e:
            raise AssertionError(
                f"Mock medium observed event {observed_event!r}, but no more events expected"
            ) from e
        if expected_event[0] == "read response (partial)":
            if observed_event[0] != "read response":
                raise AssertionError(
                    f"Mock medium observed event {observed_event!r}, but expected event {expected_event!r}"
                )
        elif observed_event != expected_event:
            raise AssertionError(
                f"Mock medium observed event {observed_event!r}, but expected event {expected_event!r}"
            )
        if self._expected_events:
            next_event = self._expected_events[0]
            if next_event[0].startswith("read response"):
                self._mock_request._response = next_event[1]

    def get_request(self):
        return self._mock_request

    def disconnect(self):
        if self._mock_request._read_bytes:
            self._assertEvent(("read response", self._mock_request._read_bytes))
            self._mock_request._read_bytes = b""
        self._assertEvent("disconnect")


class _MockMediumRequest:
    """A mock ClientMediumRequest used by MockMedium."""

    def __init__(self, mock_medium):
        self._medium = mock_medium
        self._written_bytes = b""
        self._read_bytes = b""
        self._response = None

    def accept_bytes(self, bytes):
        self._written_bytes += bytes

    def finished_writing(self):
        self._medium._assertEvent(("send request", self._written_bytes))
        self._written_bytes = b""

    def finished_reading(self):
        self._medium._assertEvent(("read response", self._read_bytes))
        self._read_bytes = b""

    def read_bytes(self, size):
        resp = self._response
        bytes, resp = resp[:size], resp[size:]
        self._response = resp
        self._read_bytes += bytes
        return bytes

    def read_line(self):
        resp = self._response
        try:
            line, resp = resp.split(b"\n", 1)
            line += b"\n"
        except ValueError:
            line, resp = resp, b""
        self._response = resp
        self._read_bytes += line
        return line


class Test_SmartClientVersionDetection(tests.TestCase):
    """Tests for _SmartClient's automatic protocol version detection.

    On the first remote call, _SmartClient will keep retrying the request with
    different protocol versions until it finds one that works.
    """

    def test_version_three_server(self):
        """With a protocol 3 server, only one request is needed."""
        medium = MockMedium()
        smart_client = client._SmartClient(medium, headers={})
        message_start = protocol.MESSAGE_VERSION_THREE + b"\x00\x00\x00\x02de"
        medium.expect_request(
            message_start + b"s\x00\x00\x00\x1el11:method-name5:arg 15:arg 2ee",
            message_start + b"s\0\0\0\x13l14:response valueee",
        )
        result = smart_client.call(b"method-name", b"arg 1", b"arg 2")
        # The call succeeded without raising any exceptions from the mock
        # medium, and the smart_client returns the response from the server.
        self.assertEqual((b"response value",), result)
        self.assertEqual([], medium._expected_events)
        # Also, the v3 works then the server should be assumed to support RPCs
        # introduced in 1.6.
        self.assertFalse(medium._is_remote_before((1, 6)))

    def test_version_two_server(self):
        """If the server only speaks protocol 2, the client will first try
        version 3, then fallback to protocol 2.

        Further, _SmartClient caches the detection, so future requests will all
        use protocol 2 immediately.
        """
        medium = MockMedium()
        smart_client = client._SmartClient(medium, headers={})
        # First the client should send a v3 request, but the server will reply
        # with a v2 error.
        medium.expect_request(
            b"bzr message 3 (bzr 1.6)\n\x00\x00\x00\x02de"
            + b"s\x00\x00\x00\x1el11:method-name5:arg 15:arg 2ee",
            b"bzr response 2\nfailed\n\n",
        )
        # So then the client should disconnect to reset the connection, because
        # the client needs to assume the server cannot read any further
        # requests off the original connection.
        medium.expect_disconnect()
        # The client should then retry the original request in v2
        medium.expect_request(
            b"bzr request 2\nmethod-name\x01arg 1\x01arg 2\n",
            b"bzr response 2\nsuccess\nresponse value\n",
        )
        result = smart_client.call(b"method-name", b"arg 1", b"arg 2")
        # The smart_client object will return the result of the successful
        # query.
        self.assertEqual((b"response value",), result)

        # Now try another request, and this time the client will just use
        # protocol 2.  (i.e. the autodetection won't be repeated)
        medium.expect_request(
            b"bzr request 2\nanother-method\n",
            b"bzr response 2\nsuccess\nanother response\n",
        )
        result = smart_client.call(b"another-method")
        self.assertEqual((b"another response",), result)
        self.assertEqual([], medium._expected_events)

        # Also, because v3 is not supported, the client medium should assume
        # that RPCs introduced in 1.6 aren't supported either.
        self.assertTrue(medium._is_remote_before((1, 6)))

    def test_unknown_version(self):
        """If the server does not use any known (or at least supported)
        protocol version, a SmartProtocolError is raised.
        """
        medium = MockMedium()
        smart_client = client._SmartClient(medium, headers={})
        unknown_protocol_bytes = b"Unknown protocol!"
        # The client will try v3 and v2 before eventually giving up.
        medium.expect_request(
            b"bzr message 3 (bzr 1.6)\n\x00\x00\x00\x02de"
            + b"s\x00\x00\x00\x1el11:method-name5:arg 15:arg 2ee",
            unknown_protocol_bytes,
        )
        medium.expect_disconnect()
        medium.expect_request(
            b"bzr request 2\nmethod-name\x01arg 1\x01arg 2\n", unknown_protocol_bytes
        )
        medium.expect_disconnect()
        self.assertRaises(
            errors.SmartProtocolError,
            smart_client.call,
            b"method-name",
            b"arg 1",
            b"arg 2",
        )
        self.assertEqual([], medium._expected_events)

    def test_first_response_is_error(self):
        """If the server replies with an error, then the version detection
        should be complete.

        This test is very similar to test_version_two_server, but catches a bug
        we had in the case where the first reply was an error response.
        """
        medium = MockMedium()
        smart_client = client._SmartClient(medium, headers={})
        message_start = protocol.MESSAGE_VERSION_THREE + b"\x00\x00\x00\x02de"
        # Issue a request that gets an error reply in a non-default protocol
        # version.
        medium.expect_request(
            message_start + b"s\x00\x00\x00\x10l11:method-nameee",
            b"bzr response 2\nfailed\n\n",
        )
        medium.expect_disconnect()
        medium.expect_request(
            b"bzr request 2\nmethod-name\n", b"bzr response 2\nfailed\nFooBarError\n"
        )
        err = self.assertRaises(
            errors.ErrorFromSmartServer, smart_client.call, b"method-name"
        )
        self.assertEqual((b"FooBarError",), err.error_tuple)
        # Now the medium should have remembered the protocol version, so
        # subsequent requests will use the remembered version immediately.
        medium.expect_request(
            b"bzr request 2\nmethod-name\n",
            b"bzr response 2\nsuccess\nresponse value\n",
        )
        result = smart_client.call(b"method-name")
        self.assertEqual((b"response value",), result)
        self.assertEqual([], medium._expected_events)


class Test_SmartClient(tests.TestCase):
    def test_call_default_headers(self):
        """ProtocolThreeRequester.call by default sends a 'Software
        version' header.
        """
        smart_client = client._SmartClient("dummy medium")
        self.assertEqual(
            breezy.__version__.encode("utf-8"),
            smart_client._headers[b"Software version"],
        )
        # XXX: need a test that smart_client._headers is passed to the request
        # encoder.


class Test_SmartClientRequest(tests.TestCase):
    def make_client_with_failing_medium(self, fail_at_write=True, response=b""):
        response_io = BytesIO(response)
        output = BytesIO()
        vendor = FirstRejectedBytesIOSSHVendor(
            response_io, output, fail_at_write=fail_at_write
        )
        ssh_params = medium.SSHParams("a host", "a port", "a user", "a pass")
        client_medium = medium.SmartSSHClientMedium("base", ssh_params, vendor)
        smart_client = client._SmartClient(client_medium, headers={})
        return output, vendor, smart_client

    def make_response(self, args, body=None, body_stream=None):
        response_io = BytesIO()
        response = _mod_request.SuccessfulSmartServerResponse(
            args, body=body, body_stream=body_stream
        )
        responder = protocol.ProtocolThreeResponder(response_io.write)
        responder.send_response(response)
        return response_io.getvalue()

    def test__call_doesnt_retry_append(self):
        response = self.make_response(("appended", b"8"))
        output, vendor, smart_client = self.make_client_with_failing_medium(
            fail_at_write=False, response=response
        )
        smart_request = client._SmartClientRequest(
            smart_client, b"append", (b"foo", b""), body=b"content\n"
        )
        self.assertRaises(errors.ConnectionReset, smart_request._call, 3)

    def test__call_retries_get_bytes(self):
        response = self.make_response((b"ok",), b"content\n")
        output, vendor, smart_client = self.make_client_with_failing_medium(
            fail_at_write=False, response=response
        )
        smart_request = client._SmartClientRequest(smart_client, b"get", (b"foo",))
        response, response_handler = smart_request._call(3)
        self.assertEqual((b"ok",), response)
        self.assertEqual(b"content\n", response_handler.read_body_bytes())

    def test__call_noretry_get_bytes(self):
        debug.debug_flags.add("noretry")
        response = self.make_response((b"ok",), b"content\n")
        output, vendor, smart_client = self.make_client_with_failing_medium(
            fail_at_write=False, response=response
        )
        smart_request = client._SmartClientRequest(smart_client, b"get", (b"foo",))
        self.assertRaises(errors.ConnectionReset, smart_request._call, 3)

    def test__send_no_retry_pipes(self):
        client_read, server_write = create_file_pipes()
        server_read, client_write = create_file_pipes()
        client_medium = medium.SmartSimplePipesClientMedium(
            client_read, client_write, base="/"
        )
        smart_client = client._SmartClient(client_medium)
        smart_request = client._SmartClientRequest(smart_client, b"hello", ())
        # Close the server side
        server_read.close()
        encoder, response_handler = smart_request._construct_protocol(3)
        self.assertRaises(errors.ConnectionReset, smart_request._send_no_retry, encoder)

    def test__send_read_response_sockets(self):
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.bind(("127.0.0.1", 0))
        listen_sock.listen(1)
        host, port = listen_sock.getsockname()
        client_medium = medium.SmartTCPClientMedium(host, port, "/")
        client_medium._ensure_connection()
        smart_client = client._SmartClient(client_medium)
        smart_request = client._SmartClientRequest(smart_client, b"hello", ())
        # Accept the connection, but don't actually talk to the client.
        server_sock, _ = listen_sock.accept()
        server_sock.close()
        # Sockets buffer and don't really notice that the server has closed the
        # connection until we try to read again.
        handler = smart_request._send(3)
        self.assertRaises(
            errors.ConnectionReset, handler.read_response_tuple, expect_body=False
        )

    def test__send_retries_on_write(self):
        output, vendor, smart_client = self.make_client_with_failing_medium()
        smart_request = client._SmartClientRequest(smart_client, b"hello", ())
        handler = smart_request._send(3)
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol
            b"\x00\x00\x00\x02de"  # empty headers
            b"s\x00\x00\x00\tl5:helloee",
            output.getvalue(),
        )
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    "a user",
                    "a pass",
                    "a host",
                    "a port",
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
                ("close",),
                (
                    "connect_ssh",
                    "a user",
                    "a pass",
                    "a host",
                    "a port",
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
            ],
            vendor.calls,
        )
        del handler

    def test__send_doesnt_retry_read_failure(self):
        output, vendor, smart_client = self.make_client_with_failing_medium(
            fail_at_write=False
        )
        smart_request = client._SmartClientRequest(smart_client, b"hello", ())
        handler = smart_request._send(3)
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol
            b"\x00\x00\x00\x02de"  # empty headers
            b"s\x00\x00\x00\tl5:helloee",
            output.getvalue(),
        )
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    "a user",
                    "a pass",
                    "a host",
                    "a port",
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
            ],
            vendor.calls,
        )
        self.assertRaises(errors.ConnectionReset, handler.read_response_tuple)

    def test__send_request_retries_body_stream_if_not_started(self):
        output, vendor, smart_client = self.make_client_with_failing_medium()
        smart_request = client._SmartClientRequest(
            smart_client, b"hello", (), body_stream=[b"a", b"b"]
        )
        response_handler = smart_request._send(3)
        # We connect, get disconnected, and notice before consuming the stream,
        # so we try again one time and succeed.
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    "a user",
                    "a pass",
                    "a host",
                    "a port",
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
                ("close",),
                (
                    "connect_ssh",
                    "a user",
                    "a pass",
                    "a host",
                    "a port",
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
            ],
            vendor.calls,
        )
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol
            b"\x00\x00\x00\x02de"  # empty headers
            b"s\x00\x00\x00\tl5:helloe"
            b"b\x00\x00\x00\x01a"
            b"b\x00\x00\x00\x01b"
            b"e",
            output.getvalue(),
        )
        del response_handler

    def test__send_request_stops_if_body_started(self):
        # We intentionally use the python BytesIO so that we can subclass it.
        from io import BytesIO

        response = BytesIO()

        class FailAfterFirstWrite(BytesIO):
            """Allow one 'write' call to pass, fail the rest."""

            def __init__(self):
                BytesIO.__init__(self)
                self._first = True

            def write(self, s):
                if self._first:
                    self._first = False
                    return BytesIO.write(self, s)
                raise OSError(errno.EINVAL, "invalid file handle")

        output = FailAfterFirstWrite()

        vendor = FirstRejectedBytesIOSSHVendor(response, output, fail_at_write=False)
        ssh_params = medium.SSHParams("a host", "a port", "a user", "a pass")
        client_medium = medium.SmartSSHClientMedium("base", ssh_params, vendor)
        smart_client = client._SmartClient(client_medium, headers={})
        smart_request = client._SmartClientRequest(
            smart_client, b"hello", (), body_stream=[b"a", b"b"]
        )
        self.assertRaises(errors.ConnectionReset, smart_request._send, 3)
        # We connect, and manage to get to the point that we start consuming
        # the body stream. The next write fails, so we just stop.
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    "a user",
                    "a pass",
                    "a host",
                    "a port",
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
                ("close",),
            ],
            vendor.calls,
        )
        self.assertEqual(
            b"bzr message 3 (bzr 1.6)\n"  # protocol
            b"\x00\x00\x00\x02de"  # empty headers
            b"s\x00\x00\x00\tl5:helloe",
            output.getvalue(),
        )

    def test__send_disabled_retry(self):
        debug.debug_flags.add("noretry")
        output, vendor, smart_client = self.make_client_with_failing_medium()
        smart_request = client._SmartClientRequest(smart_client, b"hello", ())
        self.assertRaises(errors.ConnectionReset, smart_request._send, 3)
        self.assertEqual(
            [
                (
                    "connect_ssh",
                    "a user",
                    "a pass",
                    "a host",
                    "a port",
                    ["bzr", "serve", "--inet", "--directory=/", "--allow-writes"],
                ),
                ("close",),
            ],
            vendor.calls,
        )


class LengthPrefixedBodyDecoder(tests.TestCase):
    # XXX: TODO: make accept_reading_trailer invoke translate_response or
    # something similar to the ProtocolBase method.

    def test_construct(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual(b"", decoder.read_pending_data())
        self.assertEqual(b"", decoder.unused_data)

    def test_accept_bytes(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes(b"")
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual(b"", decoder.read_pending_data())
        self.assertEqual(b"", decoder.unused_data)
        decoder.accept_bytes(b"7")
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual(b"", decoder.read_pending_data())
        self.assertEqual(b"", decoder.unused_data)
        decoder.accept_bytes(b"\na")
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(11, decoder.next_read_size())
        self.assertEqual(b"a", decoder.read_pending_data())
        self.assertEqual(b"", decoder.unused_data)
        decoder.accept_bytes(b"bcdefgd")
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(4, decoder.next_read_size())
        self.assertEqual(b"bcdefg", decoder.read_pending_data())
        self.assertEqual(b"", decoder.unused_data)
        decoder.accept_bytes(b"one")
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual(b"", decoder.read_pending_data())
        self.assertEqual(b"", decoder.unused_data)
        decoder.accept_bytes(b"\nblarg")
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual(b"", decoder.read_pending_data())
        self.assertEqual(b"blarg", decoder.unused_data)

    def test_accept_bytes_all_at_once_with_excess(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes(b"1\nadone\nunused")
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual(b"a", decoder.read_pending_data())
        self.assertEqual(b"unused", decoder.unused_data)

    def test_accept_bytes_exact_end_of_body(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes(b"1\na")
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(5, decoder.next_read_size())
        self.assertEqual(b"a", decoder.read_pending_data())
        self.assertEqual(b"", decoder.unused_data)
        decoder.accept_bytes(b"done\n")
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual(b"", decoder.read_pending_data())
        self.assertEqual(b"", decoder.unused_data)


class TestChunkedBodyDecoder(tests.TestCase):
    """Tests for ChunkedBodyDecoder.

    This is the body decoder used for protocol version two.
    """

    def test_construct(self):
        decoder = protocol.ChunkedBodyDecoder()
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(8, decoder.next_read_size())
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual(b"", decoder.unused_data)

    def test_empty_content(self):
        r"""'chunked\nEND\n' is the complete encoding of a zero-length body."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        decoder.accept_bytes(b"END\n")
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual(b"", decoder.unused_data)

    def test_one_chunk(self):
        """A body in a single chunk is decoded correctly."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        chunk_length = b"f\n"
        chunk_content = b"123456789abcdef"
        finish = b"END\n"
        decoder.accept_bytes(chunk_length + chunk_content + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_content, decoder.read_next_chunk())
        self.assertEqual(b"", decoder.unused_data)

    def test_incomplete_chunk(self):
        """When there are less bytes in the chunk than declared by the length,
        then we haven't finished reading yet.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        chunk_length = b"8\n"
        three_bytes = b"123"
        decoder.accept_bytes(chunk_length + three_bytes)
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(
            5 + 4,
            decoder.next_read_size(),
            "The next_read_size hint should be the number of missing bytes in "
            "this chunk plus 4 (the length of the end-of-body marker: "
            "'END\\n')",
        )
        self.assertEqual(None, decoder.read_next_chunk())

    def test_incomplete_length(self):
        """A chunk length hasn't been read until a newline byte has been read."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        decoder.accept_bytes(b"9")
        self.assertEqual(
            1,
            decoder.next_read_size(),
            "The next_read_size hint should be 1, because we don't know the "
            "length yet.",
        )
        decoder.accept_bytes(b"\n")
        self.assertEqual(
            9 + 4,
            decoder.next_read_size(),
            "The next_read_size hint should be the length of the chunk plus 4 "
            "(the length of the end-of-body marker: 'END\\n')",
        )
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(None, decoder.read_next_chunk())

    def test_two_chunks(self):
        """Content from multiple chunks is concatenated."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        chunk_one = b"3\naaa"
        chunk_two = b"5\nbbbbb"
        finish = b"END\n"
        decoder.accept_bytes(chunk_one + chunk_two + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(b"aaa", decoder.read_next_chunk())
        self.assertEqual(b"bbbbb", decoder.read_next_chunk())
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual(b"", decoder.unused_data)

    def test_excess_bytes(self):
        """Bytes after the chunked body are reported as unused bytes."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        chunked_body = b"5\naaaaaEND\n"
        excess_bytes = b"excess bytes"
        decoder.accept_bytes(chunked_body + excess_bytes)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(b"aaaaa", decoder.read_next_chunk())
        self.assertEqual(excess_bytes, decoder.unused_data)
        self.assertEqual(
            1,
            decoder.next_read_size(),
            "next_read_size hint should be 1 when finished_reading.",
        )

    def test_multidigit_length(self):
        """Lengths in the chunk prefixes can have multiple digits."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        length = 0x123
        chunk_prefix = hex(length).encode("ascii") + b"\n"
        chunk_bytes = b"z" * length
        finish = b"END\n"
        decoder.accept_bytes(chunk_prefix + chunk_bytes + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_bytes, decoder.read_next_chunk())

    def test_byte_at_a_time(self):
        """A complete body fed to the decoder one byte at a time should not
        confuse the decoder.  That is, it should give the same result as if the
        bytes had been received in one batch.

        This test is the same as test_one_chunk apart from the way accept_bytes
        is called.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        chunk_length = b"f\n"
        chunk_content = b"123456789abcdef"
        finish = b"END\n"
        combined = chunk_length + chunk_content + finish
        for i in range(len(combined)):
            decoder.accept_bytes(combined[i : i + 1])
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_content, decoder.read_next_chunk())
        self.assertEqual(b"", decoder.unused_data)

    def test_read_pending_data_resets(self):
        """read_pending_data does not return the same bytes twice."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        chunk_one = b"3\naaa"
        chunk_two = b"3\nbbb"
        decoder.accept_bytes(chunk_one)
        self.assertEqual(b"aaa", decoder.read_next_chunk())
        decoder.accept_bytes(chunk_two)
        self.assertEqual(b"bbb", decoder.read_next_chunk())
        self.assertEqual(None, decoder.read_next_chunk())

    def test_decode_error(self):
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(b"chunked\n")
        chunk_one = b"b\nfirst chunk"
        error_signal = b"ERR\n"
        error_chunks = b"5\npart1" + b"5\npart2"
        finish = b"END\n"
        decoder.accept_bytes(chunk_one + error_signal + error_chunks + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(b"first chunk", decoder.read_next_chunk())
        expected_failure = _mod_request.FailedSmartServerResponse((b"part1", b"part2"))
        self.assertEqual(expected_failure, decoder.read_next_chunk())

    def test_bad_header(self):
        """accept_bytes raises a SmartProtocolError if a chunked body does not
        start with the right header.
        """
        decoder = protocol.ChunkedBodyDecoder()
        self.assertRaises(
            errors.SmartProtocolError, decoder.accept_bytes, b"bad header\n"
        )


class TestSuccessfulSmartServerResponse(tests.TestCase):
    def test_construct_no_body(self):
        response = _mod_request.SuccessfulSmartServerResponse((b"foo", b"bar"))
        self.assertEqual((b"foo", b"bar"), response.args)
        self.assertEqual(None, response.body)

    def test_construct_with_body(self):
        response = _mod_request.SuccessfulSmartServerResponse(
            (b"foo", b"bar"), b"bytes"
        )
        self.assertEqual((b"foo", b"bar"), response.args)
        self.assertEqual(b"bytes", response.body)
        # repr(response) doesn't trigger exceptions.
        repr(response)

    def test_construct_with_body_stream(self):
        bytes_iterable = [b"abc"]
        response = _mod_request.SuccessfulSmartServerResponse(
            (b"foo", b"bar"), body_stream=bytes_iterable
        )
        self.assertEqual((b"foo", b"bar"), response.args)
        self.assertEqual(bytes_iterable, response.body_stream)

    def test_construct_rejects_body_and_body_stream(self):
        """'body' and 'body_stream' are mutually exclusive."""
        self.assertRaises(
            errors.BzrError,
            _mod_request.SuccessfulSmartServerResponse,
            (),
            b"body",
            [b"stream"],
        )

    def test_is_successful(self):
        """is_successful should return True for SuccessfulSmartServerResponse."""
        response = _mod_request.SuccessfulSmartServerResponse((b"error",))
        self.assertEqual(True, response.is_successful())


class TestFailedSmartServerResponse(tests.TestCase):
    def test_construct(self):
        response = _mod_request.FailedSmartServerResponse((b"foo", b"bar"))
        self.assertEqual((b"foo", b"bar"), response.args)
        self.assertEqual(None, response.body)
        response = _mod_request.FailedSmartServerResponse((b"foo", b"bar"), b"bytes")
        self.assertEqual((b"foo", b"bar"), response.args)
        self.assertEqual(b"bytes", response.body)
        # repr(response) doesn't trigger exceptions.
        repr(response)

    def test_is_successful(self):
        """is_successful should return False for FailedSmartServerResponse."""
        response = _mod_request.FailedSmartServerResponse((b"error",))
        self.assertEqual(False, response.is_successful())


class FakeHTTPMedium:
    def __init__(self):
        self.written_request = None
        self._current_request = None

    def send_http_smart_request(self, bytes):
        self.written_request = bytes
        return None


class HTTPTunnellingSmokeTest(tests.TestCase):
    def setUp(self):
        super().setUp()
        # We use the VFS layer as part of HTTP tunnelling tests.
        self.overrideEnv("BRZ_NO_SMART_VFS", None)

    def test_smart_http_medium_request_accept_bytes(self):
        medium = FakeHTTPMedium()
        request = urllib.SmartClientHTTPMediumRequest(medium)
        request.accept_bytes(b"abc")
        request.accept_bytes(b"def")
        self.assertEqual(None, medium.written_request)
        request.finished_writing()
        self.assertEqual(b"abcdef", medium.written_request)


class RemoteHTTPTransportTestCase(tests.TestCase):
    def test_remote_path_after_clone_child(self):
        # If a user enters "bzr+http://host/foo", we want to sent all smart
        # requests for child URLs of that to the original URL.  i.e., we want to
        # POST to "bzr+http://host/foo/.bzr/smart" and never something like
        # "bzr+http://host/foo/.bzr/branch/.bzr/smart".  So, a cloned
        # RemoteHTTPTransport remembers the initial URL, and adjusts the
        # relpaths it sends in smart requests accordingly.
        base_transport = remote.RemoteHTTPTransport("bzr+http://host/path")
        new_transport = base_transport.clone("child_dir")
        self.assertEqual(base_transport._http_transport, new_transport._http_transport)
        self.assertEqual("child_dir/foo", new_transport._remote_path("foo"))
        self.assertEqual(
            b"child_dir/",
            new_transport._client.remote_path_from_transport(new_transport),
        )

    def test_remote_path_unnormal_base(self):
        # If the transport's base isn't normalised, the _remote_path should
        # still be calculated correctly.
        base_transport = remote.RemoteHTTPTransport("bzr+http://host/%7Ea/b")
        self.assertEqual("c", base_transport._remote_path("c"))

    def test_clone_unnormal_base(self):
        # If the transport's base isn't normalised, cloned transports should
        # still work correctly.
        base_transport = remote.RemoteHTTPTransport("bzr+http://host/%7Ea/b")
        new_transport = base_transport.clone("c")
        self.assertEqual(base_transport.base + "c/", new_transport.base)
        self.assertEqual(
            b"c/", new_transport._client.remote_path_from_transport(new_transport)
        )

    def test__redirect_to(self):
        t = remote.RemoteHTTPTransport("bzr+http://www.example.com/foo")
        r = t._redirected_to("http://www.example.com/foo", "http://www.example.com/bar")
        self.assertEqual(type(r), type(t))

    def test__redirect_sibling_protocol(self):
        t = remote.RemoteHTTPTransport("bzr+http://www.example.com/foo")
        r = t._redirected_to(
            "http://www.example.com/foo", "https://www.example.com/bar"
        )
        self.assertEqual(type(r), type(t))
        self.assertStartsWith(r.base, "bzr+https")

    def test__redirect_to_with_user(self):
        t = remote.RemoteHTTPTransport("bzr+http://joe@www.example.com/foo")
        r = t._redirected_to("http://www.example.com/foo", "http://www.example.com/bar")
        self.assertEqual(type(r), type(t))
        self.assertEqual("joe", t._parsed_url.user)
        self.assertEqual(t._parsed_url.user, r._parsed_url.user)

    def test_redirected_to_same_host_different_protocol(self):
        t = remote.RemoteHTTPTransport("bzr+http://joe@www.example.com/foo")
        r = t._redirected_to("http://www.example.com/foo", "bzr://www.example.com/foo")
        self.assertNotEqual(type(r), type(t))


class TestErrors(tests.TestCase):
    def test_too_many_concurrent_requests(self):
        error = medium.TooManyConcurrentRequests("a medium")
        self.assertEqualDiff(
            "The medium 'a medium' has reached its concurrent "
            "request limit. Be sure to finish_writing and finish_reading on "
            "the currently open request.",
            str(error),
        )

    def test_smart_message_handler_error(self):
        # Make an exc_info tuple.
        try:
            raise Exception("example error")
        except Exception:
            err = protocol.SmartMessageHandlerError(sys.exc_info())
        # GZ 2010-11-08: Should not store exc_info in exception instances.
        try:
            self.assertStartsWith(
                str(err), "The message handler raised an exception:\n"
            )
            self.assertEndsWith(str(err), "Exception: example error\n")
        finally:
            del err
