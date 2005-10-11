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


class TestGetConfig(TestCase):

    def test_from_fp(self):
        config_file = StringIO(sample_config_text)
        self.failUnless(isinstance(config._get_config_parser(file=config_file),
                        ConfigParser))

    def test_calls_read_filenames(self):
        # note the monkey patching. if config access was via a class instance,
        # we would not have to - if this changes in future, be sure to stop 
        # monkey patching RBC 20051011
        oldparserclass = config.ConfigParser
        config.ConfigParser = InstrumentedConfigParser
        try:
            parser = config._get_config_parser()
        finally:
            config.ConfigParser = oldparserclass
        self.failUnless(isinstance(parser, InstrumentedConfigParser))
        self.assertEqual(parser._calls, [('read', [config.config_filename()])])


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
        if self.bzr_email is not None:
            os.environ['BZREMAIL'] = bzr_email
        if self.email is not None:
            os.environ['EMAIL'] = email
        super(TestConfigItems, self).tearDown()

    def test_user_id(self):
        config_file = StringIO(sample_config_text)
        parser = config._get_config_parser(file=config_file)
        self.assertEqual("Robert Collins <robertc@example.com>",
                         config._get_user_id(parser = parser))

    def test_absent_user_id(self):
        config_file = StringIO("")
        parser = config._get_config_parser(file=config_file)
        self.assertEqual(None,
                         config._get_user_id(parser = parser))
