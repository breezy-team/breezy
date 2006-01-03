# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import BaseHTTPServer, SimpleHTTPServer, socket, errno, time
from bzrlib.tests import TestCaseInTempDir
from bzrlib.osutils import relpath


class WebserverNotAvailable(Exception):
    pass

class TestingHTTPRequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        self.server.test_case.log("webserver - %s - - [%s] %s",
                                  self.address_string(),
                                  self.log_date_time_string(),
                                  format%args)

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


class TestCaseWithWebserver(TestCaseInTempDir):
    """Derived class that starts a localhost-only webserver
    (in addition to what TestCaseInTempDir does).

    This is useful for testing RemoteBranch.
    """

    _HTTP_PORTS = range(13000, 0x8000)

    def _http_start(self):
        import SimpleHTTPServer, BaseHTTPServer, socket, errno
        httpd = None
        for port in self._HTTP_PORTS:
            try:
                httpd = TestingHTTPServer(('localhost', port),
                                          TestingHTTPRequestHandler,
                                          self)
            except socket.error, e:
                if e.args[0] == errno.EADDRINUSE:
                    continue
                print >>sys.stderr, "Cannot run webserver :-("
                raise
            else:
                break

        if httpd is None:
            raise WebserverNotAvailable("Cannot run webserver :-( "
                                        "no free ports in range %s..%s" %
                                        (_HTTP_PORTS[0], _HTTP_PORTS[-1]))

        self._http_base_url = 'http://localhost:%s/' % port
        self._http_starting.release()
        httpd.socket.settimeout(0.1)

        while self._http_running:
            try:
                httpd.handle_request()
            except socket.timeout:
                pass

    def get_remote_url(self, path):
        import os

        if os.path.isabs(path):
            remote_path = relpath(self.test_dir, path)
        else:
            remote_path = path

        self._http_starting.acquire()
        self._http_starting.release()
        return self._http_base_url + remote_path

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        import threading, os
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

    def tearDown(self):
        self._http_running = False
        self._http_thread.join()
        if self._http_proxy is not None:
            import os
            os.environ["http_proxy"] = self._http_proxy
        TestCaseInTempDir.tearDown(self)

