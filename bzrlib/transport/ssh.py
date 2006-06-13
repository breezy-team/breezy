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

"""Transport carried over SSH

Requests are sent as a command and list of arguments, followed by optional
bulk body data.  Responses are similarly a response and list of arguments,
followed by bulk body data. ::

  SEP := '\001'
    Fields are separated by Ctrl-A.
  BULK_DATA := CHUNK+ TRAILER
    Chunks can be repeated as many times as necessary.
  CHUNK := CHUNK_LEN CHUNK_BODY
  CHUNK_LEN := DIGIT+ NEWLINE
    Gives the number of bytes in the following chunk.
  CHUNK_BODY := BYTE[chunk_len]
  TRAILER := SUCCESS_TRAILER | ERROR_TRAILER
  SUCCESS_TRAILER := 'done' NEWLINE
  ERROR_TRAILER := 

"""

# The plan is that the SSHTransport will hold an SSHConnection.  It will use
# this to map Transport operations into low-level RPCs; it will also allow its
# clients to ask for an RPC interface.


# TODO: A plain integer from query_version is too simple; should give some
# capabilities too?

# TODO: Server should probably catch exceptions within itself and send them
# back across the network.  (But shouldn't catch KeyboardInterrupt etc)
# Also needs to somehow report protocol errors like bad requests.  Need to
# consider how we'll handle error reporting, e.g. if we get halfway through a
# bulk transfer and then something goes wrong.

# TODO: Standard marker at start of request/response lines?

# TODO: Client and server warnings perhaps should contain some non-ascii bytes
# to make sure the channel can carry them without trouble?  Test for this?
#
# TODO: get/put objects could be changed to gradually read back the data as it
# comes across the network
#
# TODO: What should the server do if it hits an error and has to terminate?
#
# TODO: is it useful to allow multiple chunks in the bulk data?
#
# TODO: If we get an exception during transmission of bulk data we can't just
# emit the exception because it won't be seen.
#
# TODO: Clone method on Transport; should work up towards parent directory;
# unclear how this should be stored or communicated to the server... maybe
# just pass it on all relevant requests?
#
# TODO: Better name than clone() for changing between directories.  How about
# open_dir or change_dir or chdir?
#
# TODO: Is it really good to have the notion of current directory within the
# connection?  Perhaps all Transports should factor out a common connection
# from the thing that has the directory context?
#
# TODO: Pull more things common to sftp and ssh to a higher level.
#
# TODO: The server that manages a connection should be quite small and retain
# minimum state because each of the requests are supposed to be stateless.
# Then we can write another implementation that maps to http.
#
# TODO: What to do when a client connection is garbage collected?  Maybe just
# abruptly drop the connection?


from cStringIO import StringIO
import errno
import os
import socket
import sys
import threading

from bzrlib import errors, transport
from bzrlib.transport import sftp


# must do this otherwise we can't parse the urls properly
for scheme in ['ssh', 'bzr', 'ssh+loopback']:
    transport.register_urlparse_netloc_protocol(scheme)
del scheme


class BzrProtocolError(errors.TransportError):
    pass


def _recv_tuple(from_file):
    req_line = from_file.readline()
    if req_line == None or req_line == '':
        return None
    if req_line[-1] != '\n':
        raise BzrProtocolError("request %r not terminated" % req_line)
    return tuple((a.decode('utf-8') for a in req_line[:-1].split('\1')))


def _send_tuple(to_file, args):
    to_file.write('\1'.join((a.encode('utf-8') for a in args)) + '\n')


def _recv_bulk(from_file):
    chunk_len = from_file.readline()
    try:
        chunk_len = int(chunk_len)
    except ValueError:
        raise BzrProtocolError("bad chunk length line %r" % chunk_len)
    bulk = from_file.read(chunk_len)
    if len(bulk) != chunk_len:
        raise BzrProtocolError("short read fetching bulk data chunk")
    return bulk


