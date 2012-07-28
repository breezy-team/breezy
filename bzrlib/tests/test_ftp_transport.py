# Copyright (C) 2006, 2007, 2009, 2010, 2011 Canonical Ltd
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

import ftplib
import getpass

from bzrlib import (
    config,
    errors,
    tests,
    transport,
    ui,
    urlutils,
    )

from bzrlib.transport import ftp

from bzrlib.tests import ftp_server


class TestCaseWithFTPServer(tests.TestCaseWithTransport):

    _test_needs_features = [ftp_server.FTPServerFeature]

    def setUp(self):
        self.transport_server = ftp_server.FTPTestServer
        super(TestCaseWithFTPServer, self).setUp()


class TestCaseAFTP(tests.TestCaseWithTransport):
    """Test aftp transport."""

    def test_aftp_degrade(self):
        t = transport.get_transport_from_url('aftp://host/path')
        self.assertTrue(t.is_active)
        parent = t.clone('..')
        self.assertTrue(parent.is_active)

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
        parsed_url = transport.ConnectedTransport._split_url(base)
        new_url = parsed_url.clone()
        new_url.user = self.user
        new_url.quoted_user = urlutils.quote(self.user)
        new_url.password = self.password
        new_url.quoted_password = urlutils.quote(self.password)
        return str(new_url)

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


class TestFTPErrorTranslation(tests.TestCase):

    def test_translate_directory_not_empty(self):
        # https://bugs.launchpad.net/bugs/528722
        
        t = ftp.FtpTransport("ftp://none/")

        try:
            raise ftplib.error_temp("Rename/move failure: Directory not empty")
        except Exception, e:
            e = self.assertRaises(errors.DirectoryNotEmpty,
                t._translate_ftp_error, e, "/path")
