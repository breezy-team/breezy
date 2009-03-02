# Copyright (C) 2009 Canonical Ltd
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
"""
FTP test server.

Based on pyftpdlib: http://code.google.com/p/pyftpdlib/
"""

import errno
import os
from pyftpdlib import ftpserver
import select
import threading


from bzrlib import (
    trace,
    transport,
    )


class AnonymousWithWriteAccessAuthorizer(ftpserver.DummyAuthorizer):

    def _check_permissions(self, username, perm):
        # Like base implementation but don't warn about write permissions
        # assigned to anonynous, since that's exactly our purpose.
        for p in perm:
            if p not in self.read_perms + self.write_perms:
                raise ftpserver.AuthorizerError('No such permission "%s"' %p)


class BzrConformingFS(ftpserver.AbstractedFS):

    def chmod(self, path, mode):
        return os.chmod(path, mode)

    def listdir(self, path):
        """List the content of a directory."""
        # XXX: Something just freaks out in asyncore if given unicode strings,
        # that may need to be revisited once unicode or at least utf-8 encoded
        # paths is better handled. -- vila 20090228
        return [str(s) for s in os.listdir(path)]

    def fs2ftp(self, fspath):
        p = ftpserver.AbstractedFS.fs2ftp(self, fspath)
        # We should never send unicode strings, they are not handled properly
        # by the stack (asynchat.async_chat.initiate_send using a buffer()
        # starting with python2.6 may be the real culprit, but converting to
        # str() here fixes the problem.  that may need to be revisited once
        # unicode or at least utf-8 encoded paths is better handled. -- vila
        # 20090228
        return str(p)

class BZRConformingFTPHandler(ftpserver.FTPHandler):

    abstracted_fs = BzrConformingFS

    def __init__(self, conn, server):
        ftpserver.FTPHandler.__init__(self, conn, server)
        self.authorizer = server.authorizer

    def ftp_SIZE(self, path):
        # bzr is overly picky here, but we want to make the test suite pass
        # first. This may need to be revisited -- vila 20090226
        line = self.fs.fs2ftp(path)
        if self.fs.isdir(self.fs.realpath(path)):
            why = "%s is a directory" % line
            self.log('FAIL SIZE "%s". %s.' % (line, why))
            self.respond("550 %s."  %why)
        else:
            ftpserver.FTPHandler.ftp_SIZE(self, path)

    def ftp_NLST(self, path):
        # bzr is overly picky here, but we want to make the test suite pass
        # first. This may need to be revisited -- vila 20090226
        line = self.fs.fs2ftp(path)
        if self.fs.isfile(self.fs.realpath(path)):
            why = "Not a directory: %s" % line
            self.log('FAIL SIZE "%s". %s.' % (line, why))
            self.respond("550 %s."  %why)
        else:
            ftpserver.FTPHandler.ftp_NLST(self, path)

    def ftp_SITE_CHMOD(self, line):
        try:
            mode, path = line.split()
            mode = int(mode, 8)
        except ValueError:
            # We catch both malformed line and malformed mode with the same
            # ValueError.
            self.respond("500 'SITE CHMOD %s': command not understood."
                         % line)
            self.log('FAIL SITE CHMOD MKD ' % line)
            return
        ftp_path = self.fs.fs2ftp(path)
        try:
            self.run_as_current_user(self.fs.chmod, self.fs.ftp2fs(path), mode)
        except OSError, err:
            why = ftpserver._strerror(err)
            self.log('FAIL SITE CHMOD 0%03o "%s". %s.' % (mode, ftp_path, why))
            self.respond('550 %s.' % why)
        else:
            self.log('OK SITE CHMOD 0%03o "%s".' % (mode, ftp_path))
            self.respond('200 SITE CHMOD succesful.')


# pyftpdlib says to define SITE commands by declaring ftp_SITE_<CMD> methods,
# but fails to recognize them.
ftpserver.proto_cmds['SITE CHMOD'] = ftpserver._CommandProperty(
    perm='w', # Best fit choice even if not exactly right (can be d, f or m too)
    auth_needed=True, arg_needed=True, check_path=False,
    help='Syntax: SITE CHMOD <SP>  octal_mode_bits file-name (chmod file)',
    )


class ftp_server(ftpserver.FTPServer):

    def __init__(self, address, handler, authorizer):
        ftpserver.FTPServer.__init__(self, address, handler)
        self.authorizer = authorizer
        # Worth backporting updstream ?
        self.addr = self.socket.getsockname()


class FTPServer(transport.Server):
    """Common code for FTP server facilities."""

    def __init__(self):
        self._root = None
        self._ftp_server = None
        self._port = None
        self._async_thread = None
        # ftp server logs
        self.logs = []
        self._ftpd_running = False

    def get_url(self):
        """Calculate an ftp url to this server."""
        return 'ftp://foo:bar@localhost:%d/' % (self._port)

    def get_bogus_url(self):
        """Return a URL which cannot be connected to."""
        return 'ftp://127.0.0.1:1/'

    def log(self, message):
        """This is used by medusa.ftp_server to log connections, etc."""
        self.logs.append(message)

    def setUp(self, vfs_server=None):
        from bzrlib.transport.local import LocalURLServer
        if not (vfs_server is None or isinstance(vfs_server, LocalURLServer)):
            raise AssertionError(
                "FTPServer currently assumes local transport, got %s"
                % vfs_server)
        self._root = os.getcwdu()

        address = ('localhost', 0) # bind to a random port
        authorizer = AnonymousWithWriteAccessAuthorizer()
        authorizer.add_user('foo', 'bar', self._root, perm='elradfmw')
        self._ftp_server = ftp_server(address, BZRConformingFTPHandler,
                                      authorizer)
        # This is hacky as hell, will not work if we need two servers working
        # at the same time, but that's the best we can do so far...
        # FIXME: At least log and logline could be overriden in the handler ?
        # -- vila 20090227
        ftpserver.log = self.log
        ftpserver.logline = self.log
        ftpserver.logerror = self.log

        self._port = self._ftp_server.socket.getsockname()[1]
        # Don't let it loop forever, or handle an infinite number of requests.
        # In this case it will run for 1000s, or 10000 requests
        self._async_thread = threading.Thread(
                target=self._run_server,)
        self._async_thread.start()

    def tearDown(self):
        """See bzrlib.transport.Server.tearDown."""
        # Tell the server to stop
        self._ftpd_running = False
        # But also close the server socket for tests that start the server but
        # never initiate a connection.
        self._ftp_server.close()
        self._async_thread.join()

    def _run_server(self):
        """Run the server until tearDown is called, shut it down properly then.
        """
        self._ftpd_running = True
        self._ftp_server.serve_forever(timeout=0.1, count=10000,
                                       until=lambda : not self._ftpd_running)
