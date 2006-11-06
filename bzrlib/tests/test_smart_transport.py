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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for smart transport"""

# all of this deals with byte strings so this is safe
from cStringIO import StringIO
import os
import socket
import threading
import urllib2

from bzrlib import (
        bzrdir,
        errors,
        osutils,
        tests,
        urlutils,
        )
from bzrlib.transport import (
        get_transport,
        local,
        memory,
        smart,
        )
from bzrlib.transport.http import (
        HTTPServerWithSmarts,
        SmartClientHTTPMediumRequest,
        SmartRequestHandler,
        )


class StringIOSSHVendor(object):
    """A SSH vendor that uses StringIO to buffer writes and answer reads."""

    def __init__(self, read_from, write_to):
        self.read_from = read_from
        self.write_to = write_to
        self.calls = []

    def connect_ssh(self, username, password, host, port, command):
        self.calls.append(('connect_ssh', username, password, host, port,
            command))
        return StringIOSSHConnection(self)


class StringIOSSHConnection(object):
    """A SSH connection that uses StringIO to buffer writes and answer reads."""

    def __init__(self, vendor):
        self.vendor = vendor
    
    def close(self):
        self.vendor.calls.append(('close', ))
        
    def get_filelike_channels(self):
        return self.vendor.read_from, self.vendor.write_to



class SmartClientMediumTests(tests.TestCase):
    """Tests for SmartClientMedium.

    We should create a test scenario for this: we need a server module that
    construct the test-servers (like make_loopsocket_and_medium), and the list
    of SmartClientMedium classes to test.
    """

    def make_loopsocket_and_medium(self):
        """Create a loopback socket for testing, and a medium aimed at it."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        medium = smart.SmartTCPClientMedium('127.0.0.1', port)
        return sock, medium

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
    
    def test_construct_smart_stream_medium_client(self):
        # make a new instance of the common base for Stream-like Mediums.
        # this just ensures that the constructor stays parameter-free which
        # is important for reuse : some subclasses will dynamically connect,
        # others are always on, etc.
        medium = smart.SmartClientStreamMedium()

    def test_construct_smart_client_medium(self):
        # the base client medium takes no parameters
        medium = smart.SmartClientMedium()
    
    def test_construct_smart_simple_pipes_client_medium(self):
        # the SimplePipes client medium takes two pipes:
        # readable pipe, writeable pipe.
        # Constructing one should just save these and do nothing.
        # We test this by passing in None.
        medium = smart.SmartSimplePipesClientMedium(None, None)
        
    def test_simple_pipes_client_request_type(self):
        # SimplePipesClient should use SmartClientStreamMediumRequest's.
        medium = smart.SmartSimplePipesClientMedium(None, None)
        request = medium.get_request()
        self.assertIsInstance(request, smart.SmartClientStreamMediumRequest)

    def test_simple_pipes_client_get_concurrent_requests(self):
        # the simple_pipes client does not support pipelined requests:
        # but it does support serial requests: we construct one after 
        # another is finished. This is a smoke test testing the integration
        # of the SmartClientStreamMediumRequest and the SmartClientStreamMedium
        # classes - as the sibling classes share this logic, they do not have
        # explicit tests for this.
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(None, output)
        request = medium.get_request()
        request.finished_writing()
        request.finished_reading()
        request2 = medium.get_request()
        request2.finished_writing()
        request2.finished_reading()

    def test_simple_pipes_client__accept_bytes_writes_to_writable(self):
        # accept_bytes writes to the writeable pipe.
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(None, output)
        medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
    
    def test_simple_pipes_client_disconnect_does_nothing(self):
        # calling disconnect does nothing.
        input = StringIO()
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        # send some bytes to ensure disconnecting after activity still does not
        # close.
        medium._accept_bytes('abc')
        medium.disconnect()
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)

    def test_simple_pipes_client_accept_bytes_after_disconnect(self):
        # calling disconnect on the client does not alter the pipe that
        # accept_bytes writes to.
        input = StringIO()
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        medium._accept_bytes('abc')
        medium.disconnect()
        medium._accept_bytes('abc')
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)
        self.assertEqual('abcabc', output.getvalue())
    
    def test_simple_pipes_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SimplePipes medium
        # does nothing.
        medium = smart.SmartSimplePipesClientMedium(None, None)
        medium.disconnect()

    def test_simple_pipes_client_can_always_read(self):
        # SmartSimplePipesClientMedium is never disconnected, so read_bytes
        # always tries to read from the underlying pipe.
        input = StringIO('abcdef')
        medium = smart.SmartSimplePipesClientMedium(input, None)
        self.assertEqual('abc', medium.read_bytes(3))
        medium.disconnect()
        self.assertEqual('def', medium.read_bytes(3))
        
    def test_simple_pipes_client_supports__flush(self):
        # invoking _flush on a SimplePipesClient should flush the output 
        # pipe. We test this by creating an output pipe that records
        # flush calls made to it.
        from StringIO import StringIO # get regular StringIO
        input = StringIO()
        output = StringIO()
        flush_calls = []
        def logging_flush(): flush_calls.append('flush')
        output.flush = logging_flush
        medium = smart.SmartSimplePipesClientMedium(input, output)
        # this call is here to ensure we only flush once, not on every
        # _accept_bytes call.
        medium._accept_bytes('abc')
        medium._flush()
        medium.disconnect()
        self.assertEqual(['flush'], flush_calls)

    def test_construct_smart_ssh_client_medium(self):
        # the SSH client medium takes:
        # host, port, username, password, vendor
        # Constructing one should just save these and do nothing.
        # we test this by creating a empty bound socket and constructing
        # a medium.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        unopened_port = sock.getsockname()[1]
        # having vendor be invalid means that if it tries to connect via the
        # vendor it will blow up.
        medium = smart.SmartSSHClientMedium('127.0.0.1', unopened_port,
            username=None, password=None, vendor="not a vendor")
        sock.close()

    def test_ssh_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        medium = smart.SmartSSHClientMedium('a hostname', 'a port', 'a username',
            'a password', vendor)
        medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
        self.assertEqual([('connect_ssh', 'a username', 'a password',
            'a hostname', 'a port',
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes'])],
            vendor.calls)
    
    def test_ssh_client_changes_command_when_BZR_REMOTE_PATH_is_set(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        orig_bzr_remote_path = os.environ.get('BZR_REMOTE_PATH')
        def cleanup_environ():
            osutils.set_or_unset_env('BZR_REMOTE_PATH', orig_bzr_remote_path)
        self.addCleanup(cleanup_environ)
        os.environ['BZR_REMOTE_PATH'] = 'fugly'
        medium = smart.SmartSSHClientMedium('a hostname', 'a port', 'a username',
            'a password', vendor)
        medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
        self.assertEqual([('connect_ssh', 'a username', 'a password',
            'a hostname', 'a port',
            ['fugly', 'serve', '--inet', '--directory=/', '--allow-writes'])],
            vendor.calls)
    
    def test_ssh_client_disconnect_does_so(self):
        # calling disconnect should disconnect both the read_from and write_to
        # file-like object it from the ssh connection.
        input = StringIO()
        output = StringIO()
        vendor = StringIOSSHVendor(input, output)
        medium = smart.SmartSSHClientMedium('a hostname', vendor=vendor)
        medium._accept_bytes('abc')
        medium.disconnect()
        self.assertTrue(input.closed)
        self.assertTrue(output.closed)
        self.assertEqual([
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ],
            vendor.calls)

    def test_ssh_client_disconnect_allows_reconnection(self):
        # calling disconnect on the client terminates the connection, but should
        # not prevent additional connections occuring.
        # we test this by initiating a second connection after doing a
        # disconnect.
        input = StringIO()
        output = StringIO()
        vendor = StringIOSSHVendor(input, output)
        medium = smart.SmartSSHClientMedium('a hostname', vendor=vendor)
        medium._accept_bytes('abc')
        medium.disconnect()
        # the disconnect has closed output, so we need a new output for the
        # new connection to write to.
        input2 = StringIO()
        output2 = StringIO()
        vendor.read_from = input2
        vendor.write_to = output2
        medium._accept_bytes('abc')
        medium.disconnect()
        self.assertTrue(input.closed)
        self.assertTrue(output.closed)
        self.assertTrue(input2.closed)
        self.assertTrue(output2.closed)
        self.assertEqual([
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ],
            vendor.calls)
    
    def test_ssh_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SSH medium
        # does not fail.  It's ok to disconnect an unconnected medium.
        medium = smart.SmartSSHClientMedium(None)
        medium.disconnect()

    def test_ssh_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) SSH medium raises
        # MediumNotConnected.
        medium = smart.SmartSSHClientMedium(None)
        self.assertRaises(errors.MediumNotConnected, medium.read_bytes, 0)
        self.assertRaises(errors.MediumNotConnected, medium.read_bytes, 1)

    def test_ssh_client_supports__flush(self):
        # invoking _flush on a SSHClientMedium should flush the output 
        # pipe. We test this by creating an output pipe that records
        # flush calls made to it.
        from StringIO import StringIO # get regular StringIO
        input = StringIO()
        output = StringIO()
        flush_calls = []
        def logging_flush(): flush_calls.append('flush')
        output.flush = logging_flush
        vendor = StringIOSSHVendor(input, output)
        medium = smart.SmartSSHClientMedium('a hostname', vendor=vendor)
        # this call is here to ensure we only flush once, not on every
        # _accept_bytes call.
        medium._accept_bytes('abc')
        medium._flush()
        medium.disconnect()
        self.assertEqual(['flush'], flush_calls)
        
    def test_construct_smart_tcp_client_medium(self):
        # the TCP client medium takes a host and a port.  Constructing it won't
        # connect to anything.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        unopened_port = sock.getsockname()[1]
        medium = smart.SmartTCPClientMedium('127.0.0.1', unopened_port)
        sock.close()

    def test_tcp_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        medium.accept_bytes('abc')
        t.join()
        sock.close()
        self.assertEqual(['abc'], bytes)
    
    def test_tcp_client_disconnect_does_so(self):
        # calling disconnect on the client terminates the connection.
        # we test this by forcing a short read during a socket.MSG_WAITALL
        # call: write 2 bytes, try to read 3, and then the client disconnects.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        medium.accept_bytes('ab')
        medium.disconnect()
        t.join()
        sock.close()
        self.assertEqual(['ab'], bytes)
        # now disconnect again: this should not do anything, if disconnection
        # really did disconnect.
        medium.disconnect()
    
    def test_tcp_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) TCP medium
        # does not fail.  It's ok to disconnect an unconnected medium.
        medium = smart.SmartTCPClientMedium(None, None)
        medium.disconnect()

    def test_tcp_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) TCP medium raises
        # MediumNotConnected.
        medium = smart.SmartTCPClientMedium(None, None)
        self.assertRaises(errors.MediumNotConnected, medium.read_bytes, 0)
        self.assertRaises(errors.MediumNotConnected, medium.read_bytes, 1)

    def test_tcp_client_supports__flush(self):
        # invoking _flush on a TCPClientMedium should do something useful.
        # RBC 20060922 not sure how to test/tell in this case.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        # try with nothing buffered
        medium._flush()
        medium._accept_bytes('ab')
        # and with something sent.
        medium._flush()
        medium.disconnect()
        t.join()
        sock.close()
        self.assertEqual(['ab'], bytes)
        # now disconnect again : this should not do anything, if disconnection
        # really did disconnect.
        medium.disconnect()


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
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(None, output)
        request = smart.SmartClientStreamMediumRequest(medium)
        request.finished_writing()
        self.assertRaises(errors.WritingCompleted, request.accept_bytes, None)

    def test_accept_bytes(self):
        # accept bytes should invoke _accept_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the pipes get the data.
        input = StringIO()
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        request = smart.SmartClientStreamMediumRequest(medium)
        request.accept_bytes('123')
        request.finished_writing()
        request.finished_reading()
        self.assertEqual('', input.getvalue())
        self.assertEqual('123', output.getvalue())

    def test_construct_sets_stream_request(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium sets
        # the current request to the new SmartClientStreamMediumRequest
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(None, output)
        request = smart.SmartClientStreamMediumRequest(medium)
        self.assertIs(medium._current_request, request)

    def test_construct_while_another_request_active_throws(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium with
        # a non-None _current_request raises TooManyConcurrentRequests.
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(None, output)
        medium._current_request = "a"
        self.assertRaises(errors.TooManyConcurrentRequests,
            smart.SmartClientStreamMediumRequest, medium)

    def test_finished_read_clears_current_request(self):
        # calling finished_reading clears the current request from the requests
        # medium
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(None, output)
        request = smart.SmartClientStreamMediumRequest(medium)
        request.finished_writing()
        request.finished_reading()
        self.assertEqual(None, medium._current_request)

    def test_finished_read_before_finished_write_errors(self):
        # calling finished_reading before calling finished_writing triggers a
        # WritingNotComplete error.
        medium = smart.SmartSimplePipesClientMedium(None, None)
        request = smart.SmartClientStreamMediumRequest(medium)
        self.assertRaises(errors.WritingNotComplete, request.finished_reading)
        
    def test_read_bytes(self):
        # read bytes should invoke _read_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the data is supplied. Its possible that a 
        # faulty implementation could poke at the pipe variables them selves,
        # but we trust that this will be caught as it will break the integration
        # smoke tests.
        input = StringIO('321')
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        request = smart.SmartClientStreamMediumRequest(medium)
        request.finished_writing()
        self.assertEqual('321', request.read_bytes(3))
        request.finished_reading()
        self.assertEqual('', input.read())
        self.assertEqual('', output.getvalue())

    def test_read_bytes_before_finished_write_errors(self):
        # calling read_bytes before calling finished_writing triggers a
        # WritingNotComplete error because the Smart protocol is designed to be
        # compatible with strict message based protocols like HTTP where the
        # request cannot be submitted until the writing has completed.
        medium = smart.SmartSimplePipesClientMedium(None, None)
        request = smart.SmartClientStreamMediumRequest(medium)
        self.assertRaises(errors.WritingNotComplete, request.read_bytes, None)

    def test_read_bytes_after_finished_reading_errors(self):
        # calling read_bytes after calling finished_reading raises 
        # ReadingCompleted to prevent bad assumptions on stream environments
        # breaking the needs of message-based environments.
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(None, output)
        request = smart.SmartClientStreamMediumRequest(medium)
        request.finished_writing()
        request.finished_reading()
        self.assertRaises(errors.ReadingCompleted, request.read_bytes, None)


class RemoteTransportTests(tests.TestCaseWithTransport):

    def setUp(self):
        super(RemoteTransportTests, self).setUp()
        # We're allowed to set  the transport class here, so that we don't use
        # the default or a parameterized class, but rather use the
        # TestCaseWithTransport infrastructure to set up a smart server and
        # transport.
        self.transport_server = smart.SmartTCPServer_for_testing

    def test_plausible_url(self):
        self.assert_(self.get_url().startswith('bzr://'))

    def test_probe_transport(self):
        t = self.get_transport()
        self.assertIsInstance(t, smart.SmartTransport)

    def test_get_medium_from_transport(self):
        """Remote transport has a medium always, which it can return."""
        t = self.get_transport()
        medium = t.get_smart_medium()
        self.assertIsInstance(medium, smart.SmartClientMedium)


class ErrorRaisingProtocol(object):

    def __init__(self, exception):
        self.exception = exception

    def next_read_size(self):
        raise self.exception


class SampleRequest(object):
    
    def __init__(self, expected_bytes):
        self.accepted_bytes = ''
        self._finished_reading = False
        self.expected_bytes = expected_bytes
        self.excess_buffer = ''

    def accept_bytes(self, bytes):
        self.accepted_bytes += bytes
        if self.accepted_bytes.startswith(self.expected_bytes):
            self._finished_reading = True
            self.excess_buffer = self.accepted_bytes[len(self.expected_bytes):]

    def next_read_size(self):
        if self._finished_reading:
            return 0
        else:
            return 1


class TestSmartServerStreamMedium(tests.TestCase):

    def portable_socket_pair(self):
        """Return a pair of TCP sockets connected to each other.
        
        Unlike socket.socketpair, this should work on Windows.
        """
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.bind(('127.0.0.1', 0))
        listen_sock.listen(1)
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(listen_sock.getsockname())
        server_sock, addr = listen_sock.accept()
        listen_sock.close()
        return server_sock, client_sock
    
    def test_smart_query_version(self):
        """Feed a canned query version to a server"""
        # wire-to-wire, using the whole stack
        to_server = StringIO('hello\n')
        from_server = StringIO()
        transport = local.LocalTransport(urlutils.local_path_to_url('/'))
        server = smart.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        protocol = smart.SmartServerRequestProtocolOne(transport,
                from_server.write)
        server._serve_one_request(protocol)
        self.assertEqual('ok\0011\n',
                         from_server.getvalue())

    def test_canned_get_response(self):
        transport = memory.MemoryTransport('memory:///')
        transport.put_bytes('testfile', 'contents\nof\nfile\n')
        to_server = StringIO('get\001./testfile\n')
        from_server = StringIO()
        server = smart.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        protocol = smart.SmartServerRequestProtocolOne(transport,
                from_server.write)
        server._serve_one_request(protocol)
        self.assertEqual('ok\n'
                         '17\n'
                         'contents\nof\nfile\n'
                         'done\n',
                         from_server.getvalue())

    def test_pipe_like_stream_with_bulk_data(self):
        sample_request_bytes = 'command\n9\nbulk datadone\n'
        to_server = StringIO(sample_request_bytes)
        from_server = StringIO()
        server = smart.SmartServerPipeStreamMedium(to_server, from_server, None)
        sample_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(sample_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertEqual(sample_request_bytes, sample_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_socket_stream_with_bulk_data(self):
        sample_request_bytes = 'command\n9\nbulk datadone\n'
        server_sock, client_sock = self.portable_socket_pair()
        server = smart.SmartServerSocketStreamMedium(
            server_sock, None)
        sample_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        client_sock.sendall(sample_request_bytes)
        server._serve_one_request(sample_protocol)
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))
        self.assertEqual(sample_request_bytes, sample_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_pipe_like_stream_shutdown_detection(self):
        to_server = StringIO('')
        from_server = StringIO()
        server = smart.SmartServerPipeStreamMedium(to_server, from_server, None)
        server._serve_one_request(SampleRequest('x'))
        self.assertTrue(server.finished)
        
    def test_socket_stream_shutdown_detection(self):
        server_sock, client_sock = self.portable_socket_pair()
        client_sock.close()
        server = smart.SmartServerSocketStreamMedium(
            server_sock, None)
        server._serve_one_request(SampleRequest('x'))
        self.assertTrue(server.finished)
        
    def test_pipe_like_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received seperately.
        sample_request_bytes = 'command\n'
        to_server = StringIO(sample_request_bytes * 2)
        from_server = StringIO()
        server = smart.SmartServerPipeStreamMedium(to_server, from_server, None)
        first_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(first_protocol)
        self.assertEqual(0, first_protocol.next_read_size())
        self.assertEqual('', from_server.getvalue())
        self.assertFalse(server.finished)
        # Make a new protocol, call _serve_one_request with it to collect the
        # second request.
        second_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(second_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertEqual(sample_request_bytes, second_protocol.accepted_bytes)
        self.assertFalse(server.finished)
        
    def test_socket_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received seperately.
        sample_request_bytes = 'command\n'
        server_sock, client_sock = self.portable_socket_pair()
        server = smart.SmartServerSocketStreamMedium(
            server_sock, None)
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
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))

    def test_pipe_like_stream_error_handling(self):
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        from StringIO import StringIO
        to_server = StringIO('')
        from_server = StringIO()
        self.closed = False
        def close():
            self.closed = True
        from_server.close = close
        server = smart.SmartServerPipeStreamMedium(to_server, from_server, None)
        fake_protocol = ErrorRaisingProtocol(Exception('boom'))
        server._serve_one_request(fake_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertTrue(self.closed)
        self.assertTrue(server.finished)
        
    def test_socket_stream_error_handling(self):
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        from StringIO import StringIO
        server_sock, client_sock = self.portable_socket_pair()
        server = smart.SmartServerSocketStreamMedium(
            server_sock, None)
        fake_protocol = ErrorRaisingProtocol(Exception('boom'))
        server._serve_one_request(fake_protocol)
        # recv should not block, because the other end of the socket has been
        # closed.
        self.assertEqual('', client_sock.recv(1))
        self.assertTrue(server.finished)
        
    def test_pipe_like_stream_keyboard_interrupt_handling(self):
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        to_server = StringIO('')
        from_server = StringIO()
        server = smart.SmartServerPipeStreamMedium(to_server, from_server, None)
        fake_protocol = ErrorRaisingProtocol(KeyboardInterrupt('boom'))
        self.assertRaises(
            KeyboardInterrupt, server._serve_one_request, fake_protocol)
        self.assertEqual('', from_server.getvalue())

    def test_socket_stream_keyboard_interrupt_handling(self):
        server_sock, client_sock = self.portable_socket_pair()
        server = smart.SmartServerSocketStreamMedium(
            server_sock, None)
        fake_protocol = ErrorRaisingProtocol(KeyboardInterrupt('boom'))
        self.assertRaises(
            KeyboardInterrupt, server._serve_one_request, fake_protocol)
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))
        

class TestSmartTCPServer(tests.TestCase):

    def test_get_error_unexpected(self):
        """Error reported by server with no specific representation"""
        class FlakyTransport(object):
            def get_bytes(self, path):
                raise Exception("some random exception from inside server")
        server = smart.SmartTCPServer(backing_transport=FlakyTransport())
        server.start_background_thread()
        try:
            transport = smart.SmartTCPTransport(server.get_url())
            try:
                transport.get('something')
            except errors.TransportError, e:
                self.assertContainsRe(str(e), 'some random exception')
            else:
                self.fail("get did not raise expected error")
        finally:
            server.stop_background_thread()


class SmartTCPTests(tests.TestCase):
    """Tests for connection/end to end behaviour using the TCP server.

    All of these tests are run with a server running on another thread serving
    a MemoryTransport, and a connection to it already open.

    the server is obtained by calling self.setUpServer(readonly=False).
    """

    def setUpServer(self, readonly=False):
        """Setup the server.

        :param readonly: Create a readonly server.
        """
        self.backing_transport = memory.MemoryTransport()
        if readonly:
            self.real_backing_transport = self.backing_transport
            self.backing_transport = get_transport("readonly+" + self.backing_transport.abspath('.'))
        self.server = smart.SmartTCPServer(self.backing_transport)
        self.server.start_background_thread()
        self.transport = smart.SmartTCPTransport(self.server.get_url())

    def tearDown(self):
        if getattr(self, 'transport', None):
            self.transport.disconnect()
        if getattr(self, 'server', None):
            self.server.stop_background_thread()
        super(SmartTCPTests, self).tearDown()
        

class WritableEndToEndTests(SmartTCPTests):
    """Client to server tests that require a writable transport."""

    def setUp(self):
        super(WritableEndToEndTests, self).setUp()
        self.setUpServer()

    def test_start_tcp_server(self):
        url = self.server.get_url()
        self.assertContainsRe(url, r'^bzr://127\.0\.0\.1:[0-9]{2,}/')

    def test_smart_transport_has(self):
        """Checking for file existence over smart."""
        self.backing_transport.put_bytes("foo", "contents of foo\n")
        self.assertTrue(self.transport.has("foo"))
        self.assertFalse(self.transport.has("non-foo"))

    def test_smart_transport_get(self):
        """Read back a file over smart."""
        self.backing_transport.put_bytes("foo", "contents\nof\nfoo\n")
        fp = self.transport.get("foo")
        self.assertEqual('contents\nof\nfoo\n', fp.read())

    def test_get_error_enoent(self):
        """Error reported from server getting nonexistent file."""
        # The path in a raised NoSuchFile exception should be the precise path
        # asked for by the client. This gives meaningful and unsurprising errors
        # for users.
        try:
            self.transport.get('not%20a%20file')
        except errors.NoSuchFile, e:
            self.assertEqual('not%20a%20file', e.path)
        else:
            self.fail("get did not raise expected error")

    def test_simple_clone_conn(self):
        """Test that cloning reuses the same connection."""
        # we create a real connection not a loopback one, but it will use the
        # same server and pipes
        conn2 = self.transport.clone('.')
        self.assertIs(self.transport._medium, conn2._medium)

    def test__remote_path(self):
        self.assertEquals('/foo/bar',
                          self.transport._remote_path('foo/bar'))

    def test_clone_changes_base(self):
        """Cloning transport produces one with a new base location"""
        conn2 = self.transport.clone('subdir')
        self.assertEquals(self.transport.base + 'subdir/',
                          conn2.base)

    def test_open_dir(self):
        """Test changing directory"""
        transport = self.transport
        self.backing_transport.mkdir('toffee')
        self.backing_transport.mkdir('toffee/apple')
        self.assertEquals('/toffee', transport._remote_path('toffee'))
        toffee_trans = transport.clone('toffee')
        # Check that each transport has only the contents of its directory
        # directly visible. If state was being held in the wrong object, it's
        # conceivable that cloning a transport would alter the state of the
        # cloned-from transport.
        self.assertTrue(transport.has('toffee'))
        self.assertFalse(toffee_trans.has('toffee'))
        self.assertFalse(transport.has('apple'))
        self.assertTrue(toffee_trans.has('apple'))

    def test_open_bzrdir(self):
        """Open an existing bzrdir over smart transport"""
        transport = self.transport
        t = self.backing_transport
        bzrdir.BzrDirFormat.get_default_format().initialize_on_transport(t)
        result_dir = bzrdir.BzrDir.open_containing_from_transport(transport)


class ReadOnlyEndToEndTests(SmartTCPTests):
    """Tests from the client to the server using a readonly backing transport."""

    def test_mkdir_error_readonly(self):
        """TransportNotPossible should be preserved from the backing transport."""
        self.setUpServer(readonly=True)
        self.assertRaises(errors.TransportNotPossible, self.transport.mkdir,
            'foo')
        

class SmartServerRequestHandlerTests(tests.TestCaseWithTransport):
    """Test that call directly into the handler logic, bypassing the network."""

    def test_construct_request_handler(self):
        """Constructing a request handler should be easy and set defaults."""
        handler = smart.SmartServerRequestHandler(None)
        self.assertFalse(handler.finished_reading)

    def test_hello(self):
        handler = smart.SmartServerRequestHandler(None)
        handler.dispatch_command('hello', ())
        self.assertEqual(('ok', '1'), handler.response.args)
        self.assertEqual(None, handler.response.body)
        
    def test_get_bundle(self):
        from bzrlib.bundle import serializer
        wt = self.make_branch_and_tree('.')
        self.build_tree_contents([('hello', 'hello world')])
        wt.add('hello')
        rev_id = wt.commit('add hello')
        
        handler = smart.SmartServerRequestHandler(self.get_transport())
        handler.dispatch_command('get_bundle', ('.', rev_id))
        bundle = serializer.read_bundle(StringIO(handler.response.body))
        self.assertEqual((), handler.response.args)

    def test_readonly_exception_becomes_transport_not_possible(self):
        """The response for a read-only error is ('ReadOnlyError')."""
        handler = smart.SmartServerRequestHandler(self.get_readonly_transport())
        # send a mkdir for foo, with no explicit mode - should fail.
        handler.dispatch_command('mkdir', ('foo', ''))
        # and the failure should be an explicit ReadOnlyError
        self.assertEqual(("ReadOnlyError", ), handler.response.args)
        # XXX: TODO: test that other TransportNotPossible errors are
        # presented as TransportNotPossible - not possible to do that
        # until I figure out how to trigger that relatively cleanly via
        # the api. RBC 20060918

    def test_hello_has_finished_body_on_dispatch(self):
        """The 'hello' command should set finished_reading."""
        handler = smart.SmartServerRequestHandler(None)
        handler.dispatch_command('hello', ())
        self.assertTrue(handler.finished_reading)
        self.assertNotEqual(None, handler.response)

    def test_put_bytes_non_atomic(self):
        """'put_...' should set finished_reading after reading the bytes."""
        handler = smart.SmartServerRequestHandler(self.get_transport())
        handler.dispatch_command('put_non_atomic', ('a-file', '', 'F', ''))
        self.assertFalse(handler.finished_reading)
        handler.accept_body('1234')
        self.assertFalse(handler.finished_reading)
        handler.accept_body('5678')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('ok', ), handler.response.args)
        self.assertEqual(None, handler.response.body)
        
    def test_readv_accept_body(self):
        """'readv' should set finished_reading after reading offsets."""
        self.build_tree(['a-file'])
        handler = smart.SmartServerRequestHandler(self.get_readonly_transport())
        handler.dispatch_command('readv', ('a-file', ))
        self.assertFalse(handler.finished_reading)
        handler.accept_body('2,')
        self.assertFalse(handler.finished_reading)
        handler.accept_body('3')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('readv', ), handler.response.args)
        # co - nte - nt of a-file is the file contents we are extracting from.
        self.assertEqual('nte', handler.response.body)

    def test_readv_short_read_response_contents(self):
        """'readv' when a short read occurs sets the response appropriately."""
        self.build_tree(['a-file'])
        handler = smart.SmartServerRequestHandler(self.get_readonly_transport())
        handler.dispatch_command('readv', ('a-file', ))
        # read beyond the end of the file.
        handler.accept_body('100,1')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('ShortReadvError', 'a-file', '100', '1', '0'),
            handler.response.args)
        self.assertEqual(None, handler.response.body)


