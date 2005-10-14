# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for finding and reading the bzr config file[s]."""
# import system imports here
from ConfigParser import ConfigParser
from cStringIO import StringIO
import os
import sys

#import bzrlib specific imports here
import bzrlib.config as config
import bzrlib.errors as errors
from bzrlib.selftest import TestCase, TestCaseInTempDir


sample_config_text = ("[DEFAULT]\n"
                      "email=Robert Collins <robertc@example.com>\n"
                      "editor=vim\n"
                      "gpg_signing_command=gnome-gpg\n")

class InstrumentedConfigParser(object):
    """A config parser look-enough-alike to record calls made to it."""

    def __init__(self):
        self._calls = []

    def read(self, filenames):
        self._calls.append(('read', filenames))


class FakeBranch(object):

    def __init__(self):
        self.base = "http://example.com/branches/demo"
        self.email = 'Robert Collins <robertc@example.net>\n'

    def controlfile(self, filename, mode):
        if filename != 'email':
            raise NotImplementedError
        if self.email is not None:
            return StringIO(self.email)
        raise errors.NoSuchFile


class InstrumentedConfig(config.Config):
    """An instrumented config that supplies stubs for template methods."""
    
    def __init__(self):
        super(InstrumentedConfig, self).__init__()
        self._calls = []

    def _get_user_id(self):
        self._calls.append('_get_user_id')
        return "Robert Collins <robert.collins@example.org>"


class TestConfig(TestCase):

    def test_constructs(self):
        config.Config()
 
    def test_no_default_editor(self):
        self.assertRaises(NotImplementedError, config.Config().get_editor)

    def test_user_email(self):
        my_config = InstrumentedConfig()
        self.assertEqual('robert.collins@example.org', my_config.user_email())
        self.assertEqual(['_get_user_id'], my_config._calls)

    def test_username(self):
        my_config = InstrumentedConfig()
        self.assertEqual('Robert Collins <robert.collins@example.org>',
                         my_config.username())
        self.assertEqual(['_get_user_id'], my_config._calls)
 

class TestConfigPath(TestCase):

    def setUp(self):
        super(TestConfigPath, self).setUp()
        self.oldenv = os.environ.get('HOME', None)
        os.environ['HOME'] = '/home/bogus'

    def tearDown(self):
        os.environ['HOME'] = self.oldenv
    
    def test_config_dir(self):
        self.assertEqual(config.config_dir(), '/home/bogus/.bazaar')

    def test_config_filename(self):
        self.assertEqual(config.config_filename(),
                         '/home/bogus/.bazaar/bazaar.conf')

    def test_branches_config_filename(self):
        self.assertEqual(config.branches_config_filename(),
                         '/home/bogus/.bazaar/branches.conf')


class TestGetConfig(TestCase):

    def test_constructs(self):
        my_config = config.GlobalConfig()

    def test_from_fp(self):
        config_file = StringIO(sample_config_text)
        my_config = config.GlobalConfig()
        self.failUnless(
            isinstance(my_config._get_config_parser(file=config_file),
                        ConfigParser))

    def test_cached(self):
        config_file = StringIO(sample_config_text)
        my_config = config.GlobalConfig()
        parser = my_config._get_config_parser(file=config_file)
        self.failUnless(my_config._get_config_parser() is parser)

    def test_calls_read_filenames(self):
        # replace the class that is constructured, to check its parameters
        oldparserclass = config.ConfigParser
        config.ConfigParser = InstrumentedConfigParser
        my_config = config.GlobalConfig()
        try:
            parser = my_config._get_config_parser()
        finally:
            config.ConfigParser = oldparserclass
        self.failUnless(isinstance(parser, InstrumentedConfigParser))
        self.assertEqual(parser._calls, [('read', [config.config_filename()])])


