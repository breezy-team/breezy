# Copyright (C) 2007 Canonical Ltd
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


from bzrlib.hooks import Hooks
from bzrlib.tests.test_ftp_transport import TestCaseWithFTPServer
from bzrlib.transport import (
    register_transport,
    unregister_transport,
    )
from bzrlib.transport.ftp import FtpTransport


class TransportHooks(Hooks):
    """Dict-mapping hook name to a list of callables for transport hooks"""

    def __init__(self):
        Hooks.__init__(self)
        # Invoked when the transport has just created a new connection.
        # The api signature is (transport, connection, credentials)
        self['_set_connection'] = []


class InstrumentedTransport(FtpTransport):
    """Instrumented transport class to test commands behavior"""

    hooks = TransportHooks()


class ConnectionHookedTransport(InstrumentedTransport):
    """Transport instrumented to inspect connections"""

    def _set_connection(self, connection, credentials):
        """Called when a new connection is created """
        super(ConnectionHookedTransport, self)._set_connection(connection,
                                                               credentials)
        for hook in self.hooks['_set_connection']:
            hook(self, connection, credentials)


class TestCaseWithConnectionHookedTransport(TestCaseWithFTPServer):

    def setUp(self):
        super(TestCaseWithConnectionHookedTransport, self).setUp()
        ConnectionHookedTransport.hooks.install_hook('_set_connection',
                                                     self.set_connection_hook)
        # Make our instrumented transport the default ftp transport
        register_transport('ftp://', ConnectionHookedTransport)

        def cleanup():
            InstrumentedTransport.hooks = TransportHooks()
            unregister_transport('ftp://', ConnectionHookedTransport)

        self.addCleanup(cleanup)
        self.connections = []

    def reset_connections(self):
        self.connections = []

    def set_connection_hook(self, transport, connection, credentials):
        self.connections.append(connection)