class SmartTransportRegistration(tests.TestCase):

    def test_registration(self):
        t = get_transport('bzr+ssh://example.com/path')
        self.assertIsInstance(t, smart.SmartSSHTransport)
        self.assertEqual('example.com', t._host)


class TestSmartTransport(tests.TestCase):
        
    def test_use_connection_factory(self):
        # We want to be able to pass a client as a parameter to SmartTransport.
        input = StringIO("ok\n3\nbardone\n")
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        transport = smart.SmartTransport('bzr://localhost/', medium=medium)

        # We want to make sure the client is used when the first remote
        # method is called.  No data should have been sent, or read.
        self.assertEqual(0, input.tell())
        self.assertEqual('', output.getvalue())

        # Now call a method that should result in a single request : as the
        # transport makes its own protocol instances, we check on the wire.
        # XXX: TODO: give the transport a protocol factory, which can make
        # an instrumented protocol for us.
        self.assertEqual('bar', transport.get_bytes('foo'))
        # only the needed data should have been sent/received.
        self.assertEqual(13, input.tell())
        self.assertEqual('get\x01/foo\n', output.getvalue())

    def test__translate_error_readonly(self):
        """Sending a ReadOnlyError to _translate_error raises TransportNotPossible."""
        medium = smart.SmartClientMedium()
        transport = smart.SmartTransport('bzr://localhost/', medium=medium)
        self.assertRaises(errors.TransportNotPossible,
            transport._translate_error, ("ReadOnlyError", ))


