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

"""Smart-server protocol, client and server.

Requests are sent as a command and list of arguments, followed by optional
bulk body data.  Responses are similarly a response and list of arguments,
followed by bulk body data. ::

  SEP := '\001'
    Fields are separated by Ctrl-A.
  BULK_DATA := CHUNK TRAILER
    Chunks can be repeated as many times as necessary.
  CHUNK := CHUNK_LEN CHUNK_BODY
  CHUNK_LEN := DIGIT+ NEWLINE
    Gives the number of bytes in the following chunk.
  CHUNK_BODY := BYTE[chunk_len]
  TRAILER := SUCCESS_TRAILER | ERROR_TRAILER
  SUCCESS_TRAILER := 'done' NEWLINE
  ERROR_TRAILER := 

Paths are passed across the network.  The client needs to see a namespace that
includes any repository that might need to be referenced, and the client needs
to know about a root directory beyond which it cannot ascend.

Servers run over ssh will typically want to be able to access any path the user 
can access.  Public servers on the other hand (which might be over http, ssh
or tcp) will typically want to restrict access to only a particular directory 
and its children, so will want to do a software virtual root at that level.
In other words they'll want to rewrite incoming paths to be under that level
(and prevent escaping using ../ tricks.)

URLs that include ~ should probably be passed across to the server verbatim
and the server can expand them.  This will proably not be meaningful when 
limited to a directory?

At the bottom level socket, pipes, HTTP server.  For sockets, we have the idea
that you have multiple requests and get a read error because the other side did
shutdown.  For pipes we have read pipe which will have a zero read which marks
end-of-file.  For HTTP server environment there is not end-of-stream because
each request coming into the server is independent.

So we need a wrapper around pipes and sockets to seperate out requests from
substrate and this will give us a single model which is consist for HTTP,
sockets and pipes.

Server-side
-----------

 MEDIUM  (factory for protocol, reads bytes & pushes to protocol,
          uses protocol to detect end-of-request, sends written
          bytes to client) e.g. socket, pipe, HTTP request handler.
  ^
  | bytes.
  v

PROTOCOL  (serialization, deserialization)  accepts bytes for one
          request, decodes according to internal state, pushes
          structured data to handler.  accepts structured data from
          handler and encodes and writes to the medium.  factory for
          handler.
  ^
  | structured data
  v

HANDLER   (domain logic) accepts structured data, operates state
          machine until the request can be satisfied,
          sends structured data to the protocol.


Client-side
-----------

 CLIENT             domain logic, accepts domain requests, generated structured
                    data, reads structured data from responses and turns into
                    domain data.  Sends structured data to the protocol.
                    Operates state machines until the request can be delivered
                    (e.g. reading from a bundle generated in bzrlib to deliver a
                    complete request).

                    Possibly this should just be RemoteBzrDir, RemoteTransport,
                    ...
  ^
  | structured data
  v

PROTOCOL  (serialization, deserialization)  accepts structured data for one
          request, encodes and writes to the medium.  Reads bytes from the
          medium, decodes and allows the client to read structured data.
  ^
  | bytes.
  v

 MEDIUM  (accepts bytes from the protocol & delivers to the remote server.
          Allows the potocol to read bytes e.g. socket, pipe, HTTP request.
"""


# TODO: _translate_error should be on the client, not the transport because
#     error coding is wire protocol specific.

# TODO: A plain integer from query_version is too simple; should give some
# capabilities too?

# TODO: Server should probably catch exceptions within itself and send them
# back across the network.  (But shouldn't catch KeyboardInterrupt etc)
# Also needs to somehow report protocol errors like bad requests.  Need to
# consider how we'll handle error reporting, e.g. if we get halfway through a
# bulk transfer and then something goes wrong.

# TODO: Standard marker at start of request/response lines?

# TODO: Make each request and response self-validatable, e.g. with checksums.
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
#   John proposes:  I think it would be worthwhile to have a header on each
#   chunk, that indicates it is another chunk. Then you can send an 'error'
#   chunk as long as you finish the previous chunk.
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
#
# TODO: Server in some cases will need to restrict access to files outside of
# a particular root directory.  LocalTransport doesn't do anything to stop you
# ascending above the base directory, so we need to prevent paths
# containing '..' in either the server or transport layers.  (Also need to
# consider what happens if someone creates a symlink pointing outside the 
# directory tree...)
#
# TODO: Server should rebase absolute paths coming across the network to put
# them under the virtual root, if one is in use.  LocalTransport currently
# doesn't do that; if you give it an absolute path it just uses it.
# 
# XXX: Arguments can't contain newlines or ascii; possibly we should e.g.
# urlescape them instead.  Indeed possibly this should just literally be
# http-over-ssh.
#
# FIXME: This transport, with several others, has imperfect handling of paths
# within urls.  It'd probably be better for ".." from a root to raise an error
# rather than return the same directory as we do at present.
#
# TODO: Rather than working at the Transport layer we want a Branch,
# Repository or BzrDir objects that talk to a server.
#
# TODO: Probably want some way for server commands to gradually produce body
# data rather than passing it as a string; they could perhaps pass an
# iterator-like callback that will gradually yield data; it probably needs a
# close() method that will always be closed to do any necessary cleanup.
#
# TODO: Split the actual smart server from the ssh encoding of it.
#
# TODO: Perhaps support file-level readwrite operations over the transport
# too.
#
# TODO: SmartBzrDir class, proxying all Branch etc methods across to another
# branch doing file-level operations.
#

