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

import base64, ftplib, getpass, socket

from bzrlib import (
    config, 
    errors,
    )
from bzrlib.trace import info, mutter
from bzrlib.transport.ftp import FtpTransport
from bzrlib.transport import register_transport_proto, register_transport

try:
    import kerberos
except ImportError, e:
    mutter('failed to import kerberos lib: %s', e)
    raise errors.DependencyNotPresent('kerberos', e)

if getattr(kerberos, "authGSSClientWrap", None) is None:
    raise errors.DependencyNotPresent('kerberos', 
                                      "missing encryption functions")


class GSSAPIFtp(ftplib.FTP):
    """Extended version of ftplib.FTP that can authenticate using GSSAPI."""

    def mic_putcmd(self, line):
        rc = kerberos.authGSSClientWrap(self.vc, 
            base64.b64encode(line), kerberos.authGSSClientUserName(self.vc))
        wrapped = kerberos.authGSSClientResponse(self.vc)
        ftplib.FTP.putcmd(self, "MIC " + wrapped)

    def mic_getline(self):
        resp = ftplib.FTP.getline(self)
        if resp[:4] != '631 ':
            raise AssertionError
        rc = kerberos.authGSSClientUnwrap(self.vc, resp[4:].strip("\r\n"))
        response = base64.b64decode(kerberos.authGSSClientResponse(self.vc))
        return response

    def gssapi_login(self, user):
        # Try GSSAPI login first
        resp = self.sendcmd('AUTH GSSAPI')
        if resp[:3] == '334':
            rc, self.vc = kerberos.authGSSClientInit("ftp@%s" % self.host)
            if kerberos.authGSSClientStep(self.vc, "") != 1:
                while resp[:3] in ('334', '335'):
                    authdata = kerberos.authGSSClientResponse(self.vc)
                    resp = self.sendcmd('ADAT ' + authdata)
                    if resp[:9] in ('235 ADAT=', '335 ADAT='):
                        rc = kerberos.authGSSClientStep(self.vc, resp[9:])
                        if not ((resp[:3] == '235' and rc == 1) or 
                                (resp[:3] == '335' and rc == 0)):
                            raise AssertionError
            info("Authenticated as %s" % kerberos.authGSSClientUserName(
                    self.vc))

            # Monkey patch ftplib
            self.putcmd = self.mic_putcmd
            self.getline = self.mic_getline
            self.sendcmd('USER ' + user)
            return resp
        mutter("Unable to use GSSAPI authentication: %s", resp)


class GSSAPIFtpTransport(FtpTransport):
    def _create_connection(self, credentials=None):
        """Create a new connection with the provided credentials.

        :param credentials: The credentials needed to establish the connection.

        :return: The created connection and its associated credentials.

        The credentials are a tuple with the username and password. The 
        password is used if GSSAPI Authentication is not available.

        The username and password can both be None, in which case the 
        credentials specified in the URL or provided by the 
        AuthenticationConfig() are used.
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
            connection = GSSAPIFtp()
            connection.connect(host=self._host, port=self._port)
            try:
                connection.gssapi_login(user=user)
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
    from bzrlib import tests
    if tests.FTPServerFeature.available():
        from bzrlib.tests import ftp_server
        return [(GSSAPIFtpTransport, ftp_server.FTPServer)]
    else:
        return []