class InstrumentedServerProtocol(smart.SmartServerStreamMedium):
    """A smart server which is backed by memory and saves its write requests."""

    def __init__(self, write_output_list):
        smart.SmartServerStreamMedium.__init__(self, memory.MemoryTransport())
        self._write_output_list = write_output_list


class TestSmartProtocol(tests.TestCase):
    """Tests for the smart protocol.

    Each test case gets a smart_server and smart_client created during setUp().

    It is planned that the client can be called with self.call_client() giving
    it an expected server response, which will be fed into it when it tries to
    read. Likewise, self.call_server will call a servers method with a canned
    serialised client request. Output done by the client or server for these
    calls will be captured to self.to_server and self.to_client. Each element
    in the list is a write call from the client or server respectively.
    """

    def setUp(self):
        super(TestSmartProtocol, self).setUp()
        self.server_to_client = []
        self.to_server = StringIO()
        self.to_client = StringIO()
        self.client_medium = smart.SmartSimplePipesClientMedium(self.to_client,
            self.to_server)
        self.client_protocol = smart.SmartClientRequestProtocolOne(
            self.client_medium)
        self.smart_server = InstrumentedServerProtocol(self.server_to_client)
        self.smart_server_request = smart.SmartServerRequestHandler(None)

    def assertOffsetSerialisation(self, expected_offsets, expected_serialised,
        client, smart_server_request):
        """Check that smart (de)serialises offsets as expected.
        
        We check both serialisation and deserialisation at the same time
        to ensure that the round tripping cannot skew: both directions should
        be as expected.
        
        :param expected_offsets: a readv offset list.
        :param expected_seralised: an expected serial form of the offsets.
        :param smart_server_request: a SmartServerRequestHandler instance.
        """
        # XXX: 'smart_server_request' should be a SmartServerRequestProtocol in
        # future.
        offsets = smart_server_request._deserialise_offsets(expected_serialised)
        self.assertEqual(expected_offsets, offsets)
        serialised = client._serialise_offsets(offsets)
        self.assertEqual(expected_serialised, serialised)

    def build_protocol_waiting_for_body(self):
        out_stream = StringIO()
        protocol = smart.SmartServerRequestProtocolOne(None, out_stream.write)
        protocol.has_dispatched = True
        protocol.request = smart.SmartServerRequestHandler(None)
        def handle_end_of_bytes():
            self.end_received = True
            self.assertEqual('abcdefg', protocol.request._body_bytes)
            protocol.request.response = smart.SmartServerResponse(('ok', ))
        protocol.request._end_of_body_handler = handle_end_of_bytes
        # Call accept_bytes to make sure that internal state like _body_decoder
        # is initialised.  This test should probably be given a clearer
        # interface to work with that will not cause this inconsistency.
        #   -- Andrew Bennetts, 2006-09-28
        protocol.accept_bytes('')
        return protocol

    def test_construct_version_one_server_protocol(self):
        protocol = smart.SmartServerRequestProtocolOne(None, None)
        self.assertEqual('', protocol.excess_buffer)
        self.assertEqual('', protocol.in_buffer)
        self.assertFalse(protocol.has_dispatched)
        self.assertEqual(1, protocol.next_read_size())

    def test_construct_version_one_client_protocol(self):
        # we can construct a client protocol from a client medium request
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(None, output)
        request = medium.get_request()
        client_protocol = smart.SmartClientRequestProtocolOne(request)

    def test_server_offset_serialisation(self):
        """The Smart protocol serialises offsets as a comma and \n string.

        We check a number of boundary cases are as expected: empty, one offset,
        one with the order of reads not increasing (an out of order read), and
        one that should coalesce.
        """
        self.assertOffsetSerialisation([], '',
            self.client_protocol, self.smart_server_request)
        self.assertOffsetSerialisation([(1,2)], '1,2',
            self.client_protocol, self.smart_server_request)
        self.assertOffsetSerialisation([(10,40), (0,5)], '10,40\n0,5',
            self.client_protocol, self.smart_server_request)
        self.assertOffsetSerialisation([(1,2), (3,4), (100, 200)],
            '1,2\n3,4\n100,200', self.client_protocol, self.smart_server_request)

    def test_accept_bytes_to_protocol(self):
        out_stream = StringIO()
        protocol = smart.SmartServerRequestProtocolOne(None, out_stream.write)
        protocol.accept_bytes('abc')
        self.assertEqual('abc', protocol.in_buffer)
        protocol.accept_bytes('\n')
        self.assertEqual("error\x01Generic bzr smart protocol error: bad request"
            " u'abc'\n", out_stream.getvalue())
        self.assertTrue(protocol.has_dispatched)
        self.assertEqual(1, protocol.next_read_size())

    def test_accept_bytes_with_invalid_utf8_to_protocol(self):
        out_stream = StringIO()
        protocol = smart.SmartServerRequestProtocolOne(None, out_stream.write)
        # the byte 0xdd is not a valid UTF-8 string.
        protocol.accept_bytes('\xdd\n')
        self.assertEqual(
            "error\x01Generic bzr smart protocol error: "
            "one or more arguments of request '\\xdd\\n' are not valid UTF-8\n",
            out_stream.getvalue())
        self.assertTrue(protocol.has_dispatched)
        self.assertEqual(1, protocol.next_read_size())

    def test_accept_body_bytes_to_protocol(self):
        protocol = self.build_protocol_waiting_for_body()
        self.assertEqual(6, protocol.next_read_size())
        protocol.accept_bytes('7\nabc')
        self.assertEqual(9, protocol.next_read_size())
        protocol.accept_bytes('defgd')
        protocol.accept_bytes('one\n')
        self.assertEqual(0, protocol.next_read_size())
        self.assertTrue(self.end_received)

    def test_accept_request_and_body_all_at_once(self):
        mem_transport = memory.MemoryTransport()
        mem_transport.put_bytes('foo', 'abcdefghij')
        out_stream = StringIO()
        protocol = smart.SmartServerRequestProtocolOne(mem_transport,
                out_stream.write)
        protocol.accept_bytes('readv\x01foo\n3\n3,3done\n')
        self.assertEqual(0, protocol.next_read_size())
        self.assertEqual('readv\n3\ndefdone\n', out_stream.getvalue())
        self.assertEqual('', protocol.excess_buffer)
        self.assertEqual('', protocol.in_buffer)

    def test_accept_excess_bytes_are_preserved(self):
        out_stream = StringIO()
        protocol = smart.SmartServerRequestProtocolOne(None, out_stream.write)
        protocol.accept_bytes('hello\nhello\n')
        self.assertEqual("ok\x011\n", out_stream.getvalue())
        self.assertEqual("hello\n", protocol.excess_buffer)
        self.assertEqual("", protocol.in_buffer)

    def test_accept_excess_bytes_after_body(self):
        protocol = self.build_protocol_waiting_for_body()
        protocol.accept_bytes('7\nabcdefgdone\nX')
        self.assertTrue(self.end_received)
        self.assertEqual("X", protocol.excess_buffer)
        self.assertEqual("", protocol.in_buffer)
        protocol.accept_bytes('Y')
        self.assertEqual("XY", protocol.excess_buffer)
        self.assertEqual("", protocol.in_buffer)

    def test_accept_excess_bytes_after_dispatch(self):
        out_stream = StringIO()
        protocol = smart.SmartServerRequestProtocolOne(None, out_stream.write)
        protocol.accept_bytes('hello\n')
        self.assertEqual("ok\x011\n", out_stream.getvalue())
        protocol.accept_bytes('hel')
        self.assertEqual("hel", protocol.excess_buffer)
        protocol.accept_bytes('lo\n')
        self.assertEqual("hello\n", protocol.excess_buffer)
        self.assertEqual("", protocol.in_buffer)

    def test_sync_with_request_sets_finished_reading(self):
        protocol = smart.SmartServerRequestProtocolOne(None, None)
        request = smart.SmartServerRequestHandler(None)
        protocol.sync_with_request(request)
        self.assertEqual(1, protocol.next_read_size())
        request.finished_reading = True
        protocol.sync_with_request(request)
        self.assertEqual(0, protocol.next_read_size())

    def test_query_version(self):
        """query_version on a SmartClientProtocolOne should return a number.
        
        The protocol provides the query_version because the domain level clients
        may all need to be able to probe for capabilities.
        """
        # What we really want to test here is that SmartClientProtocolOne calls
        # accept_bytes(tuple_based_encoding_of_hello) and reads and parses the
        # response of tuple-encoded (ok, 1).  Also, seperately we should test
        # the error if the response is a non-understood version.
        input = StringIO('ok\x011\n')
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        protocol = smart.SmartClientRequestProtocolOne(medium.get_request())
        self.assertEqual(1, protocol.query_version())

    def assertServerToClientEncoding(self, expected_bytes, expected_tuple,
            input_tuples):
        """Assert that each input_tuple serialises as expected_bytes, and the
        bytes deserialise as expected_tuple.
        """
        # check the encoding of the server for all input_tuples matches
        # expected bytes
        for input_tuple in input_tuples:
            server_output = StringIO()
            server_protocol = smart.SmartServerRequestProtocolOne(
                None, server_output.write)
            server_protocol._send_response(input_tuple)
            self.assertEqual(expected_bytes, server_output.getvalue())
        # check the decoding of the client protocol from expected_bytes:
        input = StringIO(expected_bytes)
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        protocol = smart.SmartClientRequestProtocolOne(medium.get_request())
        protocol.call('foo')
        self.assertEqual(expected_tuple, protocol.read_response_tuple())

    def test_client_call_empty_response(self):
        # protocol.call() can get back an empty tuple as a response. This occurs
        # when the parsed line is an empty line, and results in a tuple with
        # one element - an empty string.
        self.assertServerToClientEncoding('\n', ('', ), [(), ('', )])

    def test_client_call_three_element_response(self):
        # protocol.call() can get back tuples of other lengths. A three element
        # tuple should be unpacked as three strings.
        self.assertServerToClientEncoding('a\x01b\x0134\n', ('a', 'b', '34'),
            [('a', 'b', '34')])

    def test_client_call_with_body_bytes_uploads(self):
        # protocol.call_with_upload should length-prefix the bytes onto the 
        # wire.
        expected_bytes = "foo\n7\nabcdefgdone\n"
        input = StringIO("\n")
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        protocol = smart.SmartClientRequestProtocolOne(medium.get_request())
        protocol.call_with_body_bytes(('foo', ), "abcdefg")
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_call_with_body_readv_array(self):
        # protocol.call_with_upload should encode the readv array and then
        # length-prefix the bytes onto the wire.
        expected_bytes = "foo\n7\n1,2\n5,6done\n"
        input = StringIO("\n")
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        protocol = smart.SmartClientRequestProtocolOne(medium.get_request())
        protocol.call_with_body_readv_array(('foo', ), [(1,2),(5,6)])
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_read_body_bytes_all(self):
        # read_body_bytes should decode the body bytes from the wire into
        # a response.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        protocol = smart.SmartClientRequestProtocolOne(medium.get_request())
        protocol.call('foo')
        protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes, protocol.read_body_bytes())

    def test_client_read_body_bytes_incremental(self):
        # test reading a few bytes at a time from the body
        # XXX: possibly we should test dribbling the bytes into the stringio
        # to make the state machine work harder: however, as we use the
        # LengthPrefixedBodyDecoder that is already well tested - we can skip
        # that.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        protocol = smart.SmartClientRequestProtocolOne(medium.get_request())
        protocol.call('foo')
        protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes[0:2], protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[2:4], protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[4:6], protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[6], protocol.read_body_bytes())

    def test_client_cancel_read_body_does_not_eat_body_bytes(self):
        # cancelling the expected body needs to finish the request, but not
        # read any more bytes.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        medium = smart.SmartSimplePipesClientMedium(input, output)
        protocol = smart.SmartClientRequestProtocolOne(medium.get_request())
        protocol.call('foo')
        protocol.read_response_tuple(True)
        protocol.cancel_read_body()
        self.assertEqual(3, input.tell())
        self.assertRaises(errors.ReadingCompleted, protocol.read_body_bytes)