from cStringIO import StringIO
import os
import socket
import tempfile
import threading
import urllib
import urlparse

from bzrlib import (
    bzrdir,
    errors,
    revision,
    transport,
    trace,
    urlutils,
    )
from bzrlib.bundle.serializer import write_bundle
from bzrlib.transport.smart import medium
try:
    from bzrlib.transport import ssh
except errors.ParamikoNotPresent:
    # no paramiko.  SmartSSHClientMedium will break.
    pass

# must do this otherwise urllib can't parse the urls properly :(
for scheme in ['ssh', 'bzr', 'bzr+loopback', 'bzr+ssh']:
    transport.register_urlparse_netloc_protocol(scheme)
del scheme


def _recv_tuple(from_file):
    req_line = from_file.readline()
    return _decode_tuple(req_line)


def _decode_tuple(req_line):
    if req_line == None or req_line == '':
        return None
    if req_line[-1] != '\n':
        raise errors.SmartProtocolError("request %r not terminated" % req_line)
    return tuple(req_line[:-1].split('\x01'))


def _encode_tuple(args):
    """Encode the tuple args to a bytestream."""
    return '\x01'.join(args) + '\n'


class SmartProtocolBase(object):
    """Methods common to client and server"""

    # TODO: this only actually accomodates a single block; possibly should
    # support multiple chunks?
    def _encode_bulk_data(self, body):
        """Encode body as a bulk data chunk."""
        return ''.join(('%d\n' % len(body), body, 'done\n'))

    def _serialise_offsets(self, offsets):
        """Serialise a readv offset list."""
        txt = []
        for start, length in offsets:
            txt.append('%d,%d' % (start, length))
        return '\n'.join(txt)
        

class SmartServerRequestProtocolOne(SmartProtocolBase):
    """Server-side encoding and decoding logic for smart version 1."""
    
    def __init__(self, backing_transport, write_func):
        self._backing_transport = backing_transport
        self.excess_buffer = ''
        self._finished = False
        self.in_buffer = ''
        self.has_dispatched = False
        self.request = None
        self._body_decoder = None
        self._write_func = write_func

    def accept_bytes(self, bytes):
        """Take bytes, and advance the internal state machine appropriately.
        
        :param bytes: must be a byte string
        """
        assert isinstance(bytes, str)
        self.in_buffer += bytes
        if not self.has_dispatched:
            if '\n' not in self.in_buffer:
                # no command line yet
                return
            self.has_dispatched = True
            try:
                first_line, self.in_buffer = self.in_buffer.split('\n', 1)
                first_line += '\n'
                req_args = _decode_tuple(first_line)
                self.request = SmartServerRequestHandler(
                    self._backing_transport)
                self.request.dispatch_command(req_args[0], req_args[1:])
                if self.request.finished_reading:
                    # trivial request
                    self.excess_buffer = self.in_buffer
                    self.in_buffer = ''
                    self._send_response(self.request.response.args,
                        self.request.response.body)
            except KeyboardInterrupt:
                raise
            except Exception, exception:
                # everything else: pass to client, flush, and quit
                self._send_response(('error', str(exception)))
                return

        if self.has_dispatched:
            if self._finished:
                # nothing to do.XXX: this routine should be a single state 
                # machine too.
                self.excess_buffer += self.in_buffer
                self.in_buffer = ''
                return
            if self._body_decoder is None:
                self._body_decoder = LengthPrefixedBodyDecoder()
            self._body_decoder.accept_bytes(self.in_buffer)
            self.in_buffer = self._body_decoder.unused_data
            body_data = self._body_decoder.read_pending_data()
            self.request.accept_body(body_data)
            if self._body_decoder.finished_reading:
                self.request.end_of_body()
                assert self.request.finished_reading, \
                    "no more body, request not finished"
            if self.request.response is not None:
                self._send_response(self.request.response.args,
                    self.request.response.body)
                self.excess_buffer = self.in_buffer
                self.in_buffer = ''
            else:
                assert not self.request.finished_reading, \
                    "no response and we have finished reading."

    def _send_response(self, args, body=None):
        """Send a smart server response down the output stream."""
        assert not self._finished, 'response already sent'
        self._finished = True
        self._write_func(_encode_tuple(args))
        if body is not None:
            assert isinstance(body, str), 'body must be a str'
            bytes = self._encode_bulk_data(body)
            self._write_func(bytes)

    def next_read_size(self):
        if self._finished:
            return 0
        if self._body_decoder is None:
            return 1
        else:
            return self._body_decoder.next_read_size()