class SoukStreamServer(object):
    """Handles souk commands coming over a stream.

    The stream may be a pipe connected to sshd, or a tcp socket, or an
    in-process fifo for testing.

    One instance is created for each connected client; it can serve multiple
    requests in the lifetime of the connection.

    The server passes requests through to an underlying backing transport, 
    which will typically be a LocalTransport looking at the server's filesystem.
    """

    def __init__(self, in_file, out_file, backing_transport):
        """Construct new server.

        :param in_file: Python file from which requests can be read.
        :param out_file: Python file to write responses.
        :param backing_transport: Transport for the directory served.
        """
        self._in = in_file
        self._out = out_file
        self._backing_transport = backing_transport

    def _do_query_version(self):
        """Answer a version request with my version."""
        self._send_tuple(('bzr server', '1'))

    def _do_has(self, relpath):
        r = self._backing_transport.has(relpath) and 'yes' or 'no'
        self._send_tuple((r,))

    def _do_get(self, relpath):
        backing_file = self._backing_transport.get(relpath)
        self._send_tuple(('ok', ))
        self._send_bulk_data(backing_file.read())

    def serve(self):
        """Serve requests until the client disconnects."""
        try:
            while self._serve_one_request() != False:
                pass
        except Exception, e:
            self._report_error("%s terminating on exception %s" % (self, e))
            raise

    def _report_error(self, msg):
        sys.stderr.write(msg + '\n')
        
    def _serve_one_request(self):
        """Read one request from input, process, send back a response.
        
        :return: False if the server should terminate, otherwise None.
        """
        req_args = self._recv_tuple()
        if req_args == None:
            # client closed connection
            return False  # shutdown server
        try:
            self._dispatch_command(req_args[0], req_args[1:])
        except errors.NoSuchFile, e:
            self._send_tuple(('enoent', e.path))
        except KeyboardInterrupt:
            raise
        except Exception, e:
            # everything else: pass to client, flush, and quit
            self._send_error_and_disconnect(e)
            return False

    def _send_error_and_disconnect(self, exception):
        self._send_tuple(('error', str(exception)))
        self._out.flush()
        self._out.close()
        self._in.close()

    def _dispatch_command(self, cmd, args):
        if cmd == 'hello':
            self._do_query_version()
        elif cmd == 'has':
            self._do_has(*args)
        elif cmd == 'get':
            self._do_get(*args)
        else:
            raise BzrProtocolError("bad request %r" % (cmd,))

    def _recv_tuple(self):
        """Read a request from the client and return as a tuple.
        
        Returns None at end of file (if the client closed the connection.)
        """
        return _recv_tuple(self._in)

    def _send_tuple(self, args):
        """Send response header"""
        return _send_tuple(self._out, args)

    def _send_bulk_data(self, body):
        """Send chunked body data"""
        assert isinstance(body, str)
        self._out.write('%d\n' % len(body))
        self._out.write(body)
        self._out.write('done\n')


class SoukTCPServer(object):
    """Listens on a TCP socket and accepts connections from souk clients"""

    def __init__(self, backing_transport):
        self._server_socket = socket.socket()
        self._server_socket.bind(('127.0.0.1', 0))
        self._server_socket.listen(1)
        self.backing_transport = backing_transport

    def serve_until_stopped(self):
        # let connections timeout so that we get a chance to terminate
        self._server_socket.settimeout(0.1)
        while not self._should_terminate:
            try:
                self.accept_and_serve()
            except socket.timeout:
                pass

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%d/" % self._server_socket.getsockname()

    def accept_and_serve(self):
        conn, client_addr = self._server_socket.accept()
        from_client = conn.makefile('r', 1)
        to_client = conn.makefile('w', 1)
        handler = SoukStreamServer(from_client, to_client,
                self.backing_transport)
        handler.serve()

    def start_background_thread(self):
        self._should_terminate = False
        self._server_thread = threading.Thread(None,
                self.serve_until_stopped,
                name='server-' + self.get_url())
        self._server_thread.start()

    def stop_background_thread(self):
        self._should_terminate = True
        self._server_thread.join()


