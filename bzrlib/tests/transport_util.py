# Copyright (C) 2007-2010 Canonical Ltd
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

from bzrlib.tests import features

# SFTPTransport offers better performances but relies on paramiko, if paramiko
# is not available, we fallback to FtpTransport
if features.paramiko.available():
    from bzrlib.tests import test_sftp_transport
    from bzrlib.transport import sftp, Transport
    _backing_scheme = 'sftp'
    _backing_transport_class = sftp.SFTPTransport
    _backing_test_class = test_sftp_transport.TestCaseWithSFTPServer
else:
    from bzrlib.transport import ftp, Transport
    from bzrlib.tests import test_ftp_transport
    _backing_scheme = 'ftp'
    _backing_transport_class = ftp.FtpTransport
    _backing_test_class = test_ftp_transport.TestCaseWithFTPServer


class TestCaseWithConnectionHookedTransport(_backing_test_class):

    def setUp(self):
        super(TestCaseWithConnectionHookedTransport, self).setUp()
        self.reset_connections()

    def start_logging_connections(self):
        Transport.hooks.install_named_hook('post_connect',
            self.connections.append, None)

    def reset_connections(self):
        self.connections = []