class LengthPrefixedBodyDecoder(object):
    """Decodes the length-prefixed bulk data."""
    
    def __init__(self):
        self.bytes_left = None
        self.finished_reading = False
        self.unused_data = ''
        self.state_accept = self._state_accept_expecting_length
        self.state_read = self._state_read_no_data
        self._in_buffer = ''
        self._trailer_buffer = ''
    
    def accept_bytes(self, bytes):
        """Decode as much of bytes as possible.

        If 'bytes' contains too much data it will be appended to
        self.unused_data.

        finished_reading will be set when no more data is required.  Further
        data will be appended to self.unused_data.
        """
        # accept_bytes is allowed to change the state
        current_state = self.state_accept
        self.state_accept(bytes)
        while current_state != self.state_accept:
            current_state = self.state_accept
            self.state_accept('')

    def next_read_size(self):
        if self.bytes_left is not None:
            # Ideally we want to read all the remainder of the body and the
            # trailer in one go.
            return self.bytes_left + 5
        elif self.state_accept == self._state_accept_reading_trailer:
            # Just the trailer left
            return 5 - len(self._trailer_buffer)
        elif self.state_accept == self._state_accept_expecting_length:
            # There's still at least 6 bytes left ('\n' to end the length, plus
            # 'done\n').
            return 6
        else:
            # Reading excess data.  Either way, 1 byte at a time is fine.
            return 1
        
    def read_pending_data(self):
        """Return any pending data that has been decoded."""
        return self.state_read()

    def _state_accept_expecting_length(self, bytes):
        self._in_buffer += bytes
        pos = self._in_buffer.find('\n')
        if pos == -1:
            return
        self.bytes_left = int(self._in_buffer[:pos])
        self._in_buffer = self._in_buffer[pos+1:]
        self.bytes_left -= len(self._in_buffer)
        self.state_accept = self._state_accept_reading_body
        self.state_read = self._state_read_in_buffer

    def _state_accept_reading_body(self, bytes):
        self._in_buffer += bytes
        self.bytes_left -= len(bytes)
        if self.bytes_left <= 0:
            # Finished with body
            if self.bytes_left != 0:
                self._trailer_buffer = self._in_buffer[self.bytes_left:]
                self._in_buffer = self._in_buffer[:self.bytes_left]
            self.bytes_left = None
            self.state_accept = self._state_accept_reading_trailer
        
    def _state_accept_reading_trailer(self, bytes):
        self._trailer_buffer += bytes
        # TODO: what if the trailer does not match "done\n"?  Should this raise
        # a ProtocolViolation exception?
        if self._trailer_buffer.startswith('done\n'):
            self.unused_data = self._trailer_buffer[len('done\n'):]
            self.state_accept = self._state_accept_reading_unused
            self.finished_reading = True
    
    def _state_accept_reading_unused(self, bytes):
        self.unused_data += bytes

    def _state_read_no_data(self):
        return ''

    def _state_read_in_buffer(self):
        result = self._in_buffer
        self._in_buffer = ''
        return result


class SmartServerResponse(object):
    """Response generated by SmartServerRequestHandler."""

    def __init__(self, args, body=None):
        self.args = args
        self.body = body

# XXX: TODO: Create a SmartServerRequestHandler which will take the responsibility
# for delivering the data for a request. This could be done with as the
# StreamServer, though that would create conflation between request and response
# which may be undesirable.


