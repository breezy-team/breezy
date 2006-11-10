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

import os
import socket

from bzrlib import errors
from bzrlib.transport.smart import protocol
try:
    from bzrlib.transport import ssh
except errors.ParamikoNotPresent:
    # no paramiko.  SmartSSHClientMedium will break.
    pass


class SmartServerStreamMedium(object):
    """Handles smart commands coming over a stream.

    The stream may be a pipe connected to sshd, or a tcp socket, or an
    in-process fifo for testing.

    One instance is created for each connected client; it can serve multiple
    requests in the lifetime of the connection.

    The server passes requests through to an underlying backing transport, 
    which will typically be a LocalTransport looking at the server's filesystem.
    """

    def __init__(self, backing_transport):
        """Construct new server.

        :param backing_transport: Transport for the directory served.
        """
        # backing_transport could be passed to serve instead of __init__
        self.backing_transport = backing_transport
        self.finished = False

    def serve(self):
        """Serve requests until the client disconnects."""
        # Keep a reference to stderr because the sys module's globals get set to
        # None during interpreter shutdown.
        from sys import stderr
        try:
            while not self.finished:
                server_protocol = protocol.SmartServerRequestProtocolOne(
                    self.backing_transport, self._write_out)
                self._serve_one_request(server_protocol)
        except Exception, e:
            stderr.write("%s terminating on exception %s\n" % (self, e))
            raise

    def _serve_one_request(self, protocol):
        """Read one request from input, process, send back a response.
        
        :param protocol: a SmartServerRequestProtocol.
        """
        try:
            self._serve_one_request_unguarded(protocol)
        except KeyboardInterrupt:
            raise
        except Exception, e:
            self.terminate_due_to_error()

    def terminate_due_to_error(self):
        """Called when an unhandled exception from the protocol occurs."""
        raise NotImplementedError(self.terminate_due_to_error)


class SmartServerSocketStreamMedium(SmartServerStreamMedium):

    def __init__(self, sock, backing_transport):
        """Constructor.

        :param sock: the socket the server will read from.  It will be put
            into blocking mode.
        """
        SmartServerStreamMedium.__init__(self, backing_transport)
        self.push_back = ''
        sock.setblocking(True)
        self.socket = sock

    def _serve_one_request_unguarded(self, protocol):
        while protocol.next_read_size():
            if self.push_back:
                protocol.accept_bytes(self.push_back)
                self.push_back = ''
            else:
                bytes = self.socket.recv(4096)
                if bytes == '':
                    self.finished = True
                    return
                protocol.accept_bytes(bytes)
        
        self.push_back = protocol.excess_buffer
    
    def terminate_due_to_error(self):
        """Called when an unhandled exception from the protocol occurs."""
        # TODO: This should log to a server log file, but no such thing
        # exists yet.  Andrew Bennetts 2006-09-29.
        self.socket.close()
        self.finished = True

    def _write_out(self, bytes):
        self.socket.sendall(bytes)


class SmartServerPipeStreamMedium(SmartServerStreamMedium):

    def __init__(self, in_file, out_file, backing_transport):
        """Construct new server.

        :param in_file: Python file from which requests can be read.
        :param out_file: Python file to write responses.
        :param backing_transport: Transport for the directory served.
        """
        SmartServerStreamMedium.__init__(self, backing_transport)
        self._in = in_file
        self._out = out_file

    def _serve_one_request_unguarded(self, protocol):
        while True:
            bytes_to_read = protocol.next_read_size()
            if bytes_to_read == 0:
                # Finished serving this request.
                self._out.flush()
                return
            bytes = self._in.read(bytes_to_read)
            if bytes == '':
                # Connection has been closed.
                self.finished = True
                self._out.flush()
                return
            protocol.accept_bytes(bytes)

    def terminate_due_to_error(self):
        # TODO: This should log to a server log file, but no such thing
        # exists yet.  Andrew Bennetts 2006-09-29.
        self._out.close()
        self.finished = True

    def _write_out(self, bytes):
        self._out.write(bytes)


