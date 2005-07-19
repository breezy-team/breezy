# Copyright (C) 2004, 2005 by Canonical Ltd

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


from bzrlib.selftest import InTempDir, TestBase

class LocalTransportTest(InTempDir):
    def runTest(self):
        from bzrlib.transport import transport_test
        from bzrlib.local_transport import LocalTransport

        t = LocalTransport('.')
        transport_test(self, t)

class HttpServer(object):
    """This just encapsulates spawning and stopping
    an httpserver.
    """
    def __init__(self):
        """This just spawns a separate process to serve files from
        this directory. Call the .stop() function to kill the
        process.
        """
        from BaseHTTPServer import HTTPServer
        from SimpleHTTPServer import SimpleHTTPRequestHandler
        import os
        if hasattr(os, 'fork'):
            self.pid = os.fork()
            if self.pid != 0:
                return
        else: # How do we handle windows, which doesn't have fork?
            raise NotImplementedError('At present HttpServer cannot fork on Windows')

            # We might be able to do something like os.spawn() for the
            # python executable, and give it a simple script to run.
            # but then how do we kill it?

        try:
            self.s = HTTPServer(('', 9999), SimpleHTTPRequestHandler)
            # TODO: Is there something nicer than killing the server when done?
            self.s.serve_forever()
        except KeyboardInterrupt:
            pass
        os._exit(0)

    def stop(self):
        import os
        if self.pid is None:
            return
        if hasattr(os, 'kill'):
            import signal
            os.kill(self.pid, signal.SIGINT)
            os.waitpid(self.pid, 0)
            self.pid = None
        else:
            raise NotImplementedError('At present HttpServer cannot stop on Windows')

class HttpTransportTest(InTempDir):
    def runTest(self):
        from bzrlib.transport import transport_test_ro
        from bzrlib.http_transport import HttpTransport

        s = HttpServer()

        t = HttpTransport('http://localhost:9999/')
        transport_test_ro(self, t)

        s.stop()



TEST_CLASSES = [
    LocalTransportTest,
    HttpTransportTest
    ]