class SmartServerRequestHandler(object):
    """Protocol logic for smart server.
    
    This doesn't handle serialization at all, it just processes requests and
    creates responses.
    """

    # IMPORTANT FOR IMPLEMENTORS: It is important that SmartServerRequestHandler
    # not contain encoding or decoding logic to allow the wire protocol to vary
    # from the object protocol: we will want to tweak the wire protocol separate
    # from the object model, and ideally we will be able to do that without
    # having a SmartServerRequestHandler subclass for each wire protocol, rather
    # just a Protocol subclass.

    # TODO: Better way of representing the body for commands that take it,
    # and allow it to be streamed into the server.
    
    def __init__(self, backing_transport):
        self._backing_transport = backing_transport
        self._converted_command = False
        self.finished_reading = False
        self._body_bytes = ''
        self.response = None

    def accept_body(self, bytes):
        """Accept body data.

        This should be overriden for each command that desired body data to
        handle the right format of that data. I.e. plain bytes, a bundle etc.

        The deserialisation into that format should be done in the Protocol
        object. Set self.desired_body_format to the format your method will
        handle.
        """
        # default fallback is to accumulate bytes.
        self._body_bytes += bytes
        
    def _end_of_body_handler(self):
        """An unimplemented end of body handler."""
        raise NotImplementedError(self._end_of_body_handler)
        
    def do_hello(self):
        """Answer a version request with my version."""
        return SmartServerResponse(('ok', '1'))

    def do_has(self, relpath):
        r = self._backing_transport.has(relpath) and 'yes' or 'no'
        return SmartServerResponse((r,))

    def do_get(self, relpath):
        backing_bytes = self._backing_transport.get_bytes(relpath)
        return SmartServerResponse(('ok',), backing_bytes)

    def _deserialise_optional_mode(self, mode):
        # XXX: FIXME this should be on the protocol object.
        if mode == '':
            return None
        else:
            return int(mode)

    def do_append(self, relpath, mode):
        self._converted_command = True
        self._relpath = relpath
        self._mode = self._deserialise_optional_mode(mode)
        self._end_of_body_handler = self._handle_do_append_end
    
    def _handle_do_append_end(self):
        old_length = self._backing_transport.append_bytes(
            self._relpath, self._body_bytes, self._mode)
        self.response = SmartServerResponse(('appended', '%d' % old_length))

    def do_delete(self, relpath):
        self._backing_transport.delete(relpath)

    def do_iter_files_recursive(self, relpath):
        transport = self._backing_transport.clone(relpath)
        filenames = transport.iter_files_recursive()
        return SmartServerResponse(('names',) + tuple(filenames))

    def do_list_dir(self, relpath):
        filenames = self._backing_transport.list_dir(relpath)
        return SmartServerResponse(('names',) + tuple(filenames))

    def do_mkdir(self, relpath, mode):
        self._backing_transport.mkdir(relpath,
                                      self._deserialise_optional_mode(mode))

    def do_move(self, rel_from, rel_to):
        self._backing_transport.move(rel_from, rel_to)

    def do_put(self, relpath, mode):
        self._converted_command = True
        self._relpath = relpath
        self._mode = self._deserialise_optional_mode(mode)
        self._end_of_body_handler = self._handle_do_put

    def _handle_do_put(self):
        self._backing_transport.put_bytes(self._relpath,
                self._body_bytes, self._mode)
        self.response = SmartServerResponse(('ok',))

    def _deserialise_offsets(self, text):
        # XXX: FIXME this should be on the protocol object.
        offsets = []
        for line in text.split('\n'):
            if not line:
                continue
            start, length = line.split(',')
            offsets.append((int(start), int(length)))
        return offsets

    def do_put_non_atomic(self, relpath, mode, create_parent, dir_mode):
        self._converted_command = True
        self._end_of_body_handler = self._handle_put_non_atomic
        self._relpath = relpath
        self._dir_mode = self._deserialise_optional_mode(dir_mode)
        self._mode = self._deserialise_optional_mode(mode)
        # a boolean would be nicer XXX
        self._create_parent = (create_parent == 'T')

    def _handle_put_non_atomic(self):
        self._backing_transport.put_bytes_non_atomic(self._relpath,
                self._body_bytes,
                mode=self._mode,
                create_parent_dir=self._create_parent,
                dir_mode=self._dir_mode)
        self.response = SmartServerResponse(('ok',))

    def do_readv(self, relpath):
        self._converted_command = True
        self._end_of_body_handler = self._handle_readv_offsets
        self._relpath = relpath

    def end_of_body(self):
        """No more body data will be received."""
        self._run_handler_code(self._end_of_body_handler, (), {})
        # cannot read after this.
        self.finished_reading = True

    def _handle_readv_offsets(self):
        """accept offsets for a readv request."""
        offsets = self._deserialise_offsets(self._body_bytes)
        backing_bytes = ''.join(bytes for offset, bytes in
            self._backing_transport.readv(self._relpath, offsets))
        self.response = SmartServerResponse(('readv',), backing_bytes)
        
    def do_rename(self, rel_from, rel_to):
        self._backing_transport.rename(rel_from, rel_to)

    def do_rmdir(self, relpath):
        self._backing_transport.rmdir(relpath)

    def do_stat(self, relpath):
        stat = self._backing_transport.stat(relpath)
        return SmartServerResponse(('stat', str(stat.st_size), oct(stat.st_mode)))
        
    def do_get_bundle(self, path, revision_id):
        # open transport relative to our base
        t = self._backing_transport.clone(path)
        control, extra_path = bzrdir.BzrDir.open_containing_from_transport(t)
        repo = control.open_repository()
        tmpf = tempfile.TemporaryFile()
        base_revision = revision.NULL_REVISION
        write_bundle(repo, revision_id, base_revision, tmpf)
        tmpf.seek(0)
        return SmartServerResponse((), tmpf.read())

    def dispatch_command(self, cmd, args):
        """Deprecated compatibility method.""" # XXX XXX
        func = getattr(self, 'do_' + cmd, None)
        if func is None:
            raise errors.SmartProtocolError("bad request %r" % (cmd,))
        self._run_handler_code(func, args, {})

    def _run_handler_code(self, callable, args, kwargs):
        """Run some handler specific code 'callable'.

        If a result is returned, it is considered to be the commands response,
        and finished_reading is set true, and its assigned to self.response.

        Any exceptions caught are translated and a response object created
        from them.
        """
        result = self._call_converting_errors(callable, args, kwargs)
        if result is not None:
            self.response = result
            self.finished_reading = True
        # handle unconverted commands
        if not self._converted_command:
            self.finished_reading = True
            if result is None:
                self.response = SmartServerResponse(('ok',))

    def _call_converting_errors(self, callable, args, kwargs):
        """Call callable converting errors to Response objects."""
        try:
            return callable(*args, **kwargs)
        except errors.NoSuchFile, e:
            return SmartServerResponse(('NoSuchFile', e.path))
        except errors.FileExists, e:
            return SmartServerResponse(('FileExists', e.path))
        except errors.DirectoryNotEmpty, e:
            return SmartServerResponse(('DirectoryNotEmpty', e.path))
        except errors.ShortReadvError, e:
            return SmartServerResponse(('ShortReadvError',
                e.path, str(e.offset), str(e.length), str(e.actual)))
        except UnicodeError, e:
            # If it is a DecodeError, than most likely we are starting
            # with a plain string
            str_or_unicode = e.object
            if isinstance(str_or_unicode, unicode):
                # XXX: UTF-8 might have \x01 (our seperator byte) in it.  We
                # should escape it somehow.
                val = 'u:' + str_or_unicode.encode('utf-8')
            else:
                val = 's:' + str_or_unicode.encode('base64')
            # This handles UnicodeEncodeError or UnicodeDecodeError
            return SmartServerResponse((e.__class__.__name__,
                    e.encoding, val, str(e.start), str(e.end), e.reason))
        except errors.TransportNotPossible, e:
            if e.msg == "readonly transport":
                return SmartServerResponse(('ReadOnlyError', ))
            else:
                raise