class SmartClientMediumRequest(object):
    """A request on a SmartClientMedium.

    Each request allows bytes to be provided to it via accept_bytes, and then
    the response bytes to be read via read_bytes.

    For instance:
    request.accept_bytes('123')
    request.finished_writing()
    result = request.read_bytes(3)
    request.finished_reading()

    It is up to the individual SmartClientMedium whether multiple concurrent
    requests can exist. See SmartClientMedium.get_request to obtain instances 
    of SmartClientMediumRequest, and the concrete Medium you are using for 
    details on concurrency and pipelining.
    """

    def __init__(self, medium):
        """Construct a SmartClientMediumRequest for the medium medium."""
        self._medium = medium
        # we track state by constants - we may want to use the same
        # pattern as BodyReader if it gets more complex.
        # valid states are: "writing", "reading", "done"
        self._state = "writing"

    def accept_bytes(self, bytes):
        """Accept bytes for inclusion in this request.

        This method may not be be called after finished_writing() has been
        called.  It depends upon the Medium whether or not the bytes will be
        immediately transmitted. Message based Mediums will tend to buffer the
        bytes until finished_writing() is called.

        :param bytes: A bytestring.
        """
        if self._state != "writing":
            raise errors.WritingCompleted(self)
        self._accept_bytes(bytes)

    def _accept_bytes(self, bytes):
        """Helper for accept_bytes.

        Accept_bytes checks the state of the request to determing if bytes
        should be accepted. After that it hands off to _accept_bytes to do the
        actual acceptance.
        """
        raise NotImplementedError(self._accept_bytes)

    def finished_reading(self):
        """Inform the request that all desired data has been read.

        This will remove the request from the pipeline for its medium (if the
        medium supports pipelining) and any further calls to methods on the
        request will raise ReadingCompleted.
        """
        if self._state == "writing":
            raise errors.WritingNotComplete(self)
        if self._state != "reading":
            raise errors.ReadingCompleted(self)
        self._state = "done"
        self._finished_reading()

    def _finished_reading(self):
        """Helper for finished_reading.

        finished_reading checks the state of the request to determine if 
        finished_reading is allowed, and if it is hands off to _finished_reading
        to perform the action.
        """
        raise NotImplementedError(self._finished_reading)

    def finished_writing(self):
        """Finish the writing phase of this request.

        This will flush all pending data for this request along the medium.
        After calling finished_writing, you may not call accept_bytes anymore.
        """
        if self._state != "writing":
            raise errors.WritingCompleted(self)
        self._state = "reading"
        self._finished_writing()

    def _finished_writing(self):
        """Helper for finished_writing.

        finished_writing checks the state of the request to determine if 
        finished_writing is allowed, and if it is hands off to _finished_writing
        to perform the action.
        """
        raise NotImplementedError(self._finished_writing)

    def read_bytes(self, count):
        """Read bytes from this requests response.

        This method will block and wait for count bytes to be read. It may not
        be invoked until finished_writing() has been called - this is to ensure
        a message-based approach to requests, for compatability with message
        based mediums like HTTP.
        """
        if self._state == "writing":
            raise errors.WritingNotComplete(self)
        if self._state != "reading":
            raise errors.ReadingCompleted(self)
        return self._read_bytes(count)

    def _read_bytes(self, count):
        """Helper for read_bytes.

        read_bytes checks the state of the request to determing if bytes
        should be read. After that it hands off to _read_bytes to do the
        actual read.
        """
        raise NotImplementedError(self._read_bytes)


class SmartClientMedium(object):
    """Smart client is a medium for sending smart protocol requests over."""

    def disconnect(self):
        """If this medium maintains a persistent connection, close it.
        
        The default implementation does nothing.
        """
        

class SmartClientStreamMedium(SmartClientMedium):
    """Stream based medium common class.

    SmartClientStreamMediums operate on a stream. All subclasses use a common
    SmartClientStreamMediumRequest for their requests, and should implement
    _accept_bytes and _read_bytes to allow the request objects to send and
    receive bytes.
    """

    def __init__(self):
        self._current_request = None

    def accept_bytes(self, bytes):
        self._accept_bytes(bytes)

    def __del__(self):
        """The SmartClientStreamMedium knows how to close the stream when it is
        finished with it.
        """
        self.disconnect()

    def _flush(self):
        """Flush the output stream.
        
        This method is used by the SmartClientStreamMediumRequest to ensure that
        all data for a request is sent, to avoid long timeouts or deadlocks.
        """
        raise NotImplementedError(self._flush)

    def get_request(self):
        """See SmartClientMedium.get_request().

        SmartClientStreamMedium always returns a SmartClientStreamMediumRequest
        for get_request.
        """
        return SmartClientStreamMediumRequest(self)

    def read_bytes(self, count):
        return self._read_bytes(count)


class SmartSimplePipesClientMedium(SmartClientStreamMedium):
    """A client medium using simple pipes.
    
    This client does not manage the pipes: it assumes they will always be open.
    """

    def __init__(self, readable_pipe, writeable_pipe):
        SmartClientStreamMedium.__init__(self)
        self._readable_pipe = readable_pipe
        self._writeable_pipe = writeable_pipe

    def _accept_bytes(self, bytes):
        """See SmartClientStreamMedium.accept_bytes."""
        self._writeable_pipe.write(bytes)

    def _flush(self):
        """See SmartClientStreamMedium._flush()."""
        self._writeable_pipe.flush()

    def _read_bytes(self, count):
        """See SmartClientStreamMedium._read_bytes."""
        return self._readable_pipe.read(count)


