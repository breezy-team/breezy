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
    rules,
    tests,
    )
from bzrlib.util.configobj import configobj


class TestIniBasedRulesSearcher(tests.TestCase):

    def make_searcher(self, lines):
        """Make a _RulesSearcher from a list of strings"""
        return rules._IniBasedRulesSearcher(lines)

    def test_get_items_file_missing(self):
        rs = self.make_searcher(None)
        self.assertEquals(None, rs.get_items('a.txt'))
        self.assertEquals(None, rs.get_items('a.txt', ['foo']))

    def test_get_items_file_empty(self):
        rs = self.make_searcher([])
        self.assertEquals(None, rs.get_items('a.txt'))
        self.assertEquals(None, rs.get_items('a.txt', ['foo']))

    def test_get_items_from_extension_match(self):
        rs = self.make_searcher(["[*.txt]", "foo=bar", "a=True"])
        self.assertEquals(None, rs.get_items('a.py'))
        self.assertEquals((('foo', 'bar'), ('a', 'True')),
            rs.get_items('a.txt'))
        self.assertEquals((('foo', 'bar'), ('a', 'True')),
            rs.get_items('dir/a.txt'))
        self.assertEquals((('foo', 'bar'),),
            rs.get_items('a.txt', ['foo']))

    def test_get_items_pathname_match(self):
        rs = self.make_searcher(["[./a.txt]", "foo=baz"])
        self.assertEquals((('foo', 'baz'),),
            rs.get_items('a.txt'))
        self.assertEquals(None, rs.get_items('dir/a.txt'))

    def test_get_items_match_first(self):
        rs = self.make_searcher([
            "[./a.txt]", "foo=baz",
            "[*.txt]", "foo=bar", "a=True"])
        self.assertEquals((('foo', 'baz'),),
            rs.get_items('a.txt'))
        self.assertEquals((('foo', 'bar'), ('a', 'True')),
            rs.get_items('dir/a.txt'))


class TestStackedRulesSearcher(tests.TestCase):

    def make_searcher(self, lines1=None, lines2=None):
        """Make a _StackedRulesSearcher with 0, 1 or 2 items"""
        searchers = []
        if lines1 is not None:
            searchers.append(rules._IniBasedRulesSearcher(lines1))
        if lines2 is not None:
            searchers.append(rules._IniBasedRulesSearcher(lines2))
        return rules._StackedRulesSearcher(searchers)

    def test_stack_searching(self):
        rs = self.make_searcher(
            ["[./a.txt]", "foo=baz"],
            ["[*.txt]", "foo=bar", "a=True"])
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


class TestIterSearchRules(tests.TestCaseInTempDir):

    def make_per_user_searcher(self, lines):
        """Make a _RulesSearcher from a list of strings"""
        return rules._IniBasedRulesSearcher(lines)

    def make_branch_with_rules(self, text):
        b = self.make_branch('.')
        control_files = b.control_files
        control_files.lock_write()
        try:
            control_files.put_utf8('branch.rules', text)
        finally:
            control_files.unlock()
        return b

    def test_iter_search_rules_no_branch(self):
        per_user = self.make_per_user_searcher([
            "[./a.txt]", "foo=baz",
            "[*.txt]", "foo=bar", "a=True"])
        result = list(rules.iter_search_rules(None, ['a.txt', 'dir/a.txt'],
            _default_searcher=per_user))
        self.assertEquals((('foo', 'baz'),), result[0])
        self.assertEquals((('foo', 'bar'), ('a', 'True')), result[1])

    def test_iter_search_rules_just_branch(self):
        per_user = self.make_per_user_searcher([])
        b = self.make_branch_with_rules(
            "[./a.txt]\n"
            "foo=baz\n"
            "[*.txt]\n"
            "foo=bar\n"
            "a=True\n")
        result = list(rules.iter_search_rules(b, ['a.txt', 'dir/a.txt'],
            _default_searcher=per_user))
        self.assertEquals((('foo', 'baz'),), result[0])
        self.assertEquals((('foo', 'bar'), ('a', 'True')), result[1])

    def test_iter_search_rules_branch_and_per_user(self):
        per_user = self.make_per_user_searcher([
            "[./a.txt]", "foo=baz",
            "[*.txt]", "foo=bar", "a=True"])
        b = self.make_branch_with_rules(
            "[./a.txt]\n"
            "foo=qwerty\n")
        result = list(rules.iter_search_rules(b, ['a.txt', 'dir/a.txt'],
            _default_searcher=per_user))
        self.assertEquals((('foo', 'qwerty'),), result[0])
        self.assertEquals((('foo', 'bar'), ('a', 'True')), result[1])
