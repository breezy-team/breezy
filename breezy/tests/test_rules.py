# Copyright (C) 2008-2011, 2016 Canonical Ltd
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

"""Tests for finding, parsing and searching rule-based preferences."""

import sys

from breezy import rules, tests


class TestErrors(tests.TestCase):
    def test_unknown_rules(self):
        err = rules.UnknownRules(["foo", "bar"])
        self.assertEqual("Unknown rules detected: foo, bar.", str(err))


class TestIniBasedRulesSearcher(tests.TestCase):
    def make_searcher(self, text):
        """Make a _RulesSearcher from a string."""
        if text is None:
            lines = None
        else:
            lines = text.splitlines()
        return rules._IniBasedRulesSearcher(lines)

    def test_unknown_namespace(self):
        self.assertRaises(
            rules.UnknownRules, rules._IniBasedRulesSearcher, ["[junk]", "foo=bar"]
        )

    def test_get_items_file_missing(self):
        rs = self.make_searcher(None)
        self.assertEqual((), rs.get_items("a.txt"))
        self.assertEqual((), rs.get_selected_items("a.txt", ["foo"]))
        self.assertEqual(None, rs.get_single_value("a.txt", "foo"))

    def test_get_items_file_empty(self):
        rs = self.make_searcher("")
        self.assertEqual((), rs.get_items("a.txt"))
        self.assertEqual((), rs.get_selected_items("a.txt", ["foo"]))
        self.assertEqual(None, rs.get_single_value("a.txt", "foo"))

    def test_get_items_from_extension_match(self):
        rs = self.make_searcher("[name *.txt]\nfoo=bar\na=True\n")
        self.assertEqual((), rs.get_items("a.py"))
        self.assertEqual((("foo", "bar"), ("a", "True")), rs.get_items("a.txt"))
        self.assertEqual((("foo", "bar"), ("a", "True")), rs.get_items("dir/a.txt"))
        self.assertEqual((("foo", "bar"),), rs.get_selected_items("a.txt", ["foo"]))
        self.assertEqual("bar", rs.get_single_value("a.txt", "foo"))

    def test_get_items_from_multiple_glob_match(self):
        rs = self.make_searcher("[name *.txt *.py 'x x' \"y y\"]\nfoo=bar\na=True\n")
        self.assertEqual((), rs.get_items("NEWS"))
        self.assertEqual((("foo", "bar"), ("a", "True")), rs.get_items("a.py"))
        self.assertEqual((("foo", "bar"), ("a", "True")), rs.get_items("a.txt"))
        self.assertEqual((("foo", "bar"), ("a", "True")), rs.get_items("x x"))
        self.assertEqual((("foo", "bar"), ("a", "True")), rs.get_items("y y"))
        self.assertEqual("bar", rs.get_single_value("a.txt", "foo"))

    def test_get_items_pathname_match(self):
        rs = self.make_searcher("[name ./a.txt]\nfoo=baz\n")
        self.assertEqual((("foo", "baz"),), rs.get_items("a.txt"))
        self.assertEqual("baz", rs.get_single_value("a.txt", "foo"))
        self.assertEqual((), rs.get_items("dir/a.txt"))
        self.assertEqual(None, rs.get_single_value("dir/a.txt", "foo"))

    def test_get_items_match_first(self):
        rs = self.make_searcher(
            "[name ./a.txt]\nfoo=baz\n[name *.txt]\nfoo=bar\na=True\n"
        )
        self.assertEqual((("foo", "baz"),), rs.get_items("a.txt"))
        self.assertEqual("baz", rs.get_single_value("a.txt", "foo"))
        self.assertEqual((("foo", "bar"), ("a", "True")), rs.get_items("dir/a.txt"))
        self.assertEqual("bar", rs.get_single_value("dir/a.txt", "foo"))


class TestStackedRulesSearcher(tests.TestCase):
    def make_searcher(self, text1=None, text2=None):
        """Make a _StackedRulesSearcher with 0, 1 or 2 items."""
        searchers = []
        if text1 is not None:
            searchers.append(rules._IniBasedRulesSearcher(text1.splitlines()))
        if text2 is not None:
            searchers.append(rules._IniBasedRulesSearcher(text2.splitlines()))
        return rules._StackedRulesSearcher(searchers)

    def test_stack_searching(self):
        rs = self.make_searcher(
            "[name ./a.txt]\nfoo=baz\n", "[name *.txt]\nfoo=bar\na=True\n"
        )
        self.assertEqual((("foo", "baz"),), rs.get_items("a.txt"))
        self.assertEqual("baz", rs.get_single_value("a.txt", "foo"))
        self.assertEqual(None, rs.get_single_value("a.txt", "a"))
        self.assertEqual((("foo", "bar"), ("a", "True")), rs.get_items("dir/a.txt"))
        self.assertEqual("bar", rs.get_single_value("dir/a.txt", "foo"))
        self.assertEqual("True", rs.get_single_value("dir/a.txt", "a"))


class TestRulesPath(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideEnv("HOME", "/home/bogus")
        if sys.platform == "win32":
            self.overrideEnv(
                "BRZ_HOME", r"C:\Documents and Settings\bogus\Application Data"
            )
            self.brz_home = "C:/Documents and Settings/bogus/Application Data/breezy"
        else:
            self.brz_home = "/home/bogus/.config/breezy"

    def test_rules_path(self):
        self.assertEqual(rules.rules_path(), self.brz_home + "/rules")
