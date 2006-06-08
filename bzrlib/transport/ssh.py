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
followed by bulk body data.
"""

# The plan is that the SSHTransport will hold an SSHConnection.  It will use
# this to map Transport operations into low-level RPCs; it will also allow its
# clients to ask for an RPC interface.


# TODO: A plain integer from query_version is too simple; should give some
# capabilities too?

# TODO: Server needs an event loop that calls _serve_one_request 
# repeatedly.

# TODO: Server should probably catch exceptions within itself and send them
# back across the network.  (But shouldn't catch KeyboardInterrupt etc)
# Also needs to somehow report protocol errors like bad requests.  Need to
# consider how we'll handle error reporting, e.g. if we get halfway through a
# bulk transfer and then something goes wrong.

# TODO: Standard marker at start of request/response lines?

# TODO: Client and server warnings perhaps should contain some non-ascii bytes
# to make sure the channel can carry them without trouble?  Test for this?


import os

from bzrlib import errors


class BzrProtocolError(errors.TransportError):
    pass



class Server(object):
    """Handles bzr ssh commands over input/output pipes.

    In the real world the pipes will be stdin/stdout for a process 
    run from sshd.
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
        self._send_response(('bzr server', '1'))

    def _do_has(self, relpath):
        r = self._backing_transport.has(relpath) and 'yes' or 'no'
        self._send_response((r,))

    def serve(self):
        """Serve requests until the client disconnects."""
        while self._serve_one_request() != False:
            pass
        
    def _serve_one_request(self):
        """Read one request from input, process, send back a response.
        
        :return: False if the server should terminate, otherwise None.
        """
        req_args = self._read_request()
        if req_args == None:
            # client closed connection
            return False
        elif req_args == ('hello', '1'):
            self._do_query_version()
        elif req_args[0] == 'has':
            self._do_has(req_args[1])
        else:
            raise BzrProtocolError("bad request %r" % (req_args,))

    def _read_request(self):
        """Read a request from the client and return as a tuple.
        
        Returns None at end of file (if the client closed the connection.)
        """
        req_line = self._in.readline()
        if req_line == None or req_line == '':
            return None
        if req_line[-1] != '\n':
            raise BzrProtocolError("request %r not terminated" % req_line)
        return tuple(req_line[:-1].split('\1'))

    def _send_response(self, args):
        self._out.write('\1'.join(args) + '\n')


class SSHConnection(object):
    """Connection to a bzr ssh server.
    
    This supports some higher-level RPC operations and can also be treated 
    like a Transport to do file-like operations.
    """
    
    def query_version(self):
        """Return protocol version number of the server."""
        # XXX: should make sure it's empty
        self._send_to_server('hello\0011\n')
        resp = self._readline_from_server()
        if resp == 'bzr server\0011\n':
            return 1
        else:
            raise BzrProtocolError("bad response %r" % (resp,))
        
    def has(self, relpath):
        self._send_to_server('has\1%s\n' % relpath)
        resp = self._readline_from_server()
        if resp == 'yes\n':
            return True
        elif resp == 'no\n':
            return False
        else:
            raise BzrProtocolError("bad response not handled")

    def _send_to_server(self, message):
        self._to_server.write(message)

    def _readline_from_server(self):
        return self._from_server.readline()

    def disconnect(self):
        self._to_server.close()
        self._from_server.close()


class LoopbackSSHConnection(SSHConnection):
    """This replaces the "ssh->network->sshd" pipe in a typical network.

    It just connects together the ssh client and server, and creates
    a server for us just like running ssh will.

    The difference between this and a real SSHConnection is that the latter
    really runs /usr/bin/ssh and we don't.  Instead we start a new thread 
    running the server, connected by a pair of fifos.

    :ivar backing_transport: The transport used by the real server.
    """

    def __init__(self):
        from bzrlib.transport import memory
        self.backing_transport = memory.MemoryTransport('memory:///')
        self._start_server()

    def _start_server(self):
        import threading
        from_client_fd, to_server_fd = os.pipe()
        from_server_fd, to_client_fd = os.pipe()
        LINE_BUFFERED = 1
        self._to_server = os.fdopen(to_server_fd, 'wb', LINE_BUFFERED)
        self._from_server = os.fdopen(from_server_fd, 'rb', LINE_BUFFERED)
        self._server = Server(os.fdopen(from_client_fd, 'rb', LINE_BUFFERED),
                              os.fdopen(to_client_fd, 'wb', LINE_BUFFERED),
                              self.backing_transport)
        self._server_thread = threading.Thread(None,
                self._server.serve,
                name='loopback-bzr-server-%x' % id(self._server))
        self._server_thread.start()