class SmartTCPServer(object):
    """Listens on a TCP socket and accepts connections from smart clients"""

    def __init__(self, backing_transport, host='127.0.0.1', port=0):
        """Construct a new server.

        To actually start it running, call either start_background_thread or
        serve.

        :param host: Name of the interface to listen on.
        :param port: TCP port to listen on, or 0 to allocate a transient port.
        """
        self._server_socket = socket.socket()
        self._server_socket.bind((host, port))
        self.port = self._server_socket.getsockname()[1]
        self._server_socket.listen(1)
        self._server_socket.settimeout(1)
        self.backing_transport = backing_transport

    def serve(self):
        # let connections timeout so that we get a chance to terminate
        # Keep a reference to the exceptions we want to catch because the socket
        # module's globals get set to None during interpreter shutdown.
        from socket import timeout as socket_timeout
        from socket import error as socket_error
        self._should_terminate = False
        while not self._should_terminate:
            try:
                self.accept_and_serve()
            except socket_timeout:
                # just check if we're asked to stop
                pass
            except socket_error, e:
                trace.warning("client disconnected: %s", e)
                pass

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%d/" % self._server_socket.getsockname()

    def accept_and_serve(self):
        conn, client_addr = self._server_socket.accept()
        # For WIN32, where the timeout value from the listening socket
        # propogates to the newly accepted socket.
        conn.setblocking(True)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        handler = medium.SmartServerSocketStreamMedium(conn, self.backing_transport)
        connection_thread = threading.Thread(None, handler.serve, name='smart-server-child')
        connection_thread.setDaemon(True)
        connection_thread.start()

    def start_background_thread(self):
        self._server_thread = threading.Thread(None,
                self.serve,
                name='server-' + self.get_url())
        self._server_thread.setDaemon(True)
        self._server_thread.start()

    def stop_background_thread(self):
        self._should_terminate = True
        # self._server_socket.close()
        # we used to join the thread, but it's not really necessary; it will
        # terminate in time
        ## self._server_thread.join()


class SmartTCPServer_for_testing(SmartTCPServer):
    """Server suitable for use by transport tests.
    
    This server is backed by the process's cwd.
    """

    def __init__(self):
        self._homedir = urlutils.local_path_to_url(os.getcwd())[7:]
        # The server is set up by default like for ssh access: the client
        # passes filesystem-absolute paths; therefore the server must look
        # them up relative to the root directory.  it might be better to act
        # a public server and have the server rewrite paths into the test
        # directory.
        SmartTCPServer.__init__(self,
            transport.get_transport(urlutils.local_path_to_url('/')))
        
    def setUp(self):
        """Set up server for testing"""
        self.start_background_thread()

    def tearDown(self):
        self.stop_background_thread()

    def get_url(self):
        """Return the url of the server"""
        host, port = self._server_socket.getsockname()
        return "bzr://%s:%d%s" % (host, port, urlutils.escape(self._homedir))

    def get_bogus_url(self):
        """Return a URL which will fail to connect"""
        return 'bzr://127.0.0.1:1/'


class SmartStat(object):

    def __init__(self, size, mode):
        self.st_size = size
        self.st_mode = mode


