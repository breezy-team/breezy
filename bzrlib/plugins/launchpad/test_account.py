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

"""Tests for Launchpad user ID management functions."""

from cStringIO import StringIO

from bzrlib import config
from bzrlib.tests import TestCase, TestCaseWithMemoryTransport
from bzrlib.plugins.launchpad import account


class LaunchpadAccountTests(TestCase):

    def setup_config(self, text):
        my_config = config.GlobalConfig()
        config_file = StringIO(text)
        my_config._get_parser(config_file)
        return my_config

    def test_get_lp_login_unconfigured(self):
        # Test that get_lp_login() returns None if no username has
        # been configured.
        my_config = self.setup_config('')
        self.assertEqual(None, account.get_lp_login(my_config))

    def test_get_lp_login(self):
        # Test that get_lp_login() returns the configured username
        my_config = self.setup_config(
            '[DEFAULT]\nlaunchpad_username=test_user\n')
        self.assertEqual('test_user', account.get_lp_login(my_config))

    def test_set_lp_login(self):
        # Test that set_lp_login() updates the config file.
        my_config = self.setup_config('')
        self.assertEqual(None, my_config.get_user_option('launchpad_username'))
        account.set_lp_login('test_user', my_config)
        self.assertEqual(
            'test_user', my_config.get_user_option('launchpad_username'))


class CheckAccountTests(TestCaseWithMemoryTransport):

    def test_check_lp_login_valid_user(self):
        transport = self.get_transport()
        transport.mkdir('~test_user')
        transport.put_bytes('~test_user/+sshkeys', 'some keys here')
        account.check_lp_login('test_user', transport)

    def test_check_lp_login_no_user(self):
        transport = self.get_transport()
        self.assertRaises(account.UnknownLaunchpadUsername,
                          account.check_lp_login, 'test_user', transport)

    def test_check_lp_login_no_ssh_keys(self):
        transport = self.get_transport()
        transport.mkdir('~test_user')
        transport.put_bytes('~test_user/+sshkeys', '')
        self.assertRaises(account.NoRegisteredSSHKeys,
                          account.check_lp_login, 'test_user', transport)
