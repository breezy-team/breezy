# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Base implementation of Transport over http.

There are separate implementation modules for each http client implementation.
"""

import errno
import os
from collections import deque
from cStringIO import StringIO
import re
import urlparse
import urllib
from warnings import warn

from bzrlib.transport import Transport, register_transport, Server
from bzrlib.errors import (TransportNotPossible, NoSuchFile,
                           TransportError, ConnectionError)
from bzrlib.branch import Branch
from bzrlib.trace import mutter
# TODO: load these only when running http tests
import BaseHTTPServer, SimpleHTTPServer, socket, time
import threading
from bzrlib.ui import ui_factory


def extract_auth(url, password_manager):
    """Extract auth parameters from am HTTP/HTTPS url and add them to the given
    password manager.  Return the url, minus those auth parameters (which
    confuse urllib2).
    """
    assert re.match(r'^(https?)(\+\w+)?://', url), \
            'invalid absolute url %r' % url
    scheme, netloc, path, query, fragment = urlparse.urlsplit(url)
    
    if '@' in netloc:
        auth, netloc = netloc.split('@', 1)
        if ':' in auth:
            username, password = auth.split(':', 1)
        else:
            username, password = auth, None
        if ':' in netloc:
            host = netloc.split(':', 1)[0]
        else:
            host = netloc
        username = urllib.unquote(username)
        if password is not None:
            password = urllib.unquote(password)
        else:
            password = ui_factory.get_password(prompt='HTTP %(user)@%(host) password',
                                               user=username, host=host)
        password_manager.add_password(None, host, username, password)
    url = urlparse.urlunsplit((scheme, netloc, path, query, fragment))
    return url


class HttpTransportBase(Transport):
    """Base class for http implementations.

    Does URL parsing, etc, but not any network IO.

    The protocol can be given as e.g. http+urllib://host/ to use a particular
    implementation.
    """

    # _proto: "http" or "https"
    # _qualified_proto: may have "+pycurl", etc

    def __init__(self, base):
        """Set the base path where files will be stored."""
        proto_match = re.match(r'^(https?)(\+\w+)?://', base)
        if not proto_match:
            raise AssertionError("not a http url: %r" % base)
        self._proto = proto_match.group(1)
        impl_name = proto_match.group(2)
        if impl_name:
            impl_name = impl_name[1:]
        self._impl_name = impl_name
        if base[-1] != '/':
            base = base + '/'
        super(HttpTransportBase, self).__init__(base)
        # In the future we might actually connect to the remote host
        # rather than using get_url
        # self._connection = None
        (apparent_proto, self._host,
            self._path, self._parameters,
            self._query, self._fragment) = urlparse.urlparse(self.base)
        self._qualified_proto = apparent_proto

    def abspath(self, relpath):
        """Return the full url to the given relative path.

        This can be supplied with a string or a list.

        The URL returned always has the protocol scheme originally used to 
        construct the transport, even if that includes an explicit
        implementation qualifier.
        """
        assert isinstance(relpath, basestring)
        if isinstance(relpath, unicode):
            raise errors.InvalidURL(relpath, 'paths must not be unicode.')
        if isinstance(relpath, basestring):
            relpath_parts = relpath.split('/')
        else:
            # TODO: Don't call this with an array - no magic interfaces
            relpath_parts = relpath[:]
        if len(relpath_parts) > 1:
            if relpath_parts[0] == '':
                raise ValueError("path %r within branch %r seems to be absolute"
                                 % (relpath, self._path))
            if relpath_parts[-1] == '':
                raise ValueError("path %r within branch %r seems to be a directory"
                                 % (relpath, self._path))
        basepath = self._path.split('/')
        if len(basepath) > 0 and basepath[-1] == '':
            basepath = basepath[:-1]
        for p in relpath_parts:
            if p == '..':
                if len(basepath) == 0:
                    # In most filesystems, a request for the parent
                    # of root, just returns root.
                    continue
                basepath.pop()
            elif p == '.' or p == '':
                continue # No-op
            else:
                basepath.append(p)
        # Possibly, we could use urlparse.urljoin() here, but
        # I'm concerned about when it chooses to strip the last
        # portion of the path, and when it doesn't.
        path = '/'.join(basepath)
        if path == '':
            path = '/'
        result = urlparse.urlunparse((self._qualified_proto,
                                    self._host, path, '', '', ''))
        return result

    def _real_abspath(self, relpath):
        """Produce absolute path, adjusting protocol if needed"""
        abspath = self.abspath(relpath)
        qp = self._qualified_proto
        rp = self._proto
        if self._qualified_proto != self._proto:
            abspath = rp + abspath[len(qp):]
        if not isinstance(abspath, str):
            # escaping must be done at a higher level
            abspath = abspath.encode('ascii')
        return abspath

    def has(self, relpath):
        raise NotImplementedError("has() is abstract on %r" % self)

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        code, response_file = self._get(relpath, None)
        return response_file

    def _get(self, relpath, ranges):
        """Get a file, or part of a file.

        :param relpath: Path relative to transport base URL
        :param byte_range: None to get the whole file;
            or [(start,end)] to fetch parts of a file.

        :returns: (http_code, result_file)

        Note that the current http implementations can only fetch one range at
        a time through this call.
        """
        raise NotImplementedError(self._get)

    def readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :param offsets: A list of (offset, size) tuples.
        :param return: A list or generator of (offset, data) tuples
        """
        # Ideally we would pass one big request asking for all the ranges in
        # one go; however then the server will give a multipart mime response
        # back, and we can't parse them yet.  So instead we just get one range
        # per region, and try to coallesce the regions as much as possible.
        #
        # The read-coallescing code is not quite regular enough to have a
        # single driver routine and
        # helper method in Transport.
        def do_combined_read(combined_offsets):
            # read one coalesced block
            total_size = 0
            for offset, size in combined_offsets:
                total_size += size
            mutter('readv coalesced %d reads.', len(combined_offsets))
            offset = combined_offsets[0][0]
            byte_range = (offset, offset + total_size - 1)
            code, result_file = self._get(relpath, [byte_range])
            if code == 206:
                for off, size in combined_offsets:
                    result_bytes = result_file.read(size)
                    assert len(result_bytes) == size
                    yield off, result_bytes
            elif code == 200:
                data = result_file.read(offset + total_size)[offset:offset + total_size]
                pos = 0
                for offset, size in combined_offsets:
                    yield offset, data[pos:pos + size]
                    pos += size
                del data
        if not len(offsets):
            return
        pending_offsets = deque(offsets)
        combined_offsets = []
        while len(pending_offsets):
            offset, size = pending_offsets.popleft()
            if not combined_offsets:
                combined_offsets = [[offset, size]]
            else:
                if (len (combined_offsets) < 500 and
                    combined_offsets[-1][0] + combined_offsets[-1][1] == offset):
                    # combatible offset:
                    combined_offsets.append([offset, size])
                else:
                    # incompatible, or over the threshold issue a read and yield
                    pending_offsets.appendleft((offset, size))
                    for result in do_combined_read(combined_offsets):
                        yield result
                    combined_offsets = []
        # whatever is left is a single coalesced request
        if len(combined_offsets):
            for result in do_combined_read(combined_offsets):
                yield result

    def put(self, relpath, f, mode=None):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        raise TransportNotPossible('http PUT not supported')

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        raise TransportNotPossible('http does not support mkdir()')

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        raise TransportNotPossible('http does not support rmdir()')

    def append(self, relpath, f):
        """Append the text in the file-like object into the final
        location.
        """
        raise TransportNotPossible('http does not support append()')

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        raise TransportNotPossible('http does not support copy()')

    def copy_to(self, relpaths, other, mode=None, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.

        TODO: if other is LocalTransport, is it possible to
              do better than put(get())?
        """
        # At this point HttpTransport might be able to check and see if
        # the remote location is the same, and rather than download, and
        # then upload, it could just issue a remote copy_this command.
        if isinstance(other, HttpTransportBase):
            raise TransportNotPossible('http cannot be the target of copy_to()')
        else:
            return super(HttpTransportBase, self).\
                    copy_to(relpaths, other, mode=mode, pb=pb)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise TransportNotPossible('http does not support move()')

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise TransportNotPossible('http does not support delete()')

    def is_readonly(self):
        """See Transport.is_readonly."""
        return True

    def listable(self):
        """See Transport.listable."""
        return False

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        raise TransportNotPossible('http does not support stat()')

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

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should be passed to Transport.unlock()
        """
        raise TransportNotPossible('http does not support lock_write()')

    def clone(self, offset=None):
        """Return a new HttpTransportBase with root at self.base + offset
        For now HttpTransportBase does not actually connect, so just return
        a new HttpTransportBase object.
        """
        if offset is None:
            return self.__class__(self.base)
        else:
            return self.__class__(self.abspath(offset))

#---------------- test server facilities ----------------
# TODO: load these only when running tests


class WebserverNotAvailable(Exception):
    pass


class BadWebserverPath(ValueError):
    def __str__(self):
        return 'path %s is not in %s' % self.args


class TestingHTTPRequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        self.server.test_case.log('webserver - %s - - [%s] %s "%s" "%s"',
                                  self.address_string(),
                                  self.log_date_time_string(),
                                  format % args,
                                  self.headers.get('referer', '-'),
                                  self.headers.get('user-agent', '-'))

    def handle_one_request(self):
        """Handle a single HTTP request.

        You normally don't need to override this method; see the class
        __doc__ string for information on how to handle specific HTTP
        commands such as GET and POST.

        """
        for i in xrange(1,11): # Don't try more than 10 times
            try:
                self.raw_requestline = self.rfile.readline()
            except socket.error, e:
                if e.args[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                    # omitted for now because some tests look at the log of
                    # the server and expect to see no errors.  see recent
                    # email thread. -- mbp 20051021. 
                    ## self.log_message('EAGAIN (%d) while reading from raw_requestline' % i)
                    time.sleep(0.01)
                    continue
                raise
            else:
                break
        if not self.raw_requestline:
            self.close_connection = 1
            return
        if not self.parse_request(): # An error code has been sent, just exit
            return
        mname = 'do_' + self.command
        if not hasattr(self, mname):
            self.send_error(501, "Unsupported method (%r)" % self.command)
            return
        method = getattr(self, mname)
        method()


class TestingHTTPServer(BaseHTTPServer.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, test_case):
        BaseHTTPServer.HTTPServer.__init__(self, server_address,
                                                RequestHandlerClass)
        self.test_case = test_case

class HttpServer(Server):
    """A test server for http transports."""

    # used to form the url that connects to this server
    _url_protocol = 'http'

    def _http_start(self):
        httpd = None
        httpd = TestingHTTPServer(('localhost', 0),
                                  TestingHTTPRequestHandler,
                                  self)
        host, port = httpd.socket.getsockname()
        self._http_base_url = '%s://localhost:%s/' % (self._url_protocol, port)
        self._http_starting.release()
        httpd.socket.settimeout(0.1)

        while self._http_running:
            try:
                httpd.handle_request()
            except socket.timeout:
                pass

    def _get_remote_url(self, path):
        path_parts = path.split(os.path.sep)
        if os.path.isabs(path):
            if path_parts[:len(self._local_path_parts)] != \
                   self._local_path_parts:
                raise BadWebserverPath(path, self.test_dir)
            remote_path = '/'.join(path_parts[len(self._local_path_parts):])
        else:
            remote_path = '/'.join(path_parts)

        self._http_starting.acquire()
        self._http_starting.release()
        return self._http_base_url + remote_path

    def log(self, format, *args):
        """Capture Server log output."""
        self.logs.append(format % args)

    def setUp(self):
        """See bzrlib.transport.Server.setUp."""
        self._home_dir = os.getcwdu()
        self._local_path_parts = self._home_dir.split(os.path.sep)
        self._http_starting = threading.Lock()
        self._http_starting.acquire()
        self._http_running = True
        self._http_base_url = None
        self._http_thread = threading.Thread(target=self._http_start)
        self._http_thread.setDaemon(True)
        self._http_thread.start()
        self._http_proxy = os.environ.get("http_proxy")
        if self._http_proxy is not None:
            del os.environ["http_proxy"]
        self.logs = []

    def tearDown(self):
        """See bzrlib.transport.Server.tearDown."""
        self._http_running = False
        self._http_thread.join()
        if self._http_proxy is not None:
            import os
            os.environ["http_proxy"] = self._http_proxy

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return self._get_remote_url(self._home_dir)
        
    def get_bogus_url(self):
        """See bzrlib.transport.Server.get_bogus_url."""
        # this is chosen to try to prevent trouble with proxies, wierd dns,
        # etc
        return 'http://127.0.0.1:1/'

