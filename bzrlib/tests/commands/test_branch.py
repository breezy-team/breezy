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


import os

from bzrlib.builtins import cmd_branch
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
        # invoked when the transport is about to create or reuse
        # an ftp connection. The api signature is (transport, ftp_instance)
        self['get_FTP'] = []


class InstrumentedTransport(FtpTransport):
    """Instrumented transport class to test use by init command"""

    hooks = TransportHooks()

    def _get_FTP(self):
        """See FtpTransport._get_FTP.

        This is where we can detect if the connection is reused
        or if a new one is created. This a bit ugly, but it's the
        easiest until transport classes are refactored.
        """
        instance = super(InstrumentedTransport, self)._get_FTP()
        for hook in self.hooks['get_FTP']:
            hook(self, instance)
        return instance


class TestBranch(TestCaseWithFTPServer):

    def setUp(self):
        super(TestBranch, self).setUp()
        InstrumentedTransport.hooks.install_hook('get_FTP',
                                                 self.get_connection_hook)
        # Make our instrumented transport the default ftp transport
        register_transport('ftp://', InstrumentedTransport)

        def cleanup():
            InstrumentedTransport.hooks = TransportHooks()
            unregister_transport('ftp://', InstrumentedTransport)

        self.addCleanup(cleanup)
        self.connections = []


    def get_connection_hook(self, transport, connection):
        if connection is not None and connection not in self.connections:
            self.connections.append(connection)

    def test_branch_locally(self):
        self.make_branch_and_tree('branch')
        cmd = cmd_branch()
        cmd.run(self.get_url() + '/branch', 'local')
        self.assertEquals(1, len(self.connections))

# FIXME: Bug in ftp transport suspected, neither of the two
# cmd.run() variants can finish, we get stucked somewhere in a
# rename....

#    def test_branch_remotely(self):
#        self.make_branch_and_tree('branch')
#        cmd = cmd_branch()
#        cmd.run(self.get_url() + '/branch', self.get_url() + '/remote')
#        cmd.run('branch', self.get_url() + '/remote')
#        self.assertEquals(2, len(self.connections))

