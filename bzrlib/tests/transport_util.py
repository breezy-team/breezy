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
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.transport import (
    register_transport,
    register_urlparse_netloc_protocol,
    unregister_transport,
    _unregister_urlparse_netloc_protocol,
    )
from bzrlib.transport.sftp import SFTPTransport


class TransportHooks(Hooks):
    """Dict-mapping hook name to a list of callables for transport hooks"""

    def __init__(self):
        Hooks.__init__(self)
        # Invoked when the transport has just created a new connection.
        # The api signature is (transport, connection, credentials)
        self['_set_connection'] = []

_hooked_scheme = 'hooked'

class InstrumentedTransport(SFTPTransport):
    """Instrumented transport class to test commands behavior"""

    hooks = TransportHooks()

    def __init__(self, base, _from_transport=None):
        assert base.startswith(_hooked_scheme + '://')
        # Avoid SFTPTransport assertion since we use a dedicated scheme
        super(SFTPTransport, self).__init__(base,
                                            _from_transport=_from_transport)


class ConnectionHookedTransport(InstrumentedTransport):
    """Transport instrumented to inspect connections"""

    def _set_connection(self, connection, credentials):
        """Called when a new connection is created """
        super(ConnectionHookedTransport, self)._set_connection(connection,
                                                               credentials)
        for hook in self.hooks['_set_connection']:
            hook(self, connection, credentials)


class TestCaseWithConnectionHookedTransport(TestCaseWithSFTPServer):

    def setUp(self):
        register_urlparse_netloc_protocol(_hooked_scheme)
        register_transport(_hooked_scheme, ConnectionHookedTransport)

        def unregister():
            unregister_transport(_hooked_scheme, ConnectionHookedTransport)
            _unregister_urlparse_netloc_protocol(_hooked_scheme)

        self.addCleanup(unregister)
        super(TestCaseWithConnectionHookedTransport, self).setUp()
        self.reset_connections()

    def get_url(self, relpath=None):
        super_self = super(TestCaseWithConnectionHookedTransport, self)
        url = super_self.get_url(relpath)
        # Replace the sftp scheme by our own
        url = _hooked_scheme + url[len('sftp'):]
        return url

    def install_hooks(self):
        ConnectionHookedTransport.hooks.install_hook('_set_connection',
                                                     self.set_connection_hook)
        # uninstall our hooks when we are finished
        self.addCleanup(self.reset_hooks)

    def reset_hooks(self):
        InstrumentedTransport.hooks = TransportHooks()

    def reset_connections(self):
        self.connections = []

    def set_connection_hook(self, transport, connection, credentials):
        # Note: uncomment the following line and use 'bt' under pdb, that will
        # identify all the connections made including the extraneous ones.
        # import pdb; pdb.set_trace()
        self.connections.append(connection)

