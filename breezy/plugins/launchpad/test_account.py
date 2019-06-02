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

"""Tests for Launchpad user ID management functions."""

from ... import config
from ...tests import TestCaseInTempDir, TestCaseWithMemoryTransport
from . import account


class LaunchpadAccountTests(TestCaseInTempDir):

    def test_get_lp_login_unconfigured(self):
        # Test that get_lp_login() returns None if no username has
        # been configured.
        my_config = config.MemoryStack(b'')
        self.assertEqual(None, account.get_lp_login(my_config))

    def test_get_lp_login(self):
        # Test that get_lp_login() returns the configured username
        my_config = config.MemoryStack(
            b'[DEFAULT]\nlaunchpad_username=test-user\n')
        self.assertEqual('test-user', account.get_lp_login(my_config))

    def test_set_lp_login(self):
        # Test that set_lp_login() updates the config file.
        my_config = config.MemoryStack(b'')
        self.assertEqual(None, my_config.get('launchpad_username'))
        account.set_lp_login('test-user', my_config)
        self.assertEqual(
            'test-user', my_config.get('launchpad_username'))

    def test_unknown_launchpad_username(self):
        # Test formatting of UnknownLaunchpadUsername exception
        error = account.UnknownLaunchpadUsername(user='test-user')
        self.assertEqualDiff('The user name test-user is not registered '
                             'on Launchpad.', str(error))

    def test_no_registered_ssh_keys(self):
        # Test formatting of NoRegisteredSSHKeys exception
        error = account.NoRegisteredSSHKeys(user='test-user')
        self.assertEqualDiff('The user test-user has not registered any '
                             'SSH keys with Launchpad.\n'
                             'See <https://launchpad.net/people/+me>',
                             str(error))

    def test_set_lp_login_updates_authentication_conf(self):
        self.assertIs(None, account._get_auth_user())
        account.set_lp_login('foo')
        self.assertEqual('foo', account._get_auth_user())

    def test_get_lp_login_does_not_update_for_none_user(self):
        account.get_lp_login()
        self.assertIs(None, account._get_auth_user())

    def test_get_lp_login_updates_authentication_conf(self):
        account._set_global_option('foo')
        self.assertIs(None, account._get_auth_user())
        account.get_lp_login()
        auth = config.AuthenticationConfig()
        self.assertEqual('foo', account._get_auth_user(auth))
        self.assertEqual('foo', auth.get_user('ssh', 'bazaar.launchpad.net'))
        self.assertEqual('foo', auth.get_user('ssh',
                                              'bazaar.staging.launchpad.net'))

    def test_get_lp_login_leaves_existing_credentials(self):
        auth = config.AuthenticationConfig()
        auth.set_credentials('Foo', 'bazaar.launchpad.net', 'foo', 'ssh')
        auth.set_credentials('Bar', 'bazaar.staging.launchpad.net', 'foo',
                             'ssh')
        account._set_global_option('foo')
        account.get_lp_login()
        auth = config.AuthenticationConfig()
        credentials = auth.get_credentials('ssh', 'bazaar.launchpad.net')
        self.assertEqual('Foo', credentials['name'])

    def test_get_lp_login_errors_on_mismatch(self):
        account._set_auth_user('foo')
        account._set_global_option('bar')
        e = self.assertRaises(account.MismatchedUsernames,
                              account.get_lp_login)
        self.assertEqual('breezy.conf and authentication.conf disagree about'
                         ' launchpad account name.  Please re-run launchpad-login.', str(e))


class CheckAccountTests(TestCaseWithMemoryTransport):

    def test_check_lp_login_valid_user(self):
        transport = self.get_transport()
        transport.mkdir('~test-user')
        transport.put_bytes('~test-user/+sshkeys', b'some keys here')
        account.check_lp_login('test-user', transport)

    def test_check_lp_login_no_user(self):
        transport = self.get_transport()
        self.assertRaises(account.UnknownLaunchpadUsername,
                          account.check_lp_login, 'test-user', transport)

    def test_check_lp_login_no_ssh_keys(self):
        transport = self.get_transport()
        transport.mkdir('~test-user')
        transport.put_bytes('~test-user/+sshkeys', b'')
        self.assertRaises(account.NoRegisteredSSHKeys,
                          account.check_lp_login, 'test-user', transport)
