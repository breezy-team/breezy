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
  BULK_DATA := CHUNK+ TRAILER
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
"""



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


from cStringIO import StringIO
import errno
import os
import socket
import sys
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
# XXX: The smart server should not depend on the SFTP code being importable.
from bzrlib.bundle.serializer import write_bundle
from bzrlib.trace import mutter
from bzrlib.transport import local, sftp

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
    return tuple((a.decode('utf-8') for a in req_line[:-1].split('\x01')))


def _send_tuple(to_file, args):
    # XXX: this will be inefficient.  Just ask Robert.
    to_file.write('\x01'.join((a.encode('utf-8') for a in args)) + '\n')
    to_file.flush()


class SmartProtocolBase(object):
    """Methods common to client and server"""

    def _send_bulk_data(self, body):
        """Send chunked body data"""
        assert isinstance(body, str)
        self._out.write('%d\n' % len(body))
        self._out.write(body)
        self._out.write('done\n')
        self._out.flush()

    # TODO: this only actually accomodates a single block; possibly should support
    # multiple chunks?
    def _recv_bulk(self):
        chunk_len = self._in.readline()
        try:
            chunk_len = int(chunk_len)
        except ValueError:
            raise errors.SmartProtocolError("bad chunk length line %r" % chunk_len)
        bulk = self._in.read(chunk_len)
        if len(bulk) != chunk_len:
            raise errors.SmartProtocolError("short read fetching bulk data chunk")
        self._recv_trailer()
        return bulk

    def _recv_tuple(self):
        return _recv_tuple(self._in)

    def _recv_trailer(self):
        resp = self._recv_tuple()
        if resp == ('done', ):
            return
        else:
            self._translate_error(resp)


class SmartStreamServer(SmartProtocolBase):
    """Handles smart commands coming over a stream.

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
        self.smart_server = SmartServer(backing_transport)
        # server can call back to us to get bulk data - this is not really
        # ideal, they should get it per request instead
        self.smart_server._recv_body = self._recv_bulk

    def _recv_tuple(self):
        """Read a request from the client and return as a tuple.
        
        Returns None at end of file (if the client closed the connection.)
        """
        return _recv_tuple(self._in)

    def _send_tuple(self, args):
        """Send response header"""
        return _send_tuple(self._out, args)

    def _send_error_and_disconnect(self, exception):
        self._send_tuple(('error', str(exception)))
        self._out.flush()
        ## self._out.close()
        ## self._in.close()

    def _serve_one_request(self):
        """Read one request from input, process, send back a response.
        
        :return: False if the server should terminate, otherwise None.
        """
        req_args = self._recv_tuple()
        if req_args == None:
            # client closed connection
            return False  # shutdown server
        try:
            response = self.smart_server.dispatch_command(req_args[0], req_args[1:])
            self._send_tuple(response.args)
            if response.body is not None:
                self._send_bulk_data(response.body)
        except KeyboardInterrupt:
            raise
        except Exception, e:
            # everything else: pass to client, flush, and quit
            self._send_error_and_disconnect(e)
            return False

    def serve(self):
        """Serve requests until the client disconnects."""
        # Keep a reference to stderr because the sys module's globals get set to
        # None during interpreter shutdown.
        from sys import stderr
        try:
            while self._serve_one_request() != False:
                pass
        except Exception, e:
            stderr.write("%s terminating on exception %s\n" % (self, e))
            raise


class SmartServerResponse(object):
    """Response generated by SmartServer."""

    def __init__(self, args, body=None):
        self.args = args
        self.body = body


class SmartServer(object):
    """Protocol logic for smart server.
    
    This doesn't handle serialization at all, it just processes requests and
    creates responses.
    """

    # TODO: Better way of representing the body for commands that take it,
    # and allow it to be streamed into the server.
    
    def __init__(self, backing_transport):
        self._backing_transport = backing_transport
        
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
        if mode == '':
            return None
        else:
            return int(mode)

    def do_append(self, relpath, mode):
        old_length = self._backing_transport.append(relpath, StringIO(self._recv_body()),
                self._deserialise_optional_mode(mode))
        return SmartServerResponse(('appended', '%d' % old_length))

    def do_delete(self, relpath):
        self._backing_transport.delete(relpath)

    def do_iter_files_recursive(self, abspath):
        # XXX: the path handling needs some thought.
        #relpath = self._backing_transport.relpath(abspath)
        transport = self._backing_transport.clone(abspath)
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
        self._backing_transport.put(relpath, 
                StringIO(self._recv_body()), 
                self._deserialise_optional_mode(mode))

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
        func = getattr(self, 'do_' + cmd, None)
        if func is None:
            raise errors.SmartProtocolError("bad request %r" % (cmd,))
        try:
            result = func(*args)
            if result is None: 
                result = SmartServerResponse(('ok',))
            return result
        except errors.NoSuchFile, e:
            return SmartServerResponse(('NoSuchFile', e.path))
        except errors.FileExists, e:
            return SmartServerResponse(('FileExists', e.path))
        except errors.DirectoryNotEmpty, e:
            return SmartServerResponse(('DirectoryNotEmpty', e.path))


