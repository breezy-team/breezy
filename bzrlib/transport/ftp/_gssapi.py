# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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

"""Support for secure authentication using GSSAPI over FTP.

See RFC2228 for details.
"""

from bzrlib import config, errors
from bzrlib.trace import info, mutter
from bzrlib.transport.ftp import FtpTransport
from bzrlib.transport import register_transport_proto, register_transport

try:
    import kerberos
except ImportError, e:
    mutter('failed to import kerberos lib: %s', e)
    raise errors.DependencyNotPresent('kerberos', e)

import ftplib, getpass

class SecureFtp(ftplib.FTP):
    """Extended version of ftplib.FTP that can authenticate using GSSAPI."""
    def mic_putcmd(self, line):
        kerberos.authGSSClientWrap(
                    self.vc, line.rstrip("\r\n"), 'jelmer')
        wrapped = kerberos.authGSSClientResponse(self.vc)
        print "> " + wrapped
        ftplib.FTP.putcmd(self, "MIC " + wrapped)

    def mic_getmultiline(self):
        resp = ftplib.FTP.getmultiline(self)
        assert resp[:3] == '631'
        kerberos.authGSSClientUnwrap(self.vc, resp[4:])
        response = kerberos.authGSSClientResponse(self.vc)
        return response 

    def gssapi_login(self):
        # Try GSSAPI login first
        resp = self.sendcmd('AUTH GSSAPI')
        if resp[:3] == '334':
            rc, self.vc = kerberos.authGSSClientInit("ftp@%s" % self.host)

            kerberos.authGSSClientStep(self.vc, "")
            while resp[:3] in ('334', '335'):
                authdata = kerberos.authGSSClientResponse(self.vc)
                resp = self.sendcmd('ADAT ' + authdata)
                if resp[:3] in ('235', '335'):
                    kerberos.authGSSClientStep(self.vc, resp[9:])
            info("Authenticated as %s" % kerberos.authGSSClientUserName(
                    self.vc))
            # Monkey patch ftplib
            self.putcmd = self.mic_putcmd
            self.getmultiline = self.mic_getmultiline


class SecureFtpTransport(FtpTransport):
    def _create_connection(self, credentials=None):
        """Create a new connection with the provided credentials.

        :param credentials: The credentials needed to establish the connection.

        :return: The created connection and its associated credentials.

        The credentials are only the password as it may have been entered
        interactively by the user and may be different from the one provided
        in base url at transport creation time.
        """
        if credentials is None:
            user, password = self._user, self._password
        else:
            user, password = credentials

        auth = config.AuthenticationConfig()
        if user is None:
            user = auth.get_user('ftp', self._host, port=self._port)
            if user is None:
                # Default to local user
                user = getpass.getuser()

        mutter("Constructing FTP instance against %r" %
               ((self._host, self._port, user, '********',
                self.is_active),))
        try:
            connection = SecureFtp()
            connection.connect(host=self._host, port=self._port)
            try:
                connection.gssapi_login()
            except ftplib.error_perm, e:
                if user and user != 'anonymous' and \
                        password is None: # '' is a valid password
                    password = auth.get_password('ftp', self._host, user,
                                                 port=self._port)
                connection.login(user=user, passwd=password)
            connection.set_pasv(not self.is_active)
        except socket.error, e:
            raise errors.SocketConnectionError(self._host, self._port,
                                               msg='Unable to connect to',
                                               orig_error= e)
        except ftplib.error_perm, e:
            raise errors.TransportError(msg="Error setting up connection:"
                                        " %s" % str(e), orig_error=e)
        return connection, (user, password)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    # Dummy server to have the test suite report the number of tests
    # needing that feature. We raise UnavailableFeature from methods before
    # the test server is being used. Doing so in the setUp method has bad
    # side-effects (tearDown is never called).
    class UnavailableFTPServer(object):

        def setUp(self):
            pass

        def tearDown(self):
            pass

        def get_url(self):
            raise tests.UnavailableFeature(tests.FTPServerFeature)

        def get_bogus_url(self):
            raise tests.UnavailableFeature(tests.FTPServerFeature)

    return [(FtpTransport, UnavailableFTPServer)]