class TestLocationConfig(TestCase):

    def test_constructs(self):
        my_config = config.LocationConfig('http://example.com')
        self.assertRaises(TypeError, config.LocationConfig)

    def test_cached(self):
        config_file = StringIO(sample_config_text)
        my_config = config.LocationConfig('http://example.com')
        parser = my_config._get_branches_config_parser(file=config_file)
        self.failUnless(my_config._get_branches_config_parser() is parser)

    def test_branches_from_fp(self):
        config_file = StringIO(sample_config_text)
        my_config = config.LocationConfig('http://example.com')
        self.failUnless(isinstance(
            my_config._get_branches_config_parser(file=config_file),
            ConfigParser))

    def test_branch_calls_read_filenames(self):
        # replace the class that is constructured, to check its parameters
        oldparserclass = config.ConfigParser
        config.ConfigParser = InstrumentedConfigParser
        my_config = config.LocationConfig('http://www.example.com')
        try:
            parser = my_config._get_branches_config_parser()
        finally:
            config.ConfigParser = oldparserclass
        self.failUnless(isinstance(parser, InstrumentedConfigParser))
        self.assertEqual(parser._calls, [('read', [config.branches_config_filename()])])

    def test_get_global_config(self):
        my_config = config.LocationConfig('http://example.com')
        global_config = my_config._get_global_config()
        self.failUnless(isinstance(global_config, config.GlobalConfig))
        self.failUnless(global_config is my_config._get_global_config())


class TestBranchConfig(TestCaseInTempDir):

    def test_constructs(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertRaises(TypeError, config.BranchConfig)

    def test_get_location_config(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        location_config = my_config._get_location_config()
        self.assertEqual(branch.base, location_config.location)
        self.failUnless(location_config is my_config._get_location_config())


class TestConfigItems(TestCase):

    def setUp(self):
        super(TestConfigItems, self).setUp()
        self.bzr_email = os.environ.get('BZREMAIL')
        if self.bzr_email is not None:
            del os.environ['BZREMAIL']
        self.email = os.environ.get('EMAIL')
        if self.email is not None:
            del os.environ['EMAIL']
        self.oldenv = os.environ.get('HOME', None)
        os.environ['HOME'] = os.getcwd()

    def tearDown(self):
        os.environ['HOME'] = self.oldenv
        if os.environ.get('BZREMAIL') is not None:
            del os.environ['BZREMAIL']
        if self.bzr_email is not None:
            os.environ['BZREMAIL'] = bzr_email
        if self.email is not None:
            os.environ['EMAIL'] = email
        super(TestConfigItems, self).tearDown()


class TestGlobalConfigItems(TestConfigItems):

    def test_user_id(self):
        config_file = StringIO(sample_config_text)
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_config_parser(file=config_file)
        self.assertEqual("Robert Collins <robertc@example.com>",
                         my_config._get_user_id())

    def test_absent_user_id(self):
        config_file = StringIO("")
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_config_parser(file=config_file)
        self.assertEqual(None, my_config._get_user_id())

    def test_configured_editor(self):
        config_file = StringIO(sample_config_text)
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_config_parser(file=config_file)
        self.assertEqual("vim", my_config.get_editor())


#class TestLocationConfigItems(TestConfigItems):
#    
#    def test_location_username(self):
#        
#
#> signatures=check-if-available
#> signatures=require
#> signatures=ignore


class TestBranchConfigItems(TestConfigItems):

    def test_user_id(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertEqual("Robert Collins <robertc@example.net>",
                         my_config._get_user_id())
        branch.email = "John"
        self.assertEqual("John", my_config._get_user_id())

    def test_not_set_in_branch(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        branch.email = None
        config_file = StringIO(sample_config_text)
        (my_config._get_location_config().
            _get_global_config()._get_config_parser(config_file))
        self.assertEqual("Robert Collins <robertc@example.com>",
                         my_config._get_user_id())
        branch.email = "John"
        self.assertEqual("John", my_config._get_user_id())

    def test_BZREMAIL_OVERRIDES(self):
        os.environ['BZREMAIL'] = "Robert Collins <robertc@example.org>"
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertEqual("Robert Collins <robertc@example.org>",
                         my_config.username())
    
