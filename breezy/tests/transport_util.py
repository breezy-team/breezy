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

from . import features
from ..transport import Transport

# SFTPTransport offers better performance but relies on paramiko.
if features.paramiko.available():
    from . import test_sftp_transport
    from ..transport import sftp
    _backing_scheme = 'sftp'
    _backing_transport_class = sftp.SFTPTransport
    _backing_test_class = test_sftp_transport.TestCaseWithSFTPServer
else:
    from . import http_utils
    from ..transport.http._urllib import HttpTransport_urllib
    _backing_scheme = 'http'
    _backing_transport_class = HttpTransport_urllib
    _backing_test_class = http_utils.TestCaseWithWebserver


class TestCaseWithConnectionHookedTransport(_backing_test_class):

    def setUp(self):
        super(TestCaseWithConnectionHookedTransport, self).setUp()
        self.reset_connections()

    def start_logging_connections(self):
        Transport.hooks.install_named_hook('post_connect',
            self.connections.append, None)

    def reset_connections(self):
        self.connections = []