class LengthPrefixedBodyDecoder(tests.TestCase):

    # XXX: TODO: make accept_reading_trailer invoke translate_response or 
    # something similar to the ProtocolBase method.

    def test_construct(self):
        decoder = smart.LengthPrefixedBodyDecoder()
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)

    def test_accept_bytes(self):
        decoder = smart.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('7')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('\na')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(11, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('bcdefgd')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(4, decoder.next_read_size())
        self.assertEqual('bcdefg', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('one')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('\nblarg')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('blarg', decoder.unused_data)
        
    def test_accept_bytes_all_at_once_with_excess(self):
        decoder = smart.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('1\nadone\nunused')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('unused', decoder.unused_data)

    def test_accept_bytes_exact_end_of_body(self):
        decoder = smart.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('1\na')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(5, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('done\n')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)


class FakeHTTPMedium(object):
    def __init__(self):
        self.written_request = None
        self._current_request = None
    def send_http_smart_request(self, bytes):
        self.written_request = bytes
        return None


class HTTPTunnellingSmokeTest(tests.TestCaseWithTransport):
    
    def _test_bulk_data(self, url_protocol):
        # We should be able to send and receive bulk data in a single message.
        # The 'readv' command in the smart protocol both sends and receives bulk
        # data, so we use that.
        self.build_tree(['data-file'])
        http_server = HTTPServerWithSmarts()
        http_server._url_protocol = url_protocol
        http_server.setUp()
        self.addCleanup(http_server.tearDown)

        http_transport = get_transport(http_server.get_url())

        medium = http_transport.get_smart_medium()
        #remote_transport = RemoteTransport('fake_url', medium)
        remote_transport = smart.SmartTransport('/', medium=medium)
        self.assertEqual(
            [(0, "c")], list(remote_transport.readv("data-file", [(0,1)])))

    def test_bulk_data_pycurl(self):
        try:
            self._test_bulk_data('http+pycurl')
        except errors.UnsupportedProtocol, e:
            raise tests.TestSkipped(str(e))
    
    def test_bulk_data_urllib(self):
        self._test_bulk_data('http+urllib')

    def test_smart_http_medium_request_accept_bytes(self):
        medium = FakeHTTPMedium()
        request = SmartClientHTTPMediumRequest(medium)
        request.accept_bytes('abc')
        request.accept_bytes('def')
        self.assertEqual(None, medium.written_request)
        request.finished_writing()
        self.assertEqual('abcdef', medium.written_request)

    def _test_http_send_smart_request(self, url_protocol):
        http_server = HTTPServerWithSmarts()
        http_server._url_protocol = url_protocol
        http_server.setUp()
        self.addCleanup(http_server.tearDown)

        post_body = 'hello\n'
        expected_reply_body = 'ok\x011\n'

        http_transport = get_transport(http_server.get_url())
        medium = http_transport.get_smart_medium()
        response = medium.send_http_smart_request(post_body)
        reply_body = response.read()
        self.assertEqual(expected_reply_body, reply_body)

    def test_http_send_smart_request_pycurl(self):
        try:
            self._test_http_send_smart_request('http+pycurl')
        except errors.UnsupportedProtocol, e:
            raise tests.TestSkipped(str(e))

    def test_http_send_smart_request_urllib(self):
        self._test_http_send_smart_request('http+urllib')

    def test_http_server_with_smarts(self):
        http_server = HTTPServerWithSmarts()
        http_server.setUp()
        self.addCleanup(http_server.tearDown)

        post_body = 'hello\n'
        expected_reply_body = 'ok\x011\n'

        smart_server_url = http_server.get_url() + '.bzr/smart'
        reply = urllib2.urlopen(smart_server_url, post_body).read()

        self.assertEqual(expected_reply_body, reply)

    def test_smart_http_server_post_request_handler(self):
        http_server = HTTPServerWithSmarts()
        http_server.setUp()
        self.addCleanup(http_server.tearDown)
        httpd = http_server._get_httpd()

        socket = SampleSocket(
            'POST /.bzr/smart HTTP/1.0\r\n'
            # HTTP/1.0 posts must have a Content-Length.
            'Content-Length: 6\r\n'
            '\r\n'
            'hello\n')
        request_handler = SmartRequestHandler(
            socket, ('localhost', 80), httpd)
        response = socket.writefile.getvalue()
        self.assertStartsWith(response, 'HTTP/1.0 200 ')
        # This includes the end of the HTTP headers, and all the body.
        expected_end_of_response = '\r\n\r\nok\x011\n'
        self.assertEndsWith(response, expected_end_of_response)


class SampleSocket(object):
    """A socket-like object for use in testing the HTTP request handler."""
    
    def __init__(self, socket_read_content):
        """Constructs a sample socket.

        :param socket_read_content: a byte sequence
        """
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        from StringIO import StringIO
        self.readfile = StringIO(socket_read_content)
        self.writefile = StringIO()
        self.writefile.close = lambda: None
        
    def makefile(self, mode='r', bufsize=None):
        if 'r' in mode:
            return self.readfile
        else:
            return self.writefile

        
# TODO: Client feature that does get_bundle and then installs that into a
# branch; this can be used in place of the regular pull/fetch operation when
# coming from a smart server.
#
# TODO: Eventually, want to do a 'branch' command by fetching the whole
# history as one big bundle.  How?  
#
# The branch command does 'br_from.sprout', which tries to preserve the same
# format.  We don't necessarily even want that.  
#
# It might be simpler to handle cmd_pull first, which does a simpler fetch()
# operation from one branch into another.  It already has some code for
# pulling from a bundle, which it does by trying to see if the destination is
# a bundle file.  So it seems the logic for pull ought to be:
# 
#  - if it's a smart server, get a bundle from there and install that
#  - if it's a bundle, install that
#  - if it's a branch, pull from there
#
# Getting a bundle from a smart server is a bit different from reading a
# bundle from a URL:
#
#  - we can reasonably remember the URL we last read from 
#  - you can specify a revision number to pull, and we need to pass it across
#    to the server as a limit on what will be requested
#
# TODO: Given a URL, determine whether it is a smart server or not (or perhaps
# otherwise whether it's a bundle?)  Should this be a property or method of
# the transport?  For the ssh protocol, we always know it's a smart server.
# For http, we potentially need to probe.  But if we're explicitly given
# bzr+http:// then we can skip that for now. 
