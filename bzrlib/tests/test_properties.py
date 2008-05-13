# Copyright (C) 2008 Canonical Ltd
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

"""Tests for finding and reading the bzr properties file[s]."""

import os
import sys

from bzrlib import (
    config,
    properties,
    tests,
    )
from bzrlib.util.configobj import configobj


class TestPropertiesPath(tests.TestCase):

    def setUp(self):
        super(TestPropertiesPath, self).setUp()
        os.environ['HOME'] = '/home/bogus'
        if sys.platform == 'win32':
            os.environ['BZR_HOME'] = \
                r'C:\Documents and Settings\bogus\Application Data'
            self.bzr_home = \
                'C:/Documents and Settings/bogus/Application Data/bazaar/2.0'
        else:
            self.bzr_home = '/home/bogus/.bazaar'

    def test_properties_filename(self):
        self.assertEqual(properties.properties_filename(),
                         self.bzr_home + '/fileproperties')


class TestPropertiesProvider(tests.TestCase):

    def make_provider(self, lines):
        """Make a _PropertiesProvider from a list of strings"""
        # This works even though the API doesn't document it yet
        return properties._PropertiesProvider(lines)

    def test_get_properties_file_missing(self):
        pp = self.make_provider(None)
        self.assertEquals({}, pp.get_properties('a.txt'))
        self.assertEquals({'foo': None}, pp.get_properties('a.txt', ['foo']))

    def test_get_properties_file_empty(self):
        pp = self.make_provider([])
        self.assertEquals({}, pp.get_properties('a.txt'))
        self.assertEquals({'foo': None}, pp.get_properties('a.txt', ['foo']))

    def test_get_properties_from_extension_match(self):
        pp = self.make_provider(["[*.txt]", "foo=bar", "a=True"])
        self.assertEquals({}, pp.get_properties('a.py'))
        self.assertEquals({'foo':'bar', 'a': 'True'},
            pp.get_properties('a.txt'))
        self.assertEquals({'foo':'bar', 'a': 'True'},
            pp.get_properties('dir/a.txt'))
        self.assertEquals({'foo':'bar'},
            pp.get_properties('a.txt', ['foo']))

    def test_get_properties_pathname_match(self):
        pp = self.make_provider(["[./a.txt]", "foo=baz"])
        self.assertEquals({'foo':'baz'}, pp.get_properties('a.txt'))
        self.assertEquals({}, pp.get_properties('dir/a.txt'))

    def test_get_properties_match_first(self):
        pp = self.make_provider([
            "[./a.txt]", "foo=baz",
            "[*.txt]", "foo=bar", "a=True"])
        self.assertEquals({'foo':'baz'}, pp.get_properties('a.txt'))
        self.assertEquals({'foo':'bar', 'a': 'True'},
            pp.get_properties('dir/a.txt'))
