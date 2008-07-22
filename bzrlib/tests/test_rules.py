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

"""Tests for finding, parsing and searching rule-based preferences."""

import os
import sys

from bzrlib import (
    config,
    errors,
    rules,
    tests,
    )
from bzrlib.util.configobj import configobj


class TestIniBasedRulesSearcher(tests.TestCase):

    def make_searcher(self, text):
        """Make a _RulesSearcher from a string"""
        if text is None:
            lines = None
        else:
            lines = text.splitlines()
        return rules._IniBasedRulesSearcher(lines)

    def test_unknown_namespace(self):
        self.assertRaises(errors.UnknownRules, rules._IniBasedRulesSearcher,
            ["[junk]", "foo=bar"])

    def test_get_items_file_missing(self):
        rs = self.make_searcher(None)
        self.assertEquals((), rs.get_items('a.txt'))
        self.assertEquals((), rs.get_selected_items('a.txt', ['foo']))

    def test_get_items_file_empty(self):
        rs = self.make_searcher("")
        self.assertEquals((), rs.get_items('a.txt'))
        self.assertEquals((), rs.get_selected_items('a.txt', ['foo']))

    def test_get_items_from_extension_match(self):
        rs = self.make_searcher("[name *.txt]\nfoo=bar\na=True\n")
        self.assertEquals((), rs.get_items('a.py'))
        self.assertEquals((('foo', 'bar'), ('a', 'True')),
            rs.get_items('a.txt'))
        self.assertEquals((('foo', 'bar'), ('a', 'True')),
            rs.get_items('dir/a.txt'))
        self.assertEquals((('foo', 'bar'),),
            rs.get_selected_items('a.txt', ['foo']))

    def test_get_items_pathname_match(self):
        rs = self.make_searcher("[name ./a.txt]\nfoo=baz\n")
        self.assertEquals((('foo', 'baz'),),
            rs.get_items('a.txt'))
        self.assertEquals((), rs.get_items('dir/a.txt'))

    def test_get_items_match_first(self):
        rs = self.make_searcher(
            "[name ./a.txt]\nfoo=baz\n"
            "[name *.txt]\nfoo=bar\na=True\n")
        self.assertEquals((('foo', 'baz'),),
            rs.get_items('a.txt'))
        self.assertEquals((('foo', 'bar'), ('a', 'True')),
            rs.get_items('dir/a.txt'))


class TestStackedRulesSearcher(tests.TestCase):

    def make_searcher(self, text1=None, text2=None):
        """Make a _StackedRulesSearcher with 0, 1 or 2 items"""
        searchers = []
        if text1 is not None:
            searchers.append(rules._IniBasedRulesSearcher(
                text1.splitlines()))
        if text2 is not None:
            searchers.append(rules._IniBasedRulesSearcher(
                text2.splitlines()))
        return rules._StackedRulesSearcher(searchers)

    def test_stack_searching(self):
        rs = self.make_searcher(
            "[name ./a.txt]\nfoo=baz\n",
            "[name *.txt]\nfoo=bar\na=True\n")
        self.assertEquals((('foo', 'baz'),),
            rs.get_items('a.txt'))
        self.assertEquals((('foo', 'bar'), ('a', 'True')),
            rs.get_items('dir/a.txt'))


class TestRulesPath(tests.TestCase):

    def setUp(self):
        super(TestRulesPath, self).setUp()
        os.environ['HOME'] = '/home/bogus'
        if sys.platform == 'win32':
            os.environ['BZR_HOME'] = \
                r'C:\Documents and Settings\bogus\Application Data'
            self.bzr_home = \
                'C:/Documents and Settings/bogus/Application Data/bazaar/2.0'
        else:
            self.bzr_home = '/home/bogus/.bazaar'

    def test_rules_filename(self):
        self.assertEqual(rules.rules_filename(),
                         self.bzr_home + '/rules')
