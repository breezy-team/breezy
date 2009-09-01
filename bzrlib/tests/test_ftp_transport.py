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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from cStringIO import StringIO
import getpass
import sys

from bzrlib import (
    config,
    tests,
    transport,
    ui,
    )

from bzrlib.tests import ftp_server


class TestCaseWithFTPServer(tests.TestCaseWithTransport):

    _test_needs_features = [ftp_server.FTPServerFeature]

    def setUp(self):
        self.transport_server = ftp_server.FTPTestServer
        super(TestCaseWithFTPServer, self).setUp()


class TestCaseAFTP(tests.TestCaseWithTransport):
    """Test aftp transport."""

    def test_aftp_degrade(self):
        t = transport.get_transport('aftp://host/path')
        self.failUnless(t.is_active)
        parent = t.clone('..')
        self.failUnless(parent.is_active)

        self.assertEqual('aftp://host/path', t.abspath(''))


class TestFTPTestServer(TestCaseWithFTPServer):

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


class TestFTPTestServerUI(TestCaseWithFTPServer):

    def setUp(self):
        super(TestFTPTestServerUI, self).setUp()
        self.user = 'joe'
        self.password = 'secret'
        self.get_server().add_user(self.user, self.password)

    def get_url(self, relpath=None):
        """Overrides get_url to inject our user."""
        base = super(TestFTPTestServerUI, self).get_url(relpath)
        (scheme, user, password,
         host, port, path) = transport.ConnectedTransport._split_url(base)
        url = transport.ConnectedTransport._unsplit_url(
            scheme, self.user, self.password, host, port, path)
        return url

    def test_no_prompt_for_username(self):
        """ensure getpass.getuser() is used if there's no username in the 
        configuration.""",
        self.get_server().add_user(getpass.getuser(), self.password)
        t = self.get_transport()
        ui.ui_factory = ui.CannedInputUIFactory([self.password])
        # Issue a request to the server to connect
        t.put_bytes('foo', 'test bytes\n')
        self.assertEqual('test bytes\n', t.get_bytes('foo'))
        # Only the password should've been read
        ui.ui_factory.assert_all_input_consumed()

    def test_prompt_for_password(self):
        t = self.get_transport()
        ui.ui_factory = ui.CannedInputUIFactory([self.password])
        # Issue a request to the server to connect
        t.has('whatever/not/existing')
        # stdin should be empty (the provided password have been consumed)
        ui.ui_factory.assert_all_input_consumed()

    def test_no_prompt_for_password_when_using_auth_config(self):
        t = self.get_transport()
        ui.ui_factory = ui.CannedInputUIFactory([])
        # Create a config file with the right password
        conf = config.AuthenticationConfig()
        conf._get_config().update({'ftptest': {'scheme': 'ftp',
                                               'user': self.user,
                                               'password': self.password}})
        conf._save()
        # Issue a request to the server to connect
        t.put_bytes('foo', 'test bytes\n')
        self.assertEqual('test bytes\n', t.get_bytes('foo'))

    def test_empty_password(self):
        # Override the default user/password from setUp
        self.user = 'jim'
        self.password = ''
        self.get_server().add_user(self.user, self.password)
        t = self.get_transport()
        ui.ui_factory = ui.CannedInputUIFactory([self.password])
        # Issue a request to the server to connect
        t.has('whatever/not/existing')
        # stdin should be empty (the provided password have been consumed),
        # even if the password is empty, it's followed by a newline.
        ui.ui_factory.assert_all_input_consumed()
