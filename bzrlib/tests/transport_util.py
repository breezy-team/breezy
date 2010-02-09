# Copyright (C) 2007, 2009 Canonical Ltd
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

import bzrlib.hooks
from bzrlib.tests import features

# SFTPTransport offers better performances but relies on paramiko, if paramiko
# is not available, we fallback to FtpTransport
if features.paramiko.available():
    from bzrlib.tests import test_sftp_transport
    from bzrlib.transport import sftp
    _backing_scheme = 'sftp'
    _backing_transport_class = sftp.SFTPTransport
    _backing_test_class = test_sftp_transport.TestCaseWithSFTPServer
else:
    from bzrlib.transport import ftp
    from bzrlib.tests import test_ftp_transport
    _backing_scheme = 'ftp'
    _backing_transport_class = ftp.FtpTransport
    _backing_test_class = test_ftp_transport.TestCaseWithFTPServer

from bzrlib.transport import (
    ConnectedTransport,
    get_transport,
    register_transport,
    register_urlparse_netloc_protocol,
    unregister_transport,
    _unregister_urlparse_netloc_protocol,
    )



class TransportHooks(bzrlib.hooks.Hooks):
    """Dict-mapping hook name to a list of callables for transport hooks"""

    def __init__(self):
        super(TransportHooks, self).__init__()
        # Invoked when the transport has just created a new connection.
        # The api signature is (transport, connection, credentials)
        self['_set_connection'] = []

_hooked_scheme = 'hooked'

def _change_scheme_in(url, actual, desired):
    if not url.startswith(actual + '://'):
        raise AssertionError('url "%r" does not start with "%r]"'
                             % (url, actual))
    return desired + url[len(actual):]


class InstrumentedTransport(_backing_transport_class):
    """Instrumented transport class to test commands behavior"""

    hooks = TransportHooks()

    def __init__(self, base, _from_transport=None):
        if not base.startswith(_hooked_scheme + '://'):
            raise ValueError(base)
        # We need to trick the backing transport class about the scheme used
        # We'll do the reverse when we need to talk to the backing server
        fake_base = _change_scheme_in(base, _hooked_scheme, _backing_scheme)
        super(InstrumentedTransport, self).__init__(
            fake_base, _from_transport=_from_transport)
        # The following is needed to minimize the effects of our trick above
        # while retaining the best compatibility.
        self._scheme = _hooked_scheme
        base = self._unsplit_url(self._scheme,
                                 self._user, self._password,
                                 self._host, self._port,
                                 self._path)
        super(ConnectedTransport, self).__init__(base)


class ConnectionHookedTransport(InstrumentedTransport):
    """Transport instrumented to inspect connections"""

    def _set_connection(self, connection, credentials):
        """Called when a new connection is created """
        super(ConnectionHookedTransport, self)._set_connection(connection,
                                                               credentials)
        for hook in self.hooks['_set_connection']:
            hook(self, connection, credentials)


class TestCaseWithConnectionHookedTransport(_backing_test_class):

    def setUp(self):
        register_urlparse_netloc_protocol(_hooked_scheme)
        register_transport(_hooked_scheme, ConnectionHookedTransport)
        self.addCleanup(unregister_transport, _hooked_scheme,
                        ConnectionHookedTransport)
        self.addCleanup(_unregister_urlparse_netloc_protocol, _hooked_scheme)
        super(TestCaseWithConnectionHookedTransport, self).setUp()
        self.reset_connections()
        # Add the 'hooked' url to the permitted url list.
        # XXX: See TestCase.start_server. This whole module shouldn't need to
        # exist - a bug has been filed on that. once its cleanedup/removed, the
        # standard test support code will work and permit the server url
        # correctly.
        url = self.get_url()
        t = get_transport(url)
        if t.base.endswith('work/'):
            t = t.clone('../..')
        self.permit_url(t.base)

    def get_url(self, relpath=None):
        super_self = super(TestCaseWithConnectionHookedTransport, self)
        url = super_self.get_url(relpath)
        # Replace the backing scheme by our own (see
        # InstrumentedTransport.__init__)
        url = _change_scheme_in(url, _backing_scheme, _hooked_scheme)
        return url

    def start_logging_connections(self):
        self.overrideAttr(InstrumentedTransport, 'hooks', TransportHooks())
        # We preserved the hooks class attribute. Now we install our hook.
        ConnectionHookedTransport.hooks.install_named_hook(
            '_set_connection', self._collect_connection, None)

    def reset_connections(self):
        self.connections = []

    def _collect_connection(self, transport, connection, credentials):
        # Note: uncomment the following line and use 'bt' under pdb, that will
        # identify all the connections made including the extraneous ones.
        # import pdb; pdb.set_trace()
        self.connections.append(connection)