class SSHConnection(sftp.SFTPUrlHandling):
    """Connection to a bzr ssh server.

    The connection holds references to pipes that can be used to send requests
    to the server.

    The connection has a notion of the current directory to which it's
    connected; this is incorporated in filenames passed to the server.
    
    This supports some higher-level RPC operations and can also be treated 
    like a Transport to do file-like operations.
    """

    def __init__(self, server_url, clone_from=None):
        super(SSHConnection, self).__init__(server_url)
        if clone_from is None:
            self._connect_to_server()
        else:
            # reuse same connection
            self._to_server = clone_from._to_server
            self._from_server = clone_from._from_server

    def clone(self, relative_url):
        """Make a new SSHConnection related to me, sharing the same connection.

        This essentially opens a handle on a different remote directory.
        """
        return SSHConnection(self.abspath(relative_url), self)
    
    def query_version(self):
        """Return protocol version number of the server."""
        # XXX: should make sure it's empty
        self._send_tuple(('hello', '1'))
        resp = self._recv_tuple()
        if resp == ('bzr server', '1'):
            return 1
        else:
            raise BzrProtocolError("bad response %r" % (resp,))
        
    def has(self, relpath):
        resp = self._call('has', self._remote_path(relpath))
        if resp == ('yes', ):
            return True
        elif resp == ('no', ):
            return False
        else:
            self._translate_error(resp)

    def get(self, relpath):
        """Return file-like object reading the contents of a remote file."""
        resp = self._call('get', self._remote_path(relpath))
        if resp != ('ok', ):
            self._translate_error(resp)
        body = self._recv_bulk()
        self._recv_trailer()
        return StringIO(body)

    def _recv_trailer(self):
        resp = self._recv_tuple()
        if resp == ('done', ):
            return
        else:
            self._translate_error(resp)

    def _call(self, *args):
        self._send_tuple(args)
        return self._recv_tuple()

    def _translate_error(self, resp):
        """Raise an exception from a response"""
        what = resp[0]
        if what == 'enoent':
            raise errors.NoSuchFile(resp[1])
        else:
            raise BzrProtocolError('bad trailer on get: %r' % (resp,))

    def _recv_bulk(self):
        return _recv_bulk(self._from_server)

    def _send_tuple(self, args):
        _send_tuple(self._to_server, args)

    def _recv_tuple(self):
        return _recv_tuple(self._from_server)

    def disconnect(self):
        self._to_server.close()
        self._from_server.close()


class SoukTCPClient(SSHConnection):
    """Connection to smart server over plain tcp"""

    def __init__(self, url):
        super(SoukTCPClient, self).__init__(url)
        self._scheme, self._username, self._password, self._host, self._port, self._path = \
                transport.split_url(url)

    def _connect_to_server(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.connect((self._host, self._port))
        LINE_BUFFERED = 1
        # TODO: May be more efficient to just treat them as sockets
        # throughout?  But what about pipes to ssh?...
        self._to_server = self._socket.makefile('w', LINE_BUFFERED)
        self._from_server = self._socket.makefile('r')

    def close(self):
        self._to_server.close()
        self._from_server.close()
        self._socket.close()


class LoopbackSSHConnection(SSHConnection):
    """This replaces the "ssh->network->sshd" pipe in a typical network.

    It just connects together the ssh client and server, and creates
    a server for us just like running ssh will.

    The difference between this and a real SSHConnection is that the latter
    really runs /usr/bin/ssh and we don't.  Instead we start a new thread 
    running the server, connected by a pair of fifos.

    :ivar backing_transport: The transport used by the real server.
    """

    def __init__(self, backing_transport=None):
        if backing_transport is None:
            from bzrlib.transport import memory
            backing_transport = memory.MemoryTransport('memory:///')
        self.backing_transport = backing_transport
        super(LoopbackSSHConnection, self).__init__('ssh+loopback://localhost/')

    def _connect_to_server(self):
        import threading
        from_client_fd, to_server_fd = os.pipe()
        from_server_fd, to_client_fd = os.pipe()
        LINE_BUFFERED = 1
        self._to_server = os.fdopen(to_server_fd, 'wb', LINE_BUFFERED)
        self._from_server = os.fdopen(from_server_fd, 'rb', LINE_BUFFERED)
        self._server = SoukStreamServer(os.fdopen(from_client_fd, 'rb', LINE_BUFFERED),
                                        os.fdopen(to_client_fd, 'wb', LINE_BUFFERED),
                                        self.backing_transport)
        self._server_thread = threading.Thread(None,
                self._server.serve,
                name='loopback-bzr-server-%x' % id(self._server))
        self._server_thread.start()
