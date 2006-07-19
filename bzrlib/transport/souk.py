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

"""Souk: smart-server protocol.

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
# TODO: Transport should probably not implicitly connect from its constructor;
# it's quite useful to be able to deal with Transports representing locations
# without actually opening it.
#
# TODO: Better name for this.
#
# TODO: Split the actual smart server from the ssh encoding of it.


from cStringIO import StringIO
import errno
import os
import socket
import sys
import tempfile
import threading
import urllib
import urlparse

from bzrlib import bzrdir, errors, revision, transport, trace
from bzrlib.transport import sftp, local
from bzrlib.bundle.serializer import write_bundle
from bzrlib.trace import mutter

# must do this otherwise urllib can't parse the urls properly :(
for scheme in ['ssh', 'bzr', 'bzr+loopback']:
    transport.register_urlparse_netloc_protocol(scheme)
del scheme


class BzrProtocolError(errors.TransportError):
    """Generic bzr souk protocol error: %(details)s"""

    def __init__(self, details):
        self.details = details


def _recv_tuple(from_file):
    req_line = from_file.readline()
    return _decode_tuple(req_line)


def _decode_tuple(req_line):
    if req_line == None or req_line == '':
        return None
    if req_line[-1] != '\n':
        raise BzrProtocolError("request %r not terminated" % req_line)
    return tuple((a.decode('utf-8') for a in req_line[:-1].split('\1')))


def _send_tuple(to_file, args):
    to_file.write('\1'.join((a.encode('utf-8') for a in args)) + '\n')
    to_file.flush()


# TODO: this only actually accomodates a single block; possibly should support
# multiple chunks?
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
        self.souk_server = SoukServer(backing_transport)

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
        self._out.flush()

    def _send_error_and_disconnect(self, exception):
        self._send_tuple(('error', str(exception)))
        self._out.flush()
        self._out.close()
        self._in.close()

    def _serve_one_request(self):
        """Read one request from input, process, send back a response.
        
        :return: False if the server should terminate, otherwise None.
        """
        req_args = self._recv_tuple()
        if req_args == None:
            # client closed connection
            return False  # shutdown server
        try:
            response = self.souk_server.dispatch_command(req_args[0], req_args[1:])
            self._send_tuple(response.args)
            if response.body is not None:
                self._send_bulk_data(response.body)
        except errors.NoSuchFile, e:
            self._send_tuple(('enoent', e.path))
        except KeyboardInterrupt:
            raise
        except Exception, e:
            # everything else: pass to client, flush, and quit
            self._send_error_and_disconnect(e)
            return False

    def serve(self):
        """Serve requests until the client disconnects."""
        try:
            while self._serve_one_request() != False:
                pass
        except Exception, e:
            sys.stderr.write("%s terminating on exception %s\n" % (self, e))
            raise


class SoukServerResponse(object):
    """Response generated by SoukServer."""

    def __init__(self, args, body=None):
        self.args = args
        self.body = body


class SoukServer(object):
    """Protocol logic for souk.
    
    This doesn't handle serialization at all, it just processes requests and
    creates responses.
    """

    def __init__(self, backing_transport):
        self._backing_transport = backing_transport
        
    def do_hello(self):
        """Answer a version request with my version."""
        return SoukServerResponse(('bzr server', '1'))

    def do_has(self, relpath):
        r = self._backing_transport.has(relpath) and 'yes' or 'no'
        return SoukServerResponse((r,))

    def do_get(self, relpath):
        backing_file = self._backing_transport.get(relpath)
        return SoukServerResponse(('ok',), backing_file.read())

    def do_get_bundle(self, path, revision_id):
        # open transport relative to our base
        t = self._backing_transport.clone(path)
        control, extra_path = bzrdir.BzrDir.open_containing_from_transport(t)
        repo = control.open_repository()
        tmpf = tempfile.TemporaryFile()
        base_revision = revision.NULL_REVISION
        write_bundle(repo, revision_id, base_revision, tmpf)
        tmpf.seek(0)
        return SoukServerResponse((), tmpf.read())

    def dispatch_command(self, cmd, args):
        func = getattr(self, 'do_' + cmd, None)
        if func is None:
            raise BzrProtocolError("bad request %r" % (cmd,))
        return func(*args)


class SoukTCPServer(object):
    """Listens on a TCP socket and accepts connections from souk clients"""

    def __init__(self, backing_transport=None, port=0):
        """Construct a new server.

        To actually start it running, call either start_background_thread or
        serve.

        :param port: TCP port to listen on, or 0 to allocate a transient port.
        """
        if backing_transport is None:
            backing_transport = memory.MemoryTransport()
        self._server_socket = socket.socket()
        self._server_socket.bind(('127.0.0.1', port))
        self._server_socket.listen(1)
        self._server_socket.settimeout(1)
        self.backing_transport = backing_transport

    def serve(self):
        # let connections timeout so that we get a chance to terminate
        self._should_terminate = False
        while not self._should_terminate:
            try:
                self.accept_and_serve()
            except socket.timeout:
                # just check if we're asked to stop
                pass
            except socket.error, e:
                trace.warning("client disconnected: %s", e)
                pass

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%d/" % self._server_socket.getsockname()

    def accept_and_serve(self):
        conn, client_addr = self._server_socket.accept()
        from_client = conn.makefile('r')
        to_client = conn.makefile('w')
        handler = SoukStreamServer(from_client, to_client,
                self.backing_transport)
        handler.serve()

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


class SoukTCPServer_for_testing(SoukTCPServer):
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
        SoukTCPServer.__init__(self, transport.get_transport("file:///"))
        
    def setUp(self):
        """Set up server for testing"""
        self.start_background_thread()

    def tearDown(self):
        self.stop_background_thread()

    def get_url(self):
        """Return the url of the server"""
        host, port = self._server_socket.getsockname()
        return "bzr://%s:%d/%s" % (host, port, self._homedir)

    def get_bogus_url(self):
        """Return a URL which will fail to connect"""
        return 'bzr://127.0.0.1:1/'


class SoukTransport(sftp.SFTPUrlHandling):
    """Connection to a souk server.

    The connection holds references to pipes that can be used to send requests
    to the server.

    The connection has a notion of the current directory to which it's
    connected; this is incorporated in filenames passed to the server.
    
    This supports some higher-level RPC operations and can also be treated 
    like a Transport to do file-like operations.

    The connection can be made over a tcp socket, or (in future) an ssh pipe
    or a series of http requests.  There are concrete subclasses for each
    type: SoukTCPClient, etc.
    """

    def __init__(self, server_url, clone_from=None):
        super(SoukTransport, self).__init__(server_url)
        ## print 'init transport url=%r' % server_url
        if clone_from is None:
            self._connect_to_server()
        else:
            # reuse same connection
            self._to_server = clone_from._to_server
            self._from_server = clone_from._from_server

    def clone(self, relative_url):
        """Make a new SoukTransport related to me, sharing the same connection.

        This essentially opens a handle on a different remote directory.
        """
        new_path = self._combine_paths(self._path, relative_url)
        netloc = urllib.quote(self._host)
        if self._username is not None:
            netloc = '%s@%s' % (urllib.quote(self._username), netloc)
        if self._port is not None:
            netloc = '%s:%d' % (netloc, self._port)
        new_url = self._scheme + '://' + netloc + new_path
        return SoukTransport(new_url, clone_from=self)

    def is_readonly(self):
        """Souk protocol currently only supports readonly operations."""
        return True
    
    def query_version(self):
        """Return protocol version number of the server."""
        # XXX: should make sure it's empty
        self._send_tuple(('hello',))
        resp = self._recv_tuple()
        if resp == ('bzr server', '1'):
            return 1
        else:
            raise BzrProtocolError("bad response %r" % (resp,))

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
        resp = self._call('has', self._remote_path(relpath))
        if resp == ('yes', ):
            return True
        elif resp == ('no', ):
            return False
        else:
            self._translate_error(resp)

    def get(self, relpath):
        """Return file-like object reading the contents of a remote file.
        
        :see: Transport.get()
        """
        mutter("%s.get %s", self, relpath)
        remote = self._remote_path(relpath)
        mutter("  remote path: %s", remote)
        resp = self._call('get', remote)
        if resp != ('ok', ):
            self._translate_error(resp)
        body = self._recv_bulk()
        self._recv_trailer()
        ret = StringIO(body)
        ## print '  got %d bytes: %s' % (len(body), body[:30])
        return ret

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

    def append(self, relpath, from_file):
        raise errors.TransportNotPossible("writing to souk servers not supported yet")

    def delete(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def delete_tree(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def put(self, relpath, f, mode=None):
        raise errors.TransportNotPossible('readonly transport')

    def mkdir(self, relpath, mode=None):
        raise errors.TransportNotPossible('readonly transport')

    def rmdir(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def stat(self, relpath):
        raise errors.TransportNotPossible('souk does not support stat()')

    def lock_write(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def listable(self):
        return False

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        # The old RemoteBranch ignore lock for reading, so we will
        # continue that tradition and return a bogus lock object.
        class BogusLock(object):
            def __init__(self, path):
                self.path = path
            def unlock(self):
                pass
        return BogusLock(relpath)


class SoukStreamClient(SoukTransport):
    """Connection to smart server over externally provided fifos"""
    def __init__(self, from_server, to_server):
        ## super(SoukTCPClient, self).__init__('bzr://<pipe>/')
        self.base = 'bzr://<pipe>/'
        self._from_server = from_server
        self._to_server = to_server


class SoukTCPClient(SoukTransport):
    """Connection to smart server over plain tcp"""

    def __init__(self, url):
        super(SoukTCPClient, self).__init__(url)
        self._scheme, self._username, self._password, self._host, self._port, self._path = \
                transport.split_url(url)
        try:
            self._port = int(self._port)
        except (ValueError, TypeError), e:
            raise errors.InvalidURL(path=url, extra="invalid port %s" % self._port)

    def _connect_to_server(self):
        self._socket = socket.socket()
        result = self._socket.connect_ex((self._host, int(self._port)))
        if result:
            raise errors.ConnectionError("failed to connect to %s:%d: %s" %
                    (self._host, self._port, os.strerror(result)))
        # TODO: May be more efficient to just treat them as sockets
        # throughout?  But what about pipes to ssh?...
        self._to_server = self._socket.makefile('w')
        self._from_server = self._socket.makefile('r')

    def disconnect(self):
        super(SoukTCPClient, self).disconnect()
        self._socket.close()



def get_test_permutations():
    """Return (transport, server) permutations for testing"""
    return [(SoukTCPClient, SoukTCPServer_for_testing)]