class SmartTCPServer(object):
    """Listens on a TCP socket and accepts connections from smart clients"""

    def __init__(self, backing_transport=None, host='127.0.0.1', port=0):
        """Construct a new server.

        To actually start it running, call either start_background_thread or
        serve.

        :param host: Name of the interface to listen on.
        :param port: TCP port to listen on, or 0 to allocate a transient port.
        """
        if backing_transport is None:
            backing_transport = memory.MemoryTransport()
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
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        from_client = conn.makefile('r')
        to_client = conn.makefile('w')
        handler = SmartStreamServer(from_client, to_client,
                self.backing_transport)
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
        self._homedir = os.getcwd()
        # The server is set up by default like for ssh access: the client
        # passes filesystem-absolute paths; therefore the server must look
        # them up relative to the root directory.  it might be better to act
        # a public server and have the server rewrite paths into the test
        # directory.
        SmartTCPServer.__init__(self, transport.get_transport("file:///"))
        
    def setUp(self):
        """Set up server for testing"""
        self.start_background_thread()

    def tearDown(self):
        self.stop_background_thread()

    def get_url(self):
        """Return the url of the server"""
        host, port = self._server_socket.getsockname()
        # XXX: I think this is likely to break on windows -- self._homedir will
        # have backslashes (and maybe a drive letter?).
        #  -- Andrew Bennetts, 2006-08-29
        return "bzr://%s:%d%s" % (host, port, urlutils.escape(self._homedir))

    def get_bogus_url(self):
        """Return a URL which will fail to connect"""
        return 'bzr://127.0.0.1:1/'


class SmartStat(object):

    def __init__(self, size, mode):
        self.st_size = size
        self.st_mode = mode


