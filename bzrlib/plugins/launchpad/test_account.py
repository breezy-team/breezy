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

    def test_get_lp_username_unconfigured(self):
        # Test that get_lp_username() returns None if no username has
        # been configured.
        my_config = self.setup_config('')
        self.assertEqual(None, account.get_lp_username(my_config))

    def test_get_lp_username(self):
        # Test that get_lp_username() returns the configured username
        my_config = self.setup_config(
            '[DEFAULT]\nlaunchpad_username=test_user\n')
        self.assertEqual('test_user', account.get_lp_username(my_config))

    def test_set_lp_username(self):
        # Test that set_lp_username() updates the config file.
        my_config = self.setup_config('')
        self.assertEqual(None, my_config.get_user_option('launchpad_username'))
        account.set_lp_username('test_user', my_config)
        self.assertEqual(
            'test_user', my_config.get_user_option('launchpad_username'))


class CheckAccountTests(TestCaseWithMemoryTransport):

    def test_check_lp_username_valid_user(self):
        transport = self.get_transport()
        transport.mkdir('~test_user')
        transport.put_bytes('~test_user/+sshkeys', 'some keys here')
        account.check_lp_username('test_user', transport)

    def test_check_lp_username_connection_failure(self):
        pass

    def test_check_lp_username_no_user(self):
        transport = self.get_transport()
        self.assertRaises(account.UnknownLaunchpadUsername,
                          account.check_lp_username, 'test_user', transport)

    def test_check_lp_username_no_ssh_keys(self):
        transport = self.get_transport()
        transport.mkdir('~test_user')
        transport.put_bytes('~test_user/+sshkeys', '')
        self.assertRaises(account.NoRegisteredSSHKeys,
                          account.check_lp_username, 'test_user', transport)
