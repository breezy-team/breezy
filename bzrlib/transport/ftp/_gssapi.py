# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Support for secure authentication using GSSAPI over FTP.

See RFC2228 for details.
"""

from __future__ import absolute_import

import base64, ftplib

from bzrlib import (
    errors,
    )
from bzrlib.i18n import gettext
from bzrlib.trace import (
    mutter,
    note,
    )
from bzrlib.transport.ftp import FtpTransport

try:
    import kerberos
except ImportError, e:
    mutter('failed to import kerberos lib: %s', e)
    raise errors.DependencyNotPresent('kerberos', e)

if getattr(kerberos, "authGSSClientWrap", None) is None:
    raise errors.DependencyNotPresent('kerberos',
        "missing encryption function authGSSClientWrap")


class GSSAPIFtp(ftplib.FTP):
    """Extended version of ftplib.FTP that can authenticate using GSSAPI."""

    def mic_putcmd(self, line):
        rc = kerberos.authGSSClientWrap(self.vc, base64.b64encode(line))
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

        # Used FTP response codes:
        # 235 [ADAT=base64data] - indicates that the security data exchange
        #     completed successfully.
        # 334 [ADAT=base64data] - indicates that the requested security
        #     mechanism is ok, and includes security data to be used by the
        #     client to construct the next command.
        # 335 [ADAT=base64data] - indicates that the security data is
        #     acceptable, and more is required to complete the security
        #     data exchange.

        resp = self.sendcmd('AUTH GSSAPI')
        if resp.startswith('334 '):
            rc, self.vc = kerberos.authGSSClientInit("ftp@%s" % self.host)
            if kerberos.authGSSClientStep(self.vc, "") != 1:
                while resp[:4] in ('334 ', '335 '):
                    authdata = kerberos.authGSSClientResponse(self.vc)
                    resp = self.sendcmd('ADAT ' + authdata)
                    if resp[:9] in ('235 ADAT=', '335 ADAT='):
                        rc = kerberos.authGSSClientStep(self.vc, resp[9:])
                        if not ((resp.startswith('235 ') and rc == 1) or
                                (resp.startswith('335 ') and rc == 0)):
                            raise ftplib.error_reply, resp
            note(gettext("Authenticated as %s") %
                 kerberos.authGSSClientUserName(self.vc))

            # Monkey patch ftplib
            self.putcmd = self.mic_putcmd
            self.getline = self.mic_getline
            self.sendcmd('USER ' + user)
            return resp
        mutter("Unable to use GSSAPI authentication: %s", resp)


class GSSAPIFtpTransport(FtpTransport):
    """FTP transport implementation that will try to use GSSAPI authentication.

    """

    connection_class = GSSAPIFtp

    def _login(self, connection, auth, user, password):
        """Login with GSSAPI Authentication.

        The password is used if GSSAPI Authentication is not available.

        The username and password can both be None, in which case the
        credentials specified in the URL or provided by the
        AuthenticationConfig() are used.
        """
        try:
            connection.gssapi_login(user=user)
        except ftplib.error_perm, e:
            super(GSSAPIFtpTransport, self)._login(connection, auth,
                                                   user, password)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from bzrlib.tests import ftp_server
    if ftp_server.FTPServerFeature.available():
        return [(GSSAPIFtpTransport, ftp_server.FTPTestServer)]
    else:
        return []