class SmartTransport(sftp.SFTPUrlHandling):
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

    def __init__(self, server_url, clone_from=None, client=None):
        """Constructor.

        :param client: ignored when clone_from is not None.
        """
        ### Technically super() here is faulty because Transport's __init__
        ### fails to take 2 parameters, and if super were to choose a silly
        ### initialisation order things would blow up. 
        super(SmartTransport, self).__init__(server_url)
        if clone_from is None:
            if client is None:
                self._client = SmartStreamClient(self._connect_to_server)
            else:
                self._client = client
        else:
            # credentials may be stripped from the base in some circumstances
            # as yet to be clearly defined or documented, so copy them.
            self._username = clone_from._username
            # reuse same connection
            self._client = clone_from._client

    def clone(self, relative_url):
        """Make a new SmartTransport related to me, sharing the same connection.

        This essentially opens a handle on a different remote directory.
        """
        if relative_url is None:
            return self.__class__(self.base, self)
        else:
            return self.__class__(self.abspath(relative_url), self)

    def is_readonly(self):
        """Smart server transport can do read/write file operations."""
        return False
                                                   
    def get_smart_client(self):
        return self._client
                                                   
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
        return self._combine_paths(self._path, relpath)

    def has(self, relpath):
        """Indicate whether a remote file of the given name exists or not.

        :see: Transport.has()
        """
        resp = self._client._call('has', self._remote_path(relpath))
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
        remote = self._remote_path(relpath)
        resp = self._client._call('get', remote)
        if resp != ('ok', ):
            self._translate_error(resp, relpath)
        return StringIO(self._client._recv_bulk())

    def _serialise_optional_mode(self, mode):
        if mode is None:
            return ''
        else:
            return '%d' % mode

    def mkdir(self, relpath, mode=None):
        resp = self._client._call('mkdir', 
                                  self._remote_path(relpath), 
                                  self._serialise_optional_mode(mode))
        self._translate_error(resp)

    def put_file(self, relpath, upload_file, mode=None):
        self.put_bytes(relpath, upload_file.read(), mode)

    def put_bytes(self, relpath, upload_contents, mode=None):
        # FIXME: upload_file is probably not safe for non-ascii characters -
        # should probably just pass all parameters as length-delimited
        # strings?
        resp = self._client._call_with_upload(
            'put',
            (self._remote_path(relpath), self._serialise_optional_mode(mode)),
            upload_contents)
        self._translate_error(resp)

    def append_file(self, relpath, from_file, mode=None):
        self.append_bytes(relpath, from_file.read(), mode)
        
    def append_bytes(self, relpath, bytes, mode=None):
        resp = self._client._call_with_upload(
            'append',
            (self._remote_path(relpath), self._serialise_optional_mode(mode)),
            bytes)
        if resp[0] == 'appended':
            return int(resp[1])
        self._translate_error(resp)

    def delete(self, relpath):
        resp = self._client._call('delete', self._remote_path(relpath))
        self._translate_error(resp)

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

    def _call(self, method, *args):
        resp = self._client._call(method, *args)
        self._translate_error(resp)

    def _translate_error(self, resp, orig_path=None):
        """Raise an exception from a response"""
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
        else:
            raise errors.SmartProtocolError('unexpected smart server error: %r' % (resp,))

    def _send_tuple(self, args):
        self._client._send_tuple(args)

    def _recv_tuple(self):
        return self._client._recv_tuple()

    def disconnect(self):
        self._client.disconnect()

    def delete_tree(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def stat(self, relpath):
        resp = self._client._call('stat', self._remote_path(relpath))
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
        resp = self._client._call('list_dir',
                                  self._remote_path(relpath))
        if resp[0] == 'names':
            return [name.encode('ascii') for name in resp[1:]]
        else:
            self._translate_error(resp)

    def iter_files_recursive(self):
        resp = self._client._call('iter_files_recursive',
                                  self._remote_path(''))
        if resp[0] == 'names':
            return resp[1:]
        else:
            self._translate_error(resp)


class SmartStreamClient(SmartProtocolBase):
    """Connection to smart server over two streams"""

    def __init__(self, connect_func):
        self._connect_func = connect_func
        self._connected = False

    def __del__(self):
        self.disconnect()

    def _ensure_connection(self):
        if not self._connected:
            self._in, self._out = self._connect_func()
            self._connected = True

    def _send_tuple(self, args):
        self._ensure_connection()
        _send_tuple(self._out, args)

    def _send_bulk_data(self, body):
        self._ensure_connection()
        SmartProtocolBase._send_bulk_data(self, body)
        
    def _recv_bulk(self):
        self._ensure_connection()
        return SmartProtocolBase._recv_bulk(self)

    def _recv_tuple(self):
        self._ensure_connection()
        return SmartProtocolBase._recv_tuple(self)

    def _recv_trailer(self):
        self._ensure_connection()
        return SmartProtocolBase._recv_trailer(self)

    def disconnect(self):
        """Close connection to the server"""
        if self._connected:
            self._out.close()
            self._in.close()

    def _call(self, *args):
        self._send_tuple(args)
        return self._recv_tuple()

    def _call_with_upload(self, method, args, body):
        """Call an rpc, supplying bulk upload data.

        :param method: method name to call
        :param args: parameter args tuple
        :param body: upload body as a byte string
        """
        self._send_tuple((method,) + args)
        self._send_bulk_data(body)
        return self._recv_tuple()

    def query_version(self):
        """Return protocol version number of the server."""
        # XXX: should make sure it's empty
        self._send_tuple(('hello',))
        resp = self._recv_tuple()
        if resp == ('ok', '1'):
            return 1
        else:
            raise errors.SmartProtocolError("bad response %r" % (resp,))


class SmartTCPTransport(SmartTransport):
    """Connection to smart server over plain tcp"""

    def __init__(self, url, clone_from=None):
        super(SmartTCPTransport, self).__init__(url, clone_from)
        self._scheme, self._username, self._password, self._host, self._port, self._path = \
                transport.split_url(url)
        try:
            self._port = int(self._port)
        except (ValueError, TypeError), e:
            raise errors.InvalidURL(path=url, extra="invalid port %s" % self._port)
        self._socket = None

    def _connect_to_server(self):
        self._socket = socket.socket()
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        result = self._socket.connect_ex((self._host, int(self._port)))
        if result:
            raise errors.ConnectionError("failed to connect to %s:%d: %s" %
                    (self._host, self._port, os.strerror(result)))
        # TODO: May be more efficient to just treat them as sockets
        # throughout?  But what about pipes to ssh?...
        to_server = self._socket.makefile('w')
        from_server = self._socket.makefile('r')
        return from_server, to_server

    def disconnect(self):
        super(SmartTCPTransport, self).disconnect()
        # XXX: Is closing the socket as well as closing the files really
        # necessary?
        if self._socket is not None:
            self._socket.close()


class SmartSSHTransport(SmartTransport):
    """Connection to smart server over SSH."""

    def __init__(self, url, clone_from=None):
        # TODO: all this probably belongs in the parent class.
        super(SmartSSHTransport, self).__init__(url, clone_from)
        self._scheme, self._username, self._password, self._host, self._port, self._path = \
                transport.split_url(url)
        try:
            if self._port is not None:
                self._port = int(self._port)
        except (ValueError, TypeError), e:
            raise errors.InvalidURL(path=url, extra="invalid port %s" % self._port)

    def _connect_to_server(self):
        # XXX: don't hardcode vendor
        # XXX: cannot pass password to SSHSubprocess yet
        if self._password is not None:
            raise errors.InvalidURL("SSH smart transport doesn't handle passwords")
        self._ssh_connection = sftp.SSHSubprocess(self._host, 'openssh',
                port=self._port, user=self._username,
                command=['bzr', 'serve', '--inet'])
        return self._ssh_connection.get_filelike_channels()

    def disconnect(self):
        super(SmartSSHTransport, self).disconnect()
        self._ssh_connection.close()


def get_test_permutations():
    """Return (transport, server) permutations for testing"""
    return [(SmartTCPTransport, SmartTCPServer_for_testing)]
