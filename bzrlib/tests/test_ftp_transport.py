# Copyright (C) 2006 Canonical Ltd
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

from cStringIO import StringIO
import sys

from bzrlib import (
    config,
    tests,
    transport,
    ui,
    )


class TestCaseWithFTPServer(tests.TestCaseWithTransport):

    _test_needs_features = [tests.FTPServerFeature]

    def setUp(self):
        from bzrlib.tests import ftp_server
        self.transport_server = ftp_server.FTPServer
        super(TestCaseWithFTPServer, self).setUp()


class TestCaseAFTP(tests.TestCaseWithTransport):
    """Test aftp transport."""

    def test_aftp_degrade(self):
        t = transport.get_transport('aftp://host/path')
        self.failUnless(t.is_active)
        parent = t.clone('..')
        self.failUnless(parent.is_active)

        self.assertEqual('aftp://host/path', t.abspath(''))


class TestFTPServer(TestCaseWithFTPServer):

    def test_basic_exists(self):
        url = self.get_url()
        self.assertStartsWith(url, 'ftp://')

        t = self.get_transport()
        t.put_bytes('foo', 'test bytes\n')
        self.assertEqual('test bytes\n', t.get_bytes('foo'))

    def test__reconnect(self):
        t = self.get_transport()
        t.put_bytes('foo', 'test bytes\n')
        self.assertEqual('test bytes\n', t.get_bytes('foo'))
        t._reconnect()
        t.put_bytes('foo', 'test more bytes\n')
        self.assertEqual('test more bytes\n', t.get_bytes('foo'))


class TestFTPServerUI(TestCaseWithFTPServer):

    def _add_authorized_user(self, user, password):
        server = self.get_server()
        # FIXME: There should be a better way to declare authorized users and
        # passwords to the server
        authorizer = server._ftp_server.authorizer
        authorizer.secured_user = user
        authorizer.secured_password = password

    def test_prompt_for_password(self):
        t = self.get_transport()
        # Ensure that the test framework set the password
        self.assertIsNot(t._password, None)
        # Reset the password (get_url set the password to 'bar' so we
        # reset it to None in the transport before the connection).
        password = t._password
        t._password = None
        ui.ui_factory = tests.TestUIFactory(stdin=password+'\n',
                                            stdout=tests.StringIOWrapper())
        # Ask the server to check the password
        self._add_authorized_user(t._user, password)
        # Issue a request to the server to connect
        t.has('whatever/not/existing')
        # stdin should be empty (the provided password have been consumed)
        self.assertEqual('', ui.ui_factory.stdin.readline())

    def test_no_prompt_for_password_when_using_auth_config(self):
        t = self.get_transport()
        # Reset the password (get_url set the password to 'bar' so we
        # reset it to None in the transport before the connection).
        password = t._password
        t._password = None
        ui.ui_factory = tests.TestUIFactory(stdin='precious\n',
                                            stdout=tests.StringIOWrapper())
        # Ask the server to check the password
        self._add_authorized_user(t._user, password)

        # Create a config file with the right password
        conf = config.AuthenticationConfig()
        conf._get_config().update({'ftptest': {'scheme': 'ftp',
                                               'user': t._user,
                                               'password': password}})
        conf._save()
        # Issue a request to the server to connect
        t.put_bytes('foo', 'test bytes\n')
        self.assertEqual('test bytes\n', t.get_bytes('foo'))
        # stdin should have  been left untouched
        self.assertEqual('precious\n', ui.ui_factory.stdin.readline())