class SmartTransport(transport.Transport):
    """Connection to a smart server.

    The connection holds references to pipes that can be used to send requests
    to the server.

    The connection has a notion of the current directory to which it's
    connected; this is incorporated in filenames passed to the server.
    
    This supports some higher-level RPC operations and can also be treated 
    like a Transport to do file-like operations.

    The connection can be made over a tcp socket, or (in future) an ssh pipe
    or a series of http requests.  There are concrete subclasses for each
    type: SmartTCPTransport, etc.
    """

    # IMPORTANT FOR IMPLEMENTORS: SmartTransport MUST NOT be given encoding
    # responsibilities: Put those on SmartClient or similar. This is vital for
    # the ability to support multiple versions of the smart protocol over time:
    # SmartTransport is an adapter from the Transport object model to the 
    # SmartClient model, not an encoder.

    def __init__(self, url, clone_from=None, medium=None):
        """Constructor.

        :param medium: The medium to use for this RemoteTransport. This must be
            supplied if clone_from is None.
        """
        ### Technically super() here is faulty because Transport's __init__
        ### fails to take 2 parameters, and if super were to choose a silly
        ### initialisation order things would blow up. 
        if not url.endswith('/'):
            url += '/'
        super(SmartTransport, self).__init__(url)
        self._scheme, self._username, self._password, self._host, self._port, self._path = \
                transport.split_url(url)
        if clone_from is None:
            self._medium = medium
        else:
            # credentials may be stripped from the base in some circumstances
            # as yet to be clearly defined or documented, so copy them.
            self._username = clone_from._username
            # reuse same connection
            self._medium = clone_from._medium
        assert self._medium is not None

    def abspath(self, relpath):
        """Return the full url to the given relative path.
        
        @param relpath: the relative path or path components
        @type relpath: str or list
        """
        return self._unparse_url(self._remote_path(relpath))
    
    def clone(self, relative_url):
        """Make a new SmartTransport related to me, sharing the same connection.

        This essentially opens a handle on a different remote directory.
        """
        if relative_url is None:
            return SmartTransport(self.base, self)
        else:
            return SmartTransport(self.abspath(relative_url), self)

    def is_readonly(self):
        """Smart server transport can do read/write file operations."""
        return False
                                                   
    def get_smart_client(self):
        return self._medium

    def get_smart_medium(self):
        return self._medium
                                                   
    def _unparse_url(self, path):
        """Return URL for a path.

        :see: SFTPUrlHandling._unparse_url
        """
        # TODO: Eventually it should be possible to unify this with
        # SFTPUrlHandling._unparse_url?
        if path == '':
            path = '/'
        path = urllib.quote(path)
        netloc = urllib.quote(self._host)
        if self._username is not None:
            netloc = '%s@%s' % (urllib.quote(self._username), netloc)
        if self._port is not None:
            netloc = '%s:%d' % (netloc, self._port)
        return urlparse.urlunparse((self._scheme, netloc, path, '', '', ''))

    def _remote_path(self, relpath):
        """Returns the Unicode version of the absolute path for relpath."""
        return self._combine_paths(self._path, relpath)

    def _call(self, method, *args):
        resp = self._call2(method, *args)
        self._translate_error(resp)

    def _call2(self, method, *args):
        """Call a method on the remote server."""
        protocol = SmartClientRequestProtocolOne(self._medium.get_request())
        protocol.call(method, *args)
        return protocol.read_response_tuple()

    def _call_with_body_bytes(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        protocol = SmartClientRequestProtocolOne(self._medium.get_request())
        protocol.call_with_body_bytes((method, ) + args, body)
        return protocol.read_response_tuple()

    def has(self, relpath):
        """Indicate whether a remote file of the given name exists or not.

        :see: Transport.has()
        """
        resp = self._call2('has', self._remote_path(relpath))
        if resp == ('yes', ):
            return True
        elif resp == ('no', ):
            return False
        else:
            self._translate_error(resp)

    def get(self, relpath):
        """Return file-like object reading the contents of a remote file.
        
        :see: Transport.get_bytes()/get_file()
        """
        return StringIO(self.get_bytes(relpath))

    def get_bytes(self, relpath):
        remote = self._remote_path(relpath)
        protocol = SmartClientRequestProtocolOne(self._medium.get_request())
        protocol.call('get', remote)
        resp = protocol.read_response_tuple(True)
        if resp != ('ok', ):
            protocol.cancel_read_body()
            self._translate_error(resp, relpath)
        return protocol.read_body_bytes()

    def _serialise_optional_mode(self, mode):
        if mode is None:
            return ''
        else:
            return '%d' % mode

    def mkdir(self, relpath, mode=None):
        resp = self._call2('mkdir', self._remote_path(relpath),
            self._serialise_optional_mode(mode))
        self._translate_error(resp)

    def put_bytes(self, relpath, upload_contents, mode=None):
        # FIXME: upload_file is probably not safe for non-ascii characters -
        # should probably just pass all parameters as length-delimited
        # strings?
        resp = self._call_with_body_bytes('put',
            (self._remote_path(relpath), self._serialise_optional_mode(mode)),
            upload_contents)
        self._translate_error(resp)

    def put_bytes_non_atomic(self, relpath, bytes, mode=None,
                             create_parent_dir=False,
                             dir_mode=None):
        """See Transport.put_bytes_non_atomic."""
        # FIXME: no encoding in the transport!
        create_parent_str = 'F'
        if create_parent_dir:
            create_parent_str = 'T'

        resp = self._call_with_body_bytes(
            'put_non_atomic',
            (self._remote_path(relpath), self._serialise_optional_mode(mode),
             create_parent_str, self._serialise_optional_mode(dir_mode)),
            bytes)
        self._translate_error(resp)

    def put_file(self, relpath, upload_file, mode=None):
        # its not ideal to seek back, but currently put_non_atomic_file depends
        # on transports not reading before failing - which is a faulty
        # assumption I think - RBC 20060915
        pos = upload_file.tell()
        try:
            return self.put_bytes(relpath, upload_file.read(), mode)
        except:
            upload_file.seek(pos)
            raise

    def put_file_non_atomic(self, relpath, f, mode=None,
                            create_parent_dir=False,
                            dir_mode=None):
        return self.put_bytes_non_atomic(relpath, f.read(), mode=mode,
                                         create_parent_dir=create_parent_dir,
                                         dir_mode=dir_mode)

    def append_file(self, relpath, from_file, mode=None):
        return self.append_bytes(relpath, from_file.read(), mode)
        
    def append_bytes(self, relpath, bytes, mode=None):
        resp = self._call_with_body_bytes(
            'append',
            (self._remote_path(relpath), self._serialise_optional_mode(mode)),
            bytes)
        if resp[0] == 'appended':
            return int(resp[1])
        self._translate_error(resp)

    def delete(self, relpath):
        resp = self._call2('delete', self._remote_path(relpath))
        self._translate_error(resp)

    def readv(self, relpath, offsets):
        if not offsets:
            return

        offsets = list(offsets)

        sorted_offsets = sorted(offsets)
        # turn the list of offsets into a stack
        offset_stack = iter(offsets)
        cur_offset_and_size = offset_stack.next()
        coalesced = list(self._coalesce_offsets(sorted_offsets,
                               limit=self._max_readv_combine,
                               fudge_factor=self._bytes_to_read_before_seek))

        protocol = SmartClientRequestProtocolOne(self._medium.get_request())
        protocol.call_with_body_readv_array(
            ('readv', self._remote_path(relpath)),
            [(c.start, c.length) for c in coalesced])
        resp = protocol.read_response_tuple(True)

        if resp[0] != 'readv':
            # This should raise an exception
            protocol.cancel_read_body()
            self._translate_error(resp)
            return

        # FIXME: this should know how many bytes are needed, for clarity.
        data = protocol.read_body_bytes()
        # Cache the results, but only until they have been fulfilled
        data_map = {}
        for c_offset in coalesced:
            if len(data) < c_offset.length:
                raise errors.ShortReadvError(relpath, c_offset.start,
                            c_offset.length, actual=len(data))
            for suboffset, subsize in c_offset.ranges:
                key = (c_offset.start+suboffset, subsize)
                data_map[key] = data[suboffset:suboffset+subsize]
            data = data[c_offset.length:]

            # Now that we've read some data, see if we can yield anything back
            while cur_offset_and_size in data_map:
                this_data = data_map.pop(cur_offset_and_size)
                yield cur_offset_and_size[0], this_data
                cur_offset_and_size = offset_stack.next()

    def rename(self, rel_from, rel_to):
        self._call('rename',
                   self._remote_path(rel_from),
                   self._remote_path(rel_to))

    def move(self, rel_from, rel_to):
        self._call('move',
                   self._remote_path(rel_from),
                   self._remote_path(rel_to))

    def rmdir(self, relpath):
        resp = self._call('rmdir', self._remote_path(relpath))

    def _translate_error(self, resp, orig_path=None):
        """Raise an exception from a response"""
        if resp is None:
            what = None
        else:
            what = resp[0]
        if what == 'ok':
            return
        elif what == 'NoSuchFile':
            if orig_path is not None:
                error_path = orig_path
            else:
                error_path = resp[1]
            raise errors.NoSuchFile(error_path)
        elif what == 'error':
            raise errors.SmartProtocolError(unicode(resp[1]))
        elif what == 'FileExists':
            raise errors.FileExists(resp[1])
        elif what == 'DirectoryNotEmpty':
            raise errors.DirectoryNotEmpty(resp[1])
        elif what == 'ShortReadvError':
            raise errors.ShortReadvError(resp[1], int(resp[2]),
                                         int(resp[3]), int(resp[4]))
        elif what in ('UnicodeEncodeError', 'UnicodeDecodeError'):
            encoding = str(resp[1]) # encoding must always be a string
            val = resp[2]
            start = int(resp[3])
            end = int(resp[4])
            reason = str(resp[5]) # reason must always be a string
            if val.startswith('u:'):
                val = val[2:].decode('utf-8')
            elif val.startswith('s:'):
                val = val[2:].decode('base64')
            if what == 'UnicodeDecodeError':
                raise UnicodeDecodeError(encoding, val, start, end, reason)
            elif what == 'UnicodeEncodeError':
                raise UnicodeEncodeError(encoding, val, start, end, reason)
        elif what == "ReadOnlyError":
            raise errors.TransportNotPossible('readonly transport')
        else:
            raise errors.SmartProtocolError('unexpected smart server error: %r' % (resp,))

    def disconnect(self):
        self._medium.disconnect()

    def delete_tree(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def stat(self, relpath):
        resp = self._call2('stat', self._remote_path(relpath))
        if resp[0] == 'stat':
            return SmartStat(int(resp[1]), int(resp[2], 8))
        else:
            self._translate_error(resp)

    ## def lock_read(self, relpath):
    ##     """Lock the given file for shared (read) access.
    ##     :return: A lock object, which should be passed to Transport.unlock()
    ##     """
    ##     # The old RemoteBranch ignore lock for reading, so we will
    ##     # continue that tradition and return a bogus lock object.
    ##     class BogusLock(object):
    ##         def __init__(self, path):
    ##             self.path = path
    ##         def unlock(self):
    ##             pass
    ##     return BogusLock(relpath)

    def listable(self):
        return True

    def list_dir(self, relpath):
        resp = self._call2('list_dir', self._remote_path(relpath))
        if resp[0] == 'names':
            return [name.encode('ascii') for name in resp[1:]]
        else:
            self._translate_error(resp)

    def iter_files_recursive(self):
        resp = self._call2('iter_files_recursive', self._remote_path(''))
        if resp[0] == 'names':
            return resp[1:]
        else:
            self._translate_error(resp)


class SmartClientRequestProtocolOne(SmartProtocolBase):
    """The client-side protocol for smart version 1."""

    def __init__(self, request):
        """Construct a SmartClientRequestProtocolOne.

        :param request: A SmartClientMediumRequest to serialise onto and
            deserialise from.
        """
        self._request = request
        self._body_buffer = None

    def call(self, *args):
        bytes = _encode_tuple(args)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()

    def call_with_body_bytes(self, args, body):
        """Make a remote call of args with body bytes 'body'.

        After calling this, call read_response_tuple to find the result out.
        """
        bytes = _encode_tuple(args)
        self._request.accept_bytes(bytes)
        bytes = self._encode_bulk_data(body)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()

    def call_with_body_readv_array(self, args, body):
        """Make a remote call with a readv array.

        The body is encoded with one line per readv offset pair. The numbers in
        each pair are separated by a comma, and no trailing \n is emitted.
        """
        bytes = _encode_tuple(args)
        self._request.accept_bytes(bytes)
        readv_bytes = self._serialise_offsets(body)
        bytes = self._encode_bulk_data(readv_bytes)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()

    def cancel_read_body(self):
        """After expecting a body, a response code may indicate one otherwise.

        This method lets the domain client inform the protocol that no body
        will be transmitted. This is a terminal method: after calling it the
        protocol is not able to be used further.
        """
        self._request.finished_reading()

    def read_response_tuple(self, expect_body=False):
        """Read a response tuple from the wire.

        This should only be called once.
        """
        result = self._recv_tuple()
        if not expect_body:
            self._request.finished_reading()
        return result

    def read_body_bytes(self, count=-1):
        """Read bytes from the body, decoding into a byte stream.
        
        We read all bytes at once to ensure we've checked the trailer for 
        errors, and then feed the buffer back as read_body_bytes is called.
        """
        if self._body_buffer is not None:
            return self._body_buffer.read(count)
        _body_decoder = LengthPrefixedBodyDecoder()

        while not _body_decoder.finished_reading:
            bytes_wanted = _body_decoder.next_read_size()
            bytes = self._request.read_bytes(bytes_wanted)
            _body_decoder.accept_bytes(bytes)
        self._request.finished_reading()
        self._body_buffer = StringIO(_body_decoder.read_pending_data())
        # XXX: TODO check the trailer result.
        return self._body_buffer.read(count)

    def _recv_tuple(self):
        """Receive a tuple from the medium request."""
        line = ''
        while not line or line[-1] != '\n':
            # TODO: this is inefficient - but tuples are short.
            new_char = self._request.read_bytes(1)
            line += new_char
            assert new_char != '', "end of file reading from server."
        return _decode_tuple(line)

    def query_version(self):
        """Return protocol version number of the server."""
        self.call('hello')
        resp = self.read_response_tuple()
        if resp == ('ok', '1'):
            return 1
        else:
            raise errors.SmartProtocolError("bad response %r" % (resp,))


class SmartTCPTransport(SmartTransport):
    """Connection to smart server over plain tcp.
    
    This is essentially just a factory to get 'RemoteTransport(url,
        SmartTCPClientMedium).
    """

    def __init__(self, url):
        _scheme, _username, _password, _host, _port, _path = \
            transport.split_url(url)
        try:
            _port = int(_port)
        except (ValueError, TypeError), e:
            raise errors.InvalidURL(path=url, extra="invalid port %s" % _port)
        client_medium = medium.SmartTCPClientMedium(_host, _port)
        super(SmartTCPTransport, self).__init__(url, medium=client_medium)


class SmartSSHTransport(SmartTransport):
    """Connection to smart server over SSH.

    This is essentially just a factory to get 'RemoteTransport(url,
        SmartSSHClientMedium).
    """

    def __init__(self, url):
        _scheme, _username, _password, _host, _port, _path = \
            transport.split_url(url)
        try:
            if _port is not None:
                _port = int(_port)
        except (ValueError, TypeError), e:
            raise errors.InvalidURL(path=url, extra="invalid port %s" % 
                _port)
        client_medium = medium.SmartSSHClientMedium(_host, _port,
                                                    _username, _password)
        super(SmartSSHTransport, self).__init__(url, medium=client_medium)


def get_test_permutations():
    """Return (transport, server) permutations for testing."""
    ### We may need a little more test framework support to construct an
    ### appropriate RemoteTransport in the future.
    return [(SmartTCPTransport, SmartTCPServer_for_testing)]