class SmartSSHClientMedium(SmartClientStreamMedium):
    """A client medium using SSH."""
    
    def __init__(self, host, port=None, username=None, password=None,
            vendor=None):
        """Creates a client that will connect on the first use.
        
        :param vendor: An optional override for the ssh vendor to use. See
            bzrlib.transport.ssh for details on ssh vendors.
        """
        SmartClientStreamMedium.__init__(self)
        self._connected = False
        self._host = host
        self._password = password
        self._port = port
        self._username = username
        self._read_from = None
        self._ssh_connection = None
        self._vendor = vendor
        self._write_to = None

    def _accept_bytes(self, bytes):
        """See SmartClientStreamMedium.accept_bytes."""
        self._ensure_connection()
        self._write_to.write(bytes)

    def disconnect(self):
        """See SmartClientMedium.disconnect()."""
        if not self._connected:
            return
        self._read_from.close()
        self._write_to.close()
        self._ssh_connection.close()
        self._connected = False

    def _ensure_connection(self):
        """Connect this medium if not already connected."""
        if self._connected:
            return
        executable = os.environ.get('BZR_REMOTE_PATH', 'bzr')
        if self._vendor is None:
            vendor = ssh._get_ssh_vendor()
        else:
            vendor = self._vendor
        self._ssh_connection = vendor.connect_ssh(self._username,
                self._password, self._host, self._port,
                command=[executable, 'serve', '--inet', '--directory=/',
                         '--allow-writes'])
        self._read_from, self._write_to = \
            self._ssh_connection.get_filelike_channels()
        self._connected = True

    def _flush(self):
        """See SmartClientStreamMedium._flush()."""
        self._write_to.flush()

    def _read_bytes(self, count):
        """See SmartClientStreamMedium.read_bytes."""
        if not self._connected:
            raise errors.MediumNotConnected(self)
        return self._read_from.read(count)


class SmartTCPClientMedium(SmartClientStreamMedium):
    """A client medium using TCP."""
    
    def __init__(self, host, port):
        """Creates a client that will connect on the first use."""
        SmartClientStreamMedium.__init__(self)
        self._connected = False
        self._host = host
        self._port = port
        self._socket = None

    def _accept_bytes(self, bytes):
        """See SmartClientMedium.accept_bytes."""
        self._ensure_connection()
        self._socket.sendall(bytes)

    def disconnect(self):
        """See SmartClientMedium.disconnect()."""
        if not self._connected:
            return
        self._socket.close()
        self._socket = None
        self._connected = False

    def _ensure_connection(self):
        """Connect this medium if not already connected."""
        if self._connected:
            return
        self._socket = socket.socket()
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        result = self._socket.connect_ex((self._host, int(self._port)))
        if result:
            raise errors.ConnectionError("failed to connect to %s:%d: %s" %
                    (self._host, self._port, os.strerror(result)))
        self._connected = True

    def _flush(self):
        """See SmartClientStreamMedium._flush().
        
        For TCP we do no flushing. We may want to turn off TCP_NODELAY and 
        add a means to do a flush, but that can be done in the future.
        """

    def _read_bytes(self, count):
        """See SmartClientMedium.read_bytes."""
        if not self._connected:
            raise errors.MediumNotConnected(self)
        return self._socket.recv(count)


class SmartClientStreamMediumRequest(SmartClientMediumRequest):
    """A SmartClientMediumRequest that works with an SmartClientStreamMedium."""

    def __init__(self, medium):
        SmartClientMediumRequest.__init__(self, medium)
        # check that we are safe concurrency wise. If some streams start
        # allowing concurrent requests - i.e. via multiplexing - then this
        # assert should be moved to SmartClientStreamMedium.get_request,
        # and the setting/unsetting of _current_request likewise moved into
        # that class : but its unneeded overhead for now. RBC 20060922
        if self._medium._current_request is not None:
            raise errors.TooManyConcurrentRequests(self._medium)
        self._medium._current_request = self

    def _accept_bytes(self, bytes):
        """See SmartClientMediumRequest._accept_bytes.
        
        This forwards to self._medium._accept_bytes because we are operating
        on the mediums stream.
        """
        self._medium._accept_bytes(bytes)

    def _finished_reading(self):
        """See SmartClientMediumRequest._finished_reading.

        This clears the _current_request on self._medium to allow a new 
        request to be created.
        """
        assert self._medium._current_request is self
        self._medium._current_request = None
        
    def _finished_writing(self):
        """See SmartClientMediumRequest._finished_writing.

        This invokes self._medium._flush to ensure all bytes are transmitted.
        """
        self._medium._flush()

    def _read_bytes(self, count):
        """See SmartClientMediumRequest._read_bytes.
        
        This forwards to self._medium._read_bytes because we are operating
        on the mediums stream.
        """
        return self._medium._read_bytes(count)


